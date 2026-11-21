# SPDX-License-Identifier: GPL-3.0-or-later
"""The Tile look's channel tiles (chosen direction, 2026-11-19): folded and folded-out tiles, the combined fader and meter track,
muted, clipping, linked and focused states, moving a tile, and the mini tiles of the compact list."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from sluice import skin_tile, themes
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import MONITOR, STREAM, Mixer
from sluice.ui import MainWindow


def make(qapp, tmp_path, layout="columns", size=(1456, 860), recording=False, theme="dark"):
    mixer = Mixer.demo()
    mixer.look, mixer.layout, mixer.theme = "tile", layout, theme
    mixer.hints_seen.append("firstrun")
    if recording:
        mixer.set_recording_mix(True)
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


def tile(win, channel_id):
    return next(s for s in win.strips if s.channel.id == channel_id)


def test_a_folded_tile_is_264_by_192_with_its_header_lanes_and_footer(qapp, tmp_path):
    from sluice.ui_tile import SHADOW, TILE_H, TILE_W, TileLane, TileStrip
    win, engine = make(qapp, tmp_path)
    try:
        left, top, right, bottom = SHADOW
        for strip in win.strips:
            assert isinstance(strip, TileStrip)
            assert (strip.width(), strip.height()) == (TILE_W + left + right, TILE_H + top + bottom)
            rect = strip.frame.tile_rect()
            assert (rect.width(), rect.height()) == (TILE_W, TILE_H)
            assert list(strip.faders) == [MONITOR, STREAM] and all(isinstance(l, TileLane) for l in strip.faders.values())
            assert strip.meters[MONITOR] is strip.faders[MONITOR]  # one track is fader and meter
            assert strip.link.isVisible() and strip.menu_button.isVisible() and strip.chevron.isVisible()
            assert strip.fx_button.isVisible() and not strip.details.isVisible()
        assert tile(win, "mic").fx_button.text() == "7 effects" and tile(win, "game").fx_button.text() == "1 effect"
        assert tile(win, "browser").fx_button.text() == "No effects"
        assert tile(win, "music").source_line.text() == "spotify, vlc"
        assert tile(win, "game").tint == skin_tile.CHANNEL_TINTS["game"] == "#ff8a3d"
    finally:
        win.shutdown()


def test_the_lane_is_the_fader_and_moving_one_linked_lane_moves_both(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        game = tile(win, "game")
        assert game.channel.linked and game.lanes_box.linked
        assert game.faders[MONITOR].link_down and game.faders[STREAM].link_up
        game.faders[MONITOR].setGain(-120)
        settle(qapp)
        assert game.channel.levels[MONITOR] == pytest.approx(-12.0)
        assert game.channel.levels[STREAM] == pytest.approx(-12.0)
        assert game.readouts[STREAM].text() == "-12.0 dB"
        music = tile(win, "music")  # not linked in the demo
        assert not music.lanes_box.linked and not music.faders[MONITOR].link_down
        music.faders[MONITOR].setGain(-30)
        assert music.channel.levels[STREAM] == pytest.approx(-18.0)
    finally:
        win.shutdown()


def test_a_muted_lane_is_striped_with_a_red_button_and_says_muted(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        browser = tile(win, "browser")
        browser.mutes[STREAM].click()
        settle(qapp)
        assert browser.channel.mutes[STREAM] and browser.faders[STREAM].muted
        assert browser.readouts[STREAM].text() == "Muted" and browser.readouts[STREAM].property("muted") is True
        browser.mutes[STREAM].click()
        settle(qapp)
        assert not browser.faders[STREAM].muted and browser.readouts[STREAM].text() == "0.0 dB"
    finally:
        win.shutdown()


def test_clipping_outlines_the_track_in_red_and_the_source_line_says_when(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        game = tile(win, "game")
        lane = game.faders[MONITOR]
        assert not lane.clipping()
        lane.push(1.0)
        settle(qapp)
        assert lane.clipping() and game.source_line.text() == "Clipped just now" and game.source_line.property("clipped") is True
        game._clip_at -= 12
        game._show_source_line()
        assert game.source_line.text() == "Clipped 12 s ago"
        game._clip_at -= 100
        game._show_source_line()
        assert game.source_line.text() == "gamelauncher" and game.source_line.property("clipped") is False
        lane.grab()  # paints clipped, muted and linked states without trouble
    finally:
        win.shutdown()


def test_a_tile_with_the_focus_has_a_ring_in_its_channel_colour(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        music, chat = tile(win, "music"), tile(win, "chat")
        win.activateWindow()
        music.faders[MONITOR].setFocus()
        settle(qapp)
        if QApplication.focusWidget() is not music.faders[MONITOR]:
            pytest.skip("this platform gives no keyboard focus offscreen")
        assert music.frame.focus_color == music.tint and chat.frame.focus_color is None
        chat.link.setFocus()
        settle(qapp)
        assert chat.frame.focus_color == chat.tint and music.frame.focus_color is None
    finally:
        win.shutdown()


def test_folding_out_adds_scale_chips_and_apps_and_never_repeats_a_control(qapp, tmp_path):
    from sluice.ui_tile import OPEN_W, SHADOW
    win, engine = make(qapp, tmp_path)
    try:
        mic = tile(win, "mic")
        mic.chevron.click()
        settle(qapp)
        assert mic.expanded and mic.width() == OPEN_W + SHADOW[0] + SHADOW[2] and mic.details.isVisible()
        assert all(lane.big for lane in mic.faders.values())
        assert not mic.fx_button.isVisible()  # the chips take its place
        from PySide6.QtWidgets import QPushButton
        chips = [b for b in mic.details.findChildren(QPushButton) if b.objectName() == "fxchip"]
        assert [c.text() for c in chips] == [e.name for e in mic.channel.effects]
        first = mic.channel.effects[0]
        chips[0].click()
        assert first.bypass is True and mic.fx_button.text() == "6 of 7 on"
        chips[0].click()
        assert first.bypass is False
        assert len(mic.app_meters) == len(mic.channel.devices) + len(mic.channel.apps)
        mic.after_meters(0.5)
        assert win.tile_open == {"mic"}
        win.rebuild_channels()
        settle(qapp)
        assert tile(win, "mic").expanded  # stays folded out when the cards are rebuilt
        tile(win, "mic").chevron.click()
        assert not tile(win, "mic").expanded and tile(win, "mic").fx_button.isVisible()
    finally:
        win.shutdown()


def test_move_puts_an_app_on_another_channel(qapp, tmp_path):
    from PySide6.QtWidgets import QMenu
    win, engine = make(qapp, tmp_path)
    try:
        music = tile(win, "music")
        music.chevron.click()
        settle(qapp)
        music._move_source("app", "vlc", "VLC", "chat")
        settle(qapp)
        assert "vlc" not in engine.mixer.channel("music").apps and "vlc" in engine.mixer.channel("chat").apps
        menu = QMenu()
        music = tile(win, "music")
        music._fill_move_menu(menu, "app", "spotify", "Spotify")
        texts = [a.text() for a in menu.actions() if a.text()]
        assert "To Chat" in texts and "To Music" not in texts and "Out of the mixer" in texts
    finally:
        win.shutdown()


def test_dragging_a_tile_lifts_it_shows_a_drop_slot_and_keeps_the_new_order(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        chat, browser = tile(win, "chat"), tile(win, "browser")
        mover = win.tile_mover()
        start = chat.grip.mapToGlobal(chat.grip.rect().center())
        mover.begin(chat, start)
        settle(qapp)
        assert mover.active() and chat.frame.slot and mover.ghost is not None and mover.ghost.isVisible()
        assert not chat.lanes_box.isVisible()  # the slot shows only "Drop here"
        mover.move(browser.mapToGlobal(browser.rect().center()))
        settle(qapp)
        mover.drop(browser.mapToGlobal(browser.rect().center()))
        settle(qapp)
        assert not mover.active() and not chat.frame.slot and chat.lanes_box.isVisible()
        order = [c.id for c in engine.mixer.channels]
        assert order.index("chat") < order.index("browser")
        assert [s.channel.id for s in win.strips] == order
        assert Mixer.from_dict(engine.mixer.to_dict()).channels[order.index("chat")].id == "chat"  # saved with the settings
    finally:
        win.shutdown()


def test_escape_puts_a_dragged_tile_back(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        before = [c.id for c in engine.mixer.channels]
        system, mic = tile(win, "system"), tile(win, "mic")
        mover = win.tile_mover()
        mover.begin(system, system.grip.mapToGlobal(system.grip.rect().center()))
        mover.move(mic.mapToGlobal(mic.rect().center()))
        settle(qapp)
        QApplication.sendEvent(win, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        settle(qapp)
        assert not mover.active() and [c.id for c in engine.mixer.channels] == before
        flow = win.channels_row
        shown = [flow.itemAt(i).widget().channel.id for i in range(flow.count()) if hasattr(flow.itemAt(i).widget(), "channel")]
        assert shown == before
    finally:
        win.shutdown()


def test_the_menu_moves_a_tile_earlier_or_later_from_the_keyboard(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        assert [c.id for c in engine.mixer.channels][:2] == ["mic", "browser"]
        win.move_tile("browser", -1)
        settle(qapp)
        assert [c.id for c in engine.mixer.channels][:2] == ["browser", "mic"]
        assert [s.channel.id for s in win.strips][:2] == ["browser", "mic"]
        win.move_tile("browser", -1)  # already first: nothing happens
        assert [c.id for c in engine.mixer.channels][0] == "browser"
        tile(win, "browser").menu.aboutToShow.emit()
        assert not tile(win, "browser").earlier_action.isEnabled() and tile(win, "browser").later_action.isEnabled()
    finally:
        win.shutdown()


def test_a_third_mix_adds_a_lane_and_makes_the_tile_taller(qapp, tmp_path):
    from sluice.ui_tile import LANE_EXTRA_H, SHADOW, TILE_H
    win, engine = make(qapp, tmp_path, recording=True)
    try:
        strip = win.strips[0]
        assert len(strip.faders) == 3 and len(strip.lanes_box.lanes) == 3
        assert strip.height() == TILE_H + LANE_EXTRA_H + SHADOW[1] + SHADOW[3]
    finally:
        win.shutdown()


def test_the_compact_list_shows_mini_tiles_with_one_lane_and_the_global_switch(qapp, tmp_path):
    from sluice.ui_tile import MiniTile
    win, engine = make(qapp, tmp_path, size=(700, 900))
    try:
        assert win.layout_mode == "mini" and win.mini.tile
        assert all(isinstance(row, MiniTile) for row in win.mini.rows.values())
        assert set(win.mini.choice_buttons) == {MONITOR, STREAM}
        win._update_meters()
        win.mini.push_levels({"ch:music:monitor": 0.5, "mix:monitor": 0.4})
        row = win.mini.rows["browser"]
        row.mute.click()
        settle(qapp)
        assert engine.mixer.channel("browser").mutes[MONITOR] and row.readout.text() == "Muted" and row.fader.muted
        win.mini.choose_mix(STREAM)
        assert row.readout.text() != "Muted"
        assert row.name.x() + row.name.width() <= row.fader.x()  # the name is never under the track
    finally:
        win.shutdown()


def test_tiles_paint_in_every_state_and_theme(qapp, tmp_path):
    for theme in ("dark", "light", "contrast", "paper"):
        win, engine = make(qapp, tmp_path, theme=theme)
        try:
            game = tile(win, "game")
            game.faders[MONITOR].push(1.0)
            game.chevron.click()
            settle(qapp)
            image = win.grab().toImage()
            assert not image.isNull()
            if theme == "dark":
                assert themes.color("panel") == skin_tile.TILE_DARK["panel"]
        finally:
            win.shutdown()


def test_the_compare_looks_picture_of_tile_is_raised_keys():
    from sluice import ui_skins
    assert "raised keys" in ui_skins.BLURBS["tile"].lower()
