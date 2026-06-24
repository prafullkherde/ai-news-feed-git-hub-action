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

# ─── PATCH for job_radar.py — replace these 4 sections only ─────────────────

# ── 1. Tighten _relevant() — title only, not tags ────────────────────────────
# Tags in RemoteOK are noisy (e.g. "exec", "react" on a Manufacturing job).
# Title is the only reliable signal at pre-filter stage.

KEYWORDS = [
    "angular", "typescript", "frontend architect", "ui architect",
    "solution architect", "component library", "design system",
    "tech lead", "technical lead", "senior frontend", "principal engineer",
    "staff engineer", "react architect", "web architect", "frontend lead",
    "ui lead", "front end", "front-end architect",
]

def _relevant(title: str) -> bool:          # ← only title now, no tags arg
    t = title.lower()
    return any(k in t for k in KEYWORDS)


# ── 2. RemoteOK — filter at API level, not post-fetch ────────────────────────
# remoteok.com/api?tags=X returns only jobs tagged X. Much cleaner.
# Multiple tags = OR logic on their side.

REMOTEOK_TAG_URLS = [
    "https://remoteok.com/api?tags=angular",
    "https://remoteok.com/api?tags=typescript",
    "https://remoteok.com/api?tags=frontend",
    "https://remoteok.com/api?tags=architect",
]

def fetch_remoteok(limit: int = 10) -> list[dict]:
    jobs, seen = [], set()
    for url in REMOTEOK_TAG_URLS:
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "job-radar/1.0 (personal job search)"},
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json()[1:]:               # item[0] = legal metadata
                job_id = str(item.get("id", ""))
                if job_id in seen:
                    continue
                title = item.get("position", "")
                if not _relevant(title):            # title-only check now
                    continue
                seen.add(job_id)
                jobs.append({
                    "source": "RemoteOK",
                    "title": f"{title} @ {item.get('company', '?')}",
                    "link":  item.get("url") or f"https://remoteok.com/jobs/{job_id}",
                    "salary": item.get("salary", ""),
                    "tags":  " ".join(item.get("tags", [])),
                })
        except Exception as e:
            print(f"  RemoteOK error ({url}): {e}")

    jobs = jobs[:limit]
    print(f"  RemoteOK: {len(jobs)} matched")
    return jobs


# ── 3. WeWorkRemotely — add User-Agent header to feedparser ──────────────────
# feedparser without UA gets 403 or bozo=True from WWR in 2026.

WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]

UA_HEADERS = {"User-Agent": "Mozilla/5.0 (job-radar/1.0; personal job search)"}

def fetch_weworkremotely(limit: int = 10) -> list[dict]:
    jobs, seen = [], set()
    for feed_url in WWR_FEEDS:
        try:
            feed = feedparser.parse(feed_url, request_headers=UA_HEADERS)
            if feed.bozo and not feed.entries:
                print(f"  WWR bozo error ({feed_url}): {feed.bozo_exception}")
                continue
            print(f"  WWR feed {feed_url}: {len(feed.entries)} entries")
            for entry in feed.entries:
                link  = entry.get("link", "")
                title = entry.get("title", "")
                if link in seen:
                    continue
                if not _relevant(title):            # title only
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
            print(f"  WWR error ({feed_url}): {e}")
    print(f"  WeWorkRemotely: {len(jobs)} matched")
    return jobs


# ── 4. WorkingNomads — add UA + print raw status for debugging ───────────────

def fetch_workingnomads(limit: int = 10) -> list[dict]:
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
    send_email(filtered, errors, len(jobs))
