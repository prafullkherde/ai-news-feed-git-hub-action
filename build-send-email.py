import os
import requests
import feedparser
from datetime import datetime, timedelta, timezone

SOURCES = {
    "Anthropic": "https://www.anthropic.com/news/rss.xml",
    "Angular": "https://blog.angular.dev/feed",
    "AWS": "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
    "Lobsters": "https://lobste.rs/rss",
    "GitHub Trending": "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml",
    "Hacker News": "https://hnrss.org/frontpage",
}

CUTOFF = datetime.now(timezone.utc) - timedelta(hours=24)

def fetch_items():
    items, errors = [], []
    for name, url in SOURCES.items():
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                errors.append(name)
                continue
            for entry in feed.entries:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < CUTOFF:
                        continue
                items.append({
                    "source": name,
                    "title": entry.get("title", "No title"),
                    "link": entry.get("link", ""),
                })
        except Exception:
            errors.append(name)
    return items, errors

def filter_with_llm(items):
    prompt = (
        "From this list of tech news items, select ONLY the 5-8 most relevant "
        "for a Senior UI Solutions Architect (Angular, TypeScript, Java/Spring Boot, "
        "AI/agent tooling, enterprise architecture, AWS). Exclude general tech news, "
        "job postings, opinion pieces, unrelated niche tooling. "
        "For each selected item, output exactly: '- [TITLE](LINK): one-line why it matters'.\n\n"
        + "\n".join(f"- {it['title']} ({it['link']})" for it in items)
    )
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY_FOR_AUTO_EMAIL']}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def send_email(body_md, errors):
    html = f"<pre style='font-family:sans-serif;font-size:14px;'>{body_md}</pre>"
    if errors:
        html += f"<p style='color:red;'>⚠️ Sources with issues: {', '.join(errors)}</p>"
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": "onboarding@resend.dev",
            "to": os.environ["MY_EMAIL"].split(","),
            "subject": f"Daily Digest - {datetime.now().strftime('%d %b %Y')}",
            "html": html,
        },
    )
    print("Status:", resp.status_code, resp.text)
    resp.raise_for_status()

if __name__ == "__main__":
    items, errors = fetch_items()
    if not items:
        send_email("No items found across all sources.", errors)
    else:
        filtered = filter_with_llm(items)
        send_email(filtered, errors)
