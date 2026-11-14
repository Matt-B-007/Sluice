# SPDX-License-Identifier: GPL-3.0-or-later
"""0.9.7: dated bug reports, a visible error when saving fails, an 'already running' message that names the copy,
and a connection check before PulseAudio calls."""
import os
import re
import time
from types import SimpleNamespace

import pytest

from sluice import __version__, report
from sluice import __main__ as entry


# ------------------------------------------------------------------ report names
def test_the_default_report_name_has_the_version_and_the_time():
    name = report.default_name(time.mktime((2026, 11, 14, 10, 2, 0, 0, 0, -1)))
    assert name == f"sluice-report-{__version__}-2026-11-14-1002.txt"
    assert report.is_dated_name(name) and not report.is_dated_name(report.LATEST_NAME)
    assert not report.is_dated_name("sluice-report.txt") and not report.is_dated_name("mine.txt")


def test_the_report_says_which_sluice_made_it():
    assert re.search(rf"Created: .+ by Sluice {re.escape(__version__)}", report.build_report().splitlines()[3])


def test_a_dated_report_also_updates_latest_and_old_ones_are_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "build_report", lambda: "sluice bug report\nbody")
    for day in range(1, 15):
        p = tmp_path / f"sluice-report-0.9.7-2026-11-{day:02d}-0900.txt"
        p.write_text("old")
        os.utime(p, (1_700_000_000 + day * 100, 1_700_000_000 + day * 100))
    keep_me = tmp_path / "my-own-report.txt"
    keep_me.write_text("mine")
    written = report.write_report(tmp_path / "sluice-report-0.9.7-2026-11-20-0900.txt")
    dated = sorted(p.name for p in tmp_path.iterdir() if report.is_dated_name(p.name))
    assert len(dated) == report.KEEP_REPORTS and written.name in dated
    assert "2026-11-01-0900" not in " ".join(dated)  # the oldest went
    assert (tmp_path / report.LATEST_NAME).read_text().startswith("sluice bug report")
    assert keep_me.read_text() == "mine"  # a file you named is never touched


def test_a_report_with_your_own_name_is_written_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "build_report", lambda: "sluice bug report")
    report.write_report(tmp_path / "r.txt")
    assert [p.name for p in tmp_path.iterdir()] == ["r.txt"]


def test_with_no_path_the_report_goes_to_the_home_folder_with_a_dated_name(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "build_report", lambda: "sluice bug report")
    monkeypatch.setenv("HOME", str(tmp_path))
    path = report.write_report()
    assert path.parent == tmp_path and report.is_dated_name(path.name)


def test_the_command_line_says_why_a_report_could_not_be_written(tmp_path, monkeypatch, capsys):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(report, "build_report", boom)
    assert entry.main(["--report", str(tmp_path / "r.txt")]) == 1
    assert "could not write the report: RuntimeError: nope" in capsys.readouterr().err


def test_a_failed_save_from_the_menu_shows_a_message(qapp, tmp_path, monkeypatch):
    pytest.importorskip("pedalboard")
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow

    engine = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    try:
        target = str(tmp_path / "r.txt")
        offered = []
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: offered.append(a[2]) or (target, ""))
        shown = []
        monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: shown.append((title, text)))
        monkeypatch.setattr(report, "build_report", lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'x'")))
        win.save_report()
        assert report.is_dated_name(os.path.basename(offered[0]))
        assert shown and shown[0][0] == "Could not save the report"
        assert "ModuleNotFoundError" in shown[0][1] and target in shown[0][1]
    finally:
        win.shutdown()


# ------------------------------------------------------------------ already running
def test_the_lock_names_its_holder_and_a_second_start_does_not_wipe_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    first = entry._acquire_lock()
    assert first is not None
    assert entry._lock_holder() == (os.getpid(), __version__)
    assert entry._acquire_lock() is None
    assert entry._lock_holder() == (os.getpid(), __version__)
    first.close()


def test_the_already_running_message_names_the_copy_and_how_to_close_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    (tmp_path / "sluice.lock").write_text("81787 0.9.5\n")
    text = entry._already_running_message()
    assert "version 0.9.5" in text and f"this is {__version__}" in text
    assert "kill 81787" in text and "kill -9 81787" in text
    (tmp_path / "sluice.lock").write_text("")
    assert "pgrep -af sluice" in entry._already_running_message()


# ------------------------------------------------------------------ PulseAudio connection check
def test_a_dead_pulse_connection_raises_instead_of_calling_libpulse(monkeypatch):
    pytest.importorskip("pulsectl")
    from pulsectl import _pulsectl as lib

    from sluice.backend import _LiveCheck

    calls = []
    pulse = SimpleNamespace(_ctx=object(), connected=True, source_list=lambda: calls.append("list") or ["s"],
                            close=lambda: calls.append("close"))
    state = {"v": lib.PA_CONTEXT_READY}
    monkeypatch.setattr(lib.pa, "context_get_state", lambda ctx: state["v"], raising=False)
    guarded = _LiveCheck(pulse)
    assert guarded.source_list() == ["s"]
    state["v"] = lib.PA_CONTEXT_FAILED
    with pytest.raises(ConnectionError, match="Audio server shut down"):
        guarded.source_list()
    assert calls == ["list"]  # the dead connection was never asked
    guarded.close()  # closing is always allowed
    assert calls == ["list", "close"]
    pulse._ctx = None
    with pytest.raises(ConnectionError):
        guarded.source_list()


def test_a_test_double_without_a_context_is_passed_through():
    from sluice.backend import _LiveCheck

    guarded = _LiveCheck(SimpleNamespace(source_list=lambda: [1], loaded=[]))
    assert guarded.source_list() == [1] and guarded.loaded == []
