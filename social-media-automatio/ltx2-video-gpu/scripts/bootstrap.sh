#!/bin/bash
# bootstrap.sh — only run after preflight.sh has passed.
set -e

echo "=================================================="
echo "STEP 0/7 — Re-verify preflight (don't trust a stale pass)"
echo "=================================================="
bash preflight.sh

echo ""
echo "=================================================="
echo "STEP 1/7 — OS tools"
echo "=================================================="
apt-get update
apt-get install -y build-essential python3.10 python3-pip git ffmpeg

echo ""
echo "=================================================="
echo "STEP 2/7 — Clone Wan2GP"
echo "=================================================="
git clone https://github.com/deepbeepmeep/Wan2GP.git
cd Wan2GP

echo ""
echo "=================================================="
echo "STEP 3/7 — Isolated environment"
echo "=================================================="
python3 -m venv venv
source venv/bin/activate

echo ""
echo "=================================================="
echo "STEP 4/7 — PyTorch (pinned, not read from docs live)"
echo "=================================================="
# Verified against docs/INSTALLATION.md as of 2026-09 for cu124.
# Trade-off vs the original "read docs fresh" step: this can't catch
# an upstream change automatically. Re-check manually every so often —
# not every run, but don't assume this stays correct forever.
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

echo ""
echo "=================================================="
echo "STEP 5/7 — App dependencies"
echo "=================================================="
pip install -r requirements.txt

echo ""
echo "=================================================="
echo "STEP 6/7 — Download model weights (~45-70GB, resumes if interrupted)"
echo "=================================================="
# LTX-2 is a GATED repo — HF_TOKEN required, and the license must have
# been accepted once, manually, on the model's huggingface.co page.
# No script can do that click for you.
if [ -z "$HF_TOKEN" ]; then
  echo "FAIL: HF_TOKEN not set — cannot download gated LTX-2 weights."
  exit 1
fi
pip install -U "huggingface_hub[cli]"
huggingface-cli download Lightricks/LTX-2 \
  --include "ltx-2-19b-distilled.safetensors" --local-dir ckpts/ \
  --token "$HF_TOKEN"
huggingface-cli download google/gemma-3-12b-it --local-dir ckpts/gemma3/ \
  --token "$HF_TOKEN"

echo ""
echo "=================================================="
echo "STEP 7/7 — Confirm the whole stack actually connects"
echo "=================================================="
python3 -c "import torch; print('torch:', torch.__version__, '| CUDA available:', torch.cuda.is_available())"

echo ""
echo "=================================================="
echo "BOOTSTRAP COMPLETE — safe to run start.sh"
echo "=================================================="
