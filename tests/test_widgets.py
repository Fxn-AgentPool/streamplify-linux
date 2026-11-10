import time

import pytest

from streamplify import config as cfgmod
from streamplify import widgets
from streamplify.controller import Controller
from streamplify.device import KeyEvent

from .test_core import FakeDeck


def spec(**raw):
    return cfgmod.parse({"pages": {"main": {"1": raw}}}).pages["main"].keys[cfgmod.slot_to_key(1)]


# --- config -------------------------------------------------------------------

@pytest.mark.parametrize("raw, msg", [
    ({"widget": "weather"}, "unknown widget"),
    ({"widget": "command"}, "needs command"),
    ({"widget": "cpu", "style": "pie"}, "style must be"),
    ({"widget": "clock", "interval": 0}, "interval"),
    ({"format": "%H"}, "only valid together with 'widget'"),
])
def test_widget_config_errors(raw, msg):
    with pytest.raises(cfgmod.ConfigError, match=msg):
        spec(**raw)


def test_widget_keeps_action():
    s = spec(widget="clock", format="%H:%M:%S", run="gnome-calendar")
    assert s.widget == "clock" and s.widget_opts == {"format": "%H:%M:%S"}
    assert s.action.kind == "run"


# --- meters -------------------------------------------------------------------

def test_cpu_from_proc_stat(tmp_path):
    stat = tmp_path / "stat"
    cpu = widgets.Cpu(spec(widget="cpu"), stat_path=stat)
    stat.write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    cpu.sample()
    assert cpu.value is None                   # first sample has no delta
    stat.write_text("cpu  150 0 150 900 0 0 0 0 0 0\n")   # +100 busy, +100 idle
    cpu.sample()
    assert cpu.value == pytest.approx(50.0)
    assert cpu.render().size == (100, 100)


def test_ram_from_meminfo(tmp_path):
    mi = tmp_path / "meminfo"
    mi.write_text("MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 250 kB\n")
    ram = widgets.Ram(spec(widget="ram", style="bar"), meminfo=mi)
    ram.sample()
    assert ram.value == pytest.approx(75.0)
    assert ram.render().size == (100, 100)


@pytest.mark.parametrize("style", ["graph", "bar", "text"])
def test_meter_styles_render(tmp_path, style):
    m = widgets.Ram(spec(widget="ram", style=style), meminfo=tmp_path / "x")
    m.value = 42.0
    m.history.extend([0.1, 0.5, 0.9])
    assert m.render().size == (100, 100)


def test_temp_sensor_discovery(tmp_path):
    for i, (name, milli) in enumerate([("nvme", 40000), ("k10temp", 55500)]):
        d = tmp_path / "hwmon" / f"hwmon{i}"
        d.mkdir(parents=True)
        (d / "name").write_text(name + "\n")
        (d / "temp1_input").write_text(f"{milli}\n")
    found = widgets.find_temp_sensor(root=tmp_path)
    assert found.parent.name == "hwmon1"                      # prefers the CPU sensor
    assert widgets.find_temp_sensor("nvme", root=tmp_path).parent.name == "hwmon0"
    assert widgets.find_temp_sensor("missing", root=tmp_path) is None


def test_temp_without_sensor_shows_na(monkeypatch):
    monkeypatch.setattr(widgets, "find_temp_sensor", lambda *a, **k: None)
    t = widgets.Temp(spec(widget="temp"))
    t.sample()
    assert t.text() == "n/a"


# --- command ------------------------------------------------------------------

def test_command_widget_runs_async():
    w = widgets.Command(spec(widget="command", command="echo hello; echo world"))
    w.sample()
    assert w.changed.wait(5)
    assert w.poll_changed() and not w.poll_changed()
    assert w.output == "hello\nworld"


# --- controller integration ----------------------------------------------------

def make(keys):
    cfg = cfgmod.parse({"pages": {"main": keys, "other": {"1": {"label": "x"}}}})
    deck = FakeDeck()
    ctl = Controller(deck, cfg)
    ctl.start()
    deck.reset()
    return deck, ctl


def test_clock_only_uploads_when_image_changes(monkeypatch):
    clock_key = cfgmod.slot_to_key(1)
    t = [time.struct_time((2026, 11, 10, 12, 30, 0, 0, 314, 0))]
    monkeypatch.setattr(widgets.time, "localtime", lambda: t[0])
    deck, ctl = make({"1": {"widget": "clock"}})
    ctl.widgets[clock_key].sample()
    ctl.redraw()
    deck.reset()

    now = time.monotonic()
    for i in range(1, 5):                                     # same minute, 4 ticks
        t[0] = time.struct_time((2026, 11, 10, 12, 30, i, 0, 314, 0))
        ctl.tick(now + i)
    assert deck.uploads() == []

    t[0] = time.struct_time((2026, 11, 10, 12, 31, 0, 0, 314, 0))
    ctl.tick(now + 10)
    assert deck.uploads() == [clock_key]
    assert deck.log.count(("refresh",)) == 1


def test_widgets_only_run_on_visible_page():
    _deck, ctl = make({"1": {"widget": "clock"}, "2": {"label": "go", "page": "other"}})
    assert set(ctl.widgets) == {cfgmod.slot_to_key(1)}
    ctl.handle(KeyEvent(cfgmod.slot_to_key(2), True))
    assert ctl.page == "other" and ctl.widgets == {}
    ctl.back()
    assert set(ctl.widgets) == {cfgmod.slot_to_key(1)}


def test_seconds_until_tick():
    _, ctl = make({"1": {"widget": "clock", "interval": 5}})
    now = time.monotonic()
    assert 4 < ctl.seconds_until_tick(now) <= 5
    _, ctl2 = make({"1": {"label": "static"}})
    assert ctl2.seconds_until_tick() == float("inf")


def test_pressed_widget_key_gets_feedback():
    deck, ctl = make({"1": {"widget": "ram"}})
    k = cfgmod.slot_to_key(1)
    ctl.handle(KeyEvent(k, True))
    assert deck.uploads() == [k]


def test_failing_action_does_not_raise(monkeypatch):
    _deck, ctl = make({"1": {"label": "x", "run": "true"}})
    def boom(_):
        raise OSError("nope")
    monkeypatch.setattr("streamplify.actions.run_command", boom)
    ctl.handle(KeyEvent(cfgmod.slot_to_key(1), True))       # must not propagate
