"""Screensaver: kicks in after a period without key presses.

Modes:
    clock  one large clock + date drawn across the whole deck (default)
    dim    keep the current page, just lower the brightness
    blank  clear the keys and turn the backlight off
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .device import COLS, KEY_COUNT, KEY_SIZE, ROWS, pos_of

MODES = ("clock", "dim", "blank")
CANVAS_W, CANVAS_H = COLS * KEY_SIZE, ROWS * KEY_SIZE


@dataclass(frozen=True)
class ScreensaverConfig:
    after: float = 600.0        # seconds without a key press; 0 = never
    mode: str = "clock"
    brightness: int = 20        # backlight while active (clock / dim)
    format: str = "%H:%M"       # clock mode
    date_format: str = "%a %d %b"
    color: str = "#c8d0e0"
    bg: str = "#000000"

    @property
    def enabled(self) -> bool:
        return self.after > 0


def slice_canvas(canvas: Image.Image) -> dict[int, Image.Image]:
    """Cut a COLS*100 x ROWS*100 image into per-key images."""
    tiles = {}
    for key in range(1, KEY_COUNT + 1):
        row, col = pos_of(key)
        x, y = col * KEY_SIZE, row * KEY_SIZE
        tiles[key] = canvas.crop((x, y, x + KEY_SIZE, y + KEY_SIZE))
    return tiles


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_size: int) -> int:
    from .render import font  # late: render imports config, which imports this module
    size = max_size
    while size > 12 and draw.textlength(text, font=font(size)) > max_w:
        size -= 4
    return size


def render_clock(cfg: ScreensaverConfig, now: time.struct_time | None = None) -> Image.Image:
    from .render import font

    now = now or time.localtime()
    im = Image.new("RGB", (CANVAS_W, CANVAS_H), cfg.bg)
    d = ImageDraw.Draw(im)
    main = time.strftime(cfg.format, now)
    date = time.strftime(cfg.date_format, now) if cfg.date_format else ""
    size = _fit(d, main, CANVAS_W - 40, 170)
    if date:
        main_y = CANVAS_H * 0.42
        d.text((CANVAS_W / 2, main_y), main, fill=cfg.color, font=font(size), anchor="mm")
        dsize = _fit(d, date, CANVAS_W - 80, 40)
        d.text((CANVAS_W / 2, CANVAS_H * 0.82), date, fill=_dim(cfg.color, 0.6),
               font=font(dsize), anchor="mm")
    else:
        d.text((CANVAS_W / 2, CANVAS_H / 2), main, fill=cfg.color, font=font(size), anchor="mm")
    return im


def _cell(text: str, size: int, color, bg: str) -> Image.Image:
    from .render import font

    im = Image.new("RGB", (KEY_SIZE, KEY_SIZE), bg)
    if text:
        d = ImageDraw.Draw(im)
        size = _fit(d, text, KEY_SIZE - 8, size)
        f = font(size)
        # Centre the visible ink, not the line box (digits have no descenders).
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
        d.text(((KEY_SIZE - (x1 - x0)) / 2 - x0, (KEY_SIZE - (y1 - y0)) / 2 - y0), text, fill=color, font=f)
    return im


def _row(items: list[str], row: int, size: int, color, bg: str) -> dict[int, Image.Image] | None:
    """One item per key in ``row``, centred. None if there are too many items."""
    if len(items) > COLS:
        return None
    start = (COLS - len(items)) // 2
    out = {}
    for col in range(COLS):
        i = col - start
        text = items[i] if 0 <= i < len(items) else ""
        out[(row, col)] = _cell(text, size, color, bg)
    return out


def render_clock_tiles(cfg: ScreensaverConfig, now: time.struct_time | None = None) -> dict[int, Image.Image]:
    """Clock laid out on the key grid so bezels never cut through a character:
    one time character per key in the middle row, one date word per key in the
    bottom row. Falls back to one big canvas for formats that don't fit."""
    from .device import key_at

    now = now or time.localtime()
    main = time.strftime(cfg.format, now)
    date = time.strftime(cfg.date_format, now) if cfg.date_format else ""
    mid = _row(list(main), ROWS // 2, 116, cfg.color, cfg.bg)
    bottom = _row(date.split(), ROWS - 1, 40, _dim(cfg.color, 0.6), cfg.bg) if date else {}
    if mid is None or bottom is None:
        return slice_canvas(render_clock(cfg, now))
    grid = {(r, c): _cell("", 0, cfg.color, cfg.bg) for r in range(ROWS) for c in range(COLS)}
    grid.update(mid)
    grid.update(bottom)
    return {key_at(r, c): im for (r, c), im in grid.items()}


def _dim(color: str, factor: float) -> tuple[int, int, int]:
    r, g, b = Image.new("RGB", (1, 1), color).getpixel((0, 0))
    return int(r * factor), int(g * factor), int(b * factor)
