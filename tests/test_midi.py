# SPDX-License-Identifier: GPL-3.0-or-later
import os


from sluice.midi import (Binding, MidiEvent, MidiHub, encoder_delta, fader_to_db, load_bindings, parse,
                        request_for, save_bindings)
from sluice.model import MIN_DB


def test_parse_control_change_and_notes():
    assert parse(bytes([0xB0, 7, 100])) == [MidiEvent("cc", 1, 7, 100)]
    assert parse(bytes([0x93, 36, 90])) == [MidiEvent("on", 4, 36, 90)]
    assert parse(bytes([0x93, 36, 0]))[0].kind == "off"   # note-on with velocity 0 is a release
    assert parse(bytes([0x83, 36, 10]))[0].kind == "off"


def test_running_status_and_split_packets():
    p = __import__("sluice.midi", fromlist=["Parser"]).Parser()
    assert p.feed(bytes([0xB0, 7])) == []                 # incomplete
    assert p.feed(bytes([64, 7, 65])) == [MidiEvent("cc", 1, 7, 64), MidiEvent("cc", 1, 7, 65)]


def test_realtime_and_unrelated_messages_are_ignored():
    data = bytes([0xF8, 0xB0, 0xF8, 7, 0xFE, 50, 0xC0, 5, 0xE0, 1, 2, 0xF0, 1, 2, 3, 0xF7])
    assert parse(data) == [MidiEvent("cc", 1, 7, 50)]


def test_source_names():
    assert MidiEvent("cc", 2, 7, 1).source == "cc:2:7"
    assert MidiEvent("on", 1, 36, 9).source == "note:1:36" == MidiEvent("off", 1, 36, 0).source


def test_fader_taper():
    assert fader_to_db(127) == 0.0
    assert fader_to_db(0) == MIN_DB
    assert -13 < fader_to_db(64) < -11
    assert all(fader_to_db(v) <= fader_to_db(v + 1) for v in range(127))


def test_encoder_deltas():
    assert [encoder_delta(v) for v in (1, 3, 63, 127, 125, 65, 0, 64)] == [1, 3, 63, -1, -3, -63, 0, 0]


def test_requests_for_each_control_kind():
    fader = Binding("cc:1:7", "fader", "level", channel="music", mix="listen")
    assert request_for(fader, MidiEvent("cc", 1, 7, 127)) == {"cmd": "level", "channel": "music", "mix": "listen", "db": 0.0}
    knob = Binding("cc:1:8", "encoder", "master", mix="broadcast", step_db=2.0)
    assert request_for(knob, MidiEvent("cc", 1, 8, 127))["step"] == -2.0
    assert request_for(knob, MidiEvent("cc", 1, 8, 2))["step"] == 4.0
    assert request_for(knob, MidiEvent("cc", 1, 8, 0)) is None
    button = Binding("note:1:36", "button", "mute", channel="mic")
    assert request_for(button, MidiEvent("on", 1, 36, 100))["state"] == "toggle"
    assert request_for(button, MidiEvent("off", 1, 36, 0)) is None  # release does nothing
    cc_button = Binding("cc:1:20", "button", "master-mute", mix="listen")
    assert request_for(cc_button, MidiEvent("cc", 1, 20, 127)) is not None
    assert request_for(cc_button, MidiEvent("cc", 1, 20, 0)) is None
    assert request_for(fader, MidiEvent("on", 1, 7, 1)) is None  # a button press on a fader binding does nothing


def test_bindings_round_trip_and_bad_entries_are_skipped(tmp_path):
    path = tmp_path / "sub" / "controls.json"
    good = [Binding("cc:1:7", "fader", "level", channel="music"), Binding("note:1:36", "button", "mute", channel="mic", mix="listen")]
    save_bindings(path, good)
    assert load_bindings(path) == good
    path.write_text('{"bindings": [{"source": "x"}, 5, {"source": "cc:1:7", "control": "fader", "action": "level", "step_db": 1e9}, '
                    '{"source": "cc:1:9", "control": "fader", "action": "master", "mix": "listen"}]}')
    assert [b.source for b in load_bindings(path)] == ["cc:1:9"]
    path.write_text("not json")
    assert load_bindings(path) == []
    assert load_bindings(tmp_path / "missing.json") == []


class Rig:
    """Fake MIDI device files: pipes standing in for /dev/snd/midiC1D0."""

    def __init__(self, tmp_path):
        self.dir = tmp_path
        self.pipes = {}
        self.applied = []

    def plug(self, name):
        read, write = os.pipe()
        os.set_blocking(read, False)
        (self.dir / name).write_text("")
        self.pipes[str(self.dir / name)] = (read, write)

    def unplug(self, name):
        (self.dir / name).unlink()

    def hub(self, bindings):
        return MidiHub(lambda r: self.applied.append(r) or {"ok": True}, bindings,
                       pattern=str(self.dir / "midiC*D*"), opener=lambda path: self.pipes[path][0])

    def send(self, name, data):
        os.write(self.pipes[str(self.dir / name)][1], data)


def test_hub_reads_a_device_and_applies_bindings(tmp_path):
    rig = Rig(tmp_path)
    rig.plug("midiC1D0")
    hub = rig.hub([Binding("cc:1:7", "fader", "level", channel="music")])
    hub.rescan()
    assert len(hub.device_paths) == 1
    rig.send("midiC1D0", bytes([0xB0, 7, 127, 0xB0, 9, 5]))  # the second control has no binding
    assert hub.poll() == 2
    assert rig.applied == [{"cmd": "level", "channel": "music", "db": 0.0}]


def test_hub_notices_hotplug_and_unplug(tmp_path):
    rig = Rig(tmp_path)
    hub = rig.hub([])
    hub.rescan()
    assert hub.device_paths == []
    rig.plug("midiC2D0")
    hub.rescan()
    assert len(hub.device_paths) == 1
    rig.unplug("midiC2D0")
    hub.rescan()
    assert hub.device_paths == []


def test_hub_survives_a_device_that_vanishes_while_reading(tmp_path):
    rig = Rig(tmp_path)
    rig.plug("midiC1D0")
    hub = rig.hub([])
    hub.rescan()
    os.close(rig.pipes[str(tmp_path / "midiC1D0")][0])  # reading now fails with an OSError
    assert hub.poll() == 0
    assert hub.device_paths == []


def test_unreadable_device_is_reported_not_fatal(tmp_path):
    (tmp_path / "midiC1D0").write_text("")

    def deny(_path):
        raise PermissionError

    hub = MidiHub(lambda r: {"ok": True}, [], pattern=str(tmp_path / "midiC*D*"), opener=deny)
    hub.rescan()
    assert hub.device_paths == [] and len(hub.denied) == 1


def test_learn_captures_the_next_press_instead_of_applying_it(tmp_path):
    rig = Rig(tmp_path)
    rig.plug("midiC1D0")
    hub = rig.hub([Binding("cc:1:7", "fader", "level", channel="music")])
    hub.rescan()
    got = []
    hub.learn(got.append)
    rig.send("midiC1D0", bytes([0x90, 36, 0, 0x90, 36, 100, 0xB0, 7, 50]))  # release ignored, press learned, then normal
    hub.poll()
    assert got == [MidiEvent("on", 1, 36, 100)]
    assert len(rig.applied) == 1  # only the event after learning ended was applied
    assert hub.learning is None
