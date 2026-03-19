#!/bin/bash
# install_services.sh — Install all Tekton systemd services
# Run once after git pull to register new services with systemd
# Requires sudo

set -e
cd ~/tekton-ai-trader

echo "📦 Installing Tekton systemd services..."

# Copy all service files to systemd
sudo cp systemd/tekton-strat-ema-pullback.service  /etc/systemd/system/
sudo cp systemd/tekton-strat-session-orb.service   /etc/systemd/system/
sudo cp systemd/tekton-strat-vwap-reversion.service /etc/systemd/system/
sudo cp systemd/tekton-strat-breakout-retest.service /etc/systemd/system/
sudo cp systemd/tekton-strat-rsi-divergence.service /etc/systemd/system/
sudo cp systemd/tekton-strat-lester.service         /etc/systemd/system/

echo "  ✅ Service files copied"

# Reload systemd
sudo systemctl daemon-reload
echo "  ✅ systemd daemon reloaded"

# Enable all services (auto-start on VM reboot)
SERVICES=(
    "tekton-strat-ema-pullback"
    "tekton-strat-session-orb"
    "tekton-strat-vwap-reversion"
    "tekton-strat-breakout-retest"
    "tekton-strat-rsi-divergence"
    "tekton-strat-lester"
)

for svc in "${SERVICES[@]}"; do
    sudo systemctl enable "$svc"
    echo "  ✅ Enabled $svc"
done

echo ""
echo "✅ All services installed and enabled."
echo "   Run: bash restart.sh — to start everything"
