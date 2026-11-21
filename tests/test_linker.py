# SPDX-License-Identifier: GPL-3.0-or-later
from sluice.linker import NullLinker, PortSnapshot, PwLinker, parse_links, parse_ports, stereo_pair


def test_stereo_pair_orders_left_then_right_and_ignores_extras():
    ports = ["dev:playback_FR", "dev:playback_RL", "dev:playback_FL", "dev:playback_LFE"]
    assert stereo_pair(ports) == ["dev:playback_FL", "dev:playback_FR"]
    assert stereo_pair(["x:out_R", "x:out_L"]) == ["x:out_L", "x:out_R"]
    assert stereo_pair(["mic:capture_MONO"]) == ["mic:capture_MONO"]
    assert stereo_pair([]) == []


def test_snapshot_filters_by_node_even_when_names_share_a_prefix():
    snap = PortSnapshot(
        outputs=["sluice_ch_game:monitor_FL", "sluice_ch_game:monitor_FR", "sluice_ch_game_2:monitor_FL"],
        inputs=["dev:playback_FL", "dev:playback_FR", "other:playback_FL"],
    )
    assert snap.outputs("sluice_ch_game") == ["sluice_ch_game:monitor_FL", "sluice_ch_game:monitor_FR"]
    assert snap.inputs("dev") == ["dev:playback_FL", "dev:playback_FR"]
    assert snap.outputs("unknown") == []


def test_node_names_containing_colons_still_work():
    snap = PortSnapshot(outputs=["alsa_input.usb-Foo:0:capture_FL"])
    assert snap.outputs("alsa_input.usb-Foo:0") == ["alsa_input.usb-Foo:0:capture_FL"]


def test_parse_ports_and_links():
    assert parse_ports("a:out_L\n\n b:out_R \n") == ["a:out_L", "b:out_R"]
    text = (
        "sluice:out_monitor_L\n"
        "  |-> dev:playback_FL\n"
        "dev:playback_FL\n"
        "  |<- sluice:out_monitor_L\n"
        "  |<- other:out_L\n"
        "lonely:port\n"
    )
    assert parse_links(text) == {("sluice:out_monitor_L", "dev:playback_FL"), ("other:out_L", "dev:playback_FL")}


class FakePipewire:
    """Pretends to be pw-link, remembering links and everything it was asked to do."""

    def __init__(self, links=(), refuse=()):
        self.links = set(links)
        self.refuse = set(refuse)
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args == ["-l"]:
            text = "".join(f"{o}\n  |-> {i}\n{i}\n  |<- {o}\n" for o, i in sorted(self.links))
            return 0, text
        if args in (["-o"], ["-i"]):
            return 0, ""
        if args[0] == "-d":
            self.links.discard((args[1], args[2]))
            return 0, ""
        pair = (args[0], args[1])
        if pair in self.refuse:
            return 1, ""
        self.links.add(pair)
        return 0, ""


def test_sync_creates_missing_links_and_reports_failures():
    fake = FakePipewire(refuse={("a:out", "b:in2")})
    linker = PwLinker(run=fake)
    failed = linker.sync({("a:out", "b:in"), ("a:out", "b:in2")})
    assert failed == {("a:out", "b:in2")}
    assert ("a:out", "b:in") in fake.links


def test_sync_removes_only_links_it_made_itself():
    foreign = ("firefox:out_FL", "speakers:playback_FL")
    fake = FakePipewire(links={foreign})
    linker = PwLinker(run=fake)
    linker.sync({("a:out", "b:in")})
    linker.sync(set())  # nothing wanted any more
    assert fake.links == {foreign}


def test_sync_does_not_repeat_existing_links():
    fake = FakePipewire(links={("a:out", "b:in")})
    linker = PwLinker(run=fake)
    linker.sync({("a:out", "b:in")})
    assert not [c for c in fake.calls if c and c[0] not in ("-l", "-o", "-i", "-d")]


def test_a_link_that_already_existed_is_adopted_and_cleaned_up_on_shutdown():
    fake = FakePipewire(links={("a:out", "b:in")})
    linker = PwLinker(run=fake)
    linker.sync({("a:out", "b:in")})
    linker.shutdown()
    assert fake.links == set()


def test_shutdown_removes_everything_it_made():
    fake = FakePipewire()
    linker = PwLinker(run=fake)
    linker.sync({("a:out", "b:in"), ("c:out", "d:in")})
    assert len(fake.links) == 2
    linker.shutdown()
    assert fake.links == set()


def test_available_reflects_whether_pw_link_works():
    assert PwLinker(run=lambda args: (0, "")).available()
    assert not PwLinker(run=lambda args: (127, "")).available()
    assert not PwLinker(binary="definitely-not-a-real-binary-xyz").available()


def test_null_linker_records_links_and_invents_ports():
    linker = NullLinker()
    assert linker.sync({("a", "b")}) == set()
    assert linker.links == {("a", "b")}
    assert linker.snapshot().outputs("node") == ["node:out_L", "node:out_R"]
    linker.shutdown()
    assert linker.links == set()


# ---------------------------------------------------------------- watching the graph instead of looking on a clock (0.11.5)
class _FakeProcess:
    def __init__(self, lines):
        import io
        self.stdout = io.StringIO("".join(line + "\n" for line in lines))
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.alive = False


def test_the_graph_watcher_raises_its_flag_when_pipewire_prints_a_change():
    import time as _time

    from sluice.linker import GraphWatcher
    started = []

    def popen(args, **_kw):
        started.append(args)
        return _FakeProcess(["+ a:out -> b:in"])

    watcher = GraphWatcher(popen=popen)
    assert watcher.start() and watcher.running()
    assert [a[1:] for a in started] == [list(c) for c in GraphWatcher.COMMANDS]
    assert watcher.take_changed()  # the first look, and the printed change
    _time.sleep(0.05)
    watcher.take_changed()
    assert not watcher.take_changed()  # nothing new since
    watcher.stop()
    assert not watcher.running()


def test_a_watcher_that_cannot_start_leaves_the_clock_in_charge():
    from sluice.linker import GraphWatcher

    def popen(*_a, **_k):
        raise OSError("no pw-link")

    watcher = GraphWatcher(popen=popen)
    assert not watcher.start() and not watcher.running()


def test_with_a_watcher_the_engine_checks_links_only_when_the_graph_changed():
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import RELINK_SAFETY, Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer

    class Watcher:
        def __init__(self):
            self.flag = False

        def running(self):
            return True

        def take_changed(self):
            flag, self.flag = self.flag, False
            return flag

    linker = NullLinker()
    linker.watcher = Watcher()
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), linker)
    engine.start()
    calls = []
    engine.apply_links = lambda: calls.append(1)
    engine._link_retry = False
    import time as _time
    now = _time.monotonic() + 1000.0  # the engine stamps its refreshes with the real clock
    for step in range(10):  # ten device refreshes, nothing changed: no look at the links
        now += engine.refresh_seconds
        engine.tick(now)
    assert calls == []
    linker.watcher.flag = True
    engine.tick(now + 0.1)
    assert calls == [1]
    engine._refreshes_since_link = RELINK_SAFETY  # and once in a while anyway, in case a change was missed
    engine.tick(_time.monotonic() + 5000.0)
    assert len(calls) == 2
    engine.shutdown()
