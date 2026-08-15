"""
streamlit_app.py — Sub-project B: on-demand single-ticker analysis.

Reuses the EXACT SAME engine as the daily cron job (Main.py's run_ticker,
build_email_html, send_email) — no duplicated logic, no separate code path
that could drift out of sync with the automated pipeline.

Deploy: Streamlit Community Cloud (free) — see README section at the
bottom of this file for the 4-step setup.
"""

import os
import sys
import streamlit as st

# Main.py lives in the same folder — import its functions directly
# rather than reimplementing anything.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from Main import run_ticker, build_email_html, send_email, check_required_secrets

st.set_page_config(page_title="Stock Analysis — On Demand", page_icon="📊")
st.title("📊 On-Demand Stock Analysis")
st.caption(
    "Runs the same Executor/Critic/BA Reviewer debate as the daily report — "
    "just for one ticker, right now. Takes about 3 minutes."
)

# ---- Lightweight access gate ----
# This page is public once deployed (Streamlit Community Cloud free tier
# has no built-in auth). A passcode isn't real security, but it stops
# random visitors from burning your Groq/Resend quota by accident.
APP_PASSCODE = os.environ.get("APP_PASSCODE", "")
if APP_PASSCODE:
    entered = st.text_input("Passcode", type="password")
    if entered != APP_PASSCODE:
        st.info("Enter the passcode to continue.")
        st.stop()

# ---- Input + validation ----
ticker = st.text_input(
    "Ticker symbol",
    placeholder="e.g. CDSL.NS, TRENT.NS, AAPL, SPY, MON100.NS",
    help="Works for stocks, ETFs, and mutual fund tickers — same yfinance "
         "lookup the daily pipeline already uses, no special handling needed "
         "per asset type.",
).strip().upper()

run_clicked = st.button("Run Analysis", type="primary", disabled=not ticker)

if run_clicked:
    # Real validation: don't just check the string looks ticker-shaped —
    # confirm yfinance actually has data for it. This is the SAME check
    # get_market_data() already does inside run_ticker(), so a bad ticker
    # fails fast with a clear message instead of burning a debate's worth
    # of Groq calls on garbage input.
    missing = check_required_secrets()
    if missing:
        st.error(f"Missing required secrets: {', '.join(missing)} — set these in Streamlit Cloud's app settings, not here.")
        st.stop()

    with st.spinner(f"Running full debate on {ticker} — this takes ~3 minutes, please wait..."):
        try:
            result = run_ticker(ticker)
        except Exception as e:
            st.error(f"Couldn't analyze '{ticker}': {e}")
            st.info("Common cause: not a real ticker symbol, or yfinance has no data for it. Double-check the symbol (e.g. Indian stocks need the .NS suffix).")
            st.stop()

    ba = result["ba"]
    st.success(f"Done — {result['ticker']}: **{ba.get('recommendation')}** ({ba.get('confidence')} confidence)")

    col1, col2, col3 = st.columns(3)
    col1.metric("Next-day target", ba.get("predicted_next_day_price") or "—")
    col2.metric("Next-week target", ba.get("predicted_next_week_price") or "—")
    col3.metric("Position", f"{ba.get('proposed_position_pct')}%")

    st.write(f"**Track record:** {result['track_record']}")
    if ba.get("corrections_made"):
        st.write(f"**BA corrections:** {ba['corrections_made']}")

    why = ba.get("why") or {}
    if why:
        st.subheader("Reasoning")
        for k, v in why.items():
            st.write(f"**{k}:** {v}")

    with st.expander("Full Executor/Critic transcript"):
        for role_name, exec_claim, critic_claim in result["rounds"]:
            st.markdown(f"**{role_name} — EXECUTOR:** {exec_claim}")
            st.markdown(f"**{role_name} — CRITIC:** {critic_claim}")
            st.divider()

    # Email as a distinct subject from the daily digest, so it's easy to
    # tell apart in your inbox — same send_email() function, just a
    # different subject line and it's a single-ticker report.
    try:
        html = build_email_html([result], [])
        send_email(f"On-Demand Analysis: {result['ticker']}", html)
        st.caption("📧 Also emailed to you.")
    except Exception as e:
        st.warning(f"Analysis succeeded but email failed to send: {e}")


# ============================================================
# DEPLOYMENT — Streamlit Community Cloud (free)
# ============================================================
# 1. This file + Main.py + config/ must be in the SAME public GitHub repo
#    already used for the daily pipeline (Multi-Agent-Stock-Debate/).
# 2. share.streamlit.io -> sign in with GitHub -> "New app"
#    -> select this repo -> set "Main file path" to this file's path
#    (e.g. Multi-Agent-Stock-Debate/streamlit_app.py)
# 3. In the app's "Secrets" settings (NOT GitHub Secrets, Streamlit's own
#    secrets panel), add, in TOML format:
#      GROQ_API_KEY_FOR_AUTO_EMAIL = "..."
#      RESEND_API_KEY = "..."
#      MY_EMAIL = "..."
#      APP_PASSCODE = "choose-anything"   # optional but recommended
# 4. Deploy. You get a free *.streamlit.app URL. No server to maintain —
#    Streamlit Cloud handles hosting, restarts, and updates on every push.
