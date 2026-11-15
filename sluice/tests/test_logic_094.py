# SPDX-License-Identifier: GPL-3.0-or-later
"""0.9.4 without a window: what changed before a dropout, the glitch marker, and the new report sections."""
import logging
import time

import pytest

from sluice import events, report
from sluice.audio_io import NullIO
from sluice.backend import Device, MockSystem, Stream
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer


@pytest.fixture
def rig():
    events.clear()
    system = MockSystem()
    system.add_demo_streams()
    io = NullIO(realtime=False)
    engine = Engine(Mixer.demo(), system, io, NullLinker())
    engine.start()
    engine._quiet_until = 0.0
    yield system, io, engine
    engine.shutdown()
    events.clear()


def messages(caplog):
    return [r.getMessage() for r in caplog.records]


# ------------------------------------------------------------------------------- the memory of recent events
def test_events_report_what_came_before_a_moment_nearest_first_and_ignore_old_ones():
    events.clear()
    events.record("old", now=100.0)
    events.record("input added: Cam Link 4K", now=198.0)
    events.record("links changed: 20 wanted (+2, -0)", now=199.5)
    found = events.before(200.0)
    assert [text for _, text in found] == ["input added: Cam Link 4K", "links changed: 20 wanted (+2, -0)"]  # oldest first
    text = events.describe(found)
    assert text.index("0.5 s before") < text.index("2.0 s before")
    assert events.likely_cause(found) == "input added: Cam Link 4K"   # a "links changed" entry is a consequence, so the real cause is named
    assert events.likely_cause([(0.5, "links changed: 20 wanted (+2, -0)")]) == "links changed: 20 wanted (+2, -0)"
    assert events.likely_cause(events.before(210.0, within=15.0)) is None   # nothing within 3 s of that moment
    events.clear()


# ------------------------------------------------------------------------------- the engine says what changed
def test_a_new_device_and_a_changed_default_are_named_in_the_log(rig, caplog):
    system, _io, engine = rig
    caplog.set_level(logging.INFO)
    system.sources.append(Device("alsa_input.usb-Elgato_Cam_Link_4K-02.analog-stereo", "Cam Link 4K"))
    system.default_src = system.sources[-1].name
    engine.refresh_devices()
    text = "\n".join(messages(caplog))
    assert "input added: Cam Link 4K" in text
    assert "default input changed from Blue Yeti Microphone to Cam Link 4K" in text
    caplog.clear()
    system.sources.pop()
    system.default_src = system.sources[0].name
    engine.refresh_devices()
    assert "input removed: Cam Link 4K" in "\n".join(messages(caplog))


def test_sluice_s_own_devices_are_not_announced_as_new(rig, caplog):
    system, _io, engine = rig
    caplog.set_level(logging.INFO)
    system.sinks.append(Device("sluice_ch_extra", "Sluice (Extra) output"))
    engine.refresh_devices()
    assert "output added" not in "\n".join(messages(caplog))


def test_an_app_starting_to_play_is_named_in_the_log(rig, caplog):
    system, _io, engine = rig
    caplog.set_level(logging.INFO)
    engine.apply_rules(time.monotonic())            # the first look only remembers what is playing
    assert "app started playing" not in "\n".join(messages(caplog))
    system.streams.append(Stream(9, "obs", "OBS Studio", system.sinks[0].name))
    engine.apply_rules(time.monotonic())
    assert "app started playing: OBS Studio" in "\n".join(messages(caplog))


# ------------------------------------------------------------------------------- dropouts say what came before
def test_a_dropout_right_after_a_change_says_so_and_does_not_suggest_a_bigger_buffer(rig, caplog):
    _system, io, engine = rig
    caplog.set_level(logging.INFO)
    events.clear()
    now = time.monotonic()
    events.record("input added: Cam Link 4K", now=now - 0.4)
    events.record("links changed: 20 wanted (+2, -0)", now=now - 0.1)   # Sluice relinking is a consequence, not the cause
    io.xruns = 1
    engine._pending_xruns, engine._pending_since = 1, now
    engine._log_dropouts(now + 0.1)
    text = "\n".join(messages(caplog))
    assert "what changed just before those dropouts" in text and "input added: Cam Link 4K" in text
    assert "a larger buffer does not prevent it" in text
    assert "Settings > Audio buffer > Large" not in text
    tip = engine.dropout_tooltip()
    assert "right after: input added: Cam Link 4K." in tip
    assert "choose a larger size in Settings > Audio buffer" not in tip


def test_a_dropout_with_nothing_before_it_keeps_the_old_advice(rig, caplog):
    _system, io, engine = rig
    caplog.set_level(logging.INFO)
    events.clear()
    now = time.monotonic()
    io.xruns = 1
    engine._pending_xruns, engine._pending_since = 1, now
    engine._log_dropouts(now + 0.1)
    text = "\n".join(messages(caplog))
    assert "Settings > Audio buffer > Large" in text
    assert "a larger buffer does not prevent it" not in text
    assert "choose a larger size in Settings > Audio buffer" in engine.dropout_tooltip()


def test_marking_a_glitch_writes_the_moment_and_what_was_going_on(rig, caplog):
    _system, _io, engine = rig
    caplog.set_level(logging.INFO)
    events.record("app started playing: Discord")
    answer = engine.mark_glitch()
    text = "\n".join(messages(caplog))
    assert answer.startswith("Marked.")
    assert "MARKED BY YOU" in text and "app started playing: Discord" in text


# ------------------------------------------------------------------------------- the report
REAL_TOP = """S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME
R   72   1024  48000   1.4ms   0.4us  0.07  0.00    2   F32LE 18 48000 alsa_input.usb-Elgato-00.multichannel-input
R  278   1024  48000   6.9us   0.5us  0.00  0.00   12   BGRA 2560x1440 kwin_wayland
R  265      0      0   5.2us 145.7us  0.00  0.01   20   BGRA 2560x1440  = obs
R  207      0      0   7.2us   7.2us  0.00  0.00 2252     F32P 2 48000  + sluice_ch_mic
R  231      0      0  10.0us   4.0us  0.00  0.00 2684     F32P 2 48000  + sluice_ch_chat
R  276      0      0   0.0us   0.0us  ???   ???     1                   + sluice
"""


def test_the_headline_counts_audio_only_and_names_video_and_sluice_devices_apart():
    out = report.top_errors(REAL_TOP)
    first, *rest = out.splitlines()
    assert "alsa_input.usb-Elgato-00.multichannel-input (2)" in first and "sluice (1)" in first
    assert "kwin_wayland" not in first and "obs" not in first and "sluice_ch_mic" not in first
    assert any("Video feeds" in line and "obs (20)" in line and "kwin_wayland (12)" in line for line in rest)
    assert any("Sluice's own virtual devices (2) show 4936 errors" in line for line in rest)


def test_the_dropout_timeline_keeps_the_lines_that_matter_and_says_whether_it_is_still_happening():
    lines = [
        "2026-11-11 10:22:34,752 INFO    sluice: === sluice 0.9.4 starting (pid 1) ===",
        "2026-11-11 15:22:46,757 WARNING sluice.engine: audio dropouts: 1 in the last 1 s (2 since Sluice started; 0 of those ...",
        "2026-11-11 15:22:46,758 WARNING sluice.engine: what changed just before those dropouts: 0.4 s before: input added: Cam Link 4K",
        "2026-11-11 15:23:00,000 INFO    sluice.engine: devices: 4 inputs",
        "2026-11-11 15:39:12,258 WARNING sluice.engine: audio dropouts: 1 in the last 1 s (5 since Sluice started; 0 of those ...",
    ]
    last = time.mktime(time.strptime("2026-11-11 15:39:12", "%Y-%m-%d %H:%M:%S"))
    out = report.dropout_timeline(lines, now=last + 600)
    assert "2 dropout event(s)" in out and "10 min before this report" in out and "not happening now" in out
    assert "input added: Cam Link 4K" in out and "devices: 4 inputs" not in out
    assert "still happening" in report.dropout_timeline(lines, now=last + 30)
    assert report.dropout_timeline(lines[:1]) == "No dropouts were logged in this session."


KERNEL = """2026-11-11T15:22:45-0800 host kernel: usb 9-4: new SuperSpeed USB device number 2 using xhci-pci-prom21
2026-11-11T15:22:45-0800 host kernel: usb 9-4: Product: Cam Link 4K
2026-11-11T15:22:45-0800 host kernel: usb 9-4: SerialNumber: A29YB412216YLJ
2026-11-11T15:22:45-0800 host kernel: usb 9-4: config 1 has an invalid interface number: 7 but max is 4
2026-11-11T15:23:13-0800 host kernel: usb 9-4: USB disconnect, device number 2
2026-11-11T15:24:00-0800 host kernel: wlan0: associated
"""


def test_usb_events_keep_connects_and_disconnects_and_drop_serial_numbers(monkeypatch):
    monkeypatch.setattr(report, "_run", lambda command, timeout=6.0: KERNEL)
    out = report.usb_events()
    assert "new SuperSpeed USB device number 2" in out and "USB disconnect" in out and "Product: Cam Link 4K" in out
    assert "SerialNumber" not in out and "wlan0" not in out and "invalid interface" not in out


def test_usb_events_say_so_when_the_kernel_log_cannot_be_read(monkeypatch):
    monkeypatch.setattr(report, "_run", lambda command, timeout=6.0: "(failed with exit code 1: not allowed)")
    out = report.usb_events()
    assert out.startswith("(failed") and "systemd-journal" in out


def test_the_report_hides_the_cookie_and_kernel_serial_numbers(monkeypatch):
    text = "Cookie: 5eff:759a\n  usb 9-4: SerialNumber: A29YB412216YLJ\n"
    clean = report.anonymize(text)
    assert "5eff:759a" not in clean and "A29YB412216YLJ" not in clean
    assert "Cookie: <cookie>" in clean and "SerialNumber: <serial>" in clean


def test_the_busy_programs_section_has_the_load_and_the_top_programs():
    out = report.busy_programs()
    assert "oad average" in out or "(" in out
    assert "Programs using the most CPU" in out or out.rstrip().endswith(")")
