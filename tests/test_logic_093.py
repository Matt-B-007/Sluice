# SPDX-License-Identifier: GPL-3.0-or-later
"""0.9.3: the bug report keeps this session's log, dates the crash trace, and names who shows dropouts; Sluice notices a
session that did not end normally; restarts the person asked for bring the window back; the extra themes."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

from sluice import logs, reconnect, report, themes


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    yield tmp_path
    logs.shutdown()


# ----------------------------------------------------------------------------- report: repeated lines
def _line(second, text="audio dropouts: 1 in the last 1 s (5 since Sluice started)"):
    return f"2026-11-09 20:00:{second:02d},100 WARNING sluice.engine: {text}"


def test_a_long_run_of_similar_lines_is_collapsed_to_first_count_and_last():
    lines = [_line(s, f"audio dropouts: 1 in the last {s} s ({s} since Sluice started)") for s in range(10, 30)]
    out = report.collapse_repeats(lines)
    assert out[0] == lines[0] and out[-1] == lines[-1]
    assert len(out) == 3 and "18 similar lines" in out[1] and "20:00:10 to 20:00:29" in out[1]


def test_short_runs_are_left_alone():
    lines = [_line(1), _line(2), _line(3), "2026-11-09 20:00:04,000 INFO sluice: something else"]
    assert report.collapse_repeats(lines) == lines


def test_a_slow_block_inside_a_collapsed_run_is_kept():
    lines = [_line(s, f"dropouts (n {s}): Sluice's own work uses about 6% of a block, worst {s}%") for s in range(10, 20)]
    lines[5] = _line(15, "dropouts (n 15): Sluice's own work uses about 6% of a block, worst 149%")
    out = report.collapse_repeats(lines)
    assert any("worst 149%" in line for line in out) and "slow ones kept" in " ".join(out)


# ----------------------------------------------------------------------------- report: sessions
def _session(version, count=3):
    head = [f"2026-11-09 19:00:00,000 INFO    sluice: === sluice {version} starting (pid 1) ==="]
    return head + [f"2026-11-09 19:00:{i:02d},000 INFO    sluice: line {i} of {version}" for i in range(1, count + 1)]


def test_the_report_log_starts_at_the_current_session_and_ends_with_the_one_before():
    text = "\n".join(_session("0.9.0", 5) + _session("0.9.1", 5) + _session("0.9.2", 4))
    out = report.session_log(text)
    assert out.index("0.9.2 starting") < out.index("the end of the session before this one") < out.index("0.9.1 starting")
    assert "0.9.0" not in out  # older sessions are left out
    assert "2 earlier session(s)" in out


def test_the_current_session_is_cut_to_the_limit_and_says_so():
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet"]
    lines = _session("0.9.2", 0) + [f"2026-11-09 19:00:{i % 60:02d},000 INFO    sluice: {words[i % 10]} {words[(i * 3) % 10]} step{i}x" for i in range(100)]
    out = report.session_log("\n".join(lines), limit=10)
    assert "first 91 lines of this session not shown" in out and "step99x" in out and "step0x" not in out


def test_an_empty_log_is_reported_as_empty():
    assert report.session_log("") == "(empty)"


# ----------------------------------------------------------------------------- report: crash log
TRACE = ["Current thread 0x1 (most recent call first):", "  File \"x.py\", line 3 in f"]


def test_a_trace_is_labelled_with_the_session_it_belongs_to():
    text = "\n".join(["--- sluice session started 2026-11-09 19:50:10 (pid 7) ---"] + TRACE
                     + ["--- sluice session started 2026-11-09 21:00:00 (pid 8) ---"])
    out = report.crash_summary(text, modified=1.0)
    assert "the session that started 2026-11-09 19:50:10" in out and "x.py" in out and "File last written:" in out


def test_a_trace_before_any_session_line_says_its_time_is_unknown():
    out = report.crash_summary("\n".join(TRACE + ["--- sluice session started (pid 7) ---"]))
    assert "time unknown" in out


def test_a_file_with_only_session_lines_means_no_crash():
    out = report.crash_summary("--- sluice session started 2026-11-09 19:50:10 (pid 7) ---\n--- sluice session started 2026-11-09 20:00:00 (pid 8) ---\n")
    assert "No native crash recorded (2 session(s)" in out


def test_only_the_last_two_traces_are_shown_and_long_ones_are_cut():
    text = ""
    for n in range(4):
        text += f"--- sluice session started 2026-11-0{n + 1} 10:00:00 (pid {n}) ---\n" + "\n".join(f"  frame {n}-{i}" for i in range(60)) + "\n"
    out = report.crash_summary(text)
    assert "2026-11-04" in out and "2026-11-03" in out and "2026-11-02" not in out
    assert "(20 more lines)" in out


# ----------------------------------------------------------------------------- report: pw-top and hardware
PW_TOP = """S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME
S   55      0      0    ---     ---   ---   ---     0                  Midi-Bridge
R   72    512  48000 721.8us   1.0us  0.07  0.00   31   F32LE 18 48000 alsa_input.usb-Dev-00.input
R  211    512  48000  18.1us 627.8us  0.00  0.06   27                   + sluice
R  196      0      0   9.9us   2.1us  0.00  0.00    0     F32P 2 48000  + sluice_ch_mic
"""


def test_top_errors_names_the_programs_with_dropouts_most_first():
    out = report.top_errors(PW_TOP)
    assert out.index("alsa_input.usb-Dev-00.input (31)") < out.index("sluice (27)")
    assert "sluice_ch_mic" not in out


def test_top_errors_says_so_when_nothing_has_dropouts():
    assert report.top_errors(PW_TOP.replace("31", "0").replace("27", "0")) == "No audio program or device shows dropouts in this snapshot."
    assert "No audio program" in report.top_errors("")


def test_the_hardware_summary_never_fails_and_has_the_headings():
    out = report.hardware_summary()
    assert "CPU threads:" in out and "USB devices by controller" in out and "CPU frequency setting:" in out


# ----------------------------------------------------------------------------- running marker
def test_a_clean_session_leaves_no_marker_and_no_notice(state):
    logs.setup()
    assert not logs.running_path().exists()      # setting up the log alone does not mark a session
    logs.begin_session()
    assert logs.running_path().exists()
    logs.shutdown()
    assert not logs.running_path().exists()
    assert logs.previous_session_notice() is None


def test_a_marker_left_by_a_dead_process_is_reported(state):
    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text("999999999\n2026-11-09 19:50:10\n")
    notice = logs.previous_session_notice()
    assert notice and "did not end normally" in notice and "started 2026-11-09 19:50:10" in notice and "crash.log" in notice


def test_the_notice_is_logged_as_a_warning_at_start(state, caplog):
    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text("999999999\n2026-11-09 19:50:10\n")
    logs.setup()
    logs.begin_session()
    text = logs.log_path().read_text()
    assert "WARNING" in text and "did not end normally" in text


def test_a_marker_from_a_process_that_is_still_running_is_not_a_crash(state):
    logs.running_path().parent.mkdir(parents=True)
    other = os.getppid()  # a different process that is certainly alive
    if other == os.getpid():
        pytest.skip("no other live process to point at")
    logs.running_path().write_text(f"{other}\n2026-11-09 19:50:10\n")
    assert logs.previous_session_notice() is None


def test_a_marker_with_our_own_process_id_still_means_the_last_run_was_cut_short(state):
    """Restarts clear the marker first (see below), so a marker that carries our own id is a leftover (an id reused after a reboot)."""
    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text(f"{os.getpid()}\n2026-11-09 19:50:10\n")
    assert "did not end normally" in logs.previous_session_notice()


def test_restarting_clears_the_marker_first(state, monkeypatch):
    logs.mark_running()
    monkeypatch.setattr(os, "execv", lambda *a: None)
    reconnect.restart_self()
    assert not logs.running_path().exists()


def test_the_heartbeat_touches_the_marker_only_every_few_seconds(state, monkeypatch):
    logs.mark_running()
    old = time.time() - 100
    os.utime(logs.running_path(), (old, old))
    logs.heartbeat()                      # too soon after mark_running: nothing happens
    assert abs(logs.running_path().stat().st_mtime - old) < 1
    monkeypatch.setattr(logs, "_last_heartbeat", time.monotonic() - 10)
    logs.heartbeat()
    assert logs.running_path().stat().st_mtime > old + 50


def test_the_heartbeat_without_a_marker_does_nothing(state, monkeypatch):
    monkeypatch.setattr(logs, "_last_heartbeat", time.monotonic() - 10)
    logs.heartbeat()  # no file: no error


# ----------------------------------------------------------------------------- restarts
def test_a_restart_the_person_asked_for_shows_the_window(monkeypatch):
    monkeypatch.setattr(sys, "orig_argv", ["python", "-m", "sluice", "--minimized"], raising=False)
    assert reconnect.restart_command()[-1] == "--minimized"                       # an unattended restart stays minimized
    assert "--minimized" not in reconnect.restart_command(show_window=True)       # a button press brings the window back
    assert reconnect.restart_command(show_window=True)[-2:] == ["-m", "sluice"]


def test_show_window_leaves_other_arguments_alone(monkeypatch):
    monkeypatch.setattr(sys, "orig_argv", ["python", "-m", "sluice", "--debug", "--minimized"], raising=False)
    assert reconnect.restart_command(show_window=True)[-1] == "--debug"


# ----------------------------------------------------------------------------- themes
def test_the_three_new_built_in_themes_exist_and_are_readable():
    for theme_id, name, base in (("midnight", "Midnight Blue", "dark"), ("amber", "Amber Console", "dark"), ("paper", "Paper", "light")):
        theme = themes.BUILT_IN[theme_id]
        assert theme.name == name and theme.base == base
        assert themes.contrast_problems(theme.colors, True) == []
        assert set(theme.colors) == set(themes.TOKEN_NAMES)


def _write(folder, stem, colors, name=None, base="dark"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.json").write_text(json.dumps({"name": name or stem, "base": base, "colors": colors}))


def test_an_imported_copy_of_a_built_in_theme_is_not_listed_twice(tmp_path):
    folder = tmp_path / "themes"
    _write(folder, "midnight-blue", themes.MIDNIGHT, name="Midnight Blue")
    _write(folder, "mine", {**themes.DARK, "accent": "#ff0000"})
    names = [t.name for t in themes.custom_themes(folder)]
    assert names == ["mine"]
    assert len(themes.custom_themes(folder, hide_duplicates=False)) == 2


def test_a_built_in_theme_that_the_person_renamed_or_changed_is_their_own_and_stays_listed(tmp_path):
    folder = tmp_path / "themes"
    _write(folder, "my-night", themes.MIDNIGHT, name="My Night")                      # same colours, their name
    _write(folder, "midnight-blue-2", {**themes.MIDNIGHT, "accent": "#ff00aa"}, name="Midnight Blue")  # their name clashes, colours differ
    assert sorted(t.name for t in themes.custom_themes(folder)) == ["Midnight Blue", "My Night"]


def test_a_saved_choice_of_an_imported_copy_counts_as_the_built_in_theme(tmp_path):
    folder = tmp_path / "themes"
    _write(folder, "midnight-blue", themes.MIDNIGHT, name="Midnight Blue")
    assert themes.canonical_id("custom:midnight-blue", folder) == "midnight"
    assert themes.resolve("custom:midnight-blue", folder=folder).colors == themes.MIDNIGHT   # not Dark
    _write(folder, "mine", {**themes.DARK, "accent": "#ff0000"})
    assert themes.canonical_id("custom:mine", folder) == "custom:mine"
    assert themes.canonical_id("dark", folder) == "dark" and themes.canonical_id("custom:gone", folder) == "custom:gone"


THEME_PACK = Path(__file__).resolve().parent.parent / "themes"


@pytest.mark.skipif(not THEME_PACK.is_dir(), reason="the theme collection folder is not part of this checkout")
def test_every_theme_in_the_collection_imports_cleanly_and_is_readable():
    files = sorted(THEME_PACK.glob("*.json"))
    assert len(files) >= 30
    names = set()
    for path in files:
        theme, notes = themes.load_file(path)
        assert notes == [], f"{path.name} has entries Sluice ignores: {notes}"
        assert themes.contrast_problems(theme.colors, True) == [], path.name
        assert set(theme.colors) == set(themes.TOKEN_NAMES), path.name
        assert theme.name not in names, f"two themes are called {theme.name}"
        names.add(theme.name)
        assert (THEME_PACK / "previews" / f"{path.stem}.jpg").exists(), f"no preview for {path.name}"


def test_a_killed_process_that_has_not_been_cleared_away_counts_as_dead(state):
    import subprocess

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert logs._pid_alive(child.pid)
        child.kill()
        for _ in range(100):  # killed but not waited for: a zombie, still visible to os.kill
            if Path(f"/proc/{child.pid}/stat").exists() and Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z":
                break
            time.sleep(0.02)
        assert not logs._pid_alive(child.pid)
    finally:
        child.wait()


# ----------------------------------------------------------------------------- commands next to a running Sluice
def _other_marker():
    other = os.getppid()
    if other == os.getpid():
        pytest.skip("no other live process to point at")
    return other


def test_a_command_never_takes_over_or_removes_the_running_sluices_marker(state):
    from sluice.__main__ import main

    other = _other_marker()
    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text(f"{other}\n2026-11-09 19:50:10\n")
    assert main(["--report", str(state / "r.txt")]) == 0
    assert logs.running_path().read_text().startswith(f"{other}\n")        # still the running Sluice's
    main(["--diagnose"])
    assert logs.running_path().read_text().startswith(f"{other}\n")


def test_a_command_does_not_warn_about_the_last_session_either(state):
    from sluice.__main__ import main

    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text("999999999\n2026-11-09 19:50:10\n")     # a dead session's marker
    main(["--report", str(state / "r.txt")])
    assert "did not end normally" not in logs.log_path().read_text()
    assert logs.running_path().exists()                                      # left for the next real start to report


def test_a_command_adds_to_the_current_session_instead_of_starting_a_new_one(state):
    from sluice.__main__ import main

    logs.setup()
    logs.shutdown()
    main(["--report", str(state / "r.txt")])
    sessions = report.split_sessions(logs.log_path().read_text().splitlines())
    assert len(sessions) == 1 and "running a command" in "\n".join(sessions[0])
    assert logs.crash_path().read_text().count("--- sluice session started") == 1
    assert logs.crash_path().read_text().count("--- sluice command started") == 1


def test_a_trace_during_a_command_is_labelled_as_one():
    text = "--- sluice command started 2026-11-09 19:50:10 (pid 7) ---\n" + "\n".join(TRACE) + "\n"
    assert "during the command that started 2026-11-09 19:50:10" in report.crash_summary(text)


def test_only_the_process_that_owns_the_marker_removes_it(state):
    logs.mark_running()
    mine = logs.running_path().read_text()
    logs.running_path().write_text("1\n" + mine.split("\n", 1)[1])          # now somebody else's
    logs.mark_clean_exit()
    assert logs.running_path().exists()
    logs.running_path().write_text(mine)
    logs.mark_clean_exit()
    assert not logs.running_path().exists()


def test_a_second_start_hands_over_without_touching_the_running_sluices_marker(state, monkeypatch, capsys):
    from sluice import __main__ as entry
    from sluice import control

    other = _other_marker()
    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text(f"{other}\n2026-11-09 19:50:10\n")
    monkeypatch.setattr(entry, "_acquire_lock", lambda: None)        # the first Sluice holds the lock
    monkeypatch.setattr(control, "send", lambda *a, **k: {})         # "show your window"
    assert entry.main([]) == 0
    assert "already running" in capsys.readouterr().err
    assert logs.running_path().read_text().startswith(f"{other}\n")


def test_a_demo_never_marks_a_session(state, monkeypatch):
    import sluice.ui as ui
    from sluice import __main__ as entry

    other = _other_marker()
    logs.running_path().parent.mkdir(parents=True)
    logs.running_path().write_text(f"{other}\n2026-11-09 19:50:10\n")
    monkeypatch.setattr(ui.MainWindow, "show", lambda self: None)
    shot = state / "demo.png"
    entry.main(["--demo", "--screenshot", str(shot)])
    assert logs.running_path().read_text().startswith(f"{other}\n")


def test_a_real_session_is_marked_once_it_runs_and_unmarked_when_it_ends(state, monkeypatch):
    """The real path, with a stand-in for the audio server: the marker exists while the window runs and is gone after."""
    import sluice.ui as ui
    from sluice import __main__ as entry
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.linker import NullLinker

    class FakeJack(NullIO):
        client = object()    # what makes Sluice treat the backend as a real audio server

    seen = []
    monkeypatch.setattr(entry, "_real_parts", lambda: (MockSystem(), FakeJack(realtime=False), NullLinker()))
    monkeypatch.setattr(entry, "_acquire_lock", lambda: object())
    monkeypatch.setattr(ui.MainWindow, "show", lambda self: seen.append(logs.running_path().exists()))
    entry.main(["--screenshot", str(state / "real.png")])
    assert seen and all(seen)                      # marked by the time the window was shown
    assert not logs.running_path().exists()        # a normal exit removes it


def test_short_path_and_anonymize(tmp_path, monkeypatch):
    from sluice import logs, report

    home = tmp_path / "home" / "jordan"
    home.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
    monkeypatch.setenv("USER", "jordan")
    monkeypatch.setattr("platform.node", lambda: "Studio-PC")
    assert logs.short_path(home / ".local" / "state" / "sluice" / "sluice.log") == "~/.local/state/sluice/sluice.log"
    assert logs.short_path("/etc/hosts") == "/etc/hosts"
    raw = (
        f"Log: {home}/.local/state/sluice/sluice.log\n"
        "User Name: jordan\nHost Name: Studio-PC\n"
        "Server String: /run/user/1000/pulse/native\n"
        "alsa_input.usb-Elgato_Systems_Wave_XLR_Pro_AAY3H548118GKT-00.analog-stereo\n"
        "bluez_output.AA_BB_CC_DD_EE_FF.1\n"
        "/home/someoneelse/.config/x\n"
    )
    clean = report.anonymize(raw)
    for secret in ("jordan", "Studio-PC", "/run/user/1000", "AAY3H548118GKT", "AA_BB_CC_DD_EE_FF", "someoneelse"):
        assert secret not in clean
    assert "~/.local/state/sluice/sluice.log" in clean
    assert "Wave_XLR_Pro" in clean
