"""Live keys: widgets that redraw themselves on a timer.

A widget samples some data on its interval and renders a key image. The
controller only uploads a key when the rendered image actually changed, so
a minute clock ticking every second costs one USB upload per minute.

Config (per key):
    widget   = "clock" | "cpu" | "ram" | "temp" | "command" | "mic" | "nowplaying"
    interval = seconds between samples (default per widget)
    format   = strftime format for clock (default "%H:%M")
    style    = "graph" | "bar" | "text" for meters (default "graph")
    color    = accent colour for meters
    command  = shell command for the command widget (first lines of output shown)
    player   = MPRIS player name for nowplaying (default: whichever playerctl picks)
"""
from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from .config import KeySpec
from .device import KEY_SIZE
from .render import font

log = logging.getLogger(__name__)

W = KEY_SIZE


class Widget:
    default_interval = 1.0

    def __init__(self, spec: KeySpec):
        self.spec = spec
        opts = spec.widget_opts
        self.interval = float(opts.get("interval", self.default_interval))
        self.next_due = 0.0

    def due(self, now: float) -> bool:
        return now >= self.next_due

    def tick(self, now: float) -> None:
        self.next_due = now + self.interval
        try:
            self.sample()
        except Exception:
            log.exception("widget %s failed to sample", type(self).__name__)

    def sample(self) -> None:
        pass

    def render(self) -> Image.Image:
        raise NotImplementedError

    def poll_changed(self) -> bool:
        """True if the widget changed outside its tick (e.g. async result)."""
        return False

    def press(self) -> bool:
        """Built-in press behaviour for keys without an action. True = handled."""
        return False

    def close(self) -> None:
        pass

    # helpers
    def _canvas(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        im = Image.new("RGB", (W, W), self.spec.bg)
        return im, ImageDraw.Draw(im)


# --- clock -----------------------------------------------------------------

class Clock(Widget):
    default_interval = 1.0

    def __init__(self, spec):
        super().__init__(spec)
        self.fmt = spec.widget_opts.get("format", "%H:%M")
        self.now = time.localtime()

    def sample(self):
        self.now = time.localtime()

    def render(self):
        im, d = self._canvas()
        main = time.strftime(self.fmt, self.now)
        lines = main.split("\n")
        if self.spec.label:
            lines.append(self.spec.label)
        sizes = [self._fit(d, ln, 34 if i == 0 else 16) for i, ln in enumerate(lines)]
        total = sum(s * 1.15 for s in sizes)
        y = (W - total) / 2
        for ln, s in zip(lines, sizes, strict=True):
            d.text((W / 2, y + s * 0.575), ln, fill=self.spec.fg, font=font(s), anchor="mm")
            y += s * 1.15
        return im

    @staticmethod
    def _fit(d, text, start):
        s = start
        while s > 10 and d.textlength(text, font=font(s)) > W - 8:
            s -= 2
        return s


# --- meters ----------------------------------------------------------------

class Meter(Widget):
    """Base for percentage meters with text / bar / graph styles."""
    title = ""
    default_color = "#2ecc71"

    def __init__(self, spec):
        super().__init__(spec)
        opts = spec.widget_opts
        self.style = opts.get("style", "graph")
        self.color = opts.get("color", self.default_color)
        self.history: deque[float] = deque(maxlen=W - 12)
        self.value: float | None = None

    def read(self) -> float | None:
        raise NotImplementedError

    def text(self) -> str:
        return "n/a" if self.value is None else f"{self.value:.0f}%"

    def fraction(self) -> float:
        return 0.0 if self.value is None else max(0.0, min(1.0, self.value / 100))

    def sample(self):
        self.value = self.read()
        if self.value is not None:
            self.history.append(self.fraction())

    def render(self):
        im, d = self._canvas()
        title = self.spec.label or self.title
        d.text((W / 2, 14), title, fill=self.spec.fg, font=font(14), anchor="mm")
        if self.style == "text":
            d.text((W / 2, 58), self.text(), fill=self.spec.fg, font=font(30), anchor="mm")
            return im
        d.text((W / 2, 38), self.text(), fill=self.spec.fg, font=font(22), anchor="mm")
        x0, x1, y0, y1 = 6, W - 6, 54, W - 8
        d.rectangle((x0, y0, x1, y1), outline="#555555")
        if self.style == "bar":
            fill_x = x0 + 1 + (x1 - x0 - 2) * self.fraction()
            if self.value is not None:
                d.rectangle((x0 + 1, y0 + 1, fill_x, y1 - 1), fill=self._level_color(self.fraction()))
        else:
            pts = list(self.history)
            if pts:
                h = y1 - y0 - 2
                start = x1 - 1 - len(pts) + 1
                poly = [(start, y1 - 1)]
                poly += [(start + i, y1 - 1 - v * h) for i, v in enumerate(pts)]
                poly += [(start + len(pts) - 1, y1 - 1)]
                d.polygon(poly, fill=self._dim(self.color))
                d.line(poly[1:-1], fill=self.color, width=1)
        return im

    def _level_color(self, f: float) -> str:
        if "color" in self.spec.widget_opts:
            return self.color
        return "#e74c3c" if f > 0.85 else "#f39c12" if f > 0.6 else self.color

    @staticmethod
    def _dim(color: str) -> tuple[int, int, int]:
        rgb = Image.new("RGB", (1, 1), color).getpixel((0, 0))
        return tuple(int(c * 0.35) for c in rgb)


class Cpu(Meter):
    title = "CPU"
    default_color = "#3498db"

    def __init__(self, spec, stat_path: Path = Path("/proc/stat")):
        super().__init__(spec)
        self.path = stat_path
        self.prev: tuple[int, int] | None = None

    def read(self):
        fields = [int(x) for x in self.path.read_text().split("\n", 1)[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)     # idle + iowait
        total = sum(fields[:8])                                     # exclude guest (counted in user)
        prev, self.prev = self.prev, (idle, total)
        if prev is None or total == prev[1]:
            return self.value
        return 100.0 * (1 - (idle - prev[0]) / (total - prev[1]))


class Ram(Meter):
    title = "RAM"
    default_color = "#9b59b6"

    def __init__(self, spec, meminfo: Path = Path("/proc/meminfo")):
        super().__init__(spec)
        self.path = meminfo
        self.used_gb = 0.0

    def read(self):
        info = {}
        for line in self.path.read_text().splitlines():
            k, _, rest = line.partition(":")
            info[k] = int(rest.split()[0])
        total, avail = info["MemTotal"], info["MemAvailable"]
        self.used_gb = (total - avail) / 1024 / 1024
        return 100.0 * (total - avail) / total


class Temp(Meter):
    title = "Temp"
    default_color = "#e67e22"
    default_interval = 2.0

    def __init__(self, spec):
        super().__init__(spec)
        self.sensor = find_temp_sensor(spec.widget_opts.get("sensor"))

    def read(self):
        if self.sensor is None:
            return None
        return int(self.sensor.read_text()) / 1000

    def text(self):
        return "n/a" if self.value is None else f"{self.value:.0f}°C"

    def fraction(self):
        # 30 °C .. 100 °C mapped to 0..1
        return 0.0 if self.value is None else max(0.0, min(1.0, (self.value - 30) / 70))


PREFERRED_HWMON = ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz")


def find_temp_sensor(sensor: str | None = None, root: Path = Path("/sys/class")) -> Path | None:
    """A temp*_input file: explicit path, a hwmon chip name, or the best CPU sensor."""
    if sensor and Path(sensor).is_absolute():
        return Path(sensor) if Path(sensor).exists() else None
    chips = {}
    for hw in sorted((root / "hwmon").glob("hwmon*")):
        try:
            name = (hw / "name").read_text().strip()
        except OSError:
            continue
        inputs = sorted(hw.glob("temp*_input"))
        if inputs:
            chips.setdefault(name, inputs[0])
    for name in ((sensor,) if sensor else PREFERRED_HWMON):
        if name in chips:
            return chips[name]
    if sensor is None:
        zones = sorted((root / "thermal").glob("thermal_zone*/temp"))
        if zones:
            return zones[0]
        if chips:
            return next(iter(chips.values()))
    return None


# --- command ---------------------------------------------------------------

class AsyncWidget(Widget):
    """Widget whose data comes from a slow source (subprocess, network).

    ``fetch()`` runs in a background thread; the result is stored with
    ``apply()`` and the controller is told via ``poll_changed()``. At most
    one fetch runs at a time, so a hung source never piles up threads.
    """

    def __init__(self, spec):
        super().__init__(spec)
        self._lock = threading.Lock()
        self._running = False
        self.changed = threading.Event()

    def fetch(self):
        raise NotImplementedError

    def apply(self, result) -> None:
        raise NotImplementedError

    def sample(self):
        self._start()

    def _start(self, before=None) -> bool:
        """Run ``before()`` (optional) then ``fetch()`` in a worker thread."""
        with self._lock:
            if self._running:
                return False
            self._running = True
        threading.Thread(target=self._run, args=(before,), daemon=True).start()
        return True

    def _run(self, before=None):
        try:
            if before is not None:
                before()
            result = self.fetch()
        except Exception:
            log.exception("%s fetch failed", type(self).__name__)
            result = None
        with self._lock:
            self.apply(result)
            self._running = False
        self.changed.set()

    def poll_changed(self):
        if self.changed.is_set():
            self.changed.clear()
            return True
        return False

    def wait(self, timeout: float = 5.0) -> bool:
        """Block until the next result arrives (tests, startup)."""
        ok = self.changed.wait(timeout)
        return ok


def _cmd(argv: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


class Command(AsyncWidget):
    """Shows the output of a shell command."""
    default_interval = 10.0

    def __init__(self, spec):
        super().__init__(spec)
        self.cmd = spec.widget_opts.get("command", "")
        self.output = "…"

    def fetch(self):
        try:
            r = subprocess.run(["/bin/sh", "-c", self.cmd], capture_output=True, text=True,
                               timeout=max(5.0, self.interval))
            return (r.stdout or r.stderr).strip() or "(empty)"
        except subprocess.TimeoutExpired:
            return "timeout"
        except OSError as e:
            return f"error: {e.strerror}"

    def apply(self, result):
        self.output = "\n".join((result or "error").splitlines()[:4])

    def render(self):
        from .render import render_key
        label = self.output if not self.spec.label else f"{self.spec.label}\n{self.output}"
        return render_key(KeySpec(label=label, bg=self.spec.bg, fg=self.spec.fg,
                                  font_size=self.spec.font_size))


# --- microphone -------------------------------------------------------------

LIVE_GREEN = "#1e8449"


class Mic(AsyncWidget):
    """Default microphone mute state; pressing toggles it.

    Uses PipeWire's ``wpctl`` when present, otherwise PulseAudio's ``pactl``.
    """
    default_interval = 1.0

    def __init__(self, spec, backend: str | None = None):
        super().__init__(spec)
        if backend is None:
            backend = next((b for b in ("wpctl", "pactl") if shutil.which(b)), None)
        self.backend = backend
        self.muted: bool | None = None          # None = no mic / no audio server

    def fetch(self):
        if self.backend == "wpctl":
            r = _cmd(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
            if r is None or r.returncode != 0 or "Volume:" not in r.stdout:
                return None
            return "[MUTED]" in r.stdout
        if self.backend == "pactl":
            r = _cmd(["pactl", "get-source-mute", "@DEFAULT_SOURCE@"])
            if r is None or r.returncode != 0 or "Mute:" not in r.stdout:
                return None
            return r.stdout.split(":", 1)[1].strip().lower() == "yes"
        return None

    def apply(self, result):
        self.muted = result

    def toggle_argv(self) -> list[str] | None:
        if self.backend == "wpctl":
            return ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"]
        if self.backend == "pactl":
            return ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"]
        return None

    def press(self) -> bool:
        argv = self.toggle_argv()
        if argv is None or self.muted is None:
            return True
        # Flip first so the worker's real reading always lands last.
        self.muted = not self.muted
        if not self._start(before=lambda: _cmd(argv)):
            # A fetch is already in flight: still toggle, re-read on the next tick.
            threading.Thread(target=_cmd, args=(argv,), daemon=True).start()
            self.next_due = 0.0
        return True

    def render(self):
        from . import icons
        from .render import render_key
        if self.muted is None:
            spec = KeySpec(icon=icons.Glyph("tabler", "microphone-off"), label=self.spec.label or "No mic",
                           bg="#222222", fg="#888888")
        elif self.muted:
            spec = KeySpec(icon=icons.Glyph("tabler", "microphone-off"), label=self.spec.label or "Muted",
                           bg=self.spec.widget_opts.get("color", "#c0392b"), fg="#ffffff")
        else:
            # Green unless the user picked a background for this key.
            bg = self.spec.bg if self.spec.bg.lower() not in ("#000", "#000000", "black") else LIVE_GREEN
            spec = KeySpec(icon=icons.Glyph("tabler", "microphone"), label=self.spec.label or "Live",
                           bg=bg, fg=self.spec.fg)
        return render_key(spec)


# --- now playing -------------------------------------------------------------

ART_MAX_BYTES = 5 * 1024 * 1024
SEP = "\x1f"


@dataclass
class Track:
    status: str          # Playing | Paused | Stopped
    art_url: str
    title: str
    artist: str


class NowPlaying(AsyncWidget):
    """Album art of the current MPRIS player (via playerctl). Press = play/pause."""
    default_interval = 2.0

    def __init__(self, spec):
        super().__init__(spec)
        self.player = spec.widget_opts.get("player")
        self.track: Track | None = None
        self.art: Image.Image | None = None
        self._art_url: str | None = None
        self.available = shutil.which("playerctl") is not None

    def _pc(self, *args) -> list[str]:
        return ["playerctl", *(["-p", self.player] if self.player else []), *args]

    def fetch(self):
        if not self.available:
            return None
        fmt = SEP.join(["{{status}}", "{{mpris:artUrl}}", "{{xesam:title}}", "{{xesam:artist}}"])
        r = _cmd(self._pc("metadata", "--format", fmt))
        if r is None or r.returncode != 0 or not r.stdout.strip():
            return None
        parts = (r.stdout.rstrip("\n").split(SEP) + [""] * 4)[:4]
        track = Track(*parts)
        art = self.art if track.art_url == self._art_url else load_art(track.art_url)
        return track, art

    def apply(self, result):
        if result is None:
            self.track, self.art, self._art_url = None, None, None
        else:
            self.track, self.art = result
            self._art_url = self.track.art_url

    def press(self) -> bool:
        if self.available:
            argv = self._pc("play-pause")
            if not self._start(before=lambda: _cmd(argv)):
                threading.Thread(target=_cmd, args=(argv,), daemon=True).start()
                self.next_due = 0.0
        return True

    def render(self):
        from . import icons
        from .render import render_key
        t = self.track
        if t is None:
            label = self.spec.label or ("No player" if self.available else "playerctl?")
            return render_key(KeySpec(icon=icons.Glyph("tabler", "music-off"), label=label,
                                      bg="#222222", fg="#888888"))
        playing = t.status == "Playing"
        if self.art is None:
            text = "\n".join(x for x in (t.title, t.artist) if x) or t.status
            im = render_key(KeySpec(label=text, bg=self.spec.bg, fg=self.spec.fg, font_size=13))
        else:
            im = ImageOps.fit(self.art, (W, W), Image.LANCZOS)
        if not playing:
            im = ImageEnhance.Brightness(im).enhance(0.4)
            glyph = icons.render_glyph(icons.Glyph("tabler-filled", "player-pause"), 44, "#ffffff")
            im.paste(glyph, ((W - glyph.width) // 2, (W - glyph.height) // 2), glyph)
        return im


def load_art(url: str) -> Image.Image | None:
    """Album art from a file:// or http(s):// URL, or None."""
    if not url:
        return None
    try:
        if url.startswith("file://"):
            path = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path))
            data = path.read_bytes()[:ART_MAX_BYTES + 1]
        elif url.startswith("data:image/") and ";base64," in url[:64]:
            encoded = url.split(",", 1)[1]
            if len(encoded) > ART_MAX_BYTES * 4 // 3 + 4:
                return None
            data = base64.b64decode(encoded)
        elif url.startswith(("http://", "https://")):
            req = urllib.request.Request(url, headers={"User-Agent": "streamplify-linux"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read(ART_MAX_BYTES + 1)
        else:
            return None
        if len(data) > ART_MAX_BYTES:
            return None
        im = Image.open(io.BytesIO(data))
        im.draft("RGB", (W * 2, W * 2))     # fast JPEG downscale on decode
        im = im.convert("RGB")
        im.thumbnail((W * 2, W * 2))
        return im
    except Exception:
        log.warning("could not load album art %s", url, exc_info=True)
        return None


REGISTRY: dict[str, type[Widget]] = {
    "clock": Clock,
    "cpu": Cpu,
    "ram": Ram,
    "temp": Temp,
    "command": Command,
    "mic": Mic,
    "nowplaying": NowPlaying,
}


def create_widget(spec: KeySpec) -> Widget:
    return REGISTRY[spec.widget](spec)
