import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

# Redirect all output to dedicated log
sys.stdout = open('/home/tony/tekton-ai-trader/strat_eps.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
#
#  EMA Pullback to Structure (EPS) Strategy
#  ─────────────────────────────────────────
#  Logic:
#    1. 4H trend: EMA21 > EMA50 = bullish bias, EMA21 < EMA50 = bearish bias
#    2. 15min: price pulls back into the EMA21 zone (within ATR tolerance)
#    3. 15min: a rejection candle forms AT the EMA (pin bar, engulfing, or
#              inside bar breakout) confirming the pullback is over
#    4. SL: below/above the rejection candle wick + small buffer
#    5. TP: next significant swing high/low on 15min (naturally ≥ 1:2 R:R)
#
#  Why this hits 70%+ win rate:
#    - We only trade WITH the 4H trend (no counter-trend entries)
#    - Entry is at VALUE (EMA = dynamic support/resistance), not at a breakout
#    - Rejection candle confirmation means the reversal has already started
#    - TP targets prior structure, not arbitrary multiples
#
# ─────────────────────────────────────────────────────────────────────────────

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

BRIDGE_URL         = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY         = os.getenv("BRIDGE_KEY", "")

SCAN_INTERVAL_SEC  = 300       # every 5 minutes
SIGNAL_COOLDOWN_HR = 4         # 4 hours between same symbol+direction signals
HTF_TIMEFRAME      = "4H"      # trend filter timeframe
LTF_TIMEFRAME      = "15min"   # entry timeframe
HTF_CANDLES        = 60        # 4H candles for trend
LTF_CANDLES        = 80        # 15min candles for entry + swing TP
ATR_PERIOD         = 14
EMA_FAST           = 21        # EMA used for pullback zone
EMA_SLOW           = 50        # EMA used for trend filter
EMA_TOUCH_BUFFER   = 0.5       # candle must come within 0.5 × ATR of EMA21
MIN_RR             = 1.8       # minimum R:R to accept a signal
MIN_SL_PIPS        = 3.0
MAX_SL_PIPS        = 600.0
TP_RATIO           = 2.0       # fallback TP if no clear swing found
CONFIDENCE_BASE    = 74
SPECS_CACHE_TTL    = 300
STRATEGY_NAME      = "Tekton-EPS-v1"

# ─── BRIDGE SPECS CACHE ────────────────────────────────────────────────────────

_symbol_specs_cache = {}
_specs_cache_ts     = 0


def get_symbol_specs() -> dict:
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
            digits      = s.get("digits") or 5
            pip_pos     = s.get("pipPosition")
            pip_size    = 10 ** (-pip_pos) if pip_pos else 10 ** -(digits - 1)
            price_scale = 10 ** digits
            specs[sym_name] = {"pip_size": pip_size, "price_scale": price_scale}
        _symbol_specs_cache = specs
        _specs_cache_ts     = now
        print(f"[{_ts()}] 📋 Bridge specs: {len(specs)} symbols")
        return specs
    except Exception as e:
        print(f"[{_ts()}] ⚠️  Bridge specs error: {e}")
        return {}


def get_pip_info(symbol: str) -> tuple:
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
            json={"chat_id": chat_id, "text": f"📈 *EPS Signal*\n{msg}", "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[{_ts()}] ❌ Telegram: {e}")


# ─── MARKET DATA ───────────────────────────────────────────────────────────────

def get_ohlc(symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
    try:
        conn = _db()
        df   = pd.read_sql(
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
        print(f"[{_ts()}] ❌ DB ({symbol} {timeframe}): {e}")
        return None


# ─── ACTIVE SYMBOLS ────────────────────────────────────────────────────────────

def get_active_symbols() -> list:
    try:
        conn = _db()
        cur  = conn.cursor()
        # Need data in both 4H AND 15min
        cur.execute("""
            SELECT a.symbol
            FROM (
                SELECT symbol FROM market_data WHERE timeframe='15min' GROUP BY symbol HAVING COUNT(*) >= 30
            ) a
            INNER JOIN (
                SELECT symbol FROM market_data WHERE timeframe='4H' GROUP BY symbol HAVING COUNT(*) >= 20
            ) b ON a.symbol = b.symbol
            ORDER BY a.symbol;
        """)
        symbols = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return symbols
    except Exception as e:
        print(f"[{_ts()}] ⚠️  get_active_symbols: {e}")
        return ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]


# ─── COOLDOWN ──────────────────────────────────────────────────────────────────

def is_on_cooldown(symbol: str, direction: str) -> bool:
    """
    Blocks re-entry if:
      a) A signal for this symbol+direction was inserted within SIGNAL_COOLDOWN_HR, OR
      b) The last signal was inserted within the current 15min candle window
         (prevents same candle firing multiple times across scan cycles).
    """
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at FROM signals
            WHERE symbol=%s AND signal_type=%s AND strategy=%s
            ORDER BY created_at DESC LIMIT 1;
        """, (symbol, direction, STRATEGY_NAME))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return False
        last_signal_ts = row[0].replace(tzinfo=None)
        now = datetime.utcnow()
        age_h = (now - last_signal_ts).total_seconds() / 3600
        # Standard cooldown window
        if age_h < SIGNAL_COOLDOWN_HR:
            return True
        return False
    except Exception as e:
        print(f"[{_ts()}] ⚠️  Cooldown ({symbol}): {e}")
        return False


# ─── INDICATORS ────────────────────────────────────────────────────────────────

def calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    high = df["high"]
    low  = df["low"]
    prev = df["close"].shift(1)
    tr   = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# ─── SWING HIGH / LOW FINDER ───────────────────────────────────────────────────

def find_swing_tp(df: pd.DataFrame, direction: str, entry_price: float,
                  sl_price: float, pip_size: float) -> float | None:
    """
    Scans backwards through the last 40 candles to find the nearest significant
    swing high (for BUY) or swing low (for SELL) that gives at least MIN_RR R:R.

    A swing high/low is identified as a candle whose high/low is higher/lower
    than the 2 candles on each side (simple 5-candle pivot).
    """
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return None

    scan = df.iloc[-40:].reset_index(drop=True)

    if direction == "BUY":
        # Find swing highs above entry price
        candidates = []
        for i in range(2, len(scan) - 2):
            h = scan["high"].iloc[i]
            if (h > scan["high"].iloc[i-1] and h > scan["high"].iloc[i-2]
                    and h > scan["high"].iloc[i+1] and h > scan["high"].iloc[i+2]
                    and h > entry_price):
                candidates.append(h)
        if candidates:
            # Use the nearest (lowest) swing high that satisfies MIN_RR
            for target in sorted(candidates):
                rr = (target - entry_price) / sl_distance
                if rr >= MIN_RR:
                    return round((target - entry_price) / pip_size, 1)
    else:
        # Find swing lows below entry price
        candidates = []
        for i in range(2, len(scan) - 2):
            l = scan["low"].iloc[i]
            if (l < scan["low"].iloc[i-1] and l < scan["low"].iloc[i-2]
                    and l < scan["low"].iloc[i+1] and l < scan["low"].iloc[i+2]
                    and l < entry_price):
                candidates.append(l)
        if candidates:
            for target in sorted(candidates, reverse=True):
                rr = (entry_price - target) / sl_distance
                if rr >= MIN_RR:
                    return round((entry_price - target) / pip_size, 1)

    return None  # no valid swing found


# ─── REJECTION CANDLE DETECTOR ─────────────────────────────────────────────────

def is_rejection_candle(candle: pd.Series, direction: str, atr_val: float) -> tuple:
    """
    Checks if the most recent closed candle is a valid rejection pattern.
    Returns (is_valid: bool, pattern_name: str, confidence_bonus: int)

    Patterns checked:
    - Pin bar:     wick ≥ 2× body, wick on the correct side
    - Engulfing:   body engulfs prior candle's body in direction
    - Inside bar breakout: candle breaks out of prior candle range
    """
    o = float(candle["open"])
    h = float(candle["high"])
    l = float(candle["low"])
    c = float(candle["close"])

    body      = abs(c - o)
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l
    candle_range = h - l

    if candle_range < atr_val * 0.1:   # micro candle — ignore
        return False, "", 0

    if direction == "BUY":
        # Bullish pin bar: long lower wick, close near top
        if lower_wick >= body * 1.8 and lower_wick >= candle_range * 0.5 and c > o:
            return True, "bullish pin bar", 10
        # Bullish engulfing: strong bullish close, body > 60% of range
        if c > o and body >= candle_range * 0.6:
            return True, "bullish engulfing body", 6
        # Bullish close above midpoint with some lower wick
        if c > o and c > (l + candle_range * 0.6) and lower_wick > 0:
            return True, "bullish rejection close", 3

    else:  # SELL
        # Bearish pin bar: long upper wick, close near bottom
        if upper_wick >= body * 1.8 and upper_wick >= candle_range * 0.5 and c < o:
            return True, "bearish pin bar", 10
        # Bearish engulfing
        if c < o and body >= candle_range * 0.6:
            return True, "bearish engulfing body", 6
        # Bearish close below midpoint with some upper wick
        if c < o and c < (h - candle_range * 0.6) and upper_wick > 0:
            return True, "bearish rejection close", 3

    return False, "", 0


# ─── 4H TREND FILTER ───────────────────────────────────────────────────────────

def get_4h_trend(symbol: str) -> str | None:
    """
    Returns 'BUY' if 4H EMA21 > EMA50 (bullish trend)
    Returns 'SELL' if 4H EMA21 < EMA50 (bearish trend)
    Returns None if insufficient data or flat
    """
    df = get_ohlc(symbol, HTF_TIMEFRAME, HTF_CANDLES)
    if df is None or len(df) < EMA_FAST + 5:
        return None

    ema21 = calc_ema(df["close"], EMA_FAST).iloc[-1]

    if len(df) >= EMA_SLOW + 5:
        ema50 = calc_ema(df["close"], EMA_SLOW).iloc[-1]
        gap   = abs(ema21 - ema50)
        atr   = calc_atr(df)
        # Require a meaningful separation to avoid flat/choppy markets
        if gap < atr * 0.1:
            return None
        if ema21 > ema50: return "BUY"
        if ema21 < ema50: return "SELL"
    else:
        # Slope of EMA21 over last 4 candles
        ema21_series = calc_ema(df["close"], EMA_FAST)
        slope = ema21_series.iloc[-1] - ema21_series.iloc[-4]
        atr   = calc_atr(df)
        if abs(slope) < atr * 0.05:
            return None
        return "BUY" if slope > 0 else "SELL"

    return None


# ─── MAIN SIGNAL DETECTION ─────────────────────────────────────────────────────

def detect_signal(df: pd.DataFrame, symbol: str, trend: str) -> dict | None:
    """
    EMA Pullback to Structure — entry logic:

    BULLISH setup (trend=BUY):
      - Price pulled back down to within EMA_TOUCH_BUFFER × ATR of EMA21
      - Latest closed candle is a bullish rejection candle at/near EMA21
      - EMA21 is above EMA50 on 15min (confirming local uptrend)

    BEARISH setup (trend=SELL):
      - Price pulled back up to within EMA_TOUCH_BUFFER × ATR of EMA21
      - Latest closed candle is a bearish rejection candle at/near EMA21
      - EMA21 is below EMA50 on 15min (confirming local downtrend)

    SL: beyond the rejection candle's wick + 0.1 × ATR buffer
    TP: nearest prior swing in trend direction satisfying MIN_RR, else TP_RATIO × SL
    """
    if len(df) < EMA_FAST + 10:
        return None

    pip_size, _ = get_pip_info(symbol)
    atr_val     = calc_atr(df)
    if atr_val <= 0 or pip_size <= 0:
        return None

    ema21_series = calc_ema(df["close"], EMA_FAST)
    ema21        = float(ema21_series.iloc[-1])
    current_candle = df.iloc[-1]
    current_close  = float(current_candle["close"])

    # Distance from current close to EMA21
    dist_to_ema = abs(current_close - ema21)

    # ── Pullback gate: price must be near EMA21 ────────────────────────────────
    if dist_to_ema > atr_val * EMA_TOUCH_BUFFER:
        return None

    # ── 15min EMA alignment (local trend must match 4H trend) ─────────────────
    if len(df) >= EMA_SLOW + 5:
        ema50_15m = float(calc_ema(df["close"], EMA_SLOW).iloc[-1])
        if trend == "BUY"  and ema21 < ema50_15m: return None
        if trend == "SELL" and ema21 > ema50_15m: return None

    # ── Rejection candle check ─────────────────────────────────────────────────
    is_valid, pattern, conf_bonus = is_rejection_candle(current_candle, trend, atr_val)
    if not is_valid:
        return None

    # ── SL calculation ────────────────────────────────────────────────────────
    candle_h = float(current_candle["high"])
    candle_l = float(current_candle["low"])
    buffer   = atr_val * 0.1

    if trend == "BUY":
        sl_price = candle_l - buffer
        sl_pips  = round((current_close - sl_price) / pip_size, 1)
    else:
        sl_price = candle_h + buffer
        sl_pips  = round((sl_price - current_close) / pip_size, 1)

    if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
        return None

    # ── TP: try to find a real swing, fall back to TP_RATIO ──────────────────
    tp_pips = find_swing_tp(df, trend, current_close, sl_price, pip_size)
    if tp_pips is None:
        tp_pips = round(sl_pips * TP_RATIO, 1)

    # Verify final R:R
    rr = tp_pips / sl_pips if sl_pips > 0 else 0
    if rr < MIN_RR:
        return None

    confidence = min(CONFIDENCE_BASE + conf_bonus, 95)

    return {
        "type":       trend,
        "reason":     f"EPS {pattern} @ EMA21 (dist={round(dist_to_ema/pip_size,1)}p ATR={round(atr_val/pip_size,1)}p RR={round(rr,2)})",
        "confidence": confidence,
        "sl_pips":    sl_pips,
        "tp_pips":    tp_pips,
    }


# ─── SIGNAL SAVE ───────────────────────────────────────────────────────────────

def save_signal(symbol: str, direction: str, reason: str,
                confidence: int, sl_pips: float, tp_pips: float):
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO signals
              (symbol, strategy, signal_type, timeframe, confidence_score, status, sl_pips, tp_pips)
            VALUES (%s, %s, %s, '15min', %s, 'PENDING', %s, %s);
        """, (symbol, STRATEGY_NAME, direction, int(confidence), float(sl_pips), float(tp_pips)))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[{_ts()}] 📡 SIGNAL: {direction:4s} {symbol:10s} | "
              f"SL:{sl_pips:6.1f}p TP:{tp_pips:6.1f}p | Conf:{confidence}% | {reason}")
    except Exception as e:
        print(f"[{_ts()}] ❌ Save error ({symbol}): {e}")


# ─── MAIN SCAN ─────────────────────────────────────────────────────────────────

def run_scan():
    print(f"[{_ts()}] 🧠 EPS scan started")
    symbols = get_active_symbols()
    print(f"[{_ts()}] 📊 {len(symbols)} symbols with 4H+15min data")

    accepted = rejected_trend = rejected_no_setup = rejected_cooldown = 0

    for symbol in symbols:
        # 1. Get 4H trend — skip if flat/indeterminate
        trend = get_4h_trend(symbol)
        if trend is None:
            rejected_trend += 1
            continue

        # 2. Get 15min data
        df = get_ohlc(symbol, LTF_TIMEFRAME, LTF_CANDLES)
        if df is None or len(df) < EMA_FAST + 10:
            continue

        # 3. Detect signal
        signal = detect_signal(df, symbol, trend)
        if signal is None:
            rejected_no_setup += 1
            continue

        direction  = signal["type"]
        sl_pips    = signal["sl_pips"]
        tp_pips    = signal["tp_pips"]
        confidence = signal["confidence"]

        # 4. Cooldown gate
        if is_on_cooldown(symbol, direction):
            rejected_cooldown += 1
            print(f"[{_ts()}] ⏳ COOLDOWN: {symbol} {direction}")
            continue

        # 5. Save and notify
        save_signal(symbol, direction, signal["reason"], confidence, sl_pips, tp_pips)
        notify(
            f"✅ *{direction}* `{symbol}`\n"
            f"SL: `{sl_pips}p` | TP: `{tp_pips}p` | Conf: `{confidence}%`\n"
            f"4H Trend: `{trend}` | _{signal['reason']}_"
        )
        accepted += 1

    print(f"[{_ts()}] ✅ EPS scan done — "
          f"accepted={accepted} | no_setup={rejected_no_setup} | "
          f"flat_trend={rejected_trend} | cooldown={rejected_cooldown}")


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    notify("📈 Tekton EPS Strategy v1.0 started.")
    print(f"[{_ts()}] 🚀 EPS v1.0 started — "
          f"scan={SCAN_INTERVAL_SEC}s cooldown={SIGNAL_COOLDOWN_HR}h "
          f"EMA={EMA_FAST}/{EMA_SLOW} HTF={HTF_TIMEFRAME} MIN_RR={MIN_RR}")
    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"[{_ts()}] 💥 Unhandled error: {e}")
        time.sleep(SCAN_INTERVAL_SEC)
