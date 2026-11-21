# SPDX-License-Identifier: GPL-3.0-or-later
"""0.10.2: Sluice reports how much of the computer it uses itself, and the tray icon watches the microphone while the window is hidden."""
import json

import pytest

from sluice import efficiency, logs, report
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.efficiency import Tracker
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer


@pytest.fixture
def ui(qapp, tmp_path):
    from sluice.ui import MainWindow

    system = MockSystem()
    system.add_demo_streams()
    engine = Engine(Mixer.demo(), system, NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    yield win, system, engine
    win.shutdown()


def test_the_tracker_gives_cpu_and_time_to_the_state_the_window_was_in():
    t = Tracker(now=0.0)
    t.cpu_last = 0.0
    t.sample(now=10.0)
    t.set_state("tray", now=10.0)
    for _ in range(5):
        t.meter_tick()
    t.sample(now=40.0)
    assert t.seconds["open"] == pytest.approx(10.0) and t.seconds["tray"] == pytest.approx(30.0)
    assert t.ticks == {"open": 0, "tray": 5, "background": 0}
    assert t.snapshot(now=40.0)["by_state"]["tray"]["meter_updates"] == 5


def test_an_unknown_state_is_ignored():
    t = Tracker(now=0.0)
    t.set_state("nonsense", now=1.0)
    assert t.state == "open"


def test_a_snapshot_has_numbers_only(ui):
    win, _, engine = ui
    data = win.tracker.snapshot()
    text = json.dumps(data)
    assert data["channels"] == len(engine.mixer.channels) and data["mixes"] == len(engine.mixer.mixes)
    assert data["rss_mb"] is None or data["rss_mb"] > 0
    for channel in engine.mixer.channels:  # no names of channels, devices or apps
        assert channel.label not in text
    assert "dsp" in data and "audio_client" in data


def test_the_flags_point_at_wasteful_behaviour():
    base = {"seconds": 600.0, "cpu_seconds": 6.0, "by_state": {"open": {"seconds": 600.0, "cpu_seconds": 6.0, "meter_updates": 18000}},
            "audio_load_samples": 100, "audio_load_average": 0.05, "audio_load_worst": 0.2, "rss_mb": 150.0, "dsp": "rust"}
    assert efficiency.flags(base) == []
    assert efficiency.summary_line(base).endswith("no flags.")
    heavy = dict(base, audio_load_average=0.4, audio_load_worst=0.95, rss_mb=700.0, rss_baseline_mb=300.0, dsp="python")
    heavy["by_state"] = {"open": {"seconds": 100.0, "cpu_seconds": 30.0, "meter_updates": 3000},
                         "tray": {"seconds": 300.0, "cpu_seconds": 9.0, "meter_updates": 6000}}
    notes = " ".join(efficiency.flags(heavy))
    for words in ("on average", "at worst", "window was open", "hidden (tray)", "meter updates a second", "700 MB", "grew by", "Rust engine"):
        assert words in notes, words
    assert "flags." in efficiency.summary_line(heavy)


def test_a_short_stay_in_a_state_raises_no_flag():
    data = {"seconds": 5.0, "cpu_seconds": 4.0, "by_state": {"tray": {"seconds": 5.0, "cpu_seconds": 4.0, "meter_updates": 500}}}
    assert efficiency.flags(data) == []


def test_the_section_reads_clearly_without_data_and_with_it(ui):
    assert "no measurements" in efficiency.format_section(None)
    assert "no measurements" in efficiency.summary_line(None)
    win, _, _ = ui
    win.tracker.sample()
    text = efficiency.format_section(win.tracker.snapshot(), "This session (live).")
    for heading in ("CPU", "Memory", "Audio work", "What was switched on", "Flags"):
        assert heading in text
    assert "not measured: that would put a clock on the audio thread" in text


def test_the_bug_report_has_the_summary_on_top_and_the_section(ui, monkeypatch):
    win, _, _ = ui
    monkeypatch.setattr(report, "_run", lambda *a, **k: "")
    monkeypatch.setattr(report, "hardware_summary", lambda: "")
    monkeypatch.setattr(report, "usb_events", lambda limit=30: "")
    text = report.build_report()
    head = text.split("\n=====")[0]
    assert "Efficiency:" in head
    assert "===== Sluice's own efficiency" in text and "This session (live)." in text


def test_a_terminal_report_reads_the_snapshot_a_session_left(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    efficiency.activate(None)
    assert efficiency.for_report()[0] is None
    (tmp_path / "sluice").mkdir()
    (tmp_path / "sluice" / efficiency.SNAPSHOT_NAME).write_text(json.dumps({"taken": 0, "seconds": 120.0, "cpu_seconds": 1.2, "pid": 1}))
    data, where = efficiency.for_report()
    assert data["seconds"] == 120.0 and "last Sluice session" in where


def test_a_session_only_writes_its_snapshot_while_its_marker_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    t = Tracker()
    t.write()
    assert not efficiency.snapshot_path().exists()  # no marker: a test or a stray process leaves the real file alone
    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text("1\n")
    t.write()
    assert json.loads(efficiency.snapshot_path().read_text())["pid"] > 0


def test_the_engine_counts_the_audio_load_over_the_whole_session(ui):
    _win, _, engine = ui
    engine.io.take_load = lambda: (0.1, 0.3)
    engine.tick()
    engine.io.take_load = lambda: (0.3, 0.2)
    engine.tick()
    average, worst, blocks = engine.load_stats()
    assert blocks == 2 and average == pytest.approx(0.2) and worst == pytest.approx(0.3)


# ------------------------------------------------------------------ the tray watcher
@pytest.fixture
def tray(monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))


def test_the_tray_watcher_runs_only_while_the_window_is_hidden_in_the_tray(ui, tray):
    win, _, engine = ui
    win.show()
    win.close_actions["tray"].trigger()
    assert win.meter_timer.isActive() and not win.tray_timer.isActive()  # the window shows: the meters do the job
    win.hide()
    assert not win.meter_timer.isActive() and win.tray_timer.isActive() and win.tray_timer.interval() == 200
    assert win.tracker.state == "tray"
    win._tray_mic.trigger()  # muted: the icon is fixed, nothing to watch
    assert not win.tray_timer.isActive()
    win._tray_mic.trigger()
    assert win.tray_timer.isActive()
    win.show()
    assert not win.tray_timer.isActive() and win.tracker.state == "open"


def test_the_tray_watcher_lights_the_icon_and_costs_nothing_without_a_tray(ui, tray):
    win, _, engine = ui
    win.close_actions["tray"].trigger()
    win.hide()
    win._window_state_changed()
    engine.levels = lambda: {}
    engine.mic_level = 0.4
    win._tray_tick()
    assert win._tray_state == "talking" and win.tracker.ticks["tray"] == 1
    win.close_actions["quit"].trigger()
    assert not win.tray_timer.isActive()


def test_without_a_tray_a_hidden_window_runs_no_timer_at_all(ui):
    win, _, _ = ui
    win.show()
    win.showMinimized()
    win._set_meters_running(False)
    assert not win.meter_timer.isActive() and not win.tray_timer.isActive() and win.tracker.state == "background"


# ------------------------------------------------------------------ the first-close question
def test_the_first_close_asks_once_and_a_tray_choice_is_kept(ui, tray, monkeypatch):
    win, _, engine = ui
    win.show()
    asked = []
    monkeypatch.setattr(win, "_ask_close_choice", lambda: asked.append(1) or win.set_close_action("tray") or True)
    win.close()
    assert asked == [1] and engine.mixer.close_action == "tray" and not win._closed and not win.isVisible()
    win.bring_to_front()
    win.close()
    assert asked == [1]  # never again


def test_cancelling_the_question_keeps_the_window(ui, tray, monkeypatch):
    win, _, engine = ui
    win.show()
    monkeypatch.setattr(win, "_ask_close_choice", lambda: False)
    win.close()
    assert win.isVisible() and not win._closed and engine.mixer.close_action == "quit"


def test_the_question_is_not_asked_when_it_cannot_matter(ui, tray):
    win, _, engine = ui
    win.show()
    assert win._should_ask_close_choice(False)
    assert not win._should_ask_close_choice(True)  # logging out
    win._quitting = True
    assert not win._should_ask_close_choice(False)  # File > Quit
    win._quitting = False
    win.close_actions["minimize"].trigger()
    assert not win._should_ask_close_choice(False)  # they have chosen already


def test_no_question_without_a_tray(ui):
    win, _, _ = ui
    win.show()
    assert not win._should_ask_close_choice(False)


def test_the_question_has_the_buttons_and_the_checkbox_decides_if_quit_is_remembered(ui, tray, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    win, _, engine = ui
    win.show()
    picked = {}

    def fake_exec(self):
        picked["texts"] = [b.text() for b in self.buttons()]
        self._chosen = next(b for b in self.buttons() if b.text() == picked["want"])
        if picked.get("tick"):
            self.checkBox().setChecked(True)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self._chosen)
    picked["want"] = "Quit Sluice"
    assert win._ask_close_choice() is True and engine.mixer.close_action == "quit" and "closechoice" not in engine.mixer.hints_seen
    assert sorted(picked["texts"]) == ["Cancel", "Keep running in the tray", "Quit Sluice"]
    picked["tick"] = True
    assert win._ask_close_choice() is True and "closechoice" in engine.mixer.hints_seen
    picked["want"] = "Cancel"
    assert win._ask_close_choice() is False
    picked["want"] = "Keep running in the tray"
    assert win._ask_close_choice() is True and engine.mixer.close_action == "tray"


def test_starting_in_the_tray_stops_the_meters_and_starts_the_watcher(ui, tray):
    win, _, engine = ui
    engine.mixer.close_action = "tray"
    assert win.meter_timer.isActive()
    win.start_minimized()
    assert win.tray_active and not win.meter_timer.isActive() and win.tray_timer.isActive() and win.tracker.state == "tray"


# ------------------------------------------------------------------ helper programs
def test_helper_programs_are_counted_and_their_cpu_is_part_of_the_total(ui):
    win, _, _ = ui
    before = win.tracker.snapshot()
    efficiency.helper_launched(0.02)
    efficiency.helper_launched(0.03)
    after = win.tracker.snapshot()
    assert after["helper_launches"] - before["helper_launches"] == 2
    assert after["helper_seconds"] - before["helper_seconds"] == pytest.approx(0.05, abs=0.011)
    later = win.tracker.snapshot(now=win.tracker.started + 60.0)  # a minute in, so the section has something to say
    assert after["helper_cpu_seconds"] >= 0.0 and "helper programs (pw-link)" in efficiency.format_section(later)


def test_the_real_linker_reports_each_program_it_starts(monkeypatch):
    from sluice import linker

    seen = []
    monkeypatch.setattr(efficiency, "helper_launched", lambda seconds: seen.append(seconds))

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(linker.subprocess, "run", lambda *a, **k: Done())
    linker.PwLinker().snapshot()  # two programs: outputs and inputs
    assert len(seen) == 2 and all(s >= 0 for s in seen)
    monkeypatch.setattr(linker.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("missing")))
    linker.PwLinker().available()
    assert len(seen) == 3  # a program that cannot start counts too


def test_frequent_helper_launches_are_flagged_and_a_normal_rate_is_not():
    base = {"seconds": 600.0, "cpu_seconds": 12.0, "by_state": {}, "helper_cpu_seconds": 1.0}
    assert efficiency.flags(dict(base, helper_launches=40)) == []  # 4 a minute
    notes = " ".join(efficiency.flags(dict(base, helper_launches=600)))
    assert "helper programs (pw-link) started a minute" in notes
    heavy = " ".join(efficiency.flags(dict(base, helper_launches=10, helper_cpu_seconds=8.0)))
    assert "Helper programs used 67%" in heavy


def test_sluice_keeps_the_maths_libraries_to_one_worker_thread():
    """0.11.7: OpenBLAS started a thread per processor thread (31 idle ones on a 32-thread Ryzen). A value set by hand is kept."""
    import os
    import subprocess
    import sys
    code = "import sluice, os; print(os.environ['OPENBLAS_NUM_THREADS'], os.environ['OMP_NUM_THREADS'])"
    env = {k: v for k, v in os.environ.items() if k not in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}
    assert subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.split() == ["1", "1"]
    env["OPENBLAS_NUM_THREADS"] = "4"
    assert subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.split() == ["4", "1"]
