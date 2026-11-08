# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point: ``python -m sluice`` or the ``sluice`` command."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from . import __version__, logs
from .model import Mixer, config_path, migrate_legacy_settings

log = logging.getLogger("sluice")


def _demo_parts():
    from .audio_io import NullIO
    from .backend import MockSystem
    from .linker import NullLinker

    system = MockSystem()
    system.add_demo_streams()
    return system, NullIO(), NullLinker()


def _real_parts():
    """Connect to PipeWire. Raises with a readable message if any part is missing."""
    from .audio_io import JackIO
    from .backend import PulseSystem
    from .linker import PwLinker

    linker = PwLinker()
    if not linker.available():
        raise RuntimeError("pw-link not found or PipeWire is not running")
    from .model import Mixer, config_path

    # The block size the user chose (View > Audio buffer). A PIPEWIRE_LATENCY set in the environment still wins.
    os.environ.setdefault("PIPEWIRE_LATENCY", f"{Mixer.load(config_path()).buffer_frames}/48000")
    system = PulseSystem()
    try:
        io = JackIO()
    except Exception as exc:
        system.cleanup()
        if "name_not_unique" in str(exc):
            raise RuntimeError("another program is already connected to PipeWire as \u201csluice\u201d: close any other "
                               "Sluice (pkill -f sluice) and try again; if none is running, restart PipeWire") from exc
        from .jackfix import retry_with_pipewire_jack

        log.info("could not use the JACK library the normal way; trying PipeWire's own")
        retry_with_pipewire_jack()  # starts Sluice again with PipeWire's JACK library first, if that can help
        raise
    return system, io, linker


def _acquire_lock():
    """Allow only one sluice at a time: a second one would tear down the first one's devices."""
    try:
        import fcntl

        base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        handle = open(os.path.join(base, "sluice.lock"), "w")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        return None
    except ImportError:
        return True


def _cleanup() -> int:
    """Remove virtual devices a crashed sluice left behind."""
    lock = _acquire_lock()
    if lock is None:
        print("sluice is running. Close it first (it removes its own devices when it quits).", file=sys.stderr)
        return 1
    try:
        from .backend import PulseSystem

        system = PulseSystem(purge=False)
    except Exception as exc:
        print(f"sluice: could not connect to PipeWire/PulseAudio: {exc}", file=sys.stderr)
        return 1
    try:
        removed = system.purge_stale(legacy=True)
    finally:
        system.cleanup()
    print(f"Removed {removed} leftover sluice device(s)." if removed else "Nothing to clean up.")
    return 0


def _report(target: str) -> int:
    from .report import write_report

    path = write_report(Path(target).expanduser() if target else None)
    print(f"Saved {path}\nIt contains device names, app names and plugin paths: look it over before sharing.")
    return 0


def _rollback() -> int:
    from . import selfupdate

    root = selfupdate.install_root()
    previous = selfupdate.previous_version(root)
    if not previous:
        print("There is no earlier version to go back to.", file=sys.stderr)
        return 1
    if _acquire_lock() is None:
        print("sluice is running. Close it first, then go back.", file=sys.stderr)
        return 1
    try:
        selfupdate.rollback(root)
    except selfupdate.UpdateError as exc:
        print(f"sluice: {exc}", file=sys.stderr)
        return 1
    print(f"Went back to Sluice {previous}. Your settings were not changed.")
    return 0


def _desktop(install: bool) -> int:
    from . import desktop

    if install:
        try:
            launcher = desktop.install()
        except OSError as exc:
            print(f"sluice: could not write the launcher: {exc}", file=sys.stderr)
            return 1
        print(f"Added Sluice to the applications menu ({launcher}).\n"
              "Search for \u201cSluice\u201d in your launcher. Remove it again with: sluice --uninstall-desktop")
        return 0
    print("Removed Sluice from the applications menu." if desktop.uninstall() else "Sluice was not in the applications menu.")
    return 0


def _run_gui(args, log_file: Optional[Path]) -> int:
    lock = None
    notice = ""
    if args.demo:
        parts = _demo_parts()
        notice = "Demo mode: nothing is routed and your settings are not saved."
        log.info("demo mode")
    else:
        lock = _acquire_lock()
        if lock is None:
            try:  # a second start (the menu, or login) should show the first window rather than do nothing
                from .control import send

                send({"cmd": "show"}, timeout=2.0)
                print("sluice is already running; its window was brought to the front.", file=sys.stderr)
                return 0
            except Exception:
                print("sluice is already running (but its window could not be reached).", file=sys.stderr)
                return 1
        try:
            parts = _real_parts()
        except Exception as exc:  # missing packages, no server, permission problems...
            log.warning("could not start audio, falling back to demo mode: %s", exc, exc_info=True)
            from .distro import install_hint

            hint = install_hint(["pipewire", "pulse", "session", "jack", "pwlink"])
            print(f"sluice: {exc}\nStarting in demo mode. Run 'sluice --diagnose' to see what is missing.\n"
                  f"To install the usual missing parts (PipeWire and its JACK library): {hint}", file=sys.stderr)
            parts = _demo_parts()
            notice = (f"Could not start audio ({exc}); running in demo mode. Often the PipeWire JACK library is missing: "
                      f"{hint}. Then run sluice --diagnose.")
    system, io, linker = parts
    is_demo = not hasattr(io, "client")
    if log_file is not None:
        print(f"sluice: logging to {log_file}", file=sys.stderr)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .engine import Engine
    from .ui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])  # an existing one only happens in tests
    app.setStyle("Fusion")
    app.setApplicationName("Sluice")
    app.setDesktopFileName("sluice")  # matches sluice.desktop, so the launcher's icon is used for the window
    from PySide6.QtGui import QIcon

    from .desktop import bundled_icon

    icon = QIcon(str(bundled_icon())) if bundled_icon().is_file() else QIcon()
    if icon.isNull():  # a Qt without SVG support: the PNG does the same job
        from .desktop import bundled_png

        icon = QIcon(str(bundled_png(256)))
    app.setWindowIcon(icon)
    logs.install_qt_handler()

    config_file = None if is_demo else config_path()
    if is_demo:
        mixer = Mixer.demo()
    else:
        if config_file is not None and migrate_legacy_settings(config_file):
            log.info("copied your settings from the old pwmix folder")
        mixer = Mixer.default() if args.reset else Mixer.load(config_file)
        log.info("settings: %s%s", config_file, " (reset requested)" if args.reset else "")

    from .apps import Catalog

    engine = Engine(mixer, system, io, linker, catalog=Catalog.scan())
    engine.start()
    window = MainWindow(engine, config_file=config_file, notice=notice)
    from .ui_controls import Controls

    window.attach_controls(Controls(engine, window, config_file.with_name("controls.json") if config_file else None, demo=is_demo))
    if args.minimized:
        window.start_minimized()
    else:
        window.show()

    app.aboutToQuit.connect(window.shutdown)
    signal.signal(signal.SIGINT, lambda *_: app.quit())  # Ctrl+C in a terminal; the timers let Python see it
    signal.signal(signal.SIGTERM, lambda *_: app.quit())

    if args.screenshot:
        def grab() -> None:
            window.grab().save(args.screenshot)
            app.quit()

        QTimer.singleShot(1500, grab)

    code = app.exec()
    log.info("window closed, exit code %s", code)
    if not is_demo:
        from . import selfupdate

        installed = selfupdate.apply_staged_quietly()  # a downloaded update goes in now that nothing is running
        if installed:
            print(f"sluice: updated to {installed}; it starts next time.", file=sys.stderr)
    del lock
    return code


def main(argv: Optional[list] = None) -> int:
    args_list = sys.argv[1:] if argv is None else list(argv)
    if args_list[:1] == ["ctl"]:  # remote control of a running sluice: no logging, no Qt, fast enough for a button press
        from .control import run_cli

        return run_cli(args_list[1:])
    parser = argparse.ArgumentParser(prog="sluice", description="Virtual audio mixer for PipeWire.")
    parser.add_argument("--version", action="version", version=f"sluice {__version__}")
    parser.add_argument("--demo", action="store_true", help="use a fake audio backend; touches no audio and saves nothing")
    parser.add_argument("--reset", action="store_true", help="ignore the saved configuration")
    parser.add_argument("--diagnose", action="store_true", help="check that everything sluice needs is installed and running")
    parser.add_argument("--debug", action="store_true", help="log every detail (links, commands) to the log file and the terminal")
    parser.add_argument("--report", nargs="?", const="", metavar="FILE", help="write a bug report file (default: ~/sluice-report.txt)")
    parser.add_argument("--rollback", action="store_true", help="go back to the version before the last in-app update")
    parser.add_argument("--cleanup", action="store_true", help="remove virtual devices left behind by a crash")
    parser.add_argument("--install-desktop", action="store_true", help="add Sluice to the applications menu (your own folders only)")
    parser.add_argument("--uninstall-desktop", action="store_true", help="remove Sluice from the applications menu")
    parser.epilog = "remote control: sluice ctl --help"
    parser.add_argument("--minimized", action="store_true", help="start with the window minimized to the taskbar")
    parser.add_argument("--startup", action="store_true", help=argparse.SUPPRESS)  # only the launcher script uses this
    parser.add_argument("--autostart", choices=["off", "window", "minimized"], help="start Sluice when you log in: with the window open, minimized, or never")
    parser.add_argument("--screenshot", metavar="PNG", help=argparse.SUPPRESS)  # developer option
    args = parser.parse_args(args_list)

    log_file = logs.setup(debug=args.debug)
    try:
        if args.diagnose:
            from .diagnose import report

            text, ok = report()
            print(text)
            return 0 if ok else 1
        if args.cleanup:
            return _cleanup()
        if args.rollback:
            return _rollback()
        if args.autostart:
            from . import desktop

            try:
                desktop.set_autostart(args.autostart)
            except OSError as exc:
                print(f"sluice: could not change start-up: {exc}", file=sys.stderr)
                return 1
            print({"off": "Sluice will no longer start when you log in.",
                   "window": "Sluice will start when you log in, with its window open.",
                   "minimized": "Sluice will start when you log in, minimized to the taskbar."}[args.autostart])
            return 0
        if args.install_desktop or args.uninstall_desktop:
            return _desktop(install=args.install_desktop)
        if args.report is not None:
            return _report(args.report)
        return _run_gui(args, log_file)
    finally:
        logs.shutdown()


def run() -> None:
    """The ``sluice`` command. When ``main`` has returned, everything is already cleaned up and logged, so leave at once.

    A normal Python exit tears down Qt, JACK and the effects engine one library at a time, and that teardown has
    crashed with a segmentation fault on some systems after a perfectly clean shutdown. Skipping it loses nothing."""
    try:
        code = main()
    except SystemExit as exc:  # --version, --help and bad options exit this way
        code = exc.code
    if code is None:
        code = 0
    if not isinstance(code, int):
        print(code, file=sys.stderr)
        code = 1
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code)


if __name__ == "__main__":
    run()
