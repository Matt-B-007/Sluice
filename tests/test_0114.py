# SPDX-License-Identifier: GPL-3.0-or-later
"""0.11.4: the Tile look as raised keys (light and dark, Tile colours), lighter painting, fixes to spacing in every look, and fixes to
the Free layout, the command line's lock and the bug report."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest

from sluice import fonts, look_tile, sizing, themes
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import MONITOR, STREAM, Mixer
from sluice.ui import ElidedLabel, MainWindow

from layout_checks import problems


def make(qapp, tmp_path, look="tile", layout="columns", size=(1456, 860), theme="dark", recording=False, setup=None):
    mixer = Mixer.demo()
    mixer.look, mixer.layout, mixer.theme = look, layout, theme
    mixer.hints_seen.append("firstrun")
    if recording:
        mixer.set_recording_mix(True)
    if setup is not None:
        setup(mixer)
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.resize(*size)
    win.show()
    settle(qapp)
    return win, engine


def settle(qapp, n=6):
    for _ in range(n):
        qapp.processEvents()


# ---------------------------------------------------------------- the command line holds its lock
def test_rollback_holds_the_lock_until_the_files_are_back(tmp_path, monkeypatch, capsys):
    from sluice import __main__ as entry, selfupdate

    events = []

    class Lock:
        def close(self):
            events.append("released")

    monkeypatch.setattr(entry, "_acquire_lock", lambda: (events.append("locked"), Lock())[1])
    monkeypatch.setattr(selfupdate, "install_root", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "previous_version", lambda root: "0.11.3")
    monkeypatch.setattr(selfupdate, "rollback", lambda root: events.append("rolled back") or "0.11.3")
    assert entry.main(["--rollback"]) == 0
    assert events == ["locked", "rolled back", "released"]  # 0.11.3 dropped the lock before rolling back


def test_release_lock_closes_a_file_and_ignores_the_others(tmp_path):
    from sluice import __main__ as entry

    handle = open(tmp_path / "lock", "a+")
    entry._release_lock(handle)
    assert handle.closed
    entry._release_lock(True)   # no fcntl: nothing to close
    entry._release_lock(None)


# ---------------------------------------------------------------- raised keys
def test_tile_colours_are_saved_and_switched_from_the_view_menu(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        assert engine.mixer.tile_colors is True and themes.color("panel") == look_tile.TILE_DARK["panel"]
        win._refresh_view_menu()
        assert win.tile_colors_action.isVisible() and win.tile_colors_action.isChecked()
        win.tile_colors_action.trigger()
        assert engine.mixer.tile_colors is False and themes.color("panel") == themes.BUILT_IN["dark"].colors["panel"]
        assert Mixer.from_dict(engine.mixer.to_dict()).tile_colors is False
        win.tile_colors_action.trigger()
        win.choose_look("calm"); settle(qapp)
        win._refresh_view_menu()
        assert not win.tile_colors_action.isVisible()
    finally:
        win.shutdown()


def test_light_themes_get_white_keys_and_paint_colours_follow_a_theme_change(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, theme="light")
    try:
        assert themes.color("panel") == look_tile.TILE_LIGHT["panel"]
        light = look_tile.paint_colors()
        assert light["light"] and light is look_tile.paint_colors()  # worked out once, then reused
        win.apply_theme("dark")
        dark = look_tile.paint_colors()
        assert not dark["light"] and dark["face_top"] != light["face_top"] and dark["skirt"] != light["skirt"]
    finally:
        win.shutdown()


def test_everything_in_the_tile_look_is_a_key_or_sits_in_a_tray(qapp, tmp_path):
    from sluice.ui_tile import TileTray
    win, engine = make(qapp, tmp_path)
    try:
        assert isinstance(win.channels_widget, TileTray)
        assert all(strip.key is not None for strip in win.mix_strips)   # Listen and Broadcast are keys too
        assert win.mix_strips[0].width() == 224 + 12
        win.set_layout("rows"); settle(qapp)
        assert all(strip.frame.key is not None for strip in win.strips)
        win.grab()
    finally:
        win.shutdown()


def test_a_track_paints_the_face_behind_itself_so_a_meter_frame_repaints_only_the_track(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        lane = win.strips[0].faders[STREAM]
        assert lane.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        lane.push(0.5)
        lane.grab()
        base = lane._base
        lane.push(0.3)
        lane.grab()
        assert lane._base is base  # the fixed parts are drawn once; a frame draws only the fills, the tick and the handle
    finally:
        win.shutdown()


def test_the_desktop_widgets_follow_the_look(qapp, tmp_path):
    from sluice.ui_tile import MiniTile
    win, engine = make(qapp, tmp_path)
    try:
        win.desktop.open("mic"); win.desktop.open("dial", MONITOR); win.desktop.open("strip")
        settle(qapp)
        strip = win.desktop.open_widgets[("strip", None, None)]
        assert strip.strip.tile and all(isinstance(row, MiniTile) for row in strip.strip.rows.values())
        for widget in win.desktop.open_widgets.values():
            widget.tick()
            widget.grab()
        win.choose_look("calm"); settle(qapp)
        assert not strip.strip.tile
        win.desktop.open_widgets[("mic", None, None)].grab()
    finally:
        win.shutdown()


def test_the_bundled_fonts_load():
    families = fonts.load()
    assert all((fonts.FOLDER / name).is_file() for name in fonts.FILES)
    assert (fonts.FOLDER / "Inter-LICENSE.txt").is_file() and (fonts.FOLDER / "JetBrainsMono-LICENSE.txt").is_file()
    assert "Inter" in families and "JetBrains Mono" in families


# ---------------------------------------------------------------- the Free layout
def test_only_one_tile_is_folded_out_at_a_time_in_free_and_the_floor_folds_it_in(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, layout="free")
    try:
        music, game = win.canvas.nodes["music"], win.canvas.nodes["game"]
        QTest.mouseClick(music.chevron, Qt.MouseButton.LeftButton); settle(qapp)
        assert music.expanded and music.frame.lifted and win.canvas.open_tile is music
        QTest.mouseClick(game.chevron, Qt.MouseButton.LeftButton); settle(qapp)
        assert game.expanded and not music.expanded and win.canvas.open_tile is game
        win.canvas.toggle(win.canvas.nodes["stream"]); settle(qapp)
        assert not game.expanded and win.canvas.open_node is win.canvas.nodes["stream"]  # a mix card closes the tile
        QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, pos=QPoint(win.canvas.width() - 10, win.canvas.height() - 10))
        settle(qapp)
        assert win.canvas.open_node is None and win.canvas.open_tile is None
    finally:
        win.shutdown()


@pytest.mark.parametrize("look", ["tile", "nexus"])
def test_a_card_opens_where_it_covers_the_fewest_nodes(qapp, tmp_path, look):
    win, engine = make(qapp, tmp_path, look=look, layout="free", size=(1456, 860))
    try:
        canvas = win.canvas

        def covered(rect, node):
            return sum(max(0, r.width()) * max(0, r.height())
                       for r in (rect.intersected(n.geometry()) for n in canvas.nodes.values() if n is not node))

        for node in list(canvas.nodes.values()):
            if node.card is None:
                continue
            canvas.toggle(node); settle(qapp)
            card = node.card
            # 0.11.3 put it right of the node, else left, whatever was there
            right = node.x() + node.width() + 8
            x = right if right + card.width() <= canvas.width() else max(0, node.x() - 8 - card.width())
            y = max(0, min(node.y(), max(0, canvas.height() - card.height())))
            old = QRect(x, y, card.width(), card.height())
            assert covered(card.geometry(), node) <= covered(old, node), node.key
            canvas.close_card()
    finally:
        win.shutdown()


def test_the_mix_tile_names_its_real_device(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, layout="free")
    try:
        assert win.canvas.nodes["stream"].source_line.text() == "Sends to Sluice (Broadcast)"
        listen = win.canvas.nodes["monitor"]
        assert "Headphones" in listen.source_line.text() or "default" in listen.source_line.text()
        engine.mixer.mix(MONITOR).device = None
        listen.refresh()
        assert listen.source_line.text() == "No output"
    finally:
        win.shutdown()


def test_free_tiles_never_overlap_with_a_third_mix(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, layout="free", recording=True)
    try:
        tiles = [n for n in win.canvas.nodes.values() if hasattr(n, "expanded")]
        faces = [QRect(t.x() + 10, t.y() + 6, t.width() - 20, t.height() - 20) for t in tiles]
        for i, a in enumerate(faces):
            for b in faces[i + 1:]:
                assert not a.intersects(b)
    finally:
        win.shutdown()


# ---------------------------------------------------------------- spacing in every look
@pytest.mark.parametrize("look", ["calm", "original", "nexus", "tile"])
def test_a_long_channel_name_ends_in_an_ellipsis_and_the_tooltip_has_it_whole(qapp, tmp_path, look):
    long_name = "Music and podcasts from the second room"

    def rename(mixer):
        mixer.channel("music").label = long_name

    win, engine = make(qapp, tmp_path, look=look, setup=rename)
    try:
        strip = next(s for s in win.strips if s.channel.id == "music")
        assert isinstance(strip.title, ElidedLabel) and strip.title.text() == long_name
        assert long_name in strip.title.toolTip()
        assert problems(win, (1456, 860), look) == []
    finally:
        win.shutdown()


def test_rows_with_three_mixes_get_a_window_wide_enough_or_the_compact_list():
    assert sizing.rows_min_width(2) == sizing.ROW_FIXED + 2 * (sizing.ROW_CELL_MIN + 16) + sizing.ROW_SLACK
    assert sizing.rows_min_width(3) > sizing.rows_min_width(2)
    narrow = sizing.rows_min_width(3) - 10
    assert sizing.plan_for(narrow, 900, "rows", "calm", mixes=3).mode == "mini"
    assert sizing.plan_for(narrow, 900, "rows", "calm", mixes=2).mode == "rows"
    wide = sizing.plan_for(1920, 860, "rows", "calm", mixes=3)
    assert wide.mode == "rows" and wide.dock == "bottom"         # three mix cards need more height to stand at the side
    assert sizing.plan_for(1920, 1080, "rows", "calm", mixes=3).dock == "right"


@pytest.mark.parametrize("look", ["calm", "original", "nexus", "tile"])
@pytest.mark.parametrize("size", [(1456, 860), (1280, 860), (1100, 800), (1920, 1080)])
def test_rows_with_three_mixes_never_overlap(qapp, tmp_path, look, size):
    win, engine = make(qapp, tmp_path, look=look, layout="rows", size=size, recording=True)
    try:
        found = problems(win, size, f"{look} {size}")
        for strip in win.strips:  # the level never sits on the slider (the shared check skips text boxes)
            for mix_id, readout in strip.readouts.items():
                fader = strip.faders[mix_id]
                if readout.isVisible() and fader.isVisible():
                    a = QRect(readout.mapTo(win, QPoint(0, 0)), readout.size())
                    b = QRect(fader.mapTo(win, QPoint(0, 0)), fader.size())
                    assert not a.intersects(b), (look, size, strip.channel.id, mix_id)
        assert found == [], found[:5]
    finally:
        win.shutdown()


def test_the_report_says_whether_tile_colours_are_on(qapp, tmp_path):
    from sluice import report
    win, engine = make(qapp, tmp_path)
    try:
        assert win._report_info()["tile_colors"] is True
        assert "Tile colours: on." in report.window_summary()
    finally:
        win.shutdown()
