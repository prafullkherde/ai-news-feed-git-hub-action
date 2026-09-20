# requirements.md — LTX-2 19B Distilled Video POC (validated base file)

**Verdict: Build it — but the draft you pasted has one root-cause error that
touches every number downstream. Corrected below. This file is v2, meant to
be the single source future deployment code / scripts are generated from.**

---

## 0. Intention (locked)

Generate short (5–10s) social-media-ready video clips with synchronized audio,
text/image-to-video, on a rented single-GPU box, at near-zero marginal cost
per clip, using the **original LTX-2 19B Distilled** checkpoint via Wan2GP.
No RAG. No multi-GPU. No real-time serving. This is a POC, not a production
inference service.

---

## 1. Root-cause correction (why v1 needed a rewrite, not a patch)

The pasted draft names `ltx-2-19b-distilled` and `LTX-2.3 Distilled 1.1` as
the same model choice. **They are two different model generations,
from two different repos, with two different VRAM/speed profiles**:

```
Lightricks/LTX-2       ──▶  ltx-2-19b-distilled.safetensors   (19B, this POC)
Lightricks/LTX-2.3     ──▶  Distilled 1.1                     (22B, newer/bigger)
                              WanGP changelog, verbatim:
                              "This model is bigger (22B versus 19B)"
```

Every VRAM number, benchmark, and install instruction in a spec has to pick
one lineage. This file locks to **19B** (your stated choice: smaller, more
battle-tested at 24GB, less likely to blow the VRAM budget mid-POC).

---

## 2. Fact-validation ledger

Per protocol — every claim tagged Exists / Adopted / Disciplined, or marked
unverified. Nothing below is stated with borrowed confidence.

| Claim | Exists? | Adopted? (evidence) | Disciplined in practice? | Gap / root cause |
|---|---|---|---|---|
| `ltx-2-19b-distilled.safetensors` is a real checkpoint | ✅ Yes — Lightricks/LTX-2 on HF | ✅ Yes — official ComfyUI-LTXVideo docs reference it directly | N/A (static artifact) | — |
| Text encoder = Gemma 3 12B | ✅ Yes — confirmed on HF model card | ✅ Yes — same repo, ComfyUI docs | N/A | — |
| License = "LTX-2 Community License Agreement" | ✅ Yes — exact slug on HF | ✅ Yes | N/A | — |
| `deepbeepmeep/Wan2GP` repo, actively maintained | ✅ Yes | ✅ Yes — active changelog through mid-2026, Discord community, forks | ⚠️ Partial — fast-moving project, docs/VRAM numbers go stale between releases | Root cause: solo-maintainer velocity outpaces doc freshness — treat any pinned number in this file as **needs re-check at deploy time**, not gospel |
| RunPod Community RTX 4090 = $0.34/hr | ✅ Yes | ✅ Yes — confirmed on runpod.io directly + 3 independent price trackers | ✅ Stable across sources checked this session | — |
| Vast.ai RTX 4090 ~$0.37/hr floor | ✅ Yes | ✅ Yes — marketplace, floor price confirmed | ⚠️ Variable — marketplace, not fixed | Root cause: bid-based marketplace, price is a floor not a guarantee |
| 24GB VRAM is the "minimum" for LTX-2 | ⚠️ Stale claim | — | — | WanGP shipped VRAM optimizations since — current builds run 10s@720p in as little as **8GB**. 24GB is comfortable headroom, not the floor. Corrected below. |
| `torch==2.10.0` + stable `cu130` index installs cleanly | ⚠️ UNVERIFIED [web-uncrossed] | — | — | 2.10.0/cu130 exists but on nightly/test channels; a real user's working install this session showed `torch 2.9.1+cu130`. Don't hardcode — pull `docs/INSTALLATION.md` fresh at deploy time (see §4) |
| RTX 5090 benchmark numbers (43.5s/49.8s, 24.2GB peak) | ⚠️ UNVERIFIED [source: draft only] | — | — | Not independently found this session. Treat as directional, re-benchmark on your own 4090 (see §5) |
| sageattention 2.2.0 → ~40% speed gain | ⚠️ UNVERIFIED [source: draft only] | — | — | Not checked this session |
| $0.15 / 1-min video, from "15–20 min render @ $0.34/hr" | ❌ Arithmetic error | — | — | $0.34/hr × 15–20 min = **$0.085–$0.113**, not $0.15. Recomputed in §5 |

---

## 3. Corrected model + infra spec

| Attribute | Value | Confidence |
|---|---|---|
| Model | `ltx-2-19b-distilled.safetensors` | ✅ verified name/repo |
| Text encoder | Gemma 3 12B (`google/gemma-3-12b-it...`) | ✅ verified |
| Generation steps | 8 (distilled) | ✅ consistent across every source found |
| GPU | RTX 4090, 24GB | ✅ your locked choice |
| VRAM floor (current WanGP) | ~8GB with optimizations, **20–21GB observed for full FP8 pinning without partial-offload tuning** (real OOM reported at 19.6GB cap in a GitHub issue) | ⚠️ range, not a single number — budget for the high end |
| System RAM | 32GB workable, 48GB comfortable | ⚠️ UNVERIFIED exact floor — draft's numbers plausible, not independently confirmed |
| CUDA / driver | Whatever the rental template ships (12.4+ safe baseline per multiple sources) | ⚠️ verify against `docs/INSTALLATION.md` at deploy time, not this file |
| Storage | 60GB+ (19B checkpoint + Gemma 12B text encoder + temp/output) | Recomputed — draft's "100GB" is generous/safe, keep it |

---

## 4. Deployment-as-code spec (stage → tool → executor)

This is the section future scripts get generated from. Where a value is
version-sensitive, the instruction is "fetch fresh," not a hardcoded pin —
per the ledger above, pinning now would ship a stale version.

| Stage | Exact action | Executor | Where | Maturity |
|---|---|---|---|---|
| 1. Provision | Rent RTX 4090, PyTorch+CUDA template, 60GB+ volume | Human (or Terraform/API later) | RunPod or vast.ai | Mature |
| 2. Fetch install truth | `curl` or open `docs/INSTALLATION.md` from the live `deepbeepmeep/Wan2GP` repo — get today's exact python/torch/CUDA pin | Script | Pod, first boot | New — this step doesn't exist in the draft and should |
| 3. Clone | `git clone https://github.com/deepbeepmeep/Wan2GP.git && cd Wan2GP` | Script | Pod | Mature |
| 4. Env | `conda create -n wan2gp python=<from step 2>` | Script | Pod | Mature |
| 5. PyTorch | `pip install torch==<from step 2> torchvision torchaudio --index-url <from step 2>` | Script | Pod | Mature, but must read from step 2 — don't hardcode `2.10.0`/`cu130` |
| 6. Deps | `pip install -r requirements.txt` | Script | Pod | Mature |
| 7. Model pull | Select `ltx-2-19b-distilled` in Wan2GP UI, or `huggingface-cli download Lightricks/LTX-2 --include "ltx-2-19b-distilled.safetensors"` | Script | Pod | Mature — exact command confirmed in official ComfyUI-LTXVideo docs |
| 8. Launch | `python wgp.py` | Script | Pod | Mature |
| 9. Sanity check | `nvidia-smi` + one 4s test clip at 720p before batching | Human | Pod | New — missing from draft, cheap insurance |
| 10. Batch generate | Loop prompts, one session, no idle gaps | Script | Pod | Mature |
| 11. Pull outputs | `scp`/rsync clips to laptop | Script | Local | Mature |
| 12. Teardown | **Terminate**, not stop | Human/script | Dashboard/API | Mature — see blocker #2 below for why this is a named step, not an afterthought |

---

## 5. Cost model — recomputed, not asserted

```
cost_per_video = (render_minutes / 60) × $0.34   [RunPod Community, confirmed]
```

Render time itself is the one number nobody has confirmed for *this exact*
checkpoint on *this exact* GPU — the draft's 15–20 min figure is plausible
but unverified this session. Until step 9 (sanity check) gives you a real
number, treat cost as a range:

| Render time/video | Cost/video | 30 videos/month |
|---|---|---|
| 10 min | $0.057 | $1.70 |
| 15 min | $0.085 | $2.55 |
| 20 min | $0.113 | $3.40 |

Run the sanity-check clip first, plug the real minutes-per-clip into this
formula, and that becomes the number you commit to — not a borrowed one.

---

## 6. Execution blockers — pivot without losing the aim

| Blocker (trigger) | Pivot | Why it preserves the aim |
|---|---|---|
| OOM loading FP8 model near 20GB (confirmed real GitHub issue on a 24GB-class card) | Switch to WanGP's low-VRAM Profile (3 or 3.5) or drop resolution one notch for the first pass | Same model, same output contract — only speed changes |
| Spot/interruptible instance reclaimed mid-batch | Use RunPod Community **on-demand**, not spot, for this POC; if cost forces spot later, checkpoint/save each clip immediately on generation so a reclaim loses one clip, not the batch | Aim (cheap clips) survives; only the failure blast-radius shrinks |
| `torch`/CUDA pin from this file breaks on deploy day | Never hardcode — step 2 in §4 exists precisely so you re-read `docs/INSTALLATION.md` fresh each deploy, not trust a stale pin | Keeps the spec correct without needing this file rewritten every WanGP release |
| Actual render time blows the §5 cost model | Re-run §5 with the real number before scaling to 30 videos/month — don't discover the real cost at the end of a batch run | Aim (₹300/month-class cost) is a target to verify, not assume |
| Temptation to switch to LTX-2.3 mid-POC for "better quality" | Treat as a separate v2 branch — new venv/pod, new VRAM budget (22B, not 19B) — never retrofit into this pipeline | Stops silent scope creep from invalidating every number in this file |
| Gemma 3 12B text encoder + 19B model both resident in VRAM at once | Confirm Wan2GP's purge-after-encode behavior is active (it's the default, per its "GPU Poor" design) before assuming both fit simultaneously | Prevents debugging a phantom "24GB isn't enough" problem that's actually a config issue |

---

## 7. Open questions (still unresolved — flag before generating deployment code)

1. Host: RunPod Community vs vast.ai — not yet decided. §4 works for either; final choice only changes step 1/2's exact CLI/API calls.
2. Exact render time per clip on a real RTX 4090 — unverified, resolve via §4 step 9.
3. System RAM floor — draft says 48GB/32GB-with-flags; not independently confirmed this session, worth a real test rather than trusting either number blind.

---

## 8. Sourced link list

- Wan2GP repo: https://github.com/deepbeepmeep/Wan2GP
- LTX-2 (19B, this POC's model): https://huggingface.co/Lightricks/LTX-2
- LTX-2.3 (newer, 22B, NOT this POC): https://huggingface.co/Lightricks/LTX-2.3
- ComfyUI-LTXVideo official model-download docs: https://docs.ltx.video/open-source-model/integration-tools/comfy-ui
- RunPod GPU pricing: https://www.runpod.io/gpu/4090
- OOM issue on FP8 distilled model, ~20GB budget: https://github.com/deepbeepmeep/Wan2GP/issues/1296
