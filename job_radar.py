"""
job_radar.py  v3
─────────────────────────────────────────────────────────────────────────────
Same secrets as build-send-email.py — GROQ_API_KEY_FOR_AUTO_EMAIL, RESEND_API_KEY, MY_EMAIL
Workflow: .github/workflows/job-radar.yml  cron '30 1 * * *' (7 AM IST)
pip install: requests feedparser

PLATFORM        ENTRIES/DAY   FILTER STRATEGY
──────────────────────────────────────────────────────────────────────
RemoteOK        tag-scoped    keyword on title  (unfiltered feed needs it)
WeWorkRemotely  64 entries    NO keyword — RSS already = programming only
WorkingNomads   43 entries    NO keyword — API already = development only
Remote100K      REMOVED       404 — dead URL
──────────────────────────────────────────────────────────────────────
"""

"""
job_radar.py  v4
─────────────────────────────────────────────────────────────────────────────
Changes from v3:
  - Cross-day dedup: seen_jobs.json tracks every processed job
  - Score caching: same job never re-scored (fixes inconsistency)
  - 14-day suppression window: stale listings auto-expire back into feed
  - Retry logic on WWR/WorkingNomads fetches (3 attempts, 5s backoff)
  - PROFILE tightened: Flutter/React-only roles capped at 60

Secrets: GROQ_API_KEY_FOR_AUTO_EMAIL, RESEND_API_KEY, MY_EMAIL  (unchanged)
Workflow: see job-radar.yml — needs permissions: contents: write + git push step
"""

import json
import os
import time
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ─── Seen-jobs store ─────────────────────────────────────────────────────────
# Committed back to repo by the workflow after each run.
# Structure: { "canonical_id": { title, score, first_seen, suppress_until } }
SEEN_FILE = "seen_jobs.json"
SUPPRESS_DAYS = 14          # re-surface a listing after 14 days if still open


def load_seen() -> dict:
    try:
        with open(SEEN_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_seen(seen: dict):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2, default=str)


def _canonical_id(source: str, id_or_url: str) -> str:
    """Stable cross-run key — prevents same job re-appearing next day."""
    return f"{source}::{id_or_url}"


def _is_suppressed(seen: dict, cid: str) -> bool:
    if cid not in seen:
        return False
    suppress_until = seen[cid].get("suppress_until", "")
    if not suppress_until:
        return True     # old entry without expiry — keep suppressing
    today = datetime.now(timezone.utc).date().isoformat()
    return today <= suppress_until


# ─── Candidate profile ───────────────────────────────────────────────────────
PROFILE = """
UI Solution Architect, 17+ yrs exp.
Stack: Angular 17+, TypeScript, PrimeNG, ag-Grid, Spring Boot, Java 8, Oracle, OpenShift.
Led centralised Angular component library consumed by 40+ apps, 200+ components.
Ran SARC governance forum. AWS Solutions Architect Associate certified.
Targeting: Senior UI Architect / Frontend Architect / Technical Lead (UI) — REMOTE ONLY.
Preferred: Banking GCC, fintech, enterprise product companies. Open to global remote.

SCORING RULES (hard):
- Angular or TypeScript explicitly required → eligible for 80+
- Generic "frontend" without Angular/TS → cap at 75
- React-only, Vue-only, Flutter-only → cap at 60 (different stack)
- Pure backend, DevOps, QA, sales engineer, on-site → score 0, exclude
- Junior / mid level (< 7 yrs expected) → score 0, exclude
"""

# ─── Keyword pre-filter (RemoteOK only — WWR/WN already scoped) ──────────────
KEYWORDS = [
    "angular", "typescript", "frontend architect", "ui architect",
    "solution architect", "component library", "design system",
    "tech lead", "technical lead", "senior frontend", "principal engineer",
    "staff engineer", "web architect", "frontend lead", "ui lead",
    "front end", "front-end",
]

UA_HEADERS = {"User-Agent": "Mozilla/5.0 (job-radar/1.0; personal job search)"}


def _relevant(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in KEYWORDS)


def _fetch_with_retry(fn, name: str, retries: int = 3, delay: int = 5) -> list:
    for attempt in range(1, retries + 1):
        try:
            result = fn()
            if result is not None:
                return result
        except Exception as e:
            print(f"  {name} attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    return []


# ─── SOURCE 1: RemoteOK ──────────────────────────────────────────────────────
REMOTEOK_TAG_URLS = [
    "https://remoteok.com/api?tags=angular",
    "https://remoteok.com/api?tags=typescript",
    "https://remoteok.com/api?tags=frontend",
    "https://remoteok.com/api?tags=architect",
]

def _do_fetch_remoteok(limit: int = 15) -> list[dict]:
    jobs, seen_ids = [], set()
    for url in REMOTEOK_TAG_URLS:
        r = requests.get(url, headers=UA_HEADERS, timeout=15)
        r.raise_for_status()
        for item in r.json()[1:]:
            job_id = str(item.get("id", ""))
            if job_id in seen_ids:
                continue
            title = item.get("position", "")
            if not _relevant(title):
                continue
            seen_ids.add(job_id)
            jobs.append({
                "source": "RemoteOK",
                "cid":    _canonical_id("RemoteOK", job_id),
                "title":  f"{title} @ {item.get('company', '?')}",
                "link":   item.get("url") or f"https://remoteok.com/jobs/{job_id}",
                "salary": item.get("salary", ""),
            })
    return jobs[:limit]

def fetch_remoteok() -> list[dict]:
    jobs = _fetch_with_retry(lambda: _do_fetch_remoteok(), "RemoteOK")
    print(f"  RemoteOK: {len(jobs)} keyword-matched")
    return jobs


# ─── SOURCE 2: WeWorkRemotely ────────────────────────────────────────────────
WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]

def _do_fetch_wwr(limit: int = 20) -> list[dict]:
    jobs, seen_links = [], set()
    for feed_url in WWR_FEEDS:
        feed = feedparser.parse(feed_url, request_headers=UA_HEADERS)
        if feed.bozo and not feed.entries:
            print(f"  WWR bozo ({feed_url}): {feed.bozo_exception}")
            continue
        print(f"  WWR {feed_url}: {len(feed.entries)} entries")
        for entry in feed.entries:
            link  = entry.get("link", "")
            title = entry.get("title", "")
            if not link or not title or link in seen_links:
                continue
            seen_links.add(link)
            jobs.append({
                "source": "WeWorkRemotely",
                "cid":    _canonical_id("WWR", link),
                "title":  title,
                "link":   link,
                "salary": "",
            })
            if len(jobs) >= limit:
                return jobs
    return jobs

def fetch_weworkremotely() -> list[dict]:
    jobs = _fetch_with_retry(lambda: _do_fetch_wwr(), "WeWorkRemotely")
    print(f"  WeWorkRemotely: {len(jobs)} passed to dedup")
    return jobs


# ─── SOURCE 3: Working Nomads ────────────────────────────────────────────────
def _do_fetch_wn(limit: int = 20) -> list[dict]:
    url = "https://www.workingnomads.com/api/exposed_jobs/?category=development"
    r = requests.get(url, headers=UA_HEADERS, timeout=15)
    print(f"  WorkingNomads HTTP: {r.status_code}")
    r.raise_for_status()
    data = r.json()
    print(f"  WorkingNomads raw: {len(data)}")
    jobs = []
    for item in data:
        title = item.get("title", "")
        if not title:
            continue
        job_url = item.get("url", "")
        jobs.append({
            "source": "WorkingNomads",
            "cid":    _canonical_id("WN", job_url or title),
            "title":  f"{title} @ {item.get('company_name', '?')}",
            "link":   job_url,
            "salary": "",
        })
        if len(jobs) >= limit:
            break
    return jobs

def fetch_workingnomads() -> list[dict]:
    jobs = _fetch_with_retry(lambda: _do_fetch_wn(), "WorkingNomads")
    print(f"  WorkingNomads: {len(jobs)} passed to dedup")
    return jobs


# ─── Aggregate → cross-day dedup → split new vs cached ───────────────────────
def fetch_and_filter(seen: dict) -> tuple[list[dict], list[dict], list[str]]:
    """
    Returns:
      new_jobs    — never seen before → need LLM scoring
      cached_jobs — seen before, score cached → skip LLM
      errors      — sources that returned nothing
    """
    print("\nFetching jobs...")
    all_jobs, errors = [], []
    for name, fn in [
        ("RemoteOK",       fetch_remoteok),
        ("WeWorkRemotely", fetch_weworkremotely),
        ("WorkingNomads",  fetch_workingnomads),
    ]:
        results = fn()
        if not results:
            errors.append(name)
        all_jobs.extend(results)

    # Intra-run dedup by cid
    seen_cids, deduped = set(), []
    for j in all_jobs:
        if j["cid"] not in seen_cids:
            seen_cids.add(j["cid"])
            deduped.append(j)

    print(f"\nTotal unique this run: {len(deduped)}")

    new_jobs, cached_jobs = [], []
    for j in deduped:
        if _is_suppressed(seen, j["cid"]):
            cached = seen[j["cid"]]
            if cached.get("score", 0) >= 60:        # only resurface if was relevant
                j["score"]  = cached["score"]
                j["why"]    = cached.get("why", "")
                j["gap"]    = cached.get("gap", "")
                cached_jobs.append(j)
        else:
            new_jobs.append(j)

    print(f"New (need scoring): {len(new_jobs)}  |  Suppressed: {len(deduped) - len(new_jobs)}")
    return new_jobs, cached_jobs, errors


# ─── LLM scoring — new jobs only ─────────────────────────────────────────────
def score_with_llm(jobs: list[dict]) -> list[dict]:
    if not jobs:
        return []

    job_list = "\n".join(
        f"[{i+1}] [{j['source']}] {j['title']}"
        f"{' | ' + j['salary'] if j['salary'] else ''}"
        f" | {j['link']}"
        for i, j in enumerate(jobs)
    )

    prompt = (
        f"Candidate profile:\n{PROFILE}\n\n"
        "Score each job below 0-100 against this candidate. "
        "Apply the SCORING RULES in the profile strictly. "
        "Output ALL jobs — even 0-scored ones (so I can cache them). "
        "One entry per job, no skipping, no duplicates. Format:\n\n"
        "JOB_ID: N\n"
        "SCORE: NN\n"
        "WHY: one sentence\n"
        "GAP: one item or None\n"
        "---\n\n"
        f"JOBS:\n{job_list}"
    )

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY_FOR_AUTO_EMAIL']}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        },
        timeout=45,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]

    # Parse LLM output back onto job objects
    scored = {j["cid"]: j for j in jobs}
    current_id = None
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("JOB_ID:"):
            try:
                idx = int(line.split(":", 1)[1].strip()) - 1
                if 0 <= idx < len(jobs):
                    current_id = jobs[idx]["cid"]
            except (ValueError, IndexError):
                current_id = None
        elif line.startswith("SCORE:") and current_id:
            try:
                scored[current_id]["score"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("WHY:") and current_id:
            scored[current_id]["why"] = line.split(":", 1)[1].strip()
        elif line.startswith("GAP:") and current_id:
            scored[current_id]["gap"] = line.split(":", 1)[1].strip()

    return list(scored.values())


# ─── Update seen_jobs.json ────────────────────────────────────────────────────
def update_seen(seen: dict, scored_new: list[dict]):
    today = datetime.now(timezone.utc).date().isoformat()
    suppress_until = (
        datetime.now(timezone.utc).date() + timedelta(days=SUPPRESS_DAYS)
    ).isoformat()

    for j in scored_new:
        seen[j["cid"]] = {
            "title":          j["title"],
            "score":          j.get("score", 0),
            "why":            j.get("why", ""),
            "gap":            j.get("gap", ""),
            "first_seen":     today,
            "suppress_until": suppress_until,
        }


# ─── Build email ──────────────────────────────────────────────────────────────
def build_and_send_email(
    new_scored: list[dict],
    cached: list[dict],
    errors: list[str],
    total_reviewed: int,
):
    # Combine + sort; suppress ≤ 59
    all_hits = [j for j in new_scored + cached if j.get("score", 0) >= 60]
    all_hits.sort(key=lambda j: j.get("score", 0), reverse=True)

    if not all_hits:
        body = "<p style='color:#666'>No roles scored ≥60 today. Check again tomorrow.</p>"
    else:
        rows = []
        for j in all_hits:
            score = j.get("score", "?")
            why   = j.get("why", "")
            gap   = j.get("gap", "None")
            cached_tag = " <span style='font-size:10px;color:#aaa'>(cached score)</span>" \
                         if "first_seen" not in j else ""
            rows.append(f"""
            <div style='margin-bottom:20px;padding:12px 14px;border:1px solid #e0e0e0;
                        border-left:4px solid {"#0066cc" if score>=75 else "#f0a500" if score>=60 else "#ccc"};
                        border-radius:6px'>
              <h3 style='margin:0 0 4px;color:#0d1b2a;font-size:15px'>
                [{score}/100] {j['title']}{cached_tag}
              </h3>
              <p style='margin:2px 0;font-size:12px;color:#888'><b>Source:</b> {j['source']}</p>
              <p style='margin:4px 0;color:#333;font-size:13px'><b>Why:</b> {why}</p>
              <p style='margin:2px 0;color:#c0392b;font-size:13px'><b>Gap:</b> {gap}</p>
              <a href='{j["link"]}' style='display:inline-block;margin-top:6px;color:#0066cc;
                 font-weight:500;font-size:13px'>→ Apply Now</a>
            </div>
            """)
        body = "".join(rows)

    new_count = len([j for j in new_scored if j.get("score",0) >= 60])
    cached_count = len([j for j in cached if j.get("score",0) >= 60])
    error_block = (
        f"<p style='color:#c0392b;font-size:12px;margin-top:12px'>"
        f"⚠️ Sources with issues: {', '.join(errors)}</p>"
    ) if errors else ""

    html = f"""
    <div style='font-family:sans-serif;max-width:680px;margin:auto;padding:16px'>
      <div style='background:#0d1b2a;color:white;padding:14px 18px;border-radius:8px;margin-bottom:16px'>
        <h2 style='margin:0;font-size:18px'>🎯 Job Radar — {datetime.now().strftime('%d %b %Y')}</h2>
        <p style='margin:6px 0 0;font-size:13px;opacity:.8'>
          {total_reviewed} reviewed · <b>{new_count} new hits</b> · {cached_count} cached
          · RemoteOK · WeWorkRemotely · WorkingNomads
        </p>
      </div>
      {body}
      {error_block}
      <hr style='border:none;border-top:1px solid #eee;margin:20px 0'>
      <p style='font-size:11px;color:#aaa'>
        Listings suppressed for {SUPPRESS_DAYS} days after first seen.
        Next: open each link → use Claude browser plugin to review + apply.
      </p>
    </div>
    """

    subject_tag = f"{new_count} new" if new_count else "no new today"
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from":    "onboarding@resend.dev",
            "to":      os.environ["MY_EMAIL"].split(","),
            "subject": f"🎯 Job Radar {datetime.now().strftime('%d %b')} — {subject_tag} ({total_reviewed} reviewed)",
            "html":    html,
        },
        timeout=15,
    )
    print(f"\nEmail sent: {resp.status_code}")
    resp.raise_for_status()


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    seen = load_seen()
    print(f"Loaded seen_jobs.json: {len(seen)} entries")

    new_jobs, cached_jobs, errors = fetch_and_filter(seen)

    scored_new = score_with_llm(new_jobs)

    update_seen(seen, scored_new)
    save_seen(seen)
    print(f"seen_jobs.json updated: {len(seen)} total entries")

    build_and_send_email(scored_new, cached_jobs, errors, len(new_jobs) + len(cached_jobs)))
