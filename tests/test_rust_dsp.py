# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rust reducers (rust/sluice_dsp) must give the same sound as the Python ones. Skipped when the module is not built."""
import os

import numpy as np
import pytest

rust = pytest.importorskip("sluice_dsp")

from sluice import spectral as py  # noqa: E402

SR = 48000
BLOCKS = [256, 512, 480, 1000]  # includes sizes that are not a multiple of the hop


def signal(seconds=4.0, seed=1):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    gate = np.sin(2 * np.pi * 1.5 * t) > 0
    voice = np.sin(2 * np.pi * 180 * t) * gate * 0.3 + 0.1 * np.sin(2 * np.pi * 1200 * t) * gate
    return np.stack([voice + rng.normal(0, 0.02, n), 0.9 * voice + rng.normal(0, 0.02, n)]).astype(np.float32)


def run(effect, x, blocks=BLOCKS):
    outs, pos, i = [], 0, 0
    while pos < x.shape[1]:
        b = blocks[i % len(blocks)]
        i += 1
        outs.append(np.asarray(effect.process(x[:, pos:pos + b])))
        pos += b
    return np.concatenate(outs, axis=1)


def close(a, b):
    assert a.shape == b.shape
    assert np.max(np.abs(a - b)) < 1e-5


@pytest.mark.parametrize("reduction", [0.0, 6.0, 12.0, 24.0])
def test_noise_reducer_matches_python(reduction):
    x = signal()
    close(run(py.PythonNoiseReducer(SR, reduction), x), run(rust.NoiseReducer(SR, reduction), x))


@pytest.mark.parametrize("reverb,reduction", [(0.3, 6.0), (0.6, 9.0), (1.0, 15.0)])
def test_echo_reducer_matches_python(reverb, reduction):
    x = signal()
    close(run(py.PythonEchoReducer(SR, reverb, reduction), x), run(rust.EchoReducer(SR, reverb, reduction), x))


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
def test_sample_rates_match(rate):
    x = signal(2.0)
    close(run(py.PythonEchoReducer(rate), x), run(rust.EchoReducer(rate), x))


def test_joint_matches_python():
    x = signal()
    a = py.PythonJoint([py.PythonEchoReducer(SR, 0.6, 9.0), py.PythonNoiseReducer(SR, 15.0)])
    b = rust.Joint([rust.EchoReducer(SR, 0.6, 9.0), rust.NoiseReducer(SR, 15.0)])
    close(run(a, x), run(b, x))


def test_activity_numbers_match():
    x = signal()
    a, b = py.PythonNoiseReducer(SR, 12.0), rust.NoiseReducer(SR, 12.0)
    run(a, x), run(b, x)
    assert abs(a.activity_db - b.activity_db) < 1e-3 and a.activity_db < -1.0


def test_settings_can_change_while_running():
    x = signal(3.0)
    a, b = py.PythonNoiseReducer(SR, 6.0), rust.NoiseReducer(SR, 6.0)
    first, second = x[:, :SR], x[:, SR:]
    outs = [run(a, first), run(b, first)]
    a.reduction_db = b.reduction_db = 20.0
    outs += [run(a, second), run(b, second)]
    close(np.concatenate([outs[0], outs[2]], axis=1), np.concatenate([outs[1], outs[3]], axis=1))


def test_a_profile_is_used_and_wake_and_reset_behave():
    x = signal()
    profile = np.full(513, 1e-3)
    a, b = py.PythonNoiseReducer(SR, 12.0), rust.NoiseReducer(SR, 12.0)
    a.set_profile(profile)
    b.set_profile(profile)
    assert b.has_profile
    close(run(a, x), run(b, x))
    a.wake(), b.wake()
    close(run(a, x), run(b, x))
    a.reset(), b.reset()
    close(run(a, x), run(b, x))
    b.set_profile(None)
    assert not b.has_profile
    with pytest.raises(ValueError):
        b.set_profile(np.ones(10))


def test_bad_input_is_an_error_not_a_crash():
    with pytest.raises(ValueError):
        rust.NoiseReducer(SR).process(np.zeros((1, 512), dtype=np.float32))
    with pytest.raises(ValueError):
        rust.Joint([])
    with pytest.raises(ValueError):
        rust.Joint([py.PythonNoiseReducer(SR)])


def test_silence_stays_silent_and_empty_blocks_work():
    for fx in (rust.NoiseReducer(SR), rust.EchoReducer(SR)):
        assert np.asarray(fx.process(np.zeros((2, 0), dtype=np.float32))).shape == (2, 0)
        out = run(fx, np.zeros((2, 4000), dtype=np.float32))
        assert not np.isnan(out).any() and np.max(np.abs(out)) < 1e-6


@pytest.mark.skipif(bool(os.environ.get('SLUICE_NO_RUST')), reason='Rust switched off')
def test_the_application_picks_the_rust_classes():
    assert py.BACKEND == "rust" and py.NoiseReducer is rust.NoiseReducer
