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
