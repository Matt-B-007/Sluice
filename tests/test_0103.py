# SPDX-License-Identifier: GPL-3.0-or-later
"""0.10.3: the PulseAudio connection guard survives a reconnect, and the calls leading up to a crash are remembered."""
from types import SimpleNamespace

import pytest

pulsectl = pytest.importorskip("pulsectl")
from pulsectl import _pulsectl as lib  # noqa: E402

from sluice import backend  # noqa: E402


def _fake_pulse(state):
    calls = []
    return SimpleNamespace(_ctx=object(), connected=True, closed=False, calls=calls,
                           source_list=lambda: calls.append("source_list") or [],
                           sink_input_list=lambda: calls.append("sink_input_list") or [],
                           close=lambda: calls.append("close"))


def test_the_connection_made_by_a_reconnect_is_guarded_too(monkeypatch):
    state = {"v": lib.PA_CONTEXT_READY}
    monkeypatch.setattr(lib.pa, "context_get_state", lambda ctx: state["v"], raising=False)
    made = []

    def factory(name):
        made.append(_fake_pulse(state))
        return made[-1]

    monkeypatch.setattr(pulsectl, "Pulse", factory)
    system = backend.PulseSystem(purge=False)
    assert isinstance(system._pulse, backend._LiveCheck)
    system._reconnect()
    assert isinstance(system._pulse, backend._LiveCheck), "the guard was lost after a reconnect"
    assert len(made) == 2
    state["v"] = lib.PA_CONTEXT_FAILED  # the server went away after the reconnect
    with pytest.raises(ConnectionError, match="Audio server shut down"):
        system._pulse.sink_input_list()
    assert "sink_input_list" not in made[1].calls  # the dead connection was never asked


def test_diagnose_connections_are_guarded_and_closed(monkeypatch):
    from sluice import diagnose

    state = {"v": lib.PA_CONTEXT_READY}
    monkeypatch.setattr(lib.pa, "context_get_state", lambda ctx: state["v"], raising=False)
    made = []

    def factory(name):
        fake = _fake_pulse(state)
        fake.server_info = lambda: SimpleNamespace(server_name="PipeWire", server_version="1", default_sink_name="out")
        fake.card_list = lambda: []
        made.append(fake)
        return fake

    monkeypatch.setattr(pulsectl, "Pulse", factory)
    assert diagnose._pulse()[0] is True and diagnose._cards()[0] is True
    assert all(f.calls[-1] == "close" for f in made) and len(made) == 2


def test_the_last_calls_are_remembered_with_how_they_went(monkeypatch):
    state = {"v": lib.PA_CONTEXT_READY}
    monkeypatch.setattr(lib.pa, "context_get_state", lambda ctx: state["v"], raising=False)
    backend._BREADCRUMBS.clear()
    guarded = backend._LiveCheck(_fake_pulse(state))
    guarded.source_list()
    guarded.sink_input_list()
    state["v"] = lib.PA_CONTEXT_FAILED
    with pytest.raises(ConnectionError):
        guarded.sink_input_list()
    calls = backend.recent_pulse_calls()
    assert [(c[0], c[2]) for c in calls] == [("source_list", "ok"), ("sink_input_list", "ok"), ("sink_input_list", "closed")]
    assert all(c[1] >= 0 for c in calls)


def test_only_the_last_few_calls_are_kept():
    backend._BREADCRUMBS.clear()
    for i in range(40):
        backend._BREADCRUMBS.append((f"call{i}", 0.0, "ok"))
    assert len(backend.recent_pulse_calls()) == backend._BREADCRUMBS.maxlen
    assert backend.recent_pulse_calls()[-1][0] == "call39"


# ------------------------------------------------------------------ the bug report's thread names and CPU split
def test_threads_are_listed_by_name_and_the_window_thread_is_marked():
    import threading
    import time as _t

    from sluice import efficiency

    stop = threading.Event()
    workers = [threading.Thread(target=stop.wait, name=f"sluice-test-worker-{i}", daemon=True) for i in range(3)]
    for w in workers:
        w.start()
    _t.sleep(0.05)
    try:
        table = efficiency.thread_table()
        names = {row[0]: row for row in table}
        assert names["sluice-test-worker"][1] == 3  # three numbered threads, one group
        assert sum(1 for row in table if row[3]) == 1  # exactly one window thread
        assert all(row[2] >= 0 for row in table)
        audio_id = workers[0].native_id
        marked = efficiency.thread_table(audio_thread=audio_id)
        assert [r for r in marked if r[4]][0][0] == "audio callback"
    finally:
        stop.set()


def test_the_cpu_split_adds_up_and_never_goes_negative():
    from sluice import efficiency

    table = [("window", 1, 4.0, True, False), ("audio callback", 1, 2.0, False, True), ("OpenBLAS", 8, 0.5, False, False)]
    split = efficiency.cpu_split(table, helper_cpu=1.5, total_cpu=10.0)
    assert split == {"window": 4.0, "audio": 2.0, "other_threads": 0.5, "ended_threads": 3.5, "helpers": 1.5}
    assert efficiency.cpu_split(table, 0.0, total_cpu=1.0)["ended_threads"] == 0.0  # the table is momentarily ahead: clamp


def test_the_report_section_shows_threads_the_split_and_the_last_audio_calls():
    from sluice import efficiency

    data = {"seconds": 120.0, "process_seconds": 130.0, "by_state": {"open": {"seconds": 120.0, "cpu_seconds": 6.0, "meter_updates": 100}},
            "cpu_seconds": 6.0, "cpu_split": {"window": 4.0, "audio": 2.0, "other_threads": 0.5, "ended_threads": 0.0, "helpers": 0.2},
            "thread_groups": [{"name": "OpenBLAS", "count": 8, "cpu_seconds": 0.5}], "thread_groups_more": 3,
            "pulse_recent": [["sink_input_list", 0.4, "ok"]], "rss_mb": 100.0, "threads": 43}
    text = efficiency.format_section(data)
    assert "Where the CPU went" in text and "audio callback" in text and "helper programs" in text
    assert "Threads by name" in text and "8 x OpenBLAS" in text and "3 more groups" in text
    assert "Last calls to the audio server" in text and "sink_input_list 0.4s before this (ok)" in text


def test_a_live_snapshot_carries_the_new_numbers():
    from sluice import efficiency

    data = efficiency.Tracker().snapshot()
    assert data["thread_groups"] and data["cpu_split"].keys() >= {"window", "audio", "other_threads", "ended_threads", "helpers"}
    assert data["process_seconds"] >= 0
    assert "pulse_recent" in data


# ------------------------------------------------------------------ the menus
@pytest.fixture
def window(qapp, tmp_path):
    from sluice import themes
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow

    system = MockSystem()
    engine = Engine(Mixer.demo(), system, NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    yield win
    win.shutdown()
    themes.set_current(themes.DARK)


def _all_items(menu, path=()):
    """[(path of menu names, text without & , action)] for every real item, going into submenus."""
    for action in menu.actions():
        text = action.text().replace("&", "")
        if action.isSeparator() or not text:
            continue
        if action.menu() is not None:
            yield from _all_items(action.menu(), path + (text,))
        elif not (action.isSeparator()):
            yield path, text, action


def test_every_menu_item_lives_in_exactly_one_place(window):
    seen = {}
    for bar_action in window.menuBar().actions():
        for path, text, action in _all_items(bar_action.menu(), (bar_action.text().replace("&", ""),)):
            if action.menu() is None and not action.isSeparator() and action.isEnabled():
                seen.setdefault(text, []).append(path)
    doubled = {t: p for t, p in seen.items() if len(p) > 1}
    assert not doubled, f"the same item is in two places: {doubled}"


def test_the_update_items_sit_together_in_settings(window):
    settings = next(a.menu() for a in window.menuBar().actions() if a.text().replace("&", "") == "Settings")
    items = [a.text().replace("&", "") for a in settings.actions() if a.text()]
    start = items.index("Updates")
    assert items[start + 1:start + 4] == ["Update automatically when a new version is found", "Check for updates…",
                                          "Go back to the previous version…"]
    help_menu = next(a.menu() for a in window.menuBar().actions() if a.text().replace("&", "") == "Help")
    assert not [a for a in help_menu.actions() if "update" in a.text().lower() and "new in" not in a.text().lower()]


def test_theme_is_in_view_and_open_folder_is_in_file(window):
    names = {a.text().replace("&", ""): a.menu() for a in window.menuBar().actions()}
    assert "Theme" in [a.text().replace("&", "") for a in names["View"].actions()]
    assert "Theme" not in [a.text().replace("&", "") for a in names["Settings"].actions()]
    folders = next(a.menu() for a in names["File"].actions() if a.text().replace("&", "") == "Open folder")
    assert [a.text().replace("&", "") for a in folders.actions()] == ["Settings", "Logs", "Themes"]


def test_a_dots_ending_means_a_dialog_and_toggles_have_none(window):
    for bar_action in window.menuBar().actions():
        for path, text, action in _all_items(bar_action.menu(), (bar_action.text().replace("&", ""),)):
            if action.isCheckable():
                assert not text.endswith("…"), f"{path} > {text}: a toggle opens nothing, so it has no dots"


def test_the_shortcut_list_matches_the_menus_and_nothing_is_missing(window):
    rows = dict((text, keys) for keys, text in window.shortcut_rows())
    assert rows["Mute my microphone"] and "M" in rows["Mute my microphone"]  # it was missing from the old hand-written list
    for bar_action in window.menuBar().actions():
        for _path, text, action in _all_items(bar_action.menu()):
            if action.shortcut().toString():
                assert text.rstrip("…") in rows, f"{text} has a shortcut but is not in the shortcuts list"
    assert len(window.shortcut_rows()) == len(set(k for k, _ in window.shortcut_rows()))  # no key listed twice


# ------------------------------------------------------------------ the logo and the tray states
def _count(pixmap, test):
    image = pixmap.toImage()
    return sum(1 for x in range(image.width()) for y in range(image.height()) if test(image.pixelColor(x, y)))


def test_the_tray_states_look_different_and_say_what_they_mean(qapp):
    from sluice.ui_icons import tray_pixmap

    idle, talking, muted = (tray_pixmap(s, 32) for s in ("idle", "talking", "muted"))
    assert idle.toImage() != talking.toImage() and idle.toImage() != muted.toImage() and talking.toImage() != muted.toImage()
    light_ring = lambda c: c.alpha() > 200 and abs(c.red() - 0x4f) < 25 and abs(c.green() - 0xb5) < 25 and abs(c.blue() - 0xaa) < 25  # noqa: E731
    red = lambda c: c.alpha() > 200 and c.red() > 200 and c.green() < 82 and c.blue() < 82  # noqa: E731  (the coral S is not this red)
    assert _count(talking, light_ring) > 3 * max(1, _count(idle, light_ring))  # the closed, lighter ring
    assert _count(muted, red) > 20 and _count(idle, red) == 0 and _count(talking, red) == 0
    assert idle.toImage().pixelColor(0, 0).alpha() == 0 and muted.toImage().pixelColor(0, 0).alpha() == 0  # no tile behind the logo
    solid = lambda c: c.alpha() > 200  # noqa: E731
    assert _count(muted, solid) < _count(idle, solid) + 150  # the logo itself is faded; only the badge is solid


def test_the_logo_is_transparent_with_the_teal_ring_and_coral_s(qapp):
    from pathlib import Path

    from PySide6.QtGui import QImage

    data = Path(__import__("sluice").__file__).parent / "data"
    svg = (data / "sluice.svg").read_text()
    assert "<rect" not in svg and "#0d9488" in svg and "#f0603f" in svg
    for size in (16, 128, 512):
        image = QImage(str(data / "png" / f"sluice-{size}.png"))
        assert image.pixelColor(0, 0).alpha() == 0  # transparent corner


def test_every_logo_size_exists_and_matches_the_svg(qapp):
    from pathlib import Path

    from PySide6.QtGui import QImage

    data = Path(__import__("sluice").__file__).parent / "data"
    svg = (data / "sluice.svg").read_text()
    assert "<title>Sluice</title>" in svg and "#0d9488" in svg and "Inter Bold" in svg
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        image = QImage(str(data / "png" / f"sluice-{size}.png"))
        assert (image.width(), image.height()) == (size, size)
    docs = QImage(str(Path(__import__("sluice").__file__).parent.parent / "docs" / "icon.png"))
    assert docs.width() == 256


# ------------------------------------------------------------------ no silent catch-all blocks
def test_every_catch_all_block_logs_or_says_why_it_stays_quiet():
    """A bare ``except Exception: pass`` hides real errors from the bug report. Each catch-all must do something with the error
    (log it, keep it, raise another) or carry a comment on one of its lines saying why silence is right."""
    import ast
    from pathlib import Path

    root = Path(backend.__file__).parent
    quiet = []
    for path in sorted(root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = ast.unparse(node.type) if node.type is not None else "BaseException"
            if "Exception" not in caught and caught != "BaseException":
                continue
            body_is_silent = all(isinstance(s, (ast.Pass, ast.Continue)) or
                                 (isinstance(s, ast.Return) and (s.value is None or isinstance(s.value, ast.Constant))) or
                                 (isinstance(s, ast.Assign) and isinstance(s.value, ast.Constant))
                                 for s in node.body)
            if not body_is_silent:
                continue
            end = max(getattr(s, "end_lineno", s.lineno) for s in node.body)
            if not any("#" in lines[i] for i in range(node.lineno - 1, end)):
                quiet.append(f"{path.name}:{node.lineno}")
    assert not quiet, f"catch-all blocks that hide the error without saying why: {quiet}"


def test_the_audio_thread_is_found_by_the_graph_that_runs_on_it():
    import threading

    from sluice.dsp import Graph

    graph = Graph(48000, ["monitor"])
    assert graph.audio_thread_id is None
    ids = []
    worker = threading.Thread(target=lambda: (graph.process({}, 64), ids.append(threading.get_native_id())))
    worker.start()
    worker.join()
    assert graph.audio_thread_id == ids[0] != threading.get_native_id()


def test_cpu_used_before_a_restart_in_the_same_process_is_not_counted():
    """Sluice restarts itself in the same process after an update, and the system keeps counting CPU (and the main thread) across that:
    the split of a run must start from zero, as the 0.10.3 report did not (it showed 29 minutes for a 19 minute run)."""
    import time as _t

    from sluice import efficiency

    end = _t.process_time() + 0.4
    while _t.process_time() < end:  # CPU the "program before the restart" used
        pass
    tracker = efficiency.Tracker()
    data = tracker.snapshot()
    assert sum(data["cpu_split"].values()) < 0.25, data["cpu_split"]
    window = [g for g in data["thread_groups"] if g["name"].startswith("window")][0]
    assert window["cpu_seconds"] < 0.25
    assert data["process_seconds"] < 5  # this run, not the age of the process


def test_the_hidden_window_flag_does_not_blame_the_audio_work():
    """The effects on a microphone run the same with the window hidden. In the 0.10.3 report 1.8 of the 2.4 percent of a core measured
    while hidden was the audio callback, and the 'should be close to idle' note blamed the program for it."""
    from sluice import efficiency

    def data(audio):
        return {"seconds": 960.0, "cpu_seconds": 23.0, "by_state": {"tray": {"seconds": 960.0, "cpu_seconds": 23.0, "meter_updates": 4800,
                                                                          "audio_cpu_seconds": audio}}}

    assert not [n for n in efficiency.flags(data(17.5)) if "hidden" in n]  # 2.4% of a core, 1.8% of it audio
    flagged = [n for n in efficiency.flags(data(2.0)) if "hidden" in n]  # the rest alone is over the limit
    assert flagged and "not counting the audio work" in flagged[0]
    text = efficiency.format_section({**data(17.5), "process_seconds": 960.0, "rss_mb": 100.0, "threads": 10})
    assert "audio callback 1.82%, the rest 0.57%" in text


def test_every_menu_item_has_its_own_alt_key_letter(qapp, tmp_path):
    """Two items with the same underlined letter make the Alt key cycle instead of choosing: 0.10.3 had four such menus."""
    import re

    from sluice import themes
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow

    mixer = Mixer.demo()
    mixer.recording_mix = True  # the third mix adds a "Mute Recording" item
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    problems = []

    def check(menu, path):
        letters = {}
        for action in menu.actions():
            if action.isSeparator() or not action.text():
                continue
            found = re.search(r"&(.)", action.text())
            name = action.text().replace("&", "")
            if not found:
                if not path.endswith(("Running in the background", "Audio buffer")):  # lists of choices: reached by arrow keys
                    problems.append(f"{path} > {name}: no Alt-key letter")
            else:
                letters.setdefault(found.group(1).lower(), []).append(name)
            if action.menu() is not None and name not in ("Theme", "Restore earlier settings"):  # those two are filled in when opened
                check(action.menu(), f"{path} > {name}")
        problems.extend(f"{path}: {key.upper()} is used by {names}" for key, names in letters.items() if len(names) > 1)

    try:
        for top in win.menuBar().actions():
            if top.menu().title() == "":
                continue
            check(top.menu(), top.text().replace("&", ""))
        assert not problems, problems
    finally:
        win.shutdown()
        themes.set_current(themes.DARK)


# ------------------------------------------------------------------ crash log rotation and maths libraries (0.10.4)
def _crash_file(tmp_path, monkeypatch, sessions, trace_in=()):
    """A crash.log with ``sessions`` session headers; sessions listed in ``trace_in`` (0 = oldest) have a trace."""
    from sluice import logs

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    (tmp_path / "sluice").mkdir(exist_ok=True)
    lines = []
    for i in range(sessions):
        lines.append(f"--- sluice session started 2026-11-{i + 1:02d} 10:00:00 (pid {100 + i}, Sluice 0.10.{i % 3}) ---")
        if i in trace_in:
            lines += ["Fatal Python error: Aborted", f"Thread 0x{i:04x} (most recent call first):", "  File x.py, line 1 in f"]
    logs.crash_path().write_text("\n".join(lines) + "\n")
    return logs


def test_old_crash_traces_move_to_the_archive_with_their_version(tmp_path, monkeypatch):
    logs = _crash_file(tmp_path, monkeypatch, 15, trace_in=(1, 3, 14))
    assert logs.rotate_crash_log(10) == 2   # the traces of sessions 1 and 3 are older than the last 10
    kept = logs.crash_path().read_text()
    assert kept.count("--- sluice session started") == 10 and "Thread 0x000e" in kept and "Thread 0x0001" not in kept
    archive = logs.crash_archive_path().read_text()
    assert "Thread 0x0001" in archive and "Thread 0x0003" in archive
    assert "(Sluice 0.10.1)" in archive and "(Sluice 0.10.0)" in archive and "started 2026-11-02" in archive
    assert logs.rotate_crash_log(10) == 0   # nothing more to move the second time


def test_the_report_shows_one_calm_line_when_only_old_traces_remain(tmp_path, monkeypatch):
    from sluice import report

    logs = _crash_file(tmp_path, monkeypatch, 15, trace_in=(1, 3))
    logs.rotate_crash_log(10)
    text = report.crash_summary(logs.crash_path().read_text(), None, logs.crash_archive_path().read_text())
    assert "No native crash in the last 10 session(s)." in text
    assert "started 2026-11-04" in text and "Sluice 0.10.0" in text and "crash-archive.log" in text
    assert "Fatal Python error" not in text   # the old trace itself is not in the report


def test_a_new_crash_still_shows_in_full(tmp_path, monkeypatch):
    from sluice import report

    logs = _crash_file(tmp_path, monkeypatch, 15, trace_in=(1, 14))
    logs.rotate_crash_log(10)
    text = report.crash_summary(logs.crash_path().read_text(), None, logs.crash_archive_path().read_text())
    assert "Fatal Python error: Aborted" in text and "Thread 0x000e" in text and "No native crash" not in text
    assert "crash-archive.log" in text   # and the archive is still mentioned


def test_the_crash_file_is_shortened_in_place_so_a_running_writer_keeps_working(tmp_path, monkeypatch):
    logs = _crash_file(tmp_path, monkeypatch, 15, trace_in=(1,))
    inode = logs.crash_path().stat().st_ino
    logs.rotate_crash_log(10)
    assert logs.crash_path().stat().st_ino == inode


def test_loaded_maths_libraries_are_named_in_the_report():
    from sluice import efficiency

    maps = ("7f00 r-xp 0 00:00 0 /usr/lib/libopenblas.so.0\n7f01 r-xp 0 00:00 0 /usr/lib/libgomp.so.1\n"
            "7f02 r--p 0 00:00 0 /usr/lib/libc.so.6\n7f03 r--p 0 00:00 0\n")
    found = efficiency.math_libraries(maps)
    assert any("OpenBLAS" in f and "libopenblas.so.0" in f for f in found) and any("OpenMP" in f for f in found)
    assert len(found) == 2 and efficiency.math_libraries("") == []
    text = efficiency.format_section({"seconds": 100.0, "math_libraries": found, "processor_threads": 32})
    assert "Maths libraries loaded" in text and "32 processor threads" in text and "OPENBLAS_NUM_THREADS=1" in text
    assert "none found" in efficiency.format_section({"seconds": 100.0, "math_libraries": []})
