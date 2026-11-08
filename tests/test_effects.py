# SPDX-License-Identifier: GPL-3.0-or-later
import base64

import numpy as np
import pytest

from sluice.effects import BUILTINS, EffectInstance, builtin_names, scan_vst3, vst3_plugin_names
from sluice.model import Effect, Mixer

pedalboard = pytest.importorskip("pedalboard")

SR = 48000


def run(instance: EffectInstance, audio: np.ndarray) -> np.ndarray:
    board = pedalboard.Pedalboard(instance.plugins)
    chunks = [board(np.ascontiguousarray(audio[:, i:i + 512]), SR, reset=False) for i in range(0, audio.shape[1], 512)]
    return np.concatenate(chunks, axis=1)


def sine(amplitude: float, seconds: float = 0.5, freq: float = 440.0) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    mono = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono])


def make(kind: str, **params) -> EffectInstance:
    return EffectInstance(Effect("e1", "builtin", BUILTINS[kind].name, type=kind, params=params))


def test_every_builtin_loads_and_reports_its_parameters():
    assert len(builtin_names()) == len(BUILTINS)
    for key, definition in BUILTINS.items():
        instance = make(key)
        assert instance.usable, (key, instance.error)
        infos = instance.param_infos()
        assert [i.key for i in infos] == [p.key for p in definition.params]
        assert all(i.lo <= i.value <= i.hi for i in infos)


def test_gain_effect_changes_level():
    out = run(make("gain", gain_db=6.0206), sine(0.1))
    assert np.abs(out).max() == pytest.approx(0.2, rel=0.01)


def test_compressor_reduces_loud_signal_and_makeup_restores_it():
    loud = sine(0.9, seconds=1.0)
    plain = run(make("compressor", threshold_db=-24, ratio=8), loud)
    assert np.abs(plain[:, -4000:]).max() < 0.6
    made_up = run(make("compressor", threshold_db=-24, ratio=8, makeup_db=12), loud)
    assert np.abs(made_up[:, -4000:]).max() > np.abs(plain[:, -4000:]).max() * 2


def test_noise_gate_silences_quiet_signal_but_passes_loud():
    gate = make("noise_gate", threshold_db=-40)
    quiet = run(gate, sine(0.001, seconds=1.0))
    assert np.abs(quiet[:, -4000:]).max() < 1e-4
    loud = run(make("noise_gate", threshold_db=-40), sine(0.5, seconds=1.0))
    assert np.abs(loud[:, -4000:]).max() > 0.4


def test_eq_boosts_the_chosen_band():
    flat = run(make("eq"), sine(0.1, freq=1000.0))
    boosted = run(make("eq", mid_hz=1000.0, mid_db=12.0), sine(0.1, freq=1000.0))
    assert np.abs(boosted[:, -4000:]).max() > np.abs(flat[:, -4000:]).max() * 3


def test_stored_parameters_are_clamped_to_their_range():
    instance = make("compressor", threshold_db=999, ratio=-5)
    values = {i.key: i.value for i in instance.param_infos()}
    assert values["threshold_db"] == 0
    assert values["ratio"] == 1


def test_set_param_updates_audio_and_the_saved_value():
    instance = make("gain", gain_db=0.0)
    instance.set_param("gain_db", 6.0206)
    assert instance.effect.params["gain_db"] == pytest.approx(6.0206)
    assert np.abs(run(instance, sine(0.1))).max() == pytest.approx(0.2, rel=0.01)
    instance.set_param("gain_db", 9999)
    assert instance.effect.params["gain_db"] == 24
    instance.set_param("no_such_param", 1)  # ignored, no crash


def test_saved_parameters_survive_a_config_roundtrip(tmp_path):
    mixer = Mixer.default()
    effect = Effect("e1", "builtin", "Compressor", type="compressor")
    mixer.channel("game").effects.append(effect)
    EffectInstance(effect).set_param("threshold_db", -33.0)
    mixer.save(tmp_path / "c.json")
    restored = Mixer.load(tmp_path / "c.json").channel("game").effects[0]
    values = {i.key: i.value for i in EffectInstance(restored).param_infos()}
    assert values["threshold_db"] == -33.0


def test_unknown_builtin_is_an_error_not_a_crash():
    instance = EffectInstance(Effect("x", "builtin", "Mystery", type="mystery"))
    assert not instance.usable
    assert "Unknown built-in" in instance.error
    assert instance.param_infos() == []


def test_missing_vst3_reports_a_clear_error():
    instance = EffectInstance(Effect("x", "vst3", "Gone", path="/definitely/not/here/Gone.vst3"))
    assert not instance.usable
    assert "not found" in instance.error
    assert instance.param_infos() == []
    instance.set_param("anything", 0.5)  # no crash
    instance.capture_state()
    instance.open_editor()


def test_invalid_vst3_file_reports_a_clear_error(tmp_path):
    fake = tmp_path / "Fake.vst3"
    fake.mkdir()
    instance = EffectInstance(Effect("x", "vst3", "Fake", path=str(fake)))
    assert not instance.usable
    assert instance.error.startswith("Could not load Fake.vst3")


def test_vst3_plugin_names_of_garbage_is_empty(tmp_path):
    assert vst3_plugin_names(str(tmp_path / "nope.vst3")) == []


def test_scan_vst3_finds_bundles_sorted_and_depth_limited(tmp_path):
    (tmp_path / "Zeta.vst3").mkdir()
    (tmp_path / "alpha.vst3").mkdir()
    (tmp_path / "Vendor" / "Sub").mkdir(parents=True)
    (tmp_path / "Vendor" / "Comp.vst3").mkdir()
    (tmp_path / "Vendor" / "Sub" / "Deep.vst3").mkdir()
    (tmp_path / "Vendor" / "Sub" / "Deeper").mkdir()
    (tmp_path / "Vendor" / "Sub" / "Deeper" / "TooDeep.vst3").mkdir()
    (tmp_path / "notaplugin.txt").write_text("x")
    names = [name for name, _ in scan_vst3([tmp_path, tmp_path / "missing"])]
    assert names == ["alpha", "Comp", "Deep", "Zeta"]


def test_vst3_state_roundtrip_helpers():
    effect = Effect("x", "vst3", "Fake", path="/nowhere", state=base64.b64encode(b"state").decode())
    instance = EffectInstance(effect)
    instance.capture_state()  # nothing live, so the saved state is kept
    assert base64.b64decode(effect.state) == b"state"


def test_search_paths_include_the_usual_folders_the_environment_and_added_ones(tmp_path, monkeypatch):
    from sluice.effects import vst3_search_paths

    monkeypatch.setenv("VST3_PATH", f"{tmp_path}/env1:{tmp_path}/env2")
    paths = [str(p) for p in vst3_search_paths([str(tmp_path / "mine"), str(tmp_path / "env1")])]
    assert any(p.endswith("/.vst3") for p in paths) and "/usr/lib/vst3" in paths
    assert paths.count(str(tmp_path / "env1")) == 1  # no duplicates
    assert str(tmp_path / "env2") in paths and str(tmp_path / "mine") in paths


def test_plugins_in_added_folders_and_nested_bridge_folders_are_found(tmp_path):
    from sluice.effects import scan_vst3

    (tmp_path / "yabridge" / "Vendor").mkdir(parents=True)
    (tmp_path / "yabridge" / "Vendor" / "Comp.vst3").mkdir()
    (tmp_path / "Top.vst3").mkdir()
    (tmp_path / "SingleFile.vst3").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    names = [name for name, _ in scan_vst3([tmp_path])]
    assert names == ["Comp", "SingleFile", "Top"]


def test_added_plugin_folders_are_saved_and_junk_is_ignored(tmp_path):
    mixer = Mixer.default()
    mixer.vst3_folders = ["/opt/plugins", "/home/me/vst"]
    mixer.save(tmp_path / "c.json")
    assert Mixer.load(tmp_path / "c.json").vst3_folders == ["/opt/plugins", "/home/me/vst"]
    data = mixer.to_dict()
    data["vst3_folders"] = ["/ok", 5, "", None, ["x"]]
    assert Mixer.from_dict(data).vst3_folders == ["/ok"]
    data["vst3_folders"] = "not a list"
    assert Mixer.from_dict(data).vst3_folders == []


def _level_db(audio: np.ndarray) -> float:
    return 20 * np.log10(float(np.sqrt(np.mean(audio[:, SR // 4:] ** 2))) + 1e-12)


def test_the_high_pass_falls_twelve_db_per_octave_and_one_slider_moves_both_stages():
    instance = make("highpass")
    assert len(instance.plugins) == 2
    tone = lambda f: sine(0.1, seconds=1.0, freq=f)  # noqa: E731
    at_cutoff = _level_db(run(instance, tone(100))) - _level_db(tone(100))
    octave_down = _level_db(run(make("highpass"), tone(50))) - _level_db(tone(50))
    assert at_cutoff == pytest.approx(-6.0, abs=0.7)
    assert octave_down < at_cutoff - 6  # a single stage would only fall another 3-4 dB
    instance.apply_param("cutoff_frequency_hz", 200.0)
    assert [p.cutoff_frequency_hz for p in instance.plugins] == [200.0, 200.0]
    assert abs(_level_db(run(make("highpass"), tone(1000))) - _level_db(tone(1000))) < 0.2  # the voice is untouched


def test_the_defaults_suit_a_noisy_echoing_room():
    values = {key: {p.key: p.default for p in d.params} for key, d in BUILTINS.items()}
    assert values["highpass"]["cutoff_frequency_hz"] == 100
    gate = values["noise_gate"]
    assert (gate["threshold_db"], gate["ratio"], gate["attack_ms"], gate["release_ms"]) == (-30, 4, 3, 100)
    assert values["eq"]["mid_hz"] == 250 and values["eq"]["mid_db"] == -4 and values["eq"]["low_db"] == -2
    assert values["compressor"]["makeup_db"] == 2  # unchanged: more makeup or squash did not help in the tests


def test_the_default_gate_quiets_steady_room_noise_but_lets_speech_through():
    rng = np.random.default_rng(3)
    noise = (rng.standard_normal((2, SR * 2)) * 10 ** (-48 / 20)).astype(np.float32)  # a fan, about -48 dBFS
    gate = make("noise_gate")
    hushed = _level_db(run(gate, noise)) - _level_db(noise)
    assert hushed < -12
    speech = sine(0.1, seconds=1.0, freq=200.0)  # a steady voice-level tone, -23 dBFS
    assert _level_db(run(make("noise_gate"), speech)) - _level_db(speech) > -0.5
