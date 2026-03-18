#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  start_tekton.sh — Tekton AI Trader v4.6
#  Starts all Python services and ensures the backfill cron is registered.
#  Run on boot or after any VM restart.
#  Usage: bash /home/tony/tekton-ai-trader/start_tekton.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e
cd /home/tony/tekton-ai-trader

echo "🚀 Starting Tekton AI Trader Stack..."
echo "   $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# ── 1. Bridge (systemd-managed — restart via systemctl) ──────────────────────
echo "1️⃣  Bridge..."
sudo systemctl restart tekton-ai-trader-bridge.service
sleep 10
if sudo systemctl is-active --quiet tekton-ai-trader-bridge.service; then
    echo "   ✅ Bridge running (port 8080)"
else
    echo "   ❌ Bridge FAILED — check: sudo journalctl -u tekton-ai-trader-bridge.service -n 30"
fi

# ── 2. Executor ───────────────────────────────────────────────────────────────
echo "2️⃣  Executor..."
pkill -f tekton_executor.py 2>/dev/null || true
sleep 2
nohup python3 -u tekton_executor.py >> executor.log 2>&1 &
echo "   ✅ Executor started (PID $!)"

# ── 3. Monitor ────────────────────────────────────────────────────────────────
echo "3️⃣  Monitor..."
pkill -f tekton_monitor.py 2>/dev/null || true
sleep 2
nohup python3 -u tekton_monitor.py >> monitor.log 2>&1 &
echo "   ✅ Monitor started (PID $!)"

sleep 3

# ── 4. Strategies ─────────────────────────────────────────────────────────────
echo "4️⃣  Strategies..."

pkill -f strat_ict_fvg_v1.py        2>/dev/null || true
pkill -f strat_ema_pullback_v1.py   2>/dev/null || true
pkill -f strat_session_orb_v1.py    2>/dev/null || true
pkill -f strat_vwap_reversion_v1.py 2>/dev/null || true
pkill -f strat_breakout_retest_v1.py 2>/dev/null || true
pkill -f strat_rsi_divergence_v1.py 2>/dev/null || true
pkill -f strat_lester_v1.py         2>/dev/null || true
sleep 2

nohup python3 -u strat_ict_fvg_v1.py         >> strategy.log      2>&1 &
echo "   ✅ ICT FVG (PID $!)"
nohup python3 -u strat_ema_pullback_v1.py     >> strat_eps.log     2>&1 &
echo "   ✅ EMA Pullback (PID $!)"
nohup python3 -u strat_session_orb_v1.py      >> strat_sorb.log    2>&1 &
echo "   ✅ Session ORB (PID $!)"
nohup python3 -u strat_vwap_reversion_v1.py   >> strat_vwap.log    2>&1 &
echo "   ✅ VWAP Reversion (PID $!)"
nohup python3 -u strat_breakout_retest_v1.py  >> strat_brt.log     2>&1 &
echo "   ✅ Breakout+Retest (PID $!)"
nohup python3 -u strat_rsi_divergence_v1.py   >> strat_rsid.log    2>&1 &
echo "   ✅ RSI Divergence (PID $!)"
nohup python3 -u strat_lester_v1.py           >> strat_lester.log  2>&1 &
echo "   ✅ Lester LSV (PID $!)"

# ── 5. Cron jobs — ensure both are registered ────────────────────────────────
echo "5️⃣  Cron jobs..."

CURRENT_CRON=$(crontab -l 2>/dev/null || true)
BACKFILL_JOB="*/15 * * * * cd /home/tony/tekton-ai-trader && python3 tekton_backfill.py >> /home/tony/tekton-ai-trader/combined_trades.log 2>&1"
REPORT_JOB="0 22 * * * /usr/bin/python3 /home/tony/tekton-ai-trader/tekton_daily_report.py >> /home/tony/tekton-ai-trader/reports.log 2>&1"

UPDATED_CRON="$CURRENT_CRON"

if echo "$CURRENT_CRON" | grep -q "tekton_backfill.py"; then
    echo "   ✅ Backfill cron already registered (every 15 min)"
else
    UPDATED_CRON=$(echo "$UPDATED_CRON" | grep -v "backfill" || true)
    UPDATED_CRON="$UPDATED_CRON
$BACKFILL_JOB"
    echo "   ✅ Backfill cron registered (every 15 min)"
fi

if echo "$CURRENT_CRON" | grep -q "tekton_daily_report.py"; then
    echo "   ✅ Daily report cron already registered (22:00 UTC)"
else
    UPDATED_CRON=$(echo "$UPDATED_CRON" | grep -v "daily_report" || true)
    UPDATED_CRON="$UPDATED_CRON
$REPORT_JOB"
    echo "   ✅ Daily report cron registered (22:00 UTC)"
fi

echo "$UPDATED_CRON" | crontab -

# ── 6. Run backfill immediately on startup ────────────────────────────────────
echo "6️⃣  Running backfill now to catch up on any missed candles..."
python3 tekton_backfill.py
echo "   ✅ Backfill complete"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────────"
echo "🛡️  Tekton AI Trader v4.6 — All systems operational"
echo ""
echo "   Processes:"
ps aux | grep -E "tekton_|strat_" | grep -v grep | awk '{printf "   %-50s PID:%s\n", $11, $2}'
echo ""
echo "   Logs:"
echo "   bridge   → sudo journalctl -u tekton-ai-trader-bridge.service -f"
echo "   executor → tail -f executor.log"
echo "   monitor  → tail -f monitor.log"
echo "   FVG      → tail -f strategy.log"
echo "   EPS      → tail -f strat_eps.log"
echo "   SORB     → tail -f strat_sorb.log"
echo "   VWAP     → tail -f strat_vwap.log"
echo "   BRT      → tail -f strat_brt.log"
echo "   RSID     → tail -f strat_rsid.log"
echo "   Lester   → tail -f strat_lester.log"
echo "   Backfill → tail -f combined_trades.log"
echo "─────────────────────────────────────────────────────"

