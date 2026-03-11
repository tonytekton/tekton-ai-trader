import psycopg2
import pandas as pd
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

# This redirects all 'print' statements to a dedicated log file
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a')
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

# --- PIP SIZE MAP (overrides for non-standard pairs) ---
PIP_SIZE_MAP = {
    "XAUUSD": 0.1,    # Gold: 1 pip = 0.1
    "XAGUSD": 0.01,   # Silver
    "XTIUSD": 0.01,   # WTI Oil
    "XBRUSD": 0.01,   # Brent Oil
    "US30":   1.0,    # Dow Jones
    "US500":  0.1,    # S&P 500
    "USTEC":  0.1,    # Nasdaq
    "UK100":  0.1,
    "DE40":   0.1,
    "JP225":  1.0,
}
DEFAULT_PIP_SIZE = 0.0001  # Standard forex (4-decimal pairs)

# Track notified ignored signals to prevent spam
last_notified_ignored = {}

def get_pip_size(symbol):
    """Returns the pip size for a given symbol."""
    # JPY pairs are 2-decimal
    if symbol.endswith("JPY") and symbol not in PIP_SIZE_MAP:
        return 0.01
    return PIP_SIZE_MAP.get(symbol, DEFAULT_PIP_SIZE)

def notify(msg):
    """Sends a formatted notification to your Telegram bot."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️ Telegram credentials missing in .env")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": f"🧠 *Strategy Update:*\n{msg}",
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def get_market_data(symbol, timeframe, limit=100):
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
        return df.sort_values('timestamp').reset_index(drop=True)
    except Exception as e:
        print(f"❌ DB Read Error: {e}")
        return None

def is_htf_aligned(symbol, direction):
    """Checks 1-hour trend to ensure we aren't trading against the big move."""
    df_htf = get_market_data(symbol, "60min", limit=20)
    if df_htf is None or len(df_htf) < 10: return True

    htf_avg = df_htf['close'].mean()
    current_price = df_htf['close'].iloc[-1]

    if direction == "BUY" and current_price > htf_avg: return True
    if direction == "SELL" and current_price < htf_avg: return True
    return False

def detect_structures(df, symbol):
    """Advanced SMC Logic: Strong Fractals + MSS + FVG. Calculates SL/TP in pips."""
    if len(df) < 15: return None

    current_close = df['close'].iloc[-1]
    pip_size = get_pip_size(symbol)

    # BULLISH MSS + FVG
    fvg_bullish = df['low'].iloc[-1] > df['high'].iloc[-3]
    if current_close > df['high'].iloc[-3] and fvg_bullish:
        fvg_low  = df['high'].iloc[-3]
        fvg_high = df['low'].iloc[-1]
        # SL = below the FVG low with a small buffer (half the FVG height)
        sl_price = fvg_low - (fvg_high - fvg_low) * 0.5
        sl_pips  = round((current_close - sl_price) / pip_size, 1)
        tp_pips  = round(sl_pips * 1.8, 1)
        return {
            "type": "BUY",
            "reason": "Strong MSS + Bullish FVG",
            "confidence": 88,
            "sl_pips": sl_pips,
            "tp_pips": tp_pips
        }

    # BEARISH MSS + FVG
    fvg_bearish = df['high'].iloc[-1] < df['low'].iloc[-3]
    if current_close < df['low'].iloc[-3] and fvg_bearish:
        fvg_high = df['low'].iloc[-3]
        fvg_low  = df['high'].iloc[-1]
        # SL = above the FVG high with a small buffer (half the FVG height)
        sl_price = fvg_high + (fvg_high - fvg_low) * 0.5
        sl_pips  = round((sl_price - current_close) / pip_size, 1)
        tp_pips  = round(sl_pips * 1.8, 1)
        return {
            "type": "SELL",
            "reason": "Strong MSS + Bearish FVG",
            "confidence": 88,
            "sl_pips": sl_pips,
            "tp_pips": tp_pips
        }

    return None

def send_signal(symbol, direction, reason, confidence, sl_pips, tp_pips):
    """Inserts a validated signal with SL/TP into the database."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO signals (symbol, strategy, signal_type, timeframe, confidence_score, status, sl_pips, tp_pips)
            VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s)
            ON CONFLICT DO NOTHING;
        """, (symbol, 'Tekton-SMC-v1', direction, "15min", confidence, sl_pips, tp_pips))
        conn.commit()
        cur.close()
        conn.close()
        print(f"📡 SIGNAL SAVED: {direction} {symbol} | SL: {sl_pips}p | TP: {tp_pips}p | Conf: {confidence}%")
    except Exception as e:
        print(f"❌ Signal Insert Error: {e}")

def get_active_symbols():
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data
            WHERE timeframe = '15min'
            GROUP BY symbol
            HAVING COUNT(*) > 20;
        """)
        symbols = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return symbols
    except Exception as e:
        print(f"⚠️ Could not fetch dynamic symbols: {e}")
        return ["EURUSD", "GBPUSD", "XAUUSD"]

def run_strategy():
    print(f"🧠 AI Brain Active [{datetime.now().strftime('%H:%M:%S')}] - Scanning Market...")

    symbols = get_active_symbols()
    print(f"📊 Scanning {len(symbols)} active symbols found in database...")

    for symbol in symbols:
        df = get_market_data(symbol, "15min")
        if df is None or df.empty: continue

        signal = detect_structures(df, symbol)
        if signal:
            direction = signal['type']
            sl_pips   = signal['sl_pips']
            tp_pips   = signal['tp_pips']

            # Guard: skip if SL/TP calculated as zero or negative
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

if __name__ == "__main__":
    notify("🛡️ Tekton AI Strategy Engine Started Successfully.")

    while True:
        run_strategy()
        time.sleep(300)
