# SPDX-License-Identifier: GPL-3.0-or-later
"""Nexus in 0.11.5: glass cards on a floor that paints their shadows and a glow that follows their sound, the sound rings on the
channel and mix cards, Listen cyan and Broadcast coral, no glow on light themes, and rings that cost nothing while out of sight.
Calm gets a light touch of the same floor: soft shadows, no glow."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.look_nexus import CORAL_DARK, mix_pair  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_nexus import GlassFloor  # noqa: E402


def make(qapp, tmp_path, look="nexus", theme="dark"):
    mixer = Mixer.demo()
    mixer.look, mixer.layout, mixer.theme = look, "columns", theme
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.resize(1456, 900)
    win.show()
    for _ in range(6):
        qapp.processEvents()
    return win, engine


def _loud(win, qapp, channel="game", level=0.9, times=12):
    strip = next(s for s in win.strips if s.channel.id == channel)
    for _ in range(times):
        strip.ring.push(level)
        qapp.processEvents()
    floor = getattr(win, "channels_widget", None)
    if hasattr(floor, "_catch_up"):
        floor._catch_up()  # the glow follows ten times a second: bring it up to date now
    return strip


def test_the_cards_sit_on_a_glass_floor_and_the_glow_follows_the_sound(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        floor = win.channels_widget
        assert isinstance(floor, GlassFloor) and not floor.soft
        game = _loud(win, qapp, "game", 0.9)
        quiet = next(s for s in win.strips if s.channel.id == "browser")
        assert floor.glow_of(game) > 0.5 and floor.glow_of(quiet) == 0.0
        for _ in range(60):
            game.ring.push(0.0)
        floor._catch_up()
        assert floor.glow_of(game) < 0.1  # it fades with the sound
        win.grab()
    finally:
        win.shutdown()


def test_every_channel_and_mix_card_has_a_ring_and_mix_rings_show_their_icon(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        assert all(s.ring is not None for s in win.strips) and all(s.ring is not None for s in win.mix_strips)
        listen = win.mix_strips[0]
        assert not listen._ring_icon(1.0).isNull()
    finally:
        win.shutdown()


def test_listen_is_cyan_and_broadcast_coral_or_the_themes_second_colour(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        colors = themes.mix_colors(themes._current)
        assert colors["listen"] == "#22e5ff" and colors["broadcast"] == CORAL_DARK
        listen, broadcast = win.mix_strips[0], win.mix_strips[1]
        assert listen.ring.color == colors["listen"] and broadcast.ring.color == colors["broadcast"]
        assert broadcast.fader.fill_color.name() == colors["broadcast"] if hasattr(broadcast.fader.fill_color, "name") else True
    finally:
        win.shutdown()
    paper = themes.BUILT_IN["paper"].colors
    listen, broadcast = mix_pair(paper)
    assert listen == paper["accent"] and broadcast != listen


def test_light_themes_have_no_glow_and_a_coloured_top_edge(qapp, tmp_path):
    from sluice import ui_meters
    win, _ = make(qapp, tmp_path, theme="light")
    try:
        floor = win.channels_widget
        game = _loud(win, qapp)
        assert not floor._glows()
        before = len(ui_meters._GLOWS)
        game.ring.grab()
        assert len(ui_meters._GLOWS) == before  # no halo is drawn round the ring either
        assert "border-top: 3px solid" in game.frame.styleSheet()
    finally:
        win.shutdown()


def test_reduce_effects_turns_the_glow_off(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        win.set_reduce_effects(True)
        game = _loud(win, qapp)
        assert win.channels_widget.glow_of(game) == 0.0
    finally:
        win.set_reduce_effects(False)
        win.shutdown()


def test_a_ring_out_of_sight_is_not_redrawn(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        strip = next(s for s in win.strips if s.channel.id == "game")
        win.hide()
        qapp.processEvents()
        for _ in range(6):
            strip.ring.push(0.9)
        assert strip.ring._dirty  # waiting: nothing was painted while hidden
    finally:
        win.shutdown()


def test_six_moving_rings_stay_within_the_drawing_budget(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        rings = [s.ring for s in win.strips[:4]] + [s.ring for s in win.mix_strips]
        for ring in rings:
            ring.push(0.8)
        start = time.perf_counter()
        frames = 30
        for frame in range(frames):
            for ring in rings:
                ring.push(0.5 + 0.4 * (frame % 2))
                ring.update()
            qapp.processEvents()
        per_frame = (time.perf_counter() - start) / frames * 1000
        assert per_frame < 8.0, f"{per_frame:.2f} ms to draw six moving rings and their glow"  # about 3.5 ms here
    finally:
        win.shutdown()


def test_calm_gets_soft_shadows_and_no_glow(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, look="calm")
    try:
        floor = win.channels_widget
        assert isinstance(floor, GlassFloor) and floor.soft and floor._cards
        assert all(s.ring is None for s in win.strips)
        win.grab()
    finally:
        win.shutdown()
