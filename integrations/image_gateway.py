"""Image generation gateway.

Real generation renders a deterministic, on-brand visual card locally with
Pillow instead of calling a paid AI image-generation provider. This keeps a
genuinely designed image available with no new secrets, no network egress,
and fully deterministic, testable output for the same input text.
"""

import hashlib
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from config.settings import settings


MOCK_IMAGE_PATH = "mock://generated-linkedin-image.png"

_ASPECT_RATIO_SIZES: dict[str, tuple[int, int]] = {
    "1:1": (1200, 1200),
    "4:5": (1080, 1350),
    "16:9": (1200, 675),
}

_BACKGROUND = (247, 247, 245)
_TEXT = (17, 17, 17)
_ACCENT = (36, 81, 184)


def generate_image(prompt: str, mock_mode: bool, aspect_ratio: str = "1:1") -> str:
    """Return a generated image path.

    In mock mode this returns a deterministic marker path without calling any
    real API or touching the filesystem. In real mode this renders a real
    branded card locally with Pillow and returns its saved filesystem path.
    """
    if mock_mode:
        return MOCK_IMAGE_PATH
    return render_branded_card(prompt, aspect_ratio=aspect_ratio)


def render_branded_card(text: str, aspect_ratio: str = "1:1") -> str:
    """Render a clean, text-forward branded card and return its saved path.

    Deterministic: the same text and aspect ratio always render to the same
    file path, so repeated calls do not accumulate duplicate files.
    """
    size = _ASPECT_RATIO_SIZES.get(aspect_ratio, _ASPECT_RATIO_SIZES["1:1"])
    cleaned = " ".join(text.split()).strip() or "Network Growth Agent"
    image = Image.new("RGB", size, color=_BACKGROUND)
    draw = ImageDraw.Draw(image)
    margin = int(size[0] * 0.09)
    max_width = size[0] - 2 * margin
    font = _fit_font(draw, cleaned, max_width, size[1], margin)
    lines = _wrap_text(draw, cleaned, font, max_width)
    line_height = int(font.size * 1.3)
    block_height = line_height * len(lines)
    y = (size[1] - block_height) // 2
    for line in lines:
        draw.text((margin, y), line, font=font, fill=_TEXT)
        y += line_height
    rule_y = min(size[1] - margin // 2, y + int(size[1] * 0.03))
    draw.rectangle(
        [margin, rule_y, margin + int(size[0] * 0.07), rule_y + max(4, size[0] // 200)],
        fill=_ACCENT,
    )
    destination_dir = Path(settings.media_storage_path) / "generated"
    destination_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{cleaned}|{aspect_ratio}".encode("utf-8")).hexdigest()[:16]
    destination = destination_dir / f"{digest}.png"
    image.save(destination, format="PNG")
    return str(destination)


def _fit_font(
    draw: "ImageDraw.ImageDraw",
    text: str,
    max_width: int,
    max_height: int,
    margin: int,
) -> "ImageFont.FreeTypeFont":
    """Pick the largest font size whose wrapped text fits the card height."""
    max_text_height = max_height - 2 * margin
    for candidate_size in range(min(96, max_width // 8), 19, -4):
        font = cast(ImageFont.FreeTypeFont, ImageFont.load_default(size=candidate_size))
        lines = _wrap_text(draw, text, font, max_width)
        line_height = int(candidate_size * 1.3)
        if line_height * len(lines) <= max_text_height:
            return font
    return cast(ImageFont.FreeTypeFont, ImageFont.load_default(size=20))


def _wrap_text(
    draw: "ImageDraw.ImageDraw",
    text: str,
    font: "ImageFont.FreeTypeFont",
    max_width: int,
) -> list[str]:
    """Word-wrap text to fit max_width using the font's real glyph metrics."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines
