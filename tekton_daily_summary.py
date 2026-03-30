#!/usr/bin/env python3
"""
tekton_daily_summary.py
Tekton AI Trader — Daily Summary
Queries DB directly, sends via Telegram.
Designed to run as a systemd one-shot service on a timer.
"""

import os
import sys
import json
import psycopg2
import urllib.request
import urllib.error
from datetime import datetime, timedelta
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
            print("✅ Telegram message sent")
        else:
            print(f"❌ Telegram error: {result}")
    except urllib.error.HTTPError as e:
        print(f"❌ Telegram HTTP {e.code}: {e.read().decode()}")


def generate_summary():
    now_kl  = datetime.utcnow() + timedelta(hours=8)  # UTC+8 KL
    today   = now_kl.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)  # back to UTC

    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()

        # ── Signal stats (today) ────────────────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*)                                                      AS total,
                SUM(CASE WHEN status = 'COMPLETED'  THEN 1 ELSE 0 END)       AS completed,
                SUM(CASE WHEN status = 'FAILED'     THEN 1 ELSE 0 END)       AS failed,
                SUM(CASE WHEN status = 'EXECUTING'  THEN 1 ELSE 0 END)       AS executing,
                SUM(CASE WHEN status = 'SLREJECTED' THEN 1 ELSE 0 END)       AS sl_rejected,
                SUM(CASE WHEN status = 'PENDING'    THEN 1 ELSE 0 END)       AS pending
            FROM signals WHERE created_at >= %s
        """, (today,))
        sig = cur.fetchone()
        total, completed, failed, executing, sl_rej, pending = sig if sig else (0,0,0,0,0,0)

        # ── Top fail reasons ────────────────────────────────────────────
        cur.execute("""
            SELECT error_reason, COUNT(*) AS n
            FROM signals
            WHERE created_at >= %s AND status IN ('FAILED','SLREJECTED','DATAREJECTED')
            GROUP BY error_reason
            ORDER BY n DESC
            LIMIT 5
        """, (today,))
        fail_reasons = cur.fetchall()

        # ── Open positions ──────────────────────────────────────────────
        cur.execute("""
            SELECT symbol, signal_type, strategy, broker_position_id
            FROM signals WHERE status = 'EXECUTING'
            ORDER BY created_at DESC
        """)
        open_pos = cur.fetchall()

        # ── Strategy breakdown (today) ──────────────────────────────────
        cur.execute("""
            SELECT strategy,
                   COUNT(*)                                                   AS total,
                   SUM(CASE WHEN status = 'COMPLETED'  THEN 1 ELSE 0 END)   AS done,
                   SUM(CASE WHEN status IN ('FAILED','SLREJECTED') THEN 1 ELSE 0 END) AS fails
            FROM signals WHERE created_at >= %s
            GROUP BY strategy
            ORDER BY total DESC
        """, (today,))
        strats = cur.fetchall()

        # ── Account metrics ─────────────────────────────────────────────
        cur.execute("""
            SELECT balance, equity, drawdown_pct, timestamp
            FROM account_metrics
            ORDER BY timestamp DESC LIMIT 1
        """)
        acc = cur.fetchone()

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ DB error: {e}")
        send_telegram(f"⚠️ Tekton Daily Summary FAILED — DB error: {e}")
        sys.exit(1)

    # ── Format message ──────────────────────────────────────────────────
    bal = acc[0] if acc and acc[0] else 0
    eq  = acc[1] if acc and acc[1] else 0
    dd  = acc[2] if acc and acc[2] else 0.0

    lines = [
        f"📊 Tekton Daily Summary — {now_kl.strftime('%d %b %Y %H:%M')} KL",
        "",
        f"Account: EUR {bal:,.2f} | Equity: EUR {eq:,.2f} | DD: {dd:.2f}%",
        "",
        f"Signals today: {total} total",
        f"  Completed : {completed}",
        f"  Executing : {executing}",
        f"  Failed    : {failed}",
        f"  SL Reject : {sl_rej}",
        "",
    ]

    if open_pos:
        lines.append(f"Open Positions ({len(open_pos)}):")
        for p in open_pos:
            lines.append(f"  {p[0]} {p[1]} [{p[2]}]")
    else:
        lines.append("Open Positions: None")

    lines.append("")
    lines.append("Strategy Breakdown:")
    for s in strats:
        lines.append(f"  {s[0]}: {s[1]} signals | {s[2]} done | {s[3]} failed")

    if fail_reasons:
        lines.append("")
        lines.append("Top Fail Reasons:")
        for r in fail_reasons:
            lines.append(f"  {r[1]}x {r[0] or 'unknown'}")

    msg = "\n".join(lines)
    print(msg)
    send_telegram(msg)


if __name__ == "__main__":
    generate_summary()
