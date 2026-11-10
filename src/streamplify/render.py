"""Turn a KeySpec into a 100x100 key image."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from .config import KeySpec
from .device import KEY_SIZE

PAD = 6


@lru_cache(maxsize=64)
def font(size: int, path: Path | None = None) -> ImageFont.FreeTypeFont:
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=128)
def _icon(path: Path, box: int) -> Image.Image | None:
    try:
        im = Image.open(path)
        im.load()
    except OSError:
        return None
    im = im.convert("RGBA")
    return ImageOps.contain(im, (box, box), Image.LANCZOS)


def _wrap(text: str, f, width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=f) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _fit_text(text: str, draw, width: int, height: int, size: int | None, font_path):
    """Largest font size (or the given one) at which the wrapped text fits."""
    sizes = [size] if size else range(24, 9, -2)
    for s in sizes:
        f = font(s, font_path)
        lines = _wrap(text, f, width, draw)
        line_h = s * 1.15
        if len(lines) * line_h <= height and all(draw.textlength(ln, font=f) <= width for ln in lines):
            return f, lines, line_h
    f = font(sizes[-1] if size else 10, font_path)
    return f, _wrap(text, f, width, draw), (size or 10) * 1.15


def render_key(spec: KeySpec, *, pressed: bool = False, font_path: Path | None = None) -> Image.Image:
    im = Image.new("RGB", (KEY_SIZE, KEY_SIZE), spec.bg)
    draw = ImageDraw.Draw(im)
    inner = KEY_SIZE - 2 * PAD

    icon = _icon(spec.icon, inner if not spec.label else int(inner * 0.62)) if spec.icon else None
    if icon is not None:
        top = PAD if spec.label else (KEY_SIZE - icon.height) // 2
        im.paste(icon, ((KEY_SIZE - icon.width) // 2, top), icon)
        text_top, text_h = top + icon.height + 2, KEY_SIZE - (top + icon.height + 2) - PAD // 2
        size = spec.font_size or 14
    else:
        text_top, text_h = PAD, inner
        size = spec.font_size

    if spec.label:
        f, lines, line_h = _fit_text(spec.label, draw, inner, text_h, size, font_path)
        y = text_top + (text_h - len(lines) * line_h) / 2
        for line in lines:
            draw.text((KEY_SIZE / 2, y + line_h / 2), line, fill=spec.fg, font=f, anchor="mm")
            y += line_h

    return press_effect(im) if pressed else im


def press_effect(im: Image.Image) -> Image.Image:
    """Darken and shrink a key image so it looks pushed in."""
    im = ImageEnhance.Brightness(im).enhance(0.55)
    return ImageOps.expand(im.resize((KEY_SIZE - 8, KEY_SIZE - 8), Image.LANCZOS), 4, fill="#000000")


BLANK = KeySpec()
