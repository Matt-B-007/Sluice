# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rust JACK client against a real (dummy-driver) JACK server. Skipped when jackd or libjack is not around."""
import os
import shutil
import subprocess
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


@pytest.fixture
def server(monkeypatch):
    name = f"sluicetest{os.getpid()}"
    monkeypatch.setenv("JACK_DEFAULT_SERVER", name)
    proc = subprocess.Popen(["jackd", "-n", name, "-r", "-d", "dummy", "-r", "48000", "-p", "512"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            jack.Client("probe", no_start_server=True).close()
            break
        except jack.JackError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.skip("could not start a dummy JACK server here")
    yield name
    proc.terminate()
    proc.wait(timeout=10)


class FakeGraph:
    live = False

    def __init__(self, fn):
        self.process = fn


def test_blocks_flow_through_and_ports_follow_the_mixer(server):
    io = make_jack_io()
    assert isinstance(io, RustJackIO) and io.sample_rate == 48000 and io.blocksize == 512
    io.sync_ports(["mic"], ["main"])
    graph = FakeGraph(lambda inputs, frames: {"main": inputs["mic"] * 0.5})
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
        time.sleep(0.8)
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
    io = make_jack_io()
    io.sync_ports(["mic"], ["main"])

    def broken(inputs, frames):
        raise ValueError("boom")

    io.start(FakeGraph(broken))
    time.sleep(0.3)
    assert "ValueError: boom" in io.error
    io.error = ""
    assert io.error == ""
    io.stop()


def test_a_second_client_with_the_same_name_is_refused(server):
    first = make_jack_io()
    try:
        with pytest.raises(Exception):  # PipeWire says "name not unique"; a real JACK server only says "failure"
            make_jack_io()
    finally:
        first.stop()


def test_python_jack_is_used_when_rust_is_switched_off(server, monkeypatch):
    from sluice.audio_io import JackIO

    monkeypatch.setenv("SLUICE_NO_RUST_IO", "1")
    io = make_jack_io()
    try:
        assert isinstance(io, JackIO)
    finally:
        io.stop()
