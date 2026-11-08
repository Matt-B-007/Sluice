# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure my room: the analysis rules, the capture on the audio thread, and the whole flow through the engine."""
import numpy as np
import pytest

pedalboard = pytest.importorskip("pedalboard")

from sluice import room  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.dsp import Graph  # noqa: E402
from sluice.effects import runner_for  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402

SR = 48000


def noise(rms_db: float, seconds: float = 5.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((2, int(SR * seconds))) * 10 ** (rms_db / 20)).astype(np.float32)


def test_steady_room_noise_gives_a_threshold_just_above_it():
    result = room.analyse(noise(-42), SR)
    assert result.status == "ok" and result.usable
    assert result.threshold_db == pytest.approx(result.noise_db + room.MARGIN_DB, abs=0.1)
    assert -34 < result.threshold_db < -24  # white noise at -42 dB RMS peaks around -30 per 10 ms


def test_the_threshold_follows_the_room_and_the_microphone_level():
    quieter = room.analyse(noise(-52), SR).threshold_db
    louder = room.analyse(noise(-42), SR).threshold_db
    assert louder - quieter == pytest.approx(10.0, abs=0.5)


def test_the_measured_threshold_really_quiets_that_room():
    audio = noise(-42)
    result = room.analyse(audio, SR)
    gate = pedalboard.Pedalboard([pedalboard.NoiseGate(threshold_db=result.threshold_db, ratio=4, attack_ms=3, release_ms=100)])
    out = gate(audio, SR)[:, SR:]
    cut = 20 * np.log10(np.sqrt(np.mean(out ** 2)) / np.sqrt(np.mean(audio[:, SR:] ** 2)))
    assert cut < -12


def test_a_voice_or_sudden_noise_during_the_measurement_is_noticed_and_not_trusted():
    audio = noise(-45)
    t = np.arange(SR) / SR
    audio[:, SR * 2:SR * 3] += (0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)  # someone talks for a second
    result = room.analyse(audio, SR)
    assert result.status == "disturbed" and not result.usable
    assert "try again" in result.message.lower()


def test_no_signal_is_reported_as_a_microphone_problem():
    result = room.analyse(np.zeros((2, SR * 5), dtype=np.float32), SR)
    assert result.status == "silent" and not result.usable
    assert "microphone" in result.message.lower()


def test_too_short_a_recording_is_refused():
    assert room.analyse(noise(-42, seconds=1.0), SR).status == "silent"


def test_a_very_quiet_room_gets_the_floor_threshold():
    result = room.analyse(noise(-80), SR)
    assert result.status == "quiet_room" and result.usable and result.threshold_db == room.FLOOR_DB


def test_a_loud_room_is_capped_and_told_the_truth():
    result = room.analyse(noise(-28), SR)
    assert result.status == "too_loud" and result.usable
    assert result.threshold_db == room.CEILING_DB
    assert "closer" in result.message  # the advice that actually helps


def test_the_effects_ahead_of_the_gate_are_part_of_what_is_measured():
    mixer = Mixer.default()
    effects = mixer.channel("mic").effects
    gate_at = next(i for i, e in enumerate(effects) if e.type == "noise_gate")
    ahead = runner_for(effects[:gate_at], SR)  # the high-pass
    assert ahead is not None
    rumble = (0.05 * np.sin(2 * np.pi * 40 * np.arange(SR * 5) / SR)).astype(np.float32)
    rumble = np.stack([rumble, rumble])
    raw = room.analyse(rumble, SR)
    filtered = room.analyse(rumble, SR, ahead)
    assert filtered.noise_db < raw.noise_db - 10  # a 40 Hz rumble is mostly removed before the gate, so the gate need not rise for it


def test_bypassed_and_vst3_effects_are_not_run_for_the_measurement():
    mixer = Mixer.default()
    effects = mixer.channel("mic").effects
    for effect in effects:
        effect.bypass = True
    assert runner_for(effects, SR) is None


# ------------------------------------------------------------------ audio thread
def test_the_graph_records_exactly_what_came_in_and_then_stops():
    graph = Graph(SR, ["listen"])
    graph.set_channels(["a"])
    graph.start_capture("a", 0.1)  # 4800 frames
    block = np.arange(2 * 512, dtype=np.float32).reshape(2, 512) / 1024
    for _ in range(12):
        graph.process({"a": block}, 512)
    assert graph.capture_progress("a") == 1.0
    got = graph.take_capture("a")
    assert got.shape == (2, 4800)
    assert np.array_equal(got[:, :512], block) and np.array_equal(got[:, 512:1024], block)
    assert graph.take_capture("a") is None  # taken once
    assert graph.channels["a"].capture is None


def test_a_channel_with_no_input_records_silence_and_the_capture_can_be_cancelled():
    graph = Graph(SR, ["listen"])
    graph.set_channels(["a"])
    graph.start_capture("a", 0.05)
    for _ in range(6):
        graph.process({}, 512)
    assert not graph.take_capture("a").any()
    graph.start_capture("a", 5.0)
    graph.process({}, 512)
    graph.cancel_capture("a")
    graph.process({}, 512)
    assert graph.capture_progress("a") == 0.0 and graph.channels["a"].capture is None


def test_taking_the_recording_early_gives_nothing():
    graph = Graph(SR, ["listen"])
    graph.set_channels(["a"])
    graph.start_capture("a", 1.0)
    graph.process({"a": np.zeros((2, 512), dtype=np.float32)}, 512)
    assert 0 < graph.capture_progress("a") < 0.5
    assert graph.take_capture("a") is None


# ------------------------------------------------------------------ the whole flow
@pytest.fixture
def rig():
    io = NullIO(realtime=False)
    engine = Engine(Mixer.default(), MockSystem(), io, NullLinker())
    engine.start()
    yield engine, io
    engine.shutdown()


def listen(engine, io, seconds):
    for _ in range(int(seconds * SR / 512) + 2):
        io.process_once(512)


def gate_id(engine):
    return next(e.id for e in engine.mixer.channel("mic").effects if e.type == "noise_gate")


def test_measuring_the_room_through_the_engine(rig):
    engine, io = rig
    room_noise = noise(-45, seconds=2.0, seed=4)
    io.streamed_inputs = {"mic": room_noise}
    engine.measure_room_start("mic", 5.0)
    assert engine.measure_room_finish("mic", gate_id(engine)) is None  # nothing heard yet
    listen(engine, io, 2.0)
    assert 0 < engine.measure_room_progress("mic") < 1
    listen(engine, io, 3.5)
    result = engine.measure_room_finish("mic", gate_id(engine))
    assert result is not None and result.status == "ok"
    engine.set_effect_param(gate_id(engine), "threshold_db", result.threshold_db)
    assert engine.mixer.channel("mic").effects[3].params["threshold_db"] == result.threshold_db  # saved with the settings


def test_measuring_an_unknown_channel_or_without_audio_fails_clearly(rig):
    engine, _ = rig
    with pytest.raises(KeyError):
        engine.measure_room_start("nope")
    engine.graph = None
    with pytest.raises(RuntimeError):
        engine.measure_room_start("mic")
    assert engine.measure_room_finish("mic", "x") is None and engine.measure_room_progress("mic") == 0.0


# ------------------------------------------------------------------ echo time from a clap
def clap_room(rt60, noise_db, seed=0):
    rng = np.random.default_rng(seed)
    n = int(SR * rt60 * 1.3)
    t = np.arange(n) / SR
    tail = rng.standard_normal(n) * 10 ** (-3 * t / rt60)
    tail[: int(0.004 * SR)] = 0
    tail *= 1.0 / np.sqrt(np.sum(tail ** 2))
    h = tail.copy()
    h[int(0.002 * SR)] += 1.0
    clap = np.zeros(SR * 4)
    clap[SR:SR + 30] = rng.standard_normal(30) * 0.8
    x = np.convolve(clap, h)[: clap.size]
    x = x / np.max(np.abs(x)) * 0.5
    hum = rng.standard_normal(x.size) * 10 ** (noise_db / 20)
    return np.stack([x + hum, x + hum]).astype(np.float32)


@pytest.mark.parametrize("rt60", [0.3, 0.5, 0.8, 1.2])
def test_echo_time_is_read_from_a_clap_in_a_quiet_room(rt60):
    result = room.analyse_echo(clap_room(rt60, -70), SR)
    assert result.status == "ok" and result.usable
    assert abs(result.reverb_time - rt60) / rt60 < 0.15


def test_a_loud_room_refuses_instead_of_guessing():
    result = room.analyse_echo(clap_room(0.8, -35), SR)
    assert result.status == "no_clap" and not result.usable and "clap" in result.message


def test_echo_needs_a_signal_and_a_clap():
    assert room.analyse_echo(np.zeros((2, SR * 4), dtype=np.float32), SR).status == "silent"
    hiss = (np.random.default_rng(1).standard_normal((2, SR * 4)) * 0.01).astype(np.float32)
    assert room.analyse_echo(hiss, SR).status == "no_clap"
    assert room.analyse_echo(hiss[:, :SR], SR).status == "silent"  # too short


def test_a_measured_room_carries_its_noise_profile():
    result = room.analyse(noise(-45, seconds=5.0, seed=9), SR)
    assert result.status == "ok" and result.profile is not None and result.profile.shape == (513,)
    assert room.analyse(np.zeros((2, SR * 5), dtype=np.float32), SR).profile is None
