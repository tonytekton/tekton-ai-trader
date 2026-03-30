#!/usr/bin/env python3
"""
One-shot backfill script — fetches last 200 candles per symbol × timeframe
and upserts into market_data. Run once to catch up after the 6-day gap.
Usage: python3 backfill_now.py
"""
import requests, psycopg2, os, time, sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/tekton-ai-trader/.env"))

BRIDGE_URL = f"http://localhost:8080"
BRIDGE_KEY = os.getenv("BRIDGE_KEY", "")
HEADERS    = {"X-Bridge-Key": BRIDGE_KEY, "Content-Type": "application/json"}
TIMEFRAMES = ["5min", "15min", "60min", "4H", "Daily"]
CANDLES    = 200  # enough to cover 6-day gap for all TFs

def get_db():
    return psycopg2.connect(
        host=os.getenv("CLOUD_SQL_HOST"),
        database=os.getenv("CLOUD_SQL_DB_NAME"),
        user=os.getenv("CLOUD_SQL_DB_USER"),
        password=os.getenv("CLOUD_SQL_DB_PASSWORD"),
        port=int(os.getenv("CLOUD_SQL_PORT", 5432))
    )

def get_symbols():
    resp = requests.get(f"{BRIDGE_URL}/symbols/list", headers=HEADERS, timeout=10)
    data = resp.json()
    syms = data.get("symbols", [])
    return [s["name"] if isinstance(s, dict) else s for s in syms]

def backfill():
    print(f"🔄 Backfill started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    symbols = get_symbols()
    print(f"📋 {len(symbols)} symbols found")

    conn = get_db()
    cur  = conn.cursor()

    total = 0
    errors = 0

    for i, symbol in enumerate(symbols):
        sym_total = 0
        for tf in TIMEFRAMES:
            try:
                resp = requests.post(
                    f"{BRIDGE_URL}/prices/historical",
                    headers=HEADERS,
                    json={"symbol": symbol, "timeframe": tf, "count": CANDLES},
                    timeout=15
                )
                if not resp.ok:
                    errors += 1
                    continue
                candles = resp.json().get("candles", [])
                for c in candles:
                    ts_ms = c.get("timestamp")
                    if not ts_ms:
                        continue
                    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                    cur.execute("""
                        INSERT INTO market_data
                            (symbol, timeframe, timestamp, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
                            open=EXCLUDED.open, high=EXCLUDED.high,
                            low=EXCLUDED.low,   close=EXCLUDED.close,
                            volume=EXCLUDED.volume
                    """, (
                        symbol, tf, ts,
                        c.get("open_raw"), c.get("high_raw"),
                        c.get("low_raw"),  c.get("close_raw"),
                        c.get("volume", 0)
                    ))
                    sym_total += 1
            except Exception as e:
                errors += 1
                print(f"  ⚠️  {symbol}/{tf}: {e}")

        conn.commit()
        total += sym_total
        print(f"  [{i+1}/{len(symbols)}] {symbol}: {sym_total} rows  (total={total})")

    cur.close()
    conn.close()
    print(f"\n✅ Backfill complete: {total} rows upserted, {errors} errors")

    # Verify freshness
    conn2 = get_db()
    cur2  = conn2.cursor()
    cur2.execute("""
        SELECT timeframe, MAX(timestamp) as latest
        FROM market_data GROUP BY timeframe ORDER BY latest DESC
    """)
    print("\n📊 Data freshness after backfill:")
    now = datetime.now(timezone.utc)
    for r in cur2.fetchall():
        age = (now - r[1]).total_seconds() / 60
        status = "✅" if age < 60 else "⚠️ "
        print(f"  {status} {r[0]:<8} latest={r[1].strftime('%Y-%m-%d %H:%M')} UTC  ({age:.0f} mins ago)")
    cur2.close()
    conn2.close()

if __name__ == "__main__":
    backfill()
