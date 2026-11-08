# SPDX-License-Identifier: GPL-3.0-or-later
"""Noise and echo reduction that work on the sound's spectrum (numpy only, no extra downloads).

Both are streaming processors for the audio thread: ``process((2, frames)) -> (2, frames)``. They cut the sound into
overlapping 21 ms pieces, work out for every frequency how much of it is wanted voice and how much is room, turn the
unwanted part down, and glue the pieces back together. That costs about 16 ms of delay.

*NoiseReducer* follows the steady part of the room (fan, air conditioner, traffic hiss) and lowers it. It can start from
the noise recorded by *Measure my room* instead of having to learn it. It cannot remove noise that changes like speech
does (a TV), and no spectral method can remove noise exactly where your voice is: it lowers it and keeps your voice.

*EchoReducer* lowers the late part of a room's echo (the tail that keeps going after a word ends), estimated from how
quickly echoes in that room die away. It cannot take echo off the first moments of a word.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


class StftEffect:
    """Overlap-add framework. Subclasses implement ``gain(power) -> (K,) array`` for each frame."""

    N = 1024                 # frame length: 21 ms at 48 kHz, 47 Hz per bin
    HOP = 256                # a new frame every 5.3 ms (75 % overlap)

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = int(sample_rate)
        self.K = self.N // 2 + 1
        self.window = np.sqrt(np.hanning(self.N + 1)[:-1]).astype(np.float32)       # sqrt-Hann twice = Hann, which adds up to 2 at 75 % overlap
        self._scale = 1.0 / 2.0
        self.latency = self.N - self.HOP                          # samples
        self.reset()

    def reset(self) -> None:
        self._frame = np.zeros((2, self.N), dtype=np.float32)
        self._ola = np.zeros((2, self.N), dtype=np.float32)
        self._in = np.zeros((2, 0), dtype=np.float32)
        self._out = np.zeros((2, 0), dtype=np.float32)

    def wake(self) -> None:
        """Called when sound returns after the channel was skipped for being silent: forget the half-processed audio,
        keep what was learned about the room."""
        self._frame[:] = 0.0
        self._ola[:] = 0.0
        self._in = np.zeros((2, 0), dtype=np.float32)
        self._out = np.zeros((2, 0), dtype=np.float32)

    def gain(self, power: np.ndarray) -> np.ndarray:  # pragma: no cover - overridden
        return np.ones(self.K)

    def process(self, audio: np.ndarray) -> np.ndarray:
        frames = audio.shape[1]
        self._in = np.concatenate([self._in, audio.astype(np.float32, copy=False)], axis=1) if self._in.shape[1] else audio.astype(np.float32)
        produced = []
        while self._in.shape[1] >= self.HOP:
            new, self._in = self._in[:, : self.HOP], self._in[:, self.HOP:]
            produced.append(self._hop(new))
        if produced:
            self._out = np.concatenate([self._out] + produced, axis=1)
        if self._out.shape[1] < frames:  # only for block sizes that are not a multiple of the hop: a little extra delay, once
            self._out = np.concatenate([np.zeros((2, frames - self._out.shape[1]), dtype=np.float32), self._out], axis=1)
        result, self._out = self._out[:, :frames], self._out[:, frames:]
        return result

    def _hop(self, new: np.ndarray) -> np.ndarray:
        self._frame = np.concatenate([self._frame[:, self.HOP:], new], axis=1)
        spectrum = np.fft.rfft(self._frame * self.window, axis=1)
        mixed = 0.5 * (spectrum[0] + spectrum[1])
        power = (mixed.real ** 2 + mixed.imag ** 2).astype(np.float64)  # judged on both channels together, applied to each
        g = self.gain(power).astype(np.float32)
        wave = np.fft.irfft(spectrum * g, n=self.N, axis=1) * self.window
        self._ola += wave * self._scale
        out = self._ola[:, : self.HOP].copy()
        self._ola[:, : self.N - self.HOP] = self._ola[:, self.HOP:]
        self._ola[:, self.N - self.HOP:] = 0.0
        return out


VOICE_BINS = slice(2, 170)   # about 90 Hz to 8 kHz at 48 kHz: where the voice is, so where "how much is it turning down" is read


def _db(g: np.ndarray) -> float:
    return float(20.0 * np.mean(np.log10(np.maximum(g[VOICE_BINS], 1e-4))))


class Joint(StftEffect):
    """Echo and noise reduction in ONE pass: each part works out its own gain from the same spectrum and the gains are
    multiplied. That is one transform instead of two, and 16 ms of delay instead of 32."""

    def __init__(self, parts: list) -> None:
        self.parts = list(parts)
        super().__init__(self.parts[0].sample_rate)

    def gain(self, power: np.ndarray) -> np.ndarray:
        g = self.parts[0].gain(power)
        for part in self.parts[1:]:
            g = g * part.gain(power)
        return g

    def wake(self) -> None:
        super().wake()
        for part in self.parts:
            part.wake()


def _smooth(g: np.ndarray) -> np.ndarray:
    """Average each frequency with its neighbours: stops single bins flickering on and off (the 'musical noise' of
    simple noise reducers)."""
    padded = np.concatenate([g[:1], g, g[-1:]])
    return 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]


class NoiseReducer(StftEffect):
    """Lowers steady noise. ``reduction_db`` is the most it will turn anything down (0 = off)."""

    ALPHA_P = 0.85            # smoothing of the signal's own spectrum
    WINDOW_FRAMES = 280       # the quietest moment of the last ~1.5 s is taken as the noise level
    SUBWINDOWS = 8            # (tracked as the minimum of 8 slices of that time, so it costs one comparison a frame)
    SPEECH_RATIO = 4.0        # louder than this over that quiet level counts as voice and is kept out of the noise estimate
    BETA = 0.97               # decision-directed a priori SNR (how much the last frame's result is trusted)

    def __init__(self, sample_rate: int, reduction_db: float = 12.0) -> None:
        self.reduction_db = reduction_db
        self._profile: Optional[np.ndarray] = None
        self.activity_db = 0.0   # how much it is turning the voice's frequencies down right now (negative dB), smoothed
        super().__init__(sample_rate)

    def reset(self) -> None:
        super().reset()
        self._noise: Optional[np.ndarray] = None
        self._ps = None
        self._slices = np.full((self.SUBWINDOWS, self.K), np.inf)
        self._slice_min = np.full(self.K, np.inf)
        self._at = 0
        self._slice_frames = 0
        self._speech = np.zeros(self.K)
        self._prev_gain = np.ones(self.K)
        self._prev_snr = np.ones(self.K)
        self._frames = 0
        if self._profile is not None:
            self._noise = self._profile.copy()

    def set_profile(self, power: Optional[np.ndarray]) -> None:
        """Start from this noise spectrum (the mean power per bin, length K) instead of learning it from scratch."""
        self._profile = None if power is None else np.asarray(power, dtype=np.float64).copy()
        self._noise = None if self._profile is None else self._profile.copy()

    def gain(self, power: np.ndarray) -> np.ndarray:
        floor = 10.0 ** (-max(0.0, self.reduction_db) / 20.0)
        if floor >= 0.999:
            return np.ones(self.K)
        self._frames += 1
        power = power + 1e-12
        if self._ps is None:
            self._ps = power.copy()
        self._ps = self.ALPHA_P * self._ps + (1 - self.ALPHA_P) * power
        np.minimum(self._slice_min, self._ps, out=self._slice_min)
        self._slice_frames += 1
        if self._slice_frames >= self.WINDOW_FRAMES // self.SUBWINDOWS:
            self._slices[self._at] = self._slice_min
            self._at = (self._at + 1) % self.SUBWINDOWS
            self._slice_min = self._ps.copy()
            self._slice_frames = 0
        quiet = np.minimum(self._slices.min(axis=0), self._slice_min) * 1.6              # the minimum runs low, so it is raised a little
        if self._noise is None:
            self._noise = quiet.copy()
        voice = self._ps / np.maximum(quiet, 1e-12) > self.SPEECH_RATIO
        self._speech = 0.9 * self._speech + 0.1 * voice
        rate = 0.92 + 0.08 * self._speech                          # a bin that looks like voice hardly updates the noise
        self._noise = rate * self._noise + (1 - rate) * np.minimum(power, quiet * 3.0)
        ratio = power / np.maximum(self._noise, 1e-12)             # a posteriori SNR
        snr = self.BETA * self._prev_gain ** 2 * self._prev_snr_post + (1 - self.BETA) * np.maximum(ratio - 1.0, 0.0) \
            if hasattr(self, "_prev_snr_post") else np.maximum(ratio - 1.0, 0.0)
        self._prev_snr_post = ratio
        g = snr / (1.0 + snr)                                      # Wiener gain
        g = np.clip(_smooth(g), floor, 1.0)
        self._prev_gain = g
        self.activity_db += 0.1 * (_db(g) - self.activity_db)
        return g


class EchoReducer(StftEffect):
    """Lowers the tail of a room's echo. ``reverb_time`` is how long the room's echo takes to die away (seconds, to
    -60 dB); ``reduction_db`` is the most it will turn anything down (0 = off)."""

    LATE_SECONDS = 0.05       # echo that arrives later than this after the sound is treated as 'tail'
    ALPHA = 0.7

    def __init__(self, sample_rate: int, reverb_time: float = 0.6, reduction_db: float = 9.0) -> None:
        self.reverb_time = reverb_time
        self.reduction_db = reduction_db
        self.activity_db = 0.0
        super().__init__(sample_rate)

    def reset(self) -> None:
        super().reset()
        self._delay = max(1, round(self.LATE_SECONDS * self.sample_rate / self.HOP))
        self._ring = np.zeros((self._delay + 1, self.K))
        self._at = 0
        self._ps: Optional[np.ndarray] = None
        self._prev = np.ones(self.K)

    def gain(self, power: np.ndarray) -> np.ndarray:
        floor = 10.0 ** (-max(0.0, self.reduction_db) / 20.0)
        power = power + 1e-12
        self._ps = power.copy() if self._ps is None else self.ALPHA * self._ps + (1 - self.ALPHA) * power
        late_before = self._ring[self._at].copy()                  # this frame's spectrum from LATE_SECONDS ago
        self._ring[self._at] = self._ps
        self._at = (self._at + 1) % len(self._ring)
        decay = 10.0 ** (-6.0 * self.LATE_SECONDS / max(0.1, self.reverb_time))   # the echo's power after that long
        tail = decay * late_before
        g = np.sqrt(np.clip(1.0 - tail / power, 0.0, 1.0))
        g = np.clip(_smooth(g), floor, 1.0)
        g = np.where(g < self._prev, 0.5 * self._prev + 0.5 * g, g)  # fall quickly, but not in one jump
        self._prev = g
        self.activity_db += 0.1 * (_db(g) - self.activity_db)
        return g

    def wake(self) -> None:
        super().wake()
        self._ring[:] = 0.0      # what it remembers is from before the silence: it would be taken for an echo of the new sound
        self._ps = None
        self._prev = np.ones(self.K)
