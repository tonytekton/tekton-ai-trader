import psycopg2
import pandas as pd
import numpy as np
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

sys.stdout = open('/home/tony/tekton-ai-trader/strat_rsid.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
#
#  RSI Divergence (RSID) Strategy
#  ────────────────────────────────
#  Logic:
#    1. Detect classic RSI divergence on 15min:
#       - Bullish: price makes lower low, RSI makes higher low (hidden strength)
#       - Bearish: price makes higher high, RSI makes lower high (hidden weakness)
#    2. RSI must be in extreme zone at divergence point:
#       - Bullish: RSI < 40 (oversold territory)
#       - Bearish: RSI > 60 (overbought territory)
#    3. Structural confirmation: divergence must occur at a recognised S/R level
#       (swing high/low from the last 20 candles)
#    4. SL: beyond the divergence extreme (the lower low / higher high)
#    5. TP: next structural level (swing high/low on the other side)
#
#  Why this works:
#    - Divergence = price and momentum disagreeing = early reversal warning
#    - RSI extreme filter prevents divergence trading in strong trends
#    - S/R confluence gives the setup structural context
#    - Classic setup with decades of validation across FX markets
#
# ─────────────────────────────────────────────────────────────────────────────

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

BRIDGE_URL        = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY        = os.getenv("BRIDGE_KEY", "")

SCAN_INTERVAL_SEC  = 300
SIGNAL_COOLDOWN_HR = 4
LTF_TIMEFRAME      = "15min"
LTF_CANDLES        = 80
ATR_PERIOD         = 14
RSI_PERIOD         = 14
RSI_BULL_MAX       = 40        # RSI must be below this for bullish divergence
RSI_BEAR_MIN       = 60        # RSI must be above this for bearish divergence
DIV_LOOKBACK       = 20        # candles to look back for divergence pivot pair
DIV_MIN_SEPARATION = 5         # pivot points must be at least 5 candles apart
MIN_RR             = 1.5
MIN_SL_PIPS        = 3.0
MAX_SL_PIPS        = 200.0
CONFIDENCE_BASE    = 75
STRATEGY_NAME      = "Tekton-RSID-v1"

_symbol_specs_cache = {}
_specs_cache_ts     = 0
SPECS_CACHE_TTL     = 300


def _ts():
    return datetime.now().strftime("%H:%M:%S")

def _db():
    return psycopg2.connect(**DB_PARAMS)

def notify(msg):
    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"📈 *RSID Signal*\n{msg}", "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass

def get_symbol_specs():
    global _symbol_specs_cache, _specs_cache_ts
    now = time.time()
    if _symbol_specs_cache and (now - _specs_cache_ts) < SPECS_CACHE_TTL:
        return _symbol_specs_cache
    try:
        resp = requests.get(f"{BRIDGE_URL}/symbols/list",
                            headers={"X-Bridge-Key": BRIDGE_KEY}, timeout=10)
        resp.raise_for_status()
        specs = {}
        for s in resp.json().get("symbols", []):
            sym     = s.get("name", "")
            digits      = s.get("digits") or 5
            pip_pos     = s.get("pipPosition")
            specs[sym] = {
                "pip_size":    10 ** (-pip_pos) if pip_pos else 10 ** -(digits - 1),
                "price_scale": 10 ** digits,
            }
        _symbol_specs_cache = specs
        _specs_cache_ts     = now
        print(f"[{_ts()}] 📋 Bridge specs loaded: {len(specs)} symbols")
        return specs
    except Exception as e:
        print(f"[{_ts()}] ⚠️ Bridge specs error: {e}")
        return {}

def get_pip_info(symbol):
    specs = get_symbol_specs()
    if symbol in specs:
        return specs[symbol]["pip_size"], specs[symbol]["price_scale"]
    if symbol.endswith("JPY"):
        return 0.01, 100
    return 0.0001, 10000

def get_ohlc(symbol, timeframe, limit):
    try:
        conn = _db()
        df   = pd.read_sql(
            "SELECT timestamp, open, high, low, close FROM market_data "
            "WHERE symbol=%s AND timeframe=%s ORDER BY timestamp DESC LIMIT %s",
            conn, params=(symbol, timeframe, limit)
        )
        conn.close()
        if df.empty:
            return df
        df = df.sort_values("timestamp").reset_index(drop=True)
        _, price_scale = get_pip_info(symbol)
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] / price_scale
        return df
    except Exception as e:
        print(f"[{_ts()}] ❌ DB ({symbol} {timeframe}): {e}")
        return None

def calc_atr(df, period=ATR_PERIOD):
    high, low, prev = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def calc_rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def find_swing_lows(series, lookback):
    """Returns list of (index, value) for swing lows in lookback window."""
    pivots = []
    arr = series.values[-lookback:]
    offset = len(series) - lookback
    for i in range(2, len(arr) - 2):
        if arr[i] < arr[i-1] and arr[i] < arr[i-2] and arr[i] < arr[i+1] and arr[i] < arr[i+2]:
            pivots.append((offset + i, arr[i]))
    return pivots

def find_swing_highs(series, lookback):
    """Returns list of (index, value) for swing highs in lookback window."""
    pivots = []
    arr = series.values[-lookback:]
    offset = len(series) - lookback
    for i in range(2, len(arr) - 2):
        if arr[i] > arr[i-1] and arr[i] > arr[i-2] and arr[i] > arr[i+1] and arr[i] > arr[i+2]:
            pivots.append((offset + i, arr[i]))
    return pivots

def find_tp_target(df, direction, entry, sl_pips, pip_size):
    scan = df.iloc[-40:].reset_index(drop=True)
    min_tp = sl_pips * MIN_RR
    if direction == "BUY":
        candidates = []
        for i in range(2, len(scan) - 2):
            h = scan["high"].iloc[i]
            if h > scan["high"].iloc[i-1] and h > scan["high"].iloc[i+1] and h > entry:
                candidates.append(h)
        for t in sorted(candidates):
            tp_pips = (t - entry) / pip_size
            if tp_pips >= min_tp:
                return round(tp_pips, 1)
    else:
        candidates = []
        for i in range(2, len(scan) - 2):
            l = scan["low"].iloc[i]
            if l < scan["low"].iloc[i-1] and l < scan["low"].iloc[i+1] and l < entry:
                candidates.append(l)
        for t in sorted(candidates, reverse=True):
            tp_pips = (entry - t) / pip_size
            if tp_pips >= min_tp:
                return round(tp_pips, 1)
    return round(sl_pips * MIN_RR, 1)

def get_active_symbols():
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data WHERE timeframe=%s
            GROUP BY symbol HAVING COUNT(*) > 20
            GROUP BY symbol HAVING COUNT(*) >= 40 ORDER BY symbol;
        """, (LTF_TIMEFRAME,))
        syms = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT banned_symbols FROM settings WHERE id = 1;")
        brow = cur.fetchone()
        banned = set(brow[0].split(",")) if brow and brow[0] else set()
        syms = [s for s in syms if s not in banned]
        cur.close(); conn.close()
        return syms
    except Exception as e:
        print(f"[{_ts()}] ⚠️ get_active_symbols: {e}")
        return []

def is_on_cooldown(symbol, direction):
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at FROM signals
            WHERE symbol=%s AND signal_type=%s AND strategy=%s
            ORDER BY created_at DESC LIMIT 1;
        """, (symbol, direction, STRATEGY_NAME))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row is None:
            return False
        age_h = (datetime.utcnow() - row[0].replace(tzinfo=None)).total_seconds() / 3600
        return age_h < SIGNAL_COOLDOWN_HR
    except Exception as e:
        print(f"[{_ts()}] ⚠️ Cooldown ({symbol}): {e}")
        return False

def insert_signal(symbol, direction, sl_pips, tp_pips, confidence, reason):
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO signals
              (symbol, strategy, signal_type, timeframe, confidence_score,
               sl_pips, tp_pips, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'PENDING')
            RETURNING signal_uuid;
        """, (symbol, STRATEGY_NAME, direction, LTF_TIMEFRAME,
              int(confidence), float(round(sl_pips, 1)), float(round(tp_pips, 1))))
        uuid = cur.fetchone()[0]
        conn.commit(); cur.close(); conn.close()
        msg = (f"{direction} {symbol} | SL:{sl_pips:.1f}p TP:{tp_pips:.1f}p "
               f"| Conf:{confidence}% | {reason}")
        print(f"[{_ts()}] ▶ SIGNAL {msg}")
        notify(msg)
        return uuid
    except Exception as e:
        print(f"[{_ts()}] ❌ insert_signal ({symbol}): {e}")
        return None

# ─── CORE STRATEGY LOGIC ──────────────────────────────────────────────────────

def scan_symbol(symbol):
    pip_size, price_scale = get_pip_info(symbol)

    df = get_ohlc(symbol, LTF_TIMEFRAME, LTF_CANDLES)
    if df is None or len(df) < RSI_PERIOD + DIV_LOOKBACK + 5:
        return

    atr_val = calc_atr(df)
    if atr_val <= 0:
        return

    df["rsi"] = calc_rsi(df["close"])
    current_rsi = float(df["rsi"].iloc[-1])

    # ── BULLISH DIVERGENCE ────────────────────────────────────────────────────
    # Price: lower low | RSI: higher low | RSI in oversold zone
    if current_rsi < RSI_BULL_MAX:
        price_lows = find_swing_lows(df["low"],  DIV_LOOKBACK)
        rsi_lows   = find_swing_lows(df["rsi"],  DIV_LOOKBACK)

        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            # Most recent two price swing lows
            (i1, pl1), (i2, pl2) = price_lows[-2], price_lows[-1]
            # Find corresponding RSI lows near the same candle indices
            rl1 = next((v for i, v in rsi_lows if abs(i - i1) <= 3), None)
            rl2 = next((v for i, v in rsi_lows if abs(i - i2) <= 3), None)

            if (rl1 and rl2 and
                    pl2 < pl1 and          # price: lower low
                    rl2 > rl1 and          # RSI: higher low
                    (i2 - i1) >= DIV_MIN_SEPARATION):

                # Confirmed bullish divergence
                direction = "BUY"
                if not is_on_cooldown(symbol, direction):
                    entry    = float(df["close"].iloc[-1])
                    sl_price = pl2 - atr_val * 0.3   # below the divergence low
                    sl_pips  = (entry - sl_price) / pip_size
                    tp_pips  = find_tp_target(df, direction, entry, sl_pips, pip_size)

                    if (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS
                            and tp_pips > 0
                            and tp_pips / sl_pips >= MIN_RR):
                        rr = round(tp_pips / sl_pips, 2)
                        confidence = min(CONFIDENCE_BASE + int(rr * 2), 90)
                        reason = (f"RSID bullish div RSI:{round(rl1,1)}→{round(rl2,1)} "
                                  f"price_ll ATR={round(atr_val/pip_size,1)}p RR={rr}")
                        insert_signal(symbol, direction, sl_pips, tp_pips, confidence, reason)
                        return

    # ── BEARISH DIVERGENCE ────────────────────────────────────────────────────
    # Price: higher high | RSI: lower high | RSI in overbought zone
    if current_rsi > RSI_BEAR_MIN:
        price_highs = find_swing_highs(df["high"], DIV_LOOKBACK)
        rsi_highs   = find_swing_highs(df["rsi"],  DIV_LOOKBACK)

        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            (i1, ph1), (i2, ph2) = price_highs[-2], price_highs[-1]
            rh1 = next((v for i, v in rsi_highs if abs(i - i1) <= 3), None)
            rh2 = next((v for i, v in rsi_highs if abs(i - i2) <= 3), None)

            if (rh1 and rh2 and
                    ph2 > ph1 and          # price: higher high
                    rh2 < rh1 and          # RSI: lower high
                    (i2 - i1) >= DIV_MIN_SEPARATION):

                direction = "SELL"
                if not is_on_cooldown(symbol, direction):
                    entry    = float(df["close"].iloc[-1])
                    sl_price = ph2 + atr_val * 0.3
                    sl_pips  = (sl_price - entry) / pip_size
                    tp_pips  = find_tp_target(df, direction, entry, sl_pips, pip_size)

                    if (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS
                            and tp_pips > 0
                            and tp_pips / sl_pips >= MIN_RR):
                        rr = round(tp_pips / sl_pips, 2)
                        confidence = min(CONFIDENCE_BASE + int(rr * 2), 90)
                        reason = (f"RSID bearish div RSI:{round(rh1,1)}→{round(rh2,1)} "
                                  f"price_hh ATR={round(atr_val/pip_size,1)}p RR={rr}")
                        insert_signal(symbol, direction, sl_pips, tp_pips, confidence, reason)


def main():
    print(f"[{_ts()}] 🧠 RSI Divergence Strategy Active. [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        # Weekend gate — no trading Sat/Sun
        if datetime.utcnow().weekday() >= 5:
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 💤 WEEKEND: Markets closed — sleeping 5 min.")
            time.sleep(300)
            continue
        print(f"[{_ts()}] 🧠 RSID scan started")
        try:
            symbols = get_active_symbols()
            print(f"[{_ts()}] 📊 {len(symbols)} symbols")
            for sym in symbols:
                try:
                    scan_symbol(sym)
                except Exception as e:
                    print(f"[{_ts()}] ⚠️ {sym}: {e}")
            print(f"[{_ts()}] ✅ RSID scan done")
        except Exception as e:
            print(f"[{_ts()}] ❌ RSID ERROR: {e}")
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main()

