# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
import pytest

from sluice.dsp import Graph, PeakLimiter
from sluice.effects import EffectInstance
from sluice.model import Effect

SR = 48000
N = 512


def block(value: float, frames: int = N) -> np.ndarray:
    return np.full((2, frames), value, dtype=np.float32)


@pytest.fixture
def graph():
    g = Graph(SR, ["monitor", "stream"])
    g.set_channels(["a", "b"])
    for mix in ("monitor", "stream"):
        g.set_mix(mix, 1.0, False)
        for ch in ("a", "b"):
            g.set_gain(ch, mix, 1.0)
    return g


def test_channels_are_summed_into_each_mix(graph):
    out = graph.process({"a": block(0.2), "b": block(0.3)}, N)
    assert out["monitor"].shape == (2, N)
    assert out["monitor"].dtype == np.float32
    assert np.allclose(out["monitor"], 0.5)
    assert np.allclose(out["stream"], 0.5)


def test_per_mix_gains_are_independent(graph):
    graph.set_gain("a", "stream", 0.0)
    graph.set_gain("b", "monitor", 0.5)
    out = graph.process({"a": block(0.2), "b": block(0.4)}, N)
    assert np.allclose(out["monitor"], 0.2 + 0.2)
    assert np.allclose(out["stream"], 0.4)


def test_missing_input_is_silence(graph):
    out = graph.process({"a": block(0.25)}, N)
    assert np.allclose(out["monitor"], 0.25)


def test_gain_changes_are_ramped_not_stepped(graph):
    graph.set_gain("a", "monitor", 0.5)
    graph.process({"a": block(1.0)}, N)
    graph.set_gain("a", "monitor", 1.0)
    out = graph.process({"a": block(1.0), "b": block(0.0)}, N)["monitor"][0]
    assert out[0] == pytest.approx(0.5, abs=0.01)
    assert out[-1] == pytest.approx(1.0, abs=1e-3)
    assert np.all(np.diff(out) >= -1e-6)  # monotonic: no jump, so no click


def test_muting_ramps_to_silence_then_stays_silent(graph):
    graph.process({"a": block(1.0)}, N)  # a block has played, so the next change is ramped
    graph.set_gain("a", "monitor", 0.0)
    first = graph.process({"a": block(1.0)}, N)["monitor"][0]
    assert first[0] > 0.9 and first[-1] == pytest.approx(0.0, abs=1e-3)
    assert np.allclose(graph.process({"a": block(1.0)}, N)["monitor"], 0.0)


def test_master_gain(graph):
    graph.set_mix("monitor", 0.5, False)
    out = graph.process({"a": block(0.4)}, N)
    assert np.allclose(out["monitor"], 0.2)
    assert np.allclose(out["stream"], 0.4)


def test_master_gain_applies_immediately_before_the_first_block():
    g = Graph(SR, ["monitor"])
    g.set_channels(["a"])
    g.set_gain("a", "monitor", 1.0)
    g.set_mix("monitor", 0.0, False)  # muted from the start: must not burst at full level
    assert np.allclose(g.process({"a": block(1.0)}, N)["monitor"], 0.0)


def sine_blocks(amplitude: float, blocks: int, freq: float = 220.0, start: int = 0):
    n = N * blocks
    t = (start + np.arange(n)) / SR
    wave = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([wave, wave])


def test_mix_limiter_never_exceeds_the_ceiling():
    g = Graph(SR, ["monitor"])
    g.set_channels(["a"])
    g.set_mix("monitor", 1.0, True)
    g.set_gain("a", "monitor", 4.0)  # +12 dB of overload
    sig = sine_blocks(1.0, 16)
    ceiling = 10 ** (-1.0 / 20)
    for i in range(16):
        out = g.process({"a": sig[:, i * N:(i + 1) * N]}, N)["monitor"]
        assert np.abs(out).max() <= ceiling + 1e-6


def test_peak_limiter_leaves_quiet_audio_untouched_and_recovers_after_overload():
    limiter = PeakLimiter(SR, ceiling_db=-1.0, release_ms=100)
    quiet = sine_blocks(0.3, 4)
    assert np.allclose(limiter.process(quiet), quiet)
    loud = limiter.process(sine_blocks(4.0, 8))
    assert np.abs(loud).max() <= 10 ** (-1.0 / 20) + 1e-6
    after = limiter.process(sine_blocks(0.3, 80, start=N * 8))  # about 0.85 s of quiet audio
    assert np.abs(after[:, -N * 4:]).max() == pytest.approx(0.3, abs=0.01)  # back to unity gain


def test_peak_limiter_handles_odd_block_sizes():
    limiter = PeakLimiter(SR)
    for frames in (1, 7, 255, 1024, 1500, 4096):
        audio = (np.random.default_rng(frames).standard_normal((2, frames)) * 3).astype(np.float32)
        assert np.abs(limiter.process(audio)).max() <= limiter.ceiling + 1e-6


def test_effect_chain_is_applied(graph):
    gain = EffectInstance(Effect("g1", "builtin", "Gain", type="gain", params={"gain_db": 6.0206}))
    assert gain.usable
    graph.set_chain("a", [gain])
    out = graph.process({"a": block(0.1)}, N)
    assert np.allclose(out["monitor"], 0.2, atol=1e-3)
    graph.set_chain("a", [])  # an empty chain passes audio through unchanged
    assert np.allclose(graph.process({"a": block(0.1)}, N)["monitor"], 0.1)


def test_failing_chain_is_disabled_and_audio_keeps_flowing(graph):
    def boom(audio, sr, reset=False):
        raise RuntimeError("plugin crashed")

    graph.channels["a"].board = boom
    out = graph.process({"a": block(0.2)}, N)
    assert np.allclose(out["monitor"], 0.2)  # dry signal still comes through
    assert graph.channels["a"].board is None
    assert "plugin crashed" in graph.take_errors()[0]
    assert graph.take_errors() == []


def test_changes_while_live_wait_for_the_audio_thread(graph):
    graph.live = True
    graph.set_gain("a", "monitor", 0.25)
    assert graph.channels["a"].gains["monitor"] == 1.0  # queued, not applied yet
    graph.process({"a": block(1.0)}, N)  # applied at the start of the block
    assert graph.channels["a"].gains["monitor"] == 0.25


def test_a_bad_queued_change_does_not_stop_audio(graph):
    graph.live = True

    def bad():
        raise ValueError("nope")

    graph.submit(bad)
    out = graph.process({"a": block(0.2)}, N)
    assert np.allclose(out["monitor"], 0.2)
    assert "nope" in graph.take_errors()[0]


def test_removed_channels_stop_contributing(graph):
    graph.set_channels(["a"])
    out = graph.process({"a": block(0.2), "b": block(0.5)}, N)
    assert np.allclose(out["monitor"], 0.2)


def test_peaks_are_reported_and_reset(graph):
    graph.process({"a": block(0.3)}, N)
    peaks = graph.take_peaks()
    assert peaks["ch:a"] == pytest.approx(0.3)
    assert peaks["mix:monitor"] == pytest.approx(0.3)
    assert graph.take_peaks()["ch:a"] == 0.0


def test_zero_length_block_is_safe(graph):
    out = graph.process({"a": np.zeros((2, 0), dtype=np.float32)}, 0)
    assert out["monitor"].shape == (2, 0)


def test_nan_from_a_plugin_becomes_silence_not_noise(graph):
    def poison(audio, sr, reset=False):
        out = audio.copy()
        out[:, 10] = np.nan
        out[:, 20] = np.inf
        return out

    graph.channels["a"].board = poison
    out = graph.process({"a": block(0.2), "b": block(0.1)}, N)
    assert np.isfinite(out["monitor"]).all()
    assert out["monitor"][0, 10] == pytest.approx(0.1)  # only channel b contributes at the poisoned samples
