#!/bin/bash
# restart.sh — Clean restart of all Tekton processes
# Kills ALL instances regardless of how they were launched, then starts fresh

set -e
cd ~/tekton-ai-trader

echo "🛑 Stopping all Tekton processes..."

SCRIPTS=(
    "tekton_bridge.py"
    "tekton_executor.py"
    "tekton_monitor.py"
    "strat_ict_fvg_v1.py"
    "strat_ema_pullback_v1.py"
    "strat_session_orb_v1.py"
    "strat_vwap_reversion_v1.py"
    "strat_breakout_retest_v1.py"
    "strat_rsi_divergence_v1.py"
    "strat_lester_v1.py"
)

for script in "${SCRIPTS[@]}"; do
    pkill -f "$script" 2>/dev/null && echo "  ✅ Killed $script" || echo "  ⏭  $script not running"
done

# Wait and verify all dead
sleep 3
STILL_RUNNING=$(ps aux | grep -E "tekton_|strat_" | grep -v grep | wc -l)
if [ "$STILL_RUNNING" -gt 0 ]; then
    echo "⚠️  Force killing stragglers..."
    ps aux | grep -E "tekton_|strat_" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null
    sleep 2
fi

echo ""
echo "🚀 Starting Tekton services..."

# Bridge first — everything depends on it
nohup python3 -u tekton_bridge.py >> bridge.log 2>&1 &
echo "  ✅ Bridge started (PID $!)"
sleep 5  # Give bridge time to authenticate with cTrader

# Core services
nohup python3 -u tekton_executor.py >> executor.log 2>&1 &
echo "  ✅ Executor started (PID $!)"

nohup python3 -u tekton_monitor.py >> monitor.log 2>&1 &
echo "  ✅ Monitor started (PID $!)"

sleep 2

# Strategies
nohup python3 -u strat_ict_fvg_v1.py        >> strat_fvg.log    2>&1 & echo "  ✅ FVG started (PID $!)"
nohup python3 -u strat_ema_pullback_v1.py    >> strat_eps.log    2>&1 & echo "  ✅ EPS started (PID $!)"
nohup python3 -u strat_session_orb_v1.py     >> strat_sorb.log   2>&1 & echo "  ✅ SORB started (PID $!)"
nohup python3 -u strat_vwap_reversion_v1.py  >> strat_vwap.log   2>&1 & echo "  ✅ VWAP started (PID $!)"
nohup python3 -u strat_breakout_retest_v1.py >> strat_brt.log    2>&1 & echo "  ✅ BRT started (PID $!)"
nohup python3 -u strat_rsi_divergence_v1.py  >> strat_rsid.log   2>&1 & echo "  ✅ RSID started (PID $!)"
nohup python3 -u strat_lester_v1.py          >> strat_lester.log 2>&1 & echo "  ✅ Lester started (PID $!)"

sleep 2

echo ""
echo "📊 Process check:"
for pid in $(ps aux | grep -E "tekton_|strat_" | grep -v grep | awk '{print $2}'); do
    echo "  $pid: $(cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' ')"
done | sort -t: -k2

echo ""
echo "✅ Tekton fully restarted — $(date '+%Y-%m-%d %H:%M:%S')"
