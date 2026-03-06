import os
import requests
import psycopg2
from datetime import datetime

# --- CONFIGURATION ---
DB_HOST = "172.16.64.3"
DB_NAME = "tekton-trader"
DB_USER = "postgres" 
DB_PASS = ")^](XFrJ0@6zUcc{" # <--- Your DB password
BRIDGE_URL = "http://localhost:8080/prices/historical"
BRIDGE_KEY = "DVj7Y1Ax0kI93qEdCC6vqVh74WykbOpyeYDGduVf" # <--- Your Bridge Key

# The timeframes based exactly on your DB schema
TIMEFRAMES = ["5min", "15min", "60min", "4H", "Daily"] 

def run_backfill():
    print("🚀 Starting Dynamic Historical Data Gap Fill...")
    
    # 1. Connect to Database
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()

    # 2. Automatically find all 50+ symbols in your database
    cur.execute("SELECT DISTINCT symbol FROM market_data ORDER BY symbol;")
    symbols = [row[0] for row in cur.fetchall()]
    print(f"🔍 Found {len(symbols)} unique symbols in the database. Commencing gap fill...")

    # 3. Loop through every symbol and timeframe
    for symbol in symbols:
        for tf in TIMEFRAMES:
            try:
                # Find the exact gap for this symbol/timeframe
                cur.execute("SELECT MAX(timestamp) FROM market_data WHERE symbol = %s AND timeframe = %s", (symbol, tf))
                last_time = cur.fetchone()[0]
                
                if not last_time:
                    continue 
                    
                print(f"📊 Fetching {symbol} ({tf}) since {last_time}...")

                # 4. Ask the Bridge for the missing candles
                payload = {
                    "symbol": symbol,
                    "timeframe": tf, 
                    "from_timestamp": int(last_time.timestamp() * 1000)
                }
                
                headers = {"X-Bridge-Key": BRIDGE_KEY}
                res = requests.post(BRIDGE_URL, json=payload, headers=headers)
                
                if res.status_code == 200:
                    data = res.json()
                    candles = data.get("candles", [])
                    inserted = 0
                    
                    if not candles:
                        print(f"⚠️ No new candles to fetch for {symbol} {tf}")
                        continue
                        
                    # 5. Insert into the database using 'volume' instead of 'tick_volume'
                    for c in candles:
                        dt_timestamp = datetime.fromtimestamp(c["timestamp"] / 1000.0)
                        
                        cur.execute("""
                            INSERT INTO market_data (symbol, timeframe, timestamp, open, high, low, close, volume)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING;
                        """, (
                            symbol, 
                            tf, 
                            dt_timestamp, 
                            c["open_raw"], 
                            c["high_raw"], 
                            c["low_raw"], 
                            c["close_raw"], 
                            c["volume"]
                        ))
                        inserted += 1
                        
                    conn.commit()
                    if inserted > 0:
                        print(f"✅ Saved {inserted} missing candles for {symbol} {tf}.")
                else:
                    print(f"❌ Bridge returned error {res.status_code} for {symbol}: {res.text}")
                    
            except Exception as e:
                print(f"❌ Error fetching {symbol} {tf}: {e}")
                conn.rollback() # <--- THIS PREVENTS THE CHAIN REACTION CRASH

    cur.close()
    conn.close()
    print("🏁 Backfill Complete! The AI memory gap is completely closed.")

if __name__ == "__main__":
    run_backfill()
