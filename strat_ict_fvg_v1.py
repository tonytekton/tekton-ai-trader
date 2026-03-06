import psycopg2
import pandas as pd
import os, time, requests  # ADDED: requests for Telegram
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

# Track notified ignored signals to prevent spam
last_notified_ignored = {}

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
        # Added timeout to prevent strategy from hanging if Telegram is slow
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

def detect_structures(df):
    """Advanced SMC Logic: Strong Fractals + MSS + FVG."""
    if len(df) < 15: return None
    
    # Candle at index -3 must be higher than -5, -4 AND -2, -1
    c = df.iloc[-3]['high']
    is_strong_swing_high = (c > df.iloc[-1]['high'] and c > df.iloc[-2]['high'] and 
                            c > df.iloc[-4]['high'] and c > df.iloc[-5]['high'])
    
    l = df.iloc[-3]['low']
    is_strong_swing_low = (l < df.iloc[-1]['low'] and l < df.iloc[-2]['low'] and 
                           l < df.iloc[-4]['low'] and l < df.iloc[-5]['low'])

    current_close = df['close'].iloc[-1]
    
    # BULLISH MSS + FVG
    fvg_bullish = df['low'].iloc[-1] > df['high'].iloc[-3]
    if current_close > df['high'].iloc[-3] and fvg_bullish:
        return {"type": "BUY", "reason": "Strong MSS + Bullish FVG", "confidence": 88}

    # BEARISH MSS + FVG
    fvg_bearish = df['high'].iloc[-1] < df['low'].iloc[-3]
    if current_close < df['low'].iloc[-3] and fvg_bearish:
        return {"type": "SELL", "reason": "Strong MSS + Bearish FVG", "confidence": 88}

    return None

def send_signal(symbol, direction, reason, confidence):
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO signals (symbol, strategy, signal_type, timeframe, confidence_score, status)
            VALUES (%s, %s, %s, %s, %s, 'PENDING')
            ON CONFLICT DO NOTHING;
        """, (symbol, 'Tekton-SMC-v1', direction, "15min", confidence))
        conn.commit()
        cur.close()
        conn.close()
        print(f"📡 SIGNAL SAVED: {direction} {symbol} | Reason: {reason} | Conf: {confidence}%")
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

        signal = detect_structures(df)
        if signal:
            direction = signal['type']
            
            # --- TELEGRAM INTEGRATION ---
            if is_htf_aligned(symbol, direction):
                # Signal is valid and passing trend filters
                send_signal(symbol, direction, signal['reason'], signal['confidence'])
                
                # Notify on successful Signal generation
                msg = f"✅ *SIGNAL ACCEPTED*\nSymbol: `{symbol}`\nAction: *{direction}*\nReason: {signal['reason']}"
                notify(msg)
            else:
                # Signal failed HTF Trend Alignment
                log_msg = f"⏳ Signal filtered: {symbol} {direction} ignored (HTF Trend mismatch)"
                print(log_msg)
                
                # Check if we've already notified for this specific symbol/direction in the last hour
                # This prevents Telegram spam while the mismatch persists.
                current_time = time.time()
                key = f"{symbol}_{direction}"
                if current_time - last_notified_ignored.get(key, 0) > 3600:
                    notify(f"⚠️ *SIGNAL IGNORED*\n{log_msg}")
                    last_notified_ignored[key] = current_time

if __name__ == "__main__":
    # Test notification on start
    notify("🛡️ Tekton AI Strategy Engine Started Successfully.")
    
    while True:
        run_strategy()
        time.sleep(300) # Standard 5-minute scan interval
