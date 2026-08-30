# Repo Trend Tracker

Twice-weekly GitHub Action that finds repos gaining stars fast, cross-checks *why*
(HN, Reddit, GitHub Trending, new releases, fork-of-popular, star-manipulation heuristic),
maps contributors who show up across multiple growing repos, emails a digest, and
feeds a static lifecycle dashboard.

## Required repo layout
This file, `track_and_notify.py`, `requirements.txt`, `data/`, and `dashboard/` must sit
at the **repo root** — not inside a wrapping folder — because the workflow runs
`python track_and_notify.py` from `$GITHUB_WORKSPACE` (the checkout root):

```
your-repo/                       ← repo root, push these contents directly here
├── .github/
│   └── workflows/
│       └── track.yml            ← the scheduled workflow
├── track_and_notify.py
├── requirements.txt
├── data/
│   ├── watchlist_seed.json
│   ├── snapshots.csv            ← append-only history, source of truth
│   ├── notified.json            ← last-notified phase per repo (dedupe)
│   └── health.json              ← last 20 run outcomes, feeds the dashboard banner
└── dashboard/
    ├── index.html
    └── data.json                ← generated each run, capped at MAX_HISTORY_POINTS
```
The script itself resolves paths off `__file__`, not the working directory, so it's
safe regardless of where the workflow's `run:` step executes from — the constraint
above is purely about the workflow's `python track_and_notify.py` call finding the file.

## Lifecycle phases (matches the state diagram)
`Birth → Discovery (stars<100) → Early Signal (velocity rising) → 🚨 Breakout
(crosses FAST_GROWTH_STARS_PER_DAY) → Popularizing (sustained) → Popular → Saturation
→ Maintenance → Unmaintained`. Only **Breakout** and **Popularizing** trigger a
causality lookup + email; a repo is re-emailed only when its phase changes
(`data/notified.json`).

## WHY it's growing — causality signals
On every Breakout/Popularizing repo the script gathers, then hands to Groq to
categorize into a fixed taxonomy (`new_feature, new_release, viral_social_post,
influencer_mention, ai_integration, benchmark_result, company_adoption,
trending_technology, tutorial_or_video, dependency_ecosystem_change,
fork_of_popular_project, possible_star_manipulation, unclear`):
- **Hacker News** — Algolia search API
- **Reddit** — public `/search.json`, no auth
- **GitHub Trending RSS** — was it trending today
- **New release** — GitHub Releases API, published in last 14 days
- **Fork of popular repo** — GitHub's own `fork`/`parent` fields
- **Star-manipulation heuristic** — star spike with ~zero fork/issue movement (cheap
  proxy inspired by the StarScout paper's methodology, arxiv 2412.13459 — a signal
  to look closer at, not a verdict)

**Not covered, no free API without a key:** X/Twitter mentions, YouTube/video coverage,
influencer identity. If you add API keys for these later, drop them into `validate_growers()`
alongside the existing signals — same evidence-string pattern.

## Setup (one-time)
1. Push this repo to GitHub.
2. Repo Settings → Secrets and variables → Actions → add:
   - `RESEND_API_KEY`
   - `MY_EMAIL` (comma-separated if multiple)
   - `GROQ_API_KEY_FOR_AUTO_EMAIL`
   - `GITHUB_TOKEN` is **not** needed — Actions injects it automatically.
3. (Optional) Settings → Secrets and variables → Actions → Variables → add
   `DASHBOARD_URL` once GitHub Pages is live, so the email links to it.
4. Settings → Pages → Deploy from branch → `main` → `/dashboard` (or `/docs`, adjust path)
   to serve `dashboard/index.html` + `dashboard/data.json` for free.
5. Edit `data/watchlist_seed.json` — two lists:
   - `always_track`: exact repos to keep tracking regardless of trending/search that week.
   - `topics_of_interest`: GitHub topics (e.g. `angular`, `kubernetes`, `llm-agents`) —
     discovery runs one search per topic (`topic:{x} pushed:>14d ago`) so candidates skew
     toward your actual stack instead of generic virality. Defaults are pre-set from your
     Angular/Spring Boot/Kubernetes/OpenShift/LLM-agent stack — edit freely.

## Who maintains `data/snapshots.csv`?
Nobody but this pipeline. It's not sourced from an external maintained dataset — the
Action appends to it and commits it back on every run. Git history on that one file
**is** your audit trail (who/when data changed); there's no separate maintainer to
depend on or break.

## Exception handling & edge cases
| Failure mode | Handling |
|---|---|
| GitHub primary rate limit hit mid-run | Detected via `X-RateLimit-Remaining: 0`; snapshot loop stops early (doesn't burn remaining candidates on guaranteed 403s), logged as a run issue |
| `/contributors` returns 202 (still computing) or 404 | Treated as empty contributor list, not a crash — retried automatically next run |
| Malformed/corrupt row in `snapshots.csv` | Skipped on load (bad date or non-numeric star count), rest of history still loads |
| Corrupt `notified.json` / `watchlist_seed.json` | Treated as empty/default rather than crashing the run |
| Disk write fails (`snapshots.csv`, `notified.json`) | Caught, logged as an issue, run continues instead of dying mid-pipeline |
| Discovery returns nothing | Logged as an issue; run still completes (snapshotting/dashboard/health steps still execute on whatever history already exists) |
| Groq call fails/times out | `llm_reason()` returns `{}` — email still sends with velocity/evidence, just no WHY-category line |
| Resend call fails | Data (snapshots/dashboard/notified/health) is already written to disk **before** the email step, so nothing is lost; script exits non-zero afterward so GitHub Actions' own failure email fires as a backstop |
| One repo's API call throws | Wrapped per-function (`try/except`) — a single bad repo doesn't take down the whole run |

Each stage in `main()` (discovery, snapshotting, velocity, evidence-gathering) is wrapped
independently — one stage failing degrades that stage's output, it doesn't abort the run.

## Health / failure notifications
Two channels, neither depends on the other:
1. **Dashboard** — every run appends a status entry to `data/health.json` (bounded to the
   last 20 runs). The dashboard shows a green "Last run OK" banner or a red banner with
   the issue count + an expandable table of recent run issues.
2. **Email** — the regular digest includes a "⚠️ Pipeline issues this run" section
   whenever `RUN_ERRORS` is non-empty, and an email is sent even if there's nothing new
   to report, purely to surface the issue.
3. **Backstop** — if the email step itself is what's broken (Resend down, bad key), the
   script exits non-zero. GitHub Actions emails the repo owner on failed scheduled runs
   by default (Settings → Notifications), and the workflow also has a `Notify on hard
   failure` step that curls Resend directly (no Python dependency) as a second attempt.

## How growth/lifecycle is computed
- Every run appends one row per tracked repo to `data/snapshots.csv` (source of truth,
  git history = your audit trail).
- Velocity = Δstars / days between the last two snapshots for that repo.
- Phase per repo (`Birth → Discovery → Early Signal → Breakout → Popularizing → Popular
  → Saturation → Maintenance → Unmaintained`) is derived from velocity trend + days since
  last push. See `classify_phase()` in `track_and_notify.py` if you want to retune
  thresholds (`FAST_GROWTH_STARS_PER_DAY`, `UNMAINTAINED_DAYS`, `BIRTH_DAYS`,
  `DISCOVERY_STAR_CAP`).
- A repo is only re-emailed when its **phase changes**, not every run (`data/notified.json`
  tracks last-notified phase per repo) — avoids spamming you for the same trend.

## Known limitations (be aware, not blockers)
- `/contributors` on very large/old repos can be capped or return 202 (async) — script
  skips silently on failure rather than blocking the whole run.
- Discovery is capped at `MAX_CANDIDATES_PER_RUN` (45) to stay well inside GitHub's
  5000/hr authenticated rate limit — `always_track` repos are never dropped by this cap,
  only newly-discovered candidates compete for the remaining budget.
- HN/Reddit corroboration is best-effort; absence of a hit doesn't mean the repo isn't
  growing for a real reason, just that those two sources didn't cover it.
- No external DB — data lives in the repo as CSV/JSON. Fine at twice-weekly cadence for
  a few dozen repos; if it grows past a few thousand rows, roll old snapshots into
  weekly averages instead of raw daily rows.

## Zero-build supplement — dropped
`api.star-history.com/svg?...` was suggested earlier as a quick embed, but it runs on a
**shared** free quota against GitHub's API across all of star-history.com's users — under
load it returns errors like "GitHub restricted access to star data," and that's outside
anything we control (their quota, not ours). Not worth depending on. The dashboard here
already draws the same kind of chart from your own committed history, with no shared
quota to hit — use that instead.

## "Most popular" reference sites you could fold into `watchlist_seed.json`
For established (not just fast-growing) popular repos, worth knowing about:
- **Gitstar Ranking** (gitstar-ranking.com) — live leaderboard of most-starred repos/users.
- **OSSInsight Collections** (ossinsight.io/collections) — curated, updated rankings by
  category (e.g. "LLM," "Frontend Framework") — closer to your area-of-interest angle
  than raw star count.
- **GitHub's own search**, sorted by stars (`stars:>50000&sort=stars`) — the canonical
  source, no third party involved, already used indirectly via `repos_from_search()`.
None of these do velocity/lifecycle/causality — that's still this pipeline's job; they're
just good sources to seed `always_track` from if you want specific big names tracked
permanently.

## Evergreen reference used here
Discovery partly rides on **OSSInsight** (`api.ossinsight.io`, backing
[github.com/wangzuo/ossinsight](https://github.com/wangzuo/ossinsight)) — it already
aggregates 5B+ GitHub events into trending/growth data, free, no key. No reason to
re-derive that ourselves; `repos_from_ossinsight()` in `track_and_notify.py` calls its
`/v1/trends/repos` endpoint. Nothing found that does the full pipeline (velocity +
lifecycle + causality + contributor overlap) end-to-end — that part stays custom.
