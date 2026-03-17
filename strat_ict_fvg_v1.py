import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

# Redirect all output to strategy log
sys.stdout = open('/home/tony/tekton-ai-trader/strategy.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

BRIDGE_URL         = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY         = os.getenv("BRIDGE_KEY", "")

SCAN_INTERVAL_SEC  = 300      # scan every 5 minutes
SIGNAL_COOLDOWN_HR = 4        # minimum hours between signals for same symbol+direction
HTF_CANDLES        = 50       # candles for 1H trend filter
LTF_CANDLES        = 60       # candles for 15min detection
FVG_LOOKBACK       = 10       # scan last N candles for a valid FVG (not just last 3)
ATR_PERIOD         = 14
ATR_MIN_RATIO      = 0.2      # FVG gap must be ≥ 20% of ATR (loosened from 30%)
MIN_SL_PIPS        = 3.0      # minimum SL in pips
MAX_SL_PIPS        = 600.0    # maximum SL in pips
TP_RATIO           = 1.8      # TP = SL × 1.8R
CONFIDENCE_BASE    = 72
SPECS_CACHE_TTL    = 300

# ─── BRIDGE SPECS CACHE ────────────────────────────────────────────────────────

_symbol_specs_cache = {}
_specs_cache_ts     = 0


def get_symbol_specs() -> dict:
    """
    Fetches pip_size and price_scale for every symbol from the bridge.
    pip_size    = 10^-(pipPosition-1)  e.g. pipPosition=5 → 0.0001
    price_scale = 10^pipPosition        e.g. pipPosition=5 → 100000
    Cached for SPECS_CACHE_TTL seconds.
    """
    global _symbol_specs_cache, _specs_cache_ts
    now = time.time()
    if _symbol_specs_cache and (now - _specs_cache_ts) < SPECS_CACHE_TTL:
        return _symbol_specs_cache

    try:
        resp = requests.get(
            f"{BRIDGE_URL}/symbols/list",
            headers={"X-Bridge-Key": BRIDGE_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data    = resp.json()
        symbols = data.get("symbols", [])

        specs = {}
        for s in symbols:
            sym_name    = s.get("name", "")
            pip_pos     = s.get("pipPosition") or s.get("digits") or 4
            pip_size    = 10 ** (-(pip_pos - 1))
            price_scale = 10 ** pip_pos
            specs[sym_name] = {
                "pip_size":    pip_size,
                "price_scale": price_scale,
                "pip_pos":     pip_pos,
            }

        _symbol_specs_cache = specs
        _specs_cache_ts     = now
        print(f"[{_ts()}] 📋 Bridge specs loaded for {len(specs)} symbols")
        return specs

    except Exception as e:
        print(f"[{_ts()}] ⚠️  Could not fetch bridge specs: {e} — using fallback")
        return {}


def get_pip_info(symbol: str) -> tuple:
    """Returns (pip_size, price_scale) — bridge live data with hardcoded fallback."""
    specs = get_symbol_specs()
    if symbol in specs:
        return specs[symbol]["pip_size"], specs[symbol]["price_scale"]
    if symbol.endswith("JPY"):
        return 0.01, 1000
    FALLBACK = {
        "XAUUSD": (0.1,  100000), "XAGUSD": (0.01, 100000),
        "XTIUSD": (0.01, 100000), "XBRUSD": (0.01, 100000),
        "US30":   (1.0,  100000), "US500":  (0.1,  100000),
        "USTEC":  (0.1,  100000), "UK100":  (1.0,  100000),
        "DE40":   (1.0,  100000), "JP225":  (1.0,  100000),
        "AUS200": (1.0,  100000), "HK50":   (1.0,  100000),
    }
    return FALLBACK.get(symbol, (0.0001, 100000))


# ─── HELPERS ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _db():
    return psycopg2.connect(**DB_PARAMS)


def notify(msg: str):
    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"🧠 *Tekton Signal*\n{msg}", "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[{_ts()}] ❌ Telegram error: {e}")


# ─── MARKET DATA ───────────────────────────────────────────────────────────────

def get_ohlc(symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
    """Fetches OHLC from DB, scales raw cTrader integers to real prices."""
    try:
        conn = _db()
        df = pd.read_sql(
            "SELECT timestamp, open, high, low, close "
            "FROM market_data WHERE symbol=%s AND timeframe=%s "
            "ORDER BY timestamp DESC LIMIT %s",
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
        print(f"[{_ts()}] ❌ DB error ({symbol} {timeframe}): {e}")
        return None


# ─── ACTIVE SYMBOLS ────────────────────────────────────────────────────────────

def get_active_symbols() -> list:
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data
            WHERE timeframe = '15min'
            GROUP BY symbol HAVING COUNT(*) >= 30
            ORDER BY symbol;
        """)
        symbols = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return symbols
    except Exception as e:
        print(f"[{_ts()}] ⚠️  get_active_symbols error: {e}")
        return ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]


# ─── COOLDOWN CHECK ────────────────────────────────────────────────────────────

def is_on_cooldown(symbol: str, direction: str) -> bool:
    """True if a signal for this symbol+direction was inserted within SIGNAL_COOLDOWN_HR hours."""
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at FROM signals
            WHERE symbol = %s AND signal_type = %s AND strategy = 'Tekton-SMC-v1'
            ORDER BY created_at DESC LIMIT 1;
        """, (symbol, direction))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return False
        age_hours = (datetime.utcnow() - row[0].replace(tzinfo=None)).total_seconds() / 3600
        return age_hours < SIGNAL_COOLDOWN_HR
    except Exception as e:
        print(f"[{_ts()}] ⚠️  Cooldown check error ({symbol}): {e}")
        return False


# ─── ATR ───────────────────────────────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    high  = df["high"]
    low   = df["low"]
    prev  = df["close"].shift(1)
    tr    = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# ─── HTF TREND FILTER ──────────────────────────────────────────────────────────

def htf_trend(symbol: str) -> str | None:
    """
    1H trend using EMA20 vs EMA50.
    Returns 'BUY', 'SELL', or None (neutral / insufficient data).
    """
    df = get_ohlc(symbol, "60min", HTF_CANDLES)
    if df is None or len(df) < 20:
        return None

    closes = df["close"]
    ema20  = closes.ewm(span=20, adjust=False).mean().iloc[-1]

    if len(df) >= 50:
        ema50 = closes.ewm(span=50, adjust=False).mean().iloc[-1]
        if ema20 > ema50:   return "BUY"
        if ema20 < ema50:   return "SELL"
        return None
    else:
        # Fewer than 50 candles — use EMA20 slope
        ema20_prev = closes.ewm(span=20, adjust=False).mean().iloc[-4]
        if ema20 > ema20_prev: return "BUY"
        if ema20 < ema20_prev: return "SELL"
        return None


# ─── SIGNAL DETECTION ──────────────────────────────────────────────────────────

def detect_signal(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    Scans the last FVG_LOOKBACK candles for any valid ICT Fair Value Gap + MSS.

    Key fixes over v1:
    - Rolls across candles [-FVG_LOOKBACK .. -3] instead of checking only iloc[-3]
      This means we find FVGs that formed earlier in the lookback window, not just
      the most recent 3 candles which almost never align on every 5-min scan.
    - Uses ATR to gate noise (gap >= ATR_MIN_RATIO × ATR)
    - Returns the STRONGEST signal found (largest gap relative to ATR)
    - SL/TP sanity gates: MIN_SL_PIPS / MAX_SL_PIPS
    """
    if len(df) < 20:
        return None

    pip_size, _ = get_pip_info(symbol)
    atr_val     = calc_atr(df)
    if atr_val <= 0 or pip_size <= 0:
        return None

    current_close = float(df["close"].iloc[-1])
    best_signal   = None
    best_gap_atr  = 0.0

    # Scan from newest to oldest within lookback window
    # i = the index of the MIDDLE candle of the 3-candle FVG pattern
    # pattern: candle[i-1], candle[i], candle[i+1]
    # FVG is the gap between candle[i-1] and candle[i+1]
    end_idx   = len(df) - 1          # latest complete candle
    start_idx = max(1, len(df) - FVG_LOOKBACK)

    for i in range(end_idx - 1, start_idx, -1):
        c_prev = df.iloc[i - 1]  # candle before gap
        c_mid  = df.iloc[i]      # middle candle (inside gap)
        c_next = df.iloc[i + 1]  # candle after gap (most recent side)

        # ── BULLISH FVG ────────────────────────────────────────────────────────
        # Gap: c_prev.high < c_next.low (price jumped up, leaving unfilled space)
        # MSS: current price is above c_prev.high (bullish break of structure)
        gap_b = float(c_next["low"]) - float(c_prev["high"])
        if (gap_b > 0
                and gap_b >= atr_val * ATR_MIN_RATIO
                and current_close > float(c_prev["high"])   # price above gap (MSS)
                and current_close > float(c_mid["high"])    # broke mid-candle high
        ):
            sl_price = float(c_prev["high"]) - (gap_b * 0.1)
            sl_pips  = round((current_close - sl_price) / pip_size, 1)
            tp_pips  = round(sl_pips * TP_RATIO, 1)

            if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
                continue

            gap_atr_ratio = gap_b / atr_val
            if gap_atr_ratio > best_gap_atr:
                best_gap_atr = gap_atr_ratio
                confidence   = CONFIDENCE_BASE
                if gap_atr_ratio >= 0.5: confidence += 8
                if gap_atr_ratio >= 1.0: confidence += 8
                age_candles  = end_idx - i  # how many candles ago the FVG formed
                if age_candles <= 2: confidence += 5  # fresher = better

                best_signal = {
                    "type":       "BUY",
                    "reason":     (f"Bullish FVG+MSS "
                                   f"(gap={round(gap_b/pip_size,1)}p "
                                   f"ATR={round(atr_val/pip_size,1)}p "
                                   f"age={age_candles}c)"),
                    "confidence": min(confidence, 95),
                    "sl_pips":    sl_pips,
                    "tp_pips":    tp_pips,
                }

        # ── BEARISH FVG ────────────────────────────────────────────────────────
        # Gap: c_prev.low > c_next.high (price dropped, leaving unfilled space above)
        # MSS: current price is below c_prev.low (bearish break of structure)
        gap_s = float(c_prev["low"]) - float(c_next["high"])
        if (gap_s > 0
                and gap_s >= atr_val * ATR_MIN_RATIO
                and current_close < float(c_prev["low"])    # price below gap (MSS)
                and current_close < float(c_mid["low"])     # broke mid-candle low
        ):
            sl_price = float(c_prev["low"]) + (gap_s * 0.1)
            sl_pips  = round((sl_price - current_close) / pip_size, 1)
            tp_pips  = round(sl_pips * TP_RATIO, 1)

            if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
                continue

            gap_atr_ratio = gap_s / atr_val
            if gap_atr_ratio > best_gap_atr:
                best_gap_atr = gap_atr_ratio
                confidence   = CONFIDENCE_BASE
                if gap_atr_ratio >= 0.5: confidence += 8
                if gap_atr_ratio >= 1.0: confidence += 8
                age_candles  = end_idx - i
                if age_candles <= 2: confidence += 5

                best_signal = {
                    "type":       "SELL",
                    "reason":     (f"Bearish FVG+MSS "
                                   f"(gap={round(gap_s/pip_size,1)}p "
                                   f"ATR={round(atr_val/pip_size,1)}p "
                                   f"age={age_candles}c)"),
                    "confidence": min(confidence, 95),
                    "sl_pips":    sl_pips,
                    "tp_pips":    tp_pips,
                }

    return best_signal


# ─── SIGNAL INSERT ─────────────────────────────────────────────────────────────

def save_signal(symbol: str, direction: str, reason: str,
                confidence: int, sl_pips: float, tp_pips: float):
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO signals
              (symbol, strategy, signal_type, timeframe, confidence_score, status, sl_pips, tp_pips)
            VALUES (%s, 'Tekton-SMC-v1', %s, '15min', %s, 'PENDING', %s, %s);
        """, (symbol, direction, int(confidence), float(sl_pips), float(tp_pips)))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[{_ts()}] 📡 SIGNAL: {direction:4s} {symbol:10s} | "
              f"SL:{sl_pips:6.1f}p TP:{tp_pips:6.1f}p | Conf:{confidence}% | {reason}")
    except Exception as e:
        print(f"[{_ts()}] ❌ Signal insert error ({symbol}): {e}")


# ─── MAIN SCAN ─────────────────────────────────────────────────────────────────

def run_scan():
    print(f"[{_ts()}] 🧠 Scan started")
    symbols = get_active_symbols()
    print(f"[{_ts()}] 📊 {len(symbols)} active symbols")

    accepted = rejected_htf = rejected_cooldown = rejected_no_setup = 0

    for symbol in symbols:
        df = get_ohlc(symbol, "15min", LTF_CANDLES)
        if df is None or len(df) < 20:
            continue

        signal = detect_signal(df, symbol)
        if signal is None:
            rejected_no_setup += 1
            continue

        direction  = signal["type"]
        sl_pips    = signal["sl_pips"]
        tp_pips    = signal["tp_pips"]
        confidence = signal["confidence"]

        # Cooldown gate
        if is_on_cooldown(symbol, direction):
            rejected_cooldown += 1
            print(f"[{_ts()}] ⏳ COOLDOWN: {symbol} {direction}")
            continue

        # HTF trend filter
        trend = htf_trend(symbol)
        if trend is not None and trend != direction:
            rejected_htf += 1
            print(f"[{_ts()}] 🚫 HTF BLOCK: {symbol} {direction} (1H={trend})")
            continue

        # HTF aligned — confidence bonus
        if trend == direction:
            confidence = min(confidence + 6, 95)

        save_signal(symbol, direction, signal["reason"], confidence, sl_pips, tp_pips)
        notify(
            f"✅ *{direction}* `{symbol}`\n"
            f"SL: `{sl_pips}p` | TP: `{tp_pips}p` | Conf: `{confidence}%`\n"
            f"_{signal['reason']}_"
        )
        accepted += 1

    print(f"[{_ts()}] ✅ Scan done — "
          f"accepted={accepted} | no_setup={rejected_no_setup} | "
          f"htf_blocked={rejected_htf} | cooldown={rejected_cooldown}")


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    notify("🛡️ Tekton Strategy Engine v1.2 started.")
    print(f"[{_ts()}] 🚀 Strategy v1.2 started — "
          f"scan={SCAN_INTERVAL_SEC}s cooldown={SIGNAL_COOLDOWN_HR}h "
          f"lookback={FVG_LOOKBACK}c ATR_min={ATR_MIN_RATIO}")
    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"[{_ts()}] 💥 Unhandled error: {e}")
        time.sleep(SCAN_INTERVAL_SEC)
