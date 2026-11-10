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

def make(keys, screensaver=False):
    cfg = cfgmod.parse({"pages": {"main": keys, "other": {"1": {"label": "x"}}},
                        "screensaver": screensaver})
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


# --- icons --------------------------------------------------------------------

def test_glyph_icon_config_and_suggestions():
    from streamplify import icons
    s = spec(icon="tabler:microphone", label="Mic")
    assert s.icon == icons.Glyph("tabler", "microphone")
    with pytest.raises(cfgmod.ConfigError, match="did you mean tabler:microphone"):
        spec(icon="tabler:microfone")
    with pytest.raises(cfgmod.ConfigError, match="only exists as outline"):
        spec(icon="tabler-filled:terminal-2")
    with pytest.raises(cfgmod.ConfigError, match="unknown icon set"):
        spec(icon="fa:home")


def test_glyph_renders_in_colour():
    from streamplify import icons
    im = icons.render_glyph(icons.Glyph("tabler-filled", "player-play"), 40, "#ff0000")
    assert max(im.size) == 40
    assert im.getpixel((im.width // 3, im.height // 2)) == (255, 0, 0, 255)   # inside the triangle


def test_file_icon_paths_still_work(tmp_path):
    s = cfgmod.parse({"pages": {"main": {"1": {"icon": "img.png"}}}}, base=tmp_path).pages["main"].keys[11]
    assert s.icon == tmp_path / "img.png"


# --- mic ------------------------------------------------------------------------

class FakeRun:
    """Stands in for widgets._cmd: answers by argv[:2], records calls."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, argv, timeout=2.0):
        import subprocess
        self.calls.append(argv)
        out = self.answers.get(tuple(argv[:2]))
        if callable(out):
            out = out()
        return None if out is None else subprocess.CompletedProcess(argv, 0, out, "")


def run_sync(w):
    """Run one async fetch and wait for it."""
    w.changed.clear()
    w.sample()
    assert w.wait(5)


@pytest.mark.parametrize("backend, out, muted", [
    ("wpctl", "Volume: 0.80\n", False),
    ("wpctl", "Volume: 0.80 [MUTED]\n", True),
    ("pactl", "Mute: yes\n", True),
    ("pactl", "Mute: no\n", False),
])
def test_mic_state(monkeypatch, backend, out, muted):
    fake = FakeRun({("wpctl", "get-volume"): out, ("pactl", "get-source-mute"): out})
    monkeypatch.setattr(widgets, "_cmd", fake)
    w = widgets.Mic(spec(widget="mic"), backend=backend)
    run_sync(w)
    assert w.muted is muted
    assert w.render().size == (100, 100)


def test_mic_toggle(monkeypatch):
    state = {"muted": False}
    def get():
        return "Volume: 1.00 [MUTED]\n" if state["muted"] else "Volume: 1.00\n"
    def toggle():
        state["muted"] = not state["muted"]
        return ""
    fake = FakeRun({("wpctl", "get-volume"): get, ("wpctl", "set-mute"): toggle})
    monkeypatch.setattr(widgets, "_cmd", fake)
    w = widgets.Mic(spec(widget="mic"), backend="wpctl")
    run_sync(w)
    assert w.muted is False
    w.changed.clear()
    w.press()
    assert w.muted is True                       # optimistic, before the worker finishes
    assert w.wait(5)
    assert w.muted is True and state["muted"] is True
    assert ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"] in fake.calls


def test_mic_without_audio_server(monkeypatch):
    monkeypatch.setattr(widgets, "_cmd", FakeRun({}))
    w = widgets.Mic(spec(widget="mic"), backend="wpctl")
    run_sync(w)
    assert w.muted is None
    w.press()                                    # no-op, must not raise
    assert w.render().size == (100, 100)


# --- now playing -------------------------------------------------------------------

def test_nowplaying_with_file_art(monkeypatch, tmp_path):
    from PIL import Image
    cover = tmp_path / "cover art.jpg"
    Image.new("RGB", (300, 300), "#ff0000").save(cover)
    meta = widgets.SEP.join(["Playing", cover.as_uri(), "Song", "Artist"]) + "\n"
    fake = FakeRun({("playerctl", "metadata"): meta})
    monkeypatch.setattr(widgets, "_cmd", fake)
    w = widgets.NowPlaying(spec(widget="nowplaying"))
    w.available = True
    run_sync(w)
    assert w.track.title == "Song" and w.art is not None
    playing = w.render()
    assert playing.getpixel((50, 50))[0] > 200   # red cover, full brightness

    w.track = widgets.Track("Paused", cover.as_uri(), "Song", "Artist")
    paused = w.render()
    assert paused.getpixel((5, 5))[0] < 120      # dimmed


def test_nowplaying_art_is_cached_per_url(monkeypatch, tmp_path):
    from PIL import Image
    cover = tmp_path / "c.png"
    Image.new("RGB", (50, 50), "blue").save(cover)
    meta = widgets.SEP.join(["Playing", cover.as_uri(), "A", "B"])
    monkeypatch.setattr(widgets, "_cmd", FakeRun({("playerctl", "metadata"): meta}))
    loads = []
    real = widgets.load_art
    monkeypatch.setattr(widgets, "load_art", lambda u: loads.append(u) or real(u))
    w = widgets.NowPlaying(spec(widget="nowplaying"))
    w.available = True
    run_sync(w)
    run_sync(w)
    assert len(loads) == 1


def test_nowplaying_no_player(monkeypatch):
    monkeypatch.setattr(widgets, "_cmd", FakeRun({}))
    w = widgets.NowPlaying(spec(widget="nowplaying"))
    w.available = True
    run_sync(w)
    assert w.track is None
    assert w.render().size == (100, 100)


def test_nowplaying_press_runs_play_pause(monkeypatch):
    fake = FakeRun({("playerctl", "-p"): ""})
    monkeypatch.setattr(widgets, "_cmd", fake)
    w = widgets.NowPlaying(spec(widget="nowplaying", player="spotify"))
    w.available = True
    w.changed.clear()
    w.press()
    assert w.wait(5)
    assert ["playerctl", "-p", "spotify", "play-pause"] in fake.calls


def test_load_art_rejects_unknown_schemes_and_huge_files(tmp_path, monkeypatch):
    assert widgets.load_art("ftp://x/y.jpg") is None
    assert widgets.load_art("") is None
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * 64)
    monkeypatch.setattr(widgets, "ART_MAX_BYTES", 32)
    assert widgets.load_art(big.as_uri()) is None


def test_widget_press_used_when_no_action(monkeypatch):
    monkeypatch.setattr(widgets, "_cmd", FakeRun({("wpctl", "get-volume"): "Volume: 1.00\n"}))
    monkeypatch.setattr(widgets.shutil, "which", lambda n: "/usr/bin/" + n)
    _deck, ctl = make({"1": {"widget": "mic"}})
    w = ctl.widgets[cfgmod.slot_to_key(1)]
    assert w.wait(5)
    pressed = []
    monkeypatch.setattr(w, "press", lambda: pressed.append(1) or True)
    ctl.handle(KeyEvent(cfgmod.slot_to_key(1), True))
    assert pressed == [1]


def test_load_art_data_uri():
    import base64
    import io as _io

    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (20, 20), "green").save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    im = widgets.load_art(uri)
    assert im is not None and im.getpixel((5, 5))[1] > 100


def test_mic_live_is_green_by_default_but_respects_bg():
    w = widgets.Mic(spec(widget="mic"), backend="wpctl")
    w.muted = False
    assert w.render().getpixel((2, 2)) == (30, 132, 73)
    w2 = widgets.Mic(spec(widget="mic", bg="#123456"), backend="wpctl")
    w2.muted = False
    assert w2.render().getpixel((2, 2)) == (0x12, 0x34, 0x56)
