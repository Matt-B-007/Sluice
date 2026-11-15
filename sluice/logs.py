# SPDX-License-Identifier: GPL-3.0-or-later
"""Logging, so a bug can be understood after it happened.

* ``~/.local/state/sluice/sluice.log``  rotating log (512 KB, 3 old copies kept)
* ``~/.local/state/sluice/crash.log``  Python traceback if sluice itself crashes natively
  (for example inside a misbehaving VST3 plugin), written by ``faulthandler``

Normal runs log at INFO; ``sluice --debug`` adds DEBUG (every link and command).
Nothing from the audio thread is ever logged: that could cause dropouts.
"""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Optional

LOG_NAME = "sluice.log"
CRASH_NAME = "crash.log"
RUNNING_NAME = "running"   # exists while a session is alive; its modified time is the last sign of life
HEARTBEAT_SECONDS = 5.0
MAX_BYTES = 512 * 1024
BACKUPS = 3

_fault_file = None
_last_heartbeat = 0.0
_original_threading_hook = threading.excepthook


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "sluice"


def log_path() -> Path:
    return state_dir() / LOG_NAME


def short_path(path) -> str:
    """A path for showing to people: the home folder is written as ``~`` so no user name appears."""
    text = str(path)
    home = str(Path.home()).rstrip("/")
    if home and home != "/" and (text == home or text.startswith(home + "/")):
        return "~" + text[len(home):]
    return text


def crash_path() -> Path:
    return state_dir() / CRASH_NAME


def running_path() -> Path:
    return state_dir() / RUNNING_NAME


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists, but belongs to someone else
    try:  # a process that was killed but not yet cleared away by its parent is dead as far as we are concerned
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        if stat.rsplit(")", 1)[1].split()[0] == "Z":
            return False
    except (OSError, IndexError):
        pass
    return True


def previous_session_notice() -> Optional[str]:
    """A sentence about the last session if it did not end normally (crash, kill, power loss), else None.

    A session that ends normally removes the marker; a restart into the same process (Sluice restarts itself with the
    same process id) also does, so a marker that is still there at start-up means the last run was cut short."""
    try:
        marker = running_path()
        lines = marker.read_text(encoding="utf-8").splitlines()
        seen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(marker.stat().st_mtime))
    except (OSError, ValueError):
        return None
    try:
        pid = int(lines[0]) if lines else 0
    except ValueError:
        pid = 0
    if pid and pid != os.getpid() and _pid_alive(pid):
        return None  # another Sluice is running right now: its marker is not a crash
    started = lines[1] if len(lines) > 1 else "an unknown time"
    return (f"the previous Sluice session (started {started}, last seen running at {seen}) did not end normally: "
            f"it crashed, was stopped, or the computer lost power. If it crashed, {crash_path().name} has the details")


def mark_running() -> None:
    global _last_heartbeat
    try:
        running_path().parent.mkdir(parents=True, exist_ok=True)
        running_path().write_text(f"{os.getpid()}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
        _last_heartbeat = time.monotonic()
    except OSError:
        pass


def heartbeat() -> None:
    """Called often (twice a second); touches the marker every few seconds so its time is the last sign of life."""
    global _last_heartbeat
    now = time.monotonic()
    if now - _last_heartbeat < HEARTBEAT_SECONDS:
        return
    _last_heartbeat = now
    try:
        os.utime(running_path())
    except OSError:
        pass


def mark_clean_exit() -> None:
    """Remove the marker, but only our own: a command such as ``sluice --report`` run next to a running Sluice must not
    remove the running Sluice's marker."""
    try:
        lines = running_path().read_text(encoding="utf-8").splitlines()
        if lines and lines[0].strip() != str(os.getpid()):
            return
        running_path().unlink()
    except OSError:
        pass


def setup(debug: bool = False, session: bool = True) -> Optional[Path]:
    """Start logging. Returns the log file path, or None if the file could not be created.

    ``session`` is True for the window (a new part of the log and of the crash file) and False for a command such as
    ``--report`` or ``--diagnose``, which only adds lines to the current session. Marking the session as running is a
    separate step, ``begin_session``, taken once the window really is running."""
    root = logging.getLogger("sluice")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False
    _close_handlers(root)

    path: Optional[Path] = None
    try:
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            directory / LOG_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)
        path = directory / LOG_NAME
    except OSError:
        pass

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    console.setFormatter(logging.Formatter("sluice: %(levelname)s: %(message)s"))
    root.addHandler(console)

    _install_crash_hooks()
    _enable_faulthandler(session)
    log_session_header(session)
    return path


def begin_session() -> None:
    """The window is really running (the audio server is connected and no other Sluice holds the lock): report a last
    session that ended badly, then mark this one as running. Not called for a second start that is about to hand over to
    the first, for a demo, or for a command, none of which may touch the running Sluice's marker."""
    notice = previous_session_notice()
    if notice:
        logging.getLogger("sluice").warning("%s", notice)
    mark_running()


def shutdown() -> None:
    """Flush and close the log, and stop writing native-crash dumps."""
    global _fault_file
    logging.getLogger("sluice").info("logging stopped")
    mark_clean_exit()
    _close_handlers(logging.getLogger("sluice"))
    try:
        faulthandler.disable()
    except Exception:
        pass
    if _fault_file is not None:
        try:
            _fault_file.close()
        except OSError:
            pass
        _fault_file = None
    sys.excepthook = sys.__excepthook__
    threading.excepthook = _original_threading_hook


def _close_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _install_crash_hooks() -> None:
    crash = logging.getLogger("sluice.crash")

    def on_exception(exc_type, exc, tb) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            crash.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def on_thread_exception(args) -> None:
        name = args.thread.name if args.thread is not None else "?"
        crash.critical("Uncaught exception in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = on_exception
    threading.excepthook = on_thread_exception


def _enable_faulthandler(session: bool = True) -> None:
    global _fault_file
    try:
        if _fault_file is not None:
            _fault_file.close()
        _fault_file = open(crash_path(), "a", encoding="utf-8")
        kind = "session" if session else "command"
        _fault_file.write(f"--- sluice {kind} started {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()}) ---\n")
        _fault_file.flush()
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError:
        _fault_file = None


def log_session_header(session: bool = True) -> None:
    log = logging.getLogger("sluice")
    try:
        from . import __version__

        # "starting" opens a session in the bug report's log section; a command is not one
        log.info("=== sluice %s %s (pid %d) ===", __version__, "starting" if session else "running a command", os.getpid())
        log.info("python %s on %s", platform.python_version(), platform.platform())
        from importlib import metadata

        for package in ("PySide6", "pedalboard", "JACK-Client", "numpy", "pulsectl"):
            names = ("PySide6", "PySide6-Essentials") if package == "PySide6" else (package,)
            for name in names:
                try:
                    log.info("%s %s", name, metadata.version(name))
                    break
                except metadata.PackageNotFoundError:
                    continue
            else:
                log.warning("%s is not installed", package)
        session = os.environ.get("XDG_SESSION_TYPE", "?")
        log.info("session: %s, wayland display: %s", session, bool(os.environ.get("WAYLAND_DISPLAY")))
        for key in sorted(os.environ):
            if key.startswith("PIPEWIRE_") or key == "VST3_PATH":
                log.info("env %s=%s", key, os.environ[key])
    except Exception as exc:  # the header is a convenience: it must never stop sluice starting
        log.warning("could not write session header: %s", exc)


def install_qt_handler() -> None:
    """Send Qt's own warnings to the log (call after the QApplication exists)."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    qt_log = logging.getLogger("sluice.qt")
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, _context, message) -> None:
        if "propagateSizeHints" in message:  # harmless noise from the headless test platform
            return
        qt_log.log(levels.get(mode, logging.WARNING), "%s", message)

    qInstallMessageHandler(handler)
