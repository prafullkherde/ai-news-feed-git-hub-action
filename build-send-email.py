import os
import requests
import feedparser
from datetime import datetime, timedelta, timezone

SOURCES = {
    "Hacker News": "https://hnrss.org/frontpage",
    "Angular Blog": "https://blog.angular.dev/feed",
}

CUTOFF = datetime.now(timezone.utc) - timedelta(hours=24)

def fetch_items():
    items = []
    for name, url in SOURCES.items():
        feed = feedparser.parse(url)
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
    return items

def build_email_html(items):
    if not items:
        return "<p>No new items in the last 24 hours.</p>"
    html = "<h2>Daily Digest</h2>"
    for it in items[:10]:
        html += f'<p><b>[{it["source"]}]</b> <a href="{it["link"]}">{it["title"]}</a></p>'
    return html

def send_email(html_body):
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": "onboarding@resend.dev",
            "to": [os.environ["MY_EMAIL"]],
            "subject": f"Daily Digest - {datetime.now().strftime('%d %b %Y')}",
            "html": html_body,
        },
    )
    print("Status:", resp.status_code)
    print("Response:", resp.text)
    resp.raise_for_status()
    print("Email sent:", resp.status_code)

if __name__ == "__main__":
    items = fetch_items()
    html = build_email_html(items)
    send_email(html)
