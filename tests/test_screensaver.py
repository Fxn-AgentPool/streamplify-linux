import time

import pytest

from streamplify import config as cfgmod
from streamplify import screensaver
from streamplify.controller import Controller
from streamplify.device import KeyEvent

from .test_core import FakeDeck


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(saver=None, keys=None):
    data = {"pages": {"main": keys or {"1": {"label": "A", "run": "true"}, "2": {"widget": "clock"}},
                      "sub": {"1": {"label": "x"}}}}
    if saver is not None:
        data["screensaver"] = saver
    cfg = cfgmod.parse(data)
    deck = FakeDeck()
    ctl = Controller(deck, cfg)
    clock = Clock()
    ctl.clock = clock
    ctl.start()
    deck.reset()
    return deck, ctl, clock


# --- config -------------------------------------------------------------------

def test_defaults_ten_minutes_clock():
    cfg = cfgmod.parse({})
    assert cfg.screensaver.after == 600 and cfg.screensaver.mode == "clock"
    assert cfg.screensaver.enabled


def test_disable():
    assert not cfgmod.parse({"screensaver": False}).screensaver.enabled
    assert not cfgmod.parse({"screensaver": {"after": 0}}).screensaver.enabled


@pytest.mark.parametrize("raw, msg", [
    ({"mode": "fireworks"}, "mode must be"),
    ({"after": -5}, "after must be"),
    ({"brightness": 150}, "brightness must be"),
    ({"aftr": 60}, "unknown field"),
])
def test_config_errors(raw, msg):
    with pytest.raises(cfgmod.ConfigError, match=msg):
        cfgmod.parse({"screensaver": raw})


# --- rendering ------------------------------------------------------------------

def test_clock_canvas_slices_into_15_keys():
    cfg = screensaver.ScreensaverConfig()
    canvas = screensaver.render_clock(cfg, time.struct_time((2026, 11, 10, 12, 34, 0, 1, 314, 0)))
    assert canvas.size == (500, 300)
    tiles = screensaver.slice_canvas(canvas)
    assert sorted(tiles) == list(range(1, 16)) and all(t.size == (100, 100) for t in tiles.values())
    # middle of the deck has ink (digits), corners stay background
    assert tiles[8].getbbox() is not None
    assert tiles[11].getpixel((2, 2)) == (0, 0, 0)


# --- controller -----------------------------------------------------------------

def test_kicks_in_after_idle_time():
    deck, ctl, clock = make({"after": 60})
    clock.t += 59
    ctl.tick()
    assert not ctl.saver_active
    clock.t += 1
    ctl.tick()
    assert ctl.saver_active
    assert ("brightness", 20) in deck.log
    assert len(deck.uploads()) > 0                  # clock drawn


def test_key_press_resets_idle_timer():
    _, ctl, clock = make({"after": 60})
    clock.t += 50
    ctl.handle(KeyEvent(cfgmod.slot_to_key(3), True))
    ctl.handle(KeyEvent(cfgmod.slot_to_key(3), False))
    clock.t += 50
    ctl.tick()
    assert not ctl.saver_active


def test_wake_press_is_swallowed(monkeypatch):
    ran = []
    monkeypatch.setattr("streamplify.actions.run_command", lambda c: ran.append(c))
    deck, ctl, clock = make({"after": 60})
    clock.t += 61
    ctl.tick()
    deck.reset()
    k = cfgmod.slot_to_key(1)
    ctl.handle(KeyEvent(k, True))
    assert not ctl.saver_active
    assert ran == []                                 # the waking press did not run the action
    assert ("brightness", 80) in deck.log            # brightness restored
    ctl.handle(KeyEvent(k, False))                   # its release is swallowed too
    ctl.handle(KeyEvent(k, True))
    assert ran == ["true"]                           # next press works normally


def test_widgets_pause_and_resume():
    _, ctl, clock = make({"after": 60})
    assert ctl.widgets
    clock.t += 61
    ctl.tick()
    assert ctl.widgets == {}
    ctl.handle(KeyEvent(5, True))
    assert ctl.widgets


def test_clock_mode_only_uploads_changed_tiles(monkeypatch):
    t = [time.struct_time((2026, 11, 10, 12, 30, 0, 1, 314, 0))]
    monkeypatch.setattr(screensaver.time, "localtime", lambda: t[0])
    deck, ctl, clock = make({"after": 60, "date_format": ""})
    clock.t += 61
    ctl.tick()
    deck.reset()
    clock.t += 1.5
    ctl.tick()
    assert deck.uploads() == []                      # same minute: nothing re-sent
    t[0] = time.struct_time((2026, 11, 10, 12, 31, 0, 1, 314, 0))
    clock.t += 1.5
    ctl.tick()
    changed = deck.uploads()
    assert 0 < len(changed) < 15                     # only tiles with the changing digit


def test_blank_mode_turns_backlight_off_and_restores_everything():
    deck, ctl, clock = make({"after": 60, "mode": "blank"})
    clock.t += 61
    ctl.tick()
    assert ("brightness", 0) in deck.log and ("clear", None) in deck.log
    assert ctl.seconds_until_tick() == float("inf")
    deck.reset()
    ctl.handle(KeyEvent(5, True))
    assert sorted(deck.uploads()) == list(range(1, 16))   # full redraw after the screen was cleared


def test_dim_mode_keeps_page():
    deck, ctl, clock = make({"after": 60, "mode": "dim", "brightness": 10})
    clock.t += 61
    ctl.tick()
    assert ("brightness", 10) in deck.log
    assert deck.uploads() == []


def test_never_brightens_a_dimmer_deck():
    deck, ctl, clock = make({"after": 60, "brightness": 50})
    ctl.set_brightness(30)
    clock.t += 61
    ctl.tick()
    assert deck.log[-1] != ("brightness", 50)
    assert ("brightness", 30) in deck.log


def test_seconds_until_tick_includes_screensaver_start():
    _, ctl, clock = make({"after": 300}, keys={"1": {"label": "static"}})
    assert ctl.seconds_until_tick() == pytest.approx(300)
    clock.t += 100
    assert ctl.seconds_until_tick() == pytest.approx(200)


def test_reload_wakes_up():
    _, ctl, clock = make({"after": 60})
    clock.t += 61
    ctl.tick()
    ctl.reload(cfgmod.parse({"pages": {"main": {"1": {"label": "new"}}}}))
    assert not ctl.saver_active
