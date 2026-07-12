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

# ---- BRAND CONSTANTS (fixed once, do not change per-post) ----
CANVAS = (1080, 1080)               # 1:1 square, per your spec ("Instagram square 1:1 format")
FONT_BOLD = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
BRAND_GRADIENT = [(250, 240, 210), (250, 240, 210)]  # cream fallback, matches Ideogram bg family
ACCENT = (20, 20, 20)                # black underline accent, per your spec ("bold black text")
TEXT_COLOR = (20, 20, 20)            # near-black, high contrast on mustard/cream/mint
FOOTER_TEXT = "@your_handle"         # identity anchor, appears on every slide


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


def render_slide(text, slide_no, total_slides, out_path, background_bytes=None):
    """
    background_bytes: raw PNG/JPG bytes from generate_background.py (Ideogram).
    If None, falls back to flat gradient -- lets you test/run without an
    Ideogram key while wiring the rest.
    """
    if background_bytes:
        from io import BytesIO
        img = Image.open(BytesIO(background_bytes)).convert("RGB").resize(CANVAS)
    else:
        img = make_gradient_bg(CANVAS, *BRAND_GRADIENT)
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


def render_carousel(thought_slides, out_dir):
    """
    thought_slides: list of 3 short strings (one idea split across slides,
    or 3 related sub-points of the same thought)
    Returns list of file paths, in post order.
    """
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, text in enumerate(thought_slides, start=1):
        path = os.path.join(out_dir, f"slide_{i}.png")
        render_slide(text, i, len(thought_slides), path)
        paths.append(path)
    return paths


if __name__ == "__main__":
    # SELF-TEST: real render, no mocks
    sample = [
        "Discipline is choosing what you want most over what you want now.",
        "Momentum is built in the repetitions nobody sees.",
        "Alignment beats intensity every single time.",
    ]
    result = render_carousel(sample, "/home/claude/carousel-pipeline/output/test_carousel")
    print("Rendered:", result)
