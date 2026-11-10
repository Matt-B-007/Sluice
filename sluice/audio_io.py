# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio data plane: how blocks of samples get in and out of the DSP graph.

``JackIO`` registers ports with the PipeWire JACK layer (pipewire-jack). ``NullIO``
makes up its own input and discards the output, which powers ``--demo`` mode and the tests.

Port names are shared by both so the engine can compute the links it wants either way.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import zlib
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

log = logging.getLogger("sluice.audio")

CLIENT = "sluice"
SLOW_BLOCK = 0.7  # a block that used more than this share of its time counts as Sluice running late


def in_port_names(channel_id: str) -> tuple:
    return (f"{CLIENT}:in_{channel_id}_L", f"{CLIENT}:in_{channel_id}_R")


def out_port_names(mix_id: str) -> tuple:
    return (f"{CLIENT}:out_{mix_id}_L", f"{CLIENT}:out_{mix_id}_R")


def _short(name: str) -> str:
    return name.split(":", 1)[1]


class AudioIO(ABC):
    label = "abstract"
    sample_rate = 48000
    blocksize = 512
    xruns = 0
    xruns_ours = 0  # dropouts that came while one of Sluice's own blocks was running long (the rest came from elsewhere)
    error = ""

    def take_load(self) -> tuple:
        """(average, worst) share of a block's time Sluice's own audio work used since the last call, 0..1+.
        (0, 0) when the backend does not measure it."""
        return 0.0, 0.0

    @abstractmethod
    def sync_ports(self, channel_ids: list, mix_ids: list) -> None:
        """Make sure there is one stereo input per channel and one stereo output per mix."""

    @abstractmethod
    def start(self, graph) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


# ===================================================================== synthetic
class NullIO(AudioIO):
    """Generates test signals and drops the output. ``realtime=False`` lets tests step blocks by hand."""

    label = "Demo mode (no audio is touched)"

    def __init__(self, sample_rate: int = 48000, blocksize: int = 512, realtime: bool = True) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.realtime = realtime
        self.channel_ids: list = []
        self.mix_ids: list = []
        self.fixed_inputs: dict = {}  # tests: channel id -> (2, n) array (cycled) overriding the synth
        self.streamed_inputs: dict = {}  # tests: channel id -> (2, n) recording played through block after block, then repeated
        self._stream_at: dict = {}
        self.last_outputs: dict = {}
        self.blocks = 0
        self._graph = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._position: dict = {}

    def sync_ports(self, channel_ids: list, mix_ids: list) -> None:
        self.channel_ids = list(channel_ids)
        self.mix_ids = list(mix_ids)

    def start(self, graph) -> None:
        self._graph = graph
        graph.live = True
        if self.realtime:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="nullio", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._graph is not None:
            self._graph.live = False

    def _synth(self, channel_id: str, frames: int) -> np.ndarray:
        """Smoothly varying fake signal, different per channel."""
        start = self._position.get(channel_id, 0)
        self._position[channel_id] = start + frames
        t = (start + np.arange(frames)) / self.sample_rate
        seed = zlib.crc32(channel_id.encode())
        freq = 110.0 + (seed % 400)
        phase = (seed % 628) / 100.0
        envelope = 0.05 + 0.30 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.35 * t + phase))
        tone = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * 2 * freq * t)
        mono = (envelope * tone).astype(np.float32)
        return np.stack((mono, mono * 0.95))

    def process_once(self, frames: Optional[int] = None) -> dict:
        frames = frames or self.blocksize
        inputs = {}
        for cid in self.channel_ids:
            fixed = self.fixed_inputs.get(cid)
            streamed = self.streamed_inputs.get(cid)
            if streamed is not None:
                at = self._stream_at.get(cid, 0)
                index = (at + np.arange(frames)) % streamed.shape[1]
                inputs[cid] = streamed[:, index]
                self._stream_at[cid] = (at + frames) % streamed.shape[1]
            elif fixed is not None:
                reps = -(-frames // fixed.shape[1])
                inputs[cid] = np.tile(fixed, (1, reps))[:, :frames]
            else:
                inputs[cid] = self._synth(cid, frames)
        self.last_outputs = self._graph.process(inputs, frames)
        self.blocks += 1
        return self.last_outputs

    def _run(self) -> None:
        period = self.blocksize / self.sample_rate
        next_time = time.monotonic()
        while not self._stop.is_set():
            self.process_once()
            next_time += period
            delay = next_time - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_time = time.monotonic()


# ========================================================================== JACK
class JackIO(AudioIO):
    """Real audio through PipeWire's JACK layer. Needs ``pipewire-jack`` and the JACK-Client package."""

    label = "PipeWire (JACK)"

    def __init__(self, client_name: str = CLIENT) -> None:
        # Ask PipeWire not to auto-connect our ports; we manage every link ourselves.
        os.environ.setdefault("PIPEWIRE_PROPS", "{ node.autoconnect=false }")
        # Ask for ~10 ms blocks: small enough to feel live, large enough for Python to keep up.
        os.environ.setdefault("PIPEWIRE_LATENCY", "512/48000")
        import jack  # imported lazily: it needs libjack at import time

        self._jack = jack
        self.client = jack.Client(client_name, no_start_server=True, use_exact_name=True)
        self.sample_rate = int(self.client.samplerate)
        self.blocksize = int(self.client.blocksize)
        log.info("JACK client '%s' connected: %d Hz, %d frames per block", client_name, self.sample_rate, self.blocksize)
        self.xruns = 0
        self.xruns_ours = 0
        self.error = ""
        self._init_timing()
        self._in: dict = {}
        self._out: dict = {}
        self._graph = None
        self.client.set_process_callback(self._process)
        self.client.set_xrun_callback(self._on_xrun)
        self.client.set_shutdown_callback(self._on_shutdown)

    def sync_ports(self, channel_ids: list, mix_ids: list) -> None:
        new_in = {}
        for cid in channel_ids:
            new_in[cid] = self._in.get(cid) or (
                self.client.inports.register(_short(in_port_names(cid)[0])),
                self.client.inports.register(_short(in_port_names(cid)[1])),
            )
        new_out = {}
        for mid in mix_ids:
            new_out[mid] = self._out.get(mid) or (
                self.client.outports.register(_short(out_port_names(mid)[0])),
                self.client.outports.register(_short(out_port_names(mid)[1])),
            )
        old = [p for cid, pair in self._in.items() if cid not in new_in for p in pair]
        old += [p for mid, pair in self._out.items() if mid not in new_out for p in pair]
        self._in, self._out = new_in, new_out  # swap first so the callback never sees dead ports
        if old and self._graph is not None and getattr(self._graph, "live", False):
            # a block that started before the swap may still hold the old ports: let it finish
            time.sleep(3 * self.blocksize / self.sample_rate)
        for port in old:
            try:
                port.unregister()
            except Exception:
                pass

    def start(self, graph) -> None:
        self._graph = graph
        graph.live = True
        self.client.activate()

    def stop(self) -> None:
        try:
            self.client.deactivate()
        except Exception as exc:
            log.warning("JACK deactivate failed: %s", exc)
        if self._graph is not None:
            self._graph.live = False
        try:
            self.client.close()
        except Exception as exc:
            log.warning("JACK close failed: %s", exc)

    def _init_timing(self) -> None:
        self._period = self.blocksize / self.sample_rate  # seconds one block lasts
        self._busy_sum = 0.0   # seconds spent in our own audio work since take_load() was last called
        self._busy_peak = 0.0
        self._blocks = 0
        self._last_busy = 0.0
        self._block_start = 0.0
        self._in_block = False

    def take_load(self) -> tuple:
        blocks, total, peak = self._blocks, self._busy_sum, self._busy_peak
        self._blocks, self._busy_sum, self._busy_peak = 0, 0.0, 0.0
        if not blocks:
            return 0.0, 0.0
        return total / blocks / self._period, peak / self._period

    def _process(self, frames: int) -> None:
        graph = self._graph
        if graph is None:
            return
        start = time.perf_counter()  # two clock reads per block: how long our own work takes, to tell our dropouts from others
        self._block_start, self._in_block = start, True
        try:
            inputs = {cid: np.stack((left.get_array(), right.get_array())) for cid, (left, right) in self._in.items()}
            outputs = graph.process(inputs, frames)
            for mid, (left, right) in self._out.items():
                block = outputs.get(mid)
                if block is None:
                    left.get_array()[:] = 0.0
                    right.get_array()[:] = 0.0
                else:
                    left.get_array()[:] = block[0]
                    right.get_array()[:] = block[1]
        except Exception as exc:  # never let an exception escape into the audio thread
            self.error = f"{type(exc).__name__}: {exc}"
            for left, right in list(self._out.values()):
                try:
                    left.get_array()[:] = 0.0
                    right.get_array()[:] = 0.0
                except Exception:
                    pass
        busy = time.perf_counter() - start
        self._in_block = False
        self._last_busy = busy
        self._busy_sum += busy
        self._blocks += 1
        if busy > self._busy_peak:
            self._busy_peak = busy

    def _on_xrun(self, _delay: float) -> None:
        self.xruns += 1
        # Ours if the block that was running (or had just run) used most of its time: Sluice was the slow one. If it was
        # quick, the server was waiting for somebody else.
        busy = time.perf_counter() - self._block_start if self._in_block else self._last_busy
        if busy > SLOW_BLOCK * self._period:
            self.xruns_ours += 1

    def _on_shutdown(self, _status, reason: str) -> None:
        self.error = f"Audio server shut down: {reason}"
