# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rust mixing kernels give the numpy results (to float rounding)."""
import numpy as np
import pytest

from sluice.dsp import PythonPeakLimiter, _curve

rust = pytest.importorskip("sluice_dsp")
if not hasattr(rust, "finish_mix"):
    pytest.skip("older sluice_dsp build", allow_module_level=True)

SR = 48000


def noise(frames, amp=1.5, seed=1):
    return (np.random.default_rng(seed).standard_normal((2, frames)) * amp).astype(np.float32)


@pytest.mark.parametrize("frames", [1, 7, 512, 1024, 1500, 4096])
def test_limiter_matches_python_across_blocks(frames):
    a, b = PythonPeakLimiter(SR), rust.PeakLimiter(SR)
    for seed in range(4):
        x = noise(frames, seed=seed)
        np.testing.assert_allclose(b.process(x), a.process(x), atol=2e-6)


def test_limiter_never_exceeds_the_ceiling():
    lim = rust.PeakLimiter(SR, -1.0, 100.0)
    out = lim.process(noise(8192, amp=4.0))
    assert np.abs(out).max() <= 10 ** (-1 / 20) * 1.00001


def test_block_stats():
    x = noise(256)
    peak, nonzero, finite = rust.block_stats(x)
    assert peak == pytest.approx(np.abs(x).max()) and nonzero and finite
    x[0, 3] = np.nan
    assert rust.block_stats(x)[2] is False
    assert rust.block_stats(np.zeros((2, 8), np.float32)) == (0.0, False, True)


@pytest.mark.parametrize("prev,target", [(0.5, 0.5), (0.0, 1.0), (1.0, 0.25)])
@pytest.mark.parametrize("frames", [1, 2, 512])
def test_accumulate_matches_numpy(prev, target, frames):
    x, base = noise(frames), noise(frames, seed=9)
    want = base + x * _curve(prev, target, frames)
    got = base.copy()
    rust.accumulate(got, x, prev, target)
    np.testing.assert_allclose(got, want, atol=1e-6)


@pytest.mark.parametrize("limited", [True, False])
def test_finish_mix_matches_numpy(limited):
    a = PythonPeakLimiter(SR)
    b = rust.PeakLimiter(SR)
    for seed in range(3):
        x = noise(512, seed=seed)
        want = x * _curve(0.8, 1.2, 512)
        if limited:
            want = np.clip(a.process(want), -1, 1)
        got = x.copy()
        peak = rust.finish_mix(got, 0.8, 1.2, b if limited else None)
        np.testing.assert_allclose(got, want, atol=2e-6)
        assert peak == pytest.approx(np.abs(want).max(), abs=2e-6)
