# SPDX-License-Identifier: GPL-3.0-or-later
"""The gate, compressor and limiter of the built-in effects (0.12.0), one implementation for both engines.

Before 0.12.0 these copied pedalboard's (JUCE's) and existed twice, in Rust and as pedalboard's own:
- the Limiter added make-up gain after limiting, so its "Ceiling" was not a ceiling (a -2 dB setting peaked at full scale and
  clipped), behind a hidden 4:1 compressor at -10 dB;
- the compressor and the gate followed left and right separately, so a stereo sound louder on one side moved sideways;
- the gate had no hold and no hysteresis, so it chattered and cut off the ends of words.

These work in steps of about a millisecond: the level is measured over each step (both channels together), the gain for the end
of the step is worked out, and the gain glides there sample by sample. That is a few dozen Python steps per audio block, cheap,
and the same on every computer, with or without the Rust engine. The limiter is the brick-wall one the Listen and Broadcast mixes
already use (dsp.PeakLimiter: Rust when it is there), which never lets a sample past its ceiling."""

from __future__ import annotations

import math

import numpy as np

STEP_MS = 1.0
FLOOR_DB = -120.0


def _step(sample_rate: int) -> int:
    return max(16, int(round(sample_rate * STEP_MS / 1000.0)))


def _coefficient(ms: float, step_seconds: float) -> float:
    """How much of the old value is kept per step for a smoothing time of ``ms`` (0: none)."""
    return math.exp(-step_seconds / (ms / 1000.0)) if ms > 0 else 0.0


def _apply(audio: np.ndarray, start_db: float, ends_db: list, step: int) -> np.ndarray:
    """``audio`` times a gain that glides, step by step, from ``start_db`` to each value of ``ends_db`` (one per step)."""
    frames = audio.shape[1]
    points_db = np.array([start_db] + list(ends_db), dtype=np.float64)
    where = np.minimum(np.arange(len(points_db)) * step, frames)
    gain = np.interp(np.arange(frames), where, 10.0 ** (points_db / 20.0)).astype(np.float32)
    return audio * gain


def _levels(audio: np.ndarray, step: int, rms: bool) -> list:
    """The level of each step in dB, both channels together: the peak, or the RMS (the mean of both channels' squares)."""
    frames = audio.shape[1]
    whole = frames // step * step
    values = []
    if whole:
        part = audio[:, :whole].reshape(2, -1, step)
        values = (
            np.sqrt(np.mean(np.square(part, dtype=np.float64), axis=(0, 2))) if rms else np.max(np.abs(part), axis=(0, 2))
        ).tolist()
    if whole < frames:
        rest = audio[:, whole:]
        values.append(float(np.sqrt(np.mean(np.square(rest, dtype=np.float64)))) if rms else float(np.max(np.abs(rest))))
    return [20.0 * math.log10(v) if v > 1e-6 else FLOOR_DB for v in values]


class VoiceGate:
    """A gate that quiets the room between words. Opens above ``threshold_db``; stays open for ``hold_ms`` after the voice drops;
    closes only once the level is ``HYSTERESIS`` dB below the threshold (no chattering on a level that hovers there); then turns
    down by ``depth_db``. ``attack_ms`` and ``release_ms`` are how fast it opens and closes."""

    HYSTERESIS = 4.0
    SENSE_MS = 10.0  # the level it listens to is smoothed over this long (a single millisecond would follow every wave)

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.threshold_db, self.depth_db, self.attack_ms, self.hold_ms, self.release_ms = -40.0, 24.0, 2.0, 120.0, 150.0
        self._level_db = FLOOR_DB
        self._open = False
        self._held = 0.0
        self._gain_db = -24.0
        self.activity_db = 0.0

    def wake(self) -> None:
        self._level_db = FLOOR_DB

    def process(self, audio: np.ndarray) -> np.ndarray:
        step = _step(self.sample_rate)
        seconds = step / self.sample_rate
        sense = _coefficient(self.SENSE_MS, seconds)
        depth = max(0.0, self.depth_db)
        open_rate = depth / max(self.attack_ms / 1000.0, seconds) * seconds  # dB per step
        close_rate = depth / max(self.release_ms / 1000.0, seconds) * seconds
        start = self._gain_db
        ends = []
        for level in _levels(audio, step, rms=True):
            power = 10.0 ** (level / 10.0)
            smoothed = 10.0 ** (self._level_db / 10.0) * sense + power * (1.0 - sense)
            self._level_db = 10.0 * math.log10(smoothed) if smoothed > 1e-12 else FLOOR_DB
            if self._level_db >= self.threshold_db:
                self._open, self._held = True, self.hold_ms / 1000.0
            elif self._level_db < self.threshold_db - self.HYSTERESIS:
                if self._held > 0:
                    self._held -= seconds
                else:
                    self._open = False
            target = 0.0 if self._open else -depth
            if self._gain_db < target:
                self._gain_db = min(target, self._gain_db + open_rate)
            elif self._gain_db > target:
                self._gain_db = max(target, self._gain_db - close_rate)
            ends.append(self._gain_db)
        self.activity_db = self._gain_db
        return _apply(audio, start, ends, step)


class LinkedCompressor:
    """A compressor following both channels together (a stereo sound stays where it is), with a soft knee of ``KNEE`` dB. Turns
    down what goes over ``threshold_db`` by ``ratio``, over ``attack_ms`` / ``release_ms``, then adds ``makeup_db``."""

    KNEE = 6.0

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.threshold_db, self.ratio, self.attack_ms, self.release_ms, self.makeup_db = -18.0, 3.0, 10.0, 100.0, 2.0
        self._env_db = FLOOR_DB
        self._gain_db = None
        self.activity_db = 0.0

    def wake(self) -> None:
        self._env_db = FLOOR_DB

    def reduction(self, level_db: float) -> float:
        """How many dB to take off at this level (0 or negative)."""
        over = level_db - self.threshold_db
        slope = 1.0 / max(1.0, self.ratio) - 1.0
        half = self.KNEE / 2.0
        if over <= -half:
            return 0.0
        if over < half:
            return slope * (over + half) ** 2 / (2.0 * self.KNEE)
        return slope * over

    def process(self, audio: np.ndarray) -> np.ndarray:
        step = _step(self.sample_rate)
        seconds = step / self.sample_rate
        attack, release = _coefficient(self.attack_ms, seconds), _coefficient(self.release_ms, seconds)
        start = self._gain_db if self._gain_db is not None else self.makeup_db
        ends = []
        for level in _levels(audio, step, rms=False):
            keep = attack if level > self._env_db else release
            self._env_db = level + keep * (self._env_db - level)
            cut = self.reduction(self._env_db)
            self.activity_db = cut
            ends.append(cut + self.makeup_db)
        self._gain_db = ends[-1] if ends else start
        return _apply(audio, start, ends, step)


class CeilingLimiter:
    """The brick-wall limiter of the Listen and Broadcast mixes, as a channel effect: no sample goes past ``threshold_db`` (the
    Ceiling), and it lets go over ``release_ms``. No make-up gain: what is under the ceiling comes out as it went in."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._threshold_db, self._release_ms = -2.0, 60.0
        self._limiter = None
        self.activity_db = 0.0

    @property
    def threshold_db(self) -> float:
        return self._threshold_db

    @threshold_db.setter
    def threshold_db(self, value: float) -> None:
        if value != self._threshold_db:
            self._threshold_db, self._limiter = float(value), None

    @property
    def release_ms(self) -> float:
        return self._release_ms

    @release_ms.setter
    def release_ms(self, value: float) -> None:
        if value != self._release_ms:
            self._release_ms, self._limiter = float(value), None

    def wake(self) -> None:
        pass

    def process(self, audio: np.ndarray) -> np.ndarray:
        if self._limiter is None:
            from .dsp import PeakLimiter

            self._limiter = PeakLimiter(self.sample_rate, self._threshold_db, self._release_ms)
        out = np.asarray(self._limiter.process(np.ascontiguousarray(audio, dtype=np.float32)), dtype=np.float32)
        before, after = float(np.max(np.abs(audio))) if audio.size else 0.0, float(np.max(np.abs(out))) if out.size else 0.0
        self.activity_db = 20.0 * math.log10(after / before) if before > 1e-6 and after > 0 else 0.0
        return out


# 0.13.1: the classes above are the reference and the fallback. The Rust engine (0.12.0 and later) has the same three with the
# same settings and results (tests/test_native_graph.py compares them); using them lets a chain of built-in effects run in the
# Rust audio path without Python. SLUICE_NO_RUST=1 keeps these.
PythonVoiceGate, PythonLinkedCompressor, PythonCeilingLimiter = VoiceGate, LinkedCompressor, CeilingLimiter
if not __import__("os").environ.get("SLUICE_NO_RUST"):
    try:
        import sluice_dsp as _rust

        if hasattr(_rust, "VoiceGate"):
            VoiceGate, LinkedCompressor, CeilingLimiter = _rust.VoiceGate, _rust.LinkedCompressor, _rust.CeilingLimiter
    except Exception:  # no Rust engine, or one built for another Python: the Python ones are used
        pass
