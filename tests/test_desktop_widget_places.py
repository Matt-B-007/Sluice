# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop widgets in 0.11.5: a channel widget and a mix widget, snapping to screen edges and to each other, a place remembered on
each screen, KDE's layer-shell when it can be used (and an ordinary window when it cannot), and the KWin rule fallback."""
import ctypes
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402

from sluice import desktop_place  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer, clean_widget_spec  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402

SCREEN = (0, 0, 1920, 1080)


# ---------------------------------------------------------------- snapping and places (pure)
def test_a_widget_near_a_screen_edge_snaps_to_it():
    assert desktop_place.snap((10, 500, 200, 100), SCREEN, []) == (0, 500)
    assert desktop_place.snap((1712, 500, 200, 100), SCREEN, []) == (1720, 500)  # right edges meet
    assert desktop_place.snap((900, 1072 - 100, 200, 100), SCREEN, []) == (900, 980)
    assert desktop_place.snap((500, 500, 200, 100), SCREEN, []) == (500, 500)  # far from everything: stays


def test_a_widget_near_another_snaps_beside_it_with_a_gap_or_lines_up():
    other = (400, 300, 200, 100)
    x, y = desktop_place.snap((612, 304, 150, 80), SCREEN, [other])
    assert x == 400 + 200 + desktop_place.GAP and y == 300  # beside it, tops lined up
    x, y = desktop_place.snap((404, 410, 150, 80), SCREEN, [other])
    assert y == 300 + 100 + desktop_place.GAP and x == 400  # under it, left edges lined up


def test_a_widget_is_always_kept_on_its_screen():
    assert desktop_place.snap((-300, -50, 200, 100), SCREEN, []) == (0, 0)
    assert desktop_place.clamp((1900, 1070, 200, 100), SCREEN) == (1720, 980)


def test_a_place_is_remembered_on_each_screen_and_used_when_that_screen_is_back():
    spec = {"kind": "mic", "mix": None, "channel": None, "x": None, "y": None}
    desktop_place.remember(spec, "HDMI-1", 1950, 40)
    desktop_place.remember(spec, "eDP-1", 30, 700)
    screens = {"eDP-1": (0, 0, 1920, 1080), "HDMI-1": (1920, 0, 2560, 1440)}
    assert spec["screen"] == "eDP-1"
    assert desktop_place.place_for(spec, screens, "eDP-1", (84, 84)) == (30, 700)
    spec["screen"] = "HDMI-1"
    assert desktop_place.place_for(spec, screens, "eDP-1", (84, 84)) == (1950, 40)
    laptop_only = {"eDP-1": (0, 0, 1920, 1080)}
    assert desktop_place.place_for(spec, laptop_only, "eDP-1", (84, 84)) == (30, 700)  # its place on the screen that is here
    assert desktop_place.place_for({"x": 5000, "y": 40}, laptop_only, "eDP-1", (84, 84)) == (1836, 40)  # kept on the main screen
    assert desktop_place.place_for({"x": None, "y": None}, laptop_only, "eDP-1", (84, 84)) is None


def test_saved_places_are_cleaned_and_new_kinds_are_accepted():
    spec = clean_widget_spec({"kind": "channel", "channel": "game", "x": 10, "y": 20, "screen": "eDP-1",
                              "places": {"eDP-1": [10, 20], "bad": [1, "x"], 5: [1, 2], "big": [1, 99999]}})
    assert spec["places"] == {"eDP-1": [10, 20]} and spec["screen"] == "eDP-1"
    assert clean_widget_spec({"kind": "channel"}) is None  # a channel widget needs its channel
    assert clean_widget_spec({"kind": "mix", "mix": "stream"})["kind"] == "mix"
    many = {f"s{i}": [i, i] for i in range(20)}
    assert len(desktop_place.clean_places(many)) == desktop_place.MAX_PLACES


# ---------------------------------------------------------------- layer-shell (no KDE here: a stand-in library)
class FakeFunction:
    def __init__(self, calls, name, result=None):
        self.calls, self.name, self.result = calls, name, result
        self.argtypes = self.restype = None

    def __call__(self, *args):
        self.calls.append((self.name, args))
        return self.result


class FakeLibrary:
    def __init__(self, missing=()):
        self.calls = []
        for key, symbol in desktop_place.SYMBOLS.items():
            if key not in missing:
                setattr(self, symbol, FakeFunction(self.calls, key, 1234 if key == "get" else None))


KDE = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}


def test_layer_shell_is_only_used_on_kde_wayland_with_every_function_there():
    assert not desktop_place.LayerShell(loader=FakeLibrary, env={"XDG_CURRENT_DESKTOP": "GNOME"}, platform="wayland").available
    assert not desktop_place.LayerShell(loader=FakeLibrary, env={"XDG_CURRENT_DESKTOP": "KDE"}, platform="xcb").available
    assert not desktop_place.LayerShell(loader=lambda: None, env=KDE, platform="wayland").available
    missing = desktop_place.LayerShell(loader=lambda: FakeLibrary(missing=("setMargins",)), env=KDE, platform="wayland")
    assert not missing.available and "missing" in missing.reason
    assert desktop_place.LayerShell(loader=lambda: FakeLibrary(missing=("setScope",)), env=KDE, platform="wayland").available


def test_a_layer_shell_widget_is_put_on_the_top_layer_and_moved_by_its_margins():
    lib = FakeLibrary()
    shell = desktop_place.LayerShell(loader=lambda: lib, env=KDE, platform="wayland")
    window = object()
    assert shell.attach(window, pointer=0xBEEF) and shell.is_attached(window)
    names = [name for name, _ in lib.calls]
    assert names[:5] == ["get", "setLayer", "setAnchors", "setKeyboardInteractivity", "setExclusiveZone"]
    assert lib.calls[1][1][1] == desktop_place.LAYER_TOP
    assert lib.calls[2][1][1] == desktop_place.ANCHOR_TOP | desktop_place.ANCHOR_LEFT
    assert shell.place(window, 2000, 50, screen_origin=(1920, 0))
    margins = ctypes.cast(lib.calls[-1][1][1], ctypes.POINTER(desktop_place._Margins)).contents
    assert (margins.left, margins.top) == (80, 50)
    shell.forget(window)
    assert not shell.place(window, 1, 1)


def test_the_kwin_rule_keeps_the_widgets_above_and_is_found_by_title():
    commands = desktop_place.kwin_rule_commands("kwriteconfig6")
    pairs = {c[-2]: c[-1] for c in commands}
    assert pairs["title"] == desktop_place.RULE_TITLE and pairs["above"] == "true" and pairs["aboverule"] == "2"
    assert all(c[:3] == ["kwriteconfig6", "--file", "kwinrulesrc"] for c in commands)


# ---------------------------------------------------------------- the widgets in the window
def make(qapp, tmp_path, look="calm"):
    mixer = Mixer.demo()
    mixer.look = look
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.show()
    qapp.processEvents()
    return win, engine


def test_a_channel_widget_changes_levels_and_mutes_in_every_mix(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        assert win.desktop.open("channel", channel="game")
        widget = win.desktop.open_widgets[("channel", None, "game")]
        assert widget.windowTitle().startswith(desktop_place.RULE_TITLE)
        rows = widget._rows()
        assert [lane[0] for lane, *_ in rows] == [m.id for m in engine.mixer.mixes]
        (_lane, _row, mute, groove) = rows[1]
        widget.toggle_mute(engine.mixer.mixes[1].id)
        assert engine.mixer.channel("game").mutes[engine.mixer.mixes[1].id]
        widget.set_db(engine.mixer.mixes[0].id, -12.0)
        assert engine.mixer.channel("game").levels[engine.mixer.mixes[0].id] == -12.0
        point = groove.center()
        event = QWheelEvent(point, widget.mapToGlobal(point.toPoint()).toPointF(), QPointF(0, 0).toPoint(), QPointF(0, 120).toPoint(),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        before = engine.mixer.channel("game").levels[engine.mixer.mixes[1].id]
        widget.wheelEvent(event)
        assert engine.mixer.channel("game").levels[engine.mixer.mixes[1].id] == before + 1.0
        for look in ("calm", "nexus", "tile", "original"):  # it is drawn in every look
            win.choose_look(look)
            widget.grab()
    finally:
        win.shutdown()


def test_a_mix_widget_changes_the_level_mute_and_limiter(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "nexus")
    try:
        assert win.desktop.open("mix", "stream")
        widget = win.desktop.open_widgets[("mix", "stream", None)]
        mix = engine.mixer.mix("stream")
        widget.set_db("stream", -3.0)
        assert mix.gain_db == -3.0
        widget.toggle_mute("stream")
        assert mix.mute
        limiter = mix.limiter
        from PySide6.QtTest import QTest
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget._limiter_rect().center().toPoint())
        assert mix.limiter is (not limiter)
        widget.grab()
    finally:
        win.shutdown()


def test_widgets_snap_and_remember_their_screen_when_they_stop_moving(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        win.desktop.open("mic")
        widget = win.desktop.open_widgets[("mic", None, None)]
        area = widget.screen().availableGeometry()
        widget.move(area.left() + 9, area.top() + 300)
        widget.settle()
        assert widget.x() == area.left()
        assert widget.spec["places"][widget.screen().name() or "screen"] == [area.left(), area.top() + 300]
        saved = Mixer.from_dict(engine.mixer.to_dict()).desktop_widgets[0]
        assert saved["places"] == widget.spec["places"]
    finally:
        win.shutdown()


def test_the_widgets_menu_offers_channels_and_mixes(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        win._fill_widgets_menu()
        texts = [a.text() for a in win.widgets_menu.actions()]
        assert "Listen mix" in texts and "Broadcast mix" in texts
        channels = next(a.menu() for a in win.widgets_menu.actions() if a.menu() is not None and a.text() == "Channels")
        game = next(a for a in channels.actions() if a.text() == engine.mixer.channel("game").label)
        game.trigger()
        assert win.desktop.is_open("channel", None, "game")
    finally:
        win.shutdown()
