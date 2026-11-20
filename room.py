# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure the room: turn a few quiet seconds from the microphone into a noise-gate threshold.

The noise gate needs a threshold just above the room's noise, and that depends on how loud the room is and on the
microphone's gain, so no fixed number suits everybody. This listens to the channel's input while the person stays
quiet, passes it through the effects that come before the gate (gain, high-pass), looks at the loudest moment of every
10 ms, and puts the threshold a little above the loud end of those. On a simulated noisy room that margin cut steady
noise by 17 to 18 dB in five of six simulated rooms (12 dB in the one too loud for a gate) without touching quiet
speech (``python tools/tune_room.py`` repeats it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

LISTEN_SECONDS = 5.0       # how long the microphone is listened to
SKIP_SECONDS = 0.5         # the first moments are thrown away: the click of the button, a breath, settling in
BLOCK_MS = 10              # the room is judged in 10 ms pieces
MARGIN_DB = 4.0            # threshold = the loud end of the room's noise (95th percentile of the pieces) + this
CEILING_DB = -22.0         # a gate above this would cut into ordinary speech, so it never goes higher
FLOOR_DB = -60.0           # a room quieter than this hardly needs a gate
NOTHING_DB = -80.0         # below this there is no signal at all (muted, wrong or disconnected microphone)
SUDDEN_DB = 12.0           # steady noise stays within a few dB of itself; a voice, a door or a cough jumps far above


@dataclass
class RoomResult:
    status: str            # "ok", "quiet_room", "too_loud", "disturbed" or "silent"
    threshold_db: float    # what to set the gate to (only meant to be used for ok, quiet_room and too_loud)
    noise_db: float        # the loud end of the room's noise, in dB below full scale
    message: str           # plain words for the person
    profile: Optional[np.ndarray] = None   # the room's noise spectrum, for the Noise Reducer to start from

    @property
    def usable(self) -> bool:
        return self.status in ("ok", "quiet_room", "too_loud")


def _block_peaks_db(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    size = max(1, int(sample_rate * BLOCK_MS / 1000))
    mono = np.max(np.abs(audio), axis=0) if audio.ndim == 2 else np.abs(audio)
    blocks = len(mono) // size
    if blocks == 0:
        return np.array([], dtype=np.float64)
    peaks = mono[: blocks * size].reshape(blocks, size).max(axis=1)
    return 20.0 * np.log10(np.maximum(peaks, 1e-9))


def analyse(audio: np.ndarray, sample_rate: int, before: Optional[Callable] = None) -> RoomResult:
    result = _analyse(audio, sample_rate, before)
    if result.status in ("ok", "quiet_room", "too_loud"):
        result.profile = noise_profile(np.asarray(audio, dtype=np.float32)[:, int(SKIP_SECONDS * sample_rate):])
    return result


def _analyse(audio: np.ndarray, sample_rate: int, before: Optional[Callable] = None) -> RoomResult:
    """``audio`` is (2, n) from the channel's input. ``before`` (optional) runs the effects ahead of the gate on it."""
    audio = np.asarray(audio, dtype=np.float32)
    audio = audio[:, int(SKIP_SECONDS * sample_rate):]
    if audio.shape[1] < sample_rate:
        return RoomResult("silent", FLOOR_DB, NOTHING_DB, "That was too short to measure. Please try again.")
    if float(np.max(np.abs(audio))) < 10 ** (NOTHING_DB / 20):
        return RoomResult("silent", FLOOR_DB, NOTHING_DB,
                          "I heard nothing at all. Is the right microphone selected and not muted? "
                          "(Check the Mic channel's input and the mute buttons.)")
    if before is not None:
        audio = np.asarray(before(audio), dtype=np.float32)
    peaks = _block_peaks_db(audio, sample_rate)
    if len(peaks) < 50:
        return RoomResult("silent", FLOOR_DB, NOTHING_DB, "That was too short to measure. Please try again.")
    p50, p95, p99 = (float(np.percentile(peaks, q)) for q in (50, 95, 99))
    if p99 - p50 > SUDDEN_DB:
        return RoomResult(
            "disturbed", min(CEILING_DB, p95 + MARGIN_DB), p95,
            "I heard something sudden (talking, a cough, a door, a keyboard?) while measuring, so the result could be "
            "set too high and cut into your voice. Please try again and stay quiet for the whole time.")
    threshold = p95 + MARGIN_DB
    if threshold < FLOOR_DB:
        return RoomResult("quiet_room", FLOOR_DB, p95,
                          f"Your room is very quiet (about {p95:.0f} dB). The gate is set to {FLOOR_DB:.0f} dB and "
                          "will hardly need to work.")
    if threshold > CEILING_DB:
        return RoomResult(
            "too_loud", CEILING_DB, p95,
            f"Your room is loud: its noise reaches about {p95:.0f} dB, close to the level of ordinary speech. "
            f"The gate is set as high as is safe ({CEILING_DB:.0f} dB), but it can only quiet part of the noise. "
            "Moving the microphone closer to your mouth, or turning its gain down, helps more than any setting.")
    return RoomResult("ok", round(threshold, 1), p95,
                      f"Your room's noise reaches about {p95:.0f} dB. The gate threshold is set to {threshold:.1f} dB, "
                      "just above it.")


# ------------------------------------------------------------------------------------------ noise profile
def noise_profile(audio: np.ndarray) -> np.ndarray:
    """The mean power of each frequency (513 of them) in a quiet recording, as the Noise Reducer measures it
    (1024-sample pieces, a square-root Hann window, both channels averaged)."""
    from .spectral import StftEffect

    window = np.sqrt(np.hanning(StftEffect.N + 1)[:-1]).astype(np.float32)
    n = audio.shape[1]
    starts = range(0, n - StftEffect.N + 1, StftEffect.HOP)
    total = np.zeros(StftEffect.N // 2 + 1)
    count = 0
    for i in starts:
        spectrum = np.fft.rfft(audio[:, i:i + StftEffect.N] * window, axis=1)
        mixed = 0.5 * (spectrum[0] + spectrum[1])
        total += mixed.real ** 2 + mixed.imag ** 2
        count += 1
    return total / max(1, count)


# ------------------------------------------------------------------------------------------- echo time
ECHO_SECONDS = 4.0         # how long to listen for the clap and the echo after it
CLAP_OVER_NOISE_DB = 35.0  # the clap must stand this far above the room's noise to measure how the echo dies away
MIN_ECHO, MAX_ECHO = 0.15, 2.0


@dataclass
class EchoResult:
    status: str            # "ok", "no_clap", "silent" or "unclear"
    reverb_time: float     # seconds for the echo to fall by 60 dB (only meant to be used for "ok")
    message: str

    @property
    def usable(self) -> bool:
        return self.status == "ok"


def analyse_echo(audio: np.ndarray, sample_rate: int) -> EchoResult:
    """``audio`` is (2, n) from the microphone while the person claps once, sharply, and then keeps quiet. The echo's
    decay is read from the fall in level after the clap (backward integration, fitted between 5 and 20 dB below the
    clap, then scaled to 60 dB)."""
    audio = np.asarray(audio, dtype=np.float64)
    if audio.shape[1] < sample_rate * 2 or float(np.max(np.abs(audio))) < 10 ** (NOTHING_DB / 20):
        return EchoResult("silent", 0.0, "I heard nothing at all. Is the right microphone selected and not muted?")
    mono = audio.mean(axis=0)
    # Rumble would hide the end of the decay: take out everything below 150 Hz (in the frequency domain, so no extra package).
    spectrum = np.fft.rfft(mono)
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sample_rate)
    spectrum *= np.clip((freqs - 100.0) / 100.0, 0.0, 1.0)  # silent below 100 Hz, fully there from 200 Hz
    mono = np.fft.irfft(spectrum, n=len(mono))
    block = max(1, int(sample_rate * 0.003))
    blocks = len(mono) // block
    energy = (mono[: blocks * block].reshape(blocks, block) ** 2).mean(axis=1) + 1e-18
    db = 10 * np.log10(energy)
    peak = int(np.argmax(db))
    noise_power = float(np.median(energy))               # more than half of the recording is the room alone
    if db[peak] - 10 * np.log10(noise_power) < CLAP_OVER_NOISE_DB or peak > blocks - int(0.4 * sample_rate / block):
        return EchoResult("no_clap", 0.0,
                          "I did not hear a clear clap. Clap once, sharply and close to the microphone, then stay quiet. "
                          "In a loud room a louder clap or a closer microphone helps.")
    tail = energy[peak:]
    smooth = np.convolve(tail, np.ones(3) / 3, mode="same")
    below = np.nonzero(smooth < noise_power * 4.0)[0]    # where the echo has sunk into the room's own noise
    end = int(below[0]) if len(below) else len(tail)
    useful = np.maximum(tail[:end] - noise_power, 1e-18)
    if len(useful) < 8:
        return EchoResult("unclear", 0.0, "The echo died away too quickly to measure: your room may have very little echo. "
                                          "Leave the Echo Reducer on a short time such as 0.3 s.")
    edc = np.cumsum(useful[::-1])[::-1]                  # backward (Schroeder) integration
    edc_db = 10 * np.log10(edc / edc[0])
    top = np.nonzero(edc_db <= -5)[0]
    bottom = np.nonzero(edc_db <= -20)[0]
    if len(top) == 0 or len(bottom) == 0 or bottom[0] - top[0] < 3:
        return EchoResult("unclear", 0.0, "The echo died away too quickly to measure: your room may have very little echo. "
                                          "Leave the Echo Reducer on a short time such as 0.3 s.")
    t = np.arange(top[0], bottom[0] + 1) * block / sample_rate
    slope, _ = np.polyfit(t, edc_db[top[0]:bottom[0] + 1], 1)
    if slope >= -1.0:
        return EchoResult("unclear", 0.0, "I could not tell how the echo dies away. Please try again, with no other sounds.")
    rt60 = float(np.clip(-60.0 / slope, MIN_ECHO, MAX_ECHO))
    return EchoResult("ok", round(rt60, 2),
                      f"Your room's echo takes about {rt60:.1f} seconds to die away.")


# ------------------------------------------------------------------------------------------- voice level
VOICE_SECONDS = 6.0        # how long to listen while the person talks
VOICE_TARGET_DB = -20.0    # the average level of speech (the louder pieces) that suits a stream or a recording
VOICE_PEAK_DB = -3.0       # the loudest moments should stay below this, or there is no room left before clipping
VOICE_RAISE_DB = 3.0       # a voice this far under the target is called quiet
VOICE_LOWER_DB = 1.5       # ...and this far over it (or too close to clipping) is called loud
VOICE_BLOCK_MS = 50
VOICE_SPREAD_DB = 8.0      # talking must rise this far above the room's pauses, or it was not really measured


@dataclass
class VoiceResult:
    status: str            # "ok", "too_quiet", "too_loud", "no_speech" or "silent"
    level_db: float        # the average level of the talking, in dB below full scale
    peak_db: float         # the loudest moment
    change_db: float       # how much to raise (positive) or lower (negative) the microphone's level
    message: str

    @property
    def usable(self) -> bool:
        return self.status in ("too_quiet", "too_loud")


def analyse_voice(audio: np.ndarray, sample_rate: int) -> VoiceResult:
    """``audio`` is (2, n) from the microphone, before any effect, while the person talks normally for a few seconds."""
    audio = np.asarray(audio, dtype=np.float32)[:, int(SKIP_SECONDS * sample_rate):]
    if audio.shape[1] < 2 * sample_rate:
        return VoiceResult("silent", NOTHING_DB, NOTHING_DB, 0.0, "That was too short to measure. Please try again.")
    peak = float(np.max(np.abs(audio)))
    if peak < 10 ** (NOTHING_DB / 20):
        return VoiceResult("silent", NOTHING_DB, NOTHING_DB, 0.0,
                           "I heard nothing at all. Is the right microphone selected and not muted? "
                           "(Check the Mic channel's input and the mute buttons.)")
    # The loudest moments are judged the way speech has them (the loud end of every 10 ms piece), so that one click, cough
    # or knock does not decide how much room the voice has.
    peak_db = float(np.percentile(_block_peaks_db(audio, sample_rate), 99))
    size = max(1, int(sample_rate * VOICE_BLOCK_MS / 1000))
    blocks = audio.shape[1] // size
    power = np.mean(audio[:, : blocks * size].reshape(2, blocks, size) ** 2, axis=(0, 2))
    block_db = 10.0 * np.log10(np.maximum(power, 1e-12))
    loud_end = float(np.percentile(block_db, 95))
    spoken = block_db[block_db > loud_end - 15.0]  # the pieces where you were really talking, not the pauses
    if float(np.percentile(block_db, 95) - np.percentile(block_db, 10)) < VOICE_SPREAD_DB or len(spoken) < 10:
        return VoiceResult("no_speech", loud_end, float(peak_db), 0.0,
                           "I could not tell your voice from the room. Please try again, talking in your normal voice the "
                           "whole time, as if you were on a call.")
    level = float(10.0 * np.log10(np.mean(10 ** (spoken / 10.0))))
    headroom = VOICE_PEAK_DB - float(peak_db)  # how much louder it could get before the peaks leave no room
    change = min(VOICE_TARGET_DB - level, headroom)
    facts = f"Your voice averages about {level:.0f} dB, with its loudest moments near {peak_db:.0f} dB."
    if change >= VOICE_RAISE_DB:
        return VoiceResult("too_quiet", level, float(peak_db), round(change, 1),
                           f"{facts} That is on the quiet side: for streaming and recording aim for about "
                           f"{VOICE_TARGET_DB:.0f} dB. Raise the microphone's level by about {change:.0f} dB (in your sound "
                           "settings, with the knob on your interface, or let Sluice add it). A voice this quiet also leaves "
                           "the Compressor with nothing to do.")
    if change <= -VOICE_LOWER_DB:
        return VoiceResult("too_loud", level, float(peak_db), round(change, 1),
                           f"{facts} That is loud enough to risk clipping on your loudest words. Lower the microphone's "
                           f"level by about {-change:.0f} dB.")
    return VoiceResult("ok", level, float(peak_db), 0.0, f"{facts} That is a good level: no change needed.")
