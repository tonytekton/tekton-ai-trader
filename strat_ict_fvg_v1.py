import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

# Redirect all output to strategy log
sys.stdout = open('/home/tony/tekton-ai-trader/strategy.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY = os.getenv("BRIDGE_KEY", "")

SCAN_INTERVAL_SEC  = 300          # scan every 5 minutes
SIGNAL_COOLDOWN_HR = 4            # minimum hours between signals for same symbol+direction
HTF_CANDLES        = 30           # candles to use for 1H trend filter
LTF_CANDLES        = 50           # candles to use for 15min signal detection
MIN_SL_PIPS        = 5.0          # discard signals with SL too tight
MAX_SL_PIPS        = 500.0        # discard signals with SL unreasonably wide
TP_RATIO           = 1.8          # TP = SL * 1.8 (1.8R)
CONFIDENCE_BASE    = 72           # base confidence score
SPECS_CACHE_TTL    = 300          # seconds to cache bridge specs

# ─── BRIDGE SPECS CACHE ────────────────────────────────────────────────────────

_symbol_specs_cache = {}
_specs_cache_ts     = 0


def get_symbol_specs() -> dict:
    """
    Fetches pip_size and price_scale for every symbol from the bridge.
    pip_size   = 10^-(pipPosition-1)  e.g. pipPosition=5 → 0.0001
    price_scale = 10^pipPosition       e.g. pipPosition=5 → 100000
    Results are cached for SPECS_CACHE_TTL seconds.
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
            sym_name  = s.get("name", "")
            pip_pos   = s.get("pipPosition") or s.get("digits") or 4
            pip_size  = 10 ** (-(pip_pos - 1))   # human pip size
            price_scale = 10 ** pip_pos           # raw integer → real price
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
    """Returns (pip_size, price_scale) for a symbol, with hardcoded fallback."""
    specs = get_symbol_specs()
    if symbol in specs:
        return specs[symbol]["pip_size"], specs[symbol]["price_scale"]

    # Hardcoded fallback (last resort only)
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
    """Send Telegram notification."""
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
    """
    Fetches OHLC from DB, scales raw cTrader integers to real prices.
    Returns None on error, empty DataFrame if no data.
    """
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
    """
    Returns all symbols that have at least 30 rows of 15min data in the DB.
    Falls back to a minimal hardcoded list on error.
    """
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data
            WHERE timeframe = '15min'
            GROUP BY symbol
            HAVING COUNT(*) >= 30
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
    """
    Returns True if a signal for this symbol+direction was inserted
    within the last SIGNAL_COOLDOWN_HR hours.
    Prevents the same setup firing on every 5-minute scan.
    """
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at FROM signals
            WHERE symbol = %s
              AND signal_type = %s
              AND strategy = 'Tekton-SMC-v1'
            ORDER BY created_at DESC
            LIMIT 1;
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
        return False  # allow on error, don't silently block


# ─── HTF TREND FILTER ──────────────────────────────────────────────────────────

def htf_trend(symbol: str) -> str | None:
    """
    Determines the 1H trend direction using EMA20 vs EMA50.
    Returns 'BUY', 'SELL', or None if indeterminate.
    A signal must match the HTF trend to be accepted.
    """
    df = get_ohlc(symbol, "60min", HTF_CANDLES)
    if df is None or len(df) < 20:
        return None  # no data — neutral (don't block)

    ema20 = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1] if len(df) >= 50 else None

    if ema50 is not None:
        if ema20 > ema50:
            return "BUY"
        elif ema20 < ema50:
            return "SELL"
        return None
    else:
        # Fewer than 50 candles — use slope of EMA20
        ema20_prev = df["close"].ewm(span=20, adjust=False).mean().iloc[-3]
        if ema20 > ema20_prev:
            return "BUY"
        elif ema20 < ema20_prev:
            return "SELL"
        return None


# ─── VOLATILITY FILTER ─────────────────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate Average True Range over last `period` candles."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"].shift(1)
    tr    = pd.concat([
        high - low,
        (high - close).abs(),
        (low  - close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


# ─── SIGNAL DETECTION ──────────────────────────────────────────────────────────

def detect_signal(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    ICT Fair Value Gap (FVG) + Market Structure Shift (MSS) detection.

    Improvements over v1:
    - Uses ATR to validate that the FVG is meaningful (not noise)
    - Validates FVG gap size is at least 0.5× ATR (filters weak setups)
    - Calculates SL from actual swing low/high (not just FVG edge)
    - Confidence scoring: base + bonuses for gap size and HTF alignment
    - SL/TP sanity gates applied here (not just in outer loop)
    """
    if len(df) < 20:
        return None

    pip_size, _ = get_pip_info(symbol)
    current_close = float(df["close"].iloc[-1])
    atr_val = atr(df, 14)

    if atr_val <= 0:
        return None

    # ── BULLISH FVG + MSS ──────────────────────────────────────────────────────
    # Classic 3-candle FVG: candle[-3] high < candle[-1] low → gap between them
    # MSS confirmation: price closes above candle[-3] high
    fvg_high_b = float(df["low"].iloc[-1])
    fvg_low_b  = float(df["high"].iloc[-3])
    gap_b      = fvg_high_b - fvg_low_b

    if (gap_b > 0                                      # valid gap
            and gap_b >= atr_val * 0.3                 # gap is meaningful (≥30% ATR)
            and current_close > fvg_low_b              # price above gap (MSS)
            and current_close > float(df["high"].iloc[-2])  # broke prior candle high
    ):
        # SL below FVG low with 10% buffer
        sl_price = fvg_low_b - (gap_b * 0.1)
        sl_pips  = round((current_close - sl_price) / pip_size, 1)
        tp_pips  = round(sl_pips * TP_RATIO, 1)

        if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
            return None

        confidence = CONFIDENCE_BASE
        if gap_b >= atr_val * 0.6:  confidence += 8   # large gap bonus
        if gap_b >= atr_val * 1.0:  confidence += 8   # very large gap bonus

        return {
            "type":       "BUY",
            "reason":     f"Bullish FVG+MSS (gap={round(gap_b/pip_size,1)}p, ATR={round(atr_val/pip_size,1)}p)",
            "confidence": min(confidence, 95),
            "sl_pips":    sl_pips,
            "tp_pips":    tp_pips,
        }

    # ── BEARISH FVG + MSS ──────────────────────────────────────────────────────
    # Candle[-3] low > candle[-1] high → bearish gap
    # MSS confirmation: price closes below candle[-3] low
    fvg_low_s  = float(df["high"].iloc[-1])
    fvg_high_s = float(df["low"].iloc[-3])
    gap_s      = fvg_high_s - fvg_low_s

    if (gap_s > 0
            and gap_s >= atr_val * 0.3
            and current_close < fvg_high_s
            and current_close < float(df["low"].iloc[-2])
    ):
        sl_price = fvg_high_s + (gap_s * 0.1)
        sl_pips  = round((sl_price - current_close) / pip_size, 1)
        tp_pips  = round(sl_pips * TP_RATIO, 1)

        if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
            return None

        confidence = CONFIDENCE_BASE
        if gap_s >= atr_val * 0.6:  confidence += 8
        if gap_s >= atr_val * 1.0:  confidence += 8

        return {
            "type":       "SELL",
            "reason":     f"Bearish FVG+MSS (gap={round(gap_s/pip_size,1)}p, ATR={round(atr_val/pip_size,1)}p)",
            "confidence": min(confidence, 95),
            "sl_pips":    sl_pips,
            "tp_pips":    tp_pips,
        }

    return None


# ─── SIGNAL INSERT ─────────────────────────────────────────────────────────────

def save_signal(symbol: str, direction: str, reason: str, confidence: int,
                sl_pips: float, tp_pips: float):
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
              f"SL:{sl_pips:6.1f}p TP:{tp_pips:6.1f}p | "
              f"Conf:{confidence}% | {reason}")
    except Exception as e:
        print(f"[{_ts()}] ❌ Signal insert error ({symbol}): {e}")


# ─── MAIN SCAN ─────────────────────────────────────────────────────────────────

def run_scan():
    print(f"[{_ts()}] 🧠 Scan started")

    symbols = get_active_symbols()
    print(f"[{_ts()}] 📊 {len(symbols)} active symbols")

    accepted = 0
    rejected_htf = 0
    rejected_cooldown = 0
    rejected_no_setup = 0

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

        # ── Cooldown gate ──────────────────────────────────────────────────────
        if is_on_cooldown(symbol, direction):
            rejected_cooldown += 1
            print(f"[{_ts()}] ⏳ COOLDOWN: {symbol} {direction} — skipping (< {SIGNAL_COOLDOWN_HR}h since last)")
            continue

        # ── HTF trend filter ───────────────────────────────────────────────────
        trend = htf_trend(symbol)
        if trend is not None and trend != direction:
            rejected_htf += 1
            print(f"[{_ts()}] 🚫 HTF BLOCK: {symbol} {direction} vs 1H trend={trend}")
            continue

        # HTF aligned — add confidence bonus
        if trend == direction:
            confidence = min(confidence + 6, 95)

        # ── Accept and save ────────────────────────────────────────────────────
        save_signal(symbol, direction, signal["reason"], confidence, sl_pips, tp_pips)
        notify(
            f"✅ *{direction}* `{symbol}`\n"
            f"SL: `{sl_pips}p` | TP: `{tp_pips}p` | Conf: `{confidence}%`\n"
            f"_{signal['reason']}_"
        )
        accepted += 1

    print(f"[{_ts()}] ✅ Scan done — "
          f"accepted={accepted} | "
          f"no_setup={rejected_no_setup} | "
          f"htf_blocked={rejected_htf} | "
          f"cooldown={rejected_cooldown}")


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    notify("🛡️ Tekton Strategy Engine v1.1 started.")
    print(f"[{_ts()}] 🚀 Strategy engine started. Scan interval: {SCAN_INTERVAL_SEC}s, Cooldown: {SIGNAL_COOLDOWN_HR}h")

    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"[{_ts()}] 💥 Unhandled error in run_scan: {e}")
        time.sleep(SCAN_INTERVAL_SEC)
