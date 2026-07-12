"""
queue_manager.py
Tracks today's thought queue + posted state, same pattern as your
seen_jobs.json dedup logic in job_radar.py. Prevents double-posting
if a cron run overlaps or retries.
"""

import json
import os
from datetime import date

STATE_FILE = os.path.join(os.path.dirname(__file__), "state", "queue.json")


def _today():
    return date.today().isoformat()


def load_queue():
    if not os.path.exists(STATE_FILE):
        return {"date": _today(), "thoughts": [], "posted_count": 0}
    with open(STATE_FILE, "r") as f:
        data = json.load(f)
    if data.get("date") != _today():
        # new day -> reset queue, force regeneration
        return {"date": _today(), "thoughts": [], "posted_count": 0}
    return data


def save_queue(data):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def needs_generation(data, target_per_day=4):
    return len(data["thoughts"]) == 0


def next_unposted(data):
    for item in data["thoughts"]:
        if not item.get("posted"):
            return item
    return None


def mark_posted(data, thought_id, media_id):
    for item in data["thoughts"]:
        if item["id"] == thought_id:
            item["posted"] = True
            item["media_id"] = media_id
    data["posted_count"] += 1
    save_queue(data)


if __name__ == "__main__":
    # SELF-TEST
    q = load_queue()
    print("Loaded:", q)
    print("Needs generation:", needs_generation(q))
