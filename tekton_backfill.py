import os
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
DB_HOST    = os.getenv("CLOUD_SQL_HOST", "172.16.64.3")
DB_NAME    = "tekton-trader"
DB_USER    = os.getenv("CLOUD_SQL_DB_USER", "postgres")
DB_PASS    = os.getenv("CLOUD_SQL_DB_PASSWORD")
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8080") + "/prices/historical"
BRIDGE_KEY = os.getenv("BRIDGE_KEY", "")

# Timeframes stored in market_data
TIMEFRAMES = ["5min", "15min", "60min", "4H", "Daily"]

# ─── BACKFILL ──────────────────────────────────────────────────────────────────

def run_backfill():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Starting backfill gap fill...")

    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME,
                                user=DB_USER, password=DB_PASS)
        cur  = conn.cursor()
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ DB connection failed: {e}")
        return

    # Get all symbols currently in the DB
    cur.execute("SELECT DISTINCT symbol FROM market_data ORDER BY symbol;")
    symbols = [row[0] for row in cur.fetchall()]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 {len(symbols)} symbols found")

    total_inserted = 0

    for symbol in symbols:
        for tf in TIMEFRAMES:
            try:
                # Find the gap — last candle we have for this symbol+timeframe
                cur.execute(
                    "SELECT MAX(timestamp) FROM market_data WHERE symbol=%s AND timeframe=%s",
                    (symbol, tf)
                )
                last_time = cur.fetchone()[0]

                if not last_time:
                    continue

                payload = {
                    "symbol":         symbol,
                    "timeframe":      tf,
                    "from_timestamp": int(last_time.timestamp() * 1000) + 1  # +1ms excludes the candle we already have
                }

                res = requests.post(
                    BRIDGE_URL,
                    json=payload,
                    headers={"X-Bridge-Key": BRIDGE_KEY},
                    timeout=15
                )

                if res.status_code == 200:
                    candles = res.json().get("candles", [])
                    if not candles:
                        continue

                    inserted = 0
                    for c in candles:
                        dt = datetime.fromtimestamp(c["timestamp"] / 1000.0)
                        cur.execute("""
                            INSERT INTO market_data
                              (symbol, timeframe, timestamp, open, high, low, close, volume)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT DO NOTHING;
                        """, (symbol, tf, dt,
                              c["open_raw"], c["high_raw"],
                              c["low_raw"],  c["close_raw"],
                              c.get("volume", 0)))
                        inserted += 1

                    conn.commit()
                    if inserted > 0:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {symbol} {tf}: +{inserted} candles")
                        total_inserted += inserted
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  {symbol} {tf}: bridge {res.status_code}")

            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {symbol} {tf}: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass

    cur.close()
    conn.close()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🏁 Backfill complete. Total inserted: {total_inserted} candles")


if __name__ == "__main__":
    run_backfill()
