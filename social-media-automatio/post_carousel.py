"""
post_carousel.py
⚠️ NOT SELF-TESTED — my sandbox has no route to graph.facebook.com.
This is the correct 3-step Graph API carousel chain (verified against
API shape, not against a live call). You must test this against your
own IG Business account + System User token before trusting it in cron.

Prereqs (your side, one-time):
  1. IG account = Business/Creator, linked to an FB Page
  2. Page + IG asset added to a Meta Business Manager
  3. System User created in Business Manager, token generated with
     scopes: instagram_content_publish, pages_manage_posts, pages_read_engagement
  4. Images must be reachable at a PUBLIC https URL (raw.githubusercontent.com
     from your existing claude-web-artefact repo pattern works fine at this volume)
"""

import os
import requests
import time

GRAPH_VERSION = "v19.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

IG_USER_ID = os.environ["IG_USER_ID"]
PAGE_ID = os.environ["FB_PAGE_ID"]
ACCESS_TOKEN = os.environ["META_SYSTEM_USER_TOKEN"]


def create_child_container(image_url):
    """Step 1: one unpublished container per image, is_carousel_item=true"""
    resp = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media",
        data={
            "image_url": image_url,
            "is_carousel_item": "true",
            "access_token": ACCESS_TOKEN,
        },
    )
    if not resp.ok:
        print(f"META ERROR for {image_url}: {resp.status_code} - {resp.text}")
    resp.raise_for_status()
    return resp.json()["id"]
    """Step 2: parent container referencing all child container IDs"""
    resp = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption,
            "access_token": ACCESS_TOKEN,
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


def publish_container(container_id):
    """Step 3: publish the parent container -> goes live"""
    resp = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": ACCESS_TOKEN},
    )
    resp.raise_for_status()
    return resp.json()["id"]  # this is your media_id -> store in queue_manager


def post_ig_carousel(image_urls, caption):
    """
    Full chain with per-child retry -- one failed child breaks the
    whole carousel silently if you don't check each response (flagged earlier).
    """
    child_ids = []
    for url in image_urls:
        for attempt in range(3):
            try:
                child_ids.append(create_child_container(url))
                break
            except requests.HTTPError as e:
                if attempt == 2:
                    raise RuntimeError(f"Child container failed after 3 tries: {url}") from e
                time.sleep(2)

    parent_id = create_carousel_container(child_ids, caption)
    time.sleep(3)  # Meta needs a moment before publish, container not always instantly ready
    media_id = publish_container(parent_id)
    return media_id


def post_fb_photos(image_paths_or_urls, caption):
    """
    FB Page carousel = simpler: attach multiple photos to one post via
    unpublished photo uploads + attached_media on the feed post.
    """
    attached_media = []
    for url in image_paths_or_urls:
        resp = requests.post(
            f"{BASE_URL}/{PAGE_ID}/photos",
            data={"url": url, "published": "false", "access_token": ACCESS_TOKEN},
        )
        resp.raise_for_status()
        attached_media.append({"media_fbid": resp.json()["id"]})

    resp = requests.post(
        f"{BASE_URL}/{PAGE_ID}/feed",
        json={
            "message": caption,
            "attached_media": attached_media,
            "access_token": ACCESS_TOKEN,
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


if __name__ == "__main__":
    print("This module is not meant to run standalone without real image URLs + token.")
    print("Wire it via run_pipeline.py after you've verified your Business Manager setup.")
