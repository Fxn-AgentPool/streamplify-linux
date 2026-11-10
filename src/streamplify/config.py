"""TOML configuration.

Keys are addressed in *reading order*: 1 = top-left, 5 = top-right,
15 = bottom-right. Example::

    brightness = 80
    start_page = "main"

    [pages.main.1]
    label = "Terminal"
    icon = "~/icons/terminal.png"
    run = "kitty"

    [pages.main.2]
    label = "Media"
    bg = "#8e44ad"
    page = "media"

    [pages.media.15]
    label = "Back"
    back = true
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import icons
from .actions import HotkeyError, parse_combo
from .device import COLS, KEY_COUNT, key_at

DEFAULT_PATH = Path("~/.config/streamplify/config.toml").expanduser()

ACTION_FIELDS = ("run", "url", "hotkey", "page", "back", "brightness")
STYLE_FIELDS = ("label", "icon", "icon_color", "bg", "fg", "font_size")
WIDGETS = ("clock", "cpu", "ram", "temp", "command", "mic", "nowplaying")
WIDGET_OPTS = ("interval", "format", "style", "color", "command", "sensor", "player")
METER_STYLES = ("graph", "bar", "text")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    kind: str           # one of ACTION_FIELDS
    value: object


@dataclass(frozen=True)
class KeySpec:
    label: str = ""
    icon: Path | icons.Glyph | None = None
    icon_color: str | None = None       # glyph icons only; defaults to fg
    bg: str = "#000000"
    fg: str = "#ffffff"
    font_size: int | None = None
    action: Action | None = None
    widget: str | None = None
    widget_opts: dict = field(default_factory=dict)


@dataclass
class Page:
    name: str
    keys: dict[int, KeySpec] = field(default_factory=dict)   # device key index -> spec


@dataclass
class Config:
    brightness: int = 80
    start_page: str = "main"
    font: Path | None = None
    pages: dict[str, Page] = field(default_factory=dict)
    path: Path | None = None


def slot_to_key(slot: int) -> int:
    """Reading-order slot (1 = top-left) -> device key index."""
    if not 1 <= slot <= KEY_COUNT:
        raise ConfigError(f"key {slot} out of range 1..{KEY_COUNT}")
    row, col = divmod(slot - 1, COLS)
    return key_at(row, col)


def _parse_key(where: str, raw: dict, base: Path) -> KeySpec:
    actions = [k for k in ACTION_FIELDS if k in raw]
    if len(actions) > 1:
        raise ConfigError(f"{where}: only one action allowed, got {', '.join(actions)}")
    action = Action(actions[0], raw[actions[0]]) if actions else None
    if action and action.kind == "hotkey":
        try:
            parse_combo(str(action.value))
        except HotkeyError as e:
            raise ConfigError(f"{where}: {e}") from None
    if action and action.kind == "brightness":
        v = action.value
        if not (isinstance(v, int) or (isinstance(v, str) and v[:1] in "+-" and v[1:].isdigit())):
            raise ConfigError(f"{where}: brightness must be 0-100 or '+N'/'-N'")
    unknown = set(raw) - set(ACTION_FIELDS) - set(STYLE_FIELDS) - set(WIDGET_OPTS) - {"widget"}
    if unknown:
        raise ConfigError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    widget = raw.get("widget")
    opts = {k: raw[k] for k in WIDGET_OPTS if k in raw}
    if widget is None and opts:
        raise ConfigError(f"{where}: {', '.join(sorted(opts))} only valid together with 'widget'")
    if widget is not None:
        if widget not in WIDGETS:
            raise ConfigError(f"{where}: unknown widget '{widget}' (choose from {', '.join(WIDGETS)})")
        if widget == "command" and not opts.get("command"):
            raise ConfigError(f"{where}: command widget needs command = \"...\"")
        if "style" in opts and opts["style"] not in METER_STYLES:
            raise ConfigError(f"{where}: style must be one of {', '.join(METER_STYLES)}")
        iv = opts.get("interval", 1)
        if not (isinstance(iv, (int, float)) and iv >= 0.1):
            raise ConfigError(f"{where}: interval must be a number of seconds >= 0.1")
    icon = raw.get("icon")
    if icon is not None:
        if icons.is_glyph_ref(str(icon)):
            try:
                icon = icons.parse(str(icon))
            except icons.UnknownIcon as e:
                raise ConfigError(f"{where}: {e}") from None
        else:
            icon = Path(icon).expanduser()
            if not icon.is_absolute():
                icon = base / icon
    return KeySpec(
        label=str(raw.get("label", "")),
        icon=icon,
        icon_color=raw.get("icon_color"),
        bg=raw.get("bg", "#000000"),
        fg=raw.get("fg", "#ffffff"),
        font_size=raw.get("font_size"),
        action=action,
        widget=widget,
        widget_opts=opts,
    )


def parse(data: dict, base: Path = Path(".")) -> Config:
    cfg = Config(
        brightness=int(data.get("brightness", 80)),
        start_page=data.get("start_page", "main"),
        font=Path(data["font"]).expanduser() if "font" in data else None,
    )
    for name, raw_page in data.get("pages", {}).items():
        page = Page(name)
        for slot_s, raw_key in raw_page.items():
            try:
                slot = int(slot_s)
            except ValueError:
                raise ConfigError(f"pages.{name}: key '{slot_s}' must be a number 1..{KEY_COUNT}") from None
            page.keys[slot_to_key(slot)] = _parse_key(f"pages.{name}.{slot}", raw_key, base)
        cfg.pages[name] = page
    if cfg.start_page not in cfg.pages:
        cfg.pages.setdefault(cfg.start_page, Page(cfg.start_page))
    for page in cfg.pages.values():
        for spec in page.keys.values():
            if spec.action and spec.action.kind == "page" and spec.action.value not in cfg.pages:
                raise ConfigError(f"page '{page.name}' links to unknown page '{spec.action.value}'")
    return cfg


def load(path: Path = DEFAULT_PATH) -> Config:
    path = Path(path).expanduser()
    with open(path, "rb") as f:
        cfg = parse(tomllib.load(f), base=path.parent)
    cfg.path = path
    return cfg
