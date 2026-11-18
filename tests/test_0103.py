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
    bright_teal = lambda c: c.alpha() > 200 and c.green() > 220 and c.blue() > 200 and c.red() < 130  # noqa: E731
    red = lambda c: c.alpha() > 200 and c.red() > 200 and c.green() < 110 and c.blue() < 110  # noqa: E731
    assert _count(talking, bright_teal) > 3 * max(1, _count(idle, bright_teal))  # the closed, brighter ring
    assert _count(muted, red) > 20 and _count(idle, red) == 0 and _count(talking, red) == 0


def test_every_logo_size_exists_and_matches_the_svg(qapp):
    from pathlib import Path

    from PySide6.QtGui import QImage

    data = Path(__import__("sluice").__file__).parent / "data"
    svg = (data / "sluice.svg").read_text()
    assert "<title>Sluice</title>" in svg and "#2ee6c5" in svg and "Inter Bold" in svg
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
