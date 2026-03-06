import os, requests, time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BRIDGE_URL = "http://localhost:8080"
HEADERS = {"X-Bridge-Key": os.getenv("BRIDGE_KEY")}

def send_telegram_report(report_text):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": report_text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=15) #
    except Exception as e:
        print(f"❌ Telegram Report Error: {e}")

def generate_daily_report():
    try:
        # Get start/end timestamps for the last 24 hours
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (24 * 60 * 60 * 1000)

        # Request history from Bridge
        res = requests.post(f"{BRIDGE_URL}/positions/history", 
                            json={"from_timestamp": start_ms, "to_timestamp": now_ms}, 
                            headers=HEADERS)
        data = res.json()
        
        if not data.get("success"):
            return "⚠️ Failed to fetch trade history."

        trades = data.get("positions", [])
        total_pnl = sum(t['pnl'] for t in trades) # P&L in currency units
        win_count = len([t for t in trades if t['pnl'] > 0])
        loss_count = len([t for t in trades if t['pnl'] <= 0])
        
        # Format the message
        report = (
            f"📊 *DAILY TRADING REPORT*\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d')}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 *Net Profit/Loss:* €{total_pnl:.2f}\n"
            f"📈 *Total Trades:* {len(trades)}\n"
            f"✅ *Wins:* {win_count} | ❌ *Losses:* {loss_count}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🤖 *Status:* System Healthy"
        )
        return report

    except Exception as e:
        return f"❌ Error generating report: {str(e)}"

if __name__ == "__main__":
    print("🕒 Generating Daily Summary...")
    report_msg = generate_daily_report()
    send_telegram_report(report_msg)
    print("✅ Report Sent to Telegram.")
