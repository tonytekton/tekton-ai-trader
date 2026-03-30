#!/usr/bin/env python3
"""
Standalone script to check market_data freshness.
Run manually anytime: python3 check_data_freshness.py
Also called by the VM-side monitor service.
"""
import psycopg2, os, sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/tekton-ai-trader/.env"))

STALE_THRESHOLD_MINS = 45

MARKET_HOURS = {
    # Mon 06:00 UTC → Fri 16:00 UTC is market open
    # weekday(): 0=Mon, 4=Fri, 5=Sat, 6=Sun
}

def is_market_open(now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()
    if wd == 5:  # Saturday
        return False
    if wd == 6:  # Sunday before 22:00 UTC
        return now_utc.hour < 22
    if wd == 4 and now_utc.hour >= 16:  # Friday after 16:00 UTC
        return False
    return True

def check():
    conn = psycopg2.connect(
        host=os.getenv("CLOUD_SQL_HOST"),
        database=os.getenv("CLOUD_SQL_DB_NAME"),
        user=os.getenv("CLOUD_SQL_DB_USER"),
        password=os.getenv("CLOUD_SQL_DB_PASSWORD"),
        port=int(os.getenv("CLOUD_SQL_PORT", 5432))
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT timeframe, MAX(timestamp) as latest
        FROM market_data GROUP BY timeframe ORDER BY latest DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    now = datetime.now(timezone.utc)
    market_open = is_market_open(now)

    stale = []
    fresh = []

    for tf, latest in rows:
        age_mins = (now - latest).total_seconds() / 60
        if age_mins > STALE_THRESHOLD_MINS:
            stale.append((tf, latest, age_mins))
        else:
            fresh.append((tf, latest, age_mins))

    print(f"Market hours: {'OPEN' if market_open else 'CLOSED'}  |  Checked: {now.strftime('%Y-%m-%d %H:%M')} UTC")
    print()

    if stale:
        print(f"🔴 STALE TIMEFRAMES ({len(stale)}):")
        for tf, latest, age in stale:
            hrs = age / 60
            print(f"   {tf:<8} last={latest.strftime('%Y-%m-%d %H:%M')} UTC  age={hrs:.1f}h")
    else:
        print("✅ All timeframes fresh")

    if fresh:
        print(f"\n✅ FRESH TIMEFRAMES ({len(fresh)}):")
        for tf, latest, age in fresh:
            print(f"   {tf:<8} last={latest.strftime('%Y-%m-%d %H:%M')} UTC  age={age:.0f}min")

    return stale, market_open

if __name__ == "__main__":
    stale, market_open = check()
    if stale and market_open:
        print(f"\n⚠️  ACTION REQUIRED: market is open but {len(stale)} timeframe(s) are stale!")
        print("   Run: python3 backfill_now.py")
        sys.exit(1)
    else:
        sys.exit(0)
