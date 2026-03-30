import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

_log_file = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stdout = _log_file
sys.stderr = _log_file

class _PrefixedLogger:
    """Wraps a file stream and prepends [BREAKOUT] to every line written."""
    def __init__(self, stream):
        self._stream = stream
    def write(self, msg):
        if msg and msg != '\n':
            lines = msg.split('\n')
            prefixed = []
            for line in lines:
                if line:
                    prefixed.append(f"[BREAKOUT] {line}")
                else:
                    prefixed.append(line)
            self._stream.write('\n'.join(prefixed))
        else:
            self._stream.write(msg)
    def flush(self):
        self._stream.flush()
    def fileno(self):
        return self._stream.fileno()

sys.stdout = _PrefixedLogger(sys.stdout)
sys.stderr = _PrefixedLogger(sys.stderr)

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
#
#  Breakout + Retest (BRT) Strategy
#  ──────────────────────────────────
#  Logic:
#    1. Identify a significant swing high/low level from the last 30 candles
#       (must be touched/rejected at least twice = confirmed S/R)
#    2. A breakout candle closes convincingly beyond the level (≥ 0.5×ATR body)
#    3. The very next 1–4 candles retest the broken level from the other side
#    4. Retest candle closes back away from the level (confirmation)
#    5. Entry on next candle
#    6. SL: beyond the retest candle wick (level should hold)
#    7. TP: next structural swing on the other side
#
#  Why this works:
#    - S/R flip is one of the most reliable price action setups
#    - Retest confirmation eliminates fake breakouts
#    - Previous S/R becomes new S/R — gives clean structural TP targets
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
SIGNAL_COOLDOWN_HR = 6
LTF_TIMEFRAME      = "15min"
LTF_CANDLES        = 80
ATR_PERIOD         = 14
LEVEL_LOOKBACK     = 30        # candles to look back for S/R level
LEVEL_TOUCH_BUFFER = 0.3       # level must be touched within 0.3×ATR
MIN_TOUCHES        = 2         # level must have been touched at least twice
BREAKOUT_BODY_ATR  = 0.5       # breakout candle body must be ≥ 0.5×ATR
RETEST_MAX_CANDLES = 4         # retest must occur within 4 candles of breakout
MIN_RR             = 1.5
MIN_SL_PIPS        = 3.0
MAX_SL_PIPS        = 200.0
CONFIDENCE_BASE    = 77
STRATEGY_NAME      = "Tekton-BRT-v1"

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
            json={"chat_id": chat_id, "text": f"📈 *BRT Signal*\n{msg}", "parse_mode": "Markdown"},
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
            pip_pos     = s.get("pipPosition")
            specs[sym] = {
                "pip_size":    10 ** (-pip_pos),
                "price_scale": 100000,  # cTrader trendbar raw integers are always price × 100,000
            }
        _symbol_specs_cache = specs
        _specs_cache_ts     = now
        print(f"[{_ts()}] 📋 Bridge specs loaded: {len(specs)} symbols")
        return specs
    except Exception as e:
        raise RuntimeError(f"❌ Failed to load bridge specs: {e}") from e

def get_pip_info(symbol):
    """Raises if symbol not found — no hardcoded fallbacks."""
    specs = get_symbol_specs()
    if symbol not in specs:
        raise ValueError(f"❌ Symbol {symbol} not found in bridge specs — cannot trade")
    return specs[symbol]["pip_size"], specs[symbol]["price_scale"]

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

def find_sr_levels(df, atr_val):
    """
    Find significant S/R levels in the lookback window.
    A level qualifies if at least MIN_TOUCHES candle highs or lows
    touched it within LEVEL_TOUCH_BUFFER × ATR.
    Returns list of (price, type) where type is 'resistance' or 'support'.
    """
    scan = df.iloc[-LEVEL_LOOKBACK:].reset_index(drop=True)
    buf  = atr_val * LEVEL_TOUCH_BUFFER
    levels = []

    # Resistance: clusters around swing highs
    highs = scan["high"].values
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            level = highs[i]
            touches = sum(1 for h in highs if abs(h - level) <= buf)
            if touches >= MIN_TOUCHES:
                levels.append((level, "resistance"))

    # Support: clusters around swing lows
    lows = scan["low"].values
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            level = lows[i]
            touches = sum(1 for l in lows if abs(l - level) <= buf)
            if touches >= MIN_TOUCHES:
                levels.append((level, "support"))

    return levels

def find_swing_tp(df, direction, entry_price, sl_pips, pip_size):
    """Find next structural target beyond entry for TP."""
    scan = df.iloc[-40:].reset_index(drop=True)
    min_tp_pips = sl_pips * MIN_RR

    if direction == "BUY":
        candidates = []
        for i in range(2, len(scan) - 2):
            h = scan["high"].iloc[i]
            if (h > scan["high"].iloc[i-1] and h > scan["high"].iloc[i+1]
                    and h > entry_price):
                candidates.append(h)
        for target in sorted(candidates):
            tp_pips = (target - entry_price) / pip_size
            if tp_pips >= min_tp_pips:
                return round(tp_pips, 1)
    else:
        candidates = []
        for i in range(2, len(scan) - 2):
            l = scan["low"].iloc[i]
            if (l < scan["low"].iloc[i-1] and l < scan["low"].iloc[i+1]
                    and l < entry_price):
                candidates.append(l)
        for target in sorted(candidates, reverse=True):
            tp_pips = (entry_price - target) / pip_size
            if tp_pips >= min_tp_pips:
                return round(tp_pips, 1)

    # Fallback: MIN_RR × SL
    return round(sl_pips * MIN_RR, 1)

def get_active_symbols():
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data WHERE timeframe=%s
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
    if df is None or len(df) < LEVEL_LOOKBACK + 10:
        return

    atr_val = calc_atr(df)
    if atr_val <= 0:
        return

    levels = find_sr_levels(df.iloc[:-5], atr_val)  # find levels excluding last 5 candles
    if not levels:
        return

    # Work with the last 5 candles as "recent action"
    recent = df.iloc[-5:].reset_index(drop=True)
    c_curr = df.iloc[-1]
    c_prev = df.iloc[-2]

    for level_price, level_type in levels:
        # ── Check for breakout candle (2–6 candles ago) ──────────────────────
        for bo_idx in range(1, min(6, len(df) - 1)):
            bo_candle = df.iloc[-(bo_idx + 1)]
            body_size = abs(bo_candle["close"] - bo_candle["open"])

            if body_size < atr_val * BREAKOUT_BODY_ATR:
                continue  # body too small — not a convincing breakout

            # Bullish breakout of resistance
            if (level_type == "resistance"
                    and bo_candle["close"] > level_price
                    and bo_candle["open"]  < level_price):
                direction = "BUY"

            # Bearish breakout of support
            elif (level_type == "support"
                    and bo_candle["close"] < level_price
                    and bo_candle["open"]  > level_price):
                direction = "SELL"
            else:
                continue

            # ── Check for retest in candles AFTER the breakout ───────────────
            post_bo = df.iloc[-(bo_idx):]
            retest_confirmed = False
            retest_candle    = None

            for rt_idx in range(len(post_bo)):
                rt = post_bo.iloc[rt_idx]
                buf = atr_val * LEVEL_TOUCH_BUFFER

                if direction == "BUY":
                    # Retest: low touches the broken resistance (now support)
                    # but close remains above it
                    if (rt["low"] <= level_price + buf
                            and rt["close"] >= level_price - buf):
                        retest_confirmed = True
                        retest_candle    = rt
                        break
                else:
                    if (rt["high"] >= level_price - buf
                            and rt["close"] <= level_price + buf):
                        retest_confirmed = True
                        retest_candle    = rt
                        break

            if not retest_confirmed or retest_candle is None:
                continue

            # Only act if the retest is recent (within last 2 candles)
            if rt_idx > RETEST_MAX_CANDLES:
                continue

            if is_on_cooldown(symbol, direction):
                print(f"[{_ts()}] ⏳ COOLDOWN: {symbol} {direction}")
                return

            # ── SL / TP ───────────────────────────────────────────────────────
            if direction == "BUY":
                sl_price = retest_candle["low"] - atr_val * 0.2
                entry    = c_curr["close"]
            else:
                sl_price = retest_candle["high"] + atr_val * 0.2
                entry    = c_curr["close"]

            sl_pips = abs(entry - sl_price) / pip_size
            if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
                continue

            tp_pips = find_swing_tp(df, direction, entry, sl_pips, pip_size)
            if tp_pips <= 0:
                continue
            if sl_pips > 0 and (tp_pips / sl_pips) < MIN_RR:
                continue

            rr         = round(tp_pips / sl_pips, 2)
            level_pips = round(level_price / pip_size, 1)
            confidence = min(CONFIDENCE_BASE + int(rr * 2), 92)
            reason     = (f"BRT {direction} level={level_price:.5f} "
                          f"ATR={round(atr_val/pip_size,1)}p RR={rr}")

            insert_signal(symbol, direction, sl_pips, tp_pips, confidence, reason)
            return  # one signal per symbol per scan


def main():
    print(f"[{_ts()}] 🧠 Breakout+Retest Strategy Active. [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        if not is_market_open():
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 💤 MARKET CLOSED (Fri 16:00–Sun 22:00 UTC) — sleeping 5 min.")
            time.sleep(300)
            continue
        print(f"[{_ts()}] 🧠 BRT scan started")
        try:
            symbols = get_active_symbols()
            print(f"[{_ts()}] 📊 {len(symbols)} symbols")
            for sym in symbols:
                try:
                    scan_symbol(sym)
                except Exception as e:
                    print(f"[{_ts()}] ⚠️ {sym}: {e}")
            print(f"[{_ts()}] ✅ BRT scan done")
        except Exception as e:
            print(f"[{_ts()}] ❌ BRT ERROR: {e}")
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

