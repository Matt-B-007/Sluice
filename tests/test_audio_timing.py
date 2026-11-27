"""0.12.6: whose dropout it was is decided by the slowest of the last few blocks, and the time a block waits for Python's lock
(held by the window) is measured apart from its own work, logged with dropouts and shown in the bug report."""
import logging
import sys

import pytest

from sluice import audio_io, efficiency
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer


class TimedIO(audio_io.NullIO):
    """NullIO that reports a load, a lock wait and dropouts like the Rust client."""

    def __init__(self):
        super().__init__(realtime=False)
        self.load, self.wait = (0.0, 0.0), None

    def take_load(self):
        return self.load

    def take_wait(self):
        return self.wait


def make_engine(io):
    eng = Engine(Mixer.demo(), MockSystem(), io, NullLinker())
    eng.start()
    return eng


def test_the_lock_wait_is_kept_for_the_session_and_the_worst_block():
    io = TimedIO()
    eng = make_engine(io)
    try:
        assert eng.wait_stats() is None  # nothing measured yet
        io.load, io.wait = (0.05, 0.3), (0.01, 0.05, 0.02)
        eng.tick(1000.0)
        io.load, io.wait = (0.06, 2.9), (0.02, 2.6, 2.5)  # a block took 290%: 250% of it was waiting for the window
        eng.tick(1001.0)
        average, worst, in_worst = eng.wait_stats()
        assert average == pytest.approx(0.015) and worst == pytest.approx(2.6) and in_worst == pytest.approx(2.5)
    finally:
        eng.shutdown()


def test_dropouts_are_logged_with_the_wait(caplog):
    io = TimedIO()
    eng = make_engine(io)
    try:
        io.load, io.wait = (0.05, 2.0), (0.02, 1.8, 1.8)
        eng.tick(1000.0)
        io.xruns = 1
        with caplog.at_level(logging.WARNING, logger="sluice.engine"):
            eng.tick(1010.0)
            eng.tick(1030.0)
        assert "waiting for the window" in caplog.text
    finally:
        eng.shutdown()


def test_the_python_client_and_old_rust_engines_say_the_wait_is_not_measured():
    assert audio_io.NullIO(realtime=False).take_wait() is None
    assert "not measured" in efficiency.wait_line(None)
    text = efficiency.wait_line([0.02, 1.8, 1.75])
    assert "average 2.0%" in text and "worst 180.0%" in text and "175.0%" in text


def test_a_slow_block_a_moment_before_the_dropout_is_ours():
    """0.12.6: your report: blocks took 152-292% of their time, yet "0 of those while Sluice itself was running late", because
    only the last block was looked at, and a quick one had run by the time the dropout was reported."""
    io = audio_io.JackIO.__new__(audio_io.JackIO)
    io.blocksize, io.sample_rate, io.xruns, io.xruns_ours = 1024, 48000, 0, 0
    io._init_timing()
    now = audio_io.time.perf_counter()
    io._recent = [(now - 3 * io._period, 2.9 * io._period), (now - 2 * io._period, 0.02 * io._period)]
    io._last_busy, io._in_block = 0.02 * io._period, False
    io._on_xrun(0.0)
    assert io.xruns_ours == 1
    io._recent = [(now - 50 * io._period, 2.9 * io._period)]  # long ago: not this dropout's cause
    io._on_xrun(0.0)
    assert io.xruns_ours == 1 and io.xruns == 2


def test_audio_blocks_get_the_lock_sooner():
    before = sys.getswitchinterval()
    try:
        audio_io._share_the_lock_sooner()
        assert sys.getswitchinterval() == pytest.approx(0.001)
    finally:
        sys.setswitchinterval(before)


def test_the_rust_engine_measures_the_wait():
    sluice_dsp = pytest.importorskip("sluice_dsp")
    assert sluice_dsp.VERSION == "0.11.1" and hasattr(sluice_dsp.JackEngine, "take_wait")


# ----------------------------------------------------------------------------- 0.12.6: start-up is measured
def test_startup_steps_are_measured_from_the_process_start(monkeypatch):
    monkeypatch.setattr(efficiency, "STARTUP", {})
    age = efficiency.process_age()
    assert age is not None and 0.0 <= age < 24 * 3600
    efficiency.startup_mark("Python and imports")
    efficiency.startup_mark("window shown")
    efficiency.startup_mark("window shown")  # only the first time counts
    assert list(efficiency.STARTUP) == ["Python and imports", "window shown"]
    line = efficiency.startup_line({"Python and imports": 0.6, "audio connected": 0.65, "window shown": 1.4})
    assert line == "Python and imports 0.60 (+0.60) · audio connected 0.65 (+0.05) · window shown 1.40 (+0.75)"


def test_the_bug_report_shows_start_up():
    text = efficiency.format_section({"startup": {"Python and imports": 0.6, "window shown": 1.4}, "rss_mb": 100}, "now")
    assert "Start-up (seconds after the process started" in text and "window shown 1.40" in text
