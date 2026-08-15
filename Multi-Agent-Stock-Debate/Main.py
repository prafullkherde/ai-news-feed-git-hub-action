"""
Multi-Agent Stock Debate — Executor / Critic / Senior BA Reviewer
====================================================================
3 roles, 2 model providers (config in ./config/settings.py):
  EXECUTOR  -> Groq   (argues each of 7 rounds)
  CRITIC    -> Groq (counters each round — different model than Executor on purpose)
  BA REVIEW -> Groq, but a DIFFERENT model than the Executor (reads the
               full transcript + yesterday's logged outcome, corrects
               anything wrong, and produces the final structured call:
               BUY/SELL/HOLD, next-day + next-week price target,
               confidence, and a code-clamped position size)

Runs over the ticker list in config/settings.py. Each ticker has its own
append-only JSON log under logs/<ticker>.json, committed back to the repo
by the GitHub Action (see stock-debate.yml) — this is the persistence
layer, since Action runners have no disk between runs.

Every run, BEFORE making a new prediction, it:
  1. loads yesterday's (and older unverified) log entries for that ticker
  2. checks real closing prices since then, marks each old prediction's
     next-day / next-week call as correct/wrong with an error %
  3. feeds that track record into the BA agent's prompt, so today's
     confidence is grounded in "have I been right lately", not vibes
  4. appends today's new prediction (unverified until tomorrow/next week)

IMPORTANT — price targets are LLM-generated estimates, not a statistical
model. The entire point of the verification loop is to make it visible,
with real numbers, whether they're worth anything over time.

See README.md for the full "assumed -> observed -> diagnosed -> fixed"
incident log covering every bug found in this project so far.
"""
import os
import sys
import json
import time
import datetime
import requests
import pandas as pd
import yfinance as yf

from config import settings as cfg

REQUIRED_SECRETS = ["GROQ_API_KEY_FOR_AUTO_EMAIL", "RESEND_API_KEY", "MY_EMAIL"]
# These 4 are the ONLY values that belong in GitHub Secrets. Everything
# else lives in config/settings.py — see that file's module docstring
# for why that split matters.

ROLES = [
    ("Fundamental", "Evaluate {t}'s financial health and business performance using the fundamental data below."),
    ("Technical", "Evaluate {t}'s price action and technical indicators (SMA, RSI, MACD) using the data below."),
    ("Sentiment", "Interpret market sentiment for {t} using the recent news headlines below. If no headlines are available, say so explicitly instead of guessing."),
    ("Bull Case", "Build the strongest bull (buy) case for {t} using all data and discussion so far."),
    ("Bear Case", "Build the strongest bear (sell/avoid) case for {t} using all data and discussion so far."),
    ("Trade Proposal", "Synthesize the research into one concrete trade proposal (direction, position size, stop level) for {t}."),
    ("Risk & Portfolio", "Evaluate the proposed trade for {t} against the portfolio constraints below. Give a preliminary APPROVE or REJECT — the final call is made by the BA reviewer afterward."),
]

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


# ============================================================
# START: PERSISTENCE — read/write/verify the per-ticker JSON logs
# ============================================================

def log_path(ticker: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in ticker)
    return os.path.join(LOG_DIR, f"{safe}.json")


def load_log(ticker: str):
    path = log_path(ticker)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_log(ticker: str, entries: list):
    os.makedirs(LOG_DIR, exist_ok=True)
    entries = entries[-cfg.MAX_LOG_ENTRIES:]
    with open(log_path(ticker), "w") as f:
        json.dump(entries, f, indent=2, default=str)


def verify_past_predictions(entries: list, price_hist: pd.Series):
    """price_hist: Close series indexed by date, ascending, from a wide
    enough history window to cover verification lookback. Mutates entries
    in place, filling verified_next_day / verified_next_week where the
    real trading days have since occurred and weren't already checked."""
    checked = 0
    for entry in entries:
        try:
            pred_date = pd.Timestamp(entry["date"]).tz_localize(price_hist.index.tz) if price_hist.index.tz else pd.Timestamp(entry["date"])
        except Exception:
            continue
        future = price_hist[price_hist.index > pred_date]
        base_price = entry.get("price_at_prediction")
        if base_price is None:
            continue

        if entry.get("verified_next_day") is None and len(future) >= 1:
            actual = float(future.iloc[0])
            predicted = entry.get("predicted_next_day_price")
            if predicted is not None:
                entry["verified_next_day"] = {
                    "actual_price": round(actual, 2),
                    "direction_correct": (actual >= base_price) == (predicted >= base_price),
                    "error_pct": round((actual - predicted) / predicted * 100, 2),
                }
                checked += 1

        if entry.get("verified_next_week") is None and len(future) >= 5:
            actual_w = float(future.iloc[4])
            predicted_w = entry.get("predicted_next_week_price")
            if predicted_w is not None:
                entry["verified_next_week"] = {
                    "actual_price": round(actual_w, 2),
                    "direction_correct": (actual_w >= base_price) == (predicted_w >= base_price),
                    "error_pct": round((actual_w - predicted_w) / predicted_w * 100, 2),
                }
                checked += 1

    return entries, checked


def track_record_summary(entries: list) -> str:
    day_calls = [e["verified_next_day"] for e in entries if e.get("verified_next_day")]
    week_calls = [e["verified_next_week"] for e in entries if e.get("verified_next_week")]
    if not day_calls and not week_calls:
        return "No verified predictions yet — this is the first run or nothing has matured."
    parts = []
    if day_calls:
        acc = sum(1 for d in day_calls if d["direction_correct"]) / len(day_calls) * 100
        parts.append(f"Next-day direction accuracy: {acc:.0f}% over {len(day_calls)} verified calls")
    if week_calls:
        acc = sum(1 for w in week_calls if w["direction_correct"]) / len(week_calls) * 100
        parts.append(f"Next-week direction accuracy: {acc:.0f}% over {len(week_calls)} verified calls")
    return " | ".join(parts)

# ============================================================
# END: PERSISTENCE
# ============================================================


# ============================================================
# START: MARKET DATA — yfinance fetch + technical indicator math
# ============================================================

def compute_rsi(close: pd.Series, period: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def compute_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def extract_headlines(news_items):
    """yfinance's news schema has changed shape more than once (title can
    sit at top level or nested under 'content'). Handle both, never crash."""
    headlines = []
    for n in news_items or []:
        title = n.get("title")
        if not title and isinstance(n.get("content"), dict):
            title = n["content"].get("title")
        if title:
            headlines.append(title)
    return headlines


def get_market_data(ticker: str):
    tk = yf.Ticker(ticker)
    try:
        hist = tk.history(period="6mo")  # wide enough to cover indicators + verification lookback
    except Exception as e:
        raise RuntimeError(f"Price history fetch failed for '{ticker}': {e}")
    if hist is None or hist.empty:
        raise RuntimeError(f"No price history returned for '{ticker}' — check the ticker symbol.")

    close = hist["Close"]
    rsi_series = compute_rsi(close)
    macd_line, signal_line = compute_macd(close)

    technicals = {
        "last_close": round(float(close.iloc[-1]), 2),
        "sma_20": round(float(close.rolling(20).mean().iloc[-1]), 2) if len(close) >= 20 else None,
        "sma_50": round(float(close.rolling(50).mean().iloc[-1]), 2) if len(close) >= 50 else None,
        "rsi_14": round(float(rsi_series.iloc[-1]), 2) if len(close) >= 14 and pd.notna(rsi_series.iloc[-1]) else None,
        "macd": round(float(macd_line.iloc[-1]), 3) if len(close) >= 26 else None,
        "macd_signal": round(float(signal_line.iloc[-1]), 3) if len(close) >= 26 else None,
        "3mo_return_pct": round((float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100, 2),
        "volatility_pct": round(float(close.pct_change().std()) * 100, 2),
    }

    try:
        info = tk.info or {}
    except Exception:
        info = {}
    fundamentals = {
        "marketCap": info.get("marketCap"),
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "profitMargins": info.get("profitMargins"),
        "revenueGrowth": info.get("revenueGrowth"),
        "debtToEquity": info.get("debtToEquity"),
        "returnOnEquity": info.get("returnOnEquity"),
    }
    if all(v is None for v in fundamentals.values()):
        fundamentals["_warning"] = "fundamentals unavailable (common for ETFs like MON100, or a scraper block) — treat Fundamental round as low-confidence"

    try:
        news = tk.news
    except Exception:
        news = []
    headlines = extract_headlines(news)
    if not headlines:
        headlines = ["[no headlines returned by data source]"]

    return fundamentals, technicals, headlines, close

# ============================================================
# END: MARKET DATA
# ============================================================


# ============================================================
# START: COMPACT FORMATTING — same information, fewer tokens
# ============================================================
# Python's default f-string embedding of a dict/list (e.g. f"{fundamentals}")
# produces {'marketCap': 280979603456, 'trailingPE': 59.28, ...} -- full
# key names, quotes, braces, commas. That punctuation overhead gets paid
# EVERY round (7x per ticker), not once. These helpers produce the same
# information as plain "key: value" pairs instead -- no functional change,
# same numbers, same precision, just less punctuation to pay tokens for.

def _format_fundamentals(fundamentals: dict) -> str:
    parts = [f"{k}: {v}" for k, v in fundamentals.items() if k != "_warning"]
    line = "Fundamentals: " + ", ".join(parts)
    if "_warning" in fundamentals:
        line += f" ({fundamentals['_warning']})"
    return line


def _format_technicals(technicals: dict) -> str:
    parts = [f"{k}: {v}" for k, v in technicals.items()]
    return "Technicals: " + ", ".join(parts)


def _format_headlines(headlines: list) -> str:
    return "Recent headlines: " + "; ".join(headlines)


# ============================================================
# START: MODEL CALLS — Groq (Executor + Critic + BA), one shared quota
# ============================================================
# Shared retry/backoff behavior: config/settings.py -> RETRY
# Provider-specific behavior (reasoning budgets, model fallback,
# per-provider pacing): config/settings.py -> EXECUTOR / CRITIC / BA_REVIEWER

def _sleep_backoff(resp, attempt: int):
    retry_after = resp.headers.get("Retry-After") if resp is not None else None
    wait = float(retry_after) if retry_after else cfg.RETRY.base_backoff_seconds * (attempt + 1)
    # Log the actual response body (truncated) so a 429 is diagnosable —
    # without this we can't tell a per-minute limit (worth waiting out)
    # from a daily quota exhaustion (waiting won't help at all today).
    body_snippet = (resp.text[:300] if resp is not None and resp.text else "")
    print(f"    429 rate limited — waiting {wait:.0f}s (attempt {attempt + 1}/{cfg.RETRY.max_retries}) — body: {body_snippet}", file=sys.stderr)
    time.sleep(wait)


def _is_daily_quota_exhausted(resp) -> bool:
    """Heuristic check on a 429 response body for a per-DAY quota signal
    (as opposed to per-minute). If the daily cap is hit, retrying within
    this run cannot succeed — the quota only resets on the provider's
    daily window, not by waiting a few seconds. Matches common phrasing
    from both Groq and Gemini error bodies; if the check can't tell,
    it defaults to False (retry normally) rather than guessing wrong
    and abandoning a call that could have succeeded."""
    if resp is None or not resp.text:
        return False
    body_lower = resp.text.lower()
    return any(marker in body_lower for marker in ("per day", "perday", "daily", "requests per day", "rpd"))


def _log_rate_limit_headers(resp, provider: str):
    """Print any header whose name suggests remaining quota (rate-limit,
    quota, retry-after). Groq reliably sends these (x-ratelimit-remaining-
    requests, x-ratelimit-remaining-tokens, x-ratelimit-reset-requests,
    etc.) on every response, success or not. Gemini's REST API is less
    consistent about it, so this may print nothing for Gemini — that
    itself is useful information (means we're flying blind on Gemini's
    real-time quota and can only infer it from 429 bodies)."""
    if resp is None:
        return
    relevant = {k: v for k, v in resp.headers.items() if any(s in k.lower() for s in ("ratelimit", "rate-limit", "quota", "retry-after"))}
    if relevant:
        print(f"    [{provider} quota headers] {relevant}", file=sys.stderr)


def call_groq(system_prompt: str, user_prompt: str, model: str, max_tokens: int, delay_seconds: float, reasoning_effort: str = None) -> str:
    """Calls Groq's chat completions endpoint. Used for the Executor,
    Critic, and BA Reviewer, with different `model`/`max_tokens`/
    `delay_seconds`/`reasoning_effort` per config. reasoning_effort is now
    an explicit parameter rather than being inferred by comparing `model`
    to cfg.EXECUTOR.model — that was a real bug: BA Reviewer moved onto
    gpt-oss-20b (also a reasoning model, same family as Executor's
    gpt-oss-120b) but never got reasoning suppression applied, since the
    comparison only ever matched Executor's own model name."""
    last_error = None
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        # Any gpt-oss family model (Executor's 120b, BA Reviewer's 20b)
        # spends hidden output-token budget on chain-of-thought unless
        # told otherwise — see config/settings.py for the per-role value.
        body["reasoning_effort"] = reasoning_effort

    for attempt in range(cfg.RETRY.max_retries):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY_FOR_AUTO_EMAIL']}"},
                json=body,
                timeout=60,
            )
            _log_rate_limit_headers(resp, f"GROQ:{model}")
            if resp.status_code == 429:
                if _is_daily_quota_exhausted(resp):
                    last_error = f"429 daily quota exhausted, not retrying — body: {resp.text[:300]}"
                    print(f"    429 looks like a DAILY quota, not per-minute — skipping remaining retries. body: {resp.text[:200]}", file=sys.stderr)
                    break
                _sleep_backoff(resp, attempt)
                last_error = "429 Too Many Requests (all retries exhausted)"
                continue
            resp.raise_for_status()
            time.sleep(delay_seconds)
            choice = resp.json()["choices"][0]
            content = choice["message"]["content"].strip()
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length" or len(content) < cfg.RETRY.min_valid_response_chars:
                return f"[GROQ TRUNCATED ({model}, finish_reason={finish_reason}): {content!r}]"
            return content
        except Exception as e:
            last_error = str(e)
            break
    time.sleep(delay_seconds)
    return f"[GROQ ERROR ({model}): {last_error}]"

# ============================================================
# END: MODEL CALLS
# ============================================================


# ============================================================
# START: DEBATE ROUNDS — Executor argues, Critic counters, x7
# ============================================================

def executor_turn(template, ticker, data_ctx, transcript):
    system_prompt = (
        "You are the EXECUTOR agent in a stock research pipeline. "
        "Argue a specific analytical position using ONLY the data provided. "
        "Cite specific numbers from the data in every claim. Never state an "
        "opinion without a number behind it. Be concise (5-7 sentences)."
    )
    user_prompt = f"{template.format(t=ticker)}\n\nDATA:\n{data_ctx}\n\nPrior discussion:\n{transcript}"
    return call_groq(system_prompt, user_prompt, cfg.EXECUTOR.model, cfg.EXECUTOR.max_tokens, cfg.EXECUTOR.request_delay_seconds, cfg.EXECUTOR.reasoning_effort)


def critic_turn(role_name, ticker, data_ctx, exec_claim, transcript):
    system_prompt = (
        "You are the CRITIC agent in a stock research pipeline. "
        "Find the weakest point in the Executor's argument and counter it "
        "using a specific number from the SAME data (or a different metric "
        "within it). You must disagree on at least one concrete point — do "
        "not just validate. Be concise (5-7 sentences). "
        "Respond with ONLY the final critique — do not narrate your "
        "thinking process, do not write 'here's my analysis' or numbered "
        "reasoning steps, do not restate the task. Go straight to the "
        "counter-argument, first word to last."
    )
    user_prompt = (
        f"Topic: {role_name} analysis for {ticker}\n\nDATA:\n{data_ctx}\n\n"
        f"Executor's claim:\n{exec_claim}\n\nPrior discussion:\n{transcript}\n\n"
        "Counter this with data-backed pushback. /no_think"
    )
    # WHY the literal "/no_think" suffix: the system-prompt instruction to
    # skip narration was CONFIRMED ignored in production — the model wrote
    # "no narrating thinking process" back at us as part of its own visible
    # chain-of-thought, then narrated for 800+ tokens before running out of
    # room anyway. Qwen3's chat template has a documented control token for
    # this exact case: /no_think suppresses reasoning mode at the template
    # level rather than relying on the model to voluntarily comply with a
    # plain-language instruction it can (and did) disregard.
    return call_groq(system_prompt, user_prompt, cfg.CRITIC.model, cfg.CRITIC.max_tokens, cfg.CRITIC.request_delay_seconds)


MAX_CONTEXT_ROUNDS = 2
# WHY: passing the FULL accumulating transcript to every round is what
# drove per-call token consumption from ~150 tokens (round 1) to 2000+
# (round 6-7), which is the real cause of hitting Groq's 200k/day TPD
# cap partway through a run — CONFIRMED in production (SUZLON's later
# rounds and all of MON100 failed with daily quota exhausted). Each
# round only needs recent context to avoid repeating the same point,
# not the entire history — trimming to the last 2 rounds cuts per-call
# token cost substantially without changing what the debate can argue.
# The FULL transcript is still built and passed to BA Reviewer once at
# the end, since that one call genuinely needs the complete picture and
# only happens once per ticker, not 7 times.


def run_debate(ticker: str, fund_str: str, tech_str: str, headlines_str: str, portfolio_ctx: str):
    full_ctx = f"{fund_str}\n{tech_str}\n{headlines_str}"
    rounds_text = []
    rounds = []
    for role_name, template in ROLES:
        round_start = time.time()
        if role_name == "Fundamental":
            round_ctx = fund_str
        elif role_name == "Technical":
            round_ctx = tech_str
        elif role_name == "Sentiment":
            round_ctx = headlines_str
        elif role_name == "Risk & Portfolio":
            round_ctx = f"{full_ctx}\nPortfolio constraints: {portfolio_ctx}"
        else:  # Bull Case, Bear Case, Trade Proposal — synthesis rounds need the full picture
            round_ctx = full_ctx
        recent_context = "".join(rounds_text[-MAX_CONTEXT_ROUNDS:])

        print(f"  [{ticker}] {role_name}: calling Executor (Groq)...", file=sys.stderr)
        exec_claim = executor_turn(template, ticker, round_ctx, recent_context)

        print(f"  [{ticker}] {role_name}: calling Critic (Groq)...", file=sys.stderr)
        critic_claim = critic_turn(role_name, ticker, round_ctx, exec_claim, recent_context)

        rounds_text.append(f"\n[{role_name} — EXECUTOR]: {exec_claim}\n[{role_name} — CRITIC]: {critic_claim}\n")
        rounds.append((role_name, exec_claim, critic_claim))
        print(f"  [{ticker}] OK {role_name} ({time.time() - round_start:.1f}s)", file=sys.stderr)
    return rounds, "".join(rounds_text)

# ============================================================
# END: DEBATE ROUNDS
# ============================================================


# ============================================================
# START: BA REVIEWER — reads the transcript, corrects it, issues the final call
# ============================================================

def ba_review(ticker, transcript, data_ctx, portfolio_ctx, yesterday_entry, track_record):
    print(f"  [{ticker}] calling Senior BA Reviewer (Groq)...", file=sys.stderr)
    yesterday_note = "No prior logged prediction for this ticker."
    if yesterday_entry:
        yesterday_note = (
            f"Yesterday's call: {yesterday_entry.get('recommendation')} "
            f"at price {yesterday_entry.get('price_at_prediction')}, "
            f"next-day target {yesterday_entry.get('predicted_next_day_price')}. "
            f"Verified outcome: {yesterday_entry.get('verified_next_day')}"
        )

    system_prompt = (
        "You are a SENIOR STOCK BROKER acting as Business Analyst reviewer. "
        "You receive a full Executor-vs-Critic debate transcript across 7 "
        "analysis rounds. Your job: find anything wrong or overstated in "
        "that transcript and correct it yourself — do not just repeat the "
        "Executor's or Critic's conclusion if the data doesn't support it. "
        "Factor in the track record of past predictions for this ticker: "
        "if recent calls were wrong, be more conservative. "
        "Respond with STRICT JSON ONLY, no markdown fences, no prose outside "
        "the JSON, matching exactly this schema:\n"
        '{"recommendation": "BUY|SELL|HOLD", '
        '"confidence": "Low|Medium|High", '
        '"predicted_next_day_price": <number>, '
        '"predicted_next_week_price": <number>, '
        '"proposed_position_pct": <number, % of portfolio, 0 if HOLD>, '
        '"why": {"Fundamental": "...", "Technical": "...", "Sentiment": "...", '
        '"Bull": "...", "Bear": "...", "Risk": "..."}, '
        '"corrections_made": "what you fixed or overrode from the debate, or none"}'
    )
    user_prompt = (
        f"Ticker: {ticker}\nCurrent price: {data_ctx.split(chr(10))[1] if chr(10) in data_ctx else ''}\n\n"
        f"DATA:\n{data_ctx}\n\nPORTFOLIO CONSTRAINTS:\n{portfolio_ctx}\n\n"
        f"TRACK RECORD FOR THIS TICKER:\n{track_record}\n\n{yesterday_note}\n\n"
        f"FULL DEBATE TRANSCRIPT:\n{transcript}"
    )
    raw = call_groq(system_prompt, user_prompt, cfg.BA_REVIEWER.model, cfg.BA_REVIEWER.max_tokens, cfg.BA_REVIEWER.request_delay_seconds, cfg.BA_REVIEWER.reasoning_effort)

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[cleaned.find("{"):]
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        parsed = {
            "recommendation": "PARSE_ERROR",
            "confidence": "Low",
            "predicted_next_day_price": None,
            "predicted_next_week_price": None,
            "proposed_position_pct": 0,
            "why": {},
            "corrections_made": "BA response could not be parsed as JSON",
            "_raw": raw,
        }
    return parsed

# ============================================================
# END: BA REVIEWER
# ============================================================


# ============================================================
# START: RUNNER — one full ticker end-to-end (data -> debate -> review -> log)
# ============================================================

def run_ticker(ticker: str):
    ticker_start = time.time()
    print(f"\n=== {ticker} (started {datetime.datetime.now().strftime('%H:%M:%S')}) ===", file=sys.stderr)
    fundamentals, technicals, headlines, close_series = get_market_data(ticker)
    fund_str = _format_fundamentals(fundamentals)
    tech_str = _format_technicals(technicals)
    headlines_str = _format_headlines(headlines)
    data_ctx = f"{fund_str}\n{tech_str}\n{headlines_str}"
    # ^ same 3-line order as before (Fundamentals, Technicals, Headlines) —
    # ba_review()'s "Current price" extraction below indexes line 1 of
    # this string and depends on that order staying put.

    exposure = cfg.PORTFOLIO.current_exposure_pct.get(ticker, 0)
    room_pct = max(cfg.PORTFOLIO.max_position_pct - exposure, 0)
    portfolio_ctx = (
        f"Portfolio value: {cfg.PORTFOLIO.value:,.0f} | Max position per ticker: {cfg.PORTFOLIO.max_position_pct}% | "
        f"Current exposure to {ticker}: {exposure}% | Remaining room: {room_pct}%"
    )

    entries = load_log(ticker)
    entries, verified_count = verify_past_predictions(entries, close_series)
    if verified_count:
        print(f"  verified {verified_count} past prediction(s)", file=sys.stderr)
    track_record = track_record_summary(entries)
    yesterday_entry = entries[-1] if entries else None

    rounds, transcript = run_debate(ticker, fund_str, tech_str, headlines_str, portfolio_ctx)
    ba = ba_review(ticker, transcript, data_ctx, portfolio_ctx, yesterday_entry, track_record)

    # Code enforces both position rules below — never trust the LLM's own
    # JSON to have obeyed them, even though the prompt asked it to.
    proposed = ba.get("proposed_position_pct") or 0
    try:
        proposed = float(proposed)
    except (TypeError, ValueError):
        proposed = 0

    recommendation = ba.get("recommendation")
    if recommendation != "BUY":
        # Rule 1: a HOLD/SELL/PARSE_ERROR call proposing a nonzero new
        # position is self-contradictory — force it to 0 in code.
        if proposed > 0:
            ba["corrections_made"] = (ba.get("corrections_made", "") + f" | Position forced to 0% by code — recommendation was {recommendation}, not BUY.").strip(" |")
        clamped = 0
    else:
        # Rule 2: never allocate more than the remaining portfolio room,
        # regardless of how bullish the BA's own case sounds.
        clamped = max(0, min(proposed, room_pct))
        if clamped < proposed:
            ba["corrections_made"] = (ba.get("corrections_made", "") + f" | Position auto-capped from {proposed}% to {clamped}% by risk rule (room={room_pct}%).").strip(" |")

    ba["proposed_position_pct"] = clamped
    ba["position_value"] = round(cfg.PORTFOLIO.value * clamped / 100, 2)

    entry = {
        "date": datetime.date.today().isoformat(),
        "price_at_prediction": technicals["last_close"],
        "recommendation": ba.get("recommendation"),
        "confidence": ba.get("confidence"),
        "predicted_next_day_price": ba.get("predicted_next_day_price"),
        "predicted_next_week_price": ba.get("predicted_next_week_price"),
        "proposed_position_pct": ba.get("proposed_position_pct"),
        "position_value": ba.get("position_value"),
        "why": ba.get("why"),
        "corrections_made": ba.get("corrections_made"),
        "verified_next_day": None,
        "verified_next_week": None,
    }
    entries.append(entry)
    save_log(ticker, entries)
    print(f"  [{ticker}] DONE in {time.time() - ticker_start:.1f}s total", file=sys.stderr)

    return {
        "ticker": ticker,
        "rounds": rounds,
        "data_ctx": data_ctx,
        "portfolio_ctx": portfolio_ctx,
        "ba": ba,
        "entry": entry,
        "track_record": track_record,
        "yesterday_entry": yesterday_entry,
    }

# ============================================================
# END: RUNNER
# ============================================================


# ============================================================
# START: EMAIL — build the HTML summary and send via Resend
# ============================================================

def build_email_html(results, errors):
    today = datetime.date.today()
    parts = [
        f"<h2>Multi-Agent Stock Debate — {today}</h2>",
        f"<p><b>Executor</b>: Groq {cfg.EXECUTOR.model} &nbsp;|&nbsp; <b>Critic</b>: Groq {cfg.CRITIC.model} &nbsp;|&nbsp; "
        f"<b>Senior BA Reviewer</b>: Groq {cfg.BA_REVIEWER.model}</p>",
        "<p style='color:#a00'><b>Note:</b> next-day/next-week prices are model-generated estimates, "
        "not a statistical forecast. Track record below is the actual accuracy check.</p>",
    ]
    for r in results:
        ba = r["ba"]
        parts.append(f"<h3>{r['ticker']} — {ba.get('recommendation')} ({ba.get('confidence')} confidence)</h3>")
        parts.append(
            f"<p>Next-day target: {ba.get('predicted_next_day_price')} | "
            f"Next-week target: {ba.get('predicted_next_week_price')} | "
            f"Position: {ba.get('proposed_position_pct')}% (~{ba.get('position_value')})</p>"
        )
        parts.append(f"<p><b>Track record:</b> {r['track_record']}</p>")
        if ba.get("corrections_made"):
            parts.append(f"<p><b>BA corrections:</b> {ba['corrections_made']}</p>")
        why = ba.get("why") or {}
        if why:
            parts.append("<ul>" + "".join(f"<li><b>{k}:</b> {v}</li>" for k, v in why.items()) + "</ul>")
        parts.append("<details><summary>Full Executor/Critic transcript</summary>")
        for role_name, exec_claim, critic_claim in r["rounds"]:
            parts.append(f"<p><b>{role_name} — EXECUTOR:</b> {exec_claim}<br><b>CRITIC:</b> {critic_claim}</p>")
        parts.append("</details><hr>")

    if errors:
        parts.append("<h3 style='color:red'>Tickers that failed this run</h3><ul>")
        parts += [f"<li>{t}: {e}</li>" for t, e in errors]
        parts.append("</ul>")

    return "\n".join(parts)


def send_email(subject: str, html: str):
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={"from": "onboarding@resend.dev", "to": os.environ["MY_EMAIL"].split(","), "subject": subject, "html": html},
        timeout=30,
    )
    print("Email status:", resp.status_code, resp.text, file=sys.stderr)
    resp.raise_for_status()

# ============================================================
# END: EMAIL
# ============================================================


# ============================================================
# START: MAIN — secret validation, per-ticker loop, final summary email
# ============================================================

def check_required_secrets():
    """Only the 3 REQUIRED_SECRETS above should ever be missing/empty —
    everything else is a config/settings.py value with a real default, so
    it can't be empty by the GitHub-Actions-empty-string mechanism that
    caused earlier bugs. Returns the list of missing/empty secret names."""
    return [name for name in REQUIRED_SECRETS if not os.environ.get(name, "").strip()]


if __name__ == "__main__":
    missing_secrets = check_required_secrets()
    if missing_secrets:
        print(f"Missing or empty required secrets: {missing_secrets}", file=sys.stderr)
        # Can't email about a missing RESEND_API_KEY/MY_EMAIL, obviously.
        if "RESEND_API_KEY" not in missing_secrets and "MY_EMAIL" not in missing_secrets:
            try:
                send_email(
                    "Stock Debate FAILED — missing secrets",
                    f"<p>These required secrets were missing or empty: {missing_secrets}</p>"
                    f"<p>Check Settings → Secrets → Actions in the repo.</p>",
                )
            except Exception as e:
                print(f"Email send also failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not cfg.TICKERS:
        # Defensive only — TICKERS is now a plain list in config/settings.py,
        # not a parsed secret string, so this should only trip if someone
        # edits the file to an empty list directly.
        print("config.settings.TICKERS is empty — edit that file to add tickers.", file=sys.stderr)
        sys.exit(1)

    run_start = time.time()
    results, errors = [], []
    for ticker in cfg.TICKERS:
        try:
            results.append(run_ticker(ticker))
        except Exception as e:
            print(f"  FAILED {ticker}: {e}", file=sys.stderr)
            errors.append((ticker, str(e)))

    html = build_email_html(results, errors)
    try:
        send_email(f"Stock Debate — {datetime.date.today()} ({len(results)}/{len(cfg.TICKERS)} tickers)", html)
    except Exception as e:
        print(f"Email send failed: {e}", file=sys.stderr)

    print(f"\nDone in {time.time() - run_start:.1f}s total. {len(results)} succeeded, {len(errors)} failed.")
    if not results:
        sys.exit(1)

# ============================================================
# END: MAIN
# ============================================================
