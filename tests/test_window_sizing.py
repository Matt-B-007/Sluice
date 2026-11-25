# SPDX-License-Identifier: GPL-3.0-or-later
"""The window arranges itself at the size it has (wrapping cards, a bar for Listen and Broadcast, the compact list)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from sluice import sizing, themes
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.flow import FlowLayout
from sluice.linker import NullLinker
from sluice.model import Mixer
from sluice.ui import MainWindow

from layout_checks import problems


def make(qapp, tmp_path, skin="calm", layout="columns", size=(1456, 800), many_apps=False, theme="dark"):
    mixer = Mixer.demo()
    mixer.skin, mixer.layout, mixer.theme = skin, layout, theme
    if many_apps:
        mixer.channels[2].apps = ["steam:1091500", "cs2", "steam:5335510", "steam:1240440", "steam:949230"]
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.resize(*size)
    win.show()
    settle(qapp)
    return win, engine


def settle(qapp):
    for _ in range(6):
        qapp.processEvents()


# ---------------------------------------------------------------- the plan (pure)
@pytest.mark.parametrize("size,layout,skin,expected", [
    ((1456, 800), "columns", "calm", ("columns", "right", "standard")),
    ((1920, 1080), "columns", "nexus", ("columns", "right", "roomy")),
    ((1100, 800), "columns", "calm", ("columns", "bottom", "compact")),
    ((900, 800), "columns", "nexus", ("columns", "bottom", "compact")),
    ((1100, 600), "columns", "calm", ("mini", "right", "mini")),      # a bar under the channels would leave them no room
    ((700, 900), "columns", "calm", ("mini", "right", "mini")),       # tall and narrow: the compact list
    ((1456, 400), "columns", "calm", ("mini", "right", "mini")),      # too short for cards
    ((1500, 800), "rows", "calm", ("rows", "right", "standard")),
    ((1300, 800), "rows", "calm", ("rows", "bottom", "standard")),
    ((960, 800), "rows", "calm", ("mini", "right", "mini")),
    ((1500, 800), "free", "nexus", ("columns", "right", "standard")),  # Free is gone (0.11.5): a saved Free shows Columns
    ((1500, 800), "free", "calm", ("columns", "right", "standard")),
    ((1500, 800), "nonsense", "calm", ("columns", "right", "standard")),
])
def test_the_plan_for_a_size(size, layout, skin, expected):
    plan = sizing.plan_for(size[0], size[1], layout, skin)
    assert tuple(plan) == expected


def test_a_plan_is_kept_close_to_the_edge_so_dragging_does_not_flicker():
    plan, changes = None, 0
    for width in list(range(1300, 1100, -4)) + list(range(1100, 1300, 4)):
        new = sizing.plan_for(width, 800, "columns", "calm", plan)
        changes += new != plan
        plan = new
    assert changes <= 3  # first plan, one switch down, one switch up
    seen = sizing.plan_for(1170, 800, "columns", "calm", sizing.plan_for(1300, 800, "columns", "calm"))
    assert seen.dock == "right"  # within the margin of the edge it changed at: unchanged


def test_every_plan_is_one_of_the_known_values():
    for width in range(300, 2700, 37):
        for height in range(280, 1500, 61):
            for layout in ("columns", "rows", "free", "?"):
                for skin in themes.SKINS:
                    plan = sizing.plan_for(width, height, layout, skin)
                    assert plan.mode in ("columns", "rows", "mini") and plan.dock in ("right", "bottom")
                    assert plan.step in sizing.STEPS


# ---------------------------------------------------------------- the flow layout
def test_a_flow_layout_wraps_and_grows_taller_as_it_narrows(qapp):
    box = QWidget()
    flow = FlowLayout(box, 10)
    for _ in range(6):
        card = QLabel("card")
        card.setFixedSize(100, 50)
        flow.addWidget(card)
    flow.addStretch(1)
    assert flow.count() == 6
    assert flow.heightForWidth(1000) == 50                 # one line
    assert flow.heightForWidth(340) == 2 * 50 + 10         # three a line
    assert flow.heightForWidth(100) == 6 * 50 + 5 * 10     # one a line
    box.resize(340, 200)
    box.show()
    settle(qapp)
    tops = sorted({flow.itemAt(i).geometry().y() for i in range(6)})
    assert tops == [0, 60]
    taken = flow.takeAt(0)
    assert taken is not None and flow.count() == 5


# ---------------------------------------------------------------- the window
def test_the_window_follows_its_size_and_never_changes_the_saved_layout(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "nexus", "columns")
    try:
        assert (win.layout_mode, win._dock) == ("columns", "right")
        win.resize(1100, 800); settle(qapp)
        assert (win.layout_mode, win._dock) == ("columns", "bottom")
        win.resize(700, 900); settle(qapp)
        assert win.layout_mode == "mini" and win.mini is not None
        assert engine.mixer.layout == "columns"
        assert win.layout_buttons["columns"].isChecked()  # the choice is still shown
        win.resize(1456, 800); settle(qapp)
        assert (win.layout_mode, win._dock) == ("columns", "right") and win.mini is None
        assert win._relayouts == 3
    finally:
        win.shutdown()


def test_resizing_inside_one_arrangement_does_not_rebuild_the_cards(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, "calm", "columns", (1500, 900))
    try:
        cards = list(win.strips)
        before = win._relayouts
        for width in (1480, 1420, 1360, 1300, 1250):
            win.resize(width, 900); settle(qapp)
        assert win.strips == cards and win._relayouts == before
    finally:
        win.shutdown()


def test_the_window_can_be_made_small_and_keeps_its_choices(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "calm", "rows", (380, 320))
    try:
        assert win.width() == 380 and win.height() == 320
        assert win.minimumWidth() <= 360 and win.minimumHeight() <= 300
        assert win.layout_mode == "mini" and engine.mixer.layout == "rows"
    finally:
        win.shutdown()


def test_a_look_change_in_a_small_window_keeps_the_compact_list(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, "calm", "columns", (560, 900))
    try:
        win.choose_skin("nexus"); settle(qapp)
        assert win.layout_mode == "mini"
        win.choose_skin("glass"); settle(qapp)
        assert win.layout_mode == "mini"
        win.set_layout("rows"); settle(qapp)
        assert win.engine.mixer.layout == "rows" and win.layout_mode == "mini"
    finally:
        win.shutdown()


# ---------------------------------------------------------------- the compact list does the same things as the cards
def test_the_compact_list_changes_levels_mutes_and_the_main_level(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "calm", "columns", (500, 800))
    try:
        mini = win.mini
        assert set(mini.rows) == {c.id for c in engine.mixer.channels}
        row = mini.rows["game"]
        engine.set_linked("game", False)  # linked channels move both mixes together
        row.fader.setGain(-120)
        game = next(c for c in engine.mixer.channels if c.id == "game")
        assert game.levels["monitor"] == pytest.approx(-12.0)
        row.mute.click()
        assert game.mutes["monitor"] is True
        mini.choice_buttons["stream"].click()
        row.fader.setGain(-60)
        assert game.levels["stream"] == pytest.approx(-6.0) and game.levels["monitor"] == pytest.approx(-12.0)
        mini.master_row.fader.setGain(-30)
        mix = next(m for m in engine.mixer.mixes if m.id == "stream")
        assert mix.gain_db == pytest.approx(-3.0)
        mini.master_row.mute.click()
        assert mix.mute is True
        # a change from elsewhere (a controller, `sluice ctl`) shows in the list
        engine.set_level("game", "stream", -20.0)
        win.sync_from_model()
        assert row.fader.gain() == -200 and row.readout.text() == "-20.0 dB"
    finally:
        win.shutdown()


def test_adding_and_removing_a_channel_updates_the_compact_list(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "calm", "columns", (500, 800))
    try:
        count = len(win.mini.rows)
        engine.add_channel("Music")
        win.rebuild_channels()
        assert len(win.mini.rows) == count + 1 and "music" in win.mini.rows
        win.remove_channel("music")
        assert len(win.mini.rows) == count
    finally:
        win.shutdown()


# ---------------------------------------------------------------- nothing overlaps, nothing is cut off
SIZES = [(1456, 800), (1280, 800), (1100, 800), (900, 800), (800, 600), (700, 900), (480, 700), (1920, 1080), (1280, 430), (380, 320)]


@pytest.mark.parametrize("skin,layout,theme", [("calm", "columns", "dark"), ("calm", "rows", "dark"),
                                               ("nexus", "columns", "dark"), ("nexus", "rows", "dark"),
                                               ("tile", "columns", "dark"), ("tile", "rows", "dark"),
                                               ("tile", "columns", "light"), ("tile", "rows", "light"),
                                               ("calm", "columns", "light"), ("glass", "columns", "dark"),
                                               ("glass", "rows", "light")])
def test_no_look_or_layout_overlaps_or_cuts_off_at_any_size(qapp, tmp_path, skin, layout, theme):
    found = []
    for size in SIZES:
        win, _ = make(qapp, tmp_path, skin, layout, size, many_apps=True, theme=theme)
        try:
            found += problems(win, size, f"{skin}/{layout}/{size[0]}x{size[1]} [{win.layout_mode},{win._dock},{win._plan.step}]")
        finally:
            win.shutdown()
    assert found == [], "\n".join(map(str, found[:12]))


# ---------------------------------------------------------------- the View menu
def test_the_nexus_items_are_only_in_view_while_the_look_is_nexus(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "calm", "columns")
    try:
        win._refresh_view_menu()
        for action in (win.skin_colors_action, win.reduce_action, win.nexus_section):
            assert not action.isVisible()
        win.choose_skin("nexus"); settle(qapp)
        for action in (win.skin_colors_action, win.reduce_action, win.nexus_section):
            assert action.isVisible()
        win.choose_skin("calm"); settle(qapp)
        assert not win.reduce_action.isVisible()
    finally:
        win.shutdown()


def test_the_look_colours_switch_is_one_item_and_not_in_the_theme_menu(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "nexus", "columns")
    try:
        win._fill_theme_menu()
        assert not any("colours" in a.text().lower() and "look" in a.text().lower() for a in win.theme_menu.actions())
        win._refresh_view_menu()
        assert win.skin_colors_action.isChecked() and engine.mixer.skin_colors
        win.skin_colors_action.trigger()
        assert engine.mixer.skin_colors is False
        win._refresh_view_menu()
        assert not win.skin_colors_action.isChecked()
    finally:
        win.shutdown()


# ---------------------------------------------------------------- the bug report
def test_the_report_says_how_the_window_was_arranged_and_where_its_parts_are(qapp, tmp_path):
    from sluice import report
    win, _ = make(qapp, tmp_path, "nexus", "columns", (1100, 800))
    try:
        line = report.window_summary()
        assert line.startswith("Window: 1100x800 px on a ") and "Size step: compact" in line
        assert "Arrangement: columns, Listen and Broadcast in a bar under the channels" in line
        assert "(chosen: columns; switched by the window's size: no)" in line and "Skin's own colours: on." in line
        layout = report.window_layout()
        assert "window            1100x800" in layout and "top bar" in layout and "channel area" in layout and "mix monitor" in layout
        assert "scrolls" in layout and "card mic" in layout
        text = report.build_report(log_lines=5)
        assert "===== Window layout" in text and "Window: 1100x800 px" in text
        win.resize(700, 900); settle(qapp)
        line = report.window_summary()
        assert "Arrangement: mini (chosen: columns; switched by the window's size: yes)" in line and "Size step: mini" in line
        assert "compact list" in report.window_layout()
    finally:
        win.shutdown()
    assert report.window_summary() == "" and report.window_layout() == ""  # nothing stale after the window is gone


def test_the_report_still_builds_when_the_window_cannot_say_anything(monkeypatch):
    from sluice import report
    def broken():
        raise RuntimeError("boom")
    report.set_window_source(broken)
    try:
        assert "could not read: RuntimeError: boom" in report.window_summary()
        assert report.window_layout() == ""
    finally:
        report.set_window_source(None)


def test_a_machine_name_in_a_kernel_log_line_is_hidden_whatever_it_was(monkeypatch):
    from sluice import report
    monkeypatch.setattr(report.platform, "node", lambda: "newname")
    text = ("2026-11-19T17:33:21-08:00 oldname kernel: usb 1-1.3: Manufacturer: CORSAIR\n"
            "2026-11-19T17:34:29-08:00 newname kernel: usb 1-1.4: USB disconnect, device number 4\n")
    clean = report.anonymize(text)
    assert "oldname" not in clean and "newname" not in clean
    assert clean.count("<host> kernel:") == 2 and "Manufacturer: CORSAIR" in clean


# ---------------------------------------------------------------- easy for everyone
@pytest.mark.parametrize("skin,layout,size", [("calm", "columns", (1456, 800)), ("calm", "rows", (1456, 900)), ("nexus", "columns", (1456, 800)),
                                              ("nexus", "rows", (1456, 800)), ("calm", "columns", (500, 800)), ("glass", "columns", (1456, 800)),
                                              ("tile", "rows", (1456, 900))])
def test_every_control_has_a_name_a_tooltip_and_can_be_reached_with_the_keyboard(qapp, tmp_path, skin, layout, size):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QComboBox

    win, _ = make(qapp, tmp_path, skin, layout, size)
    try:
        lacking = []
        for widget in win.findChildren(QWidget):
            if not widget.isVisible() or not isinstance(widget, (QAbstractButton, QAbstractSlider, QComboBox)):
                continue
            if type(widget).__name__ == "QScrollBar":
                continue
            name = widget.accessibleName() or (widget.text() if isinstance(widget, QAbstractButton) else "")
            what = (type(widget).__name__, widget.objectName(), name[:30])
            if not name.strip():
                lacking.append((*what, "no name"))
            if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
                lacking.append((*what, "no keyboard focus"))
            if not widget.toolTip().strip():
                lacking.append((*what, "no tooltip"))
        assert lacking == [], lacking[:10]
    finally:
        win.shutdown()


def test_the_first_run_card_offers_a_look_and_a_note_says_why_the_list_is_compact(qapp, tmp_path):
    mixer = Mixer.demo()
    for channel in mixer.channels:
        channel.apps = []
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.resize(1456, 800); win.show(); settle(qapp)
    try:
        assert win.first_run is not None
        assert [b.text() for b in win.first_run.buttons][-1] == "See the skins"
        win.resize(500, 800); settle(qapp)
        assert "compact list" in win.status_label.text()
        win.status_label.setText("")
        win.resize(1456, 800); settle(qapp)
        win.resize(500, 800); settle(qapp)
        assert win.status_label.text() == ""  # said once, not every time
    finally:
        win.shutdown()


# ---------------------------------------------------------------- the Tile look
def test_the_tile_look_is_a_look_with_its_own_sheet_for_every_theme():
    assert themes.SKINS["tile"] == "Tile" and themes.valid_skin("tile") == "tile"
    for theme in themes.BUILT_IN.values():
        sheet = themes.build_style(theme.colors, "tile")
        assert "$" not in sheet.replace("$$", "") and "QFrame#strip" in sheet and "QFrame#tileframe" in sheet, theme.id
        assert "border-bottom: 3px solid" in sheet.split("/* Tile")[1]  # 0.11.4: raised keys (a thick lower edge on the small keys)
        assert sheet != themes.build_style(theme.colors, "calm")


def test_tiles_take_their_own_key_colours_on_dark_and_light_while_the_look_colours_are_on():
    from sluice import skin_tile
    dark, light, contrast = themes.BUILT_IN["dark"], themes.BUILT_IN["light"], themes.BUILT_IN["contrast"]
    try:
        themes.set_skin_colors(True)
        tiled = themes.skin_colors(dark, "tile")
        assert tiled["panel"] == skin_tile.TILE_DARK["panel"] and tiled["text"] == "#eef2f5" and tiled["track"] == "#14171b"
        midnight = themes.BUILT_IN["midnight"]
        assert themes.skin_colors(midnight, "tile")["panel"] == midnight.colors["panel"]  # option A: only Dark and Light
        assert themes.skin_colors(light, "tile")["panel"] == skin_tile.TILE_LIGHT["panel"]
        assert themes.skin_colors(contrast, "tile") == themes.finish(contrast.colors)
        assert themes.skin_colors(contrast, "calm") == themes.finish(contrast.colors)  # 0.12.2: Calm has its own Dark and Light
        themes.set_skin_colors(False)
        assert themes.skin_colors(dark, "tile") == themes.finish(dark.colors)
    finally:
        themes.set_skin_colors(True)
    assert not skin_tile.is_light(tiled["panel"]) and skin_tile.is_light(light.colors["panel"]) and skin_tile.is_light("#fff")
    d, l = skin_tile.tile_colors(tiled, themes.mix), skin_tile.tile_colors(light.colors, themes.mix)
    assert d["tile_edge"] != l["tile_edge"] and d["skirt"] != l["skirt"]


def test_the_tile_look_has_no_glow_and_no_nexus_items(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, "tile", "columns")
    try:
        assert all(getattr(s, "ring", None) is None for s in win.strips)
        win._refresh_view_menu()
        assert not win.reduce_action.isVisible() and win.skin_colors_action.isVisible()
    finally:
        win.shutdown()


# ------------------------------------------------------------------------------------ desktop widgets and the live meters
def test_widget_specs_are_cleaned_and_saved(qapp, tmp_path):
    from sluice.model import MAX_DESKTOP_WIDGETS, Mixer, clean_widget_spec

    assert clean_widget_spec({"kind": "nope"}) is None and clean_widget_spec("x") is None
    assert clean_widget_spec({"kind": "dial", "mix": "listen", "x": True, "y": 10**9}) == {
        "kind": "dial", "mix": "listen", "channel": None, "x": None, "y": None}
    mixer = Mixer.demo()
    mixer.desktop_widgets = [{"kind": "mic", "mix": None, "channel": None, "x": 5, "y": 6}]
    again = Mixer.from_dict(mixer.to_dict())
    assert again.desktop_widgets == mixer.desktop_widgets
    data = mixer.to_dict()
    data["desktop_widgets"] = [{"kind": "mic"}] * 30 + ["junk", {"kind": "dial", "mix": "m"}]
    assert len(Mixer.from_dict(data).desktop_widgets) == 2  # the same widget 30 times is one, junk is dropped
    data["desktop_widgets"] = [{"kind": "dial", "mix": str(i)} for i in range(30)]
    assert len(Mixer.from_dict(data).desktop_widgets) == MAX_DESKTOP_WIDGETS


def test_widgets_open_close_and_come_back(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        d = win.desktop
        assert d.open("mic") and d.open("dial", "monitor") and d.open("strip")
        assert d.open("mic") and len(d.open_widgets) == 3 and len(engine.mixer.desktop_widgets) == 3
        assert not d.open("bogus")
        assert all(w.isVisible() for w in d.open_widgets.values())
        assert d.toggle("mic") is False and not d.is_open("mic") and len(engine.mixer.desktop_widgets) == 2
        saved = [dict(s) for s in engine.mixer.desktop_widgets]
        win.shutdown()  # closing Sluice closes them but remembers them
        assert not d.open_widgets and engine.mixer.desktop_widgets == saved
    finally:
        win.shutdown()


def test_saved_widgets_reappear_with_the_window(qapp, tmp_path):
    mixer = Mixer.demo()
    mixer.desktop_widgets = [{"kind": "mic", "mix": None, "channel": None, "x": 40, "y": 50}]
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "c.json")
    try:
        w = win.desktop.open_widgets[("mic", None, None)]
        assert w.isVisible() and (w.x(), w.y()) == (40, 50)
    finally:
        win.shutdown()


def test_mic_and_dial_widgets_do_their_one_thing(qapp, tmp_path):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    win, engine = make(qapp, tmp_path)
    try:
        win.desktop.open("mic")
        win.desktop.open("dial", "monitor")
        mic = win.desktop.open_widgets[("mic", None, None)]
        QTest.mouseClick(mic, Qt.MouseButton.LeftButton)
        assert engine.mic_muted
        QTest.mouseClick(mic, Qt.MouseButton.LeftButton)
        assert not engine.mic_muted
        dial = win.desktop.open_widgets[("dial", "monitor", None)]
        before = engine.mixer.mixes[0].gain_db

        def wheel(delta, mods=Qt.KeyboardModifier.NoModifier):
            dial.wheelEvent(QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, mods,
                                        Qt.ScrollPhase.NoScrollPhase, False))

        wheel(120)
        assert engine.mixer.mixes[0].gain_db == pytest.approx(before + 1.0)
        wheel(-120, Qt.KeyboardModifier.ShiftModifier)
        assert engine.mixer.mixes[0].gain_db == pytest.approx(before + 0.8)
        QTest.mouseClick(dial, Qt.MouseButton.LeftButton)
        assert engine.mixer.mixes[0].mute
        assert dial.grab().width() == dial.width()  # it paints
        mic.grab()
    finally:
        win.shutdown()


def test_widgets_only_repaint_when_something_changed(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        win.desktop.open("dial", "monitor")
        dial = win.desktop.open_widgets[("dial", "monitor", None)]
        calls = []
        dial.update = lambda *a: calls.append(1)
        for _ in range(5):
            dial.tick()
        assert not calls
        engine.set_master("monitor", -7.0)
        dial.tick()
        assert len(calls) == 1
        win.hide()
        assert dial.timer.isActive()  # they keep running for the desktop; the window's own meters stop
        dial.hide()
        assert not dial.timer.isActive()
    finally:
        win.shutdown()


def test_widgets_do_not_keep_sluice_alive(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        win.desktop.open("strip")
        assert not win.desktop.open_widgets[("strip", None, None)].testAttribute(Qt.WidgetAttribute.WA_QuitOnClose)
    finally:
        win.shutdown()


def test_view_menu_lists_and_toggles_widgets(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        win._fill_widgets_menu()
        texts = [a.text() for a in win.widgets_menu.actions() if not a.isSeparator()]
        assert texts == ["Microphone mute button", "Listen volume dial", "Broadcast volume dial", "Channel list", "Listen mix",
                         "Broadcast mix", "Channels", "Close all widgets"]
        win.widgets_menu.actions()[0].trigger()
        assert win.desktop.is_open("mic")
        win._fill_widgets_menu()
        assert win.widgets_menu.actions()[0].isChecked() and win.widgets_menu.actions()[-1].isEnabled()
        win.widgets_menu.actions()[-1].trigger()
        assert not win.desktop.open_widgets and win.engine.mixer.desktop_widgets == []
    finally:
        win.shutdown()


def test_control_meters_command(qapp):
    from sluice.control_socket import ControlApi

    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    try:
        out = ControlApi(engine).handle({"cmd": "meters"})
        assert out["ok"] and "mic_muted" in out and any(k.startswith("mix:") for k in out["meters"])
        assert all(0.0 <= v <= 1.0 for v in out["meters"].values())
    finally:
        engine.shutdown()


def test_control_watch_streams_and_cleans_up(qapp, tmp_path):
    import json as _json
    import threading

    from PySide6.QtCore import QCoreApplication

    from sluice import control_socket

    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    path = str(tmp_path / "w.sock")
    server = control_socket.ControlServer(control_socket.ControlApi(engine), path)
    got, err = [], []

    def client():
        try:
            control_socket.watch(got.append, path=path, limit=4)
        except Exception as exc:  # pragma: no cover
            err.append(exc)

    thread = threading.Thread(target=client)
    thread.start()
    while thread.is_alive():
        QCoreApplication.processEvents()
        thread.join(0.005)
    for _ in range(20):
        QCoreApplication.processEvents()
    try:
        assert not err and got[0].get("watching") is True
        assert sum("meters" in m for m in got) == 4
        assert not server._watchers and server._watch_timer is None  # the client left: nothing keeps running
        _json.dumps(got)
    finally:
        server.close()
        engine.shutdown()


def test_calm_fits_in_a_wider_fallback_font(qapp, tmp_path):
    """CI draws with DejaVu Sans, wider than the fonts on most desktops: nothing may be cut off there either."""
    from PySide6.QtGui import QFont

    saved = qapp.font()
    qapp.setFont(QFont("DejaVu Sans", 10))
    try:
        found = []
        for size in ((1456, 800), (900, 800), (1920, 1080)):
            win, _ = make(qapp, tmp_path, "calm", "columns", size, many_apps=True)
            try:
                found += problems(win, size, f"calm/{size}")
            finally:
                win.shutdown()
        assert found == [], "\n".join(map(str, found[:8]))
    finally:
        qapp.setFont(saved)


@pytest.mark.parametrize("skin", ["calm", "glass", "nexus"])
def test_the_default_window_shows_five_channels_in_one_row(qapp, tmp_path, skin):
    """0.11.7: the default window was meant to fit five channels beside Listen and Broadcast; from 0.11.5 it fitted four, and a
    report showed System pushed to a second row with the channel area scrolling."""
    from sluice.ui_base import DEFAULT_SIZE, default_size
    win, _ = make(qapp, tmp_path, skin, "columns", DEFAULT_SIZE)
    try:
        tops = {strip.mapTo(win, strip.rect().topLeft()).y() for strip in win.strips[:5]}
        assert len(win.strips) >= 5 and len(tops) == 1, (skin, sorted(tops))
        assert win._dock == "right"
    finally:
        win.shutdown()
    assert default_size((1366, 728)) == (1326, 688)  # a smaller screen: it fits the screen instead
    assert default_size(None) == DEFAULT_SIZE
