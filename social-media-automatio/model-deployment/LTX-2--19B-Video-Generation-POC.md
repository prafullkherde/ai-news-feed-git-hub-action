# LTX-2 19B Video Generation POC — Master Context File

Consolidated from a full deployment-planning thread. Feed this to any AI
assistant as complete context before asking it to continue this work.

---

## 1. Project Intent (locked)

Generate short (5-10s) social-media-ready video clips with synchronized
audio, text-to-video and image-to-video, on a single rented GPU, at
near-zero marginal cost per clip. Will be called via REST API. Using
**LTX-2 19B Distilled** (the original, smaller checkpoint — NOT LTX-2.3)
via **Wan2GP**. No RAG, no multi-GPU, no agent layer, no real-time serving.
This is a POC — human-executed steps are fine, no need for full automation
yet. API security (auth) is deliberately deferred until after the pipeline
is proven working, not skipped forever.

---

## 2. Root-cause correction made early (still governs every number below)

The original draft spec conflated two different model generations:
- `LTX-2 19B Distilled` (Lightricks/LTX-2 repo) — **this project's model**
- `LTX-2.3 Distilled 1.1` (Lightricks/LTX-2.3 repo) — newer, 22B, NOT this
  project. WanGP's own changelog: "This model is bigger (22B versus 19B)."

Every VRAM/speed/cost/install number in this file is locked to the 19B
lineage. Do not substitute LTX-2.3 numbers into this pipeline.

---

## 3. Validated facts ledger (checked against primary sources this thread)

| Claim | Status | Note |
|---|---|---|
| `ltx-2-19b-distilled.safetensors` real checkpoint | ✅ Confirmed | Lightricks/LTX-2 on HuggingFace |
| Text encoder = Gemma 3 12B | ✅ Confirmed | Separate HF repo: google/gemma-3-12b-it |
| License = LTX-2 Community License Agreement | ✅ Confirmed | Exact slug on HF |
| `deepbeepmeep/Wan2GP` repo real, active | ✅ Confirmed | "GPU Poor" project, active changelog |
| 24GB VRAM = comfortable, NOT bare minimum | ✅ Confirmed (corrected) | Current WanGP: 10s@720p runs in as little as 8GB after optimizations; original draft's "24GB minimum" was stale |
| FP8 model alone needs ~20-21GB VRAM | ✅ Confirmed | Real OOM reported at ~19.6GB cap in a GitHub issue |
| Gemma-3 + LTX-2 both fully loaded = ~45GB, won't fit 24GB | ✅ Confirmed by math | This is WHY Wan2GP purges Gemma-3 from VRAM after encoding, before loading LTX-2 — mandatory, not optional |
| RunPod Community RTX 4090 = $0.34/hr | ✅ Confirmed | Multiple independent sources |
| Vast.ai RTX 4090 ~$0.37/hr floor | ✅ Confirmed | Marketplace floor |
| Vast.ai RTX 3090 listings seen | ✅ Confirmed | $0.14-0.21/hr range depending on host, disk, region |
| `torch==2.10.0`+`cu130` on stable pip index | ⚠️ Unverified | Exists on nightly/test channels only; a real user's working install showed torch 2.9.1+cu130. Don't hardcode — read `docs/INSTALLATION.md` fresh at deploy time |
| Gemma 3 12B max context tokens | ⚠️ Conflicting | Google's own listing: 32,768. Third-party resellers: 128K. Unresolved — check official model card at deploy time |
| Wan2GP on Apple Silicon (M-series) | ❌ Not viable | Real benchmark: M1 16GB → ~15 min for a few seconds of video; recommended RAM is 64GB+; model needs ~40GB alone. FP8 doesn't even work on Metal (MPS) — forced to larger fp16/bf16 weights |
| docker build/run works inside a rented vast.ai/RunPod instance | ❌ WRONG, corrected | A rented instance IS ALREADY a Docker container — no nested docker host access by default. Confirmed via vast.ai's own docs |
| RunPod stopped-pod storage doubles to $0.20/GB/mo | ✅ Confirmed | vs $0.10/GB/mo while running |
| Vast.ai storage ~$0.10-0.12/GB/mo flat | ✅ Confirmed | Same rate whether running or stopped (no doubling penalty, unlike RunPod) |
| Vast.ai payment: Stripe (card) + crypto (BitPay/Crypto.com/Coinbase), $5 min deposit | ✅ Confirmed | Official docs. No UPI support found anywhere in docs |
| AWS g5.xlarge (A10G, 22GB VRAM) = $1.006/hr on-demand, us-east-1 | ✅ Confirmed | Note: 22GB, not a full 24GB — tighter fit than a true 24GB card |
| AWS EC2 (not Bedrock) is the real GPU-rental equivalent on AWS | ✅ Confirmed | Bedrock = managed API only, no instance/SSH/GPU access — ruled out entirely |

---

## 4. Final model + infra spec

| Attribute | Value |
|---|---|
| Model | `ltx-2-19b-distilled.safetensors` |
| Text encoder | Gemma 3 12B |
| Steps | 8 (distilled) |
| GPU | RTX 3090 or 4090, 24GB VRAM (both work — see §9 for the chosen instance) |
| VRAM floor | ~20-21GB for FP8 model alone; both models never coexist in VRAM |
| System RAM | 32GB workable, 48GB comfortable (⚠️ not independently confirmed exact floor) |
| Storage | 60-80GB+ (weights ~45-70GB dominate; outputs are a rounding error) |
| CUDA | Match whatever the specific rented host's "Max CUDA" shows — varies per listing, always re-check |

---

## 5. Architecture — the full pipeline, one call

```
user prompt (text, or +reference image for I2V)
       │
       ▼
Gemma-3 12B (text encoder) — tokenize → embed → transformer layers
       │  (LM head/softmax/temperature NOT used — we stop at the
       │   hidden-state embedding, Gemma-3 never "writes" text here)
       ▼
embedding vector
       │
[ Gemma-3 PURGED from VRAM — mandatory, see §3 ]
       │
       ▼
LTX-2 19B (DiT, diffusion transformer) — NOT autoregressive, NO LM
head/softmax/temperature. 8 joint denoising steps refine video frames
AND audio waveform TOGETHER (native audio, single pass — not
image-then-motion-then-audio as separate stages)
       │
       ▼
VAE decode → raw frames + waveform
       │
       ▼
ffmpeg (muxing, not editing) → final .mp4
       │
       ▼
served via Wan2GP's Gradio server, port 7860, REST-callable
```

Dependency-order software stack (what needs what to run):
```
Layer 0: OS + CUDA runtime (host-provided, already in the container)
Layer 1: OS tools (python3.10, pip, git, ffmpeg, build-essential)
Layer 2: ML libraries (torch, torchvision, torchaudio — CUDA-matched)
Layer 3: Wan2GP application code (imports Layer 2, won't run without it)
Layer 4: Model weights (data, read by Layer 3's code via torch/safetensors loader)
```

Character/object consistency: none across separate generations by
default (each run starts from fresh random noise). Fix: generate/supply
one reference image per character, use as I2V conditioning on every
clip featuring it. Works well for one character at a time; weakens with
multiple interacting characters in one frame (no verified numeric
threshold — qualitative, not a hard cutoff). Stronger fallback if needed:
LoRA/IP-Adapter fine-tuned on that character.

RAG: not needed — no external knowledge base to retrieve from, the model
translates a description into pixels using only its trained-in
knowledge. "Context" here is just the prompt (+ optional reference
image), not retrieved documents.

Agent layer: not needed — this is one straight forward pass (prompt in,
video out), no decision loop, no tool-calling. ReAct/CoT patterns don't
apply. A thin REST wrapper in front of Wan2GP's own server is sufficient
for the stated intent ("hit this model over REST").

---

## 6. Deployment decision: no Docker build on the rented box

Rented vast.ai/RunPod instances are themselves already Docker containers
— no nested `docker build`/`docker run` access by default (confirmed via
vast.ai's own docs). Chosen path: **plain shell scripts run directly
inside the rented container**, no Dockerfile involved for this POC.

(Alternative paths exist but are NOT the current plan: Path B = build a
custom image with weights pre-baked, on your OWN machine, push to a
registry, select it as the template — enables a true "rent → ready in
under 5 min" flow on every future rental, at the cost of managing a
40-70GB image. Path C = vast.ai's VM rental mode, which does support
nested docker, at higher cost/slower boot/fewer templates.)

---

## 7. The three deployment files (current, final versions)

### preflight.sh
```bash
#!/bin/bash
set -e
echo "== GPU visible? =="
nvidia-smi || { echo "FAIL: no GPU"; exit 1; }
echo "== VRAM check =="
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)
[ "$VRAM" -ge 20000 ] || { echo "FAIL: only ${VRAM}MB VRAM"; exit 1; }
echo "== Disk check =="
FREE=$(df --output=avail -BG . | tail -1 | tr -dc '0-9')
[ "$FREE" -ge 60 ] || { echo "FAIL: only ${FREE}GB free, need 60GB+"; exit 1; }
echo "== Driver / Python present =="
nvidia-smi --query-gpu=driver_version --format=csv,noheader
python3 --version
echo "== Internet reachable =="
curl -sSf -m 10 https://huggingface.co > /dev/null || { echo "FAIL: can't reach huggingface.co"; exit 1; }
echo "ALL CHECKS PASSED — safe to run bootstrap.sh"
```

### bootstrap.sh
```bash
#!/bin/bash
set -e
bash preflight.sh
apt-get update
apt-get install -y build-essential python3.10 python3-pip git ffmpeg
git clone https://github.com/deepbeepmeep/Wan2GP.git
cd Wan2GP
python3 -m venv venv
source venv/bin/activate
# READ docs/INSTALLATION.md FIRST — match the pip index/cu-tag to THIS
# host's "Max CUDA" value (check the rental listing, e.g. 12.8 → use
# a cu124 build, NOT cu130). Never hardcode a version from an old doc.
echo "Check https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/INSTALLATION.md"
read -p "Press Enter once you've run today's real pip install command: "
pip install -r requirements.txt
pip install -U "huggingface_hub[cli]"
huggingface-cli download Lightricks/LTX-2 \
  --include "ltx-2-19b-distilled.safetensors" --local-dir ckpts/
huggingface-cli download google/gemma-3-12b-it --local-dir ckpts/gemma3/
python3 -c "import torch; print('torch:', torch.__version__, '| CUDA available:', torch.cuda.is_available())"
echo "BOOTSTRAP COMPLETE — safe to run start.sh"
```

### start.sh
```bash
#!/bin/bash
set -e
cd Wan2GP
source venv/bin/activate
python3 wgp.py --listen --port 7860
# Stop: Ctrl+C. Stop billing: TERMINATE from the dashboard — deliberately
# manual, never scripted.
```

Downloads resume automatically if interrupted (huggingface_hub's cache
mechanism) — a dropped connection does not restart the 45-70GB from zero.

---

## 8. Docker/OS layer notes (concepts, even though no Dockerfile is built here)

- `apt-get update` refreshes the package INDEX only — does not
  upgrade the image or install anything by itself.
- `python3.10` (not 3.11) because Ubuntu 22.04's default repos ship
  3.10 — 3.11 would need an extra PPA (deadsnakes), not worth it here.
- `build-essential` = compiler toolchain (gcc/g++/make) — needed ONLY if
  a pip package has no prebuilt wheel for this exact setup and falls
  back to compiling from source (e.g. flash-attn, sageattention).
- `python3-pip` ships separately from `python3` in Debian/Ubuntu's apt
  packaging policy (unlike Node's official installer, which bundles npm).
- `venv` isolation is a SEPARATE layer from container isolation — the
  container isolates you from other renters; venv isolates this one
  project's package versions from the container's system Python.
- `-y` on apt auto-answers ALL prompts for that command (not just one
  package) — without it, a script hangs forever waiting for a keypress
  that never comes.
- CUDA/driver/PyTorch stack, bottom to top: GPU silicon → driver (OS
  sees the GPU) → CUDA toolkit (lets software use GPU parallelism) →
  PyTorch (links against CUDA's compiled libraries, version-locked per
  major CUDA version) → your code. `torch.cuda.is_available()` returning
  True is the one command that proves the whole chain is wired correctly.
- Model weight files are flat tensors (learned numeric coefficients),
  not 3D geometry — Wan2GP's code deserializes them into VRAM-resident
  PyTorch tensors via a loader function, same as any file read.

---

## 9. Current chosen vast.ai instance + template

```
Offer: Type #20017835, Czechia (CZ)
GPU: 1x RTX 3090, 24GB VRAM, 35.3 TFLOPS
Max CUDA: 12.8   ← use a cu124 (NOT cu130) torch build on this host
Reliability: 99.03%
Download: 549 Mbps  (~13-14 min estimated for ~55GB weights)
Price: $0.214/hr (+ bandwidth: $4.00/TB up, $2.667/TB down)

Template config (final, corrected):
  Image: vastai/base-image:cuda-12.8.1-auto
  Disk: 80GB (raised from a broken 32GB default)
  Ports: default portal ports + 7860 added manually (Wan2GP's port —
         NOT included by default, must be added by hand every template)
  Launch mode: Interactive shell server, SSH (direct) — Jupyter NOT
         needed, skip its HTTPS certificate entirely
  On-start script: LEFT BLANK — the earlier 'Preflight.sh' entry was
         a bug (file doesn't exist yet on a fresh instance, and a bare
         filename isn't directly executable). Automating this via
         PROVISIONING_SCRIPT is a valid later optimization, not now.
```

---

## 10. Full walkthrough (current, matches the instance above)

```
1. Template already configured correctly (§9) — create/rent this offer
2. Wait for "running" status (~30-90s)
3. Dashboard → instance → "Connect" button (NOT the Portal link) →
   copy the real SSH command with its real port
4. On your machine: Cmd+Space → Terminal (macOS ships SSH client
   built in, nothing to install) → paste the SSH command
   One-time-ever setup, if not already done:
     ssh-keygen -t ed25519 -C "your-email"
     → paste the .pub file into vast.ai Account → SSH Keys
5. Same terminal: scp -P <port> preflight.sh bootstrap.sh start.sh root@<ip>:~/
6. bash preflight.sh   → confirms 80GB disk, VRAM≥20GB, GPU visible
7. bash bootstrap.sh   → at the PyTorch step, use a cu124 build (§9);
   budget ~13-14 min for model download on this host's bandwidth
8. Test with existing image-generation code FIRST (cheaper/faster
   smoke test) before moving to video — confirms the whole chain
   (Gemma-3 → server → your REST call) works
9. bash start.sh       → confirm port 7860 shows mapped in the
   dashboard's Ports tab before calling it from outside
10. Switch to video generation once images work — same running
    server, no redeploy needed
11. End of session: STOP (not terminate) if you'll return — weights
    persist, only small storage billing continues. TERMINATE only
    when fully done with the whole POC.
```

---

## 11. Cost model (real usage pattern, not always-on)

```
Actual usage: ~10 hrs/month GPU time (batch-style, not continuous)
  10hrs × $0.214/hr (this instance)           = $2.14
  Storage, 80GB × ~$0.10-0.12/GB/mo            = ~$8-9.60/mo
  One-time download bandwidth (~55GB)          = ~$0.15
  ─────────────────────────────────────────────────────
  Approx monthly total, light POC usage        ≈ $10-12/month

Compare: pasted-listing "$0.169-0.214/hr × 720hrs" = ~$108-154/month
  — that number assumes ALWAYS-ON, not this project's actual pattern.
  Confirm intended usage pattern before comparing GPUs on hourly rate
  alone; at true light usage, the $/hr gap between GPU choices barely
  moves the total.

AWS g5.xlarge alternative ($1.006/hr, 22GB VRAM, $200 prepaid credit
available): financially the stronger option for this POC specifically
(credit already paid for, covers ~198hrs of runtime) — considered, but
Vast.ai chosen for this pass due to AWS's greater manual console
configuration overhead. Worth revisiting if further budget is needed.
```

---

## 12. Debugging playbook

```
Script hangs, no output          → unanswered apt prompt (missing -y)
torch.cuda.is_available()=False  → driver/CUDA/torch version mismatch;
                                    re-check nvidia-smi driver version
                                    against torch's cu-tag, and the
                                    host's "Max CUDA" listing
OOM crash mid-generation          → watch nvidia-smi live during a run;
                                    compare against the ~45GB combined
                                    footprint if purge isn't happening
"ffmpeg not found"                → apt install step didn't complete;
                                    check earlier log for a silent fail
"file not found" on model load    → ls ckpts/ — confirm download size
                                    matches expected (~20-43GB / ~25GB),
                                    a killed download leaves a partial
                                    file at the same name
Can't reach API from outside      → check the dashboard's Ports tab —
                                    wgp.py's "running on 7860" is the
                                    INTERNAL port; hit the mapped
                                    EXTERNAL port instead
```

---

## 13. Open questions — still unresolved

1. Exact render time per clip on a real RTX 3090/4090 for the 19B
   model — not independently benchmarked yet; resolve via the sanity
   test in step 8 of §10, then recompute §11's cost model with the
   real number.
2. Gemma 3 12B's real max context token limit — conflicting sources
   (32,768 vs 128K), unresolved.
3. System RAM exact floor for this pipeline — not independently
   confirmed, only the original draft's unverified 32-48GB claim.
4. Whether to eventually move to Path B (custom pre-baked Docker
   image) for faster repeat-rental turnaround — not yet started.

---

## 14. Source links

- Wan2GP: https://github.com/deepbeepmeep/Wan2GP
- LTX-2 (19B, this project's model): https://huggingface.co/Lightricks/LTX-2
- LTX-2.3 (newer, 22B, NOT this project): https://huggingface.co/Lightricks/LTX-2.3
- Gemma 3 12B: https://huggingface.co/google/gemma-3-12b-it
- Wan2GP install docs: https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/INSTALLATION.md
- OOM issue at ~20GB VRAM budget: https://github.com/deepbeepmeep/Wan2GP/issues/1296
- Vast.ai docs (payment, containers): https://docs.vast.ai
- RunPod GPU pricing: https://www.runpod.io/gpu/4090
