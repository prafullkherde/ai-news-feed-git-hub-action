"""
compose_carousel.py
Renders N slides for one IG/FB carousel from a single "thought".
Self-contained: no network call required. Uses local Poppins font +
PIL-generated gradient background so brand look stays IDENTICAL every day
(fixes the "generic AI quote graphic" failure mode flagged earlier).

Swap BACKGROUND_MODE to "pollinations" later if you want AI-generated
backgrounds instead of the flat gradient -- see generate_image.py.
"""

from PIL import Image, ImageDraw, ImageFont
import textwrap
import os

# ---- BRAND CONSTANTS ----
CANVAS = (1080, 1080)               # 1:1 square, per your spec ("Instagram square 1:1 format")
FONT_BOLD = "fonts/Poppins-Bold.ttf"
FONT_REGULAR = "fonts/Poppins-Regular.ttf"
ACCENT = (20, 20, 20)                # black underline accent, per your spec ("bold black text")
TEXT_COLOR = (20, 20, 20)            # near-black, works on all 4 palette colors below
FOOTER_TEXT = "@prafull_daily_thoughts"

# Rotating background palette - one flat color per post, cycled deterministically
# so the SAME thought always renders the same color (idempotent re-runs),
# but different thoughts get visible variation. Matches your original spec:
# mustard-yellow, cream, beige, mint-green.
COLOR_PALETTE = [
    (245, 196, 85),   # mustard-yellow
    (250, 240, 210),  # cream
    (235, 224, 200),  # beige
    (200, 230, 210),  # mint-green
]


def pick_background_color(thought_id):
    """Deterministic rotation - same thought_id always gets the same color
    (so re-running a failed post doesn't change its look), different
    thoughts cycle through the palette."""
    idx = sum(ord(c) for c in thought_id) % len(COLOR_PALETTE)
    return COLOR_PALETTE[idx]


def make_gradient_bg(size, top_color, bottom_color):
    w, h = size
    base = Image.new("RGB", size, top_color)
    top = Image.new("RGB", size, top_color)
    bottom = Image.new("RGB", size, bottom_color)
    mask = Image.new("L", size)
    mask_data = []
    for y in range(h):
        mask_data.extend([int(255 * (y / h))] * w)
    mask.putdata(mask_data)
    base.paste(bottom, (0, 0), mask)
    return base


def wrap_text(text, font, max_width, draw):
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_slide(text, slide_no, total_slides, out_path, background_bytes=None, bg_color=None):
    """
    background_bytes: raw PNG/JPG bytes from generate_background.py (Ideogram).
    If None, falls back to a flat color background -- lets you test/run
    without an Ideogram key while wiring the rest.
    bg_color: RGB tuple for the flat background. If None, defaults to cream.
    """
    if background_bytes:
        from io import BytesIO
        img = Image.open(BytesIO(background_bytes)).convert("RGB").resize(CANVAS)
    else:
        color = bg_color or COLOR_PALETTE[1]  # cream default
        img = make_gradient_bg(CANVAS, color, color)
    draw = ImageDraw.Draw(img)

    # accent bar - top-left, brand anchor repeated every slide
    draw.rectangle([(80, 90), (160, 100)], fill=ACCENT)

    # slide counter (top-right) - signals "swipe" affordance for carousel
    counter_font = ImageFont.truetype(FONT_REGULAR, 34)
    counter_text = f"{slide_no}/{total_slides}"
    draw.text((CANVAS[0] - 160, 85), counter_text, font=counter_font, fill=ACCENT)

    # main thought text, centered vertically
    body_font = ImageFont.truetype(FONT_BOLD, 64)
    lines = wrap_text(text, body_font, CANVAS[0] - 160, draw)
    line_height = 78
    total_text_height = len(lines) * line_height
    y = (CANVAS[1] - total_text_height) // 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=body_font)
        line_width = bbox[2] - bbox[0]
        x = (CANVAS[0] - line_width) // 2
        draw.text((x, y), line, font=body_font, fill=TEXT_COLOR)
        y += line_height

    # footer identity anchor - fixed position every slide, every day
    footer_font = ImageFont.truetype(FONT_REGULAR, 30)
    draw.text((80, CANVAS[1] - 100), FOOTER_TEXT, font=footer_font, fill=(90, 90, 90))

    img.save(out_path, quality=95)
    return out_path


def render_carousel(thought_slides, out_dir, thought_id="default"):
    """
    thought_slides: list of 3 short strings (one idea split across slides,
    or 3 related sub-points of the same thought)
    thought_id: used to deterministically pick this carousel's background
    color from COLOR_PALETTE - same id always gets the same color.
    Returns list of file paths, in post order.
    """
    os.makedirs(out_dir, exist_ok=True)
    bg_color = pick_background_color(thought_id)
    paths = []
    for i, text in enumerate(thought_slides, start=1):
        path = os.path.join(out_dir, f"slide_{i}.png")
        render_slide(text, i, len(thought_slides), path, bg_color=bg_color)
        paths.append(path)
    return paths


if __name__ == "__main__":
    # SELF-TEST: real render, no mocks
    sample = [
        "Discipline is choosing what you want most over what you want now.",
        "Momentum is built in the repetitions nobody sees.",
        "Alignment beats intensity every single time.",
    ]
    result = render_carousel(sample, "output/test_carousel")
    print("Rendered:", result)
