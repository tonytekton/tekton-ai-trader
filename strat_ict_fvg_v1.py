import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

# This redirects all 'print' statements to a dedicated log file
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
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
    """Returns a dict of { symbol: { pip_size, price_scale } } from the bridge."""
    global _symbol_specs_cache, _specs_cache_ts

    now = time.time()
    if _symbol_specs_cache and (now - _specs_cache_ts) < SPECS_CACHE_TTL:
        return _symbol_specs_cache

    try:
        resp = requests.get(
            f"{BRIDGE_URL}/symbols/list",
            headers={"X-Bridge-Key": BRIDGE_KEY},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        symbols = data.get("symbols", data) if isinstance(data, dict) else data

        specs = {}
        for s in symbols:
            sym_name = s.get("name") or s.get("symbolName", "")
            pip_pos  = s.get("pipPosition", 4)
            # pip_size = 10^-pipPosition (real pip value, e.g. EURUSD=0.0001, XBRUSD=0.01)
            pip_size     = 1.0 if pip_pos == 1 else 10 ** (-pip_pos)  # pip_pos=1 → indices, 1 pip = 1.0
            # price_scale = 100000 ALWAYS — the bridge historical API returns raw integers
            # where raw / 100000 = real price for ALL symbols (FX, JPY, indices, commodities)
            # e.g. EURUSD raw=116411 → 116411/100000 = 1.16411 ✅
            # e.g. XBRUSD raw=6130000 → 6130000/100000 = 61.30 ✅
            # e.g. F40 raw=813440000 → 813440000/100000 = 8134.4 ✅
            price_scale  = 100000
            specs[sym_name] = {
                "pip_size":    pip_size,
                "price_scale": price_scale,
            }

        _symbol_specs_cache = specs
        _specs_cache_ts = now
        print(f"📋 Bridge specs loaded for {len(specs)} symbols")
        return specs

    except Exception as e:
        print(f"❌ Bridge specs UNAVAILABLE — skipping scan cycle: {e} — falling back to defaults")
        return {}


def get_pip_size_and_scale(symbol):
    """
    Returns (pip_size, price_scale) for a symbol.
    Falls back to hardcoded defaults if bridge is unavailable.
    """
    specs = get_symbol_specs()
    if symbol in specs:
        return specs[symbol]["pip_size"], specs[symbol]["price_scale"]

    # Hardcoded fallback (last resort)
    # Fallback: price_scale is ALWAYS 100000 for all symbols
    # pip_size = 10^-pipPosition
    fallback = {
        "XAUUSD": (0.01,   100000),  # pipPos=2
        "XAGUSD": (0.01,   100000),  # pipPos=2
        "XTIUSD": (0.01,   100000),  # pipPos=2
        "XBRUSD": (0.01,   100000),  # pipPos=2
        "US30":   (0.1,    100000),  # pipPos=1
        "US500":  (0.1,    100000),  # pipPos=1
        "USTEC":  (0.1,    100000),  # pipPos=1
        "UK100":  (0.1,    100000),  # pipPos=1
        "DE40":   (0.1,    100000),  # pipPos=1
        "JP225":  (0.1,    100000),  # pipPos=1
        "F40":    (0.1,    100000),  # pipPos=1
        "AUS200": (0.1,    100000),  # pipPos=1
        "STOXX50":(0.1,    100000),  # pipPos=1
    }
    if symbol.endswith("JPY"):
        return (0.01, 100000)  # JPY pairs: pipPos=2, price_scale=100000
    return fallback.get(symbol, (0.0001, 100000))  # FX default: pipPos=4, price_scale=100000


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
        """, (symbol, 'Tekton-SMC-v1', direction, LTF_TIMEFRAME, int(confidence), float(sl_pips), float(tp_pips)))
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

    try:
        get_symbol_specs()  # pre-check — raises if bridge specs unavailable
    except Exception as spec_err:
        print(f"[{_ts()}] ❌ BRIDGE SPECS FAILED — skipping scan cycle. Check /symbols/list endpoint. Error: {spec_err}")
        return
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


if __name__ == "__main__":
    notify("🛡️ Tekton AI Strategy Engine Started Successfully.")

    while True:
        run_strategy()
        time.sleep(300)
