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
echo "STEP 4/7 — PyTorch — READ docs/INSTALLATION.md FIRST"
echo "=================================================="
echo "!! Do not skip this — open the line below and read the"
echo "!! ACTUAL current pip command before running it blind:"
echo "!! https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/INSTALLATION.md"
echo ""
echo "Paste today's real command here, e.g.:"
echo "  pip install torch torchvision torchaudio --index-url <URL from docs>"
read -p "Press Enter once you've run that command manually, to continue: "

echo ""
echo "=================================================="
echo "STEP 5/7 — App dependencies"
echo "=================================================="
pip install -r requirements.txt

echo ""
echo "=================================================="
echo "STEP 6/7 — Download model weights (~45-70GB, resumes if interrupted)"
echo "=================================================="
pip install -U "huggingface_hub[cli]"
huggingface-cli download Lightricks/LTX-2 \
  --include "ltx-2-19b-distilled.safetensors" --local-dir ckpts/
huggingface-cli download google/gemma-3-12b-it --local-dir ckpts/gemma3/

echo ""
echo "=================================================="
echo "STEP 7/7 — Confirm the whole stack actually connects"
echo "=================================================="
python3 -c "import torch; print('torch:', torch.__version__, '| CUDA available:', torch.cuda.is_available())"

echo ""
echo "=================================================="
echo "BOOTSTRAP COMPLETE — safe to run start.sh"
echo "=================================================="
