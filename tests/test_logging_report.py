# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import sys
import threading

import pytest

from sluice import logs, report
from sluice.__main__ import main
from sluice.audio_io import NullIO
from sluice.backend import MockSystem, Stream
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Effect, Mixer, new_effect_id


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Point the log, crash log and config at a temp folder, and undo all global hooks afterwards."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    yield tmp_path
    logs.shutdown()
    logging.getLogger("sluice").propagate = True


def read_log() -> str:
    for handler in logging.getLogger("sluice").handlers:
        handler.flush()
    return logs.log_path().read_text()


# ------------------------------------------------------------------------- logging
def test_setup_creates_the_log_with_a_session_header(state):
    path = logs.setup()
    assert path == state / "state" / "sluice" / "sluice.log"
    text = read_log()
    assert "sluice 0." in text and "starting" in text
    assert "python 3." in text
    assert "pedalboard" in text


def test_messages_are_logged_and_debug_is_off_by_default(state):
    logs.setup()
    log = logging.getLogger("sluice.test")
    log.info("hello info")
    log.debug("hello debug")
    text = read_log()
    assert "hello info" in text
    assert "hello debug" not in text


def test_debug_flag_adds_debug_messages(state):
    logs.setup(debug=True)
    logging.getLogger("sluice.test").debug("hello debug")
    assert "hello debug" in read_log()


def test_calling_setup_twice_does_not_duplicate_lines(state):
    logs.setup()
    logs.setup()
    logging.getLogger("sluice.test").info("only once please")
    assert read_log().count("only once please") == 1


def test_an_uncaught_exception_is_logged_with_its_traceback(state, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored after the test
    logs.setup()
    try:
        raise ValueError("kaboom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    text = read_log()
    assert "Uncaught exception" in text and "ValueError: kaboom" in text and "Traceback" in text


def test_an_exception_in_a_thread_is_logged(state, monkeypatch):
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    logs.setup()

    def explode():
        raise RuntimeError("thread boom")

    thread = threading.Thread(target=explode, name="worker-x")
    thread.start()
    thread.join()
    text = read_log()
    assert "worker-x" in text and "thread boom" in text


def test_the_native_crash_log_is_created(state):
    logs.setup()
    assert "session started" in logs.crash_path().read_text()


def test_setup_survives_an_unwritable_state_folder(tmp_path, monkeypatch):
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, not a folder")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    try:
        assert logs.setup() is None  # no log file, but no crash either
        logging.getLogger("sluice.test").info("still fine")
    finally:
        logs.shutdown()
        logging.getLogger("sluice").propagate = True


# -------------------------------------------------------------- what the engine logs
@pytest.fixture
def rig():
    system = MockSystem()
    system.add_demo_streams()
    io = NullIO(realtime=False)
    engine = Engine(Mixer.demo(), system, io, NullLinker())
    yield system, io, engine
    engine.shutdown()


def test_engine_logs_its_lifecycle_and_app_moves(rig, caplog):
    system, io, engine = rig
    with caplog.at_level(logging.INFO, logger="sluice"):
        engine.start()
        engine.assign_app("firefox", "chat")
        engine.add_channel("Karaoke")
        engine.remove_channel("karaoke")
    text = caplog.text
    assert "starting: channels" in text and "started" in text
    assert "moved Spotify" in text and "sluice_ch_music" in text
    assert "app 'firefox' assigned to channel 'chat'" in text
    assert "channel 'karaoke' added" in text and "channel 'karaoke' removed" in text
    assert "links:" in text


def test_engine_logs_effect_problems(rig, caplog):
    _, _, engine = rig
    engine.start()
    with caplog.at_level(logging.INFO, logger="sluice"):
        engine.add_effect("chat", Effect(new_effect_id(), "vst3", "Gone", path="/no/such.vst3"))
        engine.add_effect("chat", Effect(new_effect_id(), "builtin", "Gain", type="gain"))
    assert "could not load" in caplog.text and "not found" in caplog.text
    assert "effect 'Gain' (builtin) added" in caplog.text


def test_engine_logs_dropouts_and_audio_errors_once(rig, caplog):
    _, io, engine = rig
    engine.start()
    with caplog.at_level(logging.INFO, logger="sluice"):
        io.xruns = 3
        engine.tick(now=1e9)
        engine.tick(now=1e9 + 1)  # no new dropouts: nothing more to say
        io.error = "callback failed"
        engine.take_errors()
        io.error = "callback failed"
        engine.take_errors()  # same error again: logged only once
    assert caplog.text.count("audio dropouts") == 1 and "3 new" in caplog.text
    assert caplog.text.count("callback failed") == 1


def test_engine_logs_backend_errors_and_failed_moves(rig, caplog):
    system, _, engine = rig
    engine.start()
    system.move_error = RuntimeError("sink busy")
    system.streams.append(Stream(9, "spotify", "Spotify", system.sinks[0].name))
    with caplog.at_level(logging.WARNING, logger="sluice"):
        engine.apply_rules(1e9)
    assert "Could not move Spotify" in caplog.text


# ------------------------------------------------------------------------- report
def test_sluice_blocks_keeps_only_sluice_ports():
    text = (
        "firefox:out_FL\n  |-> speakers:playback_FL\n"
        "sluice:out_monitor_L\n  |-> speakers:playback_FL\n"
        "sluice_ch_game:monitor_FL\n  |-> sluice:in_game_L\n"
        "other:port\n"
    )
    kept = report.sluice_blocks(text)
    assert "firefox" not in kept and "other:port" not in kept
    assert "sluice:out_monitor_L" in kept and "sluice_ch_game:monitor_FL" in kept
    assert report.sluice_blocks("nothing:here") == "(no sluice ports or links found)"


def test_report_contains_every_section_and_survives_missing_tools(state):
    logs.setup()
    logging.getLogger("sluice.test").info("marker line for the report")
    Mixer.demo().save()
    text = report.build_report()
    for heading in ("sluice", "Self-check", "PipeWire", "pactl info", "sluice ports and links", "Settings", "Log, last", "Native crash log"):
        assert f"===== {heading}" in text, heading
    assert "marker line for the report" in text  # the log tail
    assert '"channels"' in text  # the saved settings
    assert "Look it over before sharing" in text
    assert "(not available" in text or "pactl" in text  # missing tools are reported, not fatal


def test_report_without_any_files(state):
    text = report.build_report()
    assert "(no saved settings yet)" in text and "(file not found)" in text


def test_write_report_to_a_path(state):
    target = state / "out" / "r.txt"
    target.parent.mkdir()
    assert report.write_report(target) == target
    assert target.read_text().startswith("sluice bug report")


# ------------------------------------------------------------------- command line
def test_report_command_writes_the_file_and_warns_about_privacy(state, capsys):
    target = state / "mine.txt"
    assert main(["--report", str(target)]) == 0
    assert target.exists()
    assert "look it over" in capsys.readouterr().out.lower()


def test_cleanup_without_an_audio_server_fails_politely(state, capsys):
    assert main(["--cleanup"]) == 1
    assert "could not connect" in capsys.readouterr().err.lower()


def test_cleanup_refuses_while_sluice_is_running(state, monkeypatch, capsys):
    from sluice import __main__ as entry

    monkeypatch.setattr(entry, "_acquire_lock", lambda: None)
    assert main(["--cleanup"]) == 1
    assert "is running" in capsys.readouterr().err


def test_demo_run_logs_a_session(qapp, state, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    shot = state / "shot.png"
    assert main(["--demo", "--screenshot", str(shot)]) == 0
    assert shot.exists()
    text = (state / "state" / "sluice" / "sluice.log").read_text()
    assert "demo mode" in text and "started" in text and "shut down cleanly" in text
    assert "logging stopped" in text


def test_run_leaves_without_interpreter_teardown_and_keeps_the_exit_code(monkeypatch):
    from sluice import __main__ as entry

    exits = []
    monkeypatch.setattr(os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(entry, "main", lambda: 3)
    entry.run()
    monkeypatch.setattr(entry, "main", lambda: None)
    entry.run()

    def option_error():
        raise SystemExit(2)

    monkeypatch.setattr(entry, "main", option_error)
    entry.run()
    monkeypatch.setattr(entry, "main", lambda: (_ for _ in ()).throw(SystemExit("bad")))
    entry.run()
    assert exits == [3, 0, 2, 1]


def test_the_real_command_exits_with_the_right_codes(tmp_path):
    import subprocess
    import sys

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "XDG_STATE_HOME": str(tmp_path / "s"),
           "XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_RUNTIME_DIR": str(tmp_path), "SLUICE_SOCKET": str(tmp_path / "x.sock")}

    def run(*args):
        return subprocess.run([sys.executable, "-m", "sluice", *args], env=env, capture_output=True, text=True, timeout=60)

    version = run("--version")
    assert version.returncode == 0 and version.stdout.startswith("sluice ")  # output is flushed before the hard exit
    assert run("--no-such-option").returncode == 2
    assert run("ctl", "status").returncode == 2  # no sluice is running
    shot = tmp_path / "shot.png"
    demo = run("--demo", "--screenshot", str(shot))
    assert demo.returncode == 0 and shot.exists() and shot.stat().st_size > 1000
    log = (tmp_path / "s" / "sluice" / "sluice.log").read_text()
    assert "window closed, exit code 0" in log and log.rstrip().endswith("logging stopped")  # the log is complete


def test_a_name_clash_with_another_sluice_is_explained(monkeypatch):
    import pytest

    from sluice import __main__ as entry

    class Boom:
        def __init__(self):
            raise RuntimeError('Error initializing "sluice": <jack.Status 0x4: name_not_unique>')

    class FakeSystem:
        def cleanup(self):
            pass

    import sluice.audio_io, sluice.backend, sluice.jackfix, sluice.linker
    monkeypatch.setattr(sluice.audio_io, "JackIO", Boom)
    monkeypatch.setattr(sluice.backend, "PulseSystem", lambda *a, **k: FakeSystem())
    monkeypatch.setattr(sluice.jackfix, "retry_with_pipewire_jack", lambda: None)
    monkeypatch.setattr(sluice.linker.PwLinker, "available", lambda self: True)
    with pytest.raises(RuntimeError, match="already connected to PipeWire"):
        entry._real_parts()
