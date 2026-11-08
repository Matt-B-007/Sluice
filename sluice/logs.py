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
from pathlib import Path
from typing import Optional

LOG_NAME = "sluice.log"
CRASH_NAME = "crash.log"
MAX_BYTES = 512 * 1024
BACKUPS = 3

_fault_file = None
_original_threading_hook = threading.excepthook


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "sluice"


def log_path() -> Path:
    return state_dir() / LOG_NAME


def crash_path() -> Path:
    return state_dir() / CRASH_NAME


def setup(debug: bool = False) -> Optional[Path]:
    """Start logging. Returns the log file path, or None if the file could not be created."""
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
    _enable_faulthandler()
    log_session_header()
    return path


def shutdown() -> None:
    """Flush and close the log, and stop writing native-crash dumps."""
    global _fault_file
    logging.getLogger("sluice").info("logging stopped")
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


def _enable_faulthandler() -> None:
    global _fault_file
    try:
        if _fault_file is not None:
            _fault_file.close()
        _fault_file = open(crash_path(), "a", encoding="utf-8")
        _fault_file.write(f"--- sluice session started (pid {os.getpid()}) ---\n")
        _fault_file.flush()
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError:
        _fault_file = None


def log_session_header() -> None:
    log = logging.getLogger("sluice")
    try:
        from . import __version__

        log.info("=== sluice %s starting (pid %d) ===", __version__, os.getpid())
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
