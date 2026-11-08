# SPDX-License-Identifier: GPL-3.0-or-later
import json

from sluice import presets
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer
import pytest


@pytest.fixture
def engine():
    e = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
    e.start()
    yield e
    e.shutdown()


def effect(engine, kind):
    return next(x for x in engine.mixer.channel("mic").effects if x.type == kind)


def test_a_built_in_preset_changes_the_reducers_and_leaves_the_gate_alone(engine):
    engine.set_effect_param(effect(engine, "noise_gate").id, "threshold_db", -41.0)
    entries = presets.BUILT_IN["Very noisy or echoing room"][1]
    assert presets.apply(engine, "mic", entries) == 2
    assert effect(engine, "noise_reducer").params["reduction_db"] == 18
    assert effect(engine, "echo_reducer").params["reverb_time"] == 0.9
    assert effect(engine, "noise_gate").params["threshold_db"] == -41.0


def test_quiet_room_switches_the_reducers_off_and_the_default_switches_them_back_on(engine):
    presets.apply(engine, "mic", presets.BUILT_IN["Quiet room"][1])
    assert effect(engine, "noise_reducer").bypass and effect(engine, "echo_reducer").bypass
    presets.apply(engine, "mic", presets.BUILT_IN["Noisy, echoing room (the default)"][1])
    assert not effect(engine, "noise_reducer").bypass


def test_a_preset_never_carries_a_gate_threshold_even_if_a_file_says_so(engine):
    before = effect(engine, "noise_gate").params["threshold_db"]
    presets.apply(engine, "mic", [{"type": "noise_gate", "bypass": False, "params": {"threshold_db": -5.0, "ratio": 2.0}}])
    assert effect(engine, "noise_gate").params["threshold_db"] == before
    assert effect(engine, "noise_gate").params["ratio"] == 2.0
    assert "threshold_db" not in next(e for e in presets.snapshot(engine.mixer.channel("mic").effects) if e["type"] == "noise_gate")["params"]


def test_missing_effects_are_skipped(engine):
    assert presets.apply(engine, "browser", presets.BUILT_IN["Light touch"][1]) == 0


def test_your_own_presets_are_saved_loaded_and_survive_damage(tmp_path, engine):
    path = presets.path_beside(tmp_path / "config.json")
    assert presets.load_user(path) == {}
    saved = {"Mine": presets.snapshot(engine.mixer.channel("mic").effects)}
    assert presets.save_user(path, saved)
    assert presets.load_user(path)["Mine"][0]["type"] == "highpass"
    path.write_text("{ nope")
    assert presets.load_user(path) == {}
    path.write_text(json.dumps({"Odd": [{"type": "eq", "params": {"mid_db": "loud", "low_db": 1}}, "junk"]}))
    assert presets.load_user(path) == {"Odd": [{"type": "eq", "bypass": False, "params": {"low_db": 1.0}}]}
    assert presets.path_beside(None) is None and not presets.save_user(None, saved)
