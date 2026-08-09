# Multi-Agent Stock Debate — Executor / Critic / Senior BA Reviewer

3 roles, 2 model providers, running over a **list of tickers**, with a
**persistent per-ticker log** that verifies yesterday's prediction against
real closing prices before making today's — so right and wrong calls both
build up an actual accuracy record, not just a fresh guess every day.

| Role | Model | Job |
|---|---|---|
| Executor | Groq `openai/gpt-oss-120b` | Argues each of 7 rounds (Fundamental → Technical → Sentiment → Bull → Bear → Trade → Risk) |
| Critic | Gemini 2.5 Flash | Counters every round with a different data point — different vendor on purpose |
| **Senior BA Reviewer** | Groq `llama-3.3-70b-versatile` (3rd distinct model) | Reads the whole transcript + yesterday's verified outcome, corrects anything wrong, issues the final BUY/SELL/HOLD + next-day/next-week price target |

**Honest limitation, stated up front:** next-day/next-week prices are
LLM-generated estimates, not a statistical model — there's no inherent
reason they should beat a coin flip. The verification loop exists
specifically to make that measurable with real numbers instead of assumed.
Don't trade on this before the log has weeks of verified history.

## Secrets — all new ones prefixed `STOCK_P_`
| Secret | New or reused | Default if unset |
|---|---|---|
| `GROQ_API_KEY_FOR_AUTO_EMAIL` | Reused | — required |
| `RESEND_API_KEY` | Reused | — required |
| `MY_EMAIL` | Reused | — required |
| `GEMINI_API_KEY` | **New** — free, aistudio.google.com/apikey | — required |
| `STOCK_P_TICKERS` | New | `CDSL.NS,TRENT.NS,SUZLON.NS,MON100.NS` |
| `STOCK_P_PORTFOLIO_VALUE` | New | `100000` |
| `STOCK_P_MAX_POSITION_PCT` | New | `5` |
| `STOCK_P_CURRENT_EXPOSURE_JSON` | New | `{}` (0% exposure assumed for any ticker not listed) |

`MON100.NS` is the Motilal Oswal NASDAQ-100 ETF, not a company — it has no
earnings/margins, so the Fundamental round will flag it as low-confidence
automatically (this is existing, tested behavior, not a new special case).

## How the 3 portfolio vars get consumed — case by case
| Case | Exposure (this ticker) | Room = MAX − exposure | What happens |
|---|---|---|---|
| Fresh BUY, never held | 0% | full `MAX_POSITION_PCT` | BA proposes a %; **code clamps** to ≤ room, regardless of what the BA said |
| Already at the cap | = `MAX_POSITION_PCT` | 0% | Any BUY is force-clamped to 0% — logged as "auto-capped by risk rule," even if the BA argued for more |
| Partial room | between 0 and max | remainder | BA's proposed size is clamped to the remainder, never above it |
| SELL / trim | > 0% | n/a | Recommendation is framed as reducing toward 0%, not a fresh position calc |

The clamp happens **in `run_ticker()`, in code, after parsing the BA's
JSON** — this is deliberate: the BA is asked to respect the constraint in
its prompt, but the prompt is not trusted. The code enforces it and
records when it had to override the model. Verified in testing: BA proposed
9% with only 3% of room available → code capped to 3% and logged
`"Position auto-capped from 9.0% to 3% by risk rule"`.

## How the daily read-verify-write loop works
1. Load `logs/<ticker>.json` (committed by the previous run).
2. For every past entry not yet verified, check real closes since that
   date: next trading day → `verified_next_day`, 5 trading days later →
   `verified_next_week`. Each gets `direction_correct` (bool) and
   `error_pct` (magnitude miss).
3. Build a plain-text track record ("Next-day accuracy: 71% over 7 calls")
   and feed it to the BA reviewer, so a recent losing streak makes it more
   conservative — this is the actual mechanism, not just a log for humans
   to read later.
4. Run the 7-round Executor/Critic debate, then the BA review.
5. Append today's (still-unverified) prediction, clamp the position size,
   write the file back.
6. The **workflow** (not the Python) commits `logs/` back to the repo —
   Action runners have no disk between runs, so without this the whole
   loop resets to zero every day.

## Data completeness — unchanged findings, now per-ticker
| Round | Source | Confidence |
|---|---|---|
| Fundamental | yfinance `.info` | Good for stocks, expected-empty for `MON100.NS` (ETF) |
| Technical | Price history, SMA20/50, RSI-14, MACD | Good |
| Sentiment | yfinance `.news` headlines only | Weak — no sentiment score, no Reddit/StockTwits; flagged in-prompt when empty |
| Risk & Portfolio | Now grounded in real `STOCK_P_*` values instead of invented constraints | Fixed (was the earlier gap) |

## Setup
```bash
cp stock-agent-debate/stock-debate.yml .github/workflows/
git add . && git commit -m "add multi-stock debate agent" && git push
```
Add `GEMINI_API_KEY` and the four `STOCK_P_*` secrets in repo settings.
Everything else is reused from your existing `ai-news-feed-git-hub-action`.

## Verified before shipping (no live API keys required for these)
- `py_compile` clean
- Log path sanitization, save/load roundtrip, entry trimming
- Verification math against a synthetic price series — correctly flagged
  a case where direction was right but magnitude was off by 19%
- BA JSON parsing: clean JSON, markdown-fenced JSON, and malformed text
  all handled without crashing (malformed falls back to a logged
  `PARSE_ERROR` entry instead of killing the run)
- **Position-size clamp**: confirmed the code overrides an over-limit LLM
  proposal (9% requested vs 3% room) and logs the override
- Email builder handles a mix of successful tickers and per-ticker
  failures in the same run without crashing
- Not verified here (needs live keys / open internet, blocked in this
  sandbox specifically): actual Groq/Gemini/Yahoo HTTP responses, actual
  git push permissions in Actions, actual Resend delivery. Check Action
  logs on first real run.
