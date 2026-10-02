#!/bin/bash
# start.sh — only run after bootstrap.sh has completed.
set -e

WAN2GP_DIR="${WAN2GP_DIR:-/root/Wan2GP}"
cd "$WAN2GP_DIR"

if pgrep -f "wgp.py" > /dev/null; then
  echo "wgp.py already running — not launching a second instance."
  exit 0
fi

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
