# LTX-2 Video Pipeline — Project Context

Repo: `github.com/prafullkherde/ai-news-feed-git-hub-action`
Project folder: `social-media-automatio/ltx2-video-gpu` (note: "automatio" — existing typo in the repo, kept as-is since renaming would break paths everywhere)

## 1. Intent

Self-hosted AI video generation (not paid APIs like Kling/Veo — ~7-9x cheaper at target volume) for 2-3 videos/day, ~2 min each, to grow a channel before introducing paid tooling. Fully automated via GitHub Actions — no manual SSH, no manual CLI, "API hit → instance wakes → generates → destroys."

## 2. Model stack

| Component | Value |
|---|---|
| Video model | LTX-2 19B distilled (FP8), gated HF repo |
| Text encoder | Gemma 3 12B |
| Serving app | Wan2GP (open source), port 7860 |
| Runtime image | `robatvastai/wan2gp` (readymade, vast.ai-affiliated, updates near-daily) — **not** a custom-built image |
| Wan2GP real path in image | `/opt/workspace-internal/Wan2GP/wgp.py` (confirmed by discovery run — not `/root/Wan2GP` as first assumed) |
| ffmpeg | Confirmed present in the image |
| GPU floor | ~20-21GB VRAM (RTX 3090/4090-class or equivalent, e.g. RTX PRO 4000 also qualifies at 24GB) |

## 3. Repo file inventory

| File | Git path | Purpose |
|---|---|---|
| `Vast-ai-GPU-life-cycle-control.yml` | `.github/workflows/` | **Daily** driver: create → deploy → health_check → generate → stop/start/destroy. Options reordered + described in sequence. ⚠️ **Not yet updated** with volume/machine_id pinning — still has pre-volume syntax, will likely fail as-is. |
| `Ltx2 setup volume v2.yml` | `.github/workflows/` | One-time/occasional: finds or creates the `ltx2_weights` volume, rents a temp instance on that machine, downloads weights once, destroys the temp instance. Idempotent — reuses existing volume, never recreates. |
| `LTX2-Build-Push-Image.yml` | `.github/workflows/` | **Optional fallback only** — builds a custom image from `docker/Dockerfile` and pushes to GHCR. Not currently used; the readymade image covers this. |
| `preflight.sh` | `social-media-automatio/ltx2-video-gpu/scripts/` | Bandwidth probe (fails fast if host <100 Mbps) + GPU/VRAM/disk checks. Headless-safe. |
| `bootstrap.sh` | same | Checks `/data` (the mounted volume) for existing weights, skips download if present; downloads via `python3 -m huggingface_hub...` if missing (not the `huggingface-cli` binary — see §5). |
| `start.sh` | same | Idempotent launch guard (`pgrep` check before starting wgp.py). |
| `find_gpu_volume_match.py` | same | Real committed Python file — finds the cheapest GPU offer whose machine also offers volume storage, GPU-first. Replaces three separate embedded-YAML-Python failures (see §5). |
| `Dockerfile` | `social-media-automatio/ltx2-video-gpu/docker/` | **Optional fallback only** — not used unless the readymade image is ever found missing something. |
| `price-log.csv` | `social-media-automatio/ltx2-video-gpu/` | Appended by `create` each run: timestamp, offer, GPU, price. |

**Secrets (repo Settings → Secrets → Actions):** `LTX2_GPU_VAST_API_KEY`, `LTX2_GPU_SSH_PRIVATE_KEY`, `LTX2_GPU_HF_TOKEN` (HF read-token from the account that accepted the LTX-2 license).

## 4. Architecture decisions (and why)

- **Readymade image over custom build** — `robatvastai/wan2gp` already has torch/CUDA/Wan2GP baked in; building our own added maintenance for no benefit once this was found.
- **Persistent Volume over re-downloading weights every run** — two real deploy failures (dropped SSH mid-download, `docker_build()` host error) both traced back to re-pulling 45-70GB from scratch on a slow/bad host each time. Volume removes this from the daily critical path entirely.
- **Volume pins you to one `machine_id`** — a volume only attaches to an instance on its own physical host. This is a real trade-off: you give up "shop the whole marketplace daily" in exchange for never re-downloading. Worth it at this workload; named explicitly so it's not mistaken for a bug.
- **GPU-first search, not volume-first** — proven empirically: searching cheapest-volume-first and checking for GPU availability after picked 10/10 machines with zero free GPUs. Flipped to GPU-first (scarce, fast-moving resource), volume-second (abundant, stable resource) — matches how real schedulers (Kubernetes, SkyPilot) do it.
- **Daily cycle, not weekly batch** — weekly batching was the plan before the image+volume fix made daily `deploy` fast and reliable again.
- **Destroy nightly, not stop** — once setup is fast (image+volume), there's no reason to pay idle instance-disk cost for "warm" standby.

## 5. Bug history (chronological, short)

| # | Bug | Root cause | Fix |
|---|---|---|---|
| 1 | `scp` path not found | `PROJECT_DIR` missing `social-media-automatio/` prefix | Added `env.PROJECT_DIR` |
| 2 | `bootstrap.sh` not found | Filename case mismatch (`Bootstrap.sh` vs `bootstrap.sh`) | Renamed file to lowercase |
| 3 | `curl: Empty reply` on health check | Connecting via vast.ai's **proxy** SSH (`ssh_host`/`ssh_port`), not **direct** (`public_ipaddr` + `ports["22/tcp"]`) — proxy is slow/unreliable for large transfers | Switched extraction to direct fields |
| 4 | "Invalid workflow file" — **three separate times** | Multi-line Python embedded in YAML `run:` blocks breaks YAML indentation rules (quoted strings AND heredocs both fail this way) | Moved all multi-line Python to a real committed `.py` file, called as one line |
| 5 | Deploy killed at `timeout 1800`, exit 124 | Fixed-duration timeout can't survive a 50x bandwidth swing across random hosts | Replaced with idle-based polling (fails only on no progress, not total duration) |
| 6 | `vastai destroy/stop/start` silently no-op in CI | Y/N confirmation prompt, no TTY in GitHub Actions | `yes \|` prefix on all three |
| 7 | `vastai create volume: id required` | Needs an offer ID from `search volumes` first, not freeform `--name`/`--size` | Search-then-create pattern |
| 8 | 403 attaching volume | Volume only attaches to an instance on its **own machine_id** | Pinned instance search to the volume's machine |
| 9 | `ModuleNotFoundError: torch`, `huggingface-cli: command not found` | Non-interactive `ssh host "cmd"` skips `.bashrc`, so conda/venv activation is invisible | Source `.bashrc`/`/etc/profile` explicitly; call `python3 -m huggingface_hub...` instead of the CLI shim |
| 10 | Volume created on a GPU-dead host (10/10 failures) | Searched cheapest-volume-first without checking GPU availability | Flipped to GPU-first search (§4) |
| 11 | `docker_build()` host-side failure | Random vast.ai host infrastructure fault, invisible to our scripts | Auto-destroy-on-failed-poll (doesn't fix the host, stops it from billing silently) |

## 6. Cost (real data points gathered, not fully measured end-to-end yet)

- Volume, 80GB: **$16-21/month** (varies by host — seen both)
- Compute, RTX 3090-class: **$0.15-0.27/hr** (seen range, including one RTX PRO 4000 at $0.27/hr)
- Estimated total at 1-2hr/day: **~$21-35/month** — ⚠️ not yet confirmed by a real completed end-to-end run
- Volumes have an **expiry date** (seen: Dec 31, 2026) — needs periodic renewal check, not yet automated

## 7. Still outstanding

1. **Main lifecycle workflow** (`Vast-ai-GPU-life-cycle-control.yml`) needs the same `machine_id` pinning + `--link-volume`/`--mount-path` fix already applied to the setup workflow. Not yet done — deliberately held back until setup succeeds once end-to-end.
2. `LTX2 Setup Volume` workflow has not yet completed successfully end-to-end — last run was fixed post-failure (GPU-first search), not yet re-run and confirmed.
3. Possible merge: fold Setup-Volume's logic into the main lifecycle workflow as one more `action` option, so there's only one file instead of two that must stay in sync manually. Proposed, not yet built — pending confirmation.
4. `bootstrap.sh`/`start.sh`'s `WAN2GP_DIR` needs updating to `/opt/workspace-internal/Wan2GP` (confirmed via discovery) — confirm this has actually been pushed.
5. README — requested, intentionally deferred until the pipeline is confirmed working once end-to-end, so it documents what's real rather than what's planned.
6. Full cost/timing numbers — need one real completed daily cycle to replace the current estimates.
