# SPDX-License-Identifier: GPL-3.0-or-later
"""0.9.2 without a window: dropout counting and logging, the voice level check, preset matching, the report additions."""
import logging
import re
import time

import numpy as np
import pytest

from sluice import presets, report, room
from sluice.audio_io import SLOW_BLOCK, AudioIO, JackIO, NullIO
from sluice.backend import MockSystem
from sluice.engine import XRUN_LOG_SECONDS, Engine
from sluice.linker import NullLinker
from sluice.model import STREAM, Effect, Mixer, new_effect_id

SR = 48000


@pytest.fixture
def rig():
    system = MockSystem()
    system.add_demo_streams()
    io = NullIO(realtime=False)
    engine = Engine(Mixer.demo(), system, io, NullLinker())
    engine.start()
    engine._quiet_until = 0.0
    yield io, engine
    engine.shutdown()


# ------------------------------------------------------------------- the status bar wording
def test_one_dropout_is_not_dropouts(rig):
    io, engine = rig
    assert "0 dropouts" in engine.status_text()
    io.xruns = 1
    assert engine.status_text().endswith("1 dropout")
    io.xruns = 2
    assert engine.status_text().endswith("2 dropouts")


def test_the_status_bar_only_names_a_culprit_when_there_is_something_to_go_on(rig):
    io, engine = rig
    io.xruns, io.xruns_ours = 2, 2
    assert "mostly" not in engine.status_text()  # two dropouts say nothing about who is to blame
    io.xruns, io.xruns_ours = 10, 9
    assert engine.status_text().endswith("10 dropouts · mostly Sluice")
    io.xruns, io.xruns_ours = 10, 1
    assert engine.status_text().endswith("· mostly elsewhere")
    io.xruns, io.xruns_ours = 10, 4
    assert "mostly" not in engine.status_text()  # a mixed picture is not called either way


def test_dropouts_are_counted_from_the_settled_point_for_both_numbers(rig):
    io, engine = rig
    io.xruns, io.xruns_ours = 6, 5
    engine._quiet_until = time.monotonic() + 100
    engine.tick(now=time.monotonic())  # still settling: nothing is counted yet
    assert engine.dropout_counts() == (0, 0)
    engine._quiet_until = 0.0
    io.xruns, io.xruns_ours = 9, 6
    engine.tick(now=1e9)
    assert engine.dropout_counts() == (3, 1)


def test_the_tooltip_explains_a_dropout_and_points_at_the_tools(rig):
    io, engine = rig
    text = engine.dropout_tooltip()
    assert "any other program" in text and "pw-top" not in text  # nothing to diagnose yet
    io.xruns, io.xruns_ours = 8, 1
    engine._load = (0.31, 0.62)
    text = engine.dropout_tooltip()
    assert "pw-top" in text and "ERR" in text and "Audio buffer" in text
    assert "31%" in text and "62%" in text
    assert "Of the 8, 1 came while Sluice was running late and 7 while it was keeping up" in text


# ------------------------------------------------------------------- one log line instead of hundreds
def dropout_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("audio dropouts")]


def test_a_burst_of_dropouts_is_one_log_line_per_ten_seconds(rig, caplog):
    io, engine = rig
    with caplog.at_level(logging.INFO, logger="sluice"):
        now = 1e9
        for step in range(40):  # 20 seconds of a dropout at every half-second tick
            io.xruns += 1
            engine.tick(now=now + step * 0.5)
    lines = dropout_lines(caplog)
    assert 1 <= len(lines) <= 3, lines  # it used to be 40
    logged = sum(int(re.search(r"dropouts: (\d+) in", line).group(1)) for line in lines)
    assert logged + engine._pending_xruns == 40  # nothing is lost: what is not logged yet is waiting for the next line
    assert "since Sluice started" in lines[0]


def test_the_first_dropouts_are_logged_straight_away_with_the_hint_once(rig, caplog):
    io, engine = rig
    with caplog.at_level(logging.INFO, logger="sluice"):
        io.xruns = 4
        engine.tick(now=5.0)
        assert len(dropout_lines(caplog)) == 1
        io.xruns = 9
        engine.tick(now=5.0 + XRUN_LOG_SECONDS + 1)
    assert len(dropout_lines(caplog)) == 2
    hints = [r for r in caplog.records if "pw-top" in r.getMessage() and "keep coming" in r.getMessage()]
    assert len(hints) == 1


def test_dropouts_not_yet_logged_are_written_when_sluice_stops(rig, caplog):
    io, engine = rig
    with caplog.at_level(logging.INFO, logger="sluice"):
        io.xruns = 2
        engine.tick(now=100.0)
        io.xruns = 5
        engine.tick(now=101.0)  # inside the ten seconds: held back
        assert len(dropout_lines(caplog)) == 1
        engine.shutdown()
    assert len(dropout_lines(caplog)) == 2 and "3 in the last" in dropout_lines(caplog)[1]
    engine.start()  # the fixture shuts down again


def test_the_log_line_says_who_was_slow(rig, caplog):
    io, engine = rig
    with caplog.at_level(logging.INFO, logger="sluice"):
        io.xruns, io.xruns_ours = 6, 5
        engine.tick(now=1.0)
    assert "5 of those while Sluice itself was running late" in dropout_lines(caplog)[0]


# ------------------------------------------------------------------- telling our dropouts from others'
class FakeGraph:
    live = True

    def __init__(self, spend=0.0):
        self.spend = spend

    def process(self, inputs, frames):
        end = time.perf_counter() + self.spend
        while time.perf_counter() < end:
            pass
        return {}


def make_jack(spend, blocksize=512):
    io = JackIO.__new__(JackIO)  # no JACK server needed: only the timing is under test
    io.blocksize, io.sample_rate = blocksize, SR
    io.xruns = io.xruns_ours = 0
    io.error = ""
    io._in, io._out = {}, {}
    io._graph = FakeGraph(spend)
    io._init_timing()
    return io


def test_a_dropout_after_a_slow_block_is_ours_and_after_a_quick_one_is_somebody_elses():
    period = 512 / SR
    slow = make_jack(period * 0.9)
    slow._process(512)
    slow._on_xrun(0.0)
    assert (slow.xruns, slow.xruns_ours) == (1, 1)
    quick = make_jack(0.0)
    quick._process(512)
    quick._on_xrun(0.0)
    assert (quick.xruns, quick.xruns_ours) == (1, 0)
    assert SLOW_BLOCK < 1


def test_a_dropout_during_a_block_that_has_run_long_is_ours_too():
    io = make_jack(0.0)
    io._process(512)  # a quick block just finished...
    io._in_block, io._block_start = True, time.perf_counter() - 2 * (512 / SR)  # ...and this one is still running, long overdue
    io._on_xrun(0.0)
    assert io.xruns_ours == 1


def test_the_load_is_the_share_of_a_block_sluice_uses_and_resets_when_read():
    period = 512 / SR
    io = make_jack(period * 0.5)
    for _ in range(5):
        io._process(512)
    average, worst = io.take_load()
    assert 0.45 < average < 0.9 and worst >= average
    assert io.take_load() == (0.0, 0.0)  # read and reset: the next reading is about the next stretch of time


def test_a_failing_block_still_counts_as_a_block_and_never_raises():
    io = make_jack(0.0)

    class Broken(FakeGraph):
        def process(self, inputs, frames):
            raise RuntimeError("boom")

    io._graph = Broken()
    io._process(512)
    assert "boom" in io.error and not io._in_block and io._blocks == 1


def test_backends_without_timing_report_nothing():
    assert NullIO().take_load() == (0.0, 0.0) and AudioIO.xruns_ours == 0


# ------------------------------------------------------------------- the voice level check
def speech(rms_db, seconds=6.5, pauses_db=-90.0):
    """Bursts of a 300 Hz tone with pauses between them, like phrases of speech, at the given average level."""
    t = np.arange(int(SR * seconds)) / SR
    amplitude = 10 ** (rms_db / 20) * np.sqrt(2)
    on = (t % 0.7) < 0.4
    tone = np.sin(2 * np.pi * 300 * t) * np.where(on, amplitude, 10 ** (pauses_db / 20))
    return np.stack((tone, tone)).astype(np.float32)


def test_a_quiet_voice_is_told_how_much_to_raise_the_microphone():
    result = room.analyse_voice(speech(-29.0), SR)
    assert result.status == "too_quiet" and result.usable
    assert result.change_db == pytest.approx(9.0, abs=0.6) and result.level_db == pytest.approx(-29.0, abs=0.6)
    assert "about 9 dB" in result.message and "Compressor" in result.message


def test_a_good_voice_level_needs_no_change():
    result = room.analyse_voice(speech(-20.0), SR)
    assert result.status == "ok" and not result.usable and result.change_db == 0.0
    assert "good level" in result.message


def test_a_loud_voice_is_told_to_come_down():
    result = room.analyse_voice(speech(-11.0), SR)
    assert result.status == "too_loud" and result.change_db < -1.5 and "Lower" in result.message


def test_one_click_or_cough_does_not_decide_how_much_room_the_voice_has():
    voice = speech(-29.0)
    voice[:, 30000:30010] = 0.9  # a single sharp spike near full scale
    result = room.analyse_voice(voice, SR)
    assert result.status == "too_quiet" and result.change_db == pytest.approx(9.0, abs=0.7)


def test_peaks_that_keep_coming_limit_how_much_louder_it_may_get():
    voice = speech(-29.0)
    for start in range(30000, voice.shape[1], int(0.7 * SR)):  # a sharp peak in every phrase
        voice[:, start:start + 480] = 0.8
    result = room.analyse_voice(voice, SR)
    assert result.status != "too_quiet" and result.change_db < 3  # raising it would clip those peaks


def test_silence_a_short_clip_and_steady_noise_are_not_mistaken_for_a_voice():
    assert room.analyse_voice(np.zeros((2, SR * 6), dtype=np.float32), SR).status == "silent"
    assert room.analyse_voice(speech(-20.0, seconds=1.0), SR).status == "silent"
    steady = (np.random.default_rng(1).standard_normal((2, SR * 6)) * 0.01).astype(np.float32)
    result = room.analyse_voice(steady, SR)
    assert result.status == "no_speech" and not result.usable and "normal voice" in result.message


def test_the_engine_measures_the_voice_from_the_microphone_before_its_effects(rig):
    io, engine = rig
    io.streamed_inputs = {"mic": speech(-29.0)}
    engine.measure_room_start("mic", room.VOICE_SECONDS)
    assert engine.measure_voice_finish("mic") is None  # still listening
    for _ in range(int(room.VOICE_SECONDS * SR / 512) + 2):
        io.process_once(512)
    result = engine.measure_voice_finish("mic")
    assert result.status == "too_quiet" and result.change_db == pytest.approx(9.0, abs=0.7)


def test_the_recent_peak_after_the_effects_rises_with_sound_and_falls_in_silence(rig):
    io, engine = rig
    assert engine.channel_recent_peak_db("nope") is None
    io.fixed_inputs = {"game": (0.5 * np.sin(2 * np.pi * 300 * np.arange(SR) / SR)).astype(np.float32)[None, :].repeat(2, 0)}
    for _ in range(30):
        io.process_once(512)
    loud = engine.channel_recent_peak_db("game")
    assert loud > -12
    io.fixed_inputs = {"game": np.zeros((2, 1), dtype=np.float32)}
    for _ in range(800):
        io.process_once(512)
    assert engine.channel_recent_peak_db("game") < loud - 6  # it falls away on its own


# ------------------------------------------------------------------- which preset is in use
def chain(*specs):
    return [Effect(new_effect_id(), "builtin", t, type=t, bypass=b, params=dict(p)) for t, b, p in specs]


def test_the_default_voice_chain_is_the_default_preset():
    mixer = Mixer.default()
    assert presets.active_name(mixer.channel("mic").effects) == "Noisy, echoing room (the default)"


def test_every_built_in_preset_is_recognised_after_it_is_applied(rig):
    _, engine = rig
    for name, (_description, entries) in presets.BUILT_IN.items():
        presets.apply(engine, "mic", entries)
        assert presets.active_name(engine.mixer.channel("mic").effects) == name


def test_changing_one_value_means_no_preset_matches_any_more(rig):
    _, engine = rig
    presets.apply(engine, "mic", presets.BUILT_IN["Light touch"][1])
    echo = next(e for e in engine.mixer.channel("mic").effects if e.type == "echo_reducer")
    engine.set_effect_param(echo.id, "reduction_db", 7.0)
    assert presets.active_name(engine.mixer.channel("mic").effects) is None


def test_your_own_presets_are_recognised_too():
    effects = chain(("echo_reducer", False, {"reverb_time": 0.5, "reduction_db": 8}),
                    ("noise_reducer", False, {"reduction_db": 10}))
    mine = {"My room": presets.snapshot(effects)}
    assert presets.active_name(effects, mine) == "My room"
    assert presets.active_name(effects, {}) is None


def test_a_missing_effect_counts_as_off_but_only_for_presets_that_turn_it_off():
    only_eq = chain(("eq", False, {"mid_db": -2}))
    assert presets.active_name(only_eq) == "Quiet room"  # the reducers are off in that preset: nothing to turn off
    nothing = chain(("gain", False, {}))
    assert presets.active_name(nothing) is None  # no effect of that preset is on the channel at all
    assert presets.active_name([]) is None


def test_values_never_changed_are_compared_by_their_defaults():
    echo = chain(("echo_reducer", False, {}))[0]  # no saved values: the defaults are 0.6 s and 9 dB
    assert presets.current_value(echo, "reverb_time") == 0.6
    assert presets.matches([echo, *chain(("noise_reducer", False, {}))], presets.BUILT_IN["Noisy, echoing room (the default)"][1])
    assert presets.current_value(echo, "no_such_key") is None


def test_the_noise_gate_threshold_never_decides_which_preset_is_in_use():
    entries = [{"type": "noise_gate", "bypass": False, "params": {"threshold_db": -30.0, "ratio": 4.0}}]
    gate = chain(("noise_gate", False, {"threshold_db": -55.0, "ratio": 4.0}))
    assert presets.matches(gate, entries)


def test_the_message_after_applying_names_what_was_set():
    assert presets.summary(presets.BUILT_IN["Light touch"][1]) == "Echo Reducer 5 dB, 0.4 s; Noise Reducer 6 dB"
    assert presets.summary(presets.BUILT_IN["Quiet room"][1]) == "Echo Reducer off; Noise Reducer off; EQ"
    assert presets.short_name("Noisy, echoing room (the default)") == "Noisy, echoing room"


# ------------------------------------------------------------------- the bug report
PW_TOP = """S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
S   30      0      0    0.0     0.0  ---   ---     0  Dummy-Driver
S   42    512  48000  1.0ms   0.2ms  0.01  0.02    0  alsa_output.usb
S   88    512  48000  1.0ms   0.9ms  0.01  0.09  435  sluice
S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
R   30      0      0    0.0     0.0  ---   ---     0  Dummy-Driver
R   42    512  48000  3.0ms   2.0ms  0.01  0.02    0  alsa_output.usb
R   88    512  48000  3.0ms   0.9ms  0.01  0.09  435  sluice
"""


def test_only_the_last_round_of_pw_top_is_kept():
    kept = report.last_pw_top_round(PW_TOP)
    assert kept.splitlines()[0].startswith("S   ID") and kept.count("alsa_output.usb") == 1 and "R   88" in kept
    assert "S   88" not in kept  # the first round is dropped
    assert report.last_pw_top_round("no header at all\nline") == "no header at all\nline"
    assert report.last_pw_top_round("") == "(no output)"
    assert len(report.last_pw_top_round("S   ID\n" + "x\n" * 500).splitlines()) <= 40


def test_the_report_has_the_buffer_size_and_who_is_erring(monkeypatch):
    seen = []

    def fake_run(command, timeout=6.0):
        seen.append(command[0])
        if command[0] == "pw-metadata":
            return "update: id:0 key:'clock.rate' value:'48000'\nupdate: id:0 key:'log.level' value:'2'\n" \
                   "update: id:0 key:'clock.force-quantum' value:'512'"
        if command[0] == "pw-top":
            return PW_TOP
        return "(not available: x)"

    monkeypatch.setattr(report, "_run", fake_run)
    text = report.build_report(log_lines=5)
    assert "pw-top" in seen and "pw-metadata" in seen
    assert "clock.force-quantum" in text and "log.level" not in text
    assert "ERR is dropouts per program" in text and "435  sluice" in text


def test_the_report_still_works_without_pipewire_tools(monkeypatch):
    monkeypatch.setattr(report, "_run", lambda command, timeout=6.0: f"(not available: {command[0]} is not installed)")
    text = report.build_report(log_lines=5)
    assert "pw-top is not installed" in text and "sluice bug report" in text


def test_the_crash_log_says_when_each_session_started(tmp_path, monkeypatch):
    from sluice import logs

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    logs.setup()
    try:
        header = logs.crash_path().read_text().splitlines()[0]
    finally:
        logs.shutdown()
    assert re.fullmatch(r"--- sluice session started \d{4}-\d\d-\d\d \d\d:\d\d:\d\d \(pid \d+\) ---", header), header


def test_a_third_mix_adds_no_surprises_to_the_status_text():
    mixer = Mixer.demo()
    mixer.set_recording_mix(True)
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    try:
        assert engine.status_text().endswith("0 dropouts") and STREAM in [m.kind for m in mixer.mixes]
    finally:
        engine.shutdown()
