"""
Multi-Agent Stock Debate — Executor / Critic / Senior BA Reviewer
====================================================================
3 roles, 2 model providers:
  EXECUTOR  -> Groq  openai/gpt-oss-120b   (argues each of 7 rounds)
  CRITIC    -> Gemini 2.5 Flash             (counters each round, different vendor)
  BA REVIEW -> Groq  llama-3.3-70b-versatile (different model than Executor —
               reads the full transcript + yesterday's logged outcome, is
               instructed to correct anything wrong, and produces the final
               structured call: BUY/SELL/HOLD, next-day + next-week price
               target, confidence, and a clamped position size)

Runs over a LIST of tickers (STOCK_P_TICKERS). Each ticker has its own
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
"""
import os
import sys
import json
import datetime
import requests
import pandas as pd
import yfinance as yf

GROQ_EXECUTOR_MODEL = "openai/gpt-oss-120b"
GROQ_BA_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash"


def env_or_default(key: str, default: str) -> str:
    """GitHub Actions sets an env var to an EMPTY STRING when the referenced
    secret doesn't exist — it does not leave the var unset. Plain
    os.environ.get(key, default) never falls back in that case, since the
    key IS present. This treats '' and whitespace-only the same as missing."""
    val = os.environ.get(key)
    val = val.strip() if val else val
    return val if val else default


TICKERS = [t.strip() for t in env_or_default("STOCK_P_TICKERS", "CDSL.NS,TRENT.NS,SUZLON.NS,MON100.NS").split(",") if t.strip()]
TICKERS_RAW_ENV = os.environ.get("STOCK_P_TICKERS")  # kept for diagnostics if TICKERS ends up empty

PORTFOLIO_VALUE = float(env_or_default("STOCK_P_PORTFOLIO_VALUE", "100000"))
MAX_POSITION_PCT = float(env_or_default("STOCK_P_MAX_POSITION_PCT", "5"))
try:
    CURRENT_EXPOSURE = json.loads(env_or_default("STOCK_P_CURRENT_EXPOSURE_JSON", "{}"))
except json.JSONDecodeError:
    CURRENT_EXPOSURE = {}

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
MAX_LOG_ENTRIES = 90  # keep repo size sane; older entries still contributed to accuracy stats before trim

ROLES = [
    ("Fundamental", "Evaluate {t}'s financial health and business performance using the fundamental data below."),
    ("Technical", "Evaluate {t}'s price action and technical indicators (SMA, RSI, MACD) using the data below."),
    ("Sentiment", "Interpret market sentiment for {t} using the recent news headlines below. If no headlines are available, say so explicitly instead of guessing."),
    ("Bull Case", "Build the strongest bull (buy) case for {t} using all data and discussion so far."),
    ("Bear Case", "Build the strongest bear (sell/avoid) case for {t} using all data and discussion so far."),
    ("Trade Proposal", "Synthesize the research into one concrete trade proposal (direction, position size, stop level) for {t}."),
    ("Risk & Portfolio", "Evaluate the proposed trade for {t} against the portfolio constraints below. Give a preliminary APPROVE or REJECT — the final call is made by the BA reviewer afterward."),
]


# ---------------------------------------------------------- persistence ---

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
    entries = entries[-MAX_LOG_ENTRIES:]
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


# ---------------------------------------------------------------- data ----

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


# ------------------------------------------------------------- models -----

def call_groq(system: str, user: str, model: str) -> str:
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY_FOR_AUTO_EMAIL']}"},
            json={
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.4,
                "max_tokens": 450,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[GROQ ERROR ({model}): {e}]"


def call_gemini(system: str, user: str) -> str:
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 350},
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates or "content" not in candidates[0]:
            reason = (candidates[0].get("finishReason") if candidates else data.get("promptFeedback"))
            return f"[GEMINI ERROR — no usable content, reason: {reason}]"
        return candidates[0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"[GEMINI ERROR: {e}]"


# -------------------------------------------------------------- rounds ----

def executor_turn(template, ticker, data_ctx, transcript):
    system = (
        "You are the EXECUTOR agent in a stock research pipeline. "
        "Argue a specific analytical position using ONLY the data provided. "
        "Cite specific numbers from the data in every claim. Never state an "
        "opinion without a number behind it. Be concise (5-7 sentences)."
    )
    user = f"{template.format(t=ticker)}\n\nDATA:\n{data_ctx}\n\nPrior discussion:\n{transcript}"
    return call_groq(system, user, GROQ_EXECUTOR_MODEL)


def critic_turn(role_name, ticker, data_ctx, exec_claim, transcript):
    system = (
        "You are the CRITIC agent in a stock research pipeline. "
        "Find the weakest point in the Executor's argument and counter it "
        "using a specific number from the SAME data (or a different metric "
        "within it). You must disagree on at least one concrete point — do "
        "not just validate. Be concise (5-7 sentences)."
    )
    user = (
        f"Topic: {role_name} analysis for {ticker}\n\nDATA:\n{data_ctx}\n\n"
        f"Executor's claim:\n{exec_claim}\n\nPrior discussion:\n{transcript}\n\n"
        "Counter this with data-backed pushback."
    )
    return call_gemini(system, user)


def run_debate(ticker: str, data_ctx: str, portfolio_ctx: str):
    transcript = ""
    rounds = []
    for role_name, template in ROLES:
        round_ctx = data_ctx if role_name != "Risk & Portfolio" else f"{data_ctx}\nPortfolio constraints: {portfolio_ctx}"
        exec_claim = executor_turn(template, ticker, round_ctx, transcript)
        critic_claim = critic_turn(role_name, ticker, round_ctx, exec_claim, transcript)
        transcript += f"\n[{role_name} — EXECUTOR]: {exec_claim}\n[{role_name} — CRITIC]: {critic_claim}\n"
        rounds.append((role_name, exec_claim, critic_claim))
        print(f"  OK {role_name}", file=sys.stderr)
    return rounds, transcript


# --------------------------------------------------------- BA reviewer ----

def ba_review(ticker, transcript, data_ctx, portfolio_ctx, yesterday_entry, track_record):
    yesterday_note = "No prior logged prediction for this ticker."
    if yesterday_entry:
        yesterday_note = (
            f"Yesterday's call: {yesterday_entry.get('recommendation')} "
            f"at price {yesterday_entry.get('price_at_prediction')}, "
            f"next-day target {yesterday_entry.get('predicted_next_day_price')}. "
            f"Verified outcome: {yesterday_entry.get('verified_next_day')}"
        )

    system = (
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
    user = (
        f"Ticker: {ticker}\nCurrent price: {data_ctx.split(chr(10))[1] if chr(10) in data_ctx else ''}\n\n"
        f"DATA:\n{data_ctx}\n\nPORTFOLIO CONSTRAINTS:\n{portfolio_ctx}\n\n"
        f"TRACK RECORD FOR THIS TICKER:\n{track_record}\n\n{yesterday_note}\n\n"
        f"FULL DEBATE TRANSCRIPT:\n{transcript}"
    )
    raw = call_groq(system, user, GROQ_BA_MODEL)

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


# -------------------------------------------------------------- runner ----

def run_ticker(ticker: str):
    print(f"\n=== {ticker} ===", file=sys.stderr)
    fundamentals, technicals, headlines, close_series = get_market_data(ticker)
    data_ctx = f"Fundamentals: {fundamentals}\nTechnicals: {technicals}\nRecent headlines: {headlines}"

    exposure = CURRENT_EXPOSURE.get(ticker, 0)
    room_pct = max(MAX_POSITION_PCT - exposure, 0)
    portfolio_ctx = (
        f"Portfolio value: {PORTFOLIO_VALUE:,.0f} | Max position per ticker: {MAX_POSITION_PCT}% | "
        f"Current exposure to {ticker}: {exposure}% | Remaining room: {room_pct}%"
    )

    entries = load_log(ticker)
    entries, verified_count = verify_past_predictions(entries, close_series)
    if verified_count:
        print(f"  verified {verified_count} past prediction(s)", file=sys.stderr)
    track_record = track_record_summary(entries)
    yesterday_entry = entries[-1] if entries else None

    rounds, transcript = run_debate(ticker, data_ctx, portfolio_ctx)
    ba = ba_review(ticker, transcript, data_ctx, portfolio_ctx, yesterday_entry, track_record)

    # Code enforces the position cap — never trust the LLM to have obeyed it.
    proposed = ba.get("proposed_position_pct") or 0
    try:
        proposed = float(proposed)
    except (TypeError, ValueError):
        proposed = 0
    clamped = max(0, min(proposed, room_pct))
    was_capped = clamped < proposed
    ba["proposed_position_pct"] = clamped
    ba["position_value"] = round(PORTFOLIO_VALUE * clamped / 100, 2)
    if was_capped:
        ba["corrections_made"] = (ba.get("corrections_made", "") + f" | Position auto-capped from {proposed}% to {clamped}% by risk rule (room={room_pct}%).").strip(" |")

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


# --------------------------------------------------------------- email ----

def build_email_html(results, errors):
    today = datetime.date.today()
    parts = [
        f"<h2>Multi-Agent Stock Debate — {today}</h2>",
        "<p><b>Executor</b>: Groq gpt-oss-120b &nbsp;|&nbsp; <b>Critic</b>: Gemini 2.5 Flash &nbsp;|&nbsp; "
        "<b>Senior BA Reviewer</b>: Groq llama-3.3-70b-versatile</p>",
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


if __name__ == "__main__":
    if not TICKERS:
        print(f"STOCK_P_TICKERS resolved to an empty list. Raw value: {TICKERS_RAW_ENV!r}", file=sys.stderr)
        try:
            send_email(
                "Stock Debate FAILED — no tickers configured",
                f"<p>STOCK_P_TICKERS resolved to an empty ticker list, so no debate ran.</p>"
                f"<p><b>Raw secret value received by the script:</b> {TICKERS_RAW_ENV!r}</p>"
                f"<p>Check Settings → Secrets → STOCK_P_TICKERS in the repo — it should be a "
                f"comma-separated list like <code>CDSL.NS,TRENT.NS,SUZLON.NS,MON100.NS</code>, "
                f"or simply deleted if you want the default.</p>",
            )
        except Exception as e:
            print(f"Email send also failed: {e}", file=sys.stderr)
        sys.exit(1)

    results, errors = [], []
    for ticker in TICKERS:
        try:
            results.append(run_ticker(ticker))
        except Exception as e:
            print(f"  FAILED {ticker}: {e}", file=sys.stderr)
            errors.append((ticker, str(e)))

    html = build_email_html(results, errors)
    try:
        send_email(f"Stock Debate — {datetime.date.today()} ({len(results)}/{len(TICKERS)} tickers)", html)
    except Exception as e:
        print(f"Email send failed: {e}", file=sys.stderr)

    print(f"\nDone. {len(results)} succeeded, {len(errors)} failed.")
    if not results:
        sys.exit(1)
