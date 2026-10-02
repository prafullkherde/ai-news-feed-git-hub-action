#!/bin/bash
# bootstrap.sh — runs on an instance booted from the pre-baked
# ghcr.io/.../ltx2-video image. OS tools, torch, and Wan2GP are
# already IN THE IMAGE — this script only handles what the image
# deliberately does NOT contain: the model weights, which live on
# the persistent Volume instead.
set -e

echo "=================================================="
echo "STEP 0/3 — Re-verify preflight (don't trust a stale pass)"
echo "=================================================="
bash preflight.sh

echo ""
echo "=================================================="
echo "STEP 1/3 — Weights: check volume first, download only if missing"
echo "=================================================="
cd Wan2GP
source venv/bin/activate

if [ -f "ckpts/ltx-2-19b-distilled.safetensors" ] && [ -f "ckpts/gemma3/config.json" ]; then
  echo "Weights already present on volume — skipping download entirely."
else
  if [ -z "$HF_TOKEN" ]; then
    echo "FAIL: weights missing AND HF_TOKEN not set — cannot download gated LTX-2 weights."
    exit 1
  fi
  echo "Weights not found on volume — downloading (one-time; persists for every future run)..."
  huggingface-cli download Lightricks/LTX-2 \
    --include "ltx-2-19b-distilled.safetensors" --local-dir ckpts/ \
    --token "$HF_TOKEN"
  huggingface-cli download google/gemma-3-12b-it --local-dir ckpts/gemma3/ \
    --token "$HF_TOKEN"
fi

echo ""
echo "=================================================="
echo "STEP 2/3 — Defensive check: confirm image is the baked one"
echo "=================================================="
# Should always pass — only fails if this ever runs on the wrong image by mistake.
if [ ! -d ".git" ]; then
  echo "FAIL: Wan2GP not found where expected — wrong image?"
  exit 1
fi

echo ""
echo "=================================================="
echo "STEP 3/3 — Confirm the whole stack actually connects"
echo "=================================================="
python3 -c "import torch; print('torch:', torch.__version__, '| CUDA available:', torch.cuda.is_available())"

echo ""
echo "=================================================="
echo "BOOTSTRAP COMPLETE — safe to run start.sh"
echo "=================================================="
