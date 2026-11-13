# SPDX-License-Identifier: GPL-3.0-or-later
"""The real-time mixing graph.

``Graph.process`` is called once per audio block by an ``AudioIO`` backend. It is
plain numpy + pedalboard: given one stereo buffer per channel it runs each channel's
effect chain, mixes every channel into every mix (with per-route gain), applies the
mix master gain and limiter, and returns one stereo buffer per mix.

Threading: all changes to live state (plugin parameters, effect chains, gains) are
sent through ``submit``. While audio is running they are queued and applied at the
start of the next block, on the audio thread, so plugins are never touched from two
threads at once.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Optional

import numpy as np

from .effects import Chain

LIMITER_CEILING_DB = -1.0
SILENCE_TAIL_SECONDS = 6.0  # after this long without input, a channel's effect chain is skipped (reverb tails are shorter)


def _pedalboard():
    try:
        import pedalboard
    except ImportError:
        return None
    return pedalboard


class PeakLimiter:
    """Brickwall peak limiter: instant attack, exponential release, vectorised with numpy.

    The gain is chosen per sample so the output never exceeds ``ceiling_db``; after an
    overload it recovers smoothly over about ``release_ms``. (pedalboard's own Limiter
    does not hold its threshold, so sluice uses this one.)
    """

    CHUNK = 1024  # keeps the decay powers below numerically unstable sizes

    def __init__(self, sample_rate: int, ceiling_db: float = LIMITER_CEILING_DB, release_ms: float = 100.0) -> None:
        self.ceiling = 10.0 ** (ceiling_db / 20.0)
        self.decay = float(np.exp(-1.0 / (sample_rate * release_ms / 1000.0)))
        self._reduction = 1.0  # gain reduction (a ratio >= 1) at the end of the previous block
        self._cached = self._powers(self.CHUNK)

    def _powers(self, n: int) -> tuple:
        k = np.arange(n, dtype=np.float64)
        return self.decay ** k, self.decay ** (-k), self.decay ** (k + 1)

    def process(self, audio: np.ndarray) -> np.ndarray:
        out = np.empty_like(audio)
        for start in range(0, audio.shape[1], self.CHUNK):
            part = audio[:, start:start + self.CHUNK]
            n = part.shape[1]
            decay_n, grow_n, decay_next = self._cached if n == self.CHUNK else self._powers(n)
            need = np.maximum(np.max(np.abs(part), axis=0) / self.ceiling, 1.0)
            held = decay_n * np.maximum.accumulate(need * grow_n)  # decayed running maximum
            reduction = np.maximum(np.maximum(self._reduction * decay_next, held), 1.0)
            self._reduction = float(reduction[-1])
            out[:, start:start + n] = part / reduction.astype(np.float32)
        return out


def _curve(previous: float, target: float, frames: int):
    """Gain for one block: a scalar if unchanged, else a linear ramp (avoids zipper noise)."""
    if previous == target:
        return target
    return np.linspace(previous, target, frames, dtype=np.float32)


class Capture:
    """A few seconds of one channel's input, copied on the audio thread into memory made beforehand."""

    def __init__(self, frames: int) -> None:
        self.buf = np.zeros((2, frames), dtype=np.float32)
        self.pos = 0

    @property
    def size(self) -> int:
        return self.buf.shape[1]

    @property
    def done(self) -> bool:
        return self.pos >= self.size


RECENT_DECAY = 0.9985  # per block (about 100 a second): the held peak falls roughly 2 dB a second


class ChannelDsp:
    def __init__(self, channel_id: str) -> None:
        self.id = channel_id
        self.board = None  # pedalboard.Pedalboard or None when the chain is empty
        self.gains: dict = {}  # mix id -> target linear gain
        self.applied: dict = {}  # mix id -> gain reached at the end of the last block
        self.solo_gain: Optional[float] = None  # None: no own output; else the gain of the "<channel> only" output
        self.solo_applied = 0.0
        self.peak = 0.0
        self.recent = 0.0  # the peak after the effects, falling slowly (about 2 dB a second): "is anything loud enough?"
        self.input_recent = 0.0  # the peak before the effects, falling slowly: how loud the microphone itself is
        self.asleep = False  # the chain was skipped for silence; it is woken when sound returns
        self.quiet_frames = 0  # how long the input has been digital silence (an idle app sends exact zeros)
        self.capture: Optional[Capture] = None  # set while "Measure my room" is listening


class MixDsp:
    def __init__(self, mix_id: str) -> None:
        self.id = mix_id
        self.gain = 1.0
        self.applied = 1.0
        self.primed = False  # until the first block, gain changes take effect immediately
        self.limiter = True
        self.limiter_dsp = None
        self.peak = 0.0


class Graph:
    def __init__(self, sample_rate: int, mix_ids: Iterable) -> None:
        self.sample_rate = int(sample_rate)
        self.live = False  # set by the audio backend while blocks are being processed
        self.channels: dict = {}
        self.mixes: dict = {mix_id: MixDsp(mix_id) for mix_id in mix_ids}
        self.errors: list = []
        self._queue: deque = deque()
        self._captures: dict = {}  # channel id -> the Capture "Measure my room" is filling
        self._pb = _pedalboard()

    # ------------------------------------------------------------ control side
    def submit(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` on the audio thread before the next block (immediately if audio is stopped)."""
        if self.live:
            self._queue.append(fn)
        else:
            fn()

    def set_channels(self, channel_ids: Iterable) -> None:
        ids = list(channel_ids)

        def apply() -> None:
            for cid in ids:
                self.channels.setdefault(cid, ChannelDsp(cid))
            for cid in [c for c in self.channels if c not in ids]:
                del self.channels[cid]

        self.submit(apply)

    # --------------------------------------------------------------- capturing
    def start_capture(self, channel_id: str, seconds: float) -> None:
        """Record the next ``seconds`` of a channel's input (before its effects) for ``take_capture``."""
        capture = Capture(max(1, int(seconds * self.sample_rate)))  # made here, not on the audio thread

        def apply() -> None:
            channel = self.channels.get(channel_id)
            if channel is not None:
                channel.capture = capture

        self._captures[channel_id] = capture
        self.submit(apply)

    def capture_progress(self, channel_id: str) -> float:
        """0.0 to 1.0; 0.0 as well when nothing is being captured."""
        capture = self._captures.get(channel_id)
        return 0.0 if capture is None else min(1.0, capture.pos / capture.size)

    def take_capture(self, channel_id: str) -> Optional[np.ndarray]:
        """The finished recording (and forget it), or None while it is still running or was never started."""
        capture = self._captures.get(channel_id)
        if capture is None or not capture.done:
            return None
        del self._captures[channel_id]

        def clear() -> None:
            channel = self.channels.get(channel_id)
            if channel is not None and channel.capture is capture:
                channel.capture = None

        self.submit(clear)
        return capture.buf

    def cancel_capture(self, channel_id: str) -> None:
        capture = self._captures.pop(channel_id, None)
        if capture is None:
            return

        def clear() -> None:
            channel = self.channels.get(channel_id)
            if channel is not None and channel.capture is capture:
                channel.capture = None

        self.submit(clear)

    def set_chain(self, channel_id: str, instances: Iterable) -> None:
        """Set a channel's effect chain from usable ``EffectInstance`` objects."""
        items = [item for inst in instances for item in inst.items]

        def apply() -> None:
            channel = self.channels.get(channel_id)
            if channel is None:
                return
            channel.board = Chain(self._pb, items) if (items and self._pb) else None

        self.submit(apply)

    def set_gain(self, channel_id: str, mix_id: str, linear: float) -> None:
        def apply() -> None:
            channel = self.channels.get(channel_id)
            if channel is not None:
                channel.gains[mix_id] = float(linear)

        self.submit(apply)

    def set_solo(self, channel_id: str, linear: Optional[float]) -> None:
        """Turn the channel's own output (after its effects, before any fader) on with this gain, or off with None."""

        def apply() -> None:
            channel = self.channels.get(channel_id)
            if channel is not None:
                if channel.solo_gain is None and linear is not None:
                    channel.solo_applied = float(linear)
                channel.solo_gain = None if linear is None else float(linear)

        self.submit(apply)

    def set_mix(self, mix_id: str, linear: float, limiter: bool) -> None:
        def apply() -> None:
            mix = self.mixes.get(mix_id)
            if mix is not None:
                mix.gain = float(linear)
                mix.limiter = bool(limiter)
                if not mix.primed:
                    mix.applied = mix.gain

        self.submit(apply)

    def take_peaks(self) -> dict:
        """Peak levels (linear) since the last call, keyed 'ch:<id>' and 'mix:<id>'."""
        peaks = {}
        for cid, channel in list(self.channels.items()):
            peaks[f"ch:{cid}"], channel.peak = channel.peak, 0.0
        for mid, mix in self.mixes.items():
            peaks[f"mix:{mid}"], mix.peak = mix.peak, 0.0
        return peaks

    def take_errors(self) -> list:
        errors, self.errors = self.errors, []
        return errors

    # -------------------------------------------------------------- audio side
    def _drain(self) -> None:
        for _ in range(len(self._queue)):
            try:
                self._queue.popleft()()
            except Exception as exc:  # a bad change must not stop the audio
                self.errors.append(f"{type(exc).__name__}: {exc}")

    def _run_board(self, board, audio: np.ndarray) -> np.ndarray:
        return np.asarray(board(audio, self.sample_rate, reset=False), dtype=np.float32)

    def process(self, inputs: dict, frames: int) -> dict:
        """inputs: channel id -> (2, frames) float32. Returns mix id -> (2, frames) float32."""
        self._drain()
        outputs = {mid: np.zeros((2, frames), dtype=np.float32) for mid in self.mixes}

        silence = None  # one shared block of zeros, made only if some channel needs it
        for cid, channel in self.channels.items():
            audio = inputs.get(cid)
            if audio is not None:
                audio = np.ascontiguousarray(audio, dtype=np.float32)
            if audio is None or not audio.any():
                channel.quiet_frames = min(channel.quiet_frames + frames, 1 << 30)
            else:
                channel.quiet_frames = 0
            cap = channel.capture
            if cap is not None and frames and not cap.done:  # "Measure my room": keep a copy of what comes in
                n = min(frames, cap.size - cap.pos)
                if audio is not None:
                    cap.buf[:, cap.pos:cap.pos + n] = audio[:, :n]
                cap.pos += n
            # An idle channel (no sound for longer than any effect's tail) costs nothing: no chain, no mixing.
            if channel.quiet_frames > 0 and frames and (
                channel.board is None or channel.quiet_frames > self.sample_rate * SILENCE_TAIL_SECONDS
            ):
                channel.asleep = channel.board is not None
                channel.recent *= RECENT_DECAY
                if silence is None or silence.shape[1] != frames:
                    silence = np.zeros((2, frames), dtype=np.float32)
                for mid in outputs:
                    channel.applied[mid] = channel.gains.get(mid, 0.0)
                if channel.solo_gain is not None:
                    outputs[f"solo_{cid}"] = silence.copy()
                    channel.solo_applied = channel.solo_gain
                continue
            if audio is None:
                audio = np.zeros((2, frames), dtype=np.float32)
            if frames:
                channel.input_recent = max(float(np.max(np.abs(audio))), channel.input_recent * RECENT_DECAY)
            if channel.board is not None:
                if channel.asleep:
                    channel.asleep = False
                    wake = getattr(channel.board, "wake", None)
                    if wake is not None:
                        wake()
                try:
                    audio = self._run_board(channel.board, audio)
                except Exception as exc:  # e.g. a VST3 plugin crashed: drop the chain, keep the audio running
                    channel.board = None
                    self.errors.append(f"Effect chain on '{cid}' failed and was disabled: {exc}")
            if frames:
                level = float(np.max(np.abs(audio)))
                if not np.isfinite(level):  # a misbehaving plugin produced NaN or infinity: replace it with silence
                    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
                    level = float(np.max(np.abs(audio)))
                channel.peak = max(channel.peak, level)
                channel.recent = max(level, channel.recent * RECENT_DECAY)
            for mid, out in outputs.items():
                target = channel.gains.get(mid, 0.0)
                previous = channel.applied.get(mid, target)
                if target == 0.0 and previous == 0.0:
                    continue
                out += audio * _curve(previous, target, frames)
                channel.applied[mid] = target
            if channel.solo_gain is not None:
                outputs[f"solo_{cid}"] = (audio * _curve(channel.solo_applied, channel.solo_gain, frames)).astype(np.float32)
                channel.solo_applied = channel.solo_gain

        for mid, mix in self.mixes.items():
            out = outputs[mid]
            out *= _curve(mix.applied, mix.gain, frames)
            mix.applied = mix.gain
            mix.primed = True
            if mix.limiter:
                out = self._limit(mix, out)
            if frames:
                mix.peak = max(mix.peak, float(np.max(np.abs(out))))
            outputs[mid] = out
        return outputs

    def _limit(self, mix: MixDsp, audio: np.ndarray) -> np.ndarray:
        if mix.limiter_dsp is None:
            mix.limiter_dsp = PeakLimiter(self.sample_rate)
        return np.clip(mix.limiter_dsp.process(audio), -1.0, 1.0)  # the clip is only a safety net
