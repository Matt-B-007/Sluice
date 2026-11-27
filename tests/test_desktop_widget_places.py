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
    spec = clean_widget_spec(
        {
            "kind": "channel",
            "channel": "game",
            "x": 10,
            "y": 20,
            "screen": "eDP-1",
            "places": {"eDP-1": [10, 20], "bad": [1, "x"], 5: [1, 2], "big": [1, 99999]},
        }
    )
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
    optional_gone = desktop_place.LayerShell(
        loader=lambda: FakeLibrary(missing=("setKeyboardInteractivity", "setScreen")), env=KDE, platform="wayland"
    )
    assert optional_gone.available and set(optional_gone.missing_optional()) == {"setKeyboardInteractivity", "setScreen"}
    assert optional_gone.attach(object(), pointer=1)  # works without them


def test_a_layer_shell_widget_is_put_on_the_top_layer_and_moved_by_its_margins():
    lib = FakeLibrary()
    shell = desktop_place.LayerShell(loader=lambda: lib, env=KDE, platform="wayland")
    window = object()
    assert shell.attach(window, pointer=0xBEEF) and shell.is_attached(window)
    names = [name for name, _ in lib.calls]
    assert names[:7] == [
        "get",
        "setLayer",
        "setAnchors",
        "setKeyboardInteractivity",
        "setExclusiveZone",
        "setWantsToBeOnActiveScreen",
        "setActivateOnShow",
    ]
    assert lib.calls[5][1][1] is False and lib.calls[6][1][1] is False  # stays on its screen, takes no focus
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
    # 0.11.7: and out of the taskbar, the pager and Alt-Tab
    for key in ("skiptaskbar", "skippager", "skipswitcher"):
        assert pairs[key] == "true" and pairs[key + "rule"] == "2"


# ---------------------------------------------------------------- the widgets in the window
def make(qapp, tmp_path, skin="calm"):
    mixer = Mixer.demo()
    mixer.skin = skin
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
        event = QWheelEvent(
            point,
            widget.mapToGlobal(point.toPoint()).toPointF(),
            QPointF(0, 0).toPoint(),
            QPointF(0, 120).toPoint(),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        before = engine.mixer.channel("game").levels[engine.mixer.mixes[1].id]
        widget.wheelEvent(event)
        assert engine.mixer.channel("game").levels[engine.mixer.mixes[1].id] == before + 1.0
        for skin in ("calm", "nexus", "tile", "glass"):  # it is drawn in every look
            win.choose_skin(skin)
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


# What `nm -D --defined-only /usr/lib/libLayerShellQtInterface.so.6` printed on a Plasma 6 system (CachyOS, November 2026): the
# names Sluice asks for must be among these, spelled exactly.
PLASMA_6_EXPORTS = """
_ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE
_ZN12LayerShellQt6Window10setMarginsERK8QMargins
_ZN12LayerShellQt6Window14setDesiredSizeERK5QSize
_ZN12LayerShellQt6Window16setExclusiveEdgeENS0_6AnchorE
_ZN12LayerShellQt6Window16setExclusiveZoneEi
_ZN12LayerShellQt6Window17setActivateOnShowEb
_ZN12LayerShellQt6Window19setCloseOnDismissedEb
_ZN12LayerShellQt6Window22setScreenConfigurationENS0_19ScreenConfigurationE
_ZN12LayerShellQt6Window24setKeyboardInteractivityENS0_21KeyboardInteractivityE
_ZN12LayerShellQt6Window26setWantsToBeOnActiveScreenEb
_ZN12LayerShellQt6Window3getEP7QWindow
_ZN12LayerShellQt6Window8setLayerENS0_5LayerE
_ZN12LayerShellQt6Window8setScopeERK7QString
_ZN12LayerShellQt6Window9setScreenEP7QScreen
""".split()


def test_every_layer_shell_name_is_one_the_plasma_6_library_exports():
    assert set(desktop_place.SYMBOLS.values()) <= set(PLASMA_6_EXPORTS)


def test_mangled_names_count_their_lengths_right():
    import re

    for name in desktop_place.SYMBOLS.values():
        rest = name[len("_ZN12LayerShellQt6Window") :]
        digits = re.match(r"\d+", rest).group(0)
        method = rest[len(digits) : len(digits) + int(digits)]
        assert method.isalpha() and method.startswith(("get", "set")) and rest[len(digits) + int(digits)] == "E", name
        for found in re.finditer(r"NS0_(\d+)", rest):  # a nested name of that many letters, then E
            count, after = int(found.group(1)), rest[found.end() :]
            assert after[:count].isalpha() and after[count] == "E", name
    assert desktop_place.nested("KeyboardInteractivity") == "NS0_21KeyboardInteractivityE"


def test_the_bug_report_says_how_widgets_are_shown(monkeypatch):
    monkeypatch.setattr(
        desktop_place, "_shell", desktop_place.LayerShell(env={"XDG_CURRENT_DESKTOP": "GNOME"}, platform="wayland")
    )
    assert desktop_place.status().startswith("ordinary windows (not KDE Plasma on Wayland")
    monkeypatch.setattr(desktop_place, "_shell", desktop_place.LayerShell(loader=FakeLibrary, env=KDE, platform="wayland"))
    assert desktop_place.status().startswith("KDE layer-shell")


# ---------------------------------------------------------------- dragging a layer-shell widget (0.11.7)
def test_a_layer_shell_widget_follows_the_pointer_without_lag_or_jumps(qapp, tmp_path, monkeypatch):
    """On KDE Wayland Sluice moves layer-shell widgets itself. Qt's screen position for the pointer is out of date there, so moving
    by it lagged and jumped. The widget now moves by the pointer's distance from where it was taken, inside the widget, one step
    per frame; this drives it with a compositor that applies each move only when the frame comes, and stale screen positions."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from sluice import desktop_place
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow

    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "c.json")
    try:
        win.desktop.open("channel", channel="mic", x=500, y=300)
        widget = win.desktop.open_widgets[("channel", None, "mic")]
        widget.layered = True
        widget.spec["x"], widget.spec["y"] = 500, 300
        shown = {"at": (500, 300)}  # where the compositor shows the surface (it lags one frame behind each move)
        asked = []

        class FakeShell:
            available = True

            def place(self, _window, x, y, _origin, _screen=None):
                asked.append((x, y))

            def forget(self, _window):
                pass

        monkeypatch.setattr(desktop_place, "layer_shell", lambda: FakeShell())

        def mouse(kind, pointer, buttons=Qt.MouseButton.LeftButton):
            local = QPointF(pointer[0] - shown["at"][0], pointer[1] - shown["at"][1])
            stale = QPointF(local)  # Qt's "screen" position: wrong for a layer-shell surface, and must not be used
            return QMouseEvent(kind, local, stale, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)

        def frame():  # the compositor shows the last move, then Qt says the frame is done
            if asked:
                shown["at"] = asked[-1]
            widget.event(QEvent(QEvent.Type.UpdateRequest))

        grab = (540, 320)  # pressed 40, 20 inside the widget
        widget.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, grab))
        for step in range(1, 41):  # a steady drag 5 px right and 2 px down per event, two events per frame
            widget.mouseMoveEvent(mouse(QEvent.Type.MouseMove, (grab[0] + 5 * step, grab[1] + 2 * step)))
            if step % 2 == 0:
                frame()
        frame()
        widget.mouseMoveEvent(mouse(QEvent.Type.MouseMove, (grab[0] + 200, grab[1] + 80)))
        frame()
        assert shown["at"] == (700, 380)  # exactly under the pointer: 40, 20 from where it was taken
        xs = [x for x, _y in asked]
        assert xs == sorted(xs) and all(b - a <= 20 for a, b in zip(xs, xs[1:]))  # always forward, never a jump
        widget.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, (grab[0] + 200, grab[1] + 80), Qt.MouseButton.NoButton))
        assert not widget._dragging
    finally:
        win.shutdown()
