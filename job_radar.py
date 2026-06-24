"""
job_radar.py
─────────────────────────────────────────────────────────────────────────────
Mirrors build-send-email.py exactly:
  - same Groq call  (GROQ_API_KEY_FOR_AUTO_EMAIL)
  - same Resend call (RESEND_API_KEY, MY_EMAIL)
  - add to .github/workflows/job-radar.yml with cron '30 1 * * *'

pip install: requests feedparser beautifulsoup4  (add to workflow step)

PLATFORMS                   JOBS     METHOD
──────────────────────────────────────────────────────
RemoteOK                    ~1,600   Public JSON API  — no key
WeWorkRemotely              ~40,000  Public RSS feeds — no key
Working Nomads              ~5,000   Public JSON API  — no key
Remote100K                  ~600     HTML scrape      — fragile, $100K+ only
──────────────────────────────────────────────────────
"""

import os
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ─── Candidate profile injected into LLM prompt ─────────────────────────────
PROFILE = """
UI Solution Architect, 17+ yrs exp.
Stack: Angular, TypeScript, PrimeNG, ag-Grid, Spring Boot, Java 8, Oracle, OpenShift.
Led centralised Angular component library consumed by 40+ apps.
Ran SARC governance forum. AWS Solutions Architect Associate certified.
Targeting: Senior UI Architect / Frontend Architect / Technical Lead (UI) — REMOTE ONLY.
Preferred sectors: Banking GCC, fintech, product companies. Open to global remote.
NOT relevant: pure backend, DevOps, QA, junior/mid, on-site/hybrid India.
"""

# ─── Keyword pre-filter (runs before LLM — keeps cost low) ─────────────────
KEYWORDS = [
    "angular", "typescript", "frontend architect", "ui architect",
    "solution architect", "component library", "design system",
    "tech lead", "technical lead", "senior frontend", "principal engineer",
    "staff engineer", "react architect", "vue architect", "web architect",
]

# 48 h window — jobs post less frequently than news
CUTOFF = datetime.now(timezone.utc) - timedelta(hours=48)


def _relevant(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in KEYWORDS)


# ─── SOURCE 1: RemoteOK ─────────────────────────────────────────────────────
# Docs: https://remoteok.com/api   (public, no key, item[0] = legal metadata)
def fetch_remoteok(limit: int = 10) -> list[dict]:
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "job-radar/1.0 (personal job search)"},
            timeout=15,
        )
        r.raise_for_status()
        jobs = []
        for item in r.json()[1:]:                    # skip metadata at index 0
            title = item.get("position", "")
            tags  = " ".join(item.get("tags", []))
            if not _relevant(title + " " + tags):
                continue
            jobs.append({
                "source": "RemoteOK",
                "title": f"{title} @ {item.get('company', '?')}",
                "link":  item.get("url") or f"https://remoteok.com/jobs/{item.get('id','')}",
                "salary": item.get("salary", ""),
                "tags":  tags,
            })
            if len(jobs) >= limit:
                break
        print(f"  RemoteOK: {len(jobs)} matched")
        return jobs
    except Exception as e:
        print(f"  RemoteOK ERROR: {e}")
        return []


# ─── SOURCE 2: WeWorkRemotely ────────────────────────────────────────────────
# Public RSS per category — blessed by WWR (weworkremotely.com/remote-job-rss-feed)
WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]

def fetch_weworkremotely(limit: int = 10) -> list[dict]:
    jobs, seen = [], set()
    for feed_url in WWR_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                link  = entry.get("link", "")
                title = entry.get("title", "")
                if link in seen:
                    continue
                if not _relevant(title + " " + entry.get("summary", "")):
                    continue
                pub = entry.get("published_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < CUTOFF:
                        continue
                seen.add(link)
                jobs.append({
                    "source": "WeWorkRemotely",
                    "title": title,
                    "link":  link,
                    "salary": "",
                    "tags":  "",
                })
                if len(jobs) >= limit:
                    print(f"  WeWorkRemotely: {len(jobs)} matched")
                    return jobs
        except Exception as e:
            print(f"  WWR feed error ({feed_url}): {e}")
    print(f"  WeWorkRemotely: {len(jobs)} matched")
    return jobs


# ─── SOURCE 3: Working Nomads ────────────────────────────────────────────────
# Docs: https://www.workingnomads.com/api  (public, no key)
def fetch_workingnomads(limit: int = 10) -> list[dict]:
    try:
        r = requests.get(
            "https://www.workingnomads.com/api/exposed_jobs/?category=development",
            timeout=15,
        )
        r.raise_for_status()
        jobs = []
        for item in r.json():
            title   = item.get("title", "")
            company = item.get("company_name", "?")
            if not _relevant(title):
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
                "title": f"{title} @ {company}",
                "link":  item.get("url", ""),
                "salary": "",
                "tags":  "",
            })
            if len(jobs) >= limit:
                break
        print(f"  WorkingNomads: {len(jobs)} matched")
        return jobs
    except Exception as e:
        print(f"  WorkingNomads ERROR: {e}")
        return []


# ─── SOURCE 4: Remote100K ────────────────────────────────────────────────────
# ⚠️  Site is JS-rendered (Next.js). BeautifulSoup will likely return 0 results.
# Kept as graceful fallback — will self-report if empty. No crash.
def fetch_remote100k(limit: int = 10) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
        r = requests.get(
            "https://remote100k.com/jobs",
            headers={"User-Agent": "job-radar/1.0"},
            timeout=15,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        jobs = []
        # Selector targets any <a> pointing to a job detail page
        for card in soup.select("a[href*='/jobs/']")[:60]:
            title = card.get_text(strip=True)
            href  = card.get("href", "")
            if not href.startswith("http"):
                href = "https://remote100k.com" + href
            if not title or not _relevant(title):
                continue
            jobs.append({
                "source": "Remote100K",
                "title": title,
                "link":  href,
                "salary": "$100K+ verified",
                "tags":  "$100K+",
            })
            if len(jobs) >= limit:
                break
        note = "0 (JS-rendered site — consider skipping)" if not jobs else str(len(jobs))
        print(f"  Remote100K: {note} matched")
        return jobs
    except Exception as e:
        print(f"  Remote100K ERROR (expected if JS-rendered): {e}")
        return []


# ─── Aggregate + dedup ───────────────────────────────────────────────────────
def fetch_all_jobs() -> tuple[list[dict], list[str]]:
    print("Fetching jobs...")
    sources = [
        ("RemoteOK",       fetch_remoteok),
        ("WeWorkRemotely", fetch_weworkremotely),
        ("WorkingNomads",  fetch_workingnomads),
        ("Remote100K",     fetch_remote100k),
    ]
    all_jobs, errors = [], []
    for name, fn in sources:
        results = fn()
        if not results:
            errors.append(name)
        all_jobs.extend(results)

    # Dedup by link
    seen, deduped = set(), []
    for j in all_jobs:
        if j["link"] and j["link"] not in seen:
            seen.add(j["link"])
            deduped.append(j)

    print(f"Total unique matched: {len(deduped)}")
    return deduped, errors


# ─── LLM filter — same Groq call as build-send-email.py ─────────────────────
def filter_with_llm(jobs: list[dict]) -> str:
    if not jobs:
        return "No matching jobs found in the last 48 hours across all sources."

    job_list = "\n".join(
        f"[{i+1}] [{j['source']}] {j['title']}"
        f"{' | ' + j['salary'] if j['salary'] else ''}"
        f" | {j['link']}"
        for i, j in enumerate(jobs)
    )

    prompt = (
        f"Candidate profile:\n{PROFILE}\n\n"
        "From the list below, select the TOP 10 best matches for this candidate. "
        "Score each 0-100 for fit. "
        "Output ONLY this exact format per job, sorted score descending:\n\n"
        "## [NN/100] Job Title @ Company\n"
        "**Source:** platform name\n"
        "**Why:** one sentence — which specific skills match and why this role fits\n"
        "**Gap:** one skill/requirement missing (or 'None')\n"
        "**Apply:** URL\n\n"
        "Exclude pure backend, DevOps, junior, and non-remote roles entirely. "
        "Be strict — score below 50 = exclude.\n\n"
        f"JOB LIST:\n{job_list}"
    )

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY_FOR_AUTO_EMAIL']}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,        # low temp = consistent scoring
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ─── Email — same Resend call as build-send-email.py ────────────────────────
def send_email(body_md: str, errors: list[str], total: int):
    # Simple markdown → HTML (mirrors existing pattern)
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
        f"<p style='color:#c0392b'>⚠️ Sources with issues: {', '.join(errors)}</p>"
        if errors else ""
    )

    html = f"""
    <div style='font-family:sans-serif;max-width:680px;margin:auto;padding:16px'>
      <div style='background:#0d1b2a;color:white;padding:14px 18px;border-radius:8px;margin-bottom:16px'>
        <h2 style='margin:0;font-size:18px'>🎯 Job Radar — {datetime.now().strftime('%d %b %Y')}</h2>
        <p style='margin:4px 0 0;font-size:13px;opacity:.8'>
          {total} keyword-matched jobs scanned across RemoteOK · WeWorkRemotely · WorkingNomads · Remote100K
        </p>
      </div>
      {''.join(rows)}
      {error_block}
      <hr style='border:none;border-top:1px solid #eee;margin:20px 0'>
      <p style='font-size:11px;color:#aaa'>
        Next step: open each link → use Claude browser plugin to review + apply.
      </p>
    </div>
    """

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": "onboarding@resend.dev",
            "to": os.environ["MY_EMAIL"].split(","),
            "subject": f"🎯 Job Radar {datetime.now().strftime('%d %b')} — {total} scanned",
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
