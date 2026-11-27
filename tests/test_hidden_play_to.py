# SPDX-License-Identifier: GPL-3.0-or-later
"""0.13.1-beta.2: the "Play to Sluice (X)" devices are hidden (media.class Audio/Sink/Internal), so OBS cannot record one by
mistake and apps' sound menus do not list them; Sluice moves apps onto them with PipeWire's metadata, because the old
"move this stream to that sink" cannot see a hidden sink. Tested by hand on PipeWire 1.6.12 (hidden from pactl and OBS, ports
kept, a playing app moved in). Devices are made in alphabetical order, the order OBS lists them in."""

from types import SimpleNamespace

import pytest

try:
    import pulsectl  # noqa: F401
except (ImportError, OSError):
    pytest.skip("pulsectl or libpulse is not available", allow_module_level=True)

from test_pulse_backend import FakePulse, sink_input  # noqa: E402

from sluice import backend  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import HIDDEN_CLASS, INVALID_INDEX, MockSystem, PulseSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402


@pytest.fixture
def system(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", FakePulse)
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backend.subprocess, "run", run)
    made = PulseSystem()
    made.calls = calls
    return made


def playing(index, sink, object_id, binary="discord"):
    item = sink_input(index, sink, binary=binary)
    item.proplist["object.id"] = str(object_id)
    return item


def test_a_hidden_sink_is_made_with_the_internal_class_and_its_name(system):
    system.ensure_null_sink("sluice_ch_chat", "Play to Sluice (Chat)", hidden=True)
    _, module, args = system._pulse.loaded[-1]
    assert module == "module-null-sink"
    assert args == (
        f"sink_name=sluice_ch_chat sink_properties='device.description=Play to Sluice (Chat) media.class={HIDDEN_CLASS}'"
    )  # the exact form tested by hand (no plain space inside the name: PipeWire splits there)
    assert system.is_hidden("sluice_ch_chat")


def test_when_the_server_ignores_the_class_a_normal_device_is_made(system):
    pulse = system._pulse
    real_load = pulse.module_load

    def load_and_list(name, args=""):
        index = real_load(name, args)
        if "sluice_ch_chat" in args:
            pulse.sinks.append(SimpleNamespace(index=40, name="sluice_ch_chat", description="x", owner_module=index))
        return index

    pulse.module_load = load_and_list
    system.ensure_null_sink("sluice_ch_chat", "Play to Sluice (Chat)", hidden=True)
    first = pulse.loaded[0][0]
    assert first in pulse.unloaded and not system.is_hidden("sluice_ch_chat")
    assert HIDDEN_CLASS not in pulse.loaded[-1][2]  # made again the usual way: it still works, it is only not hidden


def test_apps_are_moved_onto_a_hidden_sink_with_pipewire_metadata_and_still_seen_there(system):
    system.ensure_null_sink("sluice_ch_chat", "Play to Sluice (Chat)", hidden=True)
    system._pulse.inputs = [playing(7, 1, 431)]
    system.move_stream(7, "sluice_ch_chat")
    assert system.calls[-1] == ["pw-metadata", "431", "target.object", "sluice_ch_chat"]
    assert system._pulse.moved == []  # not the old way: it cannot see the sink
    system._pulse.inputs = [playing(7, 999, 431)]  # the server reports a sink it does not list (the hidden one)
    (stream,) = system.list_streams()
    assert stream.sink == "sluice_ch_chat"  # so the engine sees the app on its channel and leaves it there


def test_a_route_is_forgotten_when_the_app_stops_or_is_moved_elsewhere(system):
    system.ensure_null_sink("sluice_ch_chat", "Play to Sluice (Chat)", hidden=True)
    system._pulse.inputs = [playing(7, 1, 431)]
    system.move_stream(7, "sluice_ch_chat")
    system._pulse.inputs = [playing(7, 1, 431)]  # the person moved it to the speakers in the desktop's settings
    assert system.list_streams()[0].sink == "alsa_output.speakers" and system._routes == {}
    system.move_stream(7, "sluice_ch_chat")
    system._pulse.inputs = []
    assert system.list_streams() == [] and system._routes == {}


def test_quitting_takes_back_every_target_sluice_set(system):
    system.ensure_null_sink("sluice_ch_chat", "Play to Sluice (Chat)", hidden=True)
    system._pulse.inputs = [playing(7, 1, 431), playing(8, 1, 432, binary="spotify")]
    system.move_stream(7, "sluice_ch_chat")
    system.move_stream(8, "sluice_ch_chat")
    system.cleanup()
    assert ["pw-metadata", "-d", "431", "target.object"] in system.calls
    assert ["pw-metadata", "-d", "432", "target.object"] in system.calls
    assert system._routes == {}


def test_a_stream_without_a_pipewire_id_is_reported_not_moved(system):
    system.ensure_null_sink("sluice_ch_chat", "Play to Sluice (Chat)", hidden=True)
    system._pulse.inputs = [sink_input(7, 1, binary="discord")]
    with pytest.raises(LookupError):
        system.move_stream(7, "sluice_ch_chat")


def test_a_hidden_leftover_is_adopted_from_the_module_list(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", FakePulse)
    made = PulseSystem(purge=False)
    made._pulse.modules.append(
        SimpleNamespace(
            index=33,
            name="module-null-sink",
            argument=f"sink_name=sluice_ch_chat sink_properties='device.description=x media.class={HIDDEN_CLASS}'",
            owner_module=INVALID_INDEX,
        )
    )
    made.ensure_null_sink("sluice_ch_chat", "Play to Sluice (Chat)", hidden=True)
    assert made._pulse.loaded == [] and made._modules["sluice_ch_chat"] == [33] and made.is_hidden("sluice_ch_chat")


# ---------------------------------------------------------------------------------------------- the engine
def engine_with(mixer=None):
    system = MockSystem()
    engine = Engine(mixer or Mixer.demo(), system, NullIO(realtime=False), NullLinker())
    engine.start()
    return engine, system


def test_play_to_devices_are_hidden_and_every_device_is_made_in_alphabetical_order():
    engine, system = engine_with()
    try:
        channels = engine.mixer.channels
        assert {c.sink_name for c in channels} <= system.hidden_sinks
        assert not any(c.solo_sink_name in system.hidden_sinks for c in channels if c.separate)
        names = [system.null_sinks[name][0] for name in system.created]
        assert names == sorted(names, key=str.casefold)  # "Play to Sluice (...)", then "Sluice (Broadcast) for OBS", ...
        assert names.index("Sluice (Broadcast) for OBS") < names.index("Sluice (Browser) for OBS")
    finally:
        engine.shutdown()


def test_the_switch_lists_them_again_and_is_saved():
    engine, system = engine_with()
    try:
        engine.set_show_play_to_devices(True)
        assert not any(c.sink_name in system.hidden_sinks for c in engine.mixer.channels)
        assert Mixer.from_dict(engine.mixer.to_dict()).show_play_to_devices is True
        engine.set_show_play_to_devices(False)
        assert {c.sink_name for c in engine.mixer.channels} <= system.hidden_sinks
        assert Mixer.from_dict({}).show_play_to_devices is False  # hidden unless chosen
    finally:
        engine.shutdown()


def test_a_new_channel_gets_a_hidden_play_to_device():
    engine, system = engine_with()
    try:
        channel = engine.add_channel("Podcast")
        assert channel.sink_name in system.hidden_sinks
    finally:
        engine.shutdown()


# ---------------------------------------------------------------------------------------------- the launcher's icon
def test_an_update_refreshes_the_launchers_icon_once(tmp_path, monkeypatch):
    """0.13.1-beta.2: the taskbar showed the old logo after an update (the copy made at install was never replaced)."""
    from sluice import launcher

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    ran = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **_k: ran.append(command[0]))
    assert launcher.refresh_icons() is False  # not installed: nothing to refresh
    launcher_file = launcher.launcher_path()
    launcher_file.parent.mkdir(parents=True)
    launcher_file.write_text("[Desktop Entry]\n")
    old = launcher.icon_path()
    old.parent.mkdir(parents=True)
    old.write_text("<svg>the old coral logo</svg>")
    assert launcher.refresh_icons() is True
    assert old.read_bytes() == launcher.bundled_icon().read_bytes()
    assert all(t.read_bytes() == s.read_bytes() for s, t in launcher._icon_pairs() if s.is_file())
    assert launcher.refresh_icons() is False  # the same now: nothing copied, no cache refresh
