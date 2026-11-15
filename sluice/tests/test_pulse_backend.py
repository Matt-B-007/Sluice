# SPDX-License-Identifier: GPL-3.0-or-later
"""PulseSystem against a fake pulsectl: checks the exact commands we send, not real audio."""
from types import SimpleNamespace

import pytest

pulsectl = pytest.importorskip("pulsectl")

from sluice.backend import INVALID_INDEX, PulseSystem  # noqa: E402


def sink_input(index, sink, binary=None, name=None, owner=INVALID_INDEX):
    props = {}
    if binary is not None:
        props["application.process.binary"] = binary
    if name is not None:
        props["application.name"] = name
    return SimpleNamespace(index=index, sink=sink, owner_module=owner, proplist=props)


class FakePulse:
    def __init__(self, client_name):
        self.client_name = client_name
        self.sinks = [
            SimpleNamespace(index=1, name="alsa_output.speakers", description="Speakers", owner_module=INVALID_INDEX),
            SimpleNamespace(index=2, name="sluice_ch_old", description="x", owner_module=7),
        ]
        self.sources = [
            SimpleNamespace(name="alsa_input.mic", description="Mic", owner_module=INVALID_INDEX),
            SimpleNamespace(name="alsa_output.speakers.monitor", description="Monitor", owner_module=INVALID_INDEX),
            SimpleNamespace(name="sluice_stream_mic", description="ours", owner_module=INVALID_INDEX),
        ]
        self.inputs = []
        self.modules = [
            SimpleNamespace(index=3, name="module-null-sink", argument="sink_name=sluice_ch_old"),
            SimpleNamespace(index=4, name="module-remap-source", argument="master=sluice_ch_old.monitor source_name=sluice_old_mic"),
            SimpleNamespace(index=5, name="module-null-sink", argument="sink_name=somebody_elses"),
            SimpleNamespace(index=6, name="module-loopback", argument="source=a sink=b"),
        ]
        self.loaded, self.unloaded, self.moved = [], [], []
        self.closed = False
        self._next = 20

    def server_info(self):
        return SimpleNamespace(default_sink_name="alsa_output.speakers", default_source_name="alsa_input.mic")

    def sink_list(self):
        return list(self.sinks)

    def source_list(self):
        return list(self.sources)

    def sink_input_list(self):
        return list(self.inputs)

    def module_list(self):
        return list(self.modules)

    def module_load(self, name, args=""):
        index = self._next
        self._next += 1
        self.loaded.append((index, name, args))
        return index

    def module_unload(self, index):
        self.unloaded.append(index)

    def sink_input_move(self, index, sink_index):
        self.moved.append((index, sink_index))

    def close(self):
        self.closed = True


@pytest.fixture
def system(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", FakePulse)
    return PulseSystem()


def test_stale_sluice_devices_are_purged_but_others_are_kept(system):
    assert system._pulse.unloaded == [3, 4]


def test_device_lists_flag_monitors_and_hide_our_own_objects(system):
    assert [d.name for d in system.list_sinks()] == ["alsa_output.speakers"]
    sources = system.list_sources()
    assert [d.name for d in sources if not d.monitor] == ["alsa_input.mic"]
    assert all(d.monitor for d in sources if d.name.endswith(".monitor"))
    assert not any(d.name.startswith("sluice") for d in sources)
    assert system.default_sink() == "alsa_output.speakers"
    assert system.default_source() == "alsa_input.mic"


def test_null_sink_arguments(system):
    system.ensure_null_sink("sluice_ch_game", "Sluice Game")
    _, name, args = system._pulse.loaded[-1]
    assert name == "module-null-sink"
    assert args == "sink_name=sluice_ch_game sink_properties=device.description=Sluice\u00a0Game"  # no real space: see backend


def test_descriptions_cannot_break_out_of_the_module_arguments(system):
    system.ensure_null_sink("sluice_ch_x", 'Evil" sink_name=hijack \'q\' \\ \n')
    args = system._pulse.loaded[-1][2]
    assert '"' not in args and len(args.split(" ")) == 2  # (a plain-space split, like the server's) still exactly two arguments: nothing broke out of the name
    assert "\\" not in args and "\n" not in args and "'" not in args
    assert args.startswith("sink_name=sluice_ch_x ")


def test_an_existing_sink_is_adopted_not_recreated(system):
    system._pulse.sinks.append(SimpleNamespace(index=9, name="sluice_ch_game", description="x", owner_module=42))
    system.ensure_null_sink("sluice_ch_game", "Sluice Game")
    assert system._pulse.loaded == []
    assert system._modules["sluice_ch_game"] == [42]


def test_stream_mix_also_gets_a_microphone_source(system):
    pulse = system._pulse
    pulse.sources = [s for s in pulse.sources if s.name != "sluice_stream_mic"]  # a fresh server has none yet
    system.ensure_null_sink("sluice_stream", "Sluice Stream", as_source=True)
    assert [name for _, name, _ in pulse.loaded] == ["module-null-sink", "module-remap-source"]
    args = pulse.loaded[-1][2]
    assert "master=sluice_stream.monitor" in args
    assert "source_name=sluice_stream_mic" in args
    assert "device.description=Sluice\u00a0Stream\u00a0(Mic)" in args


def test_an_existing_microphone_source_is_adopted(system):
    pulse = system._pulse
    pulse.sources = [s for s in pulse.sources if s.name != "sluice_stream_mic"]
    pulse.sources.append(SimpleNamespace(name="sluice_stream_mic", description="x", owner_module=55))
    system.ensure_null_sink("sluice_stream", "Sluice Stream", as_source=True)
    assert [name for _, name, _ in pulse.loaded] == ["module-null-sink"]
    assert 55 in system._modules["sluice_stream"]


def test_remove_null_sink_unloads_in_reverse_order(system):
    system._pulse.sources = [s for s in system._pulse.sources if s.name != "sluice_stream_mic"]
    system.ensure_null_sink("sluice_stream", "Sluice Stream", as_source=True)
    indexes = [i for i, *_ in system._pulse.loaded]
    system._pulse.unloaded.clear()
    system.remove_null_sink("sluice_stream")
    assert system._pulse.unloaded == list(reversed(indexes))
    system.remove_null_sink("sluice_stream")  # already gone: nothing happens
    assert system._pulse.unloaded == list(reversed(indexes))


def test_streams_are_listed_with_stable_app_keys(system):
    pulse = system._pulse
    pulse.inputs = [
        sink_input(10, 1, binary="Firefox", name="Firefox Web Browser"),
        sink_input(11, 1, name="Some Game"),  # no binary: falls back to the app name
        sink_input(12, 1, binary="loopback-thing", owner=77),  # made by a module: ignored
        sink_input(13, 99, binary="ghost"),  # on a sink we do not know: ignored
        sink_input(14, 2, binary="spotify", name="Spotify"),
        sink_input(15, 1),  # no identity at all: ignored
    ]
    streams = system.list_streams()
    assert [(s.index, s.key, s.name, s.sink) for s in streams] == [
        (10, "firefox", "Firefox Web Browser", "alsa_output.speakers"),
        (11, "some game", "Some Game", "alsa_output.speakers"),
        (14, "spotify", "Spotify", "sluice_ch_old"),
    ]


def test_move_stream_uses_the_sink_index(system):
    system.move_stream(10, "alsa_output.speakers")
    assert system._pulse.moved == [(10, 1)]
    with pytest.raises(LookupError):
        system.move_stream(10, "does_not_exist")


def test_cleanup_removes_everything_and_closes(system):
    system.ensure_null_sink("sluice_ch_a", "A")
    system.ensure_null_sink("sluice_ch_b", "B")
    system._pulse.unloaded.clear()
    system.cleanup()
    assert len(system._pulse.unloaded) == 2
    assert system._pulse.closed


def test_purge_stale_reports_how_many_it_removed(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", FakePulse)
    system = PulseSystem(purge=False)
    assert system._pulse.unloaded == []  # --cleanup connects without purging first, so it can count
    assert system.purge_stale() == 2
    assert system._pulse.unloaded == [3, 4]


def test_purge_stale_only_removes_the_old_pwmix_devices_when_asked(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", FakePulse)
    system = PulseSystem(purge=False)
    system._pulse.module_list = lambda: [
        SimpleNamespace(index=7, name="module-null-sink", argument="sink_name=pwmix_ch_old"),
        SimpleNamespace(index=8, name="module-remap-source", argument="source_name=pwmix_stream_mic"),
        SimpleNamespace(index=9, name="module-null-sink", argument="sink_name=sluice_ch_old"),
        SimpleNamespace(index=10, name="module-null-sink", argument="sink_name=somebody_elses"),
    ]
    assert system.purge_stale() == 1 and system._pulse.unloaded == [9]  # startup never touches the old name
    system._pulse.unloaded.clear()
    assert system.purge_stale(legacy=True) == 3 and system._pulse.unloaded == [7, 8, 9]


class SplittingPulse(FakePulse):
    """Behaves like pipewire-pulse: the argument string is cut at spaces first, and only then are quotes looked at."""

    def __init__(self, client_name, accept=("nbsp",)):
        super().__init__(client_name)
        self.accept = accept

    @staticmethod
    def _parse(args):
        tokens, current, quoted, escaped = [], "", False, False
        for ch in args:
            if escaped:
                current += ch
                escaped = False
            elif ch == "\\" and quoted:
                escaped = True
            elif ch == '"':
                quoted = not quoted
            elif ch == " " and not quoted:
                tokens.append(current)
                current = ""
            else:
                current += ch
        tokens.append(current)
        return dict(t.split("=", 1) for t in tokens if "=" in t)

    def module_load(self, name, args=""):
        index = super().module_load(name, args)
        parsed = self._parse(args)
        key = "sink_properties" if name == "module-null-sink" else "source_properties"
        description = parsed.get(key, "device.description=").split("=", 1)[1] or parsed.get("sink_name", parsed.get("source_name"))
        node = SimpleNamespace(name=parsed.get("sink_name") or parsed.get("source_name"), description=description, owner_module=index)
        (self.sinks if name == "module-null-sink" else self.sources).append(node)
        return index


def test_devices_get_their_full_names_even_though_the_server_splits_at_spaces(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", SplittingPulse)
    system = PulseSystem(purge=False)
    system._pulse.sources = [s for s in system._pulse.sources if s.name != "sluice_stream_mic"]
    system.ensure_null_sink("sluice_ch_game", "Sluice (Game)")
    system.ensure_null_sink("sluice_stream", "Sluice (Broadcast) feed", True, "Sluice (Broadcast)")
    sinks = {s.name: s.description for s in system._pulse.sinks}
    sources = {s.name: s.description for s in system._pulse.sources}
    assert sinks["sluice_ch_game"].replace(" ", " ") == "Sluice (Game)"
    assert sources["sluice_stream_mic"].replace(" ", " ") == "Sluice (Broadcast)"
    assert system._pulse.unloaded == []  # the first spelling already worked


def test_the_old_quoted_spelling_is_what_cut_names_down_to_plain_sluice():
    parsed = SplittingPulse._parse('sink_name=x sink_properties=device.description="Sluice (Game)"')
    assert parsed["sink_properties"] == "device.description=Sluice (Game)" or parsed["sink_properties"].startswith("device.description=")


def test_if_the_first_spelling_gives_the_wrong_name_the_next_is_tried(monkeypatch):
    class Stubborn(SplittingPulse):
        def module_load(self, name, args=""):
            index = FakePulse.module_load(self, name, args)
            wrong = " " in args  # pretend a server that mangles the first spelling
            key_name = args.split("sink_name=")[1].split()[0] if "sink_name=" in args else args.split("source_name=")[1].split()[0]
            node = SimpleNamespace(name=key_name, description="Sluice" if wrong else "Sluice (Game)", owner_module=index)
            (self.sinks if name == "module-null-sink" else self.sources).append(node)
            return index

        def sink_list(self):
            return [s for s in self.sinks if s.owner_module not in self.unloaded]

    monkeypatch.setattr(pulsectl, "Pulse", Stubborn)
    system = PulseSystem(purge=False)
    system.ensure_null_sink("sluice_ch_game", "Sluice (Game)")
    assert len(system._pulse.loaded) == 2 and system._pulse.unloaded == [system._pulse.loaded[0][0]]
    assert '\\"' in system._pulse.loaded[1][2]


def test_a_proton_game_named_cs2_exe_also_answers_to_cs2(system):
    system._pulse.inputs = [sink_input(11, 1, name="cs2.exe")]
    (stream,) = system.list_streams()
    assert stream.key == "cs2.exe"
    assert "cs2" in stream.names and "cs2.exe" in stream.names


def test_the_sink_list_is_not_asked_for_again_on_every_look(system):
    calls = []
    real = system._pulse.sink_list
    system._pulse.sink_list = lambda: (calls.append(1), real())[1]
    system._pulse.inputs = [sink_input(11, 1, binary="firefox")]
    system.list_streams()
    system.list_streams()
    system.list_streams()
    assert len(calls) == 1
    system._pulse.sinks.append(SimpleNamespace(index=9, name="alsa_output.new", description="n", owner_module=INVALID_INDEX))
    system._pulse.inputs = [sink_input(12, 9, binary="firefox")]  # a stream on a sink not seen before: look again
    assert system.list_streams()[0].sink == "alsa_output.new"
    assert len(calls) == 2


def test_a_broken_connection_is_replaced_and_listing_the_apps_works_again(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", FakePulse)
    system = PulseSystem(purge=False)
    first = system._pulse
    first.sink_inputs = [sink_input(5, 1, binary="firefox")]

    def broken():
        raise pulsectl.PulseError("connection terminated")

    first.sink_input_list = broken
    original = FakePulse.sink_input_list
    monkeypatch.setattr(FakePulse, "sink_input_list", lambda self: [sink_input(5, 1, binary="firefox")])
    streams = system.list_streams()
    assert [s.key for s in streams] == ["firefox"]
    assert system._pulse is not first and first.closed
    monkeypatch.setattr(FakePulse, "sink_input_list", original)


def test_if_the_server_is_really_gone_the_error_still_reaches_the_caller(monkeypatch):
    monkeypatch.setattr(pulsectl, "Pulse", FakePulse)
    system = PulseSystem(purge=False)

    def broken():
        raise pulsectl.PulseError("connection terminated")

    system._pulse.sink_input_list = broken
    monkeypatch.setattr(pulsectl, "Pulse", lambda name: (_ for _ in ()).throw(pulsectl.PulseError("no server")))
    with pytest.raises(pulsectl.PulseError):
        system.list_streams()
