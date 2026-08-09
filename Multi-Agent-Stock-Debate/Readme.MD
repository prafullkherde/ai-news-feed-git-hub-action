# Multi-Agent Stock Debate — Executor / Critic / Senior BA Reviewer

3 roles, 2 model providers, running over a list of tickers, with a
persistent per-ticker log that verifies yesterday's prediction against
real closing prices before making today's — so right and wrong calls
both build up an actual accuracy record, not just a fresh guess every day.

**Honest limitation, stated up front:** next-day/next-week prices are
LLM-generated estimates, not a statistical model. The verification loop
exists to make that measurable with real numbers instead of assumed.
Don't trade on this before the log has weeks of verified history.

## Architecture

| Role | Model | Job |
|---|---|---|
| Executor | Groq `openai/gpt-oss-120b` | Argues each of 7 rounds (Fundamental → Technical → Sentiment → Bull → Bear → Trade → Risk) |
| Critic | Gemini (candidate list, see below) | Counters every round with a different data point — different vendor on purpose |
| Senior BA Reviewer | Groq `llama-3.3-70b-versatile` (3rd, non-reasoning model) | Reads the whole transcript + yesterday's verified outcome, corrects anything wrong, issues the final BUY/SELL/HOLD + price targets |

## File layout

```
Multi-Agent-Stock-Debate/
├── Main.py                 # orchestrator — imports config, never hardcodes tunables
├── config/
│   ├── __init__.py
│   └── settings.py         # every non-secret value, grouped by agent, commented with WHY
├── logs/
│   └── <TICKER>.json       # one append-only file per ticker, committed back by the Action
└── README.md                # this file
```

## Secrets vs config — why the split

**Only 4 values are true secrets** (things that grant access, not things
that tune behavior): `GROQ_API_KEY_FOR_AUTO_EMAIL`, `GEMINI_API_KEY`,
`RESEND_API_KEY`, `MY_EMAIL`. Everything else — ticker list, portfolio
size, model choice, retry timing — lives in `config/settings.py`, plain
Python, commented, editable directly, visible in `git diff`.

This isn't just tidiness. Putting non-secret values into GitHub Secrets
(as `STOCK_P_*`) caused a real, reproduced bug — see Incident 3 below.
Moving them to a config file removes that entire failure class.

To finish the cleanup: delete the now-unused `STOCK_P_TICKERS`,
`STOCK_P_PORTFOLIO_VALUE`, `STOCK_P_MAX_POSITION_PCT`,
`STOCK_P_CURRENT_EXPOSURE_JSON`, `STOCK_P_MAX_RETRIES`,
`STOCK_P_BASE_BACKOFF_SECONDS`, `STOCK_P_*_REQUEST_DELAY_SECONDS`
secrets from repo settings — they're no longer read anywhere.

## Setup

```bash
cp Multi-Agent-Stock-Debate/stock-debate.yml .github/workflows/
git add . && git commit -m "config-driven refactor" && git push
```
Add the 4 secrets above in repo settings. Edit
`Multi-Agent-Stock-Debate/config/settings.py` directly for anything else
— tickers, portfolio value, position caps, model/timing tuning.

---

## Incident log

Every bug hit in building this, in the order found. Format: **what we
assumed → what actually happened → how we found out → what fixed it.**
Kept here (not just in chat) so the reasoning survives past this
conversation.

### 1. Wrong workflow path
- **Assumed:** the script lived at `stock-agent-debate/main.py`, matching a guessed convention.
- **Observed:** `python: can't open file '.../stock-agent-debate/main.py': No such file or directory`.
- **Identified by:** the actual repo folder was `Multi-Agent-Stock-Debate/` — a different name than assumed, never verified against the real repo first.
- **Fixed by:** cloned the actual repo, read the real file tree instead of guessing, corrected the workflow path.

### 2. Case-sensitive filename mismatch
- **Assumed:** `Main.py` and `main.py` would resolve the same way.
- **Observed:** same "file not found" error persisted after fixing the folder path.
- **Identified by:** re-cloning and `find`-listing the repo showed the committed file was `Main.py` (capital M) while the workflow referenced lowercase `main.py`. Linux runners are case-sensitive; local dev on a case-insensitive filesystem (macOS/Windows) would have hidden this.
- **Fixed by:** matched the workflow's `python` invocation to the actual on-disk capitalization.

### 3. GitHub Actions empty-string secrets
- **Assumed:** `os.environ.get(key, default)` falls back to `default` whenever a secret isn't configured.
- **Observed:** `ValueError: could not convert string to float: ''` on `STOCK_P_PORTFOLIO_VALUE` even with a default coded.
- **Identified by:** reasoning through the exact traceback — the key was clearly *present* in the environment (or `.get()` would have used the default), just empty. Confirmed: GitHub Actions sets a referenced-but-unset secret to `""`, not "undefined."
- **Fixed by:** short-term, an `env_or_default()` helper treating `""` as missing. Permanently: moved every one of these values out of Secrets entirely into `config/settings.py` (Incident 3 is the direct reason the config/secret split exists at all).

### 4. Empty ticker list, no diagnostic
- **Assumed:** if `STOCK_P_TICKERS` was set to something,`.split(",")` would produce a sane list or safely fall back to default.
- **Observed:** `Stock Debate — 2026-08-09 (0/0 tickers)` — an email with only the header, no per-ticker content, exit code 1.
- **Identified by:** traced the `(0/0 tickers)` subject format back to `len(TICKERS) == 0` — the raw secret parsed to zero non-empty entries (likely a stray comma/whitespace), and the first fix crashed before any email could explain why.
- **Fixed by:** moved the ticker list into `config/settings.py` as a plain Python list — the entire class of "secret parses to something unexpected" bug is now structurally impossible, since there's no string-splitting step left to fail.

### 5. Gemini 404 on `gemini-2.5-flash`
- **Assumed:** a single hardcoded model name would keep working.
- **Observed:** `404 Client Error: Not Found` on every Critic call, later followed by `429` on retries once volume increased.
- **Identified by:** web research surfaced active community reports of this exact model alias 404ing around the same timeframe — a live deprecation/rotation, not a code bug.
- **Fixed by:** `CriticConfig.model_candidates` — a fallback list tried in order, with whichever one responds first cached for the rest of the run so later calls don't re-probe dead aliases.

### 6. 429s from both providers — too fast, no throttling
- **Assumed:** a flat 3-second delay between calls would be safely under both providers' free-tier limits.
- **Observed:** repeated `429 Too Many Requests` from both Groq and Gemini; one run took 18 minutes, with the 4th ticker alone spending 10+ minutes in exhausted retries.
- **Identified by:** researched each provider's actual published free-tier numbers instead of guessing: Groq ≈30 RPM (but tighter TPM), Gemini ≈10 RPM. A flat 3s delay (20 calls/min) was already over Gemini's real cap.
- **Fixed by:** split into provider-specific delays grounded in the real numbers — `EXECUTOR.request_delay_seconds = 4`, `CRITIC.request_delay_seconds = 7` — plus retry-with-backoff (`RETRY.max_retries`, `RETRY.base_backoff_seconds`) honoring a `Retry-After` header when the provider sends one.

### 7. Hidden reasoning tokens truncating both agents (the big one)
- **Assumed:** a `max_tokens`/`maxOutputTokens` budget of 350-450 was plenty for a 5-7 sentence answer, and any cut-off would show up as an obvious error.
- **Observed:** *successful* (HTTP 200) responses that were garbled or cut mid-sentence — e.g. Critic replies like `"The Executor's argument overstates CDSL's"` (nothing after), Executor replies like `"We recommend a"` (nothing after). Not flagged as errors anywhere, and — worse — folded into the accumulating transcript, degrading every later round for that ticker.
- **Identified by:** researched both models specifically. Confirmed: (a) Gemini 2.5 Flash defaults to a "thinking" mode that spends the *same* output-token budget on hidden reasoning before the visible answer; (b) `openai/gpt-oss-120b` on Groq is a reasoning model with the identical behavior, corroborated by Groq's own community forum reports of "responses only contain reasoning tokens, no response."
- **Fixed by:** `CriticConfig.thinking_budget = 0` (disables Gemini's hidden reasoning), `ExecutorConfig.reasoning_effort = "low"` (minimizes Groq's), both token budgets raised for headroom, and — separately — actual truncation detection (`finish_reason == "length"` / `finishReason == "MAX_TOKENS"` or suspiciously short output) that flags a bad response instead of silently trusting it into the transcript.

### 8. Position could contradict the recommendation
- **Assumed:** if the BA's JSON says `HOLD`, its own `proposed_position_pct` would sensibly be 0.
- **Observed:** not yet broken in practice, but unguarded — nothing in code stopped a `HOLD` recommendation from carrying a nonzero position value into the log/email.
- **Identified by:** code review while adding the position-room clamp — noticed the clamp only handled *over-cap* positions, not *recommendation-inconsistent* ones.
- **Fixed by:** code now forces position to 0 for any non-`BUY` recommendation, regardless of what number the BA returned — same "enforce in code, don't just prompt for it" principle as the position-room cap.

### 9. Logging granularity too coarse to tell "slow" from "stuck"
- **Assumed:** one `print` per completed round was enough visibility.
- **Observed:** a 6-minute run with no new log output for stretches, indistinguishable from a hang.
- **Identified by:** direct question — "is this actually stuck?" — with no way to answer from the logs available at the time.
- **Fixed by:** logging before every individual model call (not just after a full round), plus elapsed-time tracking per round/ticker/run.

---

## What's verified vs. not

Verified without live API keys (all in this project's test history):
indicator math (RSI/MACD) against synthetic price series, both known
yfinance news-schema shapes, short-history edge cases, log
save/load/verify roundtrips, BA JSON parsing (clean, markdown-fenced,
and malformed), the position-room clamp, the position-forced-to-zero
rule, Gemini 404→fallback→cache behavior, 429 retry-then-succeed and
retry-exhaustion, and reasoning-token-budget routing per model.

Not verifiable without live keys / open internet (blocked in the
sandbox this was built in): actual Groq/Gemini/Yahoo HTTP response
content quality, actual git push permissions in Actions, actual Resend
delivery. Judge those from real run output, same as the incident log
above was built from real run output.
