# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
import pytest

from sluice.audio_io import NullIO
from sluice.backend import MockSystem, Stream
from sluice.engine import MOVE_RETRY_SECONDS, Engine, _connect
from sluice.linker import NullLinker, PortSnapshot
from sluice.model import MONITOR, STREAM, Effect, Mixer, new_effect_id

N = 512


@pytest.fixture
def rig():
    system = MockSystem()
    system.add_demo_streams()
    io = NullIO(realtime=False)
    linker = NullLinker()
    mixer = Mixer.demo()
    mixer.channel("chat").mutes[STREAM] = False  # chat is muted on Broadcast by default; these tests use it as a plain channel
    engine = Engine(mixer, system, io, linker)
    engine.start()
    yield system, io, linker, engine
    engine.shutdown()


def silence_except(io, engine, **levels):
    io.fixed_inputs = {c.id: np.full((2, 1), levels.get(c.id, 0.0), dtype=np.float32) for c in engine.mixer.channels}


def peak(io, key="stream", blocks=3):
    for _ in range(blocks):
        out = io.process_once(N)
    return float(np.abs(out[key]).max())


# ------------------------------------------------------------------ virtual devices
def test_start_creates_a_sink_per_channel_and_the_stream_mix(rig):
    system, *_ = rig
    assert set(system.null_sinks) == {"sluice_ch_mic", "sluice_ch_browser", "sluice_ch_game", "sluice_ch_chat", "sluice_ch_music", "sluice_ch_system", "sluice_stream", "sluice_solo_mic"}
    assert system.null_sinks["sluice_stream"][1] is True  # also exposed as a microphone
    assert system.null_sinks["sluice_ch_game"][1] is False


def test_ports_match_channels_and_mixes(rig):
    _, io, _, _ = rig
    assert io.channel_ids == ["mic", "browser", "game", "chat", "music", "system"]
    assert io.mix_ids == [MONITOR, STREAM, "solo_mic"]  # the Mic channel has its own recording device from the start


# ------------------------------------------------------------------------ apps
def test_assigned_apps_are_moved_onto_their_channel_sink(rig):
    system, *_ = rig
    sinks = {s.key: s.sink for s in system.streams}
    assert sinks["spotify"] == "sluice_ch_music"
    assert sinks["vlc"] == "sluice_ch_music"
    assert sinks["discord"] == "sluice_ch_chat"
    assert sinks["gamelauncher"] == "sluice_ch_game"
    assert sinks["firefox"] == system.sinks[0].name  # unassigned apps are left alone


def test_assigning_an_app_moves_it_immediately(rig):
    system, _, _, engine = rig
    engine.assign_app("firefox", "chat")
    assert {s.key: s.sink for s in system.streams}["firefox"] == "sluice_ch_chat"
    engine.assign_app("firefox", "game")
    assert {s.key: s.sink for s in system.streams}["firefox"] == "sluice_ch_game"


def test_unassigning_sends_the_app_back_to_the_default_device(rig):
    system, _, _, engine = rig
    engine.assign_app("spotify", None)
    assert {s.key: s.sink for s in system.streams}["spotify"] == system.default_snk


def test_a_new_stream_of_an_assigned_app_is_picked_up_by_tick(rig):
    system, _, _, engine = rig
    system.streams.append(Stream(9, "spotify", "Spotify", system.sinks[0].name))
    changed = engine.tick(now=1e9)
    assert "streams" in changed
    assert [s for s in system.streams if s.index == 9][0].sink == "sluice_ch_music"


def test_failed_moves_are_retried_only_after_a_pause(rig):
    system, _, _, engine = rig
    system.move_error = RuntimeError("sink busy")
    attempts = []
    original = system.move_stream
    system.move_stream = lambda index, sink: (attempts.append(index), original(index, sink))[1]
    system.streams.append(Stream(9, "spotify", "Spotify", system.sinks[0].name))
    engine.apply_rules(1000.0)
    assert attempts == [9]
    engine.apply_rules(1001.0)
    assert attempts == [9]  # backing off
    engine.apply_rules(1000.0 + MOVE_RETRY_SECONDS + 1)
    assert attempts == [9, 9]
    assert any("sink busy" in e for e in engine.take_errors())


# ---------------------------------------------------------------------- channels
def test_add_channel_creates_sink_ports_and_links(rig):
    system, io, linker, engine = rig
    channel = engine.add_channel("Browser")
    assert channel.sink_name in system.null_sinks
    assert channel.id in io.channel_ids
    assert (f"{channel.sink_name}:out_L", f"sluice:in_{channel.id}_L") in linker.links


def test_remove_channel_returns_its_apps_and_cleans_up(rig):
    system, io, linker, engine = rig
    engine.remove_channel("music")
    assert "sluice_ch_music" not in system.null_sinks
    assert "music" not in io.channel_ids
    io.process_once(N)  # the audio thread picks up the change at the start of the next block
    assert not [link for link in linker.links if "music" in link[0] or "music" in link[1]]
    sinks = {s.key: s.sink for s in system.streams}
    assert sinks["spotify"] == system.default_snk and sinks["vlc"] == system.default_snk
    assert "music" not in engine.graph.channels


def test_rename_recreates_the_sink_with_the_new_name(rig):
    system, _, _, engine = rig
    engine.rename_channel("game", "Games")
    assert system.null_sinks["sluice_ch_game"][0] == "Sluice (Games) output"
    assert engine.mixer.channel("game").label == "Games"
    assert {s.key: s.sink for s in system.streams}["gamelauncher"] == "sluice_ch_game"


# ------------------------------------------------------------------------ links
def test_default_links(rig):
    system, _, linker, _ = rig
    mic, headphones = system.sources[0].name, system.sinks[0].name
    assert (f"{mic}:out_L", "sluice:in_mic_L") in linker.links
    for channel in ("mic", "game", "music", "chat"):
        assert (f"sluice_ch_{channel}:out_R", f"sluice:in_{channel}_R") in linker.links  # apps on the channel
    assert ("sluice:out_monitor_L", f"{headphones}:in_L") in linker.links
    assert ("sluice:out_stream_R", "sluice_stream:in_R") in linker.links


def test_adding_and_removing_a_device(rig):
    system, _, linker, engine = rig
    usb = system.sources[2].name
    engine.add_device("game", usb)
    assert (f"{usb}:out_L", "sluice:in_game_L") in linker.links
    engine.add_device("game", usb)  # adding twice changes nothing
    assert engine.mixer.channel("game").devices.count(usb) == 1
    engine.remove_device("game", usb)
    assert not any(link[0].startswith(usb) for link in linker.links)


def test_a_missing_device_makes_no_links_and_returns_when_plugged_in(rig):
    system, _, linker, engine = rig
    engine.add_device("game", "alsa_input.ghost")
    assert not any(link[0].startswith("alsa_input.ghost") for link in linker.links)
    system.sources.append(type(system.sources[0])("alsa_input.ghost", "Ghost mic"))
    engine.tick(now=1e9)
    assert ("alsa_input.ghost:out_L", "sluice:in_game_L") in linker.links


def test_unplugging_the_monitor_device_drops_its_links(rig):
    system, _, linker, engine = rig
    headphones = system.sinks[0]
    engine.set_mix_device(MONITOR, headphones.name)
    system.sinks.remove(headphones)
    engine.tick(now=1e9)
    assert not any(link[1].startswith(headphones.name) for link in linker.links)


def test_default_device_change_is_followed(rig):
    system, _, linker, engine = rig
    system.default_snk = system.sinks[2].name
    changed = engine.tick(now=1e9)
    assert "devices" in changed
    assert ("sluice:out_monitor_L", f"{system.sinks[2].name}:in_L") in linker.links
    assert not any(link[1].startswith(system.sinks[0].name) for link in linker.links)


def test_sluice_never_feeds_itself(rig):
    system, _, linker, engine = rig
    system.default_snk = "sluice_stream"
    engine.tick(now=1e9)
    assert engine.resolve_mix_sink(engine.mixer.mix(MONITOR)) is None
    assert not any(link[0].startswith("sluice:out_monitor") for link in linker.links)
    assert engine.resolve_source("sluice_stream_mic") is None


def test_links_are_retried_until_the_ports_exist():
    class Late(NullLinker):
        ready = False
        syncs = 0

        def snapshot(self):
            return PortSnapshot(fabricate=True) if self.ready else PortSnapshot()

        def sync(self, desired):
            self.syncs += 1
            return super().sync(desired)

    system, linker = MockSystem(), Late()
    engine = Engine(Mixer.default(), system, NullIO(realtime=False), linker)
    engine.start()
    assert engine._link_retry
    before = linker.syncs
    engine.tick(now=1e9)
    assert linker.syncs > before  # tried again
    linker.ready = True
    engine.tick(now=1e9 + 1)
    assert not engine._link_retry
    assert linker.links
    engine.shutdown()


def test_connect_handles_mono_on_either_side():
    stereo_in = ["sluice:in_a_L", "sluice:in_a_R"]
    assert _connect(["mic:capture_MONO"], stereo_in) == {("mic:capture_MONO", stereo_in[0]), ("mic:capture_MONO", stereo_in[1])}
    assert _connect(["x:out_L", "x:out_R"], ["spk:playback_MONO"]) == {
        ("x:out_L", "spk:playback_MONO"), ("x:out_R", "spk:playback_MONO")}
    assert _connect(["a:L", "a:R"], ["b:L", "b:R"]) == {("a:L", "b:L"), ("a:R", "b:R")}
    assert _connect([], stereo_in) == set() and _connect(["a"], []) == set()


# ------------------------------------------------------------------------ audio
def test_levels_and_mutes_shape_the_mixes(rig):
    _, io, _, engine = rig
    silence_except(io, engine, music=0.2)  # music: -8 dB in the monitor mix, -18 dB in the stream mix
    assert peak(io, "monitor") == pytest.approx(0.2 * 10 ** (-8 / 20), rel=0.02)
    assert peak(io, "stream") == pytest.approx(0.2 * 10 ** (-18 / 20), rel=0.02)
    engine.set_mute("music", STREAM, True)
    assert peak(io, "stream") == 0.0
    assert peak(io, "monitor") > 0.05  # the monitor mix still has it


def test_linked_fader_moves_both_mixes_and_unlinked_does_not(rig):
    _, io, _, engine = rig
    engine.set_level("game", MONITOR, -20)
    assert engine.mixer.channel("game").levels[STREAM] == -20
    engine.set_level("music", MONITOR, -1)
    assert engine.mixer.channel("music").levels[STREAM] == -18  # unchanged: music is not linked
    engine.set_linked("music", True)  # linking snaps the stream fader to the monitor level
    assert engine.mixer.channel("music").levels[STREAM] == -1


def test_master_mute_and_gain(rig):
    _, io, _, engine = rig
    silence_except(io, engine, chat=0.4)
    full = peak(io, "stream")
    engine.set_master(STREAM, -6.0206)
    assert peak(io, "stream") == pytest.approx(full / 2, rel=0.02)
    engine.set_master_mute(STREAM, True)
    assert peak(io, "stream") == 0.0


def test_the_mix_limiter_can_be_switched_off(rig):
    _, io, _, engine = rig
    silence_except(io, engine, chat=0.9)
    engine.set_level("chat", MONITOR, 12)  # linked: +12 dB, so about 3.6 at the mix
    assert peak(io, "stream", blocks=4) <= 0.8913 + 1e-4
    engine.set_limiter(STREAM, False)
    assert peak(io, "stream", blocks=4) == pytest.approx(0.9 * 10 ** (12 / 20), rel=0.01)  # untouched +12 dB


def test_effects_change_the_audio_and_can_be_bypassed_and_removed(rig):
    _, io, _, engine = rig
    silence_except(io, engine, chat=0.1)
    engine.set_level("chat", STREAM, 0.0)
    engine.mixer.channel("chat").levels[STREAM] = 0.0
    base = peak(io, "stream")
    effect = Effect(new_effect_id(), "builtin", "Gain", type="gain", params={"gain_db": 6.0206})
    instance = engine.add_effect("chat", effect)
    assert instance.usable
    assert peak(io, "stream") == pytest.approx(base * 2, rel=0.02)
    engine.set_effect_bypass("chat", effect.id, True)
    assert peak(io, "stream") == pytest.approx(base, rel=0.02)
    engine.set_effect_bypass("chat", effect.id, False)
    engine.set_effect_param(effect.id, "gain_db", 0.0)
    assert peak(io, "stream") == pytest.approx(base, rel=0.02)
    engine.remove_effect("chat", effect.id)
    assert engine.effect_instance(effect.id) is None
    assert peak(io, "stream") == pytest.approx(base, rel=0.02)


def test_built_in_effects_stay_in_the_best_order_and_cannot_be_moved(rig):
    _, _, _, engine = rig
    channel = engine.mixer.channel("chat")
    for key, name in (("limiter", "Limiter"), ("compressor", "Compressor"), ("highpass", "High-pass"), ("eq", "3-Band EQ")):
        engine.add_effect("chat", Effect(new_effect_id(), "builtin", name, type=key))
    assert [e.type for e in channel.effects] == ["highpass", "eq", "compressor", "limiter"]  # whatever order they were added in
    before = [e.id for e in channel.effects]
    engine.move_effect("chat", before[0], 1)
    assert [e.id for e in channel.effects] == before
    assert any("best order" in message for message in engine.take_errors())


def test_a_vst3_can_be_moved_but_built_ins_stay_in_order(rig):
    _, _, _, engine = rig
    channel = engine.mixer.channel("mic")  # the recommended voice chain: high-pass, gate, EQ, compressor, limiter
    plugin = Effect(new_effect_id(), "vst3", "Gone", path="/not/here.vst3")
    engine.add_effect("mic", plugin)
    assert channel.effects[-1] is plugin
    engine.move_effect("mic", plugin.id, -2)
    assert [e.type or e.kind for e in channel.effects] == ["highpass", "noise_gate", "eq", "vst3", "compressor", "limiter"]
    engine.move_effect("mic", plugin.id, -9)  # clamped to the top
    assert channel.effects[0] is plugin
    assert [e.type for e in channel.effects[1:]] == ["highpass", "noise_gate", "eq", "compressor", "limiter"]


def test_the_recommended_voice_chain_replaces_the_built_ins_and_keeps_plugins(rig):
    _, _, _, engine = rig
    channel = engine.mixer.channel("game")
    plugin = Effect(new_effect_id(), "vst3", "Gone", path="/not/here.vst3")
    engine.add_effect("game", plugin)
    engine.apply_voice_chain("game")
    assert [e.type or e.kind for e in channel.effects[:1]] == ["vst3"] or plugin in channel.effects
    assert [e.type for e in channel.effects if e.kind == "builtin"] == ["highpass", "noise_gate", "eq", "compressor", "limiter"]
    assert plugin in channel.effects
    engine.apply_voice_chain("game")  # again: still exactly one of each
    assert [e.type for e in channel.effects if e.kind == "builtin"] == ["highpass", "noise_gate", "eq", "compressor", "limiter"]


def test_a_broken_effect_is_kept_but_skipped(rig):
    _, io, _, engine = rig
    effect = Effect(new_effect_id(), "vst3", "Gone", path="/not/here.vst3")
    instance = engine.add_effect("chat", effect)
    assert instance.error
    silence_except(io, engine, chat=0.2)
    assert peak(io, "stream") > 0.1  # audio still passes
    assert effect in engine.mixer.channel("chat").effects


def test_levels_report_post_fader_peaks(rig):
    _, io, _, engine = rig
    silence_except(io, engine, chat=0.2, music=0.2)
    for _ in range(2):
        io.process_once(N)
    levels = engine.levels()
    assert levels["ch:chat:monitor"] == pytest.approx(0.2, rel=0.02)
    assert levels["ch:music:monitor"] == pytest.approx(0.2 * 10 ** (-8 / 20), rel=0.02)
    assert levels["ch:music:stream"] == pytest.approx(0.2 * 10 ** (-18 / 20), rel=0.02)
    assert levels["ch:mic:monitor"] == 0.0  # muted in the monitor mix
    assert levels["mix:monitor"] > 0
    assert engine.levels()["ch:chat:monitor"] == 0.0  # peaks reset after reading


# ------------------------------------------------------------------- persistence
def test_save_config_keeps_effect_settings(rig, tmp_path):
    _, _, _, engine = rig
    effect = engine.mixer.channel("mic").effects[1]  # the compressor
    engine.set_effect_param(effect.id, "threshold_db", -33.0)
    engine.save_config(tmp_path / "c.json")
    restored = Mixer.load(tmp_path / "c.json")
    assert restored.channel("mic").effects[1].params["threshold_db"] == -33.0
    assert restored.channel_for_app("spotify").id == "music"


def test_shutdown_can_save_settings_after_audio_stops(rig, tmp_path):
    _, io, _, engine = rig
    engine.set_level("game", MONITOR, -7.0)
    engine.shutdown(save_to=tmp_path / "saved.json")
    assert Mixer.load(tmp_path / "saved.json").channel("game").levels[MONITOR] == -7.0
    assert not io._graph.live


def test_shutdown_cleans_everything_up():
    system = MockSystem()
    io, linker = NullIO(realtime=False), NullLinker()
    engine = Engine(Mixer.default(), system, io, linker)
    engine.start()
    engine.shutdown()
    assert system.cleaned_up
    assert linker.links == set()
    assert not io._graph.live


def test_backend_errors_are_collected_not_raised():
    class Broken(MockSystem):
        def list_streams(self):
            raise RuntimeError("pulse went away")

    engine = Engine(Mixer.default(), Broken(), NullIO(realtime=False), NullLinker())
    engine.start()
    assert any("pulse went away" in e for e in engine.take_errors())
    assert engine.take_errors() == []
    engine.shutdown()


def test_status_text_mentions_dropouts(rig):
    *_, engine = rig
    assert "dropouts" in engine.status_text()


def test_chat_is_not_on_the_broadcast_by_default():
    mixer = Mixer.default()
    assert mixer.channel("chat").mutes.get(STREAM) is True  # no echo for voice-chat apps that record the Broadcast mic
    assert not mixer.channel("game").mutes.get(STREAM)


def test_shutdown_puts_assigned_apps_back_on_the_normal_output(rig):
    system, _, _, engine = rig
    assert {s.key: s.sink for s in system.streams}["spotify"] == "sluice_ch_music"
    engine.shutdown()
    assert {s.key: s.sink for s in system.streams}["spotify"] == system.sinks[0].name


def test_an_app_that_is_moved_back_repeatedly_is_left_alone(rig):
    system, _, _, engine = rig
    stream = next(s for s in system.streams if s.key == "spotify")
    now = 1000.0
    for i in range(8):
        stream.sink = system.sinks[0].name  # something else keeps moving it back
        engine.apply_rules(now + i)
    assert len([m for m in system.moves if m[0] == stream.index]) <= 4  # initial move plus at most FIGHT_MOVES
    assert any("keeps being moved back" in e for e in engine.errors)


def test_a_failing_audio_server_does_not_forget_the_devices(rig):
    system, _, _, engine = rig
    known = [d.name for d in engine.sources]
    assert known

    def boom():
        raise RuntimeError("server gone")

    system.list_sources = boom
    engine.refresh_devices()
    assert [d.name for d in engine.sources] == known


def test_error_messages_that_differ_only_by_a_number_are_not_repeated(rig):
    _, _, _, engine = rig
    engine.errors.clear()
    engine._error("Pulse operation failed, id 17")
    engine._error("Pulse operation failed, id 18")
    assert len(engine.errors) == 1


def test_channel_can_take_what_an_output_device_is_playing(rig):
    from sluice.backend import Device

    system, _, _, engine = rig
    system.sources.append(Device("alsa_output.hdmi.monitor", "Monitor of HDMI", monitor=True))
    engine.refresh_devices()
    engine.add_device("game", "alsa_output.hdmi.monitor")
    wanted, _ = engine.desired_links()
    # a monitor source is the output side of its sink node: links come from "alsa_output.hdmi", never from "...hdmi.monitor"
    assert ("alsa_output.hdmi:out_L", "sluice:in_game_L") in wanted
    assert not any(out.startswith("alsa_output.hdmi.monitor") for out, _ in wanted)


def test_a_monitor_of_a_mix_output_is_refused_to_avoid_a_feedback_loop(rig):
    from sluice.backend import Device

    system, _, _, engine = rig
    listen_sink = engine.resolve_mix_sink(engine.mixer.mix("monitor"))
    system.sources.append(Device(f"{listen_sink}.monitor", "Monitor of Listen output", monitor=True))
    engine.refresh_devices()
    engine.add_device("game", f"{listen_sink}.monitor")
    wanted, _ = engine.desired_links()
    assert not any(inp.startswith("sluice:in_game") and out.startswith(listen_sink) for out, inp in wanted)
    assert any("feedback loop" in e for e in engine.errors)


def test_app_labels(rig):
    from sluice.apps import AppEntry, Catalog

    _, _, _, engine = rig
    engine.catalog = Catalog([AppEntry("Half-Life 2", "steam:220", "game", frozenset({"steam:220"}))])
    assert engine.app_label("steam:220") == "Half-Life 2"
    assert engine.app_label("steam:999") == "Steam game 999"
    assert engine.app_label("firefox") == "Firefox"  # a playing app's own name
    assert engine.app_label("never-heard-of-it") == "never-heard-of-it"


def test_changing_an_output_is_logged_and_multichannel_ones_warn(rig, caplog):
    import logging

    from sluice.backend import Device

    system, _, _, engine = rig
    system.sinks.append(Device("alsa_output.big", "Big interface", channels=17))
    engine.refresh_devices()
    with caplog.at_level(logging.INFO, logger="sluice.engine"):
        engine.set_mix_device("monitor", "alsa_output.big")
    text = caplog.text
    assert "Listen output set to alsa_output.big" in text
    assert "17 channels" in text and "first two" in text
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="sluice.engine"):
        engine.set_mix_device("monitor", "")
    assert "system default" in caplog.text and "17 channels" not in caplog.text


# --------------------------------------------------------- a channel as its own recording device
def test_a_channel_can_be_its_own_recording_device(rig):
    system, io, linker, engine = rig
    assert "sluice_solo_music" not in system.null_sinks and not any("solo_music" in out for out, _ in linker.links)
    engine.set_separate("music", True)
    assert system.null_sinks["sluice_solo_music"] == ("Sluice (Music) recording feed", True)  # also offered as a microphone
    assert any(out == "sluice:out_solo_music_L" and inp.startswith("sluice_solo_music:") for out, inp in linker.links)
    assert "solo_music" in io.mix_ids  # the audio client has ports for it
    silence_except(io, engine, music=0.3, game=0.1)
    out = None
    for _ in range(3):
        out = io.process_once(N)
    assert float(np.abs(out["solo_music"]).max()) == pytest.approx(0.3, abs=1e-3)  # just the music: no game in it
    assert "solo_game" not in out

    engine.set_level("music", "stream", -60.0)  # faders and mutes of the mixes do not touch the own output
    engine.set_mute("music", "stream", True)
    engine.set_mute("music", "monitor", True)
    for _ in range(3):
        out = io.process_once(N)
    assert float(np.abs(out["solo_music"]).max()) == pytest.approx(0.3, abs=1e-3)
    assert float(np.abs(out["stream"]).max()) < 0.2  # while the Broadcast mix really did lose the music

    engine.set_separate("music", False)
    assert "sluice_solo_music" not in system.null_sinks
    assert "solo_music" not in io.process_once(N)
    assert not any("solo_music" in out for out, _ in linker.links)


def test_own_output_follows_the_channels_effects_and_rename_and_removal(rig):
    system, io, linker, engine = rig
    engine.set_separate("mic", True)
    engine.set_effect_bypass("mic", engine.mixer.channel("mic").effects[0].id, False)
    engine.rename_channel("mic", "Voice")
    assert system.null_sinks["sluice_solo_mic"][0] == "Sluice (Voice) recording feed"
    engine.remove_channel("mic")
    assert "sluice_solo_mic" not in system.null_sinks and "sluice_ch_mic" not in system.null_sinks


def test_own_output_is_saved_and_restored(rig, tmp_path):
    _, _, _, engine = rig
    engine.set_separate("game", True)
    engine.save_config(tmp_path / "c.json")
    assert Mixer.load(tmp_path / "c.json").channel("game").separate is True
    assert Mixer.load(tmp_path / "c.json").channel("music").separate is False


def test_connections_are_rechecked_every_few_seconds_not_every_tick(rig, monkeypatch):
    import sluice.engine as engine_module

    _, _, linker, engine = rig
    clock = [engine._last_refresh]
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock[0])
    calls = []
    original = linker.sync
    linker.sync = lambda desired: (calls.append(1), original(desired))[1]
    for _ in range(40):  # 20 seconds of ticks, twice a second, with nothing changing
        clock[0] += 0.5
        engine.tick(clock[0])
    assert 2 <= len(calls) <= 4  # about every 6 seconds, not 40 times


def test_a_device_change_relinks_at_once(rig, monkeypatch):
    import sluice.engine as engine_module
    from sluice.backend import Device

    system, _, linker, engine = rig
    clock = [engine._last_refresh]
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock[0])
    calls = []
    original = linker.sync
    linker.sync = lambda desired: (calls.append(1), original(desired))[1]
    clock[0] += 2.1
    engine.tick(clock[0])  # an ordinary refresh: nothing changed, nothing relinked
    assert calls == []
    system.sources.append(Device("alsa_input.new", "New mic"))
    clock[0] += 2.1
    engine.tick(clock[0])  # the next device refresh sees it and relinks at once
    assert calls


def test_dropouts_while_settling_are_not_shown(rig):
    *_, engine = rig
    engine.io.xruns = 5
    engine.tick(now=engine._quiet_until - 0.5 if engine._quiet_until else 0.0)  # still settling after start
    assert "0 dropouts" in engine.status_text()
    engine._quiet_until = 0.0
    engine.io.xruns = 7
    engine.tick(now=1e9)
    assert "2 dropouts" in engine.status_text()


def test_listen_falls_back_to_the_system_default_when_its_device_is_missing(rig):
    system, io, linker, engine = rig
    engine.mixer.mix("monitor").device = "alsa_output.not_here"
    assert engine.resolve_mix_sink(engine.mixer.mix("monitor")) == engine.default_sink
    assert engine.mixer.mix("monitor").device == "alsa_output.not_here"  # the choice itself is kept


def test_a_microphone_plugged_in_later_is_noticed_once(rig):
    from sluice.backend import Device

    system, io, linker, engine = rig
    assert engine.take_notices() == []  # what was there at the start is not news
    system.sources.append(Device("alsa_input.usb-New_Mic", "Shiny USB Microphone"))
    assert engine.refresh_devices() is True
    notices = engine.take_notices()
    assert len(notices) == 1 and "Shiny USB Microphone" in notices[0]
    engine.refresh_devices()
    assert engine.take_notices() == []  # said once
    assert any(d.name == "alsa_input.usb-New_Mic" for d in engine.sources)  # and offered in the input lists


def test_the_mic_channel_follows_a_new_system_default_microphone(rig):
    from sluice.backend import Device

    system, io, linker, engine = rig
    system.sources.append(Device("alsa_input.usb-New_Mic", "New Mic"))
    system.default_src = "alsa_input.usb-New_Mic"
    engine.refresh_devices()
    assert engine.resolve_source("") == "alsa_input.usb-New_Mic"  # "" is the system default: no setting needed


def test_the_mic_has_its_own_recording_device_with_its_effects_from_the_start():
    mixer = Mixer.default()
    assert mixer.channel("mic").separate is True and not any(c.separate for c in mixer.channels if c.id != "mic")
    assert mixer.channel("mic").solo_description == "Sluice (Mic)"  # what OBS, Discord and games list as a microphone
    assert mixer.channel("mic").description == "Sluice (Mic) output"  # the output apps play into: a different name
    assert mixer.mix(STREAM).source_description == "Sluice (Broadcast)"
