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
│   └── notified.json            ← last-notified phase per repo (dedupe)
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
5. Edit `data/watchlist_seed.json` to permanently track specific repos regardless of
   whether they show up in trending/search that week.

## How growth/lifecycle is computed
- Every run appends one row per tracked repo to `data/snapshots.csv` (source of truth,
  git history = your audit trail).
- Velocity = Δstars / days between the last two snapshots for that repo.
- Phase per repo (`Birth → Discovery → Popular → Saturation → Unmaintained`) is derived
  from velocity trend + days since last push. See `classify_phase()` in
  `track_and_notify.py` if you want to retune thresholds
  (`FAST_GROWTH_STARS_PER_DAY`, `UNMAINTAINED_DAYS`, `BIRTH_DAYS`).
- A repo is only re-emailed when its **phase changes**, not every run (`data/notified.json`
  tracks last-notified phase per repo) — avoids spamming you for the same trend.

## Known limitations (be aware, not blockers)
- `/contributors` on very large/old repos can be capped or return 202 (async) — script
  skips silently on failure rather than blocking the whole run.
- Discovery is capped at `MAX_CANDIDATES_PER_RUN` (45) to stay well inside GitHub's
  5000/hr authenticated rate limit — raise it if you want a wider net.
- HN corroboration is best-effort (Algolia search by repo short name); absence of a hit
  doesn't mean the repo isn't growing for a real reason, just that HN didn't cover it.
- No external DB — data lives in the repo as CSV/JSON. Fine at twice-weekly cadence for
  a few dozen repos; if it grows past a few thousand rows, roll old snapshots into
  weekly averages instead of raw daily rows.

## Zero-build supplement
For a quick visual on any single repo without touching this pipeline:
`https://api.star-history.com/svg?repos=owner/repo&type=Date` — embeddable star-history
chart, ready-made, no auth.

## Evergreen reference used here
Discovery partly rides on **OSSInsight** (`api.ossinsight.io`, backing
[github.com/wangzuo/ossinsight](https://github.com/wangzuo/ossinsight)) — it already
aggregates 5B+ GitHub events into trending/growth data, free, no key. No reason to
re-derive that ourselves; `repos_from_ossinsight()` in `track_and_notify.py` calls its
`/v1/trends/repos` endpoint. Nothing found that does the full pipeline (velocity +
lifecycle + causality + contributor overlap) end-to-end — that part stays custom.
