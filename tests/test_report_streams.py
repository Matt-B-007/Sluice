"""0.12.4: the bug report lists each app's stream and its device, memory over time, and says plainly when the kernel log had
no USB lines."""
from sluice import efficiency, report

SINKS = "52\tsluice_ch_game\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n60\tsluice_ch_chat\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n"
SOURCES = "188\tsluice_solo_mic_mic\tPipeWire\tfloat32le 1ch 48000Hz\tRUNNING\n201\tsluice_ch_game.monitor\tPipeWire\tfloat32le 2ch\tRUNNING\n"
INPUTS = """Sink Input #201
	Driver: PipeWire
	Sink: 52
	Properties:
		application.name = "Shred A Billion"
		application.process.binary = "shredabillion.exe"
Sink Input #235
	Sink: 60
	Properties:
		application.name = "WEBRTC VoiceEngine"
		application.process.binary = "Discord"
"""
OUTPUTS = """Source Output #90
	Source: 201
	Properties:
		application.name = "OBS"
		application.process.binary = "obs"
Source Output #91
	Source: 188
	Properties:
		application.process.binary = "obs"
"""


def test_apps_playing_are_listed_with_their_sink():
    text = report.stream_routes(INPUTS, SINKS, "Sink Input", "Sink", "playing")
    assert "201  Shred A Billion (shredabillion.exe) → sluice_ch_game" in text
    assert "235  WEBRTC VoiceEngine (Discord) → sluice_ch_chat" in text


def test_apps_recording_are_listed_with_their_source():
    text = report.stream_routes(OUTPUTS, SOURCES, "Source Output", "Source", "recording")
    assert "90  OBS → sluice_ch_game.monitor" in text and "91  obs → sluice_solo_mic_mic" in text


def test_no_streams_and_errors_are_said_plainly():
    assert report.stream_routes("", SINKS, "Sink Input", "Sink", "playing") == "No app is playing right now."
    assert report.stream_routes("(pactl not found)", "", "Sink Input", "Sink", "playing") == "(pactl not found)"


def test_memory_is_noted_every_quarter_hour_and_shown_hourly(monkeypatch):
    rss = iter(range(60000, 200000, 1024))
    monkeypatch.setattr(efficiency, "_status", lambda key: float(next(rss)) if key == "VmRSS" else None)
    start = 1000.0
    tracker = efficiency.Tracker(now=start)
    for minute in range(0, 3 * 60 + 1):
        tracker.sample(start + minute * 60.0)
    times = [t for t, _mb in tracker.rss_samples]
    assert times[0] >= 60 and all(b - a >= 15 * 60 - 1 for a, b in zip(times, times[1:]))
    shown = efficiency.memory_over_time(tracker.rss_samples)
    assert shown.startswith("0:01 ") and "1:01 " in shown and "2:01 " in shown and shown.count("·") == 3
    assert "over time: 0:01 " in efficiency.format_section(tracker.snapshot(now=start + 3 * 3600.0), "now")


def test_an_empty_kernel_log_means_no_usb_events(monkeypatch):
    calls = []

    def run(command, timeout=6.0):
        calls.append(command[0])
        return "-- No entries --" if command[0] == "journalctl" else "(dmesg: read kernel buffer failed: Operation not permitted)"
    monkeypatch.setattr(report, "_run", run)
    assert report.usb_events() == "No USB connect, disconnect or reset lines in the kernel log of the last hours."
    assert calls == ["journalctl"]  # it went on to dmesg and showed "Operation not permitted"


def test_dmesg_is_still_tried_when_the_journal_cannot_be_read(monkeypatch):
    monkeypatch.setattr(report, "_run", lambda command, timeout=6.0: "(journalctl not found)" if command[0] == "journalctl"
                        else "2026-11-26T10:00:00 usb 1-4: USB disconnect, device number 7")
    assert "USB disconnect" in report.usb_events()
