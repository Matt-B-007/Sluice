# SPDX-License-Identifier: GPL-3.0-or-later
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pedalboard")

from PySide6.QtWidgets import QPushButton  # noqa: E402

from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_effects import EffectsDialog, ParamRow  # noqa: E402
from sluice.ui_room import MeasureRoomDialog  # noqa: E402

SR = 48000


@pytest.fixture
def rig(qapp, tmp_path):
    io = NullIO(realtime=False)
    engine = Engine(Mixer.default(), MockSystem(), io, NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    yield win, engine, io
    win.shutdown()


def room_noise(rms_db=-45.0, seconds=2.0, seed=2):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((2, int(SR * seconds))) * 10 ** (rms_db / 20)).astype(np.float32)


def make_dialog(engine, used):
    mic = engine.mixer.channel("mic")
    gate = next(e for e in mic.effects if e.type == "noise_gate")
    return MeasureRoomDialog(engine, mic, gate.id, gate.params["threshold_db"], used.append), gate


def listen(io, seconds):
    for _ in range(int(seconds * SR / 512) + 2):
        io.process_once(512)


def test_listening_then_using_the_result_sets_the_gate(rig):
    _, engine, io = rig
    used = []
    dialog, gate = make_dialog(engine, used)
    io.streamed_inputs = {"mic": room_noise()}
    assert dialog.primary.text() == "Start listening" and not dialog.bar.isVisibleTo(dialog)
    dialog.primary.click()
    assert dialog.listening and not dialog.primary.isEnabled() and dialog.close_button.text() == "Stop"
    listen(io, 2.0)
    dialog.tick()
    assert dialog.listening and 20 < dialog.bar.value() < 80  # part-way
    listen(io, 3.5)
    dialog.tick()
    assert not dialog.listening and dialog.result is not None and dialog.result.status == "ok"
    assert dialog.primary.text().startswith("Use ") and "Set it to" in dialog.text.text()
    dialog.primary.click()
    assert used == [dialog.result.threshold_db]


def test_stopping_while_listening_cancels_the_recording(rig):
    _, engine, io = rig
    dialog, _ = make_dialog(engine, [])
    dialog.primary.click()
    listen(io, 1.0)
    dialog.close_button.click()
    assert not dialog.listening and engine.measure_room_progress("mic") == 0.0
    io.process_once(512)
    assert engine.graph.channels["mic"].capture is None


def test_talking_during_the_measurement_offers_another_try_not_a_bad_threshold(rig):
    _, engine, io = rig
    used = []
    dialog, _ = make_dialog(engine, used)
    audio = room_noise(seconds=5.0)
    audio[:, SR * 2:SR * 3] += (0.3 * np.sin(2 * np.pi * 200 * np.arange(SR) / SR)).astype(np.float32)
    io.streamed_inputs = {"mic": audio}
    dialog.primary.click()
    listen(io, 5.5)
    dialog.tick()
    assert dialog.result is None and "try again" in dialog.text.text().lower()
    assert dialog.primary.text() == "Try again" and dialog.primary.isEnabled()
    assert used == []  # nothing was applied


def test_a_muted_or_missing_microphone_is_explained(rig):
    _, engine, io = rig
    dialog, _ = make_dialog(engine, [])
    io.fixed_inputs = {"mic": np.zeros((2, 1), dtype=np.float32)}
    dialog.primary.click()
    listen(io, 5.5)
    dialog.tick()
    assert "microphone" in dialog.text.text().lower() and dialog.primary.text() == "Try again"


def test_when_audio_is_not_running_it_says_so_instead_of_waiting_forever(rig):
    _, engine, io = rig
    dialog, _ = make_dialog(engine, [])
    dialog.primary.click()
    dialog._started -= 10  # nothing is processing blocks, and it has been a while
    dialog.tick()
    assert not dialog.listening and "audio" in dialog.text.text().lower() and dialog.primary.text() == "Try again"
    assert engine.measure_room_progress("mic") == 0.0


def test_the_button_is_on_the_noise_gate_page_only_and_applies_through_the_slider(rig, monkeypatch):
    win, engine, io = rig
    mic = engine.mixer.channel("mic")
    dialog = EffectsDialog(engine, mic, win)
    names = [e.type for e in mic.effects]

    def measure_buttons():
        return [b for b in dialog.params_area.widget().findChildren(QPushButton) if b.text().startswith("Measure my room")]

    dialog.list.setCurrentRow(names.index("compressor"))
    assert measure_buttons() == []
    dialog.list.setCurrentRow(names.index("noise_gate"))
    assert len(measure_buttons()) == 1

    shown = []
    monkeypatch.setattr(MeasureRoomDialog, "exec", lambda self: shown.append(self) or 0)
    measure_buttons()[0].click()
    assert len(shown) == 1 and shown[0].old_threshold == -30
    shown[0]._on_use(-31.5)  # what pressing "Use ... dB" does
    gate = mic.effects[names.index("noise_gate")]
    assert gate.params["threshold_db"] == -31.5
    row = dialog._rows["threshold_db"]
    assert isinstance(row, ParamRow) and row.readout.text() == "-31.5 dB"


def test_a_channel_without_a_gate_has_no_measure_button(rig):
    win, engine, _ = rig
    chat = engine.mixer.channel("chat")
    dialog = EffectsDialog(engine, chat, win)
    dialog._add_builtin("compressor", "Compressor")
    assert not [b for b in dialog.params_area.widget().findChildren(QPushButton) if b.text().startswith("Measure")]


def test_measuring_the_echo_with_a_clap_sets_the_room_echo_time(rig, clap_room):
    from sluice.ui_room import MeasureEchoDialog

    _, engine, io = rig
    used = []
    mic = engine.mixer.channel("mic")
    dialog = MeasureEchoDialog(engine, mic, 0.6, used.append)
    assert "clap" in dialog.text.text() and dialog.primary.text() == "Start listening"
    io.streamed_inputs = {"mic": clap_room(0.9, -75)}
    dialog.primary.click()
    assert dialog.listening and "clap" in dialog.text.text()
    listen(io, 4.2)
    dialog.tick()
    assert dialog.result is not None and dialog.result.usable
    assert dialog.primary.text() == f"Use {dialog.result.reverb_time:.1f} s" and "0.6 s" in dialog.text.text()
    dialog.primary.click()
    assert len(used) == 1 and abs(used[0] - 0.9) < 0.15


def test_a_loud_room_is_told_the_clap_was_not_clear(rig, clap_room):
    from sluice.ui_room import MeasureEchoDialog

    _, engine, io = rig
    dialog = MeasureEchoDialog(engine, engine.mixer.channel("mic"), 0.6, lambda v: None)
    io.streamed_inputs = {"mic": clap_room(0.9, -30)}
    dialog.primary.click()
    listen(io, 4.2)
    dialog.tick()
    assert dialog.result is None and "clear clap" in dialog.text.text() and dialog.primary.text() == "Try again"


def test_using_the_noise_result_also_gives_the_noise_reducer_its_profile(rig):
    _, engine, io = rig
    used = []
    dialog, gate = make_dialog(engine, used)
    io.streamed_inputs = {"mic": room_noise(seconds=5.0)}
    dialog.primary.click()
    listen(io, 5.2)
    dialog.tick()
    dialog.primary.click()
    io.process_once(512)
    reducer = next(e for e in engine.mixer.channel("mic").effects if e.type == "noise_reducer")
    assert engine.effect_instance(reducer.id).stage.profile is not None
