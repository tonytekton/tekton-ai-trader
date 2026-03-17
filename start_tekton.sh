#!/bin/bash

# Navigate to the correct directory
cd /home/tony/tekton-ai-trader

echo "🚀 Starting Tekton AI Trader Stack..."

# 1. Start the Bridge
python3 -u tekton_bridge.py > bridge.log 2>&1 &
echo "✅ Bridge Started (Port 8080)"
sleep 10

# 2. Start the Executor
python3 -u tekton_executor.py > executor.log 2>&1 &
echo "✅ Executor Started"

# 3. Start the Monitor
python3 -u tekton_monitor.py > monitor.log 2>&1 &
echo "✅ Monitor Started (drawdown protection active)"

# 4. Start the FVG Strategy
python3 -u strat_ict_fvg_v1.py >> strategy.log 2>&1 &
echo "✅ ICT FVG Strategy Started (5-min scans)"

# 5. Start the EMA Pullback Strategy
python3 -u strat_ema_pullback_v1.py >> strat_eps.log 2>&1 &
echo "✅ EMA Pullback Strategy Started (5-min scans)"

echo "🛡️ All systems operational."
echo "   Logs: bridge.log | executor.log | monitor.log | strategy.log | strat_eps.log"
