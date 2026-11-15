# SPDX-License-Identifier: GPL-3.0-or-later
import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole run: Qt cannot safely create a second one after the first is gone."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def clap_room():
    """A function ``clap_room(rt60, noise_db, seed=0)``: four seconds of microphone signal (2, n) with one clap in a
    simulated room whose echo dies away in ``rt60`` seconds, over room noise at ``noise_db`` dB."""
    sr = 48000

    def make(rt60, noise_db, seed=0):
        rng = np.random.default_rng(seed)
        n = int(sr * rt60 * 1.3)
        t = np.arange(n) / sr
        tail = rng.standard_normal(n) * 10 ** (-3 * t / rt60)
        tail[: int(0.004 * sr)] = 0
        tail *= 1.0 / np.sqrt(np.sum(tail ** 2))
        h = tail.copy()
        h[int(0.002 * sr)] += 1.0
        clap = np.zeros(sr * 4)
        clap[sr:sr + 30] = rng.standard_normal(30) * 0.8
        x = np.convolve(clap, h)[: clap.size]
        x = x / np.max(np.abs(x)) * 0.5
        hum = rng.standard_normal(x.size) * 10 ** (noise_db / 20)
        return np.stack([x + hum, x + hum]).astype(np.float32)

    return make
