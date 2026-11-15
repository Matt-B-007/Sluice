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


def test_a_room_choice_changes_the_reducers_and_leaves_the_gate_alone(engine):
    engine.set_effect_param(effect(engine, "noise_gate").id, "threshold_db", -41.0)
    entries = presets.ROOMS["Noisy"][1]
    assert presets.apply(engine, "mic", entries) == 2
    assert effect(engine, "noise_reducer").params["reduction_db"] == 18
    assert effect(engine, "echo_reducer").params["reverb_time"] == 0.8
    assert effect(engine, "noise_gate").params["threshold_db"] == -41.0


def test_quiet_switches_the_reducers_off_and_normal_switches_them_back_on(engine):
    presets.apply(engine, "mic", presets.ROOMS["Quiet"][1])
    assert effect(engine, "noise_reducer").bypass and effect(engine, "echo_reducer").bypass
    presets.apply(engine, "mic", presets.ROOMS["Normal"][1])
    assert not effect(engine, "noise_reducer").bypass


def test_a_ready_made_choice_never_carries_a_gate_threshold_or_gain_even_if_a_file_says_so(engine):
    before = effect(engine, "noise_gate").params.get("threshold_db")
    presets.apply(engine, "mic", [{"type": "noise_gate", "bypass": False, "params": {"threshold_db": -5.0, "ratio": 2.0}},
                                  {"type": "gain", "bypass": False, "params": {"gain_db": 9.0}}])
    assert effect(engine, "noise_gate").params.get("threshold_db") == before
    assert effect(engine, "noise_gate").params["ratio"] == 2.0
    assert not any(e.type == "gain" for e in engine.mixer.channel("mic").effects)


def test_your_own_preset_keeps_the_gate_threshold_and_gain(engine):
    engine.set_effect_param(effect(engine, "noise_gate").id, "threshold_db", -41.0)
    saved = presets.snapshot(engine.mixer.channel("mic").effects)
    assert next(e for e in saved if e["type"] == "noise_gate")["params"]["threshold_db"] == -41.0
    engine.set_effect_param(effect(engine, "noise_gate").id, "threshold_db", -20.0)
    presets.apply(engine, "mic", saved, personal=True)
    assert effect(engine, "noise_gate").params["threshold_db"] == -41.0


def test_applying_adds_the_effects_a_channel_lacks_in_the_usual_order(engine):
    assert presets.apply(engine, "browser", presets.STYLES["Broadcast"][1]) == 4
    kinds = [e.type for e in engine.mixer.channel("browser").effects]
    assert kinds == ["highpass", "eq", "compressor", "limiter"]
    assert presets.apply(engine, "browser", presets.ROOMS["Quiet"][1]) == 0  # nothing to switch off


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
