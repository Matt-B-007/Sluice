# SPDX-License-Identifier: GPL-3.0-or-later
"""Mic mute, the Recording mix, reconnecting and measuring the echo through the engine."""
import numpy as np
import pytest

from sluice import reconnect
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.control import ControlApi
from sluice.engine import GUARD_STREAK_LOST, Engine
from sluice.linker import NullLinker
from sluice.model import MONITOR, RECORDING, STREAM, Mixer

N = 512


@pytest.fixture
def rig():
    io = NullIO(realtime=False)
    engine = Engine(Mixer.default(), MockSystem(), io, NullLinker())
    engine.start()
    yield engine, io
    engine.shutdown()


def only(engine, io, **levels):
    """Every channel silent except the ones named."""
    io.fixed_inputs = {c.id: np.full((2, 1), levels.get(c.id, 0.0), dtype=np.float32) for c in engine.mixer.channels}


def levels(io, blocks=4):
    for _ in range(blocks):
        out = io.process_once(N)
    return {k: float(np.abs(v).max()) for k, v in out.items()}


# ------------------------------------------------------------------------- mic mute
def test_muting_the_microphone_silences_every_mix_and_its_own_device(rig):
    engine, io = rig
    engine.set_mute("mic", MONITOR, False)
    tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(48000 * 4) / 48000)).astype(np.float32)
    silent = np.zeros((2, tone.size), dtype=np.float32)
    io.streamed_inputs = {c.id: silent for c in engine.mixer.channels}
    io.streamed_inputs["mic"] = np.stack([tone, tone])
    live = levels(io)
    assert live[STREAM] > 0 and live["solo_mic"] > 0 and live[MONITOR] > 0
    engine.set_mic_muted(True)
    muted = levels(io, blocks=8)
    assert muted[STREAM] == 0 and muted["solo_mic"] == 0 and muted[MONITOR] == 0
    engine.set_mic_muted(False)
    assert levels(io, blocks=8)["solo_mic"] > 0


def test_only_channels_with_a_microphone_are_muted(rig):
    engine, io = rig
    only(engine, io, music=0.2)
    engine.set_mic_muted(True)
    assert levels(io)[STREAM] > 0


def test_the_control_command_and_status_report_the_mic(rig):
    engine, _ = rig
    api = ControlApi(engine)
    assert api.handle({"cmd": "mic-mute", "state": "on"}) == {"ok": True, "mic_muted": True}
    assert api.handle({"cmd": "status"})["mic_muted"] is True
    assert api.handle({"cmd": "mic-mute"})["mic_muted"] is False  # toggle


# --------------------------------------------------------------------- recording mix
def test_the_recording_mix_is_optional_and_saved(tmp_path):
    mixer = Mixer.default()
    assert not mixer.has_recording_mix and [m.id for m in mixer.mixes] == [MONITOR, STREAM]
    mixer.set_recording_mix(True)
    mixer.set_recording_mix(True)  # asking twice adds nothing
    assert [m.id for m in mixer.mixes] == [MONITOR, STREAM, RECORDING]
    assert all(RECORDING in c.levels for c in mixer.channels)
    mixer.channel("music").levels[RECORDING] = -9.0
    mixer.save(tmp_path / "c.json")
    again = Mixer.load(tmp_path / "c.json")
    assert again.has_recording_mix and again.channel("music").levels[RECORDING] == -9.0
    again.set_recording_mix(False)
    assert not again.has_recording_mix and all(RECORDING not in c.levels for c in again.channels)


def test_the_recording_mix_gets_its_own_device_and_output(tmp_path):
    mixer = Mixer.default()
    mixer.set_recording_mix(True)
    io = NullIO(realtime=False)
    system = MockSystem()
    engine = Engine(mixer, system, io, NullLinker())
    engine.start()
    try:
        assert system.null_sinks["sluice_recording"] == ("Sluice (Recording) feed", True)
        assert RECORDING in io.mix_ids
        only(engine, io, music=0.2)
        engine.set_mute("music", STREAM, True)  # the audience does not hear it, the recorder does
        out = levels(io)
        assert out[STREAM] == 0 and out[RECORDING] > 0
    finally:
        engine.shutdown()


# ------------------------------------------------------------------------ reconnecting
def test_a_server_shutdown_message_is_recognised_and_marks_the_engine(rig):
    engine, io = rig
    assert reconnect.is_lost_message("Audio server shut down: gone") and not reconnect.is_lost_message("xrun")
    assert not engine.server_lost
    io.error = "Audio server shut down: connection closed"
    engine.take_errors()
    assert engine.server_lost


def test_repeated_failures_mean_the_server_is_gone_but_a_success_resets_the_count(rig):
    engine, _ = rig
    engine.io.client = object()  # only the real (JACK) backend has one

    def fail():
        raise OSError("connection reset")

    for _ in range(GUARD_STREAK_LOST - 1):
        engine._guard(fail)
    engine._guard(lambda: 1)
    for _ in range(GUARD_STREAK_LOST - 1):
        engine._guard(fail)
    assert not engine.server_lost
    engine._guard(fail)
    assert engine.server_lost


def test_the_restart_command_repeats_how_sluice_was_started(monkeypatch):
    monkeypatch.setattr("sys.orig_argv", ["python", "-m", "sluice", "--minimized"], raising=False)
    command = reconnect.restart_command()
    assert command[1:] == ["-m", "sluice", "--minimized"] and command[0]


def test_the_probe_fails_quietly_without_a_server(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "jack", None)  # an import error
    assert reconnect.server_is_back() is False


# ---------------------------------------------------- echo measurement through the engine
def test_the_echo_measurement_goes_through_the_engine(rig, clap_room):
    engine, io = rig
    clap = clap_room(0.6, -75)
    io.streamed_inputs = {"mic": clap}
    engine.measure_room_start("mic", 4.0)
    assert engine.measure_echo_finish("mic") is None
    for _ in range(int(4.0 * 48000 / 512) + 3):
        io.process_once(512)
    result = engine.measure_echo_finish("mic")
    assert result is not None and result.status == "ok" and abs(result.reverb_time - 0.6) < 0.12


def test_a_measured_profile_reaches_the_noise_reducer(rig):
    engine, io = rig
    effect = next(e for e in engine.mixer.channel("mic").effects if e.type == "noise_reducer")
    stage = engine.effect_instance(effect.id).stage
    stage.ensure(48000)
    engine.apply_noise_profile("mic", np.ones(513))
    io.process_once(N)  # queued changes are applied at the start of the next block
    assert stage.profile is not None and stage._processor._profile is not None
