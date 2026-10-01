#!/bin/bash
# preflight.sh — run this FIRST, right after SSH login.
# set -e = cascade gate: any failed check stops here, nothing proceeds broken.
set -e

echo "=================================================="
echo "STEP 1/5 — GPU visible to the OS?"
echo "=================================================="
nvidia-smi || { echo "FAIL: no GPU detected. Wrong instance type rented?"; exit 1; }

echo ""
echo "=================================================="
echo "STEP 2/5 — VRAM check (need 20GB+ for 19B fp8)"
echo "=================================================="
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)
echo "Detected VRAM: ${VRAM} MB"
[ "$VRAM" -ge 20000 ] || { echo "FAIL: only ${VRAM}MB VRAM, need 20GB+"; exit 1; }

echo ""
echo "=================================================="
echo "STEP 3/5 — Disk space check (need 60GB+ free)"
echo "=================================================="
FREE=$(df --output=avail -BG . | tail -1 | tr -dc '0-9')
echo "Free disk: ${FREE}GB"
[ "$FREE" -ge 60 ] || { echo "FAIL: only ${FREE}GB free, need 60GB+. Resize volume."; exit 1; }

echo ""
echo "=================================================="
echo "STEP 4/5 — Driver + Python present?"
echo "=================================================="
nvidia-smi --query-gpu=driver_version --format=csv,noheader
python3 --version || { echo "FAIL: python3 not found"; exit 1; }

echo ""
echo "=================================================="
echo "STEP 5/5 — Internet reachable (for model download)?"
echo "=================================================="
curl -sSf -m 10 https://huggingface.co > /dev/null || { echo "FAIL: can't reach huggingface.co"; exit 1; }

echo ""
echo "=================================================="
echo "ALL CHECKS PASSED — safe to run bootstrap.sh"
echo "=================================================="
