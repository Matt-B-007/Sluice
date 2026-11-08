# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
import pytest

from sluice.effects import Chain, EffectInstance, Stage, _pedalboard
from sluice.model import Effect
from sluice.spectral import EchoReducer, NoiseReducer, StftEffect

SR = 48000


def run(fx, x, block=512):
    n = x.shape[1] // block * block
    out = np.concatenate([fx.process(x[:, i:i + block]) for i in range(0, n, block)], axis=1)
    return out[:, fx.latency:], x[:, :out.shape[1] - fx.latency]


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def test_the_framework_alone_changes_nothing():
    x = (np.random.default_rng(0).standard_normal((2, SR)) * 0.1).astype(np.float32)
    out, ref = run(StftEffect(SR), x)
    assert np.max(np.abs(out[:, 2048:] - ref[:, 2048:])) < 1e-5


def test_block_size_does_not_matter():
    x = (np.random.default_rng(1).standard_normal((2, SR)) * 0.1).astype(np.float32)
    a, _ = run(NoiseReducer(SR), x, 256)
    b, _ = run(NoiseReducer(SR), x, 480)  # not a multiple of the hop: only a little extra delay at the start
    assert a.shape[0] == 2 and np.isfinite(b).all()


def test_steady_noise_is_lowered_and_a_voice_like_tone_is_kept():
    rng = np.random.default_rng(2)
    t = np.arange(6 * SR) / SR
    noise = rng.standard_normal((2, t.size)) * 0.02
    tone = np.sin(2 * np.pi * 440 * t) * 0.2 * ((t > 3) & (t < 5))
    x = (noise + tone).astype(np.float32)
    out, ref = run(NoiseReducer(SR, 12), x)
    quiet = slice(int(2 * SR), int(2.9 * SR))
    assert rms_db(ref[:, quiet]) - rms_db(out[:, quiet]) > 6          # the noise went down
    loud = slice(int(3.5 * SR), int(4.5 * SR))
    assert abs(rms_db(out[:, loud]) - rms_db(ref[:, loud])) < 2        # the tone stayed


def test_reduction_zero_is_a_pass_through():
    x = (np.random.default_rng(3).standard_normal((2, SR)) * 0.1).astype(np.float32)
    out, ref = run(NoiseReducer(SR, 0), x)
    assert np.max(np.abs(out[:, 2048:] - ref[:, 2048:])) < 1e-5


def test_the_echo_tail_after_a_burst_is_lowered():
    rng = np.random.default_rng(4)
    burst = rng.standard_normal(int(0.3 * SR)) * 0.3
    t = np.arange(int(0.8 * SR)) / SR
    tail = rng.standard_normal(t.size) * 0.3 * 10 ** (-60 * t / 0.6 / 20 * 1.0)  # echo dying away over 0.6 s
    mono = np.concatenate([np.zeros(SR), burst, np.zeros(int(0.5 * SR))])
    mono[SR + burst.size:SR + burst.size + tail.size][:int(0.5 * SR)] += tail[:int(0.5 * SR)]
    x = np.stack([mono, mono]).astype(np.float32)
    out, ref = run(EchoReducer(SR, 0.6, 12), x)
    late = slice(SR + burst.size + int(0.1 * SR), SR + burst.size + int(0.4 * SR))
    assert rms_db(ref[:, late]) - rms_db(out[:, late]) > 3
    during = slice(SR + int(0.05 * SR), SR + int(0.25 * SR))
    assert abs(rms_db(out[:, during]) - rms_db(ref[:, during])) < 3    # the sound itself is left alone


def test_a_profile_from_the_room_can_be_set():
    fx = NoiseReducer(SR)
    fx.set_profile(np.ones(fx.K))
    assert np.allclose(fx._noise, 1.0)
    fx.set_profile(None)
    assert fx._noise is None


def test_stage_applies_changed_values_live():
    stage = Stage(lambda sr: NoiseReducer(sr), {"reduction_db": 12.0})
    stage.process(np.zeros((2, 512), dtype=np.float32), SR)
    stage.set("reduction_db", 3.0)
    assert stage._processor.reduction_db == 3.0


def test_built_in_effects_load_and_take_parameters():
    for kind in ("echo_reducer", "noise_reducer"):
        inst = EffectInstance(Effect("x", "builtin", kind, type=kind))
        assert inst.usable and inst.items == [inst.stage] and inst.plugins == []
        inst.set_param("reduction_db", 5.0)
        assert inst.effect.params["reduction_db"] == 5.0 and inst.stage.values["reduction_db"] == 5.0


def test_a_chain_mixes_plugins_and_stages_in_order():
    pb = _pedalboard()
    if pb is None:
        pytest.skip("pedalboard not installed")
    gain = EffectInstance(Effect("g", "builtin", "gain", type="gain", params={"gain_db": 6.0}))
    nr = EffectInstance(Effect("n", "builtin", "noise_reducer", type="noise_reducer", params={"reduction_db": 0.0}))
    chain = Chain(pb, gain.items + nr.items + gain.items)
    x = np.full((2, 4096), 0.05, dtype=np.float32)
    out = chain(x, SR)
    assert out.shape == x.shape and out.dtype == np.float32
    assert len(chain._parts) == 3


# ---------------------------------------------------------------- one pass, waking, activity
def test_neighbouring_reducers_run_as_one_pass_with_16_ms_of_delay():
    from sluice.effects import JointStage

    pb = _pedalboard()
    if pb is None:
        pytest.skip("pedalboard not installed")
    echo = EffectInstance(Effect("e", "builtin", "echo_reducer", type="echo_reducer"))
    noise = EffectInstance(Effect("n", "builtin", "noise_reducer", type="noise_reducer"))
    chain = Chain(pb, echo.items + noise.items)
    assert len(chain._parts) == 1 and isinstance(chain._parts[0], JointStage)
    x = (np.random.default_rng(5).standard_normal((2, SR)) * 0.05).astype(np.float32)
    out = np.concatenate([chain(x[:, i:i + 512], SR) for i in range(0, SR - 511, 512)], axis=1)
    assert np.isfinite(out).all() and out.shape[1] == (SR // 512) * 512
    assert StftEffect(SR).latency / SR == pytest.approx(0.016)


def test_a_separated_reducer_pair_is_not_merged():
    pb = _pedalboard()
    if pb is None:
        pytest.skip("pedalboard not installed")
    echo = EffectInstance(Effect("e", "builtin", "echo_reducer", type="echo_reducer"))
    gain = EffectInstance(Effect("g", "builtin", "gain", type="gain"))
    noise = EffectInstance(Effect("n", "builtin", "noise_reducer", type="noise_reducer"))
    assert len(Chain(pb, echo.items + gain.items + noise.items)._parts) == 3


def test_waking_clears_what_the_echo_reducer_remembers_but_keeps_the_noise_it_learned():
    echo = EchoReducer(SR, 0.6, 12)
    noise = NoiseReducer(SR, 12)
    x = (np.random.default_rng(6).standard_normal((2, SR)) * 0.2).astype(np.float32)
    run(echo, x)
    run(noise, x)
    learned = noise._noise.copy()
    echo.wake()
    noise.wake()
    assert not echo._ring.any() and not echo._out.size
    assert np.array_equal(noise._noise, learned)


def test_the_graph_wakes_a_chain_when_sound_returns_after_a_long_silence():
    from sluice.dsp import SILENCE_TAIL_SECONDS, Graph

    pb = _pedalboard()
    if pb is None:
        pytest.skip("pedalboard not installed")
    graph = Graph(SR, ["a"])
    graph.set_channels(["mic"])
    graph.set_gain("mic", "a", 1.0)
    woken = []

    class Spy:
        def __call__(self, audio, sample_rate, reset=False):
            return audio

        def wake(self):
            woken.append(1)

    graph.process({"mic": np.zeros((2, 512), dtype=np.float32)}, 512)
    graph.channels["mic"].board = Spy()
    for _ in range(int(SILENCE_TAIL_SECONDS * SR / 512) + 3):
        graph.process({"mic": np.zeros((2, 512), dtype=np.float32)}, 512)
    assert not woken
    graph.process({"mic": np.full((2, 512), 0.1, dtype=np.float32)}, 512)
    graph.process({"mic": np.full((2, 512), 0.1, dtype=np.float32)}, 512)
    assert woken == [1]  # once, not every block


def test_the_reducers_report_how_much_they_are_turning_the_voice_down():
    rng = np.random.default_rng(7)
    x = (rng.standard_normal((2, 4 * SR)) * 0.02).astype(np.float32)
    fx = NoiseReducer(SR, 12)
    run(fx, x)
    assert fx.activity_db < -3
    off = NoiseReducer(SR, 0)
    run(off, x)
    assert off.activity_db == 0.0


def test_a_noise_profile_helps_the_reducer_start_with_the_right_level():
    from sluice import room

    rng = np.random.default_rng(8)
    noise = (rng.standard_normal((2, 3 * SR)) * 0.02).astype(np.float32)
    profile = room.noise_profile(noise)
    assert profile.shape == (513,) and (profile > 0).all()
    fx = NoiseReducer(SR, 12)
    fx.set_profile(profile)
    out, ref = run(fx, noise[:, : SR // 2])
    assert rms_db(ref[:, 4096:]) - rms_db(out[:, 4096:]) > 3  # quiet at once, with no learning time
