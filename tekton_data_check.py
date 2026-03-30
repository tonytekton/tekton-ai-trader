#!/usr/bin/env python3
"""
tekton_data_check.py
Tekton AI Trader — Market Data Freshness Monitor
Runs as a VM cron job every 30 mins during market hours.
Checks market_data table for stale candles and sends Telegram alert if any found.

Thresholds are trading-minutes based — weekends are excluded from age calculation.
  5min  → 45 min
  15min → 90 min
  60min → 240 min
  4H    → 480 min
  Daily → 2160 min (36 trading hours — covers Friday close to Monday evening)
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

# Thresholds in TRADING minutes (weekends excluded)
THRESHOLDS = {
    "5min":  45,    # 3 missed candles
    "15min": 90,    # 3 missed candles
    "60min": 240,   # 3 missed candles + buffer
    "4H":    480,   # 1 full candle period + buffer
    "Daily": 2160,  # 36 trading hours — covers Friday close to Monday evening
}


def trading_minutes_since(dt: datetime) -> float:
    """
    Calculate elapsed TRADING minutes between dt and now UTC,
    excluding weekends (Sat 00:00 UTC — Mon 06:00 UTC).
    """
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    elapsed = 0.0
    cursor  = dt

    while cursor < now:
        wd = cursor.weekday()  # 0=Mon, 6=Sun
        h  = cursor.hour + cursor.minute / 60.0

        # Skip weekends and Monday pre-open
        is_weekend = (wd == 5) or (wd == 6) or (wd == 0 and h < 6)

        if not is_weekend:
            # Advance in 1-minute steps (capped at remaining time)
            step = min(1.0, (now - cursor).total_seconds() / 60.0)
            elapsed += step

        cursor += timedelta(minutes=1)

        # Safety cap — don't loop more than 10 days worth
        if elapsed > 14400:
            break

    return elapsed


# Market hours: Mon 06:00 UTC — Fri 21:00 UTC
def is_market_hours() -> bool:
    now = datetime.now(timezone.utc)
    wd  = now.weekday()
    if wd == 5: return False
    if wd == 6: return False
    h = now.hour + now.minute / 60.0
    if wd == 0 and h < 6:   return False
    if wd == 4 and h >= 21: return False
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

    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()
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

    now_utc = datetime.now(timezone.utc)
    stale   = []

    for tf, latest in rows:
        if tf not in THRESHOLDS:
            continue
        if latest is None:
            stale.append(f"  {tf}: NO DATA at all")
            continue

        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)

        trading_mins = trading_minutes_since(latest)
        threshold    = THRESHOLDS[tf]

        if trading_mins > threshold:
            stale.append(f"  {tf}: {trading_mins:.0f} trading-min old (limit {threshold})")
        else:
            print(f"✅ {tf}: {trading_mins:.0f} trading-min old — OK")

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
