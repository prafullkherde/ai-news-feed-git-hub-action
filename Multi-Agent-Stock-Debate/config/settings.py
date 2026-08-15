"""
Multi-Agent Stock Debate — Configuration
============================================================
Every tunable value lives HERE, not in GitHub Secrets. Only 3 true
secrets remain in repo Settings -> Secrets: GROQ_API_KEY_FOR_AUTO_EMAIL,
RESEND_API_KEY, MY_EMAIL. GEMINI_API_KEY is no longer used — the
Critic moved onto Groq (see CriticConfig below) after Gemini's free
tier hit a full daily quota exhaustion in production. Everything else — model
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

    request_delay_seconds: float = 10.0
    # WHY 10, not the original 4: Groq's free-tier rate limit is per
    # ORGANIZATION, not per-model — Executor, Critic, and BA Reviewer
    # now all draw from the SAME 30 RPM / ~6,000-8,000 TPM pool once
    # Critic moved off Gemini onto Groq too (see CriticConfig below).
    # OBSERVED: at the old 4.0s delay with Executor ALONE, remaining
    # tokens dropped to double/triple digits by the 3rd-4th ticker,
    # triggering repeated 429s. Doubling total Groq call volume (Critic
    # now included) at the same delay would make that worse, not
    # better. 10s keeps combined throughput under the refill rate.


EXECUTOR = ExecutorConfig()


# ============================================================
# CRITIC — counters every Executor round, different Groq model on purpose
# ============================================================
@dataclass(frozen=True)
class CriticConfig:
    model: str = "qwen/qwen3.6-27b"
    # WHY this model, not Gemini anymore: Gemini's free tier hit a full
    # DAILY quota exhaustion in production — every single Critic call
    # failed for an entire run, silently, while the pipeline still
    # reported "success". Qwen3.6-27b is one of only two models Groq's
    # own deprecation notices point every retiring model toward
    # (the other being Executor's gpt-oss-120b) — architecturally
    # distinct from Executor's model, which is what actually gives the
    # debate a genuine second opinion, not the vendor it's hosted on.

    max_tokens: int = 900
    # Raised from 600: qwen3.6-27b was observed writing its reasoning
    # out as VISIBLE text ("Here's a thinking process: 1. Analyze...")
    # rather than using a hidden channel like gpt-oss models do — every
    # single Critic response in production was finish_reason=length,
    # cut off mid-thought before ever reaching the actual critique. The
    # real fix is the explicit "do not narrate your thinking" instruction
    # now in Main.py's critic_turn() system prompt; this higher ceiling
    # is just a safety margin on top of that.

    request_delay_seconds: float = 10.0
    # Same combined-Groq-quota reasoning as EXECUTOR above — see that
    # comment for the full explanation. Both delays must move together;
    # changing one without the other reintroduces the exhaustion risk.


CRITIC = CriticConfig()


# ============================================================
# BA REVIEWER — reads the full transcript, corrects it, issues the final call
# ============================================================
@dataclass(frozen=True)
class BAReviewerConfig:
    model: str = "openai/gpt-oss-20b"
    # WHY this, not qwen3.6-27b (Critic's model): Groq's rate limits are
    # tracked per-MODEL, not pooled across an org. Putting BA Reviewer on
    # the SAME model as Critic meant they competed for one 8000 TPM
    # bucket within a single ticker's run — CONFIRMED in production: that
    # bucket drained to double digits by round 4, triggering repeated
    # 429s and a run that got cancelled mid-way through ticker 2.
    # gpt-oss-20b is Groq's other currently-live recommended model
    # (distinct from both Executor's gpt-oss-120b and Critic's
    # qwen3.6-27b), giving BA Reviewer its own separate quota bucket.

    max_tokens: int = 1200
    # Raised from 700: gpt-oss-20b is a reasoning model, same family as
    # Executor's gpt-oss-120b, and PARSE_ERROR on every ticker in
    # production strongly suggests it was hitting the same hidden-
    # reasoning-eats-the-budget problem Executor had before
    # reasoning_effort="low" was applied to it. Needs real headroom for
    # both that overhead AND a full structured JSON response.

    request_delay_seconds: float = 10.0

    reasoning_effort: str = "low"
    # WHY: same fix as ExecutorConfig — gpt-oss-20b is a reasoning model
    # that spends part of its output budget on hidden chain-of-thought
    # unless told to minimize it. This was NEVER being applied before —
    # the code only checked `if model == cfg.EXECUTOR.model`, which
    # never matched BA Reviewer's model name, so this suppression
    # silently never fired for BA Reviewer at all.
    # Same shared-Groq-quota reasoning as EXECUTOR/CRITIC above.


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
