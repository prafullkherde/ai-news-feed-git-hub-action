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


def shade_variant(color, slide_index):
    """Slight brightness shift per slide within the same carousel, so
    slides 1/2/3 aren't pixel-identical backgrounds but stay in the same
    color family (no jarring jumps between slides of one post)."""
    offsets = [0, -10, 8, -6, 12, -4]  # small, deterministic per slide position
    offset = offsets[slide_index % len(offsets)]
    return tuple(max(0, min(255, c + offset)) for c in color)


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


CHAR_REPLACEMENTS = {
    "\u2014": "-",   # em dash —
    "\u2013": "-",   # en dash –
    "\u2018": "'",   # left curly single quote '
    "\u2019": "'",   # right curly single quote '
    "\u201c": '"',   # left curly double quote "
    "\u201d": '"',   # right curly double quote "
    "\u2026": "...", # ellipsis …
    "\u00a0": " ",   # non-breaking space
}


EMOJI_RANGES = [
    (0x1F300, 0x1FAFF),  # misc symbols, emoticons, transport, supplemental symbols
    (0x2600, 0x27BF),    # misc symbols and dingbats (includes heart, stars, etc)
    (0xFE00, 0xFE0F),    # variation selectors
    (0x1F1E6, 0x1F1FF),  # regional indicators (flag emoji)
]


def is_emoji(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def sanitize_text(text, font):
    """
    Replaces common Unicode punctuation Groq generates (smart quotes,
    em-dashes, ellipsis) with ASCII equivalents, strips emoji (Poppins
    has no emoji glyphs at all), then drops any remaining character the
    font has no glyph for -- prevents the tofu/box-character bug from
    ever reaching the rendered image.
    """
    for bad, good in CHAR_REPLACEMENTS.items():
        text = text.replace(bad, good)

    cleaned = []
    for ch in text:
        if is_emoji(ch):
            continue  # drop silently, no font can render these as raster glyphs reliably
        if ch == " " or ch in ".,!?'\"-()":
            cleaned.append(ch)
            continue
        try:
            bbox = font.getmask(ch).getbbox()
            if bbox is not None:
                cleaned.append(ch)
            # else: font has no glyph for this char -- drop it silently
        except Exception:
            cleaned.append(ch)  # fail open rather than mangling text
    result = "".join(cleaned)
    while "  " in result:
        result = result.replace("  ", " ")
    return result.strip()


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
        color = shade_variant(color, slide_no - 1)
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
    text = sanitize_text(text, body_font)
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


CTA_TEXT = "If you enjoyed this, double-tap to like and hit that follow button to see more like this!"


def render_carousel(thought_slides, out_dir, thought_id="default", include_cta=True):
    """
    thought_slides: list of 5 short strings (the actual content).
    thought_id: used to deterministically pick this carousel's base
    background color from COLOR_PALETTE - same id always gets the same
    color family, slides within it get slight shade variation.
    include_cta: appends a fixed 6th "like + follow" slide, not from Groq.
    Returns list of file paths, in post order.
    """
    os.makedirs(out_dir, exist_ok=True)
    bg_color = pick_background_color(thought_id)

    all_slides = list(thought_slides)
    if include_cta:
        all_slides.append(CTA_TEXT)

    paths = []
    for i, text in enumerate(all_slides, start=1):
        path = os.path.join(out_dir, f"slide_{i}.png")
        render_slide(text, i, len(all_slides), path, bg_color=bg_color)
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
