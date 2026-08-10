"""
test_image_apis.py
Tests 6 image-generation candidates in one run. Each is independent --
one failing doesn't stop the others. Candidates needing an API key that
isn't set are SKIPPED (not failed) so you can run this today with zero
signups and add more coverage later.

Same test prompt across all 6, so outputs are genuinely comparable.
"""

import os
import requests
import urllib.parse
import json

PROMPT_TEXT = (
    "Studio Ghibli style painterly illustration, cloaked warrior wanderer "
    "standing on a hill, gripping a sword, gazing at a pale blue cloudy sky, "
    "warm earthy medieval clothing, soft muted color palette, anime fantasy art"
)

OUT_DIR = "results"
os.makedirs(OUT_DIR, exist_ok=True)

results = []


def save_and_log(name, resp, filename):
    content_type = resp.headers.get("content-type", "")
    if resp.status_code == 200 and "image" in content_type:
        path = os.path.join(OUT_DIR, filename)
        with open(path, "wb") as f:
            f.write(resp.content)
        results.append({"name": name, "status": "SUCCESS", "size_bytes": len(resp.content), "file": filename})
        print(f"[{name}] SUCCESS -> {filename} ({len(resp.content)} bytes)")
    else:
        snippet = resp.text[:200] if hasattr(resp, "text") else str(resp.content[:200])
        results.append({"name": name, "status": "FAILED", "http_status": resp.status_code, "detail": snippet})
        print(f"[{name}] FAILED -- status {resp.status_code}: {snippet}")


def test_pollinations_v1():
    name = "1_pollinations_image"
    try:
        encoded = urllib.parse.quote(PROMPT_TEXT)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true"
        resp = requests.get(url, timeout=90)
        save_and_log(name, resp, "1_pollinations_image.png")
    except Exception as e:
        results.append({"name": name, "status": "ERROR", "detail": str(e)})
        print(f"[{name}] ERROR: {e}")


def test_pollinations_v2_gen():
    name = "2_pollinations_gen"
    try:
        encoded = urllib.parse.quote(PROMPT_TEXT)
        url = f"https://gen.pollinations.ai/image/{encoded}"
        resp = requests.get(url, timeout=90)
        save_and_log(name, resp, "2_pollinations_gen.png")
    except Exception as e:
        results.append({"name": name, "status": "ERROR", "detail": str(e)})
        print(f"[{name}] ERROR: {e}")


def test_huggingface_flux():
    name = "3_huggingface_flux_schnell"
    key = os.environ.get("HF_TOKEN", "")
    if not key:
        results.append({"name": name, "status": "SKIPPED", "detail": "HF_TOKEN not set"})
        print(f"[{name}] SKIPPED -- set HF_TOKEN to test this one")
        return
    try:
        url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"inputs": PROMPT_TEXT},
            timeout=90,
        )
        save_and_log(name, resp, "3_huggingface_flux.png")
    except Exception as e:
        results.append({"name": name, "status": "ERROR", "detail": str(e)})
        print(f"[{name}] ERROR: {e}")


def test_craiyon():
    name = "4_craiyon"
    try:
        url = "https://api.craiyon.com/v3"
        resp = requests.post(url, json={"prompt": PROMPT_TEXT}, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            images = data.get("images", [])
            if images:
                import base64
                img_bytes = base64.b64decode(images[0])
                path = os.path.join(OUT_DIR, "4_craiyon.jpg")
                with open(path, "wb") as f:
                    f.write(img_bytes)
                results.append({"name": name, "status": "SUCCESS", "file": "4_craiyon.jpg"})
                print(f"[{name}] SUCCESS -> 4_craiyon.jpg")
            else:
                results.append({"name": name, "status": "FAILED", "detail": "no images in response"})
                print(f"[{name}] FAILED -- no images in response")
        else:
            results.append({"name": name, "status": "FAILED", "http_status": resp.status_code})
            print(f"[{name}] FAILED -- status {resp.status_code}")
    except Exception as e:
        results.append({"name": name, "status": "ERROR", "detail": str(e)})
        print(f"[{name}] ERROR: {e}")


def test_deepai():
    name = "5_deepai"
    key = os.environ.get("DEEPAI_API_KEY", "")
    if not key:
        results.append({"name": name, "status": "SKIPPED", "detail": "DEEPAI_API_KEY not set"})
        print(f"[{name}] SKIPPED -- set DEEPAI_API_KEY to test this one")
        return
    try:
        resp = requests.post(
            "https://api.deepai.org/api/text2img",
            data={"text": PROMPT_TEXT},
            headers={"api-key": key},
            timeout=90,
        )
        if resp.status_code == 200:
            image_url = resp.json().get("output_url")
            if image_url:
                img_resp = requests.get(image_url, timeout=60)
                save_and_log(name, img_resp, "5_deepai.png")
            else:
                results.append({"name": name, "status": "FAILED", "detail": "no output_url"})
        else:
            results.append({"name": name, "status": "FAILED", "http_status": resp.status_code})
            print(f"[{name}] FAILED -- status {resp.status_code}")
    except Exception as e:
        results.append({"name": name, "status": "ERROR", "detail": str(e)})
        print(f"[{name}] ERROR: {e}")


def test_stability():
    name = "6_stability_sdxl"
    key = os.environ.get("STABILITY_API_KEY", "")
    if not key:
        results.append({"name": name, "status": "SKIPPED", "detail": "STABILITY_API_KEY not set"})
        print(f"[{name}] SKIPPED -- set STABILITY_API_KEY to test this one")
        return
    try:
        url = "https://api.stability.ai/v2beta/stable-image/generate/core"
        resp = requests.post(
            url,
            headers={"authorization": f"Bearer {key}", "accept": "image/*"},
            files={"none": ""},
            data={"prompt": PROMPT_TEXT, "output_format": "png"},
            timeout=90,
        )
        save_and_log(name, resp, "6_stability_sdxl.png")
    except Exception as e:
        results.append({"name": name, "status": "ERROR", "detail": str(e)})
        print(f"[{name}] ERROR: {e}")


if __name__ == "__main__":
    test_pollinations_v1()
    test_pollinations_v2_gen()
    test_huggingface_flux()
    test_craiyon()
    test_deepai()
    test_stability()

    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    print("\n--- SUMMARY ---")
    for r in results:
        print(f"{r['name']}: {r['status']}")
