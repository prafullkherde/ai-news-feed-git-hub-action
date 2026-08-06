"""
generate_thought.py
⚠️ NOT SELF-TESTED — my sandbox has no route to api.groq.com.
Syntax/logic verified by inspection only. Run this yourself first
before wiring into run_pipeline.py.
"""

import os
import json
from groq import Groq  # pip install groq

_key = os.environ.get("GROQ_API_KEY", "")
if not _key:
    raise RuntimeError(
        "GROQ_API_KEY is empty or missing. Check: (1) secret exists in "
        "GitHub → Settings → Secrets and variables → Actions, (2) the "
        "workflow's env: block maps it to the exact name GROQ_API_KEY, "
        "(3) the secret's VALUE field isn't blank."
    )
client = Groq(api_key=_key)

SYSTEM_PROMPT = """You write short, original thoughts across a mix of topics:
discipline, alignment, momentum, habits, mindset -- AND health/fitness
specifically (body, training, longevity, energy). Rotate across both
categories day to day, don't stay only on one.
Style: a practitioner, not a generic quote account. No cliches
("hustle", "grind never stops"). Concrete, specific, slightly unexpected
angle, quotable one-liners welcome.
Examples of the tone/structure to match (don't reuse these, write new ones):
- "Fit body + healthy mind = pain free living."
- "The idea is to die young as late as possible."
- "Discipline is choosing what you want most over what you want now."
Return ONLY valid JSON, no markdown fences, no preamble."""

USER_PROMPT_TEMPLATE = """Generate {n} distinct thoughts for today.
Mix categories: aim for at least 1-2 health/fitness-angled thoughts and
1-2 discipline/mindset-angled thoughts, not all from the same category.
Each thought must be splittable into exactly 3 short slide-lines
(slide 1 = hook, slide 2 = the mechanism/why, slide 3 = the takeaway).
Return JSON: {{"thoughts": [{{"id": "t1", "slides": ["...", "...", "..."]}}]}}"""


def generate_daily_thoughts(n=4):
    resp = client.chat.completions.create(
        model="openai/gpt-oss-120b",  # matches your existing job_radar model migration
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(n=n)},
        ],
        temperature=0.9,
        response_format={"type": "json_object"},  # forces valid JSON, prevents this exact bug
    )
    raw = resp.choices[0].message.content.strip()
    # defensive: strip accidental fences, same failure mode you hit in job_radar
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)["thoughts"]
    except json.JSONDecodeError as e:
        print(f"RAW GROQ OUTPUT (failed to parse):\n{raw}")
        raise


if __name__ == "__main__":
    thoughts = generate_daily_thoughts(4)
    for t in thoughts:
        print(t["id"], "->", t["slides"])
