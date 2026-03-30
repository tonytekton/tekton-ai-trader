import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

# This redirects all 'print' statements to a dedicated log file
_log_file = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stdout = _log_file
sys.stderr = _log_file
class _PrefixedLogger:
    """Wraps a file stream and prepends [ICT-FVG] to every line written."""
    def __init__(self, stream):
        self._stream = stream
    def write(self, msg):
        if msg and msg != '\n':
            lines = msg.split('\n')
            prefixed = []
            for i, line in enumerate(lines):
                if line:
                    prefixed.append(f"[ICT-FVG] {line}")
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

sys.stderr = sys.stdout  # Also capture errors
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- DB CONFIG ---
DB_PARAMS = {
    "host": os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user": "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD")
}

# --- BRIDGE CONFIG ---
BRIDGE_URL  = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY  = os.getenv("BRIDGE_KEY", "")

# ─── TIMEFRAME CONFIG ─────────────────────────────────────────────────────────
# Change these to run the strategy on a different timeframe pair.
# Valid values: "5min", "15min", "60min", "4H", "Daily"
LTF_TIMEFRAME  = "15min"   # Entry timeframe — where signals fire
HTF_TIMEFRAME  = "60min"   # Trend filter timeframe — must agree with entry
STRATEGY_NAME  = "Tekton-FVG-v1"
# ─────────────────────────────────────────────────────────────────────────────

# Cache bridge specs so we don't hammer the bridge on every scan
_symbol_specs_cache = {}
_specs_cache_ts = 0
SPECS_CACHE_TTL = 300  # seconds

# Track notified ignored signals to prevent spam
last_notified_ignored = {}

# ---------------------------------------------------------------------------
# BRIDGE SPECS — fetch pipPosition and price scale for every symbol
# ---------------------------------------------------------------------------
def get_symbol_specs():
    """Returns a dict of { symbol: { pip_size, price_scale } } from the bridge.
    Raises on failure — no silent fallbacks.
    """
    global _symbol_specs_cache, _specs_cache_ts

    now = time.time()
    if _symbol_specs_cache and (now - _specs_cache_ts) < SPECS_CACHE_TTL:
        return _symbol_specs_cache

    resp = requests.get(
        f"{BRIDGE_URL}/symbols/list",
        headers={"X-Bridge-Key": BRIDGE_KEY},
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    symbols = data.get("symbols", data) if isinstance(data, dict) else data

    if not symbols:
        raise ValueError("❌ Bridge returned 0 symbols from /symbols/list — refusing to trade")

    specs = {}
    for s in symbols:
        sym_name = s.get("name") or s.get("symbolName", "")
        if not sym_name:
            continue
        pip_pos = s.get("pipPosition")
        if pip_pos is None:
            raise ValueError(f"❌ pipPosition missing for symbol {sym_name} — cannot calculate pip size")
        pip_size    = 10 ** (-pip_pos)
        price_scale = 100000  # cTrader trendbar raw integers are always price × 100,000
        specs[sym_name] = {
            "pip_size":    pip_size,
            "price_scale": price_scale,
        }

    _symbol_specs_cache = specs
    _specs_cache_ts = now
    print(f"📋 Bridge specs loaded for {len(specs)} symbols")
    return specs


def get_pip_size_and_scale(symbol):
    """
    Returns (pip_size, price_scale) for a symbol.
    Raises if symbol not found — no hardcoded fallbacks.
    """
    specs = get_symbol_specs()
    if symbol not in specs:
        raise ValueError(f"❌ Symbol {symbol} not found in bridge specs — cannot trade")
    return specs[symbol]["pip_size"], specs[symbol]["price_scale"]


# ---------------------------------------------------------------------------
# NOTIFICATIONS
# ---------------------------------------------------------------------------
def notify(msg):
    """Sends a formatted notification to your Telegram bot."""
    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️ Telegram credentials missing in .env")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       f"🧠 *Strategy Update:*\n{msg}",
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")


# ---------------------------------------------------------------------------
# MARKET DATA
# ---------------------------------------------------------------------------
def get_market_data(symbol, timeframe, limit=100):
    """Fetches OHLC from DB and scales raw cTrader integers to real prices."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        query = """
            SELECT timestamp, open, high, low, close
            FROM market_data
            WHERE symbol = %s AND timeframe = %s
            ORDER BY timestamp DESC LIMIT %s
        """
        df = pd.read_sql(query, conn, params=(symbol, timeframe, limit))
        conn.close()

        if df.empty:
            return df

        df = df.sort_values('timestamp').reset_index(drop=True)

        # Scale raw cTrader integers → real prices
        _, price_scale = get_pip_size_and_scale(symbol)
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col] / price_scale

        return df

    except Exception as e:
        print(f"❌ DB Read Error: {e}")
        return None


# ---------------------------------------------------------------------------
# HTF TREND FILTER
# ---------------------------------------------------------------------------
def is_htf_aligned(symbol, direction):
    """Checks 1-hour trend to ensure we aren't trading against the big move."""
    df_htf = get_market_data(symbol, HTF_TIMEFRAME, limit=20)
    if df_htf is None or len(df_htf) < 10:
        return True

    htf_avg      = df_htf['close'].mean()
    current_price = df_htf['close'].iloc[-1]

    if direction == "BUY"  and current_price > htf_avg: return True
    if direction == "SELL" and current_price < htf_avg: return True
    return False


# ---------------------------------------------------------------------------
# SIGNAL DETECTION — prices are already scaled to real values here
# ---------------------------------------------------------------------------
def detect_structures(df, symbol):
    """ICT FVG + MSS logic. All prices are real (already scaled)."""
    if len(df) < 15:
        return None

    pip_size, _ = get_pip_size_and_scale(symbol)
    current_close = float(df['close'].iloc[-1])

    # BULLISH MSS + FVG
    fvg_bullish = df['low'].iloc[-1] > df['high'].iloc[-3]
    if current_close > float(df['high'].iloc[-3]) and fvg_bullish:
        fvg_low  = float(df['high'].iloc[-3])
        fvg_high = float(df['low'].iloc[-1])
        sl_price = fvg_low - (fvg_high - fvg_low) * 0.5
        sl_pips  = round((current_close - sl_price) / pip_size, 1)
        tp_pips  = round(sl_pips * 1.8, 1)
        return {
            "type":       "BUY",
            "reason":     "Strong MSS + Bullish FVG",
            "confidence": 88,
            "sl_pips":    sl_pips,
            "tp_pips":    tp_pips
        }

    # BEARISH MSS + FVG
    fvg_bearish = df['high'].iloc[-1] < df['low'].iloc[-3]
    if current_close < float(df['low'].iloc[-3]) and fvg_bearish:
        fvg_high = float(df['low'].iloc[-3])
        fvg_low  = float(df['high'].iloc[-1])
        sl_price = fvg_high + (fvg_high - fvg_low) * 0.5
        sl_pips  = round((sl_price - current_close) / pip_size, 1)
        tp_pips  = round(sl_pips * 1.8, 1)
        return {
            "type":       "SELL",
            "reason":     "Strong MSS + Bearish FVG",
            "confidence": 88,
            "sl_pips":    sl_pips,
            "tp_pips":    tp_pips
        }

    return None


# ---------------------------------------------------------------------------
# SIGNAL INSERT
# ---------------------------------------------------------------------------
def send_signal(symbol, direction, reason, confidence, sl_pips, tp_pips):
    """Inserts a validated signal with SL/TP into the database."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO signals (symbol, strategy, signal_type, timeframe, confidence_score, status, sl_pips, tp_pips)
            VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s)
            ON CONFLICT DO NOTHING;
        """, (symbol, STRATEGY_NAME, direction, LTF_TIMEFRAME, int(confidence), float(sl_pips), float(tp_pips)))
        conn.commit()
        cur.close()
        conn.close()
        print(f"📡 SIGNAL SAVED: {direction} {symbol} | SL: {sl_pips}p | TP: {tp_pips}p | Conf: {confidence}%")
    except Exception as e:
        print(f"❌ Signal Insert Error: {e}")


# ---------------------------------------------------------------------------
# ACTIVE SYMBOLS
# ---------------------------------------------------------------------------
def get_active_symbols():
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data
            WHERE timeframe = %s
            GROUP BY symbol
            HAVING COUNT(*) > 20;
        """, (LTF_TIMEFRAME,))
        symbols = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return symbols
    except Exception as e:
        print(f"⚠️ Could not fetch dynamic symbols: {e}")
        return ["EURUSD", "GBPUSD", "XAUUSD"]


# ---------------------------------------------------------------------------
# MAIN SCAN LOOP
# ---------------------------------------------------------------------------
def run_strategy():
    print(f"🧠 AI Brain Active [{datetime.now().strftime('%H:%M:%S')}] - Scanning Market...")

    symbols = get_active_symbols()
    print(f"📊 Scanning {len(symbols)} active symbols found in database...")

    for symbol in symbols:
        df = get_market_data(symbol, LTF_TIMEFRAME)
        if df is None or df.empty:
            continue

        signal = detect_structures(df, symbol)
        if signal:
            direction = signal['type']
            sl_pips   = signal['sl_pips']
            tp_pips   = signal['tp_pips']

            # Guard: skip if SL/TP is zero or negative
            if sl_pips <= 0 or tp_pips <= 0:
                print(f"⚠️ Skipping {symbol}: invalid SL={sl_pips} TP={tp_pips}")
                continue

            if is_htf_aligned(symbol, direction):
                send_signal(symbol, direction, signal['reason'], signal['confidence'], sl_pips, tp_pips)
                msg = (f"✅ *SIGNAL ACCEPTED*\nSymbol: `{symbol}`\nAction: *{direction}*\n"
                       f"Reason: {signal['reason']}\nSL: `{sl_pips}p` | TP: `{tp_pips}p`")
                notify(msg)
            else:
                log_msg = f"⏳ Signal filtered: {symbol} {direction} ignored (HTF Trend mismatch)"
                print(log_msg)

                current_time = time.time()
                key = f"{symbol}_{direction}"
                if current_time - last_notified_ignored.get(key, 0) > 3600:
                    notify(f"⚠️ *SIGNAL IGNORED*\n{log_msg}")
                    last_notified_ignored[key] = current_time

    print(f"✅ Scan complete [{datetime.now().strftime('%H:%M:%S')}]")



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
    notify("🛡️ Tekton AI Strategy Engine Started Successfully.")

    while True:
        now_utc = datetime.utcnow()
        if not is_market_open():
            print(f"💤 MARKET CLOSED (Fri 16:00–Sun 22:00 UTC) — sleeping 5 min.")
            time.sleep(300)
            continue
        run_strategy()
        time.sleep(300)
