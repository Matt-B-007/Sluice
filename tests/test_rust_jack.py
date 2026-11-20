# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rust JACK client against a real (dummy-driver) JACK server. Skipped when jackd or libjack is not around."""
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

rust = pytest.importorskip("sluice_dsp")
if not hasattr(rust, "JackEngine"):
    pytest.skip("older sluice_dsp build", allow_module_level=True)
try:
    import jack  # noqa: F401
except (ImportError, OSError):  # no JACK library on this machine (OSError), or no module
    pytest.skip("libjack is not available", allow_module_level=True)
if shutil.which("jackd") is None:
    pytest.skip("jackd is not installed", allow_module_level=True)

if os.environ.get("SLUICE_NO_RUST") or os.environ.get("SLUICE_NO_RUST_IO"):
    pytest.skip("Rust switched off", allow_module_level=True)

from sluice.audio_io import RustJackIO, make_jack_io  # noqa: E402


PROBE = "import jack; jack.Client('probe', no_start_server=True).close()"
started = []  # every io a test made, so the fixture can stop it whatever happens


def make_io(*args, **kwargs):
    io = make_jack_io(*args, **kwargs)
    started.append(io)
    return io


@pytest.fixture
def server(monkeypatch):
    name = f"sluicetest{os.getpid()}"
    monkeypatch.setenv("JACK_DEFAULT_SERVER", name)
    proc = subprocess.Popen(["jackd", "-n", name, "-r", "-d", "dummy", "-r", "48000", "-p", "512"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline:
        # Ask from a separate process: libjack can crash outright when it meets a server that is still starting,
        # and that must not take the whole test run down with it.
        probe = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, timeout=30)
        if probe.returncode == 0:
            break
        time.sleep(0.3)
    else:
        proc.kill()
        pytest.skip("could not start a dummy JACK server here")
    started.clear()
    yield name
    for engine in started:  # a test that failed half way must not leave a client running when the server disappears
        try:
            engine.stop()
        except Exception:
            pass
    time.sleep(0.2)
    proc.terminate()
    proc.wait(timeout=10)


def wait_for(condition, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        time.sleep(0.05)


class FakeGraph:
    live = False

    def __init__(self, fn):
        self.process = fn


def test_blocks_flow_through_and_ports_follow_the_mixer(server):
    io = make_io()
    assert isinstance(io, RustJackIO) and io.sample_rate == 48000 and io.blocksize == 512
    io.sync_ports(["mic"], ["main"])
    # like the real graph: a channel may be missing for a block while ports change
    graph = FakeGraph(lambda inputs, frames: {"main": inputs.get("mic", np.zeros((2, frames), np.float32)) * 0.5})
    io.start(graph)
    assert graph.live
    c = jack.Client("tester", no_start_server=True)
    out_port, in_port = c.outports.register("o"), c.inports.register("i")
    heard = []

    @c.set_process_callback
    def process(frames):
        out_port.get_array()[:] = 0.8
        heard.append(float(np.abs(in_port.get_array()).max()))

    c.activate()
    try:
        c.connect("tester:o", "sluice:in_mic_L")
        c.connect("sluice:out_main_L", "tester:i")
        wait_for(lambda: heard and max(heard) > 0.39)  # connecting takes a moment on a busy machine
        assert max(heard) == pytest.approx(0.4, abs=1e-6)
        io.sync_ports(["mic", "chat"], ["main", "alt"])
        names = {p.name for p in c.get_ports("sluice:")}
        assert {"sluice:in_chat_L", "sluice:out_alt_R"} <= names
        io.sync_ports(["mic"], ["main"])
        assert {p.name for p in c.get_ports("sluice:")} == {"sluice:in_mic_L", "sluice:in_mic_R", "sluice:out_main_L", "sluice:out_main_R"}
        average, worst = io.take_load()
        assert 0 <= average <= worst < 1
        assert io.xruns >= 0 and io.error == ""
    finally:
        c.deactivate()
        c.close()
        io.stop()
    assert not graph.live


def test_an_exception_in_the_graph_gives_silence_and_an_error_not_a_crash(server):
    io = make_io()
    io.sync_ports(["mic"], ["main"])

    def broken(inputs, frames):
        raise ValueError("boom")

    io.start(FakeGraph(broken))
    wait_for(lambda: "ValueError: boom" in io.error)
    assert "ValueError: boom" in io.error
    io.error = ""
    assert io.error == ""
    io.stop()


def test_a_second_client_with_the_same_name_is_refused(server):
    first = make_io()
    try:
        with pytest.raises(Exception):  # PipeWire says "name not unique"; a real JACK server only says "failure"
            make_jack_io()
    finally:
        first.stop()


def test_python_jack_is_used_when_rust_is_switched_off(server, monkeypatch):
    from sluice.audio_io import JackIO

    monkeypatch.setenv("SLUICE_NO_RUST_IO", "1")
    io = make_io()
    try:
        assert isinstance(io, JackIO)
    finally:
        io.stop()


def test_channels_that_stay_are_never_missing_while_others_come_and_go(server):
    """Adding or removing a channel must not make the channels that stay vanish for a block (that was a block of silence)."""
    from sluice import spectral

    if spectral.rust_is_older(rust.VERSION, "0.10.1"):
        pytest.skip(f"the installed engine ({rust.VERSION}) is older than the fix (0.10.1): run ./install.sh again to rebuild it")
    io = make_io()
    missing = []

    def graph_fn(inputs, frames):
        if "mic" not in inputs or "main" not in ("main",):
            missing.append(sorted(inputs))
        return {"main": np.zeros((2, frames), np.float32)}

    io.sync_ports(["mic"], ["main"])
    io.start(FakeGraph(graph_fn))
    for i in range(25):
        io.sync_ports(["mic", f"extra{i}"], ["main"])
        time.sleep(0.01)
    io.sync_ports(["mic"], ["main"])
    time.sleep(0.2)
    io.stop()
    assert missing == []
