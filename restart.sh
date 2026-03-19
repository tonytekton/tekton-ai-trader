#!/bin/bash
# restart.sh — Clean restart of all Tekton processes via systemd
# Single source of truth for starting/stopping the entire stack

set -e
cd ~/tekton-ai-trader

# All managed services
SERVICES=(
    "tekton-ai-trader-bridge"
    "tekton-executor"
    "tekton-monitor"
    "tekton-strategy"
    "tekton-strat-ema-pullback"
    "tekton-strat-session-orb"
    "tekton-strat-vwap-reversion"
    "tekton-strat-breakout-retest"
    "tekton-strat-rsi-divergence"
    "tekton-strat-lester"
)

echo "🛑 Stopping all Tekton services..."
for svc in "${SERVICES[@]}"; do
    sudo systemctl stop "$svc" 2>/dev/null && echo "  ✅ Stopped $svc" || echo "  ⏭  $svc not running"
done

# Kill any orphan nohup processes not managed by systemd
echo ""
echo "🧹 Cleaning up any orphan processes..."
pkill -f "tekton_bridge.py"      2>/dev/null || true
pkill -f "tekton_executor.py"    2>/dev/null || true
pkill -f "tekton_monitor.py"     2>/dev/null || true
pkill -f "strat_ict_fvg_v1.py"  2>/dev/null || true
pkill -f "strat_ema_pullback"    2>/dev/null || true
pkill -f "strat_session_orb"     2>/dev/null || true
pkill -f "strat_vwap_reversion"  2>/dev/null || true
pkill -f "strat_breakout_retest" 2>/dev/null || true
pkill -f "strat_rsi_divergence"  2>/dev/null || true
pkill -f "strat_lester"          2>/dev/null || true
sleep 2

echo ""
echo "🚀 Starting Tekton services..."

# Bridge first — everything depends on it
sudo systemctl start tekton-ai-trader-bridge
echo "  ✅ Bridge started"
sleep 5  # Give bridge time to authenticate with cTrader

# Core services
sudo systemctl start tekton-executor
echo "  ✅ Executor started"
sudo systemctl start tekton-monitor
echo "  ✅ Monitor started"
sleep 2

# Strategies
for svc in tekton-strategy tekton-strat-ema-pullback tekton-strat-session-orb \
           tekton-strat-vwap-reversion tekton-strat-breakout-retest \
           tekton-strat-rsi-divergence tekton-strat-lester; do
    sudo systemctl start "$svc"
    echo "  ✅ $svc started"
done

sleep 2

echo ""
echo "📊 Service status:"
for svc in "${SERVICES[@]}"; do
    STATUS=$(sudo systemctl is-active "$svc" 2>/dev/null)
    if [ "$STATUS" = "active" ]; then
        echo "  🟢 $svc"
    else
        echo "  🔴 $svc ($STATUS)"
    fi
done

echo ""
echo "✅ Tekton fully restarted — $(date '+%Y-%m-%d %H:%M:%S')"
