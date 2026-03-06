#!/bin/bash
if [ -f ~/tekton-ai-trader/bridge.log ]; then
    size=$(stat -c%s ~/tekton-ai-trader/bridge.log 2>/dev/null)
    if [ $size -gt 104857600 ]; then
        cd ~/tekton-ai-trader
        tail -c 10485760 bridge.log > bridge.log.tmp
        mv bridge.log.tmp bridge.log
    fi
fi
