# SPDX-License-Identifier: GPL-3.0-or-later
"""0.9.6: a warning when an app listens to the raw microphone instead of the one with Sluice's effects."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from sluice import rawmic
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer

MIC = "alsa_input.usb-Blue_Yeti.analog-stereo"


def links_for(app, node=MIC):
    return {(f"{node}:capture_FL", f"{app}:input_FL"), (f"{node}:capture_FR", f"{app}:input_FR")}


@pytest.fixture
def engine():
    mixer = Mixer.default()
    mixer.channel("mic").devices = [MIC]
    mixer.channel("mic").separate = True
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    return engine


def test_an_app_on_the_raw_mic_is_found_but_sluice_and_meters_are_not(engine):
    links = links_for("OBS") | links_for("sluice") | links_for("input.sluice_stream_mic") | links_for("PulseAudio Volume Control")
    found = rawmic.find(links, engine.mixer.channels, engine.resolve_source)
    assert list(found) == ["OBS"] and [c.id for c in found["OBS"]] == ["mic"]


def test_nothing_is_reported_when_the_channel_has_no_effects_on(engine):
    for effect in engine.mixer.channel("mic").effects:
        effect.bypass = True
    assert rawmic.find(links_for("OBS"), engine.mixer.channels, engine.resolve_source) == {}
    engine.mixer.channel("mic").effects.clear()
    assert rawmic.find(links_for("OBS"), engine.mixer.channels, engine.resolve_source) == {}


def test_a_monitor_of_an_output_is_not_a_microphone(engine):
    engine.mixer.channel("mic").devices = [MIC + ".monitor"]
    assert rawmic.find(links_for("OBS", MIC), engine.mixer.channels, engine.resolve_source) == {}


def test_the_message_says_which_device_to_choose(engine):
    channel = engine.mixer.channel("mic")
    assert "“Sluice (Mic)”" in rawmic.message("OBS", [channel]) and "raw microphone" in rawmic.message("OBS", [channel])
    channel.separate = False
    assert "“Sluice (Broadcast)”" in rawmic.message("OBS", [channel])


def test_it_takes_a_while_before_an_app_is_reported_and_only_once(engine):
    engine.linker.others = links_for("OBS")
    engine.check_raw_mic(100.0)
    assert engine.raw_mic == {}  # a meter flicker, not a recording
    engine.check_raw_mic(100.0 + rawmic.SECONDS + 1)
    assert list(engine.raw_mic) == ["OBS"] and "OBS" in engine.raw_mic["OBS"]
    engine.raw_mic.clear()
    engine.check_raw_mic(130.0)
    assert engine.raw_mic == {}  # already told
    engine.linker.others = set()
    engine.check_raw_mic(140.0)
    engine.linker.others = links_for("OBS")
    engine.check_raw_mic(150.0)
    engine.check_raw_mic(150.0 + rawmic.SECONDS + 1)
    assert list(engine.raw_mic) == ["OBS"]  # it stopped and came back: worth saying again


def test_dont_remind_me_is_remembered_with_the_settings(engine, tmp_path):
    engine.linker.others = links_for("OBS")
    engine.check_raw_mic(0.0)
    engine.check_raw_mic(rawmic.SECONDS + 1)
    assert "OBS" in engine.raw_mic
    engine.dismiss_raw_mic("OBS")
    assert engine.raw_mic == {} and "rawmic:OBS" in engine.mixer.hints_seen
    engine.mixer.save(tmp_path / "c.json")
    again = Mixer.load(tmp_path / "c.json")
    assert "rawmic:OBS" in again.hints_seen
    engine._raw_reported.clear()
    engine._raw_first_seen.clear()
    engine.check_raw_mic(50.0)
    engine.check_raw_mic(50.0 + rawmic.SECONDS + 1)
    assert engine.raw_mic == {}


def test_the_window_shows_the_warning_and_can_stop_it(qapp, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox

    from sluice.ui import MainWindow

    mixer = Mixer.default()
    mixer.channel("mic").devices = [MIC]
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    try:
        assert win.raw_mic_button.isHidden()
        engine.raw_mic = {"OBS": rawmic.message("OBS", [mixer.channel("mic")])}
        win._update_raw_mic()
        assert not win.raw_mic_button.isHidden() and "OBS" in win.raw_mic_button.text()
        assert "raw mic" in win.raw_mic_button.text()

        def fake_exec(box):
            box.clicked = [b for b in box.buttons() if "remind" in b.text().lower()][0]

        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box.clicked)
        win.raw_mic_button.click()
        assert win.raw_mic_button.isHidden() and "rawmic:OBS" in engine.mixer.hints_seen
    finally:
        win.shutdown()


def test_with_a_graph_watcher_the_raw_mic_check_waits_for_a_change():
    """0.11.7: the check runs pw-link; every 5 seconds made Sluice start about 15 pw-link processes a minute while idle."""
    from sluice import engine as engine_module
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer

    class Watching:
        def running(self):
            return True

    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine._last_raw_check = 100.0
    watcher = Watching()
    assert not engine._raw_check_due(100.0 + rawmic.CHECK_SECONDS + 1, watcher)  # nothing changed: no look
    assert engine._raw_check_due(100.0 + engine_module.RAW_SAFETY_SECONDS, watcher)  # once a minute, to be safe
    engine._raw_first_seen["obs"] = 100.0
    assert engine._raw_check_due(100.0 + rawmic.CHECK_SECONDS, watcher)  # an app seen on it: follow it up
    engine._raw_first_seen.clear()
    assert engine._raw_check_due(100.0 + rawmic.CHECK_SECONDS, None)  # no watcher: on the clock, as before
