"""
run_pipeline.py
Single entry point, triggered 3-4x/day by GitHub Actions cron.
Idempotent: safe to re-run same day, won't double-post (queue_manager guards it).
"""

import os
import uuid
from datetime import date

from queue_manager import load_queue, save_queue, needs_generation, next_unposted, mark_posted
from compose_carousel import render_carousel
from generate_thought import generate_daily_thoughts
from post_carousel import post_ig_carousel, post_fb_photos

# ---- config ----
POSTS_PER_DAY = 4
GITHUB_REPO_RAW_BASE = os.environ.get(
    "IMAGE_HOST_BASE",
    "https://raw.githubusercontent.com/YOUR_USER/claude-web-artefact/main/carousel-images",
)
FB_CAPTION_SUFFIX = "\n\n#discipline #momentum #alignment"


def upload_to_repo(local_paths, thought_id):
    """
    Workflow runs INSIDE claude-web-artefact repo -> actions/checkout already
    provides GITHUB_TOKEN with push rights. No PAT, no rotation needed.
    Subfolder: carousel-images/{thought_id}/ -- separate from your existing
    artefact content, no collision.
    """
    import subprocess
    repo_root = os.environ.get("GITHUB_WORKSPACE", ".")
    dest_dir = os.path.join(repo_root, "carousel-images", thought_id)
    os.makedirs(dest_dir, exist_ok=True)

    urls = []
    for path in local_paths:
        fname = os.path.basename(path)
        subprocess.run(["cp", path, os.path.join(dest_dir, fname)], check=True)
        urls.append(f"{GITHUB_REPO_RAW_BASE}/carousel-images/{thought_id}/{fname}")

    subprocess.run(["git", "add", "carousel-images"], cwd=repo_root, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", f"post: {thought_id}"], cwd=repo_root, capture_output=True
    )
    if result.returncode == 0:  # non-zero = nothing to commit, not a real failure
        subprocess.run(["git", "push"], cwd=repo_root, check=True)
    return urls


def main():
    queue = load_queue()

    if needs_generation(queue, POSTS_PER_DAY):
        thoughts = generate_daily_thoughts(POSTS_PER_DAY)
        queue["thoughts"] = [
            {"id": t.get("id", str(uuid.uuid4())[:8]), "slides": t["slides"], "posted": False}
            for t in thoughts
        ]
        save_queue(queue)

    item = next_unposted(queue)
    if item is None:
        print(f"[{date.today()}] All {POSTS_PER_DAY} thoughts posted. Nothing to do.")
        return

    # 1. render
    out_dir = f"output/{item['id']}"
    local_paths = render_carousel(item["slides"], out_dir)

    # 2. host (public URL required by Graph API)
    public_urls = upload_to_repo(local_paths, item["id"])

    # 3. caption = slide 1 text (hook) + fixed hashtag suffix
    caption = item["slides"][0] + FB_CAPTION_SUFFIX

    # 4. post both platforms
    ig_media_id = post_ig_carousel(public_urls, caption)
    fb_post_id = post_fb_photos(public_urls, caption)

    # 5. mark done, prevents re-post on next cron trigger same day
    mark_posted(queue, item["id"], f"ig:{ig_media_id}|fb:{fb_post_id}")

    print(f"Posted {item['id']} -> IG:{ig_media_id} FB:{fb_post_id}")


if __name__ == "__main__":
    main()
