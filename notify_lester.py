#!/usr/bin/env python3
"""
notify_lester.py <event> <message>

Called by systemd OnFailure units to alert Lester via the Base44 agent API.
Lester then sends a WhatsApp message to Tony.
"""
import sys, os, json, urllib.request
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/tekton-ai-trader/.env"))

APP_ID    = "69b27d4d46f443e4fd0cd5bc"
API_KEY   = os.getenv("BASE44_API_KEY", "")
BASE_URL  = "https://api.base44.com/api/apps"

def notify(event, message):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "message": f"🚨 *Tekton VM Alert*\n\nEvent: {event}\nTime: {now}\n\n{message}"
    }
    url = f"{BASE_URL}/{APP_ID}/send_message"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "api_key": API_KEY
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"✅ Lester notified: {r.status}")
    except Exception as e:
        print(f"❌ Notify failed: {e}", file=sys.stderr)

if __name__ == "__main__":
    event   = sys.argv[1] if len(sys.argv) > 1 else "UNKNOWN_EVENT"
    message = sys.argv[2] if len(sys.argv) > 2 else "No details provided"
    notify(event, message)
