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
from .screensaver import render_clock_tiles
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
        self.clock = time.monotonic             # injectable for tests
        self.last_input = self.clock()
        self.saver_active = False
        self._saver_next = 0.0
        self._swallow: set[int] = set()         # keys whose press woke the screensaver

    # --- state ---
    @property
    def page(self) -> str:
        return self.page_stack[-1]

    def spec(self, key: int) -> KeySpec:
        return self.config.pages[self.page].keys.get(key, BLANK)

    def start(self) -> None:
        """(Re)initialise the device, e.g. after connect."""
        self._sent.clear()
        self.saver_active = False
        self.last_input = self.clock()
        self.deck.wake()
        self.deck.brightness(self.brightness)
        self.deck.clear()
        self._build_widgets()
        self.redraw()

    def reload(self, config: Config) -> None:
        if self.saver_active:
            self.exit_saver()
        self.last_input = self.clock()
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
        """Advance widgets / screensaver; upload keys whose image changed."""
        now = self.clock() if now is None else now
        saver = self.config.screensaver
        if self.saver_active:
            return self._saver_tick(now)
        if saver.enabled and now - self.last_input >= saver.after:
            self.enter_saver(now)
            return len(self._sent)
        keys = []
        for key, w in self.widgets.items():
            if w.due(now):
                w.tick(now)
                keys.append(key)
            elif w.poll_changed():
                keys.append(key)
        return self.redraw(keys) if keys else 0

    def seconds_until_tick(self, now: float | None = None) -> float:
        now = self.clock() if now is None else now
        if self.saver_active:
            if self.config.screensaver.mode != "clock":
                return float("inf")
            return max(0.0, self._saver_next - now)
        due = [w.next_due for w in self.widgets.values()]
        if self.config.screensaver.enabled:
            due.append(self.last_input + self.config.screensaver.after)
        return max(0.0, min(due) - now) if due else float("inf")

    # --- screensaver ---
    def enter_saver(self, now: float | None = None) -> None:
        cfg = self.config.screensaver
        log.info("screensaver on (%s)", cfg.mode)
        self.saver_active = True
        self._held.clear()
        self.stop()                              # pause live keys
        if cfg.mode == "blank":
            self.deck.brightness(0)
            self.deck.clear()
            self.deck.refresh()
            self._sent.clear()                   # screen content is gone
            return
        self.deck.brightness(min(cfg.brightness, self.brightness))
        if cfg.mode == "clock":
            self._saver_next = 0.0
            self._saver_tick(self.clock() if now is None else now)

    def _saver_tick(self, now: float) -> int:
        if self.config.screensaver.mode != "clock" or now < self._saver_next:
            return 0
        self._saver_next = now + 1.0
        tiles = render_clock_tiles(self.config.screensaver)
        return self.flush({k: encode_key_image(im) for k, im in tiles.items()})

    def exit_saver(self) -> None:
        log.info("screensaver off")
        self.saver_active = False
        self.last_input = self.clock()
        self.deck.brightness(self.brightness)
        self._build_widgets()
        self.redraw()

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
        log.debug("key %d %s", ev.key, "down" if ev.pressed else "up")
        self.last_input = self.clock()
        if self.saver_active:
            if ev.pressed:
                self._swallow.add(ev.key)        # waking up must not trigger the key
                self.exit_saver()
            return
        if not ev.pressed and ev.key in self._swallow:
            self._swallow.discard(ev.key)
            return
        if ev.pressed:
            self._held.add(ev.key)
            self.redraw([ev.key])
            spec, w = self.spec(ev.key), self.widgets.get(ev.key)
            if spec.action is None and w is not None:
                try:
                    w.press()
                except Exception:
                    log.exception("widget press failed")
            else:
                self.trigger(spec)
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
