# SPDX-License-Identifier: GPL-3.0-or-later
"""0.13.1: the Rust audio path. While every chain is made of Sluice's own Rust effects, the JACK engine mixes the blocks in
``sluice_dsp.NativeGraph`` without Python; dsp.Graph stays the reference and takes the blocks back when Python is needed (a VST3
plugin, the Effects window's live view, Measure my room). These tests check the two give the same sound."""

from types import SimpleNamespace

import numpy as np
import pytest

sluice_dsp = pytest.importorskip("sluice_dsp")
if not hasattr(sluice_dsp, "NativeGraph"):
    pytest.skip("the Rust engine is older than 0.12.0", allow_module_level=True)
pytest.importorskip("pedalboard")

from sluice import dsp, voicefx  # noqa: E402
from sluice.effects import Stage, PlainStage  # noqa: E402
from sluice.spectral import EchoReducer, NoiseReducer  # noqa: E402

SR = 48000
# the Graph tests need the Rust graph switched on (the check script's second run, SLUICE_NO_RUST=1, has it off)
needs_graph = pytest.mark.skipif(not dsp.NATIVE_GRAPH, reason="the Rust graph is switched off (SLUICE_NO_RUST)")


def speech(seconds=2.0, seed=0):
    """Words (bursts of tone and noise) with pauses and a quiet room: something for a gate and a compressor to do."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    envelope = (np.sin(2 * np.pi * 1.7 * t) > 0.2) * (0.3 + 0.6 * np.abs(np.sin(2 * np.pi * 0.4 * t)))
    voice = envelope * (np.sin(2 * np.pi * 220 * t) + 0.4 * rng.standard_normal(n))
    room = 0.003 * rng.standard_normal(n)
    left = voice + room
    return np.stack([left, 0.8 * left + 0.002 * rng.standard_normal(n)]).astype(np.float32)


def blocks(audio, sizes=(512, 333, 1024, 128)):
    i, k = 0, 0
    while i < audio.shape[1]:
        n = sizes[k % len(sizes)]
        yield np.ascontiguousarray(audio[:, i : i + n])
        i, k = i + n, k + 1


# ---------------------------------------------------------------------------------------------- the voice effects
@pytest.mark.parametrize(
    "name, settings",
    [
        ("VoiceGate", {"threshold_db": -30.0, "depth_db": 30.0, "attack_ms": 1.0, "hold_ms": 80.0, "release_ms": 120.0}),
        ("LinkedCompressor", {"threshold_db": -24.0, "ratio": 4.0, "attack_ms": 5.0, "release_ms": 80.0, "makeup_db": 3.0}),
        ("CeilingLimiter", {"threshold_db": -6.0, "release_ms": 40.0}),
    ],
)
def test_the_rust_voice_effects_match_the_python_ones(name, settings):
    python = getattr(voicefx, f"Python{name}")(SR)
    rust = getattr(sluice_dsp, name)(SR)
    for key, value in settings.items():
        setattr(python, key, value)
        setattr(rust, key, value)
        assert getattr(rust, key) == value
    for block in blocks(speech()):
        a = python.process(block.copy())
        b = rust.process(block.copy())
        assert a.shape == b.shape
        assert np.max(np.abs(a - b)) < 2e-5, name
        assert abs(python.activity_db - rust.activity_db) < 1e-6 * max(1.0, abs(python.activity_db)) + 1e-6
    python.wake()
    rust.wake()


def test_the_rust_compressors_curve_is_the_python_one():
    python, rust = voicefx.PythonLinkedCompressor(SR), sluice_dsp.LinkedCompressor(SR)
    for level in np.linspace(-60, 0, 61):
        assert rust.reduction(level) == pytest.approx(python.reduction(level), abs=1e-12)


# ---------------------------------------------------------------------------------------------- shared effects
def test_a_knob_turned_on_the_python_object_reaches_the_rust_graph():
    gain = sluice_dsp.Gain(0.0)
    run = sluice_dsp.Run([gain])
    graph = sluice_dsp.NativeGraph(SR, ["monitor"])
    graph.set_channels(["mic"])
    graph.set_chain("mic", [run])
    graph.set_channel("mic", {"monitor": 1.0}, None)
    graph.set_mix("monitor", 1.0, False)
    block = np.full((2, 256), 0.1, dtype=np.float32)
    first = graph.process({"mic": block}, 256)["monitor"]
    gain.gain_db = -20.0  # the Effects window changes the Python object...
    second = graph.process({"mic": block}, 256)["monitor"]
    assert first[0, -1] == pytest.approx(0.1, rel=1e-5)
    assert second[0, -1] == pytest.approx(0.01, rel=1e-4)  # ...and the Rust graph hears it


def test_an_effect_that_needs_python_is_refused_and_nothing_changes():
    import pedalboard

    graph = sluice_dsp.NativeGraph(SR, ["monitor"])
    graph.set_channels(["mic"])
    with pytest.raises(TypeError, match="not a native effect"):
        graph.set_chain("mic", [sluice_dsp.Gain(0.0), pedalboard.Reverb()])


# ---------------------------------------------------------------------------------------------- the whole graph
class Host:
    """Stands in for the Rust JACK engine: records which graph mixes the blocks."""

    def __init__(self):
        self.graph, self.on, self.switches = None, False, []

    def set_native(self, graph):
        self.graph = graph

    def use_native(self, on):
        self.on = on
        self.switches.append(on)


def chain_items(channel_id):
    """Fresh effect objects for a channel, the same each time it is called (each graph gets its own)."""
    if channel_id == "mic":
        gate = PlainStage(lambda sr: voicefx.VoiceGate(sr), {"threshold_db": -35.0})
        comp = PlainStage(lambda sr: voicefx.LinkedCompressor(sr), {"ratio": 3.0})
        ceiling = PlainStage(lambda sr: voicefx.CeilingLimiter(sr), {"threshold_db": -3.0})
        return [sluice_dsp.ButterworthHighPass(80.0), sluice_dsp.Gain(4.0), gate, comp, ceiling]
    if channel_id == "game":  # two spectral reducers next to each other: one joined pass
        return [
            Stage(lambda sr: NoiseReducer(sr), {"reduction_db": 10.0}),
            Stage(lambda sr: EchoReducer(sr), {"reduction_db": 6.0}),
        ]
    return []


def make_graph():
    graph = dsp.Graph(SR, ["monitor", "stream"])
    graph.set_channels(["mic", "game", "music"])
    for cid in ("mic", "game"):
        graph.set_chain(cid, [SimpleNamespace(items=chain_items(cid))])
    for cid, gains in (
        ("mic", {"monitor": 0.0, "stream": 1.0}),
        ("game", {"monitor": 0.8, "stream": 0.5}),
        ("music", {"monitor": 0.6, "stream": 0.3}),
    ):
        for mid, g in gains.items():
            graph.set_gain(cid, mid, g)
    graph.set_mix("monitor", 1.0, True)
    graph.set_mix("stream", 0.9, True)
    graph.set_solo("mic", 1.0)
    return graph


def script(step, graph):
    """What happens during the session, the same for both graphs."""
    if step == 10:
        graph.set_gain("game", "stream", 0.0)  # a fader moves (a ramp over the next block)
        graph.set_mix("monitor", 0.5, True)
    if step == 20:
        graph.set_tap("mic", graph.channels["mic"].instances[0])  # the Effects window opens on the mic: Python is needed
    if step == 30:
        graph.set_tap("mic", None)  # ...and closes
        graph.set_gain("mic", "stream", 0.7)  # a fader moves in the very block the Rust graph takes over after
    if step == 40:
        graph.set_solo("mic", None)
        graph.set_gain("music", "stream", 1.4)  # loud enough for the mix limiter


@needs_graph
def test_the_rust_graph_sounds_the_same_as_the_python_graph_through_a_whole_session():
    reference, mixed = make_graph(), make_graph()
    host = Host()
    assert mixed.attach_native(host) and host.graph is mixed.native
    assert mixed.native_active and host.on  # every chain is native: the Rust graph mixes from the start
    reference.live = mixed.live = True
    rng = np.random.default_rng(3)
    voice, music = speech(6.0, seed=1), (0.5 * rng.standard_normal((2, SR * 6))).astype(np.float32)
    native_blocks = python_blocks = 0
    position, frames = 0, 512
    for step in range(70):
        inputs = {
            "mic": voice[:, position : position + frames],
            "game": voice[:, position : position + frames] * 0.5,
            # the music app goes silent for a while (the channels sleep), then sends one block of NaN (a broken app)
            "music": (
                np.zeros((2, frames), np.float32)
                if 45 <= step < 62
                else np.full((2, frames), np.nan, np.float32)
                if step == 62
                else music[:, position : position + frames]
            ),
        }
        inputs = {k: np.ascontiguousarray(v) for k, v in inputs.items()}
        script(step, reference)
        script(step, mixed)
        want = reference.process({k: v.copy() for k, v in inputs.items()}, frames)
        if host.on:  # what the JACK engine does: the Rust graph, or Python's
            got = mixed.native.process({k: v.copy() for k, v in inputs.items()}, frames)
            native_blocks += 1
        else:
            got = mixed.process({k: v.copy() for k, v in inputs.items()}, frames)
            python_blocks += 1
        assert sorted(got) == sorted(want), step
        for key in want:
            assert np.max(np.abs(got[key] - want[key])) < 1e-5, (step, key)
        if step in (5, 25, 35, 65):
            a, b = reference.take_peaks(), mixed.take_peaks()
            for key in a:
                assert b[key] == pytest.approx(a[key], abs=1e-5), (step, key)
            for cid in ("mic", "game", "music"):
                assert mixed.channels[cid].recent == pytest.approx(reference.channels[cid].recent, abs=1e-5), (step, cid)
        position += frames
    assert host.switches == [True, False, True]  # Python only while the live view was open
    # Python from the block the live view opened in (step 20) to the one that heard it close (step 30): the Rust graph takes
    # over after that block, from where Python left everything
    assert python_blocks == 11 and native_blocks == 59
    assert mixed.channels["music"].asleep is False and reference.channels["music"].asleep is False


@needs_graph
def test_a_plugin_that_needs_python_keeps_the_blocks_in_python_and_says_why():
    import pedalboard

    graph = make_graph()
    graph.set_chain("music", [SimpleNamespace(items=[pedalboard.Reverb()])])
    host = Host()
    graph.attach_native(host)
    assert not graph.native_active and not host.on
    assert "music" in graph.native_reason and "Python" in graph.native_reason
    graph.live = True
    graph.set_chain("music", [])  # queued while Python mixes; applied at the start of the next block
    graph.process({}, 256)
    assert graph.native_active and host.on and graph.native_reason == ""


@needs_graph
def test_measure_my_room_takes_the_blocks_back_until_it_is_done():
    graph = make_graph()
    host = Host()
    graph.attach_native(host)
    graph.live = True
    assert host.on
    graph.start_capture("mic", 0.01)  # applied at once (the Rust graph had the blocks), and Python is needed
    assert not host.on and "Measure my room" in graph.native_reason
    block = np.full((2, 512), 0.2, np.float32)
    graph.process({"mic": block}, 512)
    assert graph.take_capture("mic") is not None
    graph.process({"mic": block}, 512)  # the capture is let go at the start of this block
    assert host.on


def test_without_the_rust_graph_nothing_changes(monkeypatch):
    monkeypatch.setattr(dsp, "NATIVE_GRAPH", False)
    graph = make_graph()
    assert not graph.attach_native(Host()) and graph.native is None and not graph.native_active


@needs_graph
def test_the_bug_report_says_who_mixes_the_blocks():
    from sluice import efficiency

    graph = make_graph()
    host = Host()
    host.native_blocks = 1234
    graph.attach_native(host)
    engine = SimpleNamespace(graph=graph)
    assert efficiency.audio_path(engine) == "Rust graph, no Python in the audio path; 1234 blocks mixed in Rust so far"
    graph.set_tap("mic", graph.channels["mic"].instances[0])
    assert efficiency.audio_path(engine).startswith("Python, because the Effects window shows a live view")
    assert efficiency.audio_path(SimpleNamespace(graph=make_graph())).startswith("Python (the Rust graph is not in use")
