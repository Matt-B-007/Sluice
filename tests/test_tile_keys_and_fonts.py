# SPDX-License-Identifier: GPL-3.0-or-later
"""The Tile look as raised keys (light and dark, Tile colours), lighter painting, the bundled fonts, spacing in every look, the
command line's lock and the bug report."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QRect, Qt

from sluice import fonts, skin_tile, sizing, themes
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
    from sluice import __main__ as entry, update_install

    events = []

    class Lock:
        def close(self):
            events.append("released")

    monkeypatch.setattr(entry, "_acquire_lock", lambda: (events.append("locked"), Lock())[1])
    monkeypatch.setattr(update_install, "install_root", lambda: tmp_path)
    monkeypatch.setattr(update_install, "previous_version", lambda root: "0.11.3")
    monkeypatch.setattr(update_install, "rollback", lambda root: events.append("rolled back") or "0.11.3")
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
def test_the_look_colours_are_saved_and_switched(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        assert engine.mixer.look_colors is True and themes.color("panel") == skin_tile.TILE_DARK["panel"]
        win._refresh_view_menu()
        assert win.look_colors_action.isVisible() and win.look_colors_action.isChecked()
        win.look_colors_action.trigger()
        assert engine.mixer.look_colors is False and themes.color("panel") == themes.BUILT_IN["dark"].colors["panel"]
        assert Mixer.from_dict(engine.mixer.to_dict()).look_colors is False
        win.look_colors_action.trigger()
        win.choose_look("calm"); settle(qapp)
        win._refresh_view_menu()
        assert not win.look_colors_action.isVisible()
    finally:
        win.shutdown()


def test_light_themes_get_white_keys_and_paint_colours_follow_a_theme_change(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, theme="light")
    try:
        assert themes.color("panel") == skin_tile.TILE_LIGHT["panel"]
        light = skin_tile.paint_colors()
        assert light["light"] and light is skin_tile.paint_colors()  # worked out once, then reused
        win.apply_theme("dark")
        dark = skin_tile.paint_colors()
        assert not dark["light"] and dark["face_top"] != light["face_top"] and dark["skirt"] != light["skirt"]
    finally:
        win.shutdown()


def test_the_tiles_take_the_new_colours_when_the_theme_changes(qapp, tmp_path):
    """0.11.6: a channel's colour is darkened on light themes; switching theme used to leave the tiles in the old shade."""
    win, engine = make(qapp, tmp_path, theme="dark")
    try:
        tiles = [s for s in win.strips if hasattr(s, "retint")]
        assert tiles
        before = {t.channel.id: t.tint for t in tiles}
        win.apply_theme("light")
        settle(qapp)
        changed = 0
        for tile in tiles:
            wanted = skin_tile.channel_color(tile.channel)
            assert tile.tint == wanted and tile.well.color == wanted
            assert all(lane.fill_color == wanted for lane in tile.faders.values())
            changed += wanted != before[tile.channel.id]
        assert changed  # at least one colour (yellow, green) is shaded differently on Light
        win.apply_theme("dark")
        settle(qapp)
        assert {t.channel.id: t.tint for t in tiles} == before
    finally:
        win.shutdown()


def test_everything_in_the_tile_look_is_a_key_or_sits_in_a_tray(qapp, tmp_path):
    from sluice.ui_tile_paint import TileTray
    win, engine = make(qapp, tmp_path)
    try:
        assert isinstance(win.channels_widget, TileTray)
        assert all(strip.key is not None for strip in win.mix_strips)   # Listen and Broadcast are keys too
        from sluice.ui_tile import MIX_KEY_MARGINS, MIX_KEY_W
        assert win.mix_strips[0].width() == MIX_KEY_W + MIX_KEY_MARGINS[0] + MIX_KEY_MARGINS[2]  # a short key (0.11.5)
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


def test_the_report_says_whether_the_look_colours_are_on(qapp, tmp_path):
    from sluice import report
    win, engine = make(qapp, tmp_path)
    try:
        assert win._report_info()["look_colors"] is True
        assert "Skin's own colours: on." in report.window_summary()
    finally:
        win.shutdown()


def test_a_yellow_lane_stays_yellow_on_a_dark_groove():
    """0.11.6: the fill up to the handle was the channel's colour see-through over the groove, which made yellow olive brown."""
    from sluice import depth
    groove = skin_tile.paint_colors()["track"] if not skin_tile.paint_colors()["light"] else "#16191d"
    yellow = skin_tile.CHANNEL_TINTS["system"]
    fill = depth.position_fill(yellow, groove, 0.28)
    hue = lambda c: __import__("colorsys").rgb_to_hls(*depth._rgb(c))[0] * 360  # noqa: E731
    assert abs(hue(fill) - hue(yellow)) < 3  # the same hue...
    assert depth.luminance(fill) < depth.luminance(yellow)  # ...dimmer than the live signal drawn over it
    assert depth.luminance(fill) > depth.luminance(depth.mix(groove, yellow, 0.28)) * 2  # far from the old muddy fill
    blue = skin_tile.CHANNEL_TINTS["mic"]
    assert depth.position_fill(blue, groove, 0.28) == depth.mix(groove, blue, 0.28)  # other colours look as they did


@pytest.mark.parametrize("look", list(themes.LOOKS))
def test_a_channel_widget_has_no_empty_band_at_the_bottom(qapp, tmp_path, look):
    """0.11.6: the lane widgets were a fixed 16 px (10 in Tile) taller than their lanes needed."""
    from sluice.ui_widgets import LANE_H
    win, engine = make(qapp, tmp_path, look=look)
    try:
        win.desktop.open("channel", channel="system")
        settle(qapp)
        widget = win.desktop.open_widgets[("channel", None, "system")]
        rows = widget._rows()
        last = rows[-1][1]
        top, bottom = widget.insets()
        assert widget.height() - last.bottom() == bottom  # just the card's padding and shadow under the last lane
        assert rows[0][1].top() - widget.header_height() == top
        assert last.height() == LANE_H
    finally:
        win.shutdown()
