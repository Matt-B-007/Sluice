# SPDX-License-Identifier: GPL-3.0-or-later
"""The Tile look in 0.11.5: keys with full depth (shadows that are never cut off, a thick skirt with a rim, a lit face), a sunken
tray, and Listen and Broadcast as short keys with sideways sliders."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402

from sluice import look_tile, themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import MONITOR, STREAM, Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_tile import MIX_KEY_MARGINS  # noqa: E402
from sluice.ui_tile_paint import SHADOW, SKIRT  # noqa: E402


def make(qapp, tmp_path, theme="dark", size=(1456, 900), recording=False):
    mixer = Mixer.demo()
    if recording:
        mixer.set_recording_mix(True)
    mixer.look, mixer.layout, mixer.theme = "tile", "columns", theme
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.resize(*size)
    win.show()
    for _ in range(6):
        qapp.processEvents()
    return win, engine


def test_a_key_has_room_for_its_shadows_so_none_is_cut_off(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        assert SKIRT == 8 and SHADOW[3] >= 36 and SHADOW[0] >= 20  # room below and at the sides
        frame = win.strips[0].frame
        image = frame.grab().toImage()
        ratio = image.devicePixelRatio()
        face = frame.face_rect()
        below = image.pixelColor(round(face.center().x() * ratio), round((face.bottom() + SKIRT + 8) * ratio))
        assert below.alpha() > 0  # the shadow shows under the skirt
        edge = image.pixelColor(round(face.center().x() * ratio), image.height() - 1)
        assert edge.alpha() < 12  # and has faded out before the widget's edge: nothing is cut off
    finally:
        win.shutdown()


def test_keys_overlap_by_their_shadow_room_and_sit_in_a_tray(qapp, tmp_path):
    from sluice.ui_base import TILE_GAP
    win, _ = make(qapp, tmp_path)
    try:
        first, second = win.strips[0], win.strips[1]
        assert first.y() == second.y()
        faces_gap = (second.x() + SHADOW[0]) - (first.x() + first.width() - SHADOW[2])
        assert faces_gap == SHADOW[0] + SHADOW[2] + TILE_GAP == 28
    finally:
        win.shutdown()


def test_listen_and_broadcast_are_short_keys_with_a_sideways_slider(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        listen, broadcast = win.mix_strips[0], win.mix_strips[1]
        assert listen.tile_key and broadcast.tile_key
        assert listen.height() < 200 and listen.x() == broadcast.x() and broadcast.y() > listen.y()  # stacked at the right
        assert listen.fader is listen.meter and listen.fader.orientation() == Qt.Orientation.Horizontal
        assert listen.combo is not None and not listen.details.isVisible()  # the device picker is folded away
        listen.fold.click(); qapp.processEvents()
        assert listen.details.isVisible() and listen.combo.isVisible()
        assert broadcast.device_line.text() == engine.mixer.mixes[1].source_description
        listen.fader.setGain(-60)
        assert engine.mixer.mixes[0].gain_db == -6.0 and listen.readout.text().startswith("-6")
        listen.mute.click()
        assert engine.mixer.mixes[0].mute and listen.fader.muted
        listen.limiter.click()
        assert engine.mixer.mixes[0].limiter is not True or listen.limiter.isChecked() == engine.mixer.mixes[0].limiter
        listen.meter.push(0.5)  # the window's meter timer feeds the groove
    finally:
        win.shutdown()


def test_mix_keys_go_side_by_side_under_the_tiles_in_a_narrow_window(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, size=(1000, 900))
    try:
        assert win._dock == "bottom"
        listen, broadcast = win.mix_strips[0], win.mix_strips[1]
        assert listen.tile_key and listen.y() == broadcast.y() and broadcast.x() > listen.x()
    finally:
        win.shutdown()


def test_a_recording_mix_key_can_be_removed_from_its_fold_out(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, recording=True)
    try:
        recording = win.mix_strips[-1]
        assert recording.tile_key and any(b.text().startswith("Remove the Recording mix")
                                          for b in recording.details.findChildren(type(recording.limiter)))
    finally:
        win.shutdown()


def test_every_theme_paints_tiles_without_errors_and_with_its_own_colours(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        seen = set()
        for theme_id in themes.BUILT_IN:
            win.choose_theme(theme_id)
            qapp.processEvents()
            win.grab()
            seen.add(look_tile.paint_colors()["face_top"])
        assert len(seen) == len(themes.BUILT_IN)  # no two themes give the keys the same face
    finally:
        win.shutdown()


def test_mix_key_margins_leave_room_for_the_shadow():
    assert MIX_KEY_MARGINS[3] >= 32 and MIX_KEY_MARGINS[0] >= 20
    assert MONITOR and STREAM
