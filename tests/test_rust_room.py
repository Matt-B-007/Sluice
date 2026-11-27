# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rust room/echo/voice arithmetic gives the numpy results; the results of whole analyses agree."""

import importlib

import numpy as np
import pytest

rust = pytest.importorskip("sluice_dsp")
if not hasattr(rust, "echo_energy"):
    pytest.skip("older sluice_dsp build", allow_module_level=True)

import os  # noqa: E402

if os.environ.get("SLUICE_NO_RUST") or os.environ.get("SLUICE_NO_RUST_ROOM"):
    pytest.skip("Rust switched off", allow_module_level=True)

SR = 48000


@pytest.fixture
def both(monkeypatch):
    """(rust module, python module): room.py loaded once with Rust and once without."""
    import sluice.room as with_rust

    monkeypatch.setenv("SLUICE_NO_RUST_ROOM", "1")
    importlib.reload(with_rust)
    py_copy = importlib.import_module("sluice.room")
    snapshot = type("M", (), {k: getattr(py_copy, k) for k in dir(py_copy) if not k.startswith("__")})
    monkeypatch.delenv("SLUICE_NO_RUST_ROOM")
    importlib.reload(py_copy)
    return py_copy, snapshot


def room_noise(seconds=5.5, db=-50, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((2, int(SR * seconds))) * 10 ** (db / 20)).astype(np.float32)


def test_blocks_match(both):
    fast, ref = both
    assert fast.ROOM_BACKEND == "rust" and ref.ROOM_BACKEND == "python"
    x = room_noise()
    np.testing.assert_allclose(fast._block_peaks_db(x, SR), ref._block_peaks_db(x, SR), atol=1e-4)


def test_noise_profile_matches(both):
    fast, ref = both
    x = room_noise(2.0)
    a, b = fast.noise_profile(x), ref.noise_profile(x)
    assert a.shape == b.shape == (513,)
    np.testing.assert_allclose(a, b, rtol=1e-4, atol=1e-12)


def test_room_analysis_agrees(both):
    fast, ref = both
    x = room_noise(db=-45)
    a, b = fast.analyse(x, SR), ref.analyse(x, SR)
    assert a.status == b.status == "ok"
    assert a.threshold_db == pytest.approx(b.threshold_db, abs=0.1)
    np.testing.assert_allclose(a.profile, b.profile, rtol=1e-4, atol=1e-12)


def clap(seconds=4.0, rt=0.6, seed=2):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    x = rng.standard_normal(n) * 1e-4
    t = np.arange(int(SR * 1.5)) / SR
    tail = rng.standard_normal(len(t)) * np.exp(-6.9 * t / rt) * 0.5
    start = SR
    x[start : start + len(t)] += tail
    return np.stack([x, x]).astype(np.float32)


def test_echo_analysis_agrees_including_odd_lengths(both):
    fast, ref = both
    for extra in (0, 1, 3):
        x = clap()[:, : int(SR * 4) + extra]
        a, b = fast.analyse_echo(x, SR), ref.analyse_echo(x, SR)
        assert a.status == b.status == "ok"
        assert a.reverb_time == pytest.approx(b.reverb_time, abs=0.02)


def test_voice_analysis_agrees(both):
    fast, ref = both
    rng = np.random.default_rng(5)
    n = SR * 7
    env = (np.sin(2 * np.pi * 1.5 * np.arange(n) / SR) > 0).astype(np.float32) * 0.1 + 0.002
    x = (rng.standard_normal((2, n)) * env).astype(np.float32)
    a, b = fast.analyse_voice(x, SR), ref.analyse_voice(x, SR)
    assert a.status == b.status
    assert a.level_db == pytest.approx(b.level_db, abs=0.01)
    assert a.change_db == pytest.approx(b.change_db, abs=0.1)
