from pathlib import Path

import pytest

from streamplify import config as cfgmod
from streamplify.actions import hotkey_argv
from streamplify.controller import Controller
from streamplify.device import KEY_COUNT, KeyEvent, input_to_key, key_at, pos_of
from streamplify.render import render_key


class FakeDeck:
    def __init__(self):
        self.log = []

    def wake(self): self.log.append(("wake",))
    def brightness(self, p): self.log.append(("brightness", p))
    def clear(self, key=None): self.log.append(("clear", key))
    def refresh(self): self.log.append(("refresh",))
    def upload_jpeg(self, key, jpeg): self.log.append(("upload", key))

    def uploads(self):
        return [e[1] for e in self.log if e[0] == "upload"]

    def reset(self):
        self.log.clear()


# --- layout -------------------------------------------------------------------

def test_layout_roundtrip():
    for k in range(1, KEY_COUNT + 1):
        assert key_at(*pos_of(k)) == k
    assert key_at(2, 0) == 1        # bottom-left
    assert key_at(0, 0) == 11       # top-left


def test_input_mapping_swaps_top_and_bottom_rows():
    assert [input_to_key(i) for i in range(1, 16)] == [11, 12, 13, 14, 15, 6, 7, 8, 9, 10, 1, 2, 3, 4, 5]


def test_slot_reading_order():
    assert cfgmod.slot_to_key(1) == 11      # top-left
    assert cfgmod.slot_to_key(15) == 5      # bottom-right
    assert cfgmod.slot_to_key(8) == 8       # middle unchanged
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.slot_to_key(16)


# --- config -------------------------------------------------------------------

def test_example_config_parses():
    cfg = cfgmod.load(Path(cfgmod.__file__).with_name("example.toml"))
    assert cfg.start_page == "main"
    assert {"main", "media"} <= set(cfg.pages)
    assert cfg.pages["main"].keys[cfgmod.slot_to_key(1)].action.kind == "run"


@pytest.mark.parametrize("raw, msg", [
    ({"pages": {"main": {"1": {"run": "a", "url": "b"}}}}, "only one action"),
    ({"pages": {"main": {"1": {"lable": "typo"}}}}, "unknown field"),
    ({"pages": {"main": {"1": {"page": "nope"}}}}, "unknown page"),
    ({"pages": {"main": {"x": {}}}}, "must be a number"),
    ({"pages": {"main": {"1": {"brightness": "loud"}}}}, "brightness"),
])
def test_config_errors(raw, msg):
    with pytest.raises(cfgmod.ConfigError, match=msg):
        cfgmod.parse(raw)


def test_relative_icon_resolves_against_config_dir(tmp_path):
    cfg = cfgmod.parse({"pages": {"main": {"1": {"icon": "i.png"}}}}, base=tmp_path)
    assert cfg.pages["main"].keys[11].icon == tmp_path / "i.png"


# --- rendering ----------------------------------------------------------------

def test_render_sizes_and_pressed_differs():
    spec = cfgmod.KeySpec(label="A long label that wraps", bg="#123456")
    a, b = render_key(spec), render_key(spec, pressed=True)
    assert a.size == b.size == (100, 100)
    assert a.tobytes() != b.tobytes()


def test_render_with_icon(tmp_path):
    from PIL import Image
    p = tmp_path / "icon.png"
    Image.new("RGBA", (64, 32), "red").save(p)
    assert render_key(cfgmod.KeySpec(icon=p, label="x")).size == (100, 100)
    assert render_key(cfgmod.KeySpec(icon=tmp_path / "missing.png")).size == (100, 100)


# --- controller ---------------------------------------------------------------

def make(cfg_dict=None):
    cfg = cfgmod.parse(cfg_dict or {
        "pages": {
            "main": {"1": {"label": "A", "page": "sub"}, "2": {"label": "B", "brightness": "+10"}},
            "sub": {"1": {"label": "Back", "back": True}},
        }
    })
    deck = FakeDeck()
    ctl = Controller(deck, cfg)
    ctl.start()
    return deck, ctl


def test_start_uploads_every_key_once_with_one_refresh():
    deck, _ = make()
    assert sorted(deck.uploads()) == list(range(1, 16))
    assert deck.log.count(("refresh",)) == 1


def test_redraw_without_changes_uploads_nothing():
    deck, ctl = make()
    deck.reset()
    assert ctl.redraw() == 0
    assert deck.log == []


def test_press_feedback_only_touches_that_key():
    deck, ctl = make()
    deck.reset()
    k = cfgmod.slot_to_key(2)
    ctl.handle(KeyEvent(k, True))
    assert deck.uploads() == [k]
    deck.reset()
    ctl.handle(KeyEvent(k, False))
    assert deck.uploads() == [k]


def test_page_navigation_and_back():
    _, ctl = make()
    top_left = cfgmod.slot_to_key(1)
    ctl.handle(KeyEvent(top_left, True))
    assert ctl.page == "sub"
    ctl.handle(KeyEvent(top_left, False))
    ctl.handle(KeyEvent(top_left, True))
    assert ctl.page == "main"


def test_page_switch_only_uploads_changed_keys():
    deck, ctl = make()
    deck.reset()
    ctl.goto("sub")
    # main has 2 labelled keys, sub has 1: slot 1 changes label, slot 2 goes blank. Others stay blank.
    assert sorted(deck.uploads()) == sorted([cfgmod.slot_to_key(1), cfgmod.slot_to_key(2)])


def test_brightness_relative_and_clamped():
    deck, ctl = make()
    k = cfgmod.slot_to_key(2)
    for _ in range(5):
        ctl.handle(KeyEvent(k, True))
        ctl.handle(KeyEvent(k, False))
    assert ctl.brightness == 100
    assert ("brightness", 100) in deck.log


def test_reload_keeps_valid_page_and_redraws():
    deck, ctl = make()
    ctl.goto("sub")
    deck.reset()
    ctl.reload(cfgmod.parse({"pages": {"main": {"3": {"label": "new"}}}}))
    assert ctl.page == "main"
    assert deck.uploads()


# --- hotkeys ------------------------------------------------------------------

def test_hotkey_argv(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    assert hotkey_argv("Ctrl+Shift+M", wayland=False) == [
        "xdotool", "key", "--clearmodifiers", "ctrl+shift+m"]
    assert hotkey_argv("super+l", wayland=True) == ["wtype", "-M", "logo", "-k", "l", "-m", "logo"]
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert hotkey_argv("ctrl+c", wayland=False) is None
