"""
test_image_apis.py (v2)
Tests 11 image-generation candidates. Each wrapped in a common runner that
captures: elapsed time, full exception type/detail, response content-type
even on failure (tells us HTML error page vs JSON vs binary), and a
truncated body preview -- enough detail to actually diagnose and fix each
candidate without re-running blind.

Candidates needing a key that isn't set are SKIPPED, not failed.
"""

import os
import time
import json
import base64
import requests
import urllib.parse

PROMPT_TEXT = (
    "Studio Ghibli style painterly illustration, warm semi-realistic anime "
    "fantasy art. A lone young man with a sword strapped to his back stands "
    "atop a stone wall, seen from behind or three-quarter angle, gazing "
    "out at a vast natural landscape. On his left side, in the distance, "
    "a small stone castle sits on a hill. On his right side, further down "
    "below the wall, a modest village with thatched roofs and rising smoke. "
    "Directly in front of him, filling the horizon at eye level, a massive "
    "snow-capped mountain range touches a dramatic sky full of soft clouds. "
    "Warm earthy color palette -- muted greens, browns, and golds -- with "
    "an expressive glowing sky in soft orange and pale blue tones. Natural "
    "wide-angle view, cinematic depth, adventurer/medieval clothing, "
    "painterly brushwork texture, no photorealism, no text, no watermark."
)

NEGATIVE_PROMPT = (
    "text, watermark, signature, photorealistic, 3d render, low quality, "
    "blurry, deformed hands, extra limbs, modern clothing, cartoon, flat colors"
)

OUT_DIR = "results"
os.makedirs(OUT_DIR, exist_ok=True)
results = []


def log_success(name, filename, size_bytes, elapsed, content_type=""):
    results.append({"name": name, "status": "SUCCESS", "file": filename,
                     "size_bytes": size_bytes, "elapsed_seconds": elapsed,
                     "content_type": content_type})
    print(f"[{name}] SUCCESS -> {filename} ({size_bytes} bytes, {elapsed}s)")


def log_failed(name, http_status, content_type, elapsed, body_preview):
    results.append({"name": name, "status": "FAILED", "http_status": http_status,
                     "content_type": content_type, "elapsed_seconds": elapsed,
                     "body_preview": body_preview})
    print(f"[{name}] FAILED -- {http_status} ({content_type}) in {elapsed}s: {body_preview}")


def log_error(name, elapsed, exc):
    results.append({"name": name, "status": "ERROR", "elapsed_seconds": elapsed,
                     "exception_type": type(exc).__name__, "detail": str(exc)})
    print(f"[{name}] ERROR ({type(exc).__name__}) after {elapsed}s: {exc}")


def log_skipped(name, key_env_name):
    results.append({"name": name, "status": "SKIPPED", "detail": f"{key_env_name} not set"})
    print(f"[{name}] SKIPPED -- set {key_env_name} to test this one")


def run_simple(name, key_env_name, fn):
    """For candidates that return (resp, filename) with raw image bytes."""
    key = os.environ.get(key_env_name, "") if key_env_name else "not_needed"
    if key_env_name and not key:
        log_skipped(name, key_env_name)
        return

    start = time.time()
    try:
        resp, filename = fn(key)
        elapsed = round(time.time() - start, 1)
        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 200 and "image" in content_type:
            path = os.path.join(OUT_DIR, filename)
            with open(path, "wb") as f:
                f.write(resp.content)
            log_success(name, filename, len(resp.content), elapsed, content_type)
        else:
            body_preview = resp.text[:300] if hasattr(resp, "text") else str(resp.content[:300])
            log_failed(name, resp.status_code, content_type, elapsed, body_preview)
    except Exception as e:
        log_error(name, round(time.time() - start, 1), e)


def run_self_handled(name, key_env_name, fn):
    """For candidates whose fn() saves its own file (base64 responses) and
    returns nothing -- fn should raise on any failure."""
    key = os.environ.get(key_env_name, "") if key_env_name else "not_needed"
    if key_env_name and not key:
        log_skipped(name, key_env_name)
        return

    start = time.time()
    try:
        fn(key)  # fn logs its own success internally
    except Exception as e:
        log_error(name, round(time.time() - start, 1), e)


# ---- Original 6 ----

def t1_pollinations_image(key):
    encoded = urllib.parse.quote(PROMPT_TEXT)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true"
    return requests.get(url, timeout=90), "1_pollinations_image.png"


def t2_pollinations_gen(key):
    encoded = urllib.parse.quote(PROMPT_TEXT)
    url = f"https://gen.pollinations.ai/image/{encoded}"
    return requests.get(url, timeout=90), "2_pollinations_gen.png"


def t3_huggingface_flux(key):
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    resp = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                          json={"inputs": PROMPT_TEXT,
                                "parameters": {"num_inference_steps": 4}},
                          timeout=90)
    return resp, "3_huggingface_flux.png"


def t4_craiyon(key):
    url = "https://api.craiyon.com/v3"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.post(url, json={"prompt": PROMPT_TEXT}, headers=headers, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"status {resp.status_code}: {resp.text[:300]}")
    images = resp.json().get("images", [])
    if not images:
        raise RuntimeError(f"no images in response: {resp.text[:300]}")
    img_bytes = base64.b64decode(images[0])
    path = os.path.join(OUT_DIR, "4_craiyon.jpg")
    with open(path, "wb") as f:
        f.write(img_bytes)
    log_success("4_craiyon", "4_craiyon.jpg", len(img_bytes), 0)


def t5_deepai(key):
    resp = requests.post("https://api.deepai.org/api/text2img", data={"text": PROMPT_TEXT},
                          headers={"api-key": key}, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"status {resp.status_code}: {resp.text[:300]}")
    image_url = resp.json().get("output_url")
    if not image_url:
        raise RuntimeError(f"no output_url: {resp.text[:300]}")
    return requests.get(image_url, timeout=60), "5_deepai.png"


def t6_stability(key):
    url = "https://api.stability.ai/v2beta/stable-image/generate/core"
    resp = requests.post(url, headers={"authorization": f"Bearer {key}", "accept": "image/*"},
                          files={"none": ""},
                          data={
                              "prompt": PROMPT_TEXT,
                              "negative_prompt": NEGATIVE_PROMPT,
                              "output_format": "png",
                              "style_preset": "fantasy-art",
                              "aspect_ratio": "1:1",
                          },
                          timeout=90)
    return resp, "6_stability_sdxl.png"


# ---- New: 5 more quality-focused candidates ----

def t7_fal_flux(key):
    """fal.ai FLUX.1 dev - known strong quality, real developer API."""
    url = "https://fal.run/fal-ai/flux/dev"
    resp = requests.post(url, headers={"Authorization": f"Key {key}"},
                          json={
                              "prompt": PROMPT_TEXT,
                              "image_size": "square_hd",
                              "num_inference_steps": 35,
                              "guidance_scale": 4.5,
                          }, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"status {resp.status_code}: {resp.text[:300]}")
    image_url = resp.json().get("images", [{}])[0].get("url")
    if not image_url:
        raise RuntimeError(f"no image url: {resp.text[:300]}")
    return requests.get(image_url, timeout=60), "7_fal_flux.png"


def t8_replicate_flux(key):
    """Replicate FLUX - async, needs poll loop."""
    create = requests.post(
        "https://api.replicate.com/v1/predictions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"version": "black-forest-labs/flux-schnell",
              "input": {"prompt": PROMPT_TEXT, "num_inference_steps": 4, "go_fast": False}},
        timeout=30,
    )
    if create.status_code not in (200, 201):
        raise RuntimeError(f"create failed {create.status_code}: {create.text[:300]}")
    get_url = create.json()["urls"]["get"]

    for _ in range(30):  # poll up to ~60s
        time.sleep(2)
        poll = requests.get(get_url, headers={"Authorization": f"Bearer {key}"}, timeout=30)
        status = poll.json().get("status")
        if status == "succeeded":
            output = poll.json().get("output")
            image_url = output[0] if isinstance(output, list) else output
            return requests.get(image_url, timeout=60), "8_replicate_flux.png"
        if status == "failed":
            raise RuntimeError(f"prediction failed: {poll.text[:300]}")
    raise RuntimeError("timed out waiting for prediction")


def t9_segmind(key):
    """Segmind - hosts SDXL/anime-tuned models."""
    url = "https://api.segmind.com/v1/sdxl1.0-txt2img"
    resp = requests.post(url, headers={"x-api-key": key},
                          json={
                              "prompt": PROMPT_TEXT,
                              "negative_prompt": NEGATIVE_PROMPT,
                              "samples": 1,
                              "img_width": 1024,
                              "img_height": 1024,
                              "num_inference_steps": 40,
                              "guidance_scale": 7.5,
                          },
                          timeout=90)
    return resp, "9_segmind_sdxl.png"


def t10_openai_gpt_image(key):
    """OpenAI gpt-image-1 - premium quality reference point."""
    url = "https://api.openai.com/v1/images/generations"
    resp = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={
                              "model": "gpt-image-1",
                              "prompt": PROMPT_TEXT,
                              "size": "1024x1024",
                              "quality": "high",
                          },
                          timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"status {resp.status_code}: {resp.text[:300]}")
    b64 = resp.json().get("data", [{}])[0].get("b64_json")
    if not b64:
        raise RuntimeError(f"no b64_json in response: {resp.text[:300]}")
    img_bytes = base64.b64decode(b64)
    path = os.path.join(OUT_DIR, "10_openai_gpt_image.png")
    with open(path, "wb") as f:
        f.write(img_bytes)
    log_success("10_openai_gpt_image", "10_openai_gpt_image.png", len(img_bytes), 0)


def t11_leonardo(key):
    """Leonardo.ai - async, needs poll loop, popular for illustration styles."""
    create = requests.post(
        "https://cloud.leonardo.ai/api/rest/v1/generations",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "prompt": PROMPT_TEXT,
            "negative_prompt": NEGATIVE_PROMPT,
            "width": 1024,
            "height": 1024,
            "num_images": 1,
            "guidance_scale": 7,
            "num_inference_steps": 40,
            "presetStyle": "ILLUSTRATION",
        },
        timeout=30,
    )
    if create.status_code not in (200, 201):
        raise RuntimeError(f"create failed {create.status_code}: {create.text[:300]}")
    gen_id = create.json().get("sdGenerationJob", {}).get("generationId")
    if not gen_id:
        raise RuntimeError(f"no generationId: {create.text[:300]}")

    for _ in range(30):
        time.sleep(2)
        poll = requests.get(f"https://cloud.leonardo.ai/api/rest/v1/generations/{gen_id}",
                             headers={"Authorization": f"Bearer {key}"}, timeout=30)
        gen = poll.json().get("generations_by_pk", {})
        if gen.get("status") == "COMPLETE":
            images = gen.get("generated_images", [])
            if images:
                return requests.get(images[0]["url"], timeout=60), "11_leonardo.png"
        if gen.get("status") == "FAILED":
            raise RuntimeError(f"generation failed: {poll.text[:300]}")
    raise RuntimeError("timed out waiting for generation")


if __name__ == "__main__":
    run_simple("1_pollinations_image", None, t1_pollinations_image)
    run_simple("2_pollinations_gen", None, t2_pollinations_gen)
    run_simple("3_huggingface_flux_schnell", "IMGAPI_HF_TOKEN", t3_huggingface_flux)
    run_self_handled("4_craiyon", None, t4_craiyon)
    run_simple("5_deepai", "IMGAPI_DEEPAI_KEY", t5_deepai)
    run_simple("6_stability_sdxl", "IMGAPI_STABILITY_KEY", t6_stability)
    run_simple("7_fal_flux", "IMGAPI_FAL_KEY", t7_fal_flux)
    run_simple("8_replicate_flux", "IMGAPI_REPLICATE_KEY", t8_replicate_flux)
    run_simple("9_segmind_sdxl", "IMGAPI_SEGMIND_KEY", t9_segmind)
    run_self_handled("10_openai_gpt_image", "IMGAPI_OPENAI_KEY", t10_openai_gpt_image)
    run_simple("11_leonardo", "IMGAPI_LEONARDO_KEY", t11_leonardo)

    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    print("\n--- SUMMARY ---")
    for r in results:
        extra = f" ({r.get('size_bytes', '?')} bytes, {r.get('elapsed_seconds', '?')}s)" if r["status"] == "SUCCESS" else ""
        print(f"{r['name']}: {r['status']}{extra}")
