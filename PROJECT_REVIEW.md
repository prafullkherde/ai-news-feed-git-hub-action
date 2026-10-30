# Repository Review

**Reviewed:** 2026-10-30  
**Scope:** Workflows and tracked application code in this repository. This is a static review plus a sample of recent GitHub Actions failures, not a live audit of third-party accounts or deployed services.

## Intent and design

This repository is a personal automation workbench made of separate GitHub Actions pipelines. Most jobs follow the pattern:

```text
scheduled/manual trigger → external data fetch → optional LLM analysis
→ email, dashboard data, or social post → commit small persistent state
```

There is no shared runtime, database, or common application package. Each workflow runs independently, and Git history provides the audit trail for files such as `seen_jobs.json`, the carousel queue, ticker logs, and trend snapshots.

## Components and current state

| Component | Purpose and implementation | State / external dependencies |
|---|---|---|
| Daily Digest | Fetches recent technology feeds, filters items with Groq, emails the result | Resend; RSS and Groq |
| Job Radar | Finds remote roles, scores them against a configured profile, deduplicates listings across runs | `seen_jobs.json`; job feeds, Groq, Resend |
| Repo Trend Tracker | Discovers repositories, snapshots growth, classifies lifecycle, gathers evidence, and emails changes | CSV/JSON under `repo-trend-tracker/data/`; GitHub, OSSInsight, HN/Reddit, Groq, Resend |
| Stock Debate | Runs Executor/Critic/BA review over configured tickers, clamps proposed position sizes, and compares matured targets with later closes; includes a Streamlit UI | Per-ticker JSON logs; Yahoo Finance, Groq, Resend |
| Carousel | Generates text, renders slides locally, hosts images in the repository, and publishes one queued item per run to Instagram | Queue and image files; Groq, GitHub raw-content URLs, Meta |
| LTX-2 GPU tools | Manually provisions/operates Vast.ai instances and a persistent model-weights volume | Vast.ai, Hugging Face, SSH credentials |
| Image API experiment | Manually compares external image-generation services; not a unit-test suite | Optional provider keys; workflow artifact |

## CI failure sample and resolutions

The latest 100 workflow runs visible on 2026-10-30 contained 55 failures: 45 GitHub Pages builds and 10 Stock Debate runs. Logs from representative failures and prior repeated Stock Debate failures showed two recurring causes:

1. **GitHub Pages** — runs `40892235454` and `40892107413` both configured Jekyll's source as `./docs`, but the repository had no `docs/` directory. Jekyll failed while changing into `/github/workspace/docs`. A Pages landing page now provides the missing source. The Repo Trend Tracker dashboard is now copied into `docs/repo-trend-tracker/` by its workflow for publication.
2. **Stock Debate** — runs `40934180742`, `40747188581`, and `40561062689` all failed with `float division by zero` for all four configured tickers. Stored predictions include zero/NaN targets; the verification loop divided by the target when computing percentage error. Verification now ignores invalid/non-positive prices, and market data is cleaned before use. Regression tests cover invalid and valid prices.

The local regression tests pass. Initial Stock Debate Tests runs for the pushed branch (`41008695484`) and pull request (`41008699192`) ended `action_required` with zero jobs. A later push run (`41009274015`) passed, and the Pages build/deploy run (`41009274164`) succeeded after the `docs/` landing page was added.

## Coverage

Before this change, there was no committed unit-test suite or coverage measurement. `social-media-automatio/test_image_apis.py` is a manual live-service comparison, not deterministic testing of application behavior. This change adds four isolated Stock Debate regression tests and a workflow that runs them on relevant pushes and pull requests. The rest of the repository still has no unit, end-to-end, or coverage-reporting suite; no repository-wide coverage percentage is known.

## Review findings and gaps

### Addressed here

- Prevent zero, NaN, infinite, and otherwise invalid prices from crashing historical prediction verification or being treated as usable market prices.
- Return a three-month return only when sufficient observations exist, using roughly 63 trading sessions rather than the full six-month history.
- Provide the `docs/` source required by the configured Pages build.
- Align the top-level README and the Stock Debate, carousel, and trend-tracker notes with the checked-in schedules and implementation.
- Make the LTX-2 health-check step fail when the HTTP check fails rather than reporting a successful workflow.

### Remaining priorities

1. **Expand tests beyond Stock Debate.** Add deterministic unit tests for job deduplication/scoring, trend lifecycle classification, carousel queue transitions, and email formatting. Keep live provider calls outside the regular test suite.
2. **Resolve carousel cadence and behavior intentionally.** `POSTS_PER_DAY` is four, but one cron trigger is enabled, one carousel is posted per run, and Facebook publishing is commented out. Decide whether to enable more scheduled posts or keep the current lower cadence; do not infer this from the old notes.
3. **Verify the published trend dashboard after deployment.** The tracker workflow copies its current HTML and data into `docs/repo-trend-tracker/`; the Pages site and workflow summary link to that dashboard.
4. **Reduce workflow drift and deployment risk.** Two manual LTX-2 setup workflows coexist; document which is current and retire the other after confirming it is no longer needed. Several workflows install unpinned dependencies and rely on external APIs that can change.
5. **Secure the on-demand UI.** The Streamlit passcode is optional; require an access gate or otherwise restrict deployment before exposing credentials-backed analysis publicly.
6. **Improve operational diagnostics.** Add concise runbooks for provider quota failures, credential rotation, failed publishes, and recovery of committed state. Review all network calls for timeouts and all jobs for explicit failure signaling.

## Trading-related scope

The stock component already combines fundamental fields, technical indicators, headlines, an Executor/Critic debate, position-size caps, and a prediction-verification record. It does **not** place orders. Its price targets are LLM outputs, not statistically validated forecasts. Safe next steps are data-quality tests, benchmarked backtesting with fees/slippage, and confidence calibration; adding untested entry/exit rules or broker execution would be unsafe and is not included in this change.
