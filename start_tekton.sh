#!/bin/bash

# Navigate to the correct directory
cd /home/tony/tekton-ai-trader

echo "🚀 Starting Tekton AI Trader Stack..."

# 1. Start the Bridge (Background)
python3 -u tekton-bridge-v4.py > bridge.log 2>&1 &
echo "✅ Bridge Started (Port 8080)"
sleep 10 # Wait for authentication

# 2. Start the Executor (Background)
python3 -u tekton_executor.py > executor.log 2>&1 &
echo "✅ Executor Started"

# 3. Start the Monitor (Background)
python3 -u tekton_monitor.py > monitor.log 2>&1 &
echo "✅ Monitor Started (10% Drawdown protection active)"

# 4. Start the Strategy (Background)
python3 -u strat_ict_fvg_v1.py > strategy.log 2>&1 &
echo "✅ ICT Strategy Started (5-min scans active)"

echo "🛡️ All systems operational. Check logs for details."

