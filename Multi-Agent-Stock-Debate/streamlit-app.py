"""
streamlit-app.py — Sub-project B: on-demand single-ticker analysis.

Reuses the EXACT SAME engine as the daily cron job (Main.py's run_ticker,
build_email_html, send_email) — no duplicated logic, no separate code path
that could drift out of sync with the automated pipeline.

Deploy: Streamlit Community Cloud (free) — see README section at the
bottom of this file for the setup steps.
"""

import os
import sys
import re
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from Main import run_ticker, build_email_html, send_email, check_required_secrets, get_financial_history, get_market_data
from config import settings as cfg

st.set_page_config(page_title="Stock Analysis — On Demand", page_icon="📊", layout="wide")
st.title("📊 On-Demand Stock Analysis")
st.caption(
    "Runs the same Executor/Critic/BA Reviewer debate as the daily report — "
    "just for one ticker, right now. Takes about 3 minutes."
)
with st.expander("How this works — 3 AI models, in sequence"):
    st.markdown(
        f"""
For each of 7 analysis rounds (Fundamental → Technical → Sentiment → Bull Case →
Bear Case → Trade Proposal → Risk & Portfolio), two models argue in sequence:

1. **Executor** (`{cfg.EXECUTOR.model}`, via Groq) — argues a specific position
   using only the data provided, citing real numbers.
2. **Critic** (`{cfg.CRITIC.model}`, via Groq) — deliberately disagrees, pushing
   back on the Executor's weakest point using the same data.

After all 7 rounds complete, a third model reviews the full transcript once:

3. **Senior BA Reviewer** (`{cfg.BA_REVIEWER.model}`, via Groq) — reads
   everything Executor and Critic argued, corrects anything overstated or
   wrong, and issues the final BUY/SELL/HOLD call with position sizing.

All three run on separate Groq models specifically so no single model is
checking its own work.
        """
    )

# ---- Lightweight access gate ----
APP_PASSCODE = os.environ.get("APP_PASSCODE", "")
if APP_PASSCODE:
    entered = st.text_input("Passcode", type="password")
    if entered != APP_PASSCODE:
        st.info("Enter the passcode to continue.")
        st.stop()

# ---- Inputs ----
col_a, col_b = st.columns([2, 1])
with col_a:
    raw_ticker = st.text_input(
        "Ticker symbol",
        placeholder="e.g. CDSL, TRENT, AAPL, SPY, MON100",
        help="Indian NSE stocks: the .NS suffix is added automatically if you "
             "leave it off and the plain symbol doesn't resolve. Works for "
             "stocks, ETFs, and mutual fund tickers — same yfinance lookup "
             "the daily pipeline already uses.",
    ).strip().upper()
with col_b:
    send_email_toggle = st.toggle("📧 Email me a copy", value=False)
    user_email = ""
    if send_email_toggle:
        user_email = st.text_input("Email address", placeholder="you@example.com").strip()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Email only sent if the toggle is on AND a valid address is entered —
# toggle off means zero emails, not even to the account owner.
email_ready = (not send_email_toggle) or (user_email and EMAIL_RE.match(user_email))
if send_email_toggle and user_email and not EMAIL_RE.match(user_email):
    st.warning("That doesn't look like a valid email address — double-check it.")

run_clicked = st.button("Run Analysis", type="primary", disabled=not raw_ticker or not email_ready)

if run_clicked:
    missing = check_required_secrets()
    if missing:
        st.error(f"Missing required secrets: {', '.join(missing)} — set these in Streamlit Cloud's app settings, not here.")
        st.stop()

    # Auto .NS fallback: try exactly what was typed first (covers AAPL, SPY,
    # tickers that already include a suffix). If that resolves to no data,
    # retry once with .NS appended (covers "CDSL" meant as an NSE stock).
    # Never silently guess without telling the user which one was actually used.
    ticker_to_use = raw_ticker
    used_fallback = False
    with st.spinner(f"Looking up {raw_ticker}..."):
        try:
            result = run_ticker(ticker_to_use)
        except Exception as first_error:
            if not raw_ticker.endswith(".NS") and "." not in raw_ticker:
                ticker_to_use = f"{raw_ticker}.NS"
                used_fallback = True
                try:
                    with st.spinner(f"'{raw_ticker}' didn't resolve — trying '{ticker_to_use}' (NSE)..."):
                        result = run_ticker(ticker_to_use)
                except Exception as second_error:
                    st.error(f"Couldn't find data for '{raw_ticker}' or '{ticker_to_use}'.")
                    st.info("Double-check the symbol — it may be delisted, mistyped, or listed on an exchange other than NSE.")
                    st.stop()
            else:
                st.error(f"Couldn't analyze '{raw_ticker}': {first_error}")
                st.stop()

    if used_fallback:
        st.info(f"'{raw_ticker}' didn't resolve directly — showing results for **{ticker_to_use}** (NSE) instead.")

    ba = result["ba"]

    # If every round hit the daily Groq quota, the transcript is entirely
    # error strings and BA Reviewer's output is essentially empty. Detect
    # this and say so plainly rather than showing a dashboard full of
    # blank fields and "nan" with no explanation.
    quota_failures = sum(
        1 for _, exec_claim, critic_claim in result["rounds"]
        if "quota exhausted" in exec_claim.lower() or "quota exhausted" in critic_claim.lower()
    )
    if quota_failures >= 4:
        st.error(
            f"⚠️ This run largely failed — {quota_failures} of 7 rounds hit Groq's "
            "daily token quota (shared with the automated cron job). The results "
            "below are unreliable. Wait for the quota to reset, or use a separate "
            "Groq API key for this app (see the account owner)."
        )

    st.success(f"Done — {result['ticker']}: **{ba.get('recommendation')}** ({ba.get('confidence')} confidence)")

    tab_overview, tab_financials, tab_debate = st.tabs(["📈 Overview", "💰 Financials", "🗣️ Agent Debate"])

    # ---- OVERVIEW TAB ----
    with tab_overview:
        today_close = result["entry"].get("price_at_prediction")

        st.subheader("Prediction vs. today's actual price")
        st.caption("The targets below are the agents' PREDICTIONS for future prices — "
                   "some difference from today's close is expected, that's the forecast, not an error.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Today's close", today_close if today_close else "—")
        c2.metric("Next-day target", ba.get("predicted_next_day_price") or "—")
        c3.metric("Next-week target", ba.get("predicted_next_week_price") or "—")
        c4.metric("Position", f"{ba.get('proposed_position_pct')}%")

        st.divider()
        st.subheader("Key ratios")
        # run_ticker() only returns fundamentals baked into a display string
        # (data_ctx) — fetching structured numbers separately here for the
        # metric cards below. Cheap, no-LLM call, same data source.
        try:
            f, _, _, _ = get_market_data(result["ticker"])
        except Exception:
            f = {}
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("P/E (trailing)", f.get("trailingPE") or "—")
        r1.metric("P/E (forward)", f.get("forwardPE") or "—")
        r2.metric("P/B", f.get("priceToBook") or "—")
        r2.metric("Dividend Yield", f"{f.get('dividendYield'):.2f}%" if f.get("dividendYield") else "—")
        # NOT ×100: yfinance already returns dividendYield as a percentage
        # number (e.g. 0.46 meaning 0.46%), not a fraction like 0.0046.
        # The earlier ×100 version showed 46.00% for RELIANCE.NS, whose
        # real dividend yield is ~0.4-0.5% — confirms the raw value was
        # already correctly scaled and the multiplication was the bug.
        r3.metric("ROE", f"{f.get('returnOnEquity')*100:.1f}%" if f.get("returnOnEquity") else "—")
        r3.metric("Debt/Equity", f.get("debtToEquity") or "—")
        market_cap = f.get("marketCap")
        r4.metric("Market Cap", f"₹{market_cap / 1e7:,.0f} Cr" if market_cap else "—")
        # 1 Crore = 1e7. Raw rupee figures (₹17,727,538,331,648) are
        # unreadable at large-cap scale — Indian markets conventionally
        # quote market cap in Crores.
        r4.metric("Sector", f.get("sector") or "—")
        st.caption("Sector-average P/E isn't reliably available from this data source — "
                   "not shown to avoid displaying a made-up comparison.")

        st.write(f"**Track record:** {result['track_record']}")
        if ba.get("corrections_made"):
            st.write(f"**BA corrections:** {ba['corrections_made']}")

    # ---- FINANCIALS TAB ----
    with tab_financials:
        fin = get_financial_history(result["ticker"])
        if fin["years"]:
            st.subheader("Revenue & Net Income (year-over-year)")
            chart_data = {"Year": fin["years"], "Revenue": fin["revenue"], "Net Income": fin["net_income"]}
            st.bar_chart(chart_data, x="Year", y=["Revenue", "Net Income"])
            if any(d is not None for d in fin["total_debt"]):
                st.subheader("Total Debt (year-over-year)")
                st.bar_chart({"Year": fin["years"], "Total Debt": fin["total_debt"]}, x="Year", y="Total Debt")
        else:
            st.info("No multi-year financial statements available for this ticker — "
                    "common for ETFs and mutual funds, which don't file income statements.")

    # ---- AGENT DEBATE TAB ----
    with tab_debate:
        why = ba.get("why") or {}
        if why:
            st.subheader("Reasoning")
            for k, v in why.items():
                st.write(f"**{k}:** {v}")

        with st.expander("Full Executor/Critic transcript", expanded=False):
            for role_name, exec_claim, critic_claim in result["rounds"]:
                st.markdown(f"**{role_name} — EXECUTOR:** {exec_claim}")
                st.markdown(f"**{role_name} — CRITIC:** {critic_claim}")
                st.divider()

    # ---- Email (only if the toggle is on) ----
    if send_email_toggle and user_email:
        try:
            html = build_email_html([result], [])
            send_email(f"On-Demand Analysis: {result['ticker']}", html, extra_recipient=user_email)
            st.caption(f"📧 Emailed to {user_email}.")
        except Exception as e:
            st.warning(f"Analysis succeeded but email failed to send: {e}")
    else:
        st.caption("📧 Email copy not requested — results shown above only.")


# ============================================================
# DEPLOYMENT — Streamlit Community Cloud (free)
# ============================================================
# 1. This file + Main.py + config/ + requirements.txt must be in the SAME
#    public GitHub repo already used for the daily pipeline
#    (Multi-Agent-Stock-Debate/).
# 2. share.streamlit.io -> sign in with GitHub -> "New app"
#    -> select this repo -> set "Main file path" to this file's path
#    (e.g. Multi-Agent-Stock-Debate/streamlit-app.py)
# 3. In the app's "Secrets" settings (NOT GitHub Secrets, Streamlit's own
#    secrets panel), add, in TOML format:
#      GROQ_API_KEY_FOR_AUTO_EMAIL = "..."
#      RESEND_API_KEY = "..."
#      MY_EMAIL = "..."
#      APP_PASSCODE = "choose-anything"   # optional but recommended
# 4. Deploy. You get a free *.streamlit.app URL. No server to maintain —
#    Streamlit Cloud handles hosting, restarts, and updates on every push.
