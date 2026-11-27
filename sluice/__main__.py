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
    from .audio_io import make_jack_io
    from .backend import PulseSystem
    from .linker import PwLinker

    linker = PwLinker(watch=True)  # it watches the graph for changes (one pw-link --monitor) instead of looking on a clock
    if not linker.available():
        raise RuntimeError("pw-link not found or PipeWire is not running")
    from .model import Mixer, config_path

    # The block size the user chose (Settings > Audio). A PIPEWIRE_LATENCY you set yourself still wins; the one Sluice set at an
    # earlier start (a restart keeps the environment) is replaced (0.12.1: a restart kept the old size).
    _set_latency(Mixer.load(config_path()).buffer_frames)
    system = PulseSystem()
    try:
        io = make_jack_io()
    except Exception as exc:
        system.cleanup()
        if "name_not_unique" in str(exc).lower():
            raise RuntimeError("another program is already connected to PipeWire as \u201csluice\u201d: close any other "
                               "Sluice (pkill -f sluice) and try again; if none is running, restart PipeWire") from exc
        from .jackfix import retry_with_pipewire_jack

        log.info("could not use the JACK library the normal way; trying PipeWire's own")
        retry_with_pipewire_jack()  # starts Sluice again with PipeWire's JACK library first, if that can help
        raise
    return system, io, linker


def _set_latency(frames: int, env=None) -> str:
    """Put the buffer size in PIPEWIRE_LATENCY, unless the person set that variable themselves. Returns the value in use."""
    env = os.environ if env is None else env
    current, ours = env.get("PIPEWIRE_LATENCY"), env.get("SLUICE_OWN_LATENCY")
    if current and current != ours:
        return current  # theirs
    value = f"{frames}/48000"
    env["PIPEWIRE_LATENCY"] = env["SLUICE_OWN_LATENCY"] = value
    return value


def _lock_path() -> str:
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "sluice.lock")


def _acquire_lock():
    """Allow only one sluice at a time: a second one would tear down the first one's devices.
    The holder writes its process number and version into the lock file, so a second start can name it."""
    try:
        import fcntl

        handle = open(_lock_path(), "a+")  # not "w": that would wipe the running copy's note before the lock is tried
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()} {__version__}\n")
            handle.flush()
        except OSError:
            pass
        return handle
    except OSError:
        return None
    except ImportError:
        return True


def _release_lock(lock) -> None:
    """Let go of a lock from ``_acquire_lock`` (closing the file releases it). True (no fcntl) and None need nothing."""
    close = getattr(lock, "close", None)
    if close is not None:
        try:
            close()
        except OSError:
            pass


def _lock_holder() -> tuple:
    """(process number, version) of the running Sluice, from the lock file; None for what is not known."""
    try:
        with open(_lock_path(), encoding="utf-8") as handle:
            pid, version = (handle.read().split() + ["", ""])[:2]
        return (int(pid) if pid.isdigit() else None), (version or None)
    except OSError:
        return None, None


def _already_running_message() -> str:
    pid, version = _lock_holder()
    who = "sluice is already running"
    if version:
        who += f" (version {version}{'' if version == __version__ else f'; this is {__version__}'})"
    who += ", but its window could not be reached."
    if pid:
        return (f"{who}\nClose it with:  kill {pid}\n"
                f"If it is still listed afterwards:  kill -9 {pid}\nThen start Sluice again.")
    return f"{who}\nFind it with:  pgrep -af sluice   and stop it with kill NUMBER, then start Sluice again."


def _is_sluice_process(pid: int) -> bool:
    """True when that process is a Sluice (read from /proc), so only a Sluice is ever offered to be closed."""
    try:
        parts = [p for p in Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace").split("\0") if p]
    except OSError:
        return False
    return any(a == "-m" and b == "sluice" for a, b in zip(parts, parts[1:])) or any(Path(p).name == "sluice" for p in parts[:2])


def _stop_process(pid: int, wait: float = 5.0) -> bool:
    """Ask a process to end (SIGTERM), then make it (SIGKILL). True once it is gone."""
    import time

    for sig, seconds in ((signal.SIGTERM, wait), (signal.SIGKILL, 2.0)):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not Path(f"/proc/{pid}").exists() or "zombie" in _proc_state(pid):
                return True
            time.sleep(0.1)
    return not Path(f"/proc/{pid}").exists()


def _proc_state(pid: int) -> str:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("State:"):
                return line.lower()
    except OSError:
        pass
    return ""


def _replace_stuck_copy(ask=None):
    """0.12.1: a Sluice holds the lock but does not answer (before 0.12.1, quitting from the tray could leave one like that).
    Ask, in a window (there is no terminal when started from the menu), whether to close it and start fresh. Returns the lock
    once the stuck copy is gone, or None (not a Sluice, the answer was no, or it would not end)."""
    pid, _version = _lock_holder()
    if not pid or pid == os.getpid() or not _is_sluice_process(pid):
        return None
    if ask is None:
        def ask() -> bool:
            from PySide6.QtWidgets import QApplication, QMessageBox

            _replace_stuck_copy.app = QApplication.instance() or QApplication(sys.argv[:1])  # kept: the box needs it
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Sluice is not responding")
            box.setText("Another Sluice is still running but does not answer, so this one cannot start.")
            box.setInformativeText("Close it and start Sluice again? Its settings were saved when it last changed.")
            restart = box.addButton("Close it and start", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            return box.clickedButton() is restart
    try:
        if not ask():
            return None
    except Exception as exc:  # no display to ask on: the printed message says what to do
        log.info("could not ask whether to close the stuck Sluice: %s", exc)
        return None
    log.warning("closing the Sluice that does not answer (process %s) to start again", pid)
    if not _stop_process(pid):
        return None
    import time

    for _ in range(20):  # the lock is released as the process ends
        lock = _acquire_lock()
        if lock is not None:
            return lock
        time.sleep(0.1)
    return None


_AS_COMMAND = False  # True when started as the sluice command (run() below)


def _exit_safety_net(seconds: float = 10.0) -> None:
    """0.12.1: once the window has shut down, the process must end. If something keeps it alive (a window Qt still counts, a
    thread that will not stop), end it after ``seconds``, so it can never hold the lock with nothing running."""
    import threading
    import time

    if not _AS_COMMAND:  # Sluice run inside another program (the tests): that program decides when it ends
        return

    def later() -> None:
        time.sleep(seconds)
        if not _AS_COMMAND:  # the command has returned meanwhile (a test calling run()): nothing to end
            return
        log.warning("Sluice had shut down but was still running %.0f s later; ending it now", seconds)
        try:
            logs.shutdown()
        finally:
            os._exit(0)

    threading.Thread(target=later, name="sluice-exit-safety-net", daemon=True).start()


def _cleanup() -> int:
    """Remove virtual devices a crashed sluice left behind."""
    lock = _acquire_lock()
    if lock is None:
        print("sluice is running. Close it first (it removes its own devices when it quits).", file=sys.stderr)
        return 1
    try:
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
    finally:
        _release_lock(lock)


def _report(target: str) -> int:
    from .report import write_report

    try:
        path = write_report(Path(target).expanduser() if target else None)
    except Exception as exc:
        print(f"sluice: could not write the report: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Saved {logs.short_path(path)}\nYour user name, computer name and serial numbers are replaced. It still has device names, app names and plugin paths: look it over before sharing.")
    return 0


def _rollback() -> int:
    from . import update_install

    root = update_install.install_root()
    previous = update_install.previous_version(root)
    if not previous:
        print("There is no earlier version to go back to.", file=sys.stderr)
        return 1
    lock = _acquire_lock()  # held until the files are back: a Sluice started meanwhile would run half-replaced files
    if lock is None:
        print("sluice is running. Close it first, then go back.", file=sys.stderr)
        return 1
    try:
        update_install.rollback(root)
    except update_install.UpdateError as exc:
        print(f"sluice: {exc}", file=sys.stderr)
        return 1
    finally:
        _release_lock(lock)
    print(f"Went back to Sluice {previous}. Your settings were not changed.")
    return 0


def _uninstall(args) -> int:
    from . import uninstall

    lock = _acquire_lock()
    if lock is None:
        print("sluice is running. Close it first (Help > Uninstall Sluice closes it for you).", file=sys.stderr)
        return 1
    try:
        return uninstall.run(keep_settings=args.keep_settings, assume_yes=args.yes, dry_run=args.dry_run,
                             cleanup_devices=_cleanup_devices, list_devices=_list_devices,
                             clear_caches=args.clear_caches, remove_git=args.remove_git_folder)
    finally:
        _release_lock(lock)


def _list_devices() -> list:
    from .backend import PulseSystem

    system = PulseSystem(purge=False)
    try:
        return system.leftover_devices(legacy=True)
    finally:
        system.cleanup()


def _cleanup_devices() -> int:
    from .backend import PulseSystem

    system = PulseSystem(purge=False)
    try:
        return system.purge_stale(legacy=True)
    finally:
        system.cleanup()


def _desktop(install: bool) -> int:
    from . import launcher

    if install:
        try:
            entry = launcher.install()
        except OSError as exc:
            print(f"sluice: could not write the launcher: {exc}", file=sys.stderr)
            return 1
        print(f"Added Sluice to the applications menu ({entry}).\n"
              "Search for \u201cSluice\u201d in your launcher. Remove it again with: sluice --uninstall-desktop")
        return 0
    print("Removed Sluice from the applications menu." if launcher.uninstall() else "Sluice was not in the applications menu.")
    return 0


def _run_gui(args, log_file: Optional[Path]) -> int:
    from . import efficiency
    efficiency.startup_mark("Python and imports")  # 0.12.6: start-up is measured, for the bug report
    lock = None
    notice = ""
    setup_needed = False  # audio could not start: open Settings at the Setup check (0.12.0)
    if args.demo:
        parts = _demo_parts()
        notice = "Demo mode: nothing is routed and your settings are not saved."
        log.info("demo mode")
    else:
        lock = _acquire_lock()
        if lock is None:
            try:  # a second start (the menu, or login) should show the first window rather than do nothing
                from .control_socket import send

                send({"cmd": "show"}, timeout=2.0)
                print("sluice is already running; its window was brought to the front.", file=sys.stderr)
                return 0
            except Exception as exc:  # the other copy does not answer
                log.info("the running Sluice does not answer (%s)", exc)
                lock = _replace_stuck_copy()  # 0.12.1: offer to close it and start fresh
                if lock is None:
                    print(_already_running_message(), file=sys.stderr)
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
            setup_needed = True  # 0.12.0: the window opens Settings at the Setup check, which says what is missing
            notice = (f"Could not start audio ({exc}); running in demo mode. Often the PipeWire JACK library is missing: "
                      f"{hint}. Then run sluice --diagnose.")
    system, io, linker = parts
    efficiency.startup_mark("audio connected")
    from .audio_io import is_demo as _is_demo

    is_demo = _is_demo(io)
    if not is_demo:
        logs.begin_session()  # only a real window, and only once it holds the lock
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

    from .launcher import bundled_icon

    icon = QIcon(str(bundled_icon())) if bundled_icon().is_file() else QIcon()
    if icon.isNull():  # a Qt without SVG support: the PNG does the same job
        from .launcher import bundled_png

        icon = QIcon(str(bundled_png(256)))
    app.setWindowIcon(icon)
    logs.install_qt_handler()
    efficiency.startup_mark("Qt ready")

    config_file = None if is_demo else config_path()
    if is_demo:
        mixer = Mixer.demo()
    else:
        if config_file is not None and migrate_legacy_settings(config_file):
            log.info("copied your settings from the old pwmix folder")
        mixer = Mixer.default() if args.reset else Mixer.load(config_file)
        log.info("settings: %s%s", config_file, " (reset requested)" if args.reset else "")

    efficiency.startup_mark("settings read")
    from .apps import Catalog

    catalog = Catalog.scan()
    efficiency.startup_mark("installed programs found")
    engine = Engine(mixer, system, io, linker, catalog=catalog)
    engine.start()
    efficiency.startup_mark("engine started")
    if getattr(args, "finish_move", None):
        from . import update_install
        moved = update_install.finish_move(Path(args.finish_move))
        notice = f"{notice} {moved}".strip()
    window = MainWindow(engine, config_file=config_file, notice=notice)
    efficiency.startup_mark("window built")
    window.on_shut_down = _exit_safety_net
    from .ui_controllers import Controls

    window.attach_controls(Controls(engine, window, config_file.with_name("controls.json") if config_file else None, demo=is_demo))
    if args.minimized:
        window.start_minimized()
    else:
        window.show()
    if setup_needed:
        QTimer.singleShot(500, lambda: window.open_settings("Setup check"))

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
        from . import update_install

        installed = update_install.apply_staged_quietly()  # a downloaded update goes in now that nothing is running
        if installed:
            print(f"sluice: updated to {installed}; it starts next time.", file=sys.stderr)
    del lock
    return code


def main(argv: Optional[list] = None) -> int:
    args_list = sys.argv[1:] if argv is None else list(argv)
    if args_list[:1] == ["ctl"]:  # remote control of a running sluice: no logging, no Qt, fast enough for a button press
        from .control_socket import run_cli

        return run_cli(args_list[1:])
    parser = argparse.ArgumentParser(prog="sluice", description="Virtual audio mixer for PipeWire.")
    parser.add_argument("--version", action="version", version=f"sluice {__version__}")
    parser.add_argument("--demo", action="store_true", help="use a fake audio backend; touches no audio and saves nothing")
    parser.add_argument("--reset", action="store_true", help="ignore the saved configuration")
    parser.add_argument("--diagnose", action="store_true", help="check that everything sluice needs is installed and running")
    parser.add_argument("--debug", action="store_true", help="log every detail (links, commands) to the log file and the terminal")
    parser.add_argument("--report", nargs="?", const="", metavar="FILE", help="write a bug report file (default: ~/sluice-report-VERSION-DATE-TIME.txt)")
    parser.add_argument("--rollback", action="store_true", help="go back to the version before the last in-app update")
    parser.add_argument("--cleanup", action="store_true", help="remove virtual devices left behind by a crash")
    parser.add_argument("--install-desktop", action="store_true", help="add Sluice to the applications menu (your own folders only)")
    parser.add_argument("--uninstall-desktop", action="store_true", help="remove Sluice from the applications menu")
    parser.epilog = "remote control: sluice ctl --help"
    parser.add_argument("--uninstall", action="store_true", help="remove Sluice completely (shows what it will remove and asks first)")
    parser.add_argument("--keep-settings", action="store_true", help="with --uninstall: keep your settings, presets and controller bindings (the default is to remove everything)")
    parser.add_argument("--clear-caches", action="store_true",
                        help="with --uninstall: also clear the pip and cargo download caches (other programs share them)")
    parser.add_argument("--remove-git-folder", action="store_true",
                        help="with --uninstall: also remove the Sluice folder when it is a git clone (unpushed changes are lost)")
    parser.add_argument("--yes", action="store_true", help="with --uninstall: do not ask")
    parser.add_argument("--dry-run", action="store_true", help="with --uninstall: show what would be removed and change nothing")
    parser.add_argument("--minimized", action="store_true", help="start with the window minimized (to the tray if \"Keep running in the tray\" is chosen, otherwise to the taskbar)")
    parser.add_argument("--startup", action="store_true", help=argparse.SUPPRESS)  # only the launcher script uses this
    parser.add_argument("--finish-move", metavar="OLD", help=argparse.SUPPRESS)  # 0.12.0: the moved copy deletes the old folder
    parser.add_argument("--autostart", choices=["off", "window", "minimized"], help="start Sluice when you log in: with the window open, minimized, or never")
    parser.add_argument("--screenshot", metavar="PNG", help=argparse.SUPPRESS)  # developer option
    args = parser.parse_args(args_list)

    is_command = bool(args.diagnose or args.cleanup or args.rollback or args.autostart or args.install_desktop
                      or args.uninstall_desktop or args.uninstall or args.report is not None)
    log_file = logs.setup(debug=args.debug, session=not is_command)
    try:
        if args.diagnose:
            from .diagnose import report

            text, ok = report()
            print(text)
            return 0 if ok else 1
        if args.cleanup:
            return _cleanup()
        if args.uninstall:
            return _uninstall(args)
        if args.rollback:
            return _rollback()
        if args.autostart:
            from . import launcher

            try:
                launcher.set_autostart(args.autostart)
            except OSError as exc:
                print(f"sluice: could not change start-up: {exc}", file=sys.stderr)
                return 1
            print({"off": "Sluice will no longer start when you log in.",
                   "window": "Sluice will start when you log in, with its window open.",
                   "minimized": "Sluice will start when you log in, minimized (to the tray if \"Keep running in the tray\" is chosen, "
                                "otherwise to the taskbar)."}[args.autostart])
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
    global _AS_COMMAND
    _AS_COMMAND = True
    try:
        code = main()
    except SystemExit as exc:  # --version, --help and bad options exit this way
        code = exc.code
    finally:
        _AS_COMMAND = False  # main has returned: the exit below is immediate, the safety net has nothing left to do
    if code is None:
        code = 0
    if not isinstance(code, int):
        print(code, file=sys.stderr)
        code = 1
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass  # exiting: a closed output stream is nothing to report to anyone
    os._exit(code)


if __name__ == "__main__":
    run()
