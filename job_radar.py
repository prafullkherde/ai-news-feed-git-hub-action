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

import os
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ─── Candidate profile ───────────────────────────────────────────────────────
PROFILE = """
UI Solution Architect, 17+ yrs exp.
Stack: Angular, TypeScript, PrimeNG, ag-Grid, Spring Boot, Java 8, Oracle, OpenShift.
Led centralised Angular component library consumed by 40+ apps.
Ran SARC governance forum. AWS Solutions Architect Associate certified.
Targeting: Senior UI Architect / Frontend Architect / Technical Lead (UI) — REMOTE ONLY.
Preferred sectors: Banking GCC, fintech, product companies. Open to global remote.
NOT relevant: pure backend, DevOps, QA, junior/mid roles, on-site/hybrid India.
"""

# ─── Keyword pre-filter — used only for RemoteOK (unscoped feed) ─────────────
# WWR and WorkingNomads skip this — their feeds are already scoped to dev roles
KEYWORDS = [
    "angular", "typescript", "frontend architect", "ui architect",
    "solution architect", "component library", "design system",
    "tech lead", "technical lead", "senior frontend", "principal engineer",
    "staff engineer", "react architect", "web architect", "frontend lead",
    "ui lead", "front end", "front-end",
]

CUTOFF = datetime.now(timezone.utc) - timedelta(hours=48)
UA_HEADERS = {"User-Agent": "Mozilla/5.0 (job-radar/1.0; personal job search)"}


def _relevant(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in KEYWORDS)


# ─── SOURCE 1: RemoteOK ──────────────────────────────────────────────────────
# ?tags=X = server-side filter. Still run _relevant() — tag match != title match.

REMOTEOK_TAG_URLS = [
    "https://remoteok.com/api?tags=angular",
    "https://remoteok.com/api?tags=typescript",
    "https://remoteok.com/api?tags=frontend",
    "https://remoteok.com/api?tags=architect",
]

def fetch_remoteok(limit: int = 15) -> list[dict]:
    jobs, seen = [], set()
    for url in REMOTEOK_TAG_URLS:
        try:
            r = requests.get(url, headers=UA_HEADERS, timeout=15)
            r.raise_for_status()
            for item in r.json()[1:]:
                job_id = str(item.get("id", ""))
                if job_id in seen:
                    continue
                title = item.get("position", "")
                if not _relevant(title):
                    continue
                seen.add(job_id)
                jobs.append({
                    "source": "RemoteOK",
                    "id":     job_id,
                    "title":  f"{title} @ {item.get('company', '?')}",
                    "link":   item.get("url") or f"https://remoteok.com/jobs/{job_id}",
                    "salary": item.get("salary", ""),
                })
        except Exception as e:
            print(f"  RemoteOK error ({url}): {e}")

    jobs = jobs[:limit]
    print(f"  RemoteOK: {len(jobs)} matched")
    return jobs


# ─── SOURCE 2: WeWorkRemotely ────────────────────────────────────────────────
# RSS is already scoped to programming/full-stack — skip keyword filter.
# Just deduplicate and respect the 48h cutoff.

WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]

def fetch_weworkremotely(limit: int = 20) -> list[dict]:
    jobs, seen = [], set()
    for feed_url in WWR_FEEDS:
        try:
            feed = feedparser.parse(feed_url, request_headers=UA_HEADERS)
            if feed.bozo and not feed.entries:
                print(f"  WWR bozo ({feed_url}): {feed.bozo_exception}")
                continue
            print(f"  WWR {feed_url}: {len(feed.entries)} entries")
            for entry in feed.entries:
                link  = entry.get("link", "")
                title = entry.get("title", "")
                if link in seen or not title:
                    continue
                pub = entry.get("published_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < CUTOFF:
                        continue
                seen.add(link)
                jobs.append({
                    "source": "WeWorkRemotely",
                    "id":     link,
                    "title":  title,
                    "link":   link,
                    "salary": "",
                })
                if len(jobs) >= limit:
                    break
        except Exception as e:
            print(f"  WWR error ({feed_url}): {e}")
    print(f"  WeWorkRemotely: {len(jobs)} passed to LLM")
    return jobs


# ─── SOURCE 3: Working Nomads ────────────────────────────────────────────────
# API is already scoped to development category — skip keyword filter.
# LLM will discard irrelevant roles (DevOps, backend, etc.).

def fetch_workingnomads(limit: int = 20) -> list[dict]:
    url = "https://www.workingnomads.com/api/exposed_jobs/?category=development"
    try:
        r = requests.get(url, headers=UA_HEADERS, timeout=15)
        print(f"  WorkingNomads status: {r.status_code}")
        r.raise_for_status()
        data = r.json()
        print(f"  WorkingNomads raw count: {len(data)}")
        jobs = []
        for item in data:
            title   = item.get("title", "")
            company = item.get("company_name", "?")
            if not title:
                continue
            pub_str = item.get("pub_date", "")
            if pub_str:
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    if pub_dt < CUTOFF:
                        continue
                except Exception:
                    pass
            jobs.append({
                "source": "WorkingNomads",
                "id":     item.get("url", title),
                "title":  f"{title} @ {company}",
                "link":   item.get("url", ""),
                "salary": "",
            })
            if len(jobs) >= limit:
                break
        print(f"  WorkingNomads: {len(jobs)} passed to LLM")
        return jobs
    except Exception as e:
        print(f"  WorkingNomads ERROR: {e}")
        return []


# ─── Aggregate + dedup by canonical id ──────────────────────────────────────
def fetch_all_jobs() -> tuple[list[dict], list[str]]:
    print("Fetching jobs...")
    sources = [
        ("RemoteOK",       fetch_remoteok),
        ("WeWorkRemotely", fetch_weworkremotely),
        ("WorkingNomads",  fetch_workingnomads),
    ]
    all_jobs, errors = [], []
    for name, fn in sources:
        results = fn()
        if not results:
            errors.append(name)
        all_jobs.extend(results)

    seen, deduped = set(), []
    for j in all_jobs:
        key = j.get("id") or j["link"]
        if key and key not in seen:
            seen.add(key)
            deduped.append(j)

    print(f"Total unique jobs to LLM: {len(deduped)}")
    return deduped, errors


# ─── LLM filter ──────────────────────────────────────────────────────────────
def filter_with_llm(jobs: list[dict]) -> str:
    if not jobs:
        return "No jobs found in the last 48 hours."

    job_list = "\n".join(
        f"[{i+1}] [{j['source']}] {j['title']}"
        f"{' | ' + j['salary'] if j['salary'] else ''}"
        f" | {j['link']}"
        for i, j in enumerate(jobs)
    )

    prompt = (
        f"Candidate profile:\n{PROFILE}\n\n"
        "From the job list below, select the BEST MATCHING jobs for this candidate. "
        "Return UP TO 10, fewer if quality drops below 60. "
        "CRITICAL: never list the same job twice — each job appears once only. "
        "UI/frontend focus is MANDATORY for scores above 70 — "
        "backend-only or sales roles must score below 60. "
        "Sort by score descending. Output ONLY this format:\n\n"
        "## [NN/100] Job Title @ Company\n"
        "**Source:** platform\n"
        "**Why:** one sentence — name the specific matching skills\n"
        "**Gap:** one missing requirement, or 'None'\n"
        "**Apply:** URL\n\n"
        f"JOB LIST:\n{job_list}"
    )

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY_FOR_AUTO_EMAIL']}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ─── Email ───────────────────────────────────────────────────────────────────
def send_email(body_md: str, errors: list[str], total: int):
    rows = []
    for line in body_md.split("\n"):
        if line.startswith("## "):
            rows.append(
                f"<h3 style='margin:18px 0 4px;color:#0d1b2a;border-left:4px solid #0066cc;"
                f"padding-left:10px'>{line[3:]}</h3>"
            )
        elif line.startswith("**Why:**"):
            rows.append(f"<p style='margin:3px 0;color:#333'>{line}</p>")
        elif line.startswith("**Gap:**"):
            rows.append(f"<p style='margin:3px 0;color:#c0392b'>{line}</p>")
        elif line.startswith("**Source:**"):
            rows.append(f"<p style='margin:2px 0;font-size:12px;color:#888'>{line}</p>")
        elif line.startswith("**Apply:**"):
            url = line.replace("**Apply:** ", "").strip()
            rows.append(
                f"<p style='margin:4px 0 12px'>"
                f"<a href='{url}' style='color:#0066cc;font-weight:500'>→ Apply Now</a></p>"
            )
        elif line.strip():
            rows.append(f"<p style='color:#555;margin:3px 0'>{line}</p>")

    error_block = (
        f"<p style='color:#c0392b;font-size:12px'>⚠️ Sources with issues: {', '.join(errors)}</p>"
        if errors else ""
    )

    html = f"""
    <div style='font-family:sans-serif;max-width:680px;margin:auto;padding:16px'>
      <div style='background:#0d1b2a;color:white;padding:14px 18px;border-radius:8px;margin-bottom:16px'>
        <h2 style='margin:0;font-size:18px'>🎯 Job Radar — {datetime.now().strftime('%d %b %Y')}</h2>
        <p style='margin:4px 0 0;font-size:13px;opacity:.8'>
          {total} jobs reviewed · RemoteOK · WeWorkRemotely · WorkingNomads
        </p>
      </div>
      {''.join(rows)}
      {error_block}
      <hr style='border:none;border-top:1px solid #eee;margin:20px 0'>
      <p style='font-size:11px;color:#aaa'>Next: open each link → use Claude browser plugin to review + apply.</p>
    </div>
    """

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": "onboarding@resend.dev",
            "to": os.environ["MY_EMAIL"].split(","),
            "subject": f"🎯 Job Radar {datetime.now().strftime('%d %b')} — {total} reviewed",
            "html": html,
        },
        timeout=15,
    )
    print(f"Email sent: {resp.status_code}")
    resp.raise_for_status()


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    jobs, errors = fetch_all_jobs()
    filtered = filter_with_llm(jobs)
    send_email(filtered, errors, len(jobs))
