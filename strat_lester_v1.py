import psycopg2
import pandas as pd
import numpy as np
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

sys.stdout = open('/home/tony/tekton-ai-trader/strat_lester.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── LESTER v1 — Liquidity Sweep + CHoCH + Volume (LSV) ──────────────────────
#
#  Strategy Philosophy:
#  ─────────────────────
#  Institutions don't buy at resistance or sell at support — they do the
#  opposite. They hunt the stop losses sitting just above swing highs and
#  just below swing lows, absorbing retail traders' exits to fill their own
#  large orders. Once the liquidity is taken, they reverse hard.
#
#  This strategy waits for that exact moment:
#    1. A swing high/low forms and holds for ≥ SWING_AGE candles (defined level)
#    2. Price sweeps through it (wick beyond, triggering stops)
#    3. The sweep candle CLOSES BACK on the other side (rejection — the sweep failed)
#    4. The very next candle confirms direction change (Change of Character / CHoCH)
#       by closing in the new direction with body ≥ CHOCH_BODY_ATR × ATR
#    5. Volume on the sweep candle is above average (institutional participation)
#    6. SL: beyond the sweep wick tip (if they come back here, the setup is wrong)
#    7. TP: next untested swing on the other side (clean liquidity target)
#
#  What makes this different from a simple stop-hunt setup:
#    - Volume filter: without above-average volume the sweep is retail noise
#    - CHoCH candle: we wait for momentum confirmation, not just the sweep
#    - Swing age filter: avoids sweeping fresh, untested levels
#    - Session filter: only during high-liquidity periods (no Asian drift)
#
#  This is the setup I'd look for if I were sitting at a chart.
#  — Lester
#
# ─────────────────────────────────────────────────────────────────────────────

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

BRIDGE_URL  = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY  = os.getenv("BRIDGE_KEY", "")

SCAN_INTERVAL_SEC   = 300
SIGNAL_COOLDOWN_HR  = 6
LTF_TIMEFRAME       = "15min"
HTF_TIMEFRAME       = "60min"
LTF_CANDLES         = 80
HTF_CANDLES         = 50
ATR_PERIOD          = 14

# Liquidity sweep parameters
SWING_LOOKBACK      = 20       # candles to identify swing high/low
SWING_AGE_MIN       = 5        # swing must be at least this old to be a valid level
SWEEP_BUFFER_ATR    = 0.1      # wick must extend beyond level by at least 0.1×ATR
SWEEP_CLOSE_BUFFER  = 0.3      # sweep close must return within 0.3×ATR of level

# Change of Character parameters
CHOCH_BODY_ATR      = 0.4      # CHoCH candle body must be ≥ 0.4×ATR (momentum)

# Volume filter
VOLUME_MA_PERIOD    = 20       # rolling average for volume comparison
VOLUME_MULTIPLIER   = 1.2      # sweep volume must be ≥ 1.2× average

# Session filter: London (07:00–12:00) and NY (13:00–18:00) UTC only
SESSION_HOURS_UTC   = set(range(7, 12)) | set(range(13, 18))

MIN_RR              = 1.5
MIN_SL_PIPS         = 3.0
MAX_SL_PIPS         = 200.0
CONFIDENCE_BASE     = 78
STRATEGY_NAME       = "Tekton-LSV-v1"

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
            json={"chat_id": chat_id, "text": f"🎩 *Lester Signal*\n{msg}", "parse_mode": "Markdown"},
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
        print(f"[{_ts()}] 📋 Bridge specs: {len(specs)} symbols")
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
            "SELECT timestamp, open, high, low, close, volume FROM market_data "
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
        if "volume" not in df.columns:
            df["volume"] = 1.0
        df["volume"] = df["volume"].fillna(0).replace(0, 1.0)
        return df
    except Exception as e:
        print(f"[{_ts()}] ❌ DB ({symbol} {timeframe}): {e}")
        return None

def calc_atr(df, period=ATR_PERIOD):
    high, low, prev = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def calc_volume_ma(df, period=VOLUME_MA_PERIOD):
    return df["volume"].rolling(period).mean()

def get_htf_bias(symbol):
    """
    Returns 'BUY', 'SELL', or 'NEUTRAL' based on 1H market structure.
    BUY if 1H is making higher highs and higher lows (uptrend).
    SELL if 1H is making lower highs and lower lows (downtrend).
    This prevents trading against the higher timeframe trend.
    """
    df = get_ohlc(symbol, HTF_TIMEFRAME, HTF_CANDLES)
    if df is None or len(df) < 10:
        return "NEUTRAL"
    # Simple: compare recent high/low structure
    recent = df.iloc[-10:]
    mid    = len(recent) // 2
    first_half  = recent.iloc[:mid]
    second_half = recent.iloc[mid:]
    hh = second_half["high"].max() > first_half["high"].max()
    hl = second_half["low"].min()  > first_half["low"].min()
    lh = second_half["high"].max() < first_half["high"].max()
    ll = second_half["low"].min()  < first_half["low"].min()
    if hh and hl:
        return "BUY"
    if lh and ll:
        return "SELL"
    return "NEUTRAL"

def find_swing_high(df, lookback, min_age):
    """
    Returns (index, price) of the most recent swing high in the lookback window
    that is at least min_age candles old (not the very latest action).
    """
    scan = df.iloc[-(lookback + min_age):-min_age].reset_index(drop=True)
    best = None
    for i in range(2, len(scan) - 2):
        h = scan["high"].iloc[i]
        if (h > scan["high"].iloc[i-1] and h > scan["high"].iloc[i-2]
                and h > scan["high"].iloc[i+1] and h > scan["high"].iloc[i+2]):
            if best is None or h > best[1]:
                best = (i, h)
    return best

def find_swing_low(df, lookback, min_age):
    """Returns (index, price) of the most recent significant swing low."""
    scan = df.iloc[-(lookback + min_age):-min_age].reset_index(drop=True)
    best = None
    for i in range(2, len(scan) - 2):
        l = scan["low"].iloc[i]
        if (l < scan["low"].iloc[i-1] and l < scan["low"].iloc[i-2]
                and l < scan["low"].iloc[i+1] and l < scan["low"].iloc[i+2]):
            if best is None or l < best[1]:
                best = (i, l)
    return best

def find_tp_target(df, direction, entry, sl_pips, pip_size):
    """Find the next untested swing on the other side for TP."""
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
            SELECT a.symbol FROM
              (SELECT symbol FROM market_data WHERE timeframe=%s
            GROUP BY symbol HAVING COUNT(*) > 20
               GROUP BY symbol HAVING COUNT(*) >= 40) a
            INNER JOIN
              (SELECT symbol FROM market_data WHERE timeframe=%s
               GROUP BY symbol HAVING COUNT(*) >= 20) b
            ON a.symbol = b.symbol
            ORDER BY a.symbol;
        """, (LTF_TIMEFRAME, HTF_TIMEFRAME))
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
        print(f"[{_ts()}] 🎩 SIGNAL {msg}")
        notify(msg)
        return uuid
    except Exception as e:
        print(f"[{_ts()}] ❌ insert_signal ({symbol}): {e}")
        return None


# ─── CORE STRATEGY LOGIC ──────────────────────────────────────────────────────

def scan_symbol(symbol):
    pip_size, price_scale = get_pip_info(symbol)

    df = get_ohlc(symbol, LTF_TIMEFRAME, LTF_CANDLES)
    if df is None or len(df) < SWING_LOOKBACK + SWING_AGE_MIN + 5:
        return

    atr_val = calc_atr(df)
    if atr_val <= 0:
        return

    df["vol_ma"] = calc_volume_ma(df)

    # The last two completed candles: sweep candle and CHoCH candle
    # c[-3] = sweep candle (the one that swept the level)
    # c[-2] = CHoCH candle (the confirmation candle)
    # c[-1] = current (entry on close)
    sweep_candle = df.iloc[-3]
    choch_candle = df.iloc[-2]
    vol_ma       = float(df["vol_ma"].iloc[-3])
    sweep_volume = float(sweep_candle["volume"])

    # ── Volume filter ─────────────────────────────────────────────────────────
    if vol_ma > 0 and sweep_volume < vol_ma * VOLUME_MULTIPLIER:
        return  # insufficient volume on sweep — likely retail noise

    # ── HTF bias filter ───────────────────────────────────────────────────────
    htf_bias = get_htf_bias(symbol)

    # ── BULLISH SETUP: Sweep of swing low + CHoCH up ──────────────────────────
    # Conditions:
    #   1. Swing low level exists (aged ≥ SWING_AGE_MIN candles)
    #   2. Sweep candle wick goes BELOW the swing low
    #   3. Sweep candle CLOSES BACK ABOVE the swing low (rejection)
    #   4. CHoCH candle is bullish (close > open) with body ≥ CHOCH_BODY_ATR × ATR
    #   5. HTF bias is BUY or NEUTRAL (don't fight a strong downtrend)

    if htf_bias in ("BUY", "NEUTRAL"):
        swing_low = find_swing_low(df, SWING_LOOKBACK, SWING_AGE_MIN)

        if swing_low:
            _, sl_level = swing_low
            swept_low   = sweep_candle["low"] < sl_level - atr_val * SWEEP_BUFFER_ATR
            closed_back = sweep_candle["close"] > sl_level - atr_val * SWEEP_CLOSE_BUFFER
            choch_bull  = (choch_candle["close"] > choch_candle["open"] and
                           abs(choch_candle["close"] - choch_candle["open"]) >= atr_val * CHOCH_BODY_ATR)

            if swept_low and closed_back and choch_bull:
                direction = "BUY"
                if not is_on_cooldown(symbol, direction):
                    entry    = float(df["close"].iloc[-1])
                    sl_price = sweep_candle["low"] - atr_val * 0.2  # beyond the sweep wick
                    sl_pips  = (entry - sl_price) / pip_size
                    tp_pips  = find_tp_target(df, direction, entry, sl_pips, pip_size)

                    if (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS
                            and tp_pips > 0
                            and tp_pips / sl_pips >= MIN_RR):
                        rr   = round(tp_pips / sl_pips, 2)
                        conf = min(CONFIDENCE_BASE + int(rr * 2) + (2 if htf_bias == "BUY" else 0), 93)
                        reason = (f"LSV bullish sweep low={round(sl_level/pip_size,1) if pip_size < 1 else round(sl_level,4)} "
                                  f"vol={round(sweep_volume/vol_ma,1)}×avg "
                                  f"ATR={round(atr_val/pip_size,1)}p RR={rr} HTF={htf_bias}")
                        insert_signal(symbol, direction, sl_pips, tp_pips, conf, reason)
                        return

    # ── BEARISH SETUP: Sweep of swing high + CHoCH down ───────────────────────
    if htf_bias in ("SELL", "NEUTRAL"):
        swing_high = find_swing_high(df, SWING_LOOKBACK, SWING_AGE_MIN)

        if swing_high:
            _, sh_level = swing_high
            swept_high  = sweep_candle["high"] > sh_level + atr_val * SWEEP_BUFFER_ATR
            closed_back = sweep_candle["close"] < sh_level + atr_val * SWEEP_CLOSE_BUFFER
            choch_bear  = (choch_candle["close"] < choch_candle["open"] and
                           abs(choch_candle["close"] - choch_candle["open"]) >= atr_val * CHOCH_BODY_ATR)

            if swept_high and closed_back and choch_bear:
                direction = "SELL"
                if not is_on_cooldown(symbol, direction):
                    entry    = float(df["close"].iloc[-1])
                    sl_price = sweep_candle["high"] + atr_val * 0.2
                    sl_pips  = (sl_price - entry) / pip_size
                    tp_pips  = find_tp_target(df, direction, entry, sl_pips, pip_size)

                    if (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS
                            and tp_pips > 0
                            and tp_pips / sl_pips >= MIN_RR):
                        rr   = round(tp_pips / sl_pips, 2)
                        conf = min(CONFIDENCE_BASE + int(rr * 2) + (2 if htf_bias == "SELL" else 0), 93)
                        reason = (f"LSV bearish sweep high={round(sh_level,5)} "
                                  f"vol={round(sweep_volume/vol_ma,1)}×avg "
                                  f"ATR={round(atr_val/pip_size,1)}p RR={rr} HTF={htf_bias}")
                        insert_signal(symbol, direction, sl_pips, tp_pips, conf, reason)


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

def main():
    print(f"[{_ts()}] 🎩 Lester LSV Strategy Active. [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"[{_ts()}] 🎩 Watching for liquidity sweeps with CHoCH + volume confirmation.")
    while True:
        if not is_market_open():
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 💤 MARKET CLOSED (Fri 16:00–Sun 22:00 UTC) — sleeping 5 min.")
            time.sleep(300)
            continue
        print(f"[{_ts()}] 🎩 LSV scan started")
        current_hour = datetime.utcnow().hour
        if current_hour not in SESSION_HOURS_UTC:
            print(f"[{_ts()}] ⏸ Outside London/NY session — skipping")
            time.sleep(SCAN_INTERVAL_SEC)
            continue
        try:
            symbols = get_active_symbols()
            print(f"[{_ts()}] 📊 {len(symbols)} symbols with 15min + 1H data")
            accepted = 0
            skipped  = 0
            for sym in symbols:
                try:
                    before = accepted
                    scan_symbol(sym)
                except Exception as e:
                    print(f"[{_ts()}] ⚠️ {sym}: {e}")
                    skipped += 1
            print(f"[{_ts()}] ✅ LSV scan done — {len(symbols)} scanned")
        except Exception as e:
            print(f"[{_ts()}] ❌ LSV ERROR: {e}")
        time.sleep(SCAN_INTERVAL_SEC)



def is_market_open():
    """
    Returns True if strategies should be running.
    Blackout: Friday 16:00 UTC → Sunday 22:00 UTC (matches Friday Flush window).
    """
    now = datetime.utcnow()
    wd  = now.weekday()   # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    hhmm = now.hour * 60 + now.minute

    # Friday after 16:00 UTC — stop
    if wd == 4 and hhmm >= 16 * 60:
        return False
    # All of Saturday
    if wd == 5:
        return False
    # Sunday before 22:00 UTC — still closed
    if wd == 6 and hhmm < 22 * 60:
        return False
    return True

if __name__ == "__main__":
    main()

