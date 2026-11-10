"""Built-in icon set (Tabler Icons, MIT) rendered from a bundled font.

Reference icons in the config as ``tabler:<name>`` (outline) or
``tabler-filled:<name>``. Browse names at https://tabler.io/icons.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from functools import cache, lru_cache
from importlib import resources

from PIL import Image, ImageDraw, ImageFont

SETS = {"tabler": ("outline", "tabler-icons.ttf"), "tabler-filled": ("filled", "tabler-icons-filled.ttf")}


@dataclass(frozen=True)
class Glyph:
    set: str        # "tabler" | "tabler-filled"
    name: str

    def __str__(self) -> str:
        return f"{self.set}:{self.name}"


class UnknownIcon(ValueError):
    pass


@cache
def _mapping() -> dict:
    return json.loads(resources.files("streamplify").joinpath("icons/tabler.json").read_text())


def names(set_: str = "tabler") -> dict[str, int]:
    return _mapping()[SETS[set_][0]]


def is_glyph_ref(ref: str) -> bool:
    """True for anything shaped like ``set:name`` (not a file path)."""
    prefix, sep, name = ref.partition(":")
    return bool(sep) and bool(prefix) and "/" not in ref and "." not in prefix and bool(name)


def parse(ref: str) -> Glyph:
    """Validate ``tabler:name`` / ``tabler-filled:name``; raise UnknownIcon with suggestions."""
    prefix, _, name = ref.partition(":")
    if prefix not in SETS:
        raise UnknownIcon(f"unknown icon set '{prefix}' (use {' or '.join(SETS)})")
    table = names(prefix)
    if name not in table:
        close = difflib.get_close_matches(name, table, n=3, cutoff=0.6)
        hint = f"; did you mean {', '.join(prefix + ':' + c for c in close)}?" if close else ""
        if prefix == "tabler-filled" and name in names("tabler"):
            hint = f"; it only exists as outline: tabler:{name}"
        raise UnknownIcon(f"unknown icon '{ref}'{hint}")
    return Glyph(prefix, name)


@lru_cache(maxsize=32)
def _font(set_: str, size: int) -> ImageFont.FreeTypeFont:
    with resources.as_file(resources.files("streamplify").joinpath("icons", SETS[set_][1])) as p:
        return ImageFont.truetype(str(p), size)


@lru_cache(maxsize=256)
def render_glyph(glyph: Glyph, box: int, color: str = "#ffffff") -> Image.Image:
    """The glyph as an RGBA image fitted into a ``box`` x ``box`` square."""
    ch = chr(names(glyph.set)[glyph.name])
    # Tabler glyphs fill ~their em square; render large, crop to ink, then scale down.
    big = box * 3
    canvas = Image.new("L", (big * 2, big * 2), 0)
    ImageDraw.Draw(canvas).text((big, big), ch, fill=255, font=_font(glyph.set, big), anchor="mm")
    bbox = canvas.getbbox()
    if bbox is None:
        return Image.new("RGBA", (box, box), (0, 0, 0, 0))
    mask = canvas.crop(bbox)
    mask.thumbnail((box, box), Image.LANCZOS)
    out = Image.new("RGBA", mask.size, color)
    out.putalpha(mask)
    return out
