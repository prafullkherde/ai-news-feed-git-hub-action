"""
Multi-Agent Stock Debate — Configuration
============================================================
Every tunable value lives HERE, not in GitHub Secrets. Only 4 true
secrets remain in repo Settings -> Secrets: GROQ_API_KEY_FOR_AUTO_EMAIL,
GEMINI_API_KEY, RESEND_API_KEY, MY_EMAIL. Everything else — model
choice, token budgets, retry behavior, portfolio size, ticker list — is
plain, readable, version-controlled Python you can edit directly here.

WHY this split exists (observed, not assumed):
Earlier versions put non-secret values like PORTFOLIO_VALUE and
MAX_RETRIES into GitHub Secrets as STOCK_P_*. That caused a real,
reproduced bug: GitHub Actions sets an env var to an EMPTY STRING when a
referenced secret doesn't exist, rather than leaving it unset — so
`os.environ.get(key, default)` never fell back to the default, because
the key WAS present. Moving non-secret config here removes that entire
failure class (a plain Python default always works), and makes every
knob visible in one file instead of hidden across a Secrets UI where
you can't even see the current value once saved. See README.md for the
full incident writeup.
"""
from dataclasses import dataclass, field


# ============================================================
# EXECUTOR — argues each of the 7 debate rounds, Groq-hosted
# ============================================================
@dataclass(frozen=True)
class ExecutorConfig:
    model: str = "openai/gpt-oss-120b"
    # Same model your existing daily-digest job already uses on Groq.

    reasoning_effort: str = "low"
    # WHY: gpt-oss-120b is a reasoning model — by default it spends part
    # of its output-token budget on hidden chain-of-thought before
    # writing the visible answer. OBSERVED: real production replies
    # truncated after a few words ("We recommend a", then nothing).
    # "low" minimizes that hidden spend so more of max_tokens goes to
    # the actual answer. Only applied to this model — the BA reviewer's
    # model below doesn't support/need this parameter.

    max_tokens: int = 900
    # WHY 900, not the original 450: even with reasoning_effort="low",
    # some budget still goes to hidden reasoning. 900 leaves comfortable
    # room for a full 5-7 sentence answer after that overhead.

    request_delay_seconds: float = 4.0
    # WHY: Groq's free tier is 30 requests/minute, so 2s is the
    # mathematical floor. 4s adds headroom because TPM (6,000-8,000
    # tokens/minute on this model), not RPM, is usually the real
    # constraint once each round's prompt grows with the accumulating
    # transcript.


EXECUTOR = ExecutorConfig()


# ============================================================
# CRITIC — counters every Executor round, different vendor on purpose
# ============================================================
@dataclass(frozen=True)
class CriticConfig:
    model_candidates: tuple = ("gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash")
    # WHY a list, not one hardcoded model: gemini-2.5-flash returned a
    # live 404 in production — Gemini model aliases retire or shift
    # without much notice. Candidates are tried in order at runtime;
    # whichever responds first is cached and reused for the rest of the
    # run so later calls don't waste time re-probing dead ones.

    max_output_tokens: int = 600
    # Raised from the original 350 — see thinking_budget below for why
    # the original number was too tight even before this raise.

    thinking_budget: int = 0
    # WHY: Gemini 2.5 Flash defaults to "thinking" mode, which spends
    # the SAME output-token budget on hidden reasoning before writing
    # the visible critique. OBSERVED: real critic replies cut after
    # 5-10 words ("The Executor's argument overstates CDSL's", then
    # nothing). 0 disables thinking mode entirely — a short critique
    # doesn't need it.

    request_delay_seconds: float = 7.0
    # WHY: Gemini's free tier is roughly 10 requests/minute, so 6s is
    # the mathematical floor. 7s adds a small safety margin. This was
    # the direct, confirmed cause of an 18-minute run with the 4th
    # ticker alone spending 10+ minutes in repeated exhausted retries —
    # cumulative call volume across the earlier tickers had already
    # eaten most of the per-minute quota by the time it got there.


CRITIC = CriticConfig()


# ============================================================
# BA REVIEWER — reads the full transcript, corrects it, issues the final call
# ============================================================
@dataclass(frozen=True)
class BAReviewerConfig:
    model: str = "llama-3.3-70b-versatile"
    # WHY a third, different model rather than reusing the Executor's:
    # (1) it is NOT a reasoning model, so it doesn't share gpt-oss-120b's
    # hidden-token truncation risk, and (2) using a different model than
    # the one that argued the Executor's case makes this an independent
    # check rather than the same weights reviewing their own work.

    max_tokens: int = 700
    # Needs headroom for a full structured JSON response covering all
    # 6 "why" fields plus the numeric predictions — 700 is comfortable.


BA_REVIEWER = BAReviewerConfig()


# ============================================================
# RETRY / RATE-LIMIT HANDLING — shared by every provider call
# ============================================================
@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 4
    # WHY 4: enough to ride out a short burst of 429s without retrying
    # forever. Each attempt backs off longer than the last (see below).

    base_backoff_seconds: float = 15.0
    # WHY: on a 429 with no Retry-After header from the provider, wait
    # base * (attempt_number + 1) — so 15s, 30s, 45s, 60s across 4
    # attempts. Free-tier rate windows typically refill within 60s, so
    # this recovers by attempt 3-4 in practice (observed in production).

    min_valid_response_chars: int = 40
    # WHY: a response shorter than this AND flagged as truncated by the
    # provider (finish_reason="length" / finishReason="MAX_TOKENS") is
    # almost always a cut-off mid-thought, not a genuinely short but
    # complete answer. Used to flag truncation explicitly instead of
    # silently folding a fragment into the accumulating transcript,
    # which otherwise poisons every later round's prompt for that ticker.


RETRY = RetryConfig()


# ============================================================
# PORTFOLIO / RISK — position sizing constraints
# ============================================================
@dataclass(frozen=True)
class PortfolioConfig:
    value: float = 100_000
    # Total capital the position-sizing math is based on. Not a real
    # brokerage balance — just the denominator for "% of portfolio".

    max_position_pct: float = 5.0
    # Hard ceiling per ticker. Enforced IN CODE after the BA responds
    # (see run_ticker in Main.py) — never trusted from the LLM's own
    # JSON output, on the same "review it, then fix it in code, don't
    # just hope the model obeyed the prompt" principle used throughout.

    current_exposure_pct: dict = field(default_factory=lambda: {
        # ticker -> % of portfolio already held in that name. Anything
        # not listed here defaults to 0%. Edit this dict by hand as your
        # real positions change, e.g.:
        # "CDSL.NS": 2.5,
    })


PORTFOLIO = PortfolioConfig()


# ============================================================
# TICKERS — what the debate runs over each day
# ============================================================
TICKERS = ["CDSL.NS", "TRENT.NS", "SUZLON.NS", "MON100.NS"]
# WHY these four: CDSL and TRENT are NSE-listed equities, SUZLON is a
# higher-volatility name for contrast, MON100 is the Motilal Oswal
# NASDAQ-100 ETF — not a company, so its Fundamental round correctly
# shows low-confidence (ETFs don't have the P/E-relevant earnings data a
# stock has; this is expected behavior, not a bug).
#
# Add or remove tickers by editing this list directly — this being a
# plain list (not a parsed comma-separated secret string) is also why
# the earlier "STOCK_P_TICKERS resolves to an empty list" failure mode
# can no longer happen: there's no string-splitting step left to fail.


# ============================================================
# LOGGING / PERSISTENCE
# ============================================================
MAX_LOG_ENTRIES = 90
# WHY 90: keeps each ticker's logs/<ticker>.json from growing unbounded
# in the repo over time. ~90 daily entries is roughly a trading quarter.
# Older entries still contributed to the accuracy stats before being
# trimmed — they're just not kept in the file forever.
