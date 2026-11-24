# SPDX-License-Identifier: GPL-3.0-or-later
"""0.12.1: Quit really ends Sluice (also from the tray), a copy that does not answer can be replaced, and a new buffer size
is used at a restart."""
import subprocess
import sys
import textwrap

from pathlib import Path

import pytest

import sluice.__main__ as main

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("before", ["window open", "hidden in the tray"])
def test_quit_ends_the_program(before, tmp_path):
    """Before 0.12.1, Quit with the window hidden in the tray shut the audio down but left the process running (Qt ends a program
    only when its last *visible* window closes), holding the lock: every later start said "could not start"."""
    script = textwrap.dedent(f"""
        import os, sys, pathlib
        sys.path.insert(0, {str(ROOT)!r})
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        from sluice.audio_io import NullIO
        from sluice.backend import MockSystem
        from sluice.engine import Engine
        from sluice.linker import NullLinker
        from sluice.model import Mixer
        from sluice.ui import MainWindow
        mixer = Mixer.demo(); mixer.close_action = "tray"
        engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker()); engine.start()
        win = MainWindow(engine, pathlib.Path({str(tmp_path)!r}) / "config.json"); win.show()
        if {before == "hidden in the tray"!r}:
            QTimer.singleShot(100, win.hide)
        QTimer.singleShot(300, win.quit_app)
        QTimer.singleShot(5000, lambda: os._exit(3))  # still running: the bug
        app.exec()
        os._exit(0)
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]


def test_the_safety_net_is_armed_when_the_window_shuts_down(qapp, tmp_path):
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    called = []
    win.on_shut_down = lambda: called.append(True)
    win.shutdown()
    win.shutdown()  # once only
    assert called == [True]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def holder(runtime: Path, argv_tail=("-m", "sluice")) -> subprocess.Popen:
    """A process that holds Sluice's lock and never answers, looking like a Sluice in /proc."""
    code = textwrap.dedent(f"""
        import fcntl, os, time
        handle = open({str(runtime / 'sluice.lock')!r}, "a+")
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0); handle.truncate(); handle.write(f"{{os.getpid()}} 0.12.0\\n"); handle.flush()
        print("held", flush=True)
        time.sleep(60)
    """)
    process = subprocess.Popen([sys.executable, "-c", code, *argv_tail], stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == "held"
    return process


def test_a_copy_that_does_not_answer_is_closed_when_you_say_so(runtime):
    stuck = holder(runtime)
    try:
        assert main._acquire_lock() is None
        assert main._replace_stuck_copy(ask=lambda: False) is None and stuck.poll() is None  # "Cancel": left alone
        lock = main._replace_stuck_copy(ask=lambda: True)
        assert lock is not None
        stuck.wait(timeout=10)
        main._release_lock(lock)
    finally:
        stuck.kill()


def test_only_a_sluice_is_ever_offered_to_be_closed(runtime):
    other = holder(runtime, argv_tail=("not-sluice",))
    try:
        asked = []
        assert main._replace_stuck_copy(ask=lambda: asked.append(True) or True) is None
        assert asked == [] and other.poll() is None
    finally:
        other.kill()


def test_a_restart_uses_the_new_buffer_but_your_own_setting_wins():
    env = {}
    assert main._set_latency(512, env) == "512/48000"
    assert main._set_latency(1024, env) == "1024/48000"  # a restart keeps the environment: Sluice's own value is replaced
    yours = {"PIPEWIRE_LATENCY": "256/48000"}
    assert main._set_latency(1024, yours) == "256/48000" and yours["PIPEWIRE_LATENCY"] == "256/48000"


def test_a_new_buffer_size_shows_as_waiting_and_can_restart_now(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    engine.io.demo = False  # as with a real connection (demo mode saves nothing, so there is nothing to wait for)
    win = MainWindow(engine, tmp_path / "config.json")
    try:
        running = engine.io.blocksize
        other = 1024 if running != 1024 else 2048
        choice = {"text": "At the next start"}
        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
        monkeypatch.setattr(QMessageBox, "clickedButton",
                            lambda self: next(b for b in self.buttons() if b.text() == choice["text"]))
        restarts = []
        monkeypatch.setattr(win, "restart_for_buffer", lambda: restarts.append(True))
        win.set_buffer(other)
        assert engine.mixer.buffer_frames == other and restarts == []
        assert win.rate_label.text().endswith(f"{running} frames → {other} after restart")
        choice["text"] = "Restart now"
        win.set_buffer(running if running != other else 512)
        win.set_buffer(other)
        assert restarts == [True]
        win.set_buffer(running, ask=False)  # back to the running size: nothing waits
        assert "after restart" not in win.rate_label.text()
    finally:
        win.shutdown()




def test_the_safety_net_only_runs_in_the_sluice_command(monkeypatch):
    started = []
    monkeypatch.setattr("threading.Thread.start", lambda self: started.append(self.name))
    monkeypatch.setattr(main, "_AS_COMMAND", False)
    main._exit_safety_net(0.01)
    assert started == []  # inside the tests (or any other program): never armed, it would end that program
    monkeypatch.setattr(main, "_AS_COMMAND", True)
    main._exit_safety_net(0.01)
    assert started == ["sluice-exit-safety-net"]
