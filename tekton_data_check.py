#!/usr/bin/env python3
"""
tekton_data_check.py
Tekton AI Trader — Market Data Freshness Monitor
Runs as a VM cron job every 30 mins during market hours.
Checks market_data table for stale candles and sends Telegram alert if any found.
"""

import os
import sys
import json
import psycopg2
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST"),
    "database": os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
    "user":     os.getenv("CLOUD_SQL_DB_USER", "postgres"),
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
    "port":     int(os.getenv("CLOUD_SQL_PORT", "5432")),
    "sslmode":  "disable"
}

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Staleness thresholds in minutes per timeframe
THRESHOLDS = {
    "5min":  30,
    "15min": 60,
    "60min": 180,
    "4H":    360,
    "Daily": 1560,
}

# Market hours: Mon 06:00 UTC — Fri 21:00 UTC
def is_market_hours() -> bool:
    now = datetime.now(timezone.utc)
    wd  = now.weekday()  # 0=Mon, 6=Sun
    if wd == 5: return False  # Saturday always closed
    if wd == 6: return False  # Sunday always closed
    h = now.hour + now.minute / 60.0
    if wd == 0 and h < 6:   return False  # Monday pre-open
    if wd == 4 and h >= 21: return False  # Friday close
    return True


def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram credentials not set")
        return
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        if result.get("ok"):
            print("✅ Telegram alert sent")
        else:
            print(f"❌ Telegram error: {result}")
    except urllib.error.HTTPError as e:
        print(f"❌ Telegram HTTP {e.code}: {e.read().decode()}")


def check_freshness():
    if not is_market_hours():
        print("⏸ Outside market hours — skipping check")
        sys.exit(0)

    now_utc = datetime.now(timezone.utc)

    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()

        # Get latest candle timestamp per timeframe
        cur.execute("""
            SELECT timeframe, MAX(timestamp) AS latest
            FROM market_data
            GROUP BY timeframe
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

    except Exception as e:
        msg = f"⚠️ Tekton Data Check FAILED — DB error: {e}"
        print(msg)
        send_telegram(msg)
        sys.exit(1)

    stale = []
    for tf, latest in rows:
        if tf not in THRESHOLDS:
            continue
        if latest is None:
            stale.append(f"  {tf}: NO DATA at all")
            continue

        # Make timezone-aware if naive
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)

        age_mins = (now_utc - latest).total_seconds() / 60
        threshold = THRESHOLDS[tf]

        if age_mins > threshold:
            stale.append(f"  {tf}: {age_mins:.0f} min old (limit {threshold} min)")
        else:
            print(f"✅ {tf}: {age_mins:.0f} min old — OK")

    if stale:
        lines = ["⚠️ Tekton Data Freshness Alert", ""]
        lines += stale
        lines += ["", f"Checked at {now_utc.strftime('%H:%M UTC')}"]
        msg = "\n".join(lines)
        print(msg)
        send_telegram(msg)
    else:
        print(f"✅ All timeframes fresh — {now_utc.strftime('%H:%M UTC')}")


if __name__ == "__main__":
    check_freshness()
