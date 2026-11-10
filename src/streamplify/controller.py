"""Owns the deck: pages, rendering, dirty-key diffing, key handling."""
from __future__ import annotations

import logging
import time
from typing import Protocol

from PIL import Image

from . import actions
from .config import Config, KeySpec
from .device import KEY_COUNT, KeyEvent, encode_key_image
from .render import BLANK, press_effect, render_key
from .widgets import Widget, create_widget

log = logging.getLogger(__name__)


class DeckLike(Protocol):
    def wake(self) -> None: ...
    def brightness(self, percent: int) -> None: ...
    def clear(self, key: int | None = None) -> None: ...
    def refresh(self) -> None: ...
    def upload_jpeg(self, key: int, jpeg: bytes) -> None: ...


class Controller:
    def __init__(self, deck: DeckLike, config: Config):
        self.deck = deck
        self.config = config
        self.page_stack: list[str] = [config.start_page]
        self.brightness = config.brightness
        self._sent: dict[int, bytes] = {}       # key -> last JPEG uploaded
        self._held: set[int] = set()
        self.widgets: dict[int, Widget] = {}    # live keys on the visible page

    # --- state ---
    @property
    def page(self) -> str:
        return self.page_stack[-1]

    def spec(self, key: int) -> KeySpec:
        return self.config.pages[self.page].keys.get(key, BLANK)

    def start(self) -> None:
        """(Re)initialise the device, e.g. after connect."""
        self._sent.clear()
        self.deck.wake()
        self.deck.brightness(self.brightness)
        self.deck.clear()
        self._build_widgets()
        self.redraw()

    def reload(self, config: Config) -> None:
        self.config = config
        self.page_stack = [p for p in self.page_stack if p in config.pages] or [config.start_page]
        if config.brightness != self.brightness:
            self.set_brightness(config.brightness)
        self._build_widgets()
        self.redraw()

    def stop(self) -> None:
        for w in self.widgets.values():
            w.close()
        self.widgets = {}

    # --- widgets ---
    def _build_widgets(self) -> None:
        self.stop()
        now = time.monotonic()
        for key, spec in self.config.pages[self.page].keys.items():
            if spec.widget:
                w = create_widget(spec)
                w.tick(now)
                self.widgets[key] = w

    def tick(self, now: float | None = None) -> int:
        """Sample due widgets and upload the ones whose image changed."""
        now = time.monotonic() if now is None else now
        keys = []
        for key, w in self.widgets.items():
            if w.due(now):
                w.tick(now)
                keys.append(key)
            elif w.poll_changed():
                keys.append(key)
        return self.redraw(keys) if keys else 0

    def seconds_until_tick(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        if not self.widgets:
            return float("inf")
        return max(0.0, min(w.next_due for w in self.widgets.values()) - now)

    # --- drawing ---
    def render(self, key: int) -> Image.Image:
        pressed = key in self._held
        w = self.widgets.get(key)
        if w is not None:
            im = w.render()
            return press_effect(im) if pressed else im
        return render_key(self.spec(key), pressed=pressed, font_path=self.config.font)

    def redraw(self, keys=None) -> int:
        """Upload keys whose image changed; one refresh. Returns #uploads."""
        keys = range(1, KEY_COUNT + 1) if keys is None else keys
        frames = {k: encode_key_image(self.render(k)) for k in keys}
        return self.flush(frames)

    def flush(self, frames: dict[int, bytes]) -> int:
        changed = {k: j for k, j in frames.items() if self._sent.get(k) != j}
        for k, j in changed.items():
            self.deck.upload_jpeg(k, j)
            self._sent[k] = j
        if changed:
            self.deck.refresh()
        return len(changed)

    # --- input ---
    def handle(self, ev: KeyEvent) -> None:
        if ev.pressed:
            self._held.add(ev.key)
            self.redraw([ev.key])
            self.trigger(self.spec(ev.key))
        else:
            self._held.discard(ev.key)
            self.redraw([ev.key])

    def trigger(self, spec: KeySpec) -> None:
        a = spec.action
        if a is None:
            return
        log.info("action %s=%r", a.kind, a.value)
        try:
            self._run_action(a)
        except Exception:
            # A broken action must never be mistaken for a lost device.
            log.exception("action %s failed", a.kind)

    def _run_action(self, a) -> None:
        if a.kind == "run":
            actions.run_command(a.value)
        elif a.kind == "url":
            actions.open_url(str(a.value))
        elif a.kind == "hotkey":
            actions.send_hotkey(str(a.value))
        elif a.kind == "page":
            self.goto(str(a.value))
        elif a.kind == "back":
            self.back()
        elif a.kind == "brightness":
            v = a.value
            self.set_brightness(self.brightness + int(v) if isinstance(v, str) else int(v))

    def goto(self, page: str) -> None:
        if page != self.page:
            self.page_stack.append(page)
            self._held.clear()
            self._build_widgets()
            self.redraw()

    def back(self) -> None:
        if len(self.page_stack) > 1:
            self.page_stack.pop()
            self._held.clear()
            self._build_widgets()
            self.redraw()

    def set_brightness(self, value: int) -> None:
        self.brightness = max(0, min(100, value))
        self.deck.brightness(self.brightness)
