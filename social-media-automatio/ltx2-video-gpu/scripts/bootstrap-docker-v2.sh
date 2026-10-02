#!/bin/bash
# bootstrap.sh — runs on an instance booted from the READYMADE
# robatvastai/wan2gp image. OS tools, torch, and Wan2GP are already
# IN THE IMAGE — this script only handles what the image deliberately
# does NOT contain: the model weights, which live on the attached
# volume at /data instead.
#
# PATHS BELOW ASSUME the discovery pass from LTX2-Setup-Volume.yml
# confirmed /root/Wan2GP/wgp.py and ffmpeg present. If discovery found
# a different path, update WAN2GP_DIR below before relying on this.
set -e

WAN2GP_DIR="${WAN2GP_DIR:-/root/Wan2GP}"

echo "=================================================="
echo "STEP 0/3 — Re-verify preflight (don't trust a stale pass)"
echo "=================================================="
bash preflight.sh

echo ""
echo "=================================================="
echo "STEP 1/3 — Weights: check volume first, download only if missing"
echo "=================================================="
cd "$WAN2GP_DIR"

if [ -f "/data/ltx-2-19b-distilled.safetensors" ] && [ -f "/data/gemma3/config.json" ]; then
  echo "Weights already present on volume — skipping download entirely."
  # Point Wan2GP at the volume's weights rather than copying them
  # into the container — a symlink keeps this working even if the
  # image's expected ckpts/ path differs from /data.
  mkdir -p ckpts
  ln -sfn /data/ltx-2-19b-distilled.safetensors ckpts/ltx-2-19b-distilled.safetensors
  ln -sfn /data/gemma3 ckpts/gemma3
else
  if [ -z "$HF_TOKEN" ]; then
    echo "FAIL: weights missing AND HF_TOKEN not set — cannot download gated LTX-2 weights."
    exit 1
  fi
  echo "Weights not found on volume — this should not happen if LTX2-Setup-Volume.yml ran successfully."
  echo "Downloading directly to the volume (one-time; persists for every future run)..."
  pip install -U "huggingface_hub[cli]" -q
  huggingface-cli download Lightricks/LTX-2 \
    --include "ltx-2-19b-distilled.safetensors" --local-dir /data \
    --token "$HF_TOKEN"
  huggingface-cli download google/gemma-3-12b-it --local-dir /data/gemma3 \
    --token "$HF_TOKEN"
  mkdir -p ckpts
  ln -sfn /data/ltx-2-19b-distilled.safetensors ckpts/ltx-2-19b-distilled.safetensors
  ln -sfn /data/gemma3 ckpts/gemma3
fi

echo ""
echo "=================================================="
echo "STEP 2/3 — Defensive check: confirm the image is what we expect"
echo "=================================================="
if [ ! -f "wgp.py" ]; then
  echo "FAIL: wgp.py not found at $WAN2GP_DIR — wrong image or path changed?"
  echo "Re-run the discovery step in LTX2-Setup-Volume.yml to confirm the real path."
  exit 1
fi
command -v ffmpeg > /dev/null || { echo "FAIL: ffmpeg not found in this image."; exit 1; }

echo ""
echo "=================================================="
echo "STEP 3/3 — Confirm the whole stack actually connects"
echo "=================================================="
python3 -c "import torch; print('torch:', torch.__version__, '| CUDA available:', torch.cuda.is_available())"

echo ""
echo "=================================================="
echo "BOOTSTRAP COMPLETE — safe to run start.sh"
echo "=================================================="
