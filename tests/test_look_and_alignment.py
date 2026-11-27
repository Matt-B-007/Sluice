# SPDX-License-Identifier: GPL-3.0-or-later
"""0.12.0's cleanup of how things line up: measured, so they stay lined up."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402

from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_base import short_device_name  # noqa: E402


def make(qapp, tmp_path, skin="calm"):
    mixer = Mixer.demo()
    mixer.skin = skin
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.resize(1600, 900)
    win.show()
    for _ in range(3):
        qapp.processEvents()
    return win, engine


def centre(widget, ref) -> float:
    return widget.mapTo(ref, QPoint(0, 0)).x() + widget.width() / 2


def span(widgets, ref) -> float:
    left = min(w.mapTo(ref, QPoint(0, 0)).x() for w in widgets)
    right = max(w.mapTo(ref, QPoint(0, 0)).x() + w.width() for w in widgets)
    return (left + right) / 2


@pytest.mark.parametrize("skin", ["calm"])  # (Nexus and Glass retired in 0.13.1; Tile lays its lanes out its own way)
def test_each_fader_and_its_meter_sit_as_a_pair_under_their_name_and_over_their_level(qapp, tmp_path, skin):
    win, _ = make(qapp, tmp_path, skin)
    try:
        for strip in win.strips:
            for index, mix_id in enumerate(strip.faders):
                pair = span([strip.faders[mix_id], strip.meters[mix_id]], strip)
                assert abs(pair - centre(strip.tags[index], strip)) <= 1, (skin, strip.channel.id, mix_id)
                assert abs(pair - centre(strip.readouts[mix_id], strip)) <= 1
        for card in win.mix_strips:
            pair = span([card.fader, card.meter], card)
            assert abs(pair - centre(card.readout, card)) <= 1
            gap = card.meter.mapTo(card, QPoint(0, 0)).x() - (card.fader.mapTo(card, QPoint(0, 0)).x() + card.fader.width())
            assert gap <= 16  # one pair, not two things 40 px apart
    finally:
        win.shutdown()


def test_the_tile_tray_ends_with_the_tiles(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, "tile")
    try:
        tray = win.channels_widget
        size = tray.content_size()
        assert size.height() < tray.height() - 100 and size.width() <= tray.width()
        bottom = max(s.geometry().bottom() for s in win.strips)
        assert size.height() > bottom  # every tile still on the tray
    finally:
        win.shutdown()


def test_the_effects_window_opens_on_the_chain_with_no_gap_and_arrows_only_for_plugins(qapp, tmp_path):
    from PySide6.QtWidgets import QApplication

    from sluice.ui_effects import CARD_H, EffectsDialog

    win, engine = make(qapp, tmp_path)
    try:
        dialog = EffectsDialog(engine, engine.mixer.channel("mic"), win)
        dialog.resize(1280, 940)
        dialog.show()
        for _ in range(4):
            qapp.processEvents()
        assert QApplication.focusWidget() is dialog.list  # not the Quiet button with a focus ring round it
        assert dialog.list.height() == CARD_H + 8 + 16  # one row of cards: no empty band under them
        assert not dialog.up.isVisibleTo(dialog) and not dialog.down.isVisibleTo(dialog)  # built-in effects do not move
        foot = [label.text() for label in dialog.findChildren(type(dialog.title)) if "Switch an effect off" in label.text()]
        assert foot and "Untick" not in foot[0]
        dialog.close()
    finally:
        win.shutdown()


@pytest.mark.parametrize(
    "full,short",
    [
        ("Navi 21/23 HDMI/DP Audio Controller Digital Stereo (HDMI 3)", "HDMI 3"),
        ("Family 17h (Models 00h-0fh) HD Audio Controller Analog Stereo", "Built-in audio"),
        ("Starship/Matisse HD Audio Controller Digital Stereo (IEC958)", "Built-in audio (digital)"),
        ("Blue Yeti Analog Stereo", "Blue Yeti"),
        ("Elgato Wave:3 Mono", "Elgato Wave:3"),
        ("Headphones (USB Audio)", "Headphones (USB Audio)"),
        ("Sluice (Broadcast)", "Sluice (Broadcast)"),
    ],
)
def test_device_names_are_short_on_the_cards(full, short):
    assert short_device_name(full) == short


def test_the_card_shows_the_short_name_and_the_tooltip_the_whole_one(qapp, tmp_path):
    from sluice.backend import Device

    win, engine = make(qapp, tmp_path)
    try:
        engine.sources.append(Device("alsa_input.usb-yeti.analog-stereo", "Blue Yeti Analog Stereo"))
        strip = next(s for s in win.strips if s.channel.id == "mic")
        text, tip = strip._device_text("alsa_input.usb-yeti.analog-stereo")
        assert text == "Blue Yeti" and "Blue Yeti Analog Stereo" in tip
    finally:
        win.shutdown()
