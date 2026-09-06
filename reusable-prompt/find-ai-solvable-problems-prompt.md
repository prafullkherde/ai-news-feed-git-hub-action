# PROMPT — FIND REAL, RECURRING PROBLEMS SOFTWARE/AI CAN NOW SOLVE

## ROLE
Skeptical researcher: consumer/UX researcher + PM + distribution strategist + AI architect + investor.
Start from the human problem. Do not manufacture opportunity from AI capability. Reject anything that's a pitch without evidence. "No opportunity found" is a valid output.

## SCOPE — DO NOT NARROW TO ONE CATEGORY
Sweep ALL domains equally. This explicitly includes **software/product friction**, not just financial/consumer disputes:
- App/product has no channel to report a bug or request a feature
- Settings/permissions buried or undiscoverable
- Broken cancellation/deletion flows, dead-end error states
- No way to export/delete personal data despite claims of compliance
- Silent failures (payment retries, notification black holes, sync conflicts)
- Accessibility dead ends
- Plus: banking, subscriptions, shopping, delivery, travel, housing, utilities, insurance, employment, education, government/bureaucracy, freelancers, renters, elderly/immigrant-specific friction.

Do not let examples anchor you to finance. Any domain where a human hits a wall and has to work around software/institutional failure qualifies.

---

## PHASE 0 — EXISTENCE GATE (run first, per candidate — kill fast)
For each candidate problem, before any deeper work:
1. **Does this problem verifiably exist?** Cite evidence (complaint forum thread, regulator filing, review, support-forum post, app-store review, news). No evidence → discard, don't rationalize it into the list.
2. **Is it old/recurring**, not a one-off anecdote? Give approximate duration (years) and frequency (daily/weekly/monthly/annual/once-ever).
3. **Is there proof of active help-seeking** (search queries, forum posts, "how do I..." patterns, paid workarounds)? Pain without help-seeking = weak signal, deprioritize.

Only problems passing all three proceed to Phase 1+.

---

## PHASE 1 — PROBLEM DEFINITION
One plain sentence a normal person would recognize. State: who suffers, estimated population (US/UK/EU with source, calculation shown — no "millions of people" without math).

## PHASE 2 — CONSUMER JOURNEY
- **Trigger**: smallest observable event (email, error screen, missing button, charge, rejection).
- **Current workaround**: what they actually do today (search, Reddit, support call, give up) — with evidence, not assumption.
- **Desired outcome**: smallest unit — explanation / decision / comparison / document / execution / escalation. Don't conflate problem with outcome.

## PHASE 3 — OBJECT & ENTRY TEST
- Can the customer hand over **one object** (email, PDF, screenshot, error log, contract) and get value? If it requires inbox/bank/full-account access instead, score it down.
- **Entry point** (score 0–5, 5=best): exact-match search term → object upload → email forward → browser extension → requires remembering the app later → needs advertising.
- **Who owns the door** (Green=we control entry / Yellow=customer voluntarily brings object / Orange=needs OAuth / Red=needs another company's cooperation). Prefer Green/Yellow.

## PHASE 4 — AI FIT
- What did solving this require before AI (reading, comparing, calculating, drafting)? What can AI now do (extract/classify/compare/reason/generate/ask clarifying questions)? Don't claim autonomous execution just because an LLM can produce text.
- **Verifiability** (0–5): can the customer independently check the answer (citation, calculation, doc excerpt, deterministic rule)? Reject if unverifiable and stakes are real.
- **Failure cost**: Low / Medium / High (legal, medical, financial, immigration, safety). High cost → require human-in-loop by default.
- **Human-in-loop design**: AI-only vs. AI-drafts-human-approves vs. AI-executes-after-approval vs. autonomous (only if reversible + reliable).

## PHASE 5 — WHY UNSOLVED / COMPETITION
List real competitors including non-obvious ones (Google, spreadsheets, Reddit, calling support, ignoring it). For each: what they solve, price, weakness, why complaints persist. Then state explicitly why this stayed unsolved (too small before AI / fragmented / low willingness to pay / regulation / no one owns the workflow / etc.) — the "too small/expensive before, AI changes the economics now" framing is the strongest signal.

## PHASE 6 — MONEY
- Who pays, and are they already paying/spending time on a workaround (evidence, amount, frequency)?
- Business model that matches actual behavior (one-time / subscription / success-fee / B2B2C / freemium / API) — don't force subscription onto a one-time problem.
- Rough unit economics: revenue/customer − AI cost − ops − support − failure/refund cost = contribution margin (conservative/base/optimistic).

## PHASE 7 — MVP
One input → one analysis → one output/action. No dashboards, no multi-integration ecosystem at v1. State the exact MVP in one sentence.

## PHASE 8 — TRUST/RISK
Minimum data needed; can it be processed and deleted rather than stored? Flag PII/financial/health/legal/children's data and applicable regs (GDPR/CCPA/sector-specific) — don't auto-reject regulated problems, just state the manageable MVP-level mitigation.

---

## SCORING (0–5 each, then flag penalties)
Problem reality | Frequency×scale | Search/intent evidence | Object/low-permission entry | Distribution proximity | AI solvability | Verifiability | Existing willingness-to-pay | Competitive whitespace | MVP simplicity | Retention | Trust/regulatory feasibility

**Penalties** (subtract, don't ignore): incumbent dominance, platform/API dependency, high CAC, high liability, weak intent evidence.

**Auto-reject if**: no existence evidence (Phase 0 fail) · requires broad account access · unverifiable + high failure cost · pure "nice to have" · depends on an API that could vanish · CAC depends mainly on ads · large ecosystem required before any value appears.

---

## OUTPUT

**1. What was investigated, what was rejected and why** (one line each — cite the Phase 0 evidence or lack thereof).

**2. Shortlist (10–20 survivors)** — one row per problem:
Problem | Domain | Evidence (link/type) | Frequency | Population estimate | Trigger | Object | Entry point | AI role | Verification | Failure risk | Why unsolved before | MVP | Who pays | Model | Score

**3. Top 3 — deep dive** (journey map trigger→resolution→payment; architecture: input→parser→AI/rules split→human-review point→action; economics estimate; one validation experiment with hypothesis/sample size/success-fail metric/cost/timeframe).

**4. Verdict per top-3: BUILD / TEST / WAIT / KILL**, ≤10 sentences each.

Mark every claim A (hard data/regulator/filing) through E (unvalidated hypothesis). Never present E as fact. No motivational language, no "huge opportunity" without cited evidence.
