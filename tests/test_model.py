# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest

from sluice.model import (
    MAX_DB,
    MIN_DB,
    MONITOR,
    STREAM,
    Effect,
    Mixer,
    db_to_linear,
    linear_to_db,
    new_effect_id,
)


def test_db_conversions():
    assert db_to_linear(0) == pytest.approx(1.0)
    assert db_to_linear(-6.0206) == pytest.approx(0.5, rel=1e-3)
    assert db_to_linear(MIN_DB) == 0.0
    assert linear_to_db(0) == MIN_DB
    assert linear_to_db(db_to_linear(-12)) == pytest.approx(-12)


def test_default_layout():
    mixer = Mixer.default()
    assert [c.id for c in mixer.channels] == ["mic", "browser", "game", "chat", "music", "system"]
    assert [m.id for m in mixer.mixes] == [MONITOR, STREAM]
    mic = mixer.channel("mic")
    assert mic.devices == [""]  # the system default microphone
    assert mic.mutes[MONITOR] is True  # no self-echo by default
    assert mic.mutes[STREAM] is False
    assert mixer.channel("game").sink_name == "sluice_ch_game"
    assert mixer.mix(STREAM).sink_name == "sluice_stream"
    assert mixer.mix(MONITOR).sink_name is None


def test_add_channel_makes_unique_safe_ids():
    mixer = Mixer.default()
    a = mixer.add_channel("Game")
    b = mixer.add_channel("  Browser / Tabs!  ")
    c = mixer.add_channel("")
    assert a.id == "game_2"
    assert b.id == "browser_tabs"
    assert c.label == "Channel"
    assert set(a.levels) == {MONITOR, STREAM}
    assert len({ch.id for ch in mixer.channels}) == len(mixer.channels)


def test_remove_channel():
    mixer = Mixer.default()
    mixer.remove_channel("system")
    assert [c.id for c in mixer.channels] == ["mic", "browser", "game", "chat", "music"]
    with pytest.raises(KeyError):
        mixer.channel("system")


def test_assign_app_belongs_to_one_channel_only():
    mixer = Mixer.default()
    mixer.assign_app("spotify", "music")
    mixer.assign_app("spotify", "game")
    assert mixer.channel("music").apps == []
    assert mixer.channel("game").apps == ["spotify"]
    assert mixer.channel_for_app("spotify").id == "game"
    mixer.assign_app("spotify", None)
    assert mixer.channel_for_app("spotify") is None


def test_linked_levels_move_together_and_unlinked_do_not():
    mixer = Mixer.default()
    game = mixer.channel("game")
    assert game.linked
    mixer.set_level("game", MONITOR, -9)
    assert game.levels == {MONITOR: -9, STREAM: -9}
    mic = mixer.channel("mic")
    assert not mic.linked
    mixer.set_level("mic", MONITOR, -4)
    assert mic.levels[MONITOR] == -4 and mic.levels[STREAM] == 0.0


def test_levels_are_clamped():
    mixer = Mixer.default()
    mixer.set_level("game", MONITOR, 99)
    assert mixer.channel("game").levels[STREAM] == MAX_DB
    mixer.set_level("game", MONITOR, -999)
    assert mixer.channel("game").levels[MONITOR] == MIN_DB


def test_route_and_master_gain():
    mixer = Mixer.default()
    game, monitor = mixer.channel("game"), mixer.mix(MONITOR)
    game.levels[MONITOR] = -6.0206
    assert mixer.route_gain(game, monitor) == pytest.approx(0.5, rel=1e-3)
    game.mutes[MONITOR] = True
    assert mixer.route_gain(game, monitor) == 0.0
    assert mixer.master_gain(monitor) == pytest.approx(1.0)
    monitor.mute = True
    assert mixer.master_gain(monitor) == 0.0


def test_demo_layout_is_filled_in():
    mixer = Mixer.demo()
    assert mixer.channel_for_app("spotify").id == "music"
    assert [e.type for e in mixer.channel("mic").effects] == ["highpass", "noise_gate", "eq", "compressor", "limiter"]


def test_roundtrip(tmp_path):
    mixer = Mixer.default()
    mixer.channel("game").devices = ["alsa_input.foo"]
    mixer.assign_app("spotify", "music")
    mixer.set_level("music", MONITOR, -7.5)
    mixer.channel("music").linked = False
    mixer.channel("music").mutes[STREAM] = True
    mixer.channel("system").effects.append(
        Effect(new_effect_id(), "builtin", "Compressor", type="compressor", params={"threshold_db": -30.0})
    )
    mixer.channel("system").effects.append(
        Effect("abc123", "vst3", "Plug", path="/x/Plug.vst3", plugin_name="Plug", bypass=True, state="QUJD")
    )
    mixer.mix(MONITOR).device = "alsa_output.bar"
    mixer.mix(STREAM).limiter = False
    mixer.add_channel("Browser")
    path = tmp_path / "sub" / "config.json"
    mixer.save(path)
    def without_effect_ids(data):  # effect ids are made up again on every load
        for channel in data["channels"]:
            for effect in channel["effects"]:
                effect.pop("id", None)
        return data

    assert without_effect_ids(Mixer.load(path).to_dict()) == without_effect_ids(mixer.to_dict())


def test_load_missing_corrupt_or_old_version_gives_defaults(tmp_path):
    default = Mixer.default().to_dict()
    assert Mixer.load(tmp_path / "nope.json").to_dict() == default
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert Mixer.load(bad).to_dict() == default
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"version": 1, "strips": []}))
    assert Mixer.load(old).to_dict() == default


def test_from_dict_ignores_garbage():
    data = Mixer.default().to_dict()
    data["channels"] = [
        "junk",
        None,
        {"id": "../evil", "label": "x"},  # unsafe id: dropped
        {"id": "ok", "label": "  Good  ", "color": "red; background:url(x)", "devices": ["a", 5, None],
         "apps": "nope", "levels": {MONITOR: 999, STREAM: "x"}, "mutes": {MONITOR: "yes"},
         "effects": [{"kind": "builtin", "type": "gain", "params": {"gain_db": "x", "other": 2}},
                     {"kind": "weird"}, "x"]},
        {"id": "ok", "label": "duplicate id"},
    ]
    data["mixes"] = [{"id": MONITOR, "gain_db": -999, "device": 42, "mute": "x"}, {"id": "nope"}, 3]
    mixer = Mixer.from_dict(data)
    assert [c.id for c in mixer.channels] == ["ok"]
    channel = mixer.channel("ok")
    assert channel.label == "Good"
    assert channel.color.startswith("#") and len(channel.color) == 7  # the bad colour was replaced
    assert channel.devices == ["a"]
    assert channel.apps == []
    assert channel.levels == {MONITOR: MAX_DB, STREAM: 0.0}
    assert channel.mutes == {MONITOR: False, STREAM: False}
    assert len(channel.effects) == 1
    assert channel.effects[0].params == {"other": 2.0}
    assert mixer.mix(MONITOR).gain_db == MIN_DB
    assert mixer.mix(MONITOR).device == ""  # invalid device value kept the default
    assert mixer.mix(MONITOR).mute is False


def test_all_invalid_channels_fall_back_to_defaults_but_empty_list_is_respected():
    data = Mixer.default().to_dict()
    data["channels"] = ["x", 1]
    assert len(Mixer.from_dict(data).channels) == 6
    data["channels"] = []
    assert Mixer.from_dict(data).channels == []


def test_stream_mix_ignores_saved_device():
    data = Mixer.default().to_dict()
    data["mixes"] = [{"id": STREAM, "device": "alsa_output.evil"}]
    assert Mixer.from_dict(data).mix(STREAM).device is None


def test_settings_are_copied_from_the_old_pwmix_folder_once(tmp_path):
    from sluice.model import migrate_legacy_settings

    old = tmp_path / "pwmix"
    old.mkdir()
    (old / "config.json").write_text('{"version": 2}')
    (old / "controls.json").write_text("[]")
    target = tmp_path / "sluice" / "config.json"
    assert migrate_legacy_settings(target) is True
    assert target.read_text() == '{"version": 2}' and (target.parent / "controls.json").read_text() == "[]"
    assert (old / "config.json").exists()  # the old folder is left alone
    target.write_text('{"version": 2, "mine": true}')
    assert migrate_legacy_settings(target) is False  # never overwrites Sluice's own settings
    assert "mine" in target.read_text()
    assert migrate_legacy_settings(tmp_path / "x" / "sluice" / "config.json") is False  # nothing to copy


def test_buffer_size_is_saved_and_only_known_values_are_accepted(tmp_path):
    mixer = Mixer.default()
    assert mixer.buffer_frames == 512
    mixer.buffer_frames = 1024
    mixer.save(tmp_path / "c.json")
    assert Mixer.load(tmp_path / "c.json").buffer_frames == 1024
    data = mixer.to_dict()
    for bad in (100, "1024", True, None, 4096, -512):
        data["buffer_frames"] = bad
        assert Mixer.from_dict(data).buffer_frames == 512


def test_backups_keep_the_last_five_versions_and_not_more(tmp_path):
    from sluice.model import BACKUP_EVERY_SECONDS, list_backups, make_backup

    config = tmp_path / "config.json"
    clock = 1_700_000_000.0
    for version in range(9):
        config.write_text(f"version {version}")
        made = make_backup(config, f"version {version + 1}", now=clock)
        assert made is not None
        import os
        os.utime(made, (clock, clock))  # as if made at that moment
        clock += BACKUP_EVERY_SECONDS + 5
    backups = list_backups(config)
    assert len(backups) == 5 and backups[0].read_text() == "version 8" and backups[-1].read_text() == "version 4"


def test_backups_are_not_made_for_nothing_or_too_often(tmp_path):
    import os

    from sluice.model import list_backups, make_backup

    config = tmp_path / "config.json"
    assert make_backup(config, "x", now=1e9) is None  # no file yet
    config.write_text("one")
    assert make_backup(config, "one", now=1e9) is None  # unchanged
    first = make_backup(config, "two", now=1e9)
    assert first is not None
    os.utime(first, (1e9, 1e9))
    config.write_text("two")
    assert make_backup(config, "three", now=1e9 + 60) is None  # one a minute ago: too soon
    assert len(list_backups(config)) == 1
    assert make_backup(config, "three", now=1e9 + 3600) is not None


def test_only_the_real_settings_file_gets_backups_never_an_export(tmp_path):
    from sluice.model import list_backups

    target = tmp_path / "config.json"
    Mixer.default().save(target, backups=True)
    other = Mixer.default()
    other.add_channel("Extra")
    other.save(target, backups=True)
    assert len(list_backups(target)) == 1
    export = tmp_path / "exported" / "mine.json"
    other.save(export)
    other.add_channel("More")
    other.save(export)
    assert not (export.parent / "backups").exists()


def test_close_action_is_saved_and_validated(tmp_path):
    mixer = Mixer.default()
    assert mixer.close_action == "quit"  # closing the window quits, unless someone chooses otherwise
    mixer.close_action = "minimize"
    mixer.save(tmp_path / "c.json")
    assert Mixer.load(tmp_path / "c.json").close_action == "minimize"
    for bad in ("hide", 3, None, ["quit"]):
        data = Mixer.default().to_dict()
        data["close_action"] = bad
        assert Mixer.from_dict(data).close_action == "quit"
