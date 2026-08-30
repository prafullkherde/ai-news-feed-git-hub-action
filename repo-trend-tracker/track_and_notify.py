"""
GitHub repo trend tracker + notifier.
Base pattern (fetch -> filter_with_llm -> send_email) taken from build-send-email.py.

Run twice a week via GitHub Actions. Every run:
  1. Discovers candidate repos (trending RSS + OSSInsight trends API + search API + seed watchlist).
  2. Snapshots stars/forks/contributors for each -> appends to data/snapshots.csv.
  3. Computes star velocity per repo from history -> classifies lifecycle phase
     (Birth -> Discovery -> Early Signal -> Breakout -> Popularizing -> Popular ->
     Saturation -> Maintenance -> Unmaintained).
  4. Cross-checks breakout/popularizing repos against HN, Reddit, GitHub Trending,
     new releases, fork-of-popular-project, and a star-manipulation heuristic.
  5. Asks Groq to pick a WHY category from a fixed taxonomy, grounded only in that evidence.
  6. Builds a contributor-overlap map (who shows up across multiple growing repos).
  7. Emails a digest (only repos whose phase changed since the last email).
  8. Writes dashboard/data.json for the static dashboard (history capped, see MAX_HISTORY_POINTS).

Evergreen reference: discovery partly rides on the OSSInsight public API
(https://api.ossinsight.io — see github.com/wangzuo/ossinsight), which already
aggregates 5B+ GitHub events into trending/growth data — no point re-deriving that
part ourselves. The star-manipulation heuristic here is a cheap proxy inspired by
the StarScout methodology (arxiv 2412.13459) — velocity spike with near-zero
fork/issue movement — not a real lockstep/low-activity detector; treat it as a flag
to look closer at, not a verdict.
"""
import os
import csv
import json
import time
import feedparser
import requests
from datetime import datetime, timezone

GITHUB_API = "https://api.github.com"
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")  # Actions injects this automatically, no secret needed
HEADERS = {"Accept": "application/vnd.github+json"}
if GH_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GH_TOKEN}"

ROOT = os.path.dirname(os.path.abspath(__file__))
SNAPSHOTS_CSV = os.path.join(ROOT, "data", "snapshots.csv")
WATCHLIST_SEED = os.path.join(ROOT, "data", "watchlist_seed.json")
NOTIFIED_JSON = os.path.join(ROOT, "data", "notified.json")
DASHBOARD_DATA = os.path.join(ROOT, "dashboard", "data.json")

TRENDING_RSS = "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml"
OSSINSIGHT_API = "https://api.ossinsight.io/v1"

FAST_GROWTH_STARS_PER_DAY = 10        # crossing this = Breakout
UNMAINTAINED_DAYS = 180                # no push in this many days -> dead
BIRTH_DAYS = 21                        # younger than this -> Birth
DISCOVERY_STAR_CAP = 100               # below this star count -> still Discovery
MAX_CANDIDATES_PER_RUN = 45            # rate-limit / noise guard
MAX_HISTORY_POINTS = 150               # ~1.5yr at 2x/week — keeps dashboard/data.json light

WHY_TAXONOMY = [
    "new_feature", "new_release", "viral_social_post", "influencer_mention",
    "ai_integration", "benchmark_result", "company_adoption", "trending_technology",
    "tutorial_or_video", "dependency_ecosystem_change", "fork_of_popular_project",
    "possible_star_manipulation", "unclear",
]

CSV_FIELDS = [
    "date", "full_name", "stars", "forks", "open_issues",
    "created_at", "pushed_at", "top_contributors",
]

RUN_ERRORS = []          # collected across the whole run, mailed + written to data/health.json
HEALTH_JSON = os.path.join(ROOT, "data", "health.json")
MAX_HEALTH_RUNS = 20      # bounded log — old entries roll off


def _note_error(msg):
    RUN_ERRORS.append(msg)
    print("ISSUE:", msg)


def _rate_limited(resp):
    """True + records an error if this response is a GitHub primary rate-limit hit."""
    if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = resp.headers.get("X-RateLimit-Reset", "?")
        _note_error(f"GitHub API rate limit hit (resets at epoch {reset}) — remaining candidates skipped this run")
        return True
    return False


# ---------- discovery ----------

def repos_from_trending_rss():
    names = set()
    try:
        feed = feedparser.parse(TRENDING_RSS)
        for entry in feed.entries:
            link = entry.get("link", "")
            if "github.com/" in link:
                path = link.split("github.com/")[-1].strip("/")
                parts = path.split("/")
                if len(parts) >= 2:
                    names.add(f"{parts[0]}/{parts[1]}")
    except Exception:
        pass
    return names


def repos_from_search():
    """New repos gaining stars fast, via GitHub Search API."""
    names = set()
    try:
        cutoff = (datetime.now(timezone.utc).date().isoformat())
        # repos created in last 30 days with real traction
        thirty_days_ago = (datetime.now(timezone.utc).timestamp() - 30 * 86400)
        thirty_days_ago = datetime.fromtimestamp(thirty_days_ago, tz=timezone.utc).date().isoformat()
        q = f"created:>{thirty_days_ago} stars:>50"
        resp = requests.get(
            f"{GITHUB_API}/search/repositories",
            headers=HEADERS,
            params={"q": q, "sort": "stars", "order": "desc", "per_page": 25},
            timeout=20,
        )
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                names.add(item["full_name"])
    except Exception:
        pass
    return names


def repos_from_ossinsight():
    """Verified endpoint pattern: GET /v1/trends/repos?language=All&period=past_week
    (see github.com/wangzuo/ossinsight for the project this API backs)."""
    names = set()
    try:
        resp = requests.get(
            f"{OSSINSIGHT_API}/trends/repos",
            params={"language": "All", "period": "past_week"},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code == 200:
            for row in resp.json().get("data", {}).get("rows", []):
                name = row.get("repo_name")
                if name:
                    names.add(name)
    except Exception:
        pass
    return names


def load_watchlist_seed():
    """Supports both the old flat-array schema and the new
    {"always_track": [...], "topics_of_interest": [...]} schema."""
    if not os.path.exists(WATCHLIST_SEED):
        return set(), []
    try:
        with open(WATCHLIST_SEED) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _note_error(f"watchlist_seed.json unreadable: {e}")
        return set(), []
    if isinstance(data, list):          # legacy flat array — still works
        return set(data), []
    always = set(data.get("always_track", []))
    topics = data.get("topics_of_interest", [])
    return always, topics


def repos_from_topics(topics):
    """One GitHub search per topic of interest, newest-active-first, so discovery
    leans toward what you actually track (Angular/Spring/K8s/AI) instead of pure noise."""
    names = set()
    for topic in topics:
        try:
            resp = requests.get(
                f"{GITHUB_API}/search/repositories",
                headers=HEADERS,
                params={"q": f"topic:{topic} pushed:>{_days_ago_iso(14)}", "sort": "stars", "order": "desc", "per_page": 10},
                timeout=20,
            )
            if _rate_limited(resp):
                break
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    names.add(item["full_name"])
        except requests.RequestException as e:
            _note_error(f"repos_from_topics({topic}): {e}")
    return names


def _days_ago_iso(days):
    ts = datetime.now(timezone.utc).timestamp() - days * 86400
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def previously_tracked_repos():
    if not os.path.exists(SNAPSHOTS_CSV):
        return set()
    names = set()
    with open(SNAPSHOTS_CSV) as f:
        for row in csv.DictReader(f):
            names.add(row["full_name"])
    return names


def discover_candidates():
    always_track, topics = load_watchlist_seed()
    priority = always_track | previously_tracked_repos()  # never truncated away
    discovered = (
        repos_from_trending_rss()
        | repos_from_ossinsight()
        | repos_from_search()
        | repos_from_topics(topics)
    ) - priority
    remaining_budget = max(MAX_CANDIDATES_PER_RUN - len(priority), 0)
    return list(priority) + list(discovered)[:remaining_budget]


# ---------- snapshotting ----------

def get_repo_stats(full_name):
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{full_name}", headers=HEADERS, timeout=15)
        if _rate_limited(resp):
            return "RATE_LIMITED"
        if resp.status_code != 200:
            return None
        d = resp.json()
        return {
            "stars": d.get("stargazers_count", 0),
            "forks": d.get("forks_count", 0),
            "open_issues": d.get("open_issues_count", 0),
            "created_at": d.get("created_at", ""),
            "pushed_at": d.get("pushed_at", ""),
            "description": d.get("description") or "",
        }
    except requests.RequestException as e:
        _note_error(f"get_repo_stats({full_name}): {e}")
        return None


BOT_SUFFIX = "[bot]"  # GitHub's own convention for bot accounts (dependabot[bot], renovate[bot], ...)


def get_top_contributors(full_name, limit=5):
    """Fetches more than `limit` and filters bots out before truncating, so a repo whose
    top-5 by raw commit count is 3 bots + 2 humans still returns up to 5 real humans."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{full_name}/contributors",
            headers=HEADERS,
            params={"per_page": min(limit * 4, 30)},
            timeout=15,
        )
        if resp.status_code == 202:
            return []  # GitHub still computing contributor stats for this repo — try next run
        if resp.status_code != 200:
            return []
        logins = [c["login"] for c in resp.json() if "login" in c and not c["login"].endswith(BOT_SUFFIX)]
        return logins[:limit]
    except requests.RequestException as e:
        _note_error(f"get_top_contributors({full_name}): {e}")
        return []


def append_snapshot(row):
    try:
        is_new = not os.path.exists(SNAPSHOTS_CSV)
        os.makedirs(os.path.dirname(SNAPSHOTS_CSV), exist_ok=True)
        with open(SNAPSHOTS_CSV, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    except OSError as e:
        _note_error(f"append_snapshot({row.get('full_name')}): {e}")


def snapshot_all(candidates):
    today = datetime.now(timezone.utc).date().isoformat()
    descriptions = {}
    for full_name in candidates:
        stats = get_repo_stats(full_name)
        if stats == "RATE_LIMITED":
            break  # stop burning calls; already-fetched repos this run are still saved below
        if not stats:
            continue
        contributors = get_top_contributors(full_name)
        descriptions[full_name] = stats["description"]
        append_snapshot({
            "date": today,
            "full_name": full_name,
            "stars": stats["stars"],
            "forks": stats["forks"],
            "open_issues": stats["open_issues"],
            "created_at": stats["created_at"],
            "pushed_at": stats["pushed_at"],
            "top_contributors": ";".join(contributors),
        })
        time.sleep(0.3)  # be polite to the API
    return descriptions


# ---------- velocity + lifecycle ----------

def load_history():
    """full_name -> sorted list of snapshot dicts. Skips rows with an unparseable date
    instead of letting one corrupt row crash the whole run."""
    history = {}
    if not os.path.exists(SNAPSHOTS_CSV):
        return history
    try:
        with open(SNAPSHOTS_CSV) as f:
            for row in csv.DictReader(f):
                try:
                    datetime.fromisoformat(row["date"])  # validate before keeping
                    int(row["stars"]); int(row["forks"]); int(row["open_issues"])
                except (ValueError, KeyError, TypeError):
                    continue
                history.setdefault(row["full_name"], []).append(row)
    except OSError:
        return {}
    for name in history:
        history[name].sort(key=lambda r: r["date"])
    return history


def _days_between(d1, d2):
    a = datetime.fromisoformat(d1).date()
    b = datetime.fromisoformat(d2).date()
    return max((b - a).days, 1)


def compute_velocities(rows):
    """stars/day between each consecutive pair of snapshots."""
    velocities = []
    for i in range(1, len(rows)):
        days = _days_between(rows[i - 1]["date"], rows[i]["date"])
        delta = int(rows[i]["stars"]) - int(rows[i - 1]["stars"])
        velocities.append(delta / days)
    return velocities


def classify_phase(rows):
    """
    Birth -> Discovery -> Early Signal -> Breakout -> Popularizing -> Popular
                                                            -> Saturation -> Maintenance -> Unmaintained
    Breakout/Popularizing are the two phases that trigger notification + causality lookup.
    """
    if len(rows) < 2:
        return "Birth"

    latest = rows[-1]
    try:
        created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
        pushed = datetime.fromisoformat(latest["pushed_at"].replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).days
        pushed_days_ago = (datetime.now(timezone.utc) - pushed).days
    except Exception:
        age_days, pushed_days_ago = 999, 0

    if pushed_days_ago > UNMAINTAINED_DAYS:
        return "Unmaintained"
    if age_days < BIRTH_DAYS:
        return "Birth"

    stars = int(latest["stars"])
    v = compute_velocities(rows)
    last_v = v[-1]
    prev_v = v[-2] if len(v) >= 2 else last_v

    if stars < DISCOVERY_STAR_CAP:
        return "Discovery"
    if last_v >= FAST_GROWTH_STARS_PER_DAY:
        return "Breakout" if prev_v < FAST_GROWTH_STARS_PER_DAY else "Popularizing"
    if last_v > prev_v and last_v > 0:
        return "Early Signal"
    if abs(last_v) <= 1 and prev_v > FAST_GROWTH_STARS_PER_DAY / 2:
        return "Saturation"
    if last_v > 1:
        return "Popular"
    return "Maintenance"


def find_fast_growers(history):
    """Repos currently in Breakout or Popularizing — the only phases worth a causality lookup + email."""
    fast = {}
    for full_name, rows in history.items():
        if len(rows) < 2:
            continue
        phase = classify_phase(rows)
        if phase in ("Breakout", "Popularizing"):
            v = compute_velocities(rows)
            fast[full_name] = {
                "velocity": round(v[-1], 1),
                "phase": phase,
                "stars": rows[-1]["stars"],
                "contributors": rows[-1]["top_contributors"].split(";") if rows[-1]["top_contributors"] else [],
            }
    return fast


# ---------- notification dedupe ----------

def load_notified():
    if os.path.exists(NOTIFIED_JSON):
        try:
            with open(NOTIFIED_JSON) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}  # corrupt file -> treat as empty rather than crash the run
    return {}


def save_notified(notified):
    os.makedirs(os.path.dirname(NOTIFIED_JSON), exist_ok=True)
    with open(NOTIFIED_JSON, "w") as f:
        json.dump(notified, f, indent=2)


def filter_unnotified(fast_growers, notified):
    """Only re-notify if the repo's phase has changed since last email."""
    fresh = {}
    for name, info in fast_growers.items():
        if notified.get(name) != info["phase"]:
            fresh[name] = info
    return fresh


# ---------- validation: news / trending corroboration ----------

def hn_mentions(repo_short_name):
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": repo_short_name, "tags": "story"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        hits = resp.json().get("hits", [])
        if not hits:
            return None
        top = hits[0]
        return {"title": top.get("title"), "points": top.get("points"), "url": top.get("url")}
    except Exception:
        return None


def reddit_mentions(repo_short_name):
    try:
        resp = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": repo_short_name, "sort": "new", "limit": 5},
            headers={"User-Agent": "repo-trend-tracker/1.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        posts = resp.json().get("data", {}).get("children", [])
        if not posts:
            return None
        top = posts[0]["data"]
        return {"title": top.get("title"), "subreddit": top.get("subreddit"), "score": top.get("score")}
    except Exception:
        return None


def release_signal(full_name):
    """Was there a release in the last 14 days? Correlates spikes with 'new_release'."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{full_name}/releases", headers=HEADERS, params={"per_page": 1}, timeout=10
        )
        if resp.status_code != 200:
            return None
        releases = resp.json()
        if not releases:
            return None
        published = releases[0].get("published_at")
        if not published:
            return None
        days_ago = (datetime.now(timezone.utc) - datetime.fromisoformat(published.replace("Z", "+00:00"))).days
        if days_ago <= 14:
            return {"tag": releases[0].get("tag_name", "?"), "days_ago": days_ago}
        return None
    except Exception:
        return None


def fork_signal(full_name):
    """GitHub's own API tells us directly if this is a fork of an already-popular repo."""
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{full_name}", headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        d = resp.json()
        parent = d.get("parent") or {}
        if d.get("fork") and parent.get("stargazers_count", 0) > 1000:
            return f"fork of {parent.get('full_name')} ({parent.get('stargazers_count')}★)"
        return None
    except Exception:
        return None


def star_manipulation_flag(rows):
    """Cheap heuristic only (see module docstring) — big star jump with ~zero fork/issue
    movement in the same window. Flags for a closer look, does not prove manipulation."""
    if len(rows) < 2:
        return False
    stars_delta = int(rows[-1]["stars"]) - int(rows[-2]["stars"])
    forks_delta = int(rows[-1]["forks"]) - int(rows[-2]["forks"])
    issues_delta = int(rows[-1]["open_issues"]) - int(rows[-2]["open_issues"])
    return stars_delta > 50 and forks_delta == 0 and issues_delta == 0


def validate_growers(fast_growers, trending_now, history):
    """Gathers the external-signal evidence the diagram calls the 'causality engine' input."""
    evidence = {}
    for full_name in fast_growers:
        short = full_name.split("/")[-1]
        ev = []
        if full_name in trending_now:
            ev.append("on GitHub Trending")
        hn = hn_mentions(short)
        if hn:
            ev.append(f"HN: \"{hn['title']}\" ({hn['points']} pts)")
        rd = reddit_mentions(short)
        if rd:
            ev.append(f"Reddit r/{rd['subreddit']}: \"{rd['title']}\"")
        rel = release_signal(full_name)
        if rel:
            ev.append(f"new release {rel['tag']} ({rel['days_ago']}d ago)")
        fk = fork_signal(full_name)
        if fk:
            ev.append(fk)
        if star_manipulation_flag(history[full_name]):
            ev.append("⚠ star spike with no fork/issue movement")
        evidence[full_name] = "; ".join(ev) if ev else "no external corroboration found — organic growth"
    return evidence


# ---------- LLM reasoning (Groq, same pattern as build-send-email.py) ----------

def llm_reason(fast_growers, evidence, descriptions):
    if not fast_growers:
        return {}
    lines = []
    for name, info in fast_growers.items():
        lines.append(
            f"- {name}: {info['velocity']} stars/day, phase={info['phase']}, "
            f"desc={descriptions.get(name, '')}, evidence={evidence.get(name, '')}"
        )
    prompt = (
        "For each repo below, pick exactly one category from this fixed list: "
        + ", ".join(WHY_TAXONOMY) + ".\n"
        "Output exactly: '- REPO: <category> — one-sentence reason, grounded ONLY in the evidence given. "
        "Never invent facts. If evidence is empty, use category unclear.'\n\n" + "\n".join(lines)
    )
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY_FOR_AUTO_EMAIL']}"},
            json={"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        reasons = {}
        for line in text.splitlines():
            line = line.strip("- ").strip()
            if ":" in line:
                repo, reason = line.split(":", 1)
                reasons[repo.strip()] = reason.strip()  # e.g. "new_release — shipped v2 with GPU support"
        return reasons
    except Exception:
        return {}


# ---------- contributor overlap ----------

GROWING_PHASES = {"Discovery", "Early Signal", "Breakout", "Popularizing", "Popular"}


def contributor_overlap(history):
    """Restricted to repos currently in a growing phase — Maintenance/Saturation/
    Unmaintained/Birth repos (e.g. long-established projects like jhipster or trivy)
    don't belong in a 'growing repos' contributor-overlap section even if they're
    still being tracked for their own lifecycle chart."""
    contrib_to_repos = {}
    for full_name, rows in history.items():
        if classify_phase(rows) not in GROWING_PHASES:
            continue
        latest = rows[-1]
        for c in latest["top_contributors"].split(";"):
            if c and not c.endswith(BOT_SUFFIX):  # defensive — also filtered at source in get_top_contributors
                contrib_to_repos.setdefault(c, set()).add(full_name)
    return {c: sorted(r) for c, r in contrib_to_repos.items() if len(r) >= 2}


# ---------- email ----------

def compose_html(fast_growers, reasons, overlap, dashboard_url, errors):
    parts = [f"<h2>Repo Trend Digest — {datetime.now().strftime('%d %b %Y')}</h2>"]

    if fast_growers:
        parts.append("<h3>🚀 Fast-growing repos</h3><ul>")
        for name, info in fast_growers.items():
            reason = reasons.get(name, "")
            parts.append(
                f"<li><b><a href='https://github.com/{name}'>{name}</a></b> — "
                f"{info['velocity']} stars/day, phase: {info['phase']}, {info['stars']} total stars"
                f"{'<br>' + reason if reason else ''}</li>"
            )
        parts.append("</ul>")
    else:
        parts.append("<p>No new fast-growing repos this run.</p>")

    if overlap:
        parts.append("<h3>🔁 Contributors active across multiple growing repos</h3><ul>")
        for contributor, repos in sorted(overlap.items(), key=lambda kv: -len(kv[1]))[:10]:
            parts.append(f"<li><b>{contributor}</b> — {', '.join(repos)}</li>")
        parts.append("</ul>")

    parts.append(f"<p><a href='{dashboard_url}'>Open the lifecycle dashboard →</a></p>")

    if errors:
        parts.append("<h3>⚠️ Pipeline issues this run</h3><ul>")
        for e in errors:
            parts.append(f"<li style='color:#b00;'>{e}</li>")
        parts.append("</ul>")

    return "".join(parts)


def send_email(html):
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": "onboarding@resend.dev",
            "to": os.environ["MY_EMAIL"].split(","),
            "subject": f"Repo Trend Digest - {datetime.now().strftime('%d %b %Y')}",
            "html": html,
        },
    )
    print("Email status:", resp.status_code, resp.text)
    resp.raise_for_status()


# ---------- dashboard export ----------

def write_dashboard_data(history):
    out = {}
    for full_name, rows in history.items():
        trimmed = rows[-MAX_HISTORY_POINTS:]  # keep data.json light — full history stays in snapshots.csv
        out[full_name] = {
            "phase": classify_phase(rows),
            "history": [{"date": r["date"], "stars": int(r["stars"])} for r in trimmed],
            "contributors": rows[-1]["top_contributors"].split(";") if rows[-1]["top_contributors"] else [],
        }
    os.makedirs(os.path.dirname(DASHBOARD_DATA), exist_ok=True)
    with open(DASHBOARD_DATA, "w") as f:
        json.dump(out, f, indent=2)


# ---------- health / observability ----------

def record_run_health(status, issues):
    entry = {"time": datetime.now(timezone.utc).isoformat(), "status": status, "issues": issues}
    history = []
    if os.path.exists(HEALTH_JSON):
        try:
            with open(HEALTH_JSON) as f:
                history = json.load(f)
        except (json.JSONDecodeError, OSError):
            history = []
    history.append(entry)
    history = history[-MAX_HEALTH_RUNS:]
    try:
        os.makedirs(os.path.dirname(HEALTH_JSON), exist_ok=True)
        with open(HEALTH_JSON, "w") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass  # health logging is itself best-effort — never let it be the thing that crashes a run


# ---------- main ----------

def main():
    global RUN_ERRORS
    RUN_ERRORS = []

    trending_now = repos_from_trending_rss()

    try:
        candidates = discover_candidates()
    except Exception as e:
        _note_error(f"discover_candidates crashed: {e}")
        candidates = []
    if not candidates:
        _note_error("discovery returned nothing this run")

    try:
        descriptions = snapshot_all(candidates)
    except Exception as e:
        _note_error(f"snapshot_all crashed: {e}")
        descriptions = {}

    history = load_history()

    try:
        fast_growers = find_fast_growers(history)
    except Exception as e:
        _note_error(f"find_fast_growers crashed: {e}")
        fast_growers = {}

    notified = load_notified()
    to_notify = filter_unnotified(fast_growers, notified)

    try:
        evidence = validate_growers(to_notify, trending_now, history)
    except Exception as e:
        _note_error(f"validate_growers crashed: {e}")
        evidence = {}

    reasons = llm_reason(to_notify, evidence, descriptions)
    overlap = contributor_overlap(history)

    dashboard_url = os.environ.get(
        "DASHBOARD_URL", "https://<your-username>.github.io/<your-repo>/dashboard/"
    )

    # Send whenever there's something new OR there's a heartbeat OR something went wrong —
    # RUN_ERRORS alone is reason enough to mail, even if nothing else changed this run.
    email_failed = False
    if to_notify or not fast_growers or RUN_ERRORS:
        html = compose_html(to_notify, reasons, overlap, dashboard_url, RUN_ERRORS)
        try:
            send_email(html)
        except Exception as e:
            email_failed = True
            print("Email send failed (data below is still persisted):", e)

    for name, info in to_notify.items():
        notified[name] = info["phase"]
    save_notified(notified)

    write_dashboard_data(history)

    issues = list(RUN_ERRORS) + (["email send failed — see workflow logs"] if email_failed else [])
    record_run_health("ok" if not issues else "issues", issues)

    if email_failed:
        # Data is already safely written above; exit non-zero purely so GitHub Actions'
        # own default failure notification fires as a backstop when our own email is the
        # thing that's broken.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
