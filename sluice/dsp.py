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

import logging
import threading
import os
from collections import deque
from typing import Callable, Iterable, Optional

import numpy as np

from .effects import Chain, JointStage, NativeRun, Stage, Tap, toolbox

log = logging.getLogger(__name__)

LIMITER_CEILING_DB = -1.0
SILENCE_TAIL_SECONDS = 6.0  # after this long without input, a channel's effect chain is skipped (reverb tails are shorter)


def _pedalboard():
    try:
        import pedalboard
    except ImportError:
        return None
    return pedalboard


class PythonPeakLimiter:
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
        return self.decay**k, self.decay ** (-k), self.decay ** (k + 1)

    def process(self, audio: np.ndarray) -> np.ndarray:
        out = np.empty_like(audio)
        for start in range(0, audio.shape[1], self.CHUNK):
            part = audio[:, start : start + self.CHUNK]
            n = part.shape[1]
            decay_n, grow_n, decay_next = self._cached if n == self.CHUNK else self._powers(n)
            need = np.maximum(np.max(np.abs(part), axis=0) / self.ceiling, 1.0)
            held = decay_n * np.maximum.accumulate(need * grow_n)  # decayed running maximum
            reduction = np.maximum(np.maximum(self._reduction * decay_next, held), 1.0)
            self._reduction = float(reduction[-1])
            out[:, start : start + n] = part / reduction.astype(np.float32)
        return out


# The mixing kernels in Rust, when sluice_dsp is installed (same results to float rounding; SLUICE_NO_RUST=1 or
# SLUICE_NO_RUST_MIX=1 keeps the numpy ones).
PeakLimiter = PythonPeakLimiter
_rust = None
if not os.environ.get("SLUICE_NO_RUST") and not os.environ.get("SLUICE_NO_RUST_MIX"):
    try:
        import sluice_dsp as _rust

        if not hasattr(_rust, "finish_mix"):  # an older build
            _rust = None
        else:
            PeakLimiter = _rust.PeakLimiter
    except Exception as exc:  # no Rust module, or one for another Python or CPU: the Python mixer is used (the report says which)
        log.debug("Rust mixer not used: %s", exc)
        _rust = None
MIX_BACKEND = "rust" if _rust is not None else "python"
# 0.13.1: the whole graph in Rust (sluice_dsp.NativeGraph, engine 0.12.0 and later), used by the JACK engine while every chain
# is native. SLUICE_NO_NATIVE_GRAPH=1 keeps every block in Python (to compare, or to rule it out when hunting a problem).
NATIVE_GRAPH = _rust is not None and hasattr(_rust, "NativeGraph") and not os.environ.get("SLUICE_NO_NATIVE_GRAPH")


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
        self.instances: list = []  # the EffectInstances the board was built from
        self.tap_target = None  # the EffectInstance the Effects window is looking at, or None
        self.tap: Optional[Tap] = None
        self.gains: dict = {}  # mix id -> target linear gain
        self.applied: dict = {}  # mix id -> gain reached at the end of the last block
        self.solo_gain: Optional[float] = None  # None: no own output; else the gain of the "<channel> only" output
        self.solo_applied = 0.0
        self.peak = 0.0
        self.recent = 0.0  # the peak after the effects, falling slowly (about 2 dB a second): "is anything loud enough?"
        self.input_recent = 0.0  # the peak before the effects, falling slowly: how loud the microphone itself is
        self.input_peak = 0.0  # 0.12.3: the peak before the effects since the meters last looked (a mic's meter, without the
        # reducers' delay)
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
        self.audio_thread_id: Optional[int] = (
            None  # the system id of the thread that runs ``process`` (the bug report's CPU split)
        )
        self.channels: dict = {}
        self.mixes: dict = {mix_id: MixDsp(mix_id) for mix_id in mix_ids}
        self.errors: list = []
        self._queue: deque = deque()
        self._captures: dict = {}  # channel id -> the Capture "Measure my room" is filling
        self.taps: dict = {}  # channel id -> the Tap the Effects window reads (only while it is open)
        self._pb = _pedalboard()
        # 0.13.1: the Rust graph and the audio engine that can run it (see attach_native)
        self.native = None
        self.native_host = None
        self.native_active = False
        self.native_reason = "not available"  # why the blocks are mixed in Python, for the bug report
        self._sync_after_block = False
        self._native_boards: dict = {}  # channel id -> (the board last given to the Rust graph, whether it was native)

    # ------------------------------------------------------------ control side
    def submit(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` on the audio thread before the next block (immediately if audio is stopped, or while the Rust graph mixes
        the blocks: Python's state is then not used by the audio thread, and the Rust graph gets the change at once)."""
        if self.live and not self.native_active:
            self._queue.append(fn)
        else:
            fn()
            if self.native is not None:
                self._sync_native()

    # ------------------------------------------------------------ the Rust graph
    def attach_native(self, host) -> bool:
        """0.13.1: let ``host`` (the Rust JACK engine: set_native, use_native) mix the blocks in Rust whenever every chain is
        native. Returns whether it can."""
        if not NATIVE_GRAPH or not hasattr(host, "use_native"):
            self.native_reason = "the Rust engine is too old or switched off"
            return False
        try:
            self.native = _rust.NativeGraph(self.sample_rate, list(self.mixes))
            host.set_native(self.native)
        except Exception as exc:  # an engine that cannot: Python mixes, as before
            log.warning("the Rust graph could not be used: %s", exc)
            self.native, self.native_reason = None, f"could not start ({exc})"
            return False
        self.native_host = host
        self._native_boards.clear()
        self._sync_native()
        return True

    def detach_native(self) -> None:
        if self.native_host is not None:
            try:
                self.native_host.use_native(False)
                self.native_host.set_native(None)
            except Exception as exc:
                log.debug("could not detach the Rust graph: %s", exc)
        self.native = self.native_host = None
        self.native_active = False

    def _native_items(self, channel: "ChannelDsp") -> Optional[list]:
        """The channel's chain as Rust effect objects for the Rust graph ([] for no chain); None when a part needs Python."""
        board = channel.board
        if board is None:
            return []
        parts = getattr(board, "_parts", None)
        if parts is None or getattr(board, "_tap", None) is not None:
            return None
        items = []
        for part in parts:
            if isinstance(part, NativeRun):
                items.append(part._run)
            elif isinstance(part, JointStage):
                items.append(part.ensure(self.sample_rate))
            elif isinstance(part, Stage):
                items.append(part.ensure(self.sample_rate))
            else:
                return None  # a pedalboard plugin (VST3 or one with no Rust twin)
        return items

    def _sync_native(self) -> None:
        """Give the Rust graph the settings Python keeps, then let it mix the blocks if every chain is native and nothing is
        being looked at or recorded (those need Python), or take the blocks back."""
        native = self.native
        if native is None:
            return
        reason = ""
        try:
            native.set_channels(list(self.channels))
            for cid, channel in list(self.channels.items()):
                native.set_channel(cid, dict(channel.gains), channel.solo_gain)
                known = self._native_boards.get(cid)
                if known is None or known[0] is not channel.board:
                    items = self._native_items(channel)
                    ok = items is not None
                    if ok:
                        try:
                            native.set_chain(cid, items)
                        except TypeError:
                            ok = False
                    self._native_boards[cid] = (channel.board, ok)
                    known = self._native_boards[cid]
                if channel.tap is not None:  # (its chain is built with the view's parts: not one to judge)
                    reason = reason or "the Effects window shows a live view"
                elif channel.capture is not None:
                    reason = reason or "Measure my room is listening"
                elif not known[1]:
                    reason = reason or f"'{cid}' has an effect that needs Python (a VST3 plugin, say)"
            for cid in [c for c in self._native_boards if c not in self.channels]:
                del self._native_boards[cid]
            for mid, mix in self.mixes.items():
                native.set_mix(mid, mix.gain, mix.limiter)
        except Exception as exc:  # never let the mirror stop the audio: Python mixes
            log.warning("the Rust graph could not follow a change: %s", exc)
            reason = f"it could not follow a change ({exc})"
        self.native_reason = reason
        self._switch_native(not reason)

    def _switch_native(self, on: bool) -> None:
        if on == self.native_active or self.native_host is None:
            return
        native = self.native
        if on:  # Python hands over where every channel and mix is, so nothing jumps
            for cid, channel in list(self.channels.items()):
                native.put_channel_state(
                    cid,
                    (
                        dict(channel.applied),
                        channel.solo_applied,
                        channel.recent,
                        channel.input_recent,
                        int(channel.quiet_frames),
                        channel.asleep,
                    ),
                )
            for mid, mix in self.mixes.items():
                native.put_mix_state(mid, mix.applied, mix.primed)
            self.native_active = True
            self.native_host.use_native(True)
            log.info("the Rust graph mixes the blocks (no Python in the audio path)")
        else:  # the Rust graph stops first, then Python takes over from where it was
            self.native_host.use_native(False)
            self.native_active = False
            for cid, channel in list(self.channels.items()):
                state = native.channel_state(cid)
                if state is not None:
                    (
                        applied,
                        channel.solo_applied,
                        channel.recent,
                        channel.input_recent,
                        channel.quiet_frames,
                        channel.asleep,
                    ) = state
                    channel.applied = dict(applied)
            for mid, mix in self.mixes.items():
                state = native.mix_state(mid)
                if state is not None:
                    mix.applied, mix.primed = state
            log.info("Python mixes the blocks: %s", self.native_reason)

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

    def _build_board(self, channel: "ChannelDsp") -> None:
        """(Audio thread.) The channel's chain from its instances; the effect being looked at gets parts of its own."""
        items, span = [], None
        for instance in channel.instances:
            start = len(items)
            items.extend(instance.items)
            if instance is channel.tap_target and instance.items:
                span = (start, len(items))
        if not items or not self._pb:
            channel.board = None
            return
        tap = (span[0], span[1], channel.tap) if span and channel.tap is not None else None
        channel.board = Chain(toolbox(self._pb), items, tap=tap)

    def set_chain(self, channel_id: str, instances: Iterable) -> None:
        """Set a channel's effect chain from usable ``EffectInstance`` objects."""
        instances = list(instances)

        def apply() -> None:
            channel = self.channels.get(channel_id)
            if channel is None:
                return
            channel.instances = instances
            self._build_board(channel)

        self.submit(apply)

    def set_tap(self, channel_id: str, instance) -> Optional[Tap]:
        """Look at the sound going into and out of one effect of a channel (None stops looking). Returns the Tap to read from.

        Used by the live display of the Effects window while it is open; nothing is kept once it is closed."""
        tap = Tap(self.sample_rate) if instance is not None else None  # made here, not on the audio thread
        if tap is None:
            self.taps.pop(channel_id, None)
        else:
            self.taps[channel_id] = tap

        def apply() -> None:
            channel = self.channels.get(channel_id)
            if channel is None:
                return
            channel.tap_target, channel.tap = instance, tap
            self._build_board(channel)

        self.submit(apply)
        return tap

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
        """Peak levels (linear) since the last call, keyed 'ch:<id>' (after the effects), 'in:<id>' (before them) and 'mix:<id>'."""
        peaks = {}
        for cid, channel in list(self.channels.items()):
            peaks[f"ch:{cid}"], channel.peak = channel.peak, 0.0
            peaks[f"in:{cid}"], channel.input_peak = channel.input_peak, 0.0
        for mid, mix in self.mixes.items():
            peaks[f"mix:{mid}"], mix.peak = mix.peak, 0.0
        if self.native is not None:  # 0.13.1: what the Rust graph measured (both, around a switch)
            for key, value in self.native.take_peaks().items():
                peaks[key] = max(peaks.get(key, 0.0), value)
            if self.native_active:  # the slowly falling levels the window reads, from the graph that has them
                for cid, (recent, input_recent, asleep) in self.native.levels().items():
                    channel = self.channels.get(cid)
                    if channel is not None:
                        channel.recent, channel.input_recent, channel.asleep = recent, input_recent, asleep
        return peaks

    def take_errors(self) -> list:
        errors, self.errors = self.errors, []
        return errors

    # -------------------------------------------------------------- audio side
    def _drain(self) -> None:
        changed = bool(self._queue)
        for _ in range(len(self._queue)):
            try:
                self._queue.popleft()()
            except Exception as exc:  # a bad change must not stop the audio
                self.errors.append(f"{type(exc).__name__}: {exc}")
        if changed and self.native is not None:
            # the Rust graph hears of the change after this block, which Python still mixes: a hand-over before it would give
            # the Rust graph where things were a block ago (a fader's ramp twice, the meters a block behind)
            self._sync_after_block = True

    def _run_board(self, board, audio: np.ndarray) -> np.ndarray:
        return np.asarray(board(audio, self.sample_rate, reset=False), dtype=np.float32)

    def process(self, inputs: dict, frames: int) -> dict:
        """inputs: channel id -> (2, frames) float32. Returns mix id -> (2, frames) float32."""
        if self.audio_thread_id is None:
            self.audio_thread_id = (
                threading.get_native_id()
            )  # once: the thread the bug report's CPU split calls "the audio callback"
        self._drain()
        outputs = {mid: np.zeros((2, frames), dtype=np.float32) for mid in self.mixes}

        silence = None  # one shared block of zeros, made only if some channel needs it
        for cid, channel in list(self.channels.items()):
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
                    cap.buf[:, cap.pos : cap.pos + n] = audio[:, :n]
                cap.pos += n
            # An idle channel (no sound for longer than any effect's tail) costs nothing: no chain, no mixing.
            if (
                channel.quiet_frames > 0
                and frames
                and (channel.board is None or channel.quiet_frames > self.sample_rate * SILENCE_TAIL_SECONDS)
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
                before = float(np.max(np.abs(audio)))
                channel.input_recent = max(before, channel.input_recent * RECENT_DECAY)
                channel.input_peak = max(channel.input_peak, before)
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
                if _rust is not None:
                    audio = np.ascontiguousarray(audio, dtype=np.float32)
                    level, _, finite = _rust.block_stats(audio)
                    if not finite:  # a misbehaving plugin produced NaN or infinity: replace it with silence
                        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
                        level = float(np.max(np.abs(audio)))
                else:
                    level = float(np.max(np.abs(audio)))
                    if not np.isfinite(level):
                        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
                        level = float(np.max(np.abs(audio)))
                channel.peak = max(channel.peak, level)
                channel.recent = max(level, channel.recent * RECENT_DECAY)
            for mid, out in outputs.items():
                target = channel.gains.get(mid, 0.0)
                previous = channel.applied.get(mid, target)
                if target == 0.0 and previous == 0.0:
                    continue
                if _rust is not None and out.shape == audio.shape:
                    _rust.accumulate(out, np.ascontiguousarray(audio, dtype=np.float32), previous, target)
                else:
                    out += audio * _curve(previous, target, frames)
                channel.applied[mid] = target
            if channel.solo_gain is not None:
                outputs[f"solo_{cid}"] = (audio * _curve(channel.solo_applied, channel.solo_gain, frames)).astype(np.float32)
                channel.solo_applied = channel.solo_gain

        for mid, mix in self.mixes.items():
            out = outputs[mid]
            if _rust is not None and frames:
                if mix.limiter and mix.limiter_dsp is None:
                    mix.limiter_dsp = PeakLimiter(self.sample_rate)
                peak = _rust.finish_mix(out, mix.applied, mix.gain, mix.limiter_dsp if mix.limiter else None)
                mix.applied = mix.gain
                mix.primed = True
                mix.peak = max(mix.peak, peak)
                continue
            out *= _curve(mix.applied, mix.gain, frames)
            mix.applied = mix.gain
            mix.primed = True
            if mix.limiter:
                out = self._limit(mix, out)
            if frames:
                mix.peak = max(mix.peak, float(np.max(np.abs(out))))
            outputs[mid] = out
        if self._sync_after_block:
            self._sync_after_block = False
            self._sync_native()  # (on the audio thread, between blocks: the next one may be the Rust graph's)
        return outputs

    def _limit(self, mix: MixDsp, audio: np.ndarray) -> np.ndarray:
        if mix.limiter_dsp is None:
            mix.limiter_dsp = PeakLimiter(self.sample_rate)
        return np.clip(mix.limiter_dsp.process(audio), -1.0, 1.0)  # the clip is only a safety net
