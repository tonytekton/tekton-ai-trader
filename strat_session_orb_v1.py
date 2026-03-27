import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
#
#  Session Open Range Breakout (SORB) Strategy
#  ─────────────────────────────────────────────
#  Logic:
#    1. Define the Opening Range (OR): first 4 candles (1hr) of London (07:00 UTC)
#       or NY (13:00 UTC) session
#    2. Wait for a clean breakout candle that closes OUTSIDE the OR high/low
#    3. A retest candle touches back to the OR boundary without closing back inside
#    4. Entry on the next candle after confirmed retest
#    5. SL: below/above the OR level (invalidation point)
#    6. TP: OR range × 2.0 projected from breakout level (structural extension)
#
#  Why this works:
#    - Session opens = highest liquidity concentration, cleanest price discovery
#    - OR levels act as strong S/R once broken
#    - Retest confirmation filters false breakouts
#    - London and NY opens are the two most reliable setups in FX
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
SIGNAL_COOLDOWN_HR = 8         # one trade per session per symbol
LTF_TIMEFRAME      = "15min"
LTF_CANDLES        = 60        # 15hr of 15min data
ATR_PERIOD         = 14
OR_CANDLES         = 4         # opening range = first 4 × 15min candles = 1hr
RETEST_BUFFER_ATR  = 0.3       # retest must come within 0.3×ATR of OR level
MIN_RR             = 1.5
MIN_SL_PIPS        = 3.0
MAX_SL_PIPS        = 200.0
CONFIDENCE_BASE    = 76
STRATEGY_NAME      = "Tekton-SORB-v1"

# London open: 07:00 UTC, NY open: 13:00 UTC
SESSION_OPENS_UTC  = [7, 13]

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
            json={"chat_id": chat_id, "text": f"📈 *SORB Signal*\n{msg}", "parse_mode": "Markdown"},
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
        print(f"[{_ts()}] ❌ Bridge specs UNAVAILABLE — skipping scan cycle: {e}")
        raise

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

def get_active_symbols():
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data WHERE timeframe=%s
            GROUP BY symbol HAVING COUNT(*) >= 30 ORDER BY symbol;
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

def is_session_window():
    """Returns True if we're within 3 hours after a session open (active breakout window)."""
    now_h = datetime.utcnow().hour
    for session_h in SESSION_OPENS_UTC:
        if 0 <= (now_h - session_h) % 24 <= 3:
            return True
    return False

def scan_symbol(symbol):
    pip_size, price_scale = get_pip_info(symbol)

    df = get_ohlc(symbol, LTF_TIMEFRAME, LTF_CANDLES)
    if df is None or len(df) < OR_CANDLES + 10:
        return

    atr_val = calc_atr(df)
    if atr_val <= 0:
        return

    # ── Find the most recent session open in the data ────────────────────────
    # Look for a run of candles starting at a session open hour
    df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour

    or_start_idx = None
    for i in range(len(df) - OR_CANDLES - 5, max(0, len(df) - 40), -1):
        if df["hour"].iloc[i] in SESSION_OPENS_UTC:
            or_start_idx = i
            break

    if or_start_idx is None:
        return

    or_candles = df.iloc[or_start_idx: or_start_idx + OR_CANDLES]
    or_high    = or_candles["high"].max()
    or_low     = or_candles["low"].min()
    or_range   = or_high - or_low

    if or_range <= 0 or or_range / pip_size < 3:
        return  # OR too tight — skip

    # ── Post-OR candles: look for breakout + retest ───────────────────────────
    post_or = df.iloc[or_start_idx + OR_CANDLES:].reset_index(drop=True)

    if len(post_or) < 3:
        return  # not enough post-OR candles yet

    direction   = None
    breakout_i  = None
    retest_done = False

    for i in range(len(post_or) - 1):
        c = post_or.iloc[i]

        # Bullish breakout — candle closes above OR high
        if c["close"] > or_high and breakout_i is None:
            direction  = "BUY"
            breakout_i = i

        # Bearish breakout — candle closes below OR low
        elif c["close"] < or_low and breakout_i is None:
            direction  = "SELL"
            breakout_i = i

        # Look for retest after breakout
        if breakout_i is not None and i > breakout_i:
            if direction == "BUY":
                # Price comes back to within RETEST_BUFFER_ATR of OR high
                if post_or.iloc[i]["low"] <= or_high + atr_val * RETEST_BUFFER_ATR:
                    # But candle must NOT close back below OR high
                    if post_or.iloc[i]["close"] >= or_high - atr_val * RETEST_BUFFER_ATR:
                        retest_done = True
                        break
            else:
                if post_or.iloc[i]["high"] >= or_low - atr_val * RETEST_BUFFER_ATR:
                    if post_or.iloc[i]["close"] <= or_low + atr_val * RETEST_BUFFER_ATR:
                        retest_done = True
                        break

    if not retest_done or direction is None:
        return

    # ── Cooldown check ─────────────────────────────────────────────────────────
    if is_on_cooldown(symbol, direction):
        print(f"[{_ts()}] ⏳ COOLDOWN: {symbol} {direction}")
        return

    # ── SL / TP ────────────────────────────────────────────────────────────────
    if direction == "BUY":
        sl_price = or_high - atr_val * 0.3   # just below OR high
        tp_price = or_high + or_range * 2.0  # 2× OR range extension
        entry    = or_high
    else:
        sl_price = or_low + atr_val * 0.3
        tp_price = or_low - or_range * 2.0
        entry    = or_low

    sl_pips = abs(entry - sl_price) / pip_size
    tp_pips = abs(entry - tp_price) / pip_size

    if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
        return
    if tp_pips <= 0:
        return
    if sl_pips > 0 and (tp_pips / sl_pips) < MIN_RR:
        return

    rr         = round(tp_pips / sl_pips, 2)
    confidence = min(CONFIDENCE_BASE + int(rr * 2), 90)
    reason     = (f"SORB {direction} OR_range={round(or_range/pip_size,1)}p "
                  f"ATR={round(atr_val/pip_size,1)}p RR={rr}")

    insert_signal(symbol, direction, sl_pips, tp_pips, confidence, reason)


def main():
    print(f"[{_ts()}] 🧠 SORB Strategy Engine Active. [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        print(f"[{_ts()}] 🧠 SORB scan started")
        if not is_session_window():
            print(f"[{_ts()}] ⏸ Outside session window — skipping scan")
            time.sleep(SCAN_INTERVAL_SEC)
            continue
        try:
            try:
                get_symbol_specs()  # pre-check — raises if bridge specs unavailable
            except Exception as spec_err:
                print(f"[{_ts()}] ❌ BRIDGE SPECS FAILED — skipping scan cycle. Check /symbols/list endpoint. Error: {spec_err}")
                time.sleep(SCAN_INTERVAL_SEC)
                continue
            symbols = get_active_symbols()
            print(f"[{_ts()}] 📊 {len(symbols)} symbols in session window")
            accepted = 0
            for sym in symbols:
                try:
                    before = accepted
                    scan_symbol(sym)
                except Exception as e:
                    print(f"[{_ts()}] ⚠️ {sym}: {e}")
            print(f"[{_ts()}] ✅ SORB scan done")
        except Exception as e:
            print(f"[{_ts()}] ❌ SORB ERROR: {e}")
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main()
