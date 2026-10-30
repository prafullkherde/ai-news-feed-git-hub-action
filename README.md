# Personal AI Automation Workbench

This repository is a collection of independent automations, not a single GitHub Action or only a news feed. GitHub Actions schedules or manually starts Python jobs that collect public data, use LLMs where configured, send email or publish content, and keep small amounts of state in Git.

## What runs here

| Workflow | Purpose | Schedule / entry point | Persistent output |
|---|---|---|---|
| Daily Digest | Filter recent technology RSS items for an email digest | Daily, 02:00 UTC; manual run | Email |
| Job Radar | Find and score remote UI/architecture jobs; suppress duplicates between runs | Daily, 01:30 UTC; manual run | [`seen_jobs.json`](seen_jobs.json), email |
| Repo Trend Tracker | Discover fast-growing GitHub projects, classify their lifecycle, and report evidence | Monday and Thursday, 03:00 UTC; manual run | `repo-trend-tracker/data/`, dashboard data, email |
| Stock Debate | Debate and review a small configured ticker list, then verify prior price targets | Weekdays, 13:00 UTC; manual run | `Multi-Agent-Stock-Debate/logs/`, email |
| Daily Carousel Pipeline | Generate carousel text, render slides, and publish one queued carousel per run to Instagram | Daily, 07:30 UTC; manual run | `social-media-automatio/state/queue.json`, `social-media-automatio/carousel-images/` |
| LTX-2 GPU workflows | Manually manage a Vast.ai GPU instance, persistent weights volume, and optional container image | Manual dispatch only | `social-media-automatio/ltx2-video-gpu/price-log.csv` |
| Test Image Generation APIs | Manually compare external image-generation APIs | Manual dispatch only | Workflow artifact |

Cron times are UTC. The schedule and current implementation can change; see the workflow files for the source of truth. The carousel queue is configured for four posts per day, but only one scheduled trigger is enabled and each run publishes one item, so it currently posts at most once per scheduled day. Facebook publishing is present as a helper but disabled in the active pipeline.

## Architecture

```text
RSS / GitHub / Yahoo Finance / Meta / other APIs
                 ↓
       Scheduled or manual Actions
                 ↓
 Python component (fetch → filter, analyze, or render)
                 ↓
      Email, dashboard data, or social post
                 ↓
     Small state files committed back to Git
```

The workflows are independent. There is no shared application server or central database; the repository itself is an audit trail for state such as seen jobs, carousel queue status, stock-debate logs, and trend snapshots.

## Repository map

| Path | Component |
|---|---|
| [`build-send-email.py`](build-send-email.py) | RSS-based technology digest |
| [`job_radar.py`](job_radar.py) | Job discovery, scoring, and cross-run deduplication |
| [`Multi-Agent-Stock-Debate/`](Multi-Agent-Stock-Debate/Readme.MD) | Scheduled stock analysis and Streamlit on-demand interface |
| [`repo-trend-tracker/`](repo-trend-tracker/README.md) | GitHub repository discovery, lifecycle tracking, and dashboard |
| [`social-media-automatio/`](social-media-automatio/Carousel-pipeline.md) | Instagram carousel publishing and LTX-2 GPU scripts |
| [`.github/workflows/`](.github/workflows/) | Schedules, manual operations, and stock-analysis unit tests |
| [`reusable-prompt/`](reusable-prompt/find-ai-solvable-problems-prompt.md) | Reusable prompt |
| [`PROJECT_REVIEW.md`](PROJECT_REVIEW.md) | Recorded architecture, coverage, CI sample, and prioritized gaps |

## Setup

This is a set of opt-in personal workflows, not a one-command application. Choose the components you intend to run, configure only their required GitHub Actions secrets and variables, then review and manually dispatch that workflow before relying on its schedule. Component-specific setup and configuration are documented in the linked READMEs and workflow YAML.

The common email/LLM workflows use `GROQ_API_KEY_FOR_AUTO_EMAIL`, `RESEND_API_KEY`, and `MY_EMAIL`. Other components need additional credentials (for example, Meta publishing or Vast.ai); consult the relevant workflow before configuring secrets. Never put credentials in the checked-in Python settings files.

The stock-debate regression tests use the repository's existing dependencies and Python's built-in `unittest`:

```bash
pip install -r Multi-Agent-Stock-Debate/requirements.txt
python -m unittest discover -s Multi-Agent-Stock-Debate/tests -v
```

These tests cover a small part of the stock component only. There is no measured repository-wide coverage or full validation suite yet.

## Important limitations

- Stock recommendations and price targets are LLM-generated decision support, not a validated strategy or statistical forecast. There is no broker integration or automatic trade execution. See [the stock-debate notes](Multi-Agent-Stock-Debate/Readme.MD).
- The on-demand Streamlit stock app's passcode is optional; secure its deployment before exposing it publicly to avoid unintended use of configured API quota.
- The Repo Trend Tracker dashboard is published at [GitHub Pages](https://prafullkherde.github.io/ai-news-feed-git-hub-action/repo-trend-tracker/). Each tracker run copies the dashboard and its generated data into `docs/repo-trend-tracker/` for deployment.
- Schedules and external services are best-effort; rate limits, credentials, data quality, or API changes can cause a run to fail.
- State is stored in repository files and Git history. This is simple and auditable for personal use, but is not a shared database or a multi-user concurrency design.
- The project review records known reliability and testing gaps; it is a snapshot, not a guarantee of current workflow health.
