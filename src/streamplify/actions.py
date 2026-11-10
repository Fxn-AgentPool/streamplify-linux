"""Side-effect actions bound to keys."""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess

log = logging.getLogger(__name__)

_MODS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt",
         "super": "super", "win": "super", "meta": "super", "logo": "super"}


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
    """Build the command that types a combo like 'ctrl+shift+m'."""
    if wayland is None:
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return None
    mods, key = parts[:-1], parts[-1]
    if wayland:
        if not shutil.which("wtype"):
            return None
        argv = ["wtype"]
        wmods = [{"super": "logo"}.get(_MODS.get(m, m), _MODS.get(m, m)) for m in mods]
        for m in wmods:
            argv += ["-M", m]
        argv += ["-k", key]
        for m in reversed(wmods):
            argv += ["-m", m]
        return argv
    if not shutil.which("xdotool"):
        return None
    return ["xdotool", "key", "--clearmodifiers", "+".join([_MODS.get(m, m) for m in mods] + [key])]


def send_hotkey(combo: str) -> None:
    argv = hotkey_argv(combo)
    if argv is None:
        log.warning("hotkey %r: install xdotool (X11) or wtype (Wayland)", combo)
        return
    _spawn(argv)


def describe(argv_or_cmd) -> str:
    return argv_or_cmd if isinstance(argv_or_cmd, str) else shlex.join(argv_or_cmd)
