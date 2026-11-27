# SPDX-License-Identifier: GPL-3.0-or-later
"""0.12.4: OBS and Sluice's Broadcast. Recording devices follow the Broadcast faders, Sluice says when OBS records around them
or hears itself, no app plays into Sluice's own outputs, and apps outside every channel are easy to put on one."""
import json

import pytest

from sluice import rawmic
from sluice.audio_io import NullIO
from sluice.backend import MockSystem, Stream
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer, STREAM


@pytest.fixture
def engine():
    eng = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    eng.start()
    yield eng
    eng.shutdown()


def app_channel(eng):
    return next(c for c in eng.mixer.channels if not c.devices)


def mic_channel(eng):
    return next(c for c in eng.mixer.channels if c.devices)


# ----------------------------------------------------------------------------- 1. recording devices follow Broadcast
def test_an_app_channels_recording_device_follows_its_broadcast_fader_and_mute(engine):
    game = app_channel(engine)
    engine.set_separate(game.id, True)
    engine.set_level(game.id, STREAM, -20.0)
    assert abs(engine.mixer.own_device_gain(game) - 0.1) < 1e-6
    assert abs(engine._applied_gains[(game.id, "solo")] - 0.1) < 1e-6  # what the audio thread was given
    engine.set_mute(game.id, STREAM, True)
    assert engine._applied_gains[(game.id, "solo")] == 0.0
    engine.set_mute(game.id, STREAM, False)
    engine.set_master_mute(STREAM, True)  # the whole Broadcast muted
    assert engine._applied_gains[(game.id, "solo")] == 0.0
    engine.set_master_mute(STREAM, False)
    engine.set_devices_follow_broadcast(False)  # the old behaviour: full level, the level is set in OBS
    assert engine._applied_gains[(game.id, "solo")] == 1.0


def test_a_microphones_recording_device_is_not_muted_by_broadcast(engine):
    """Discord often uses "Sluice (Mic)" as its microphone: muting Broadcast must not silence the voice chat."""
    mic = mic_channel(engine)
    engine.set_separate(mic.id, True)
    engine.set_master_mute(STREAM, True)
    engine.set_mute(mic.id, STREAM, True)
    assert engine._applied_gains[(mic.id, "solo")] == 1.0
    engine.set_mic_muted(True)  # "Mute my microphone" still does
    assert engine._applied_gains[(mic.id, "solo")] == 0.0


def test_the_choice_is_saved():
    mixer = Mixer.demo()
    assert mixer.devices_follow_broadcast is True
    mixer.devices_follow_broadcast = False
    assert Mixer.from_dict(json.loads(json.dumps(mixer.to_dict()))).devices_follow_broadcast is False


# ----------------------------------------------------------------------------- 2 and 4. recording around the faders, loops
def test_obs_recording_a_monitor_of_a_channel_is_found(engine):
    game = app_channel(engine)
    links = {(f"{game.sink_name}:monitor_FL", "obs:input_1"), (f"{game.sink_name}:monitor_FL", "sluice:in_game_L"),
             (f"{game.sink_name}:monitor_FR", "pavucontrol:input_FR")}
    assert rawmic.find_monitors(links, engine.mixer.channels) == {"obs": [game]}  # (Sluice itself and level meters are not)
    text = rawmic.monitor_message("OBS", [game])
    assert f"Monitor of Sluice ({game.label}) output" in text and "Sluice (Broadcast)" in text


def test_the_warning_appears_after_a_few_seconds_and_can_be_dismissed(engine):
    game = app_channel(engine)
    engine.linker.others = {(f"{game.sink_name}:monitor_FL", "obs:input_1")}
    engine.check_raw_mic(100.0)
    assert not engine.raw_mic  # it must last a few seconds first (meters flick on and off)
    engine.check_raw_mic(100.0 + rawmic.SECONDS + 1)
    key = "obs" + rawmic.MONITOR
    assert key in engine.raw_mic and rawmic.short_for(key) == "⚠ obs records around your faders"
    engine.dismiss_raw_mic(key)
    engine.linker.others = set()
    engine.check_raw_mic(200.0)
    assert not engine.raw_mic


def test_obs_hearing_itself_on_broadcast_is_found(engine):
    obs = app_channel(engine)
    obs.apps.append("obs")
    engine.streams = [Stream(9, "obs", "OBS", obs.sink_name)]
    links = {("sluice_stream_mic:capture_FL", "obs:input_1")}
    in_broadcast = lambda channel: engine.mixer.route_gain(channel, engine.mixer.mix(STREAM)) > 0  # noqa: E731
    assert rawmic.find_loops(links, engine.streams, engine.channel_for_stream, in_broadcast) == {"obs": (obs, "broadcast")}
    engine.set_mute(obs.id, STREAM, True)  # muted in Broadcast: no loop
    assert rawmic.find_loops(links, engine.streams, engine.channel_for_stream, in_broadcast) == {}


def test_recording_another_channels_device_is_not_a_loop(engine):
    """0.12.6: your report: OBS recorded "Sluice (Mic)" and "Sluice (Browser)" while its monitoring played into the OBS
    channel, and 0.12.4 said "OBS can hear itself on Broadcast". Neither device carries the OBS channel."""
    channels = [c for c in engine.mixer.channels if not c.devices]
    obs, browser = channels[0], channels[1]
    mic = mic_channel(engine)
    obs.apps.append("obs")
    engine.streams = [Stream(9, "obs", "OBS", obs.sink_name)]
    links = {(f"sluice_solo_{mic.id}_mic:capture_FL", "OBS:input_FL"),
             (f"sluice_solo_{browser.id}:monitor_FL", "OBS:input_FL")}
    in_broadcast = lambda channel: True  # noqa: E731
    assert rawmic.find_loops(links, engine.streams, engine.channel_for_stream, in_broadcast) == {}


def test_recording_the_device_of_the_channel_you_play_into_is_a_loop(engine):
    obs = app_channel(engine)
    obs.apps.append("obs")
    engine.streams = [Stream(9, "obs", "OBS", obs.sink_name)]
    links = {(f"sluice_solo_{obs.id}_mic:capture_FL", "OBS:input_FL")}
    found = rawmic.find_loops(links, engine.streams, engine.channel_for_stream, lambda channel: False)
    assert found == {"OBS": (obs, "own")}  # even when that channel is not in Broadcast: the device carries it anyway
    assert f"records \u201cSluice ({obs.label})\u201d" in rawmic.loop_message("OBS", obs, "own")


def test_a_warning_is_not_repeated_when_obs_reconnects(engine, caplog):
    import logging
    game = app_channel(engine)
    engine.linker.others = {(f"{game.sink_name}:monitor_FL", "obs:input_1")}
    key = "obs" + rawmic.MONITOR
    with caplog.at_level(logging.WARNING, logger="sluice.engine"):
        engine.check_raw_mic(100.0)
        engine.check_raw_mic(100.0 + rawmic.SECONDS + 1)
        engine.linker.others = set()  # OBS reconnects its sources
        engine.check_raw_mic(110.0)
        assert key not in engine.raw_mic  # gone from the status bar at once
        engine.linker.others = {(f"{game.sink_name}:monitor_FL", "obs:input_1")}
        engine.check_raw_mic(112.0)
        assert key in engine.raw_mic  # back at once, no new waiting
    assert caplog.text.count("records around your faders") == 1  # 0.12.4 logged it each time
    engine.linker.others = set()
    engine.check_raw_mic(113.0)
    engine.check_raw_mic(113.0 + rawmic.FORGET_SECONDS + 1)  # gone for a minute: forgotten, may be reported again later
    assert key not in engine._raw_reported


def test_the_check_uses_the_link_list_the_last_sync_read():
    from sluice.linker import PwLinker
    calls = []

    def run(args):
        calls.append(args)
        if args == ["-l"]:
            return 0, "a:out_1\n  |-> b:in_1\n"
        return 0, ""
    linker = PwLinker(run=run)
    linker.sync({("a:out_1", "b:in_1"), ("c:out_1", "d:in_1")})
    assert calls.count(["-l"]) == 1
    assert linker.fresh_links() == {("a:out_1", "b:in_1"), ("c:out_1", "d:in_1")}  # no second pw-link -l
    assert linker.fresh_links(max_age=-1) is None  # too old: read again


# ----------------------------------------------------------------------------- 3. Sluice's own outputs
def test_an_app_playing_into_the_broadcast_feed_is_moved_off_it(engine):
    engine.system.streams = [Stream(42, "mystery", "Mystery app", "sluice_stream")]
    engine.apply_rules(1000.0)
    assert engine.system.moves[-1] == (42, engine.default_sink)
    assert any("Sluice (Broadcast) feed" in n for n in engine.take_notices())


def test_an_app_on_a_recording_feed_goes_to_its_channel(engine):
    game = app_channel(engine)
    game.apps.append("mygame")
    engine.set_separate(game.id, True)
    engine.system.streams = [Stream(43, "mygame", "My game", game.solo_sink_name)]
    engine.apply_rules(1000.0)
    assert engine.system.moves[-1] == (43, game.sink_name)


# ----------------------------------------------------------------------------- 5. apps outside every channel
def test_apps_that_played_outside_every_channel_are_remembered_for_a_while(engine):
    engine.system.streams = [Stream(50, "chromium", "Chromium", engine.default_sink)]
    engine.apply_rules(1000.0)
    assert engine.recent_unassigned["chromium"][0] == "Chromium"
    engine.system.streams = []  # it stopped (an alert is a few seconds long)
    engine.apply_rules(1010.0)
    assert "chromium" in engine.recent_unassigned
    engine.apply_rules(1000.0 + 16 * 60)
    assert "chromium" not in engine.recent_unassigned


def test_playing_now_offers_them(qapp, tmp_path):
    from sluice.ui import MainWindow
    eng = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    eng.start()
    win = MainWindow(eng, tmp_path / "config.json")
    try:
        eng.system.streams = [Stream(50, "chromium", "Chromium", eng.default_sink)]
        eng.apply_rules(1000.0)
        eng.system.streams = []
        eng.apply_rules(1001.0)
        bar = win.apps_bar
        bar.refresh()
        assert "1 not on a channel" in bar.text()
        bar._fill()
        texts = [a.text() for a in bar.menu.actions()]
        assert any(t.startswith("Chromium") and "not on a channel" in t for t in texts)
        game = app_channel(eng)
        bar._assign("chromium", game.id)
        bar.refresh()
        assert "not on a channel" not in bar.text() and "chromium" in game.apps
    finally:
        win.shutdown()


def test_the_follow_setting_is_in_the_menu_and_settings(qapp, tmp_path):
    from sluice.ui import MainWindow
    eng = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    eng.start()
    win = MainWindow(eng, tmp_path / "config.json")
    try:
        win._refresh_mixer_menu()
        assert win.follow_action.isChecked()
        win.follow_action.trigger()
        assert eng.mixer.devices_follow_broadcast is False and "full level" in win.status_label.text()
        win.open_settings("Audio")
        win.follow_action.trigger()
        assert eng.mixer.devices_follow_broadcast is True
    finally:
        win.shutdown()


# ----------------------------------------------------------------------------- 8. Tile: a tile folded in again keeps its size
def test_a_tile_folded_out_and_in_again_is_as_tall_as_the_others(qapp, tmp_path):
    from sluice.ui import MainWindow
    mixer = Mixer.demo()
    mixer.skin = "tile"
    eng = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    eng.start()
    win = MainWindow(eng, tmp_path / "config.json")
    try:
        win.resize(1343, 860)
        win.show()
        for _ in range(10):
            qapp.processEvents()
        tiles = {s.channel.id: s for s in win.strips}
        usual = tiles["browser"].height()
        tiles["game"].set_open(True)
        assert tiles["game"].height() > usual
        tiles["game"].set_open(False)
        for _ in range(5):
            qapp.processEvents()
        assert tiles["game"].height() == usual  # it came back 24 px taller, and the window had to scroll
    finally:
        win.shutdown()


# ----------------------------------------------------------------------------- 6. a stream that ends while being moved
def test_a_stream_that_ended_while_being_moved_is_not_an_error(engine):
    game = app_channel(engine)
    game.apps.append("shredabillion.exe")
    engine.system.streams = [Stream(51891, "shredabillion.exe", "ShredABillion.exe", engine.default_sink)]

    def gone(index, sink):  # what PipeWire does when the stream closed a moment before
        engine.system.streams = []
        raise RuntimeError("51891")
    engine.system.move_stream = gone
    engine.take_errors()
    engine.apply_rules(1000.0)
    assert engine.take_errors() == []  # before 0.12.4: "Could not move ShredABillion.exe: 51891"


def test_a_real_move_failure_is_still_reported(engine):
    game = app_channel(engine)
    game.apps.append("stubborn")
    engine.system.streams = [Stream(7, "stubborn", "Stubborn", engine.default_sink)]
    engine.system.move_error = RuntimeError("refused")
    engine.take_errors()
    engine.apply_rules(1000.0)
    assert any("Could not move Stubborn" in e for e in engine.take_errors())


def test_ended_streams_are_forgotten(engine):
    engine._move_history = {1: [1.0], 2: [2.0]}
    engine.system.streams = [Stream(2, "x", "X", engine.default_sink)]
    engine.apply_rules(1000.0)
    assert 1 not in engine._move_history


# ----------------------------------------------------------------------------- 7. quitting while the session logs out
def test_quitting_when_the_audio_server_is_gone_does_not_wait_or_warn(caplog):
    import logging
    from sluice.backend import PulseSystem

    class Gone:
        def module_unload(self, index):
            raise RuntimeError("Audio server shut down: the PulseAudio connection is closed")

        def sink_input_list(self):
            raise RuntimeError("closed")

        def close(self):
            pass

    system = PulseSystem.__new__(PulseSystem)
    system._pulse = Gone()
    system._modules = {"sluice_stream": [1, 2], "sluice_ch_game": [3], "sluice_ch_chat": [4]}
    system.begin_shutdown()
    with pytest.raises(RuntimeError):
        system.list_streams()  # no reconnecting to a server that is going away
    with caplog.at_level(logging.INFO, logger="sluice.pulse"):
        system.cleanup()
    assert "already gone" in caplog.text and "could not unload" not in caplog.text and not system._modules


# ----------------------------------------------------------------------------- 9 and 10. tray and meter rate
def test_the_tray_tooltip_is_only_sent_when_it_changes(qapp, tmp_path):
    from sluice.ui import MainWindow
    eng = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    eng.start()
    win = MainWindow(eng, tmp_path / "config.json")
    try:
        sent = []

        class FakeTray:  # stands in for the panel icon (there is no tray without a desktop)
            def isVisible(self):
                return True

            def setIcon(self, icon):
                pass

            def setToolTip(self, text):
                sent.append(text)
        real, win._tray = win._tray, FakeTray()
        for _ in range(20):
            win._refresh_tray_icon()
        assert len(sent) <= 1  # it sent the same tooltip on every meter update (60 a second)
        eng.set_mic_muted(True)
        win._refresh_tray_icon()
        assert len(sent) == 2 and sent[-1] != sent[0]
        win._tray = real
    finally:
        win.shutdown()


def test_meters_run_at_half_rate_while_another_window_is_in_use(qapp, tmp_path):
    from sluice import ui_meters
    from sluice.ui import MainWindow
    eng = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    eng.start()
    win = MainWindow(eng, tmp_path / "config.json")
    try:
        win.show()
        win.isActiveWindow = lambda: False
        assert win._meter_interval() == 33 and abs(ui_meters.FRAME_S - 2 / 60) < 1e-9
        win.isActiveWindow = lambda: True
        assert win._meter_interval() == 16 and abs(ui_meters.FRAME_S - 1 / 60) < 1e-9
    finally:
        win.shutdown()
        ui_meters.FRAME_S = 1 / 60


# ----------------------------------------------------------------------------- 0.12.6: recording devices on by default
def test_new_setups_and_new_channels_have_their_own_recording_device(engine):
    assert all(c.separate for c in Mixer.default().channels)
    added = engine.add_channel("Podcast")
    assert added.separate and added.solo_sink_name in engine.system.null_sinks
    engine.set_devices_for_channels(False)
    assert not any(c.separate for c in engine.mixer.channels if not c.devices)
    assert mic_channel(engine).separate  # the microphone keeps "Sluice (Mic)"
    assert not engine.add_channel("Later").separate  # new channels follow the choice


def test_older_settings_are_kept_and_asked_about_once(tmp_path):
    import json
    mixer = Mixer.default()
    for channel in mixer.channels:
        if not channel.devices:
            channel.separate = channel.id == "game"
    data = mixer.to_dict()
    del data["recording_devices_for_channels"]  # as 0.12.5 and older wrote it
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    loaded = Mixer.load(path)
    assert loaded.channel("game").separate and not loaded.channel("music").separate  # nothing changed by itself
    assert loaded.ask_devices_for_channels and not loaded.devices_for_channels
    loaded.save(path)
    again = Mixer.load(path)
    assert not again.ask_devices_for_channels  # the choice is saved: asked only once
    everyone = Mixer.default().to_dict()
    del everyone["recording_devices_for_channels"]
    path.write_text(json.dumps(everyone))
    assert not Mixer.load(path).ask_devices_for_channels  # all on already (like yours): nothing to ask


def test_the_question_and_the_settings_switch(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from sluice.ui import MainWindow
    eng = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    eng.start()
    win = MainWindow(eng, tmp_path / "config.json")
    try:
        eng.set_devices_for_channels(False)
        eng.mixer.ask_devices_for_channels = True
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        win.ask_about_channel_devices()
        assert all(c.separate for c in eng.mixer.channels) and win.devices_action.isChecked()
        win.ask_about_channel_devices()  # never twice
        win.devices_action.trigger()  # Settings › Audio switch off
        assert not any(c.separate for c in eng.mixer.channels if not c.devices)
    finally:
        win.shutdown()
