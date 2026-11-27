# SPDX-License-Identifier: GPL-3.0-or-later
"""0.12.3: levels in percent as well as dB, on the scale KDE's volume slider and PulseAudio use."""

import json

import pytest

from sluice import ui_base
from sluice.ui_base import db_to_percent, format_level, parse_level, percent_to_db, short_level


@pytest.fixture(autouse=True)
def units():
    before = ui_base.UNITS
    yield
    ui_base.UNITS = before


@pytest.mark.parametrize("db,percent", [(0.0, 100), (-6.0, 79), (-18.0, 50), (-60.0, 0), (6.0, 126), (12.0, 158)])
def test_the_desktop_volume_scale(db, percent):
    assert round(db_to_percent(db)) == percent


def test_percent_and_db_convert_both_ways():
    for db in (-50.0, -30.0, -12.5, -3.0, 0.0, 5.0, 12.0):
        assert abs(percent_to_db(db_to_percent(db)) - db) < 1e-9
    assert percent_to_db(0) == float("-inf") and percent_to_db(500) == 12.0 and percent_to_db(1) == -60.0


def test_levels_are_shown_as_the_settings_say():
    ui_base.UNITS = "both"
    assert format_level(-18.0) == "-18.0 dB · 50%" and format_level(0.0) == "0.0 dB · 100%"
    assert format_level(-18.0, narrow=True) == "-18.0 dB"  # Tile's small boxes: one of the two
    assert format_level(-60.0) == "-inf dB · 0%"
    ui_base.UNITS = "db"
    assert format_level(-18.0) == "-18.0 dB"
    ui_base.UNITS = "percent"
    assert format_level(-18.0) == "50%" and format_level(-18.0, narrow=True) == "50%" and short_level(-18.0) == "50%"


def test_either_can_be_typed():
    ui_base.UNITS = "both"
    assert parse_level("-12") == -12.0 and parse_level("-12 dB") == -12.0
    assert abs(parse_level("50%") - (-18.06)) < 0.01 and abs(parse_level("50 %") - (-18.06)) < 0.01
    assert parse_level("100%") == 0.0 and parse_level("0%") == float("-inf") and parse_level("abc") is None
    ui_base.UNITS = "percent"  # showing percent only: a bare number is a percent, unless it says dB
    assert abs(parse_level("50") - (-18.06)) < 0.01 and parse_level("-6 dB") == -6.0


def test_the_choice_is_saved():
    from sluice.model import Mixer

    mixer = Mixer.demo()
    assert mixer.level_units == "both"
    mixer.level_units = "percent"
    assert Mixer.from_dict(json.loads(json.dumps(mixer.to_dict()))).level_units == "percent"
    data = mixer.to_dict()
    data["level_units"] = "volts"
    assert Mixer.from_dict(data).level_units == "both"


def test_the_window_shows_and_takes_percent(qapp, tmp_path):
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow

    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    try:
        strip = win.strips[0]
        mix_id = engine.mixer.mixes[0].id
        readout = strip.readouts[mix_id]
        readout.setText("50%")
        readout.setModified(True)
        readout.editingFinished.emit()
        assert abs(strip.channel.levels[mix_id] - (-18.06)) < 0.05
        assert "50%" in readout.text() and readout.toolTip().startswith("-18.1 dB = 50%")  # (the box takes the form that fits)
        win.set_level_units("percent")
        assert readout.text() == "50%" and engine.mixer.level_units == "percent" and win.units_actions["percent"].isChecked()
        win.open_settings("Themes and skins")
        win.units_actions["db"].trigger()
        assert readout.text() == "-18.1 dB"
    finally:
        win.shutdown()
