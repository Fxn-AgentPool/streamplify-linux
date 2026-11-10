"""Side-effect actions bound to keys."""
from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess

log = logging.getLogger(__name__)

_MODS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "altgr": "altgr",
         "super": "super", "win": "super", "meta": "super", "logo": "super"}

# Friendly lowercase spellings -> X keysym names. Anything else is passed
# through with its case intact (keysyms are case-sensitive: "XF86AudioMute").
_KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "space": "space", "tab": "Tab", "backspace": "BackSpace", "delete": "Delete", "del": "Delete",
    "insert": "Insert", "ins": "Insert", "home": "Home", "end": "End",
    "pageup": "Prior", "pgup": "Prior", "pagedown": "Next", "pgdn": "Next",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "print": "Print", "printscreen": "Print", "pause": "Pause", "menu": "Menu",
    "capslock": "Caps_Lock", "numlock": "Num_Lock", "scrolllock": "Scroll_Lock", "plus": "plus",
}
_FKEY = re.compile(r"[fF]([1-9]|[12][0-9]|3[0-5])")


class HotkeyError(ValueError):
    pass


def parse_combo(combo: str) -> tuple[list[str], str]:
    """'Ctrl+Shift+F13' -> (['ctrl', 'shift'], 'F13'). Modifiers are
    case-insensitive; the key keeps its case unless it has a friendly alias."""
    combo = combo.strip()
    if combo.endswith("++"):                 # "ctrl++" means ctrl + plus
        combo = combo[:-2] + "+plus"
    parts = [p.strip() for p in combo.split("+")]
    if not parts or any(not p for p in parts):
        raise HotkeyError(f"invalid hotkey '{combo}'")
    *mods, key = parts
    norm_mods = []
    for m in mods:
        if m.lower() not in _MODS:
            raise HotkeyError(f"unknown modifier '{m}' in '{combo}' (use {', '.join(sorted(set(_MODS)))})")
        norm_mods.append(_MODS[m.lower()])
    if len(key) == 1 and key.isalpha():
        key = key.lower()        # "Ctrl+C" means ctrl+c, not ctrl+shift+c
    elif _FKEY.fullmatch(key):
        key = "F" + key[1:]
    else:
        key = _KEY_ALIASES.get(key.lower(), key)
    return norm_mods, key

def _spawn(argv: list[str]) -> None:
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def run_command(cmd: str | list[str]) -> None:
    """Run detached. A string goes through the shell (so pipes/env work)."""
    if isinstance(cmd, list):
        _spawn([str(a) for a in cmd])
    else:
        _spawn(["/bin/sh", "-c", cmd])


def open_url(url: str) -> None:
    _spawn(["xdg-open", url])


def hotkey_argv(combo: str, wayland: bool | None = None) -> list[str] | None:
    """Build the command that presses a combo like 'ctrl+shift+F13'."""
    if wayland is None:
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    mods, key = parse_combo(combo)
    if wayland:
        if not shutil.which("wtype"):
            return None
        wmods = [{"super": "logo"}.get(m, m) for m in mods]
        argv = ["wtype"]
        for m in wmods:
            argv += ["-M", m]
        argv += ["-k", key]
        for m in reversed(wmods):
            argv += ["-m", m]
        return argv
    if not shutil.which("xdotool"):
        return None
    xmods = [{"altgr": "ISO_Level3_Shift"}.get(m, m) for m in mods]
    return ["xdotool", "key", "--clearmodifiers", "+".join([*xmods, key])]

def send_hotkey(combo: str) -> None:
    argv = hotkey_argv(combo)
    if argv is None:
        log.warning("hotkey %r: install xdotool (X11) or wtype (Wayland)", combo)
        return
    _spawn(argv)


def describe(argv_or_cmd) -> str:
    return argv_or_cmd if isinstance(argv_or_cmd, str) else shlex.join(argv_or_cmd)
