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

SCAN_INTERVAL_SEC  = 300
SIGNAL_COOLDOWN_HR = 1
HTF_CANDLES        = 50
LTF_CANDLES        = 60
FVG_LOOKBACK       = 10
ATR_PERIOD         = 14
ATR_MIN_RATIO      = 0.2      # FVG gap must be ≥ 20% of ATR
MSS_ATR_BUFFER     = 0.5      # price can be within 0.5×ATR of gap level and still pass
MIN_SL_PIPS        = 3.0
MAX_SL_PIPS        = 600.0
MIN_RR             = 1.5      # minimum reward:risk ratio to accept a signal — entry quality gate only
TP_RATIO           = 1.8      # reference for AI optimisation; not enforced at entry
CONFIDENCE_BASE    = 72
SPECS_CACHE_TTL    = 300

# ─── BRIDGE SPECS CACHE ────────────────────────────────────────────────────────

_symbol_specs_cache = {}
_specs_cache_ts     = 0


def get_symbol_specs() -> dict:
    """
    Fetches pip_size and price_scale for every symbol from the bridge /symbols/list.

    The bridge returns two fields per symbol:
      - digits:      decimal places in the price (always present)
      - pipPosition: cTrader pip position (may be None for some instruments)

    Price scale (raw DB integer → real price):
      price_scale = 10 ^ digits
      e.g. EURUSD digits=4 → price_scale=10000  (raw 10850 → 1.0850)
      e.g. XAUUSD digits=2 → price_scale=100    (raw 301567 → 3015.67)
      e.g. US30   digits=1 → price_scale=10     (raw 434250 → 43425.0)

    Pip size (1 pip in price units):
      If pipPosition is set by cTrader: pip_size = 10 ^ -pipPosition
        e.g. EURUSD pipPosition=4 → pip_size=0.0001  (standard 4-pip)
        e.g. USDJPY pipPosition=2 → pip_size=0.01
      If pipPosition is None (commodities, indices): pip_size = 10 ^ -(digits-1)
        e.g. XAUUSD digits=2 → pip_size = 10^-1 = 0.1  (1 pip = $0.10 on gold)
        e.g. US30   digits=1 → pip_size = 10^0  = 1.0  (1 pip = 1 point)
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
        symbols = resp.json().get("symbols", [])

        specs = {}
        for s in symbols:
            sym_name    = s.get("name", "")
            digits      = s.get("digits") or 4
            pip_pos     = s.get("pipPosition")          # may be None

            # price_scale: always derived from digits
            price_scale = 10 ** digits

            # pip_size: use pipPosition if available, else digits-1
            if pip_pos is not None:
                pip_size = 10 ** (-pip_pos)
            else:
                pip_size = 10 ** (-(digits - 1))

            specs[sym_name] = {
                "pip_size":    pip_size,
                "price_scale": price_scale,
                "digits":      digits,
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
    """
    Returns (pip_size, price_scale).
    Primary: live bridge specs.
    Fallback: hardcoded table (only used if bridge unreachable).

    Verified values (from symbols.json + cTrader docs):
      Forex 5-digit (EURUSD):  digits=4, pipPos=4  → pip=0.0001,  scale=10000
      Forex JPY (USDJPY):      digits=2, pipPos=2  → pip=0.01,    scale=100
         Note: USDJPY digits=2 means raw/100 = real price (e.g. 14850 → 148.50)
               1 pip = 0.01 ✓
      Gold (XAUUSD):           digits=2, pipPos=None → pip=0.1,   scale=100
         raw/100 = real price (e.g. 301567 → 3015.67), 1 pip = $0.10
      Silver (XAGUSD):         digits=2, pipPos=None → pip=0.1,   scale=100
      Oil (XTIUSD/XBRUSD):     digits=2, pipPos=None → pip=0.1,   scale=100
      NatGas (XNGUSD):         digits=3, pipPos=None → pip=0.01,  scale=1000
      US30/UK100/DE40/JP225:   digits=1, pipPos=None → pip=1.0,   scale=10
      US500/USTEC/AUS200:      digits=1, pipPos=None → pip=1.0,   scale=10
    """
    specs = get_symbol_specs()
    if symbol in specs:
        return specs[symbol]["pip_size"], specs[symbol]["price_scale"]

    # ── Hardcoded fallback ─────────────────────────────────────────────────────
    FALLBACK = {
        # Forex
        "EURUSD": (0.0001, 10000), "GBPUSD": (0.0001, 10000),
        "AUDUSD": (0.0001, 10000), "NZDUSD": (0.0001, 10000),
        "USDCAD": (0.0001, 10000), "USDCHF": (0.0001, 10000),
        "USDSGD": (0.0001, 10000), "EURGBP": (0.0001, 10000),
        "USDJPY": (0.01,   100),   "EURJPY": (0.01,   100),
        "GBPJPY": (0.01,   100),   "AUDJPY": (0.01,   100),
        "CADJPY": (0.01,   100),   "CHFJPY": (0.01,   100),
        # Metals
        "XAUUSD": (0.1,    100),   "XAGUSD": (0.1,    100),
        "XPTUSD": (0.1,    100),   "XPDUSD": (0.1,    100),
        # Energy
        "XTIUSD": (0.1,    100),   "XBRUSD": (0.1,    100),
        "XNGUSD": (0.01,   1000),
        # Indices (1 pip = 1 point)
        "US30":   (1.0,    10),    "US500":  (1.0,    10),
        "USTEC":  (1.0,    10),    "UK100":  (1.0,    10),
        "DE40":   (1.0,    10),    "JP225":  (1.0,    10),
        "AUS200": (1.0,    10),    "HK50":   (1.0,    10),
        "ES35":   (1.0,    10),    "FR40":   (1.0,    10),
    }
    return FALLBACK.get(symbol, (0.0001, 10000))


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
    high = df["high"]
    low  = df["low"]
    prev = df["close"].shift(1)
    tr   = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# ─── HTF TREND FILTER ──────────────────────────────────────────────────────────

def htf_trend(symbol: str) -> str | None:
    """1H trend using EMA20 vs EMA50. Returns 'BUY', 'SELL', or None."""
    df = get_ohlc(symbol, "60min", HTF_CANDLES)
    if df is None or len(df) < 20:
        return None

    closes = df["close"]
    ema20  = closes.ewm(span=20, adjust=False).mean().iloc[-1]

    if len(df) >= 50:
        ema50 = closes.ewm(span=50, adjust=False).mean().iloc[-1]
        if ema20 > ema50: return "BUY"
        if ema20 < ema50: return "SELL"
        return None
    else:
        ema20_prev = closes.ewm(span=20, adjust=False).mean().iloc[-4]
        if ema20 > ema20_prev: return "BUY"
        if ema20 < ema20_prev: return "SELL"
        return None


# ─── SIGNAL DETECTION ──────────────────────────────────────────────────────────

def detect_signal(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    Scans the last FVG_LOOKBACK candles for a valid ICT Fair Value Gap + MSS.

    FVG pattern: 3-candle sequence where outer candles don't overlap.
      Bullish: c_next.low > c_prev.high  → gap above middle candle
      Bearish: c_next.high < c_prev.low  → gap below middle candle

    MSS: current price has broken through the gap level (with ATR tolerance).
    Returns strongest setup found (largest gap/ATR ratio).
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

    end_idx   = len(df) - 1
    start_idx = max(1, len(df) - FVG_LOOKBACK)

    for i in range(end_idx - 1, start_idx, -1):
        c_prev = df.iloc[i - 1]
        c_next = df.iloc[i + 1]

        # ── BULLISH FVG ────────────────────────────────────────────────────────
        gap_b       = float(c_next["low"]) - float(c_prev["high"])
        mss_level_b = float(c_prev["high"])

        if (gap_b > 0
                and gap_b >= atr_val * ATR_MIN_RATIO
                and current_close >= mss_level_b - atr_val * MSS_ATR_BUFFER
        ):
            # SL: structural (c_prev low) vs 1×ATR below entry — wider stop wins.
            # This ensures ATR-based volatility never places stop inside normal noise.
            sl_structural = float(c_prev["low"])
            sl_atr        = current_close - atr_val
            sl_price      = min(sl_structural, sl_atr)

            # TP: purely structural — c_next high is the natural FVG target.
            # TP_RATIO kept as reference for future AI optimisation; not enforced here.
            tp_price = float(c_next["high"])

            sl_pips  = round((current_close - sl_price) / pip_size, 1)
            tp_pips  = round((tp_price - current_close) / pip_size, 1)

            # Sanity guard — catch broken calculations only
            if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
                continue
            if tp_pips <= 0:
                continue

            # Entry quality gate — reject setups below minimum RR.
            # Once in a trade, AI manages exits freely regardless of RR.
            if sl_pips > 0 and (tp_pips / sl_pips) < MIN_RR:
                continue

            gap_atr_ratio = gap_b / atr_val
            if gap_atr_ratio > best_gap_atr:
                best_gap_atr = gap_atr_ratio
                age_candles  = end_idx - i
                confidence   = CONFIDENCE_BASE
                if gap_atr_ratio >= 0.5: confidence += 8
                if gap_atr_ratio >= 1.0: confidence += 8
                if age_candles   <= 2:   confidence += 5

                best_signal = {
                    "type":       "BUY",
                    "reason":     (f"Bullish FVG+MSS "
                                   f"gap={round(gap_b/pip_size,1)}p "
                                   f"ATR={round(atr_val/pip_size,1)}p "
                                   f"age={age_candles}c"),
                    "confidence": min(confidence, 95),
                    "sl_pips":    sl_pips,
                    "tp_pips":    tp_pips,
                }

        # ── BEARISH FVG ────────────────────────────────────────────────────────
        gap_s       = float(c_prev["low"]) - float(c_next["high"])
        mss_level_s = float(c_prev["low"])

        if (gap_s > 0
                and gap_s >= atr_val * ATR_MIN_RATIO
                and current_close <= mss_level_s + atr_val * MSS_ATR_BUFFER
        ):
            # SL: structural (c_prev high) vs 1×ATR above entry — wider stop wins.
            sl_structural = float(c_prev["high"])
            sl_atr        = current_close + atr_val
            sl_price      = max(sl_structural, sl_atr)

            # TP: purely structural — c_next low is the natural FVG target.
            # TP_RATIO kept as reference for future AI optimisation; not enforced here.
            tp_price = float(c_next["low"])

            sl_pips  = round((sl_price - current_close) / pip_size, 1)
            tp_pips  = round((current_close - tp_price) / pip_size, 1)

            # Sanity guard — catch broken calculations only
            if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
                continue
            if tp_pips <= 0:
                continue

            # Entry quality gate — reject setups below minimum RR.
            # Once in a trade, AI manages exits freely regardless of RR.
            if sl_pips > 0 and (tp_pips / sl_pips) < MIN_RR:
                continue

            gap_atr_ratio = gap_s / atr_val
            if gap_atr_ratio > best_gap_atr:
                best_gap_atr = gap_atr_ratio
                age_candles  = end_idx - i
                confidence   = CONFIDENCE_BASE
                if gap_atr_ratio >= 0.5: confidence += 8
                if gap_atr_ratio >= 1.0: confidence += 8
                if age_candles   <= 2:   confidence += 5

                best_signal = {
                    "type":       "SELL",
                    "reason":     (f"Bearish FVG+MSS "
                                   f"gap={round(gap_s/pip_size,1)}p "
                                   f"ATR={round(atr_val/pip_size,1)}p "
                                   f"age={age_candles}c"),
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

        if is_on_cooldown(symbol, direction):
            rejected_cooldown += 1
            print(f"[{_ts()}] ⏳ COOLDOWN: {symbol} {direction}")
            continue

        trend = htf_trend(symbol)
        if trend is not None and trend != direction:
            rejected_htf += 1
            print(f"[{_ts()}] 🚫 HTF BLOCK: {symbol} {direction} (1H={trend})")
            continue

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
    notify("🛡️ Tekton Strategy Engine v1.4 started.")
    print(f"[{_ts()}] 🚀 Strategy v1.4 started — "
          f"scan={SCAN_INTERVAL_SEC}s cooldown={SIGNAL_COOLDOWN_HR}h "
          f"lookback={FVG_LOOKBACK}c ATR_min={ATR_MIN_RATIO} MSS_buf={MSS_ATR_BUFFER}×ATR")
    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"[{_ts()}] 💥 Unhandled error: {e}")
        time.sleep(SCAN_INTERVAL_SEC)
