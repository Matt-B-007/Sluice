"""Rough CPU and memory measurements for Sluice (developer tool, not part of the app).

    python tools/benchmark.py            # audio-callback cost + window cost (offscreen, demo backend)

The audio callback figure is how much of the time budget one buffer uses; the window figures are the
process's CPU use while idle and its resident memory.
"""
from __future__ import annotations

import os
import resource
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from sluice.model import Mixer  # noqa: E402


def rss_mb() -> float:
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6


def cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def make_engine():
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker

    system = MockSystem()
    system.add_demo_streams()
    engine = Engine(Mixer.default(), system, NullIO(realtime=False), NullLinker())
    engine.start()
    return engine


def audio_callback(frames: int = 256, rate: int = 48000, loops: int = 1500) -> None:
    engine = make_engine()
    graph = engine.graph
    ids = [c.id for c in engine.mixer.channels]
    rng = np.random.default_rng(1)
    busy = {cid: (rng.standard_normal((2, frames)) * 0.1).astype(np.float32) for cid in ids}
    for name, inputs in (("all channels playing", busy), ("everything silent (no input)", {})):
        for _ in range(int(7 * rate / frames) if not inputs else 50):  # (silent case: past the 6 s effect-tail window)
            graph.process(inputs, frames)
        start = time.perf_counter()
        for _ in range(loops):
            graph.process(inputs, frames)
        per = (time.perf_counter() - start) / loops
        budget = frames / rate
        print(f"audio callback, {name}: {per * 1e6:7.1f} us per buffer = {100 * per / budget:5.2f}% of the {budget * 1e3:.1f} ms budget")


def window(seconds: float = 6.0) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from sluice.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("sluice-benchmark")  # (also keeps the application object alive for the whole measurement)
    before = rss_mb()
    win = MainWindow(make_engine())
    win.show()
    for label, hidden in (("window visible", False), ("window hidden", True)):
        if hidden:
            win.hide()
        warm = QEventLoop()
        QTimer.singleShot(1000, warm.quit)
        warm.exec()
        c0, t0 = cpu_seconds(), time.perf_counter()
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()
        used = cpu_seconds() - c0
        print(f"{label}: {100 * used / (time.perf_counter() - t0):5.1f}% of one core (idle, offscreen)")
    print(f"memory: {before:.0f} MB before the window, {rss_mb():.0f} MB with it")
    win.shutdown()


if __name__ == "__main__":
    audio_callback()
    window()
