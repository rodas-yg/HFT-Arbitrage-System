#!/usr/bin/env bash
# Runs the shadow retrainer periodically while keeping the Mac awake.

echo "============================================================"
echo " Starting Continuous Binary Retraining Loop                 "
echo "============================================================"

while true; do
    echo "[$(date)] Launching retraining cycle..."
    .venv/bin/python retrainer.py --binary
    
    echo "[$(date)] Retrain cycle complete. Sleeping for 1 hour..."
    # Sleep for 1 hour (3600 seconds) before the next retrain
    sleep 3600
done
