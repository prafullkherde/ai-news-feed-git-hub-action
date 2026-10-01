#!/bin/bash
# start.sh — only run after bootstrap.sh has completed.
set -e

cd Wan2GP
source venv/bin/activate

echo "=================================================="
echo "Starting Wan2GP — will listen on port 7860"
echo "Remember: map/expose port 7860 in your host's"
echo "dashboard to reach this from outside the box."
echo "=================================================="

python3 wgp.py --listen --port 7860

# To stop: Ctrl+C here ends the process.
# To stop billing: go to the dashboard and TERMINATE the
# instance yourself — deliberately not scripted (§6, cost-
# control gate, discussed earlier).
