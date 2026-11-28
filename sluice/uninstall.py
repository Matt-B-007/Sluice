# SPDX-License-Identifier: GPL-3.0-or-later
"""Remove Sluice, in steps you can see first. Two ways:

* **keep my settings**: removes the program and everything it left around, but keeps the settings folder (channels,
  effects, presets, controller bindings) in case you install Sluice again;
* **remove everything**: removes every file that has to do with Sluice, then checks and tells you that nothing is left.

What is removed (all of it is inside your own home folder or your runtime folder; nothing needs root):

1. leftover virtual audio devices (only when PipeWire answers),
2. the applications-menu entry, the start-at-login entry, the launcher script, the icons and the ``sluice`` command in
   ``~/.local/bin`` (only the one install.sh wrote),
3. your settings (not when you keep them), logs and notes, the crash log, and the old ``pwmix`` folders,
4. the lock and control-socket files,
5. the Sluice folder itself: the program, its virtual environment, the Rust build folder, ``.update`` and ``.previous``
   (since 0.12.0 that is ``~/.local/share/sluice/program``; ``~/.local/share/sluice`` goes too once it is empty),
6. optionally the download caches of pip and cargo. Other programs share those, so this is only done when asked.

It only removes a folder that really is a Sluice folder, never your home folder. A folder that is a git clone is only
removed in "remove everything" mode and only when you say yes, because it may hold changes you have not pushed.
What it never touches: system packages such as PipeWire, files Sluice did not create (zips you downloaded, a separate
``Sluice-repo`` clone, your recordings), and the shared caches unless you ask.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import launcher, logs, update_install
from .model import config_path

log = logging.getLogger(__name__)

DESKTOP_KINDS = ("applications-menu entry", "start-at-login entry", "launcher script", "icon")

#: What stays on the computer whatever you choose. Shown in the dialog and printed at the end.
STAYS = (
    "System packages such as PipeWire and Python stay.",
    "Files Sluice did not create stay: zips you downloaded, a separate Sluice-repo clone, your recordings.",
)


@dataclass
class Item:
    path: Path
    what: str


@dataclass
class Plan:
    items: list = field(default_factory=list)  # Items that exist and will be removed
    kept: list = field(default_factory=list)  # (path, why) that are left alone
    install_root: Optional[Path] = None
    keep_settings: bool = False
    git_folder: bool = False  # the Sluice folder is a git clone
    git_removed: bool = False  # ... and the person said it may be removed

    @property
    def nothing(self) -> bool:
        return not self.items

    @property
    def asks_about_git(self) -> bool:
        """True when 'remove everything' should ask the git question before going on."""
        return self.git_folder and not self.keep_settings and not self.git_removed


def _home() -> Path:
    return Path.home()


def _legacy_dirs() -> list:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or (_home() / ".config")) / "pwmix"
    state = Path(os.environ.get("XDG_STATE_HOME") or (_home() / ".local" / "state")) / "pwmix"
    return [config, state]


def cache_dirs() -> list:
    """The download caches Sluice's installer may have filled: (path, what). Shared with other programs."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or (_home() / ".cache"))
    cargo = Path(os.environ.get("CARGO_HOME") or (_home() / ".cargo"))
    return [(cache / "pip", "pip download cache"), (cargo / "registry", "cargo download cache")]


def runtime_files() -> list:
    """The single-copy lock and the control sockets (in the runtime folder)."""
    names = ("sluice.lock", "sluice-control.sock", "sluice-control-demo.sock")
    bases = []
    for base in (os.environ.get("XDG_RUNTIME_DIR"), f"/tmp/sluice-{os.getuid()}", "/tmp"):
        if base and base not in bases:
            bases.append(base)
    paths = [Path(base) / name for base in bases for name in names]
    override = os.environ.get("SLUICE_SOCKET")
    if override:
        paths.append(Path(override))
    return paths


def folder_problem(root: Optional[Path], allow_git: bool = False) -> str:
    """Why the Sluice folder will not be removed, or '' when it is safe to. ``allow_git``: a git clone may go."""
    if root is None:
        return "this copy of Sluice is not in a Sluice folder (for example a pip install): remove it with pip"
    root = root.resolve()
    if root in (_home().resolve(), Path("/"), _home().resolve().parent) or root == Path(root.anchor):
        return "that folder is too important to remove"
    if (root / ".git").exists() and not allow_git:
        return "it is a git clone: it may hold changes you have not pushed, so it stays unless you say it may go"
    if not all((root / name).exists() for name in ("pyproject.toml", "install.sh", "sluice/__init__.py")):
        return "it does not look like a Sluice folder"
    if not os.access(root.parent, os.W_OK):
        return "its parent folder is not writable"
    return ""


def plan(keep_settings: bool = False, root: Optional[Path] = None, clear_caches: bool = False, remove_git: bool = False) -> Plan:
    result = Plan(install_root=root if root is not None else update_install.install_root(), keep_settings=keep_settings)
    for path, what in (
        (launcher.launcher_path(), "applications-menu entry"),
        (launcher.autostart_path(), "start-at-login entry"),
        (launcher.script_path(), "launcher script"),
        (launcher.icon_path(), "icon"),
        *[(p, "icon") for p in launcher.png_icon_paths()],
    ):
        if path.exists():
            result.items.append(Item(path, what))
    if launcher.is_our_command():
        result.items.append(Item(launcher.command_path(), "the sluice command"))
    settings = config_path().parent
    if settings.exists():
        if keep_settings:
            result.kept.append((settings, "your settings, presets and controller bindings (you chose to keep them)"))
        else:
            result.items.append(Item(settings, "settings, presets and controller bindings"))
    if logs.state_dir().exists():
        if keep_settings:  # 0.13.1-beta.3: "Also delete my settings and logs" unticked keeps the logs too, as it says
            result.kept.append((logs.state_dir(), "your logs, notes and the crash log (you chose to keep them)"))
        else:
            result.items.append(Item(logs.state_dir(), "logs, notes and the crash log"))
    for path in _legacy_dirs():
        if path.exists():
            result.items.append(Item(path, "settings or logs from the old name (pwmix)"))
    for path in runtime_files():
        if path.exists() or path.is_symlink():
            result.items.append(Item(path, "lock or control-socket file"))
    root_path = result.install_root
    result.git_folder = bool(root_path is not None and (root_path / ".git").exists())
    result.git_removed = bool(result.git_folder and remove_git and not keep_settings)
    problem = folder_problem(root_path, allow_git=result.git_removed)
    if root_path is not None and not problem:
        what = "the Sluice folder, with its virtual environment, build folders and update copies"
        if result.git_removed:
            what += " (a git clone: any unpushed changes in it are lost)"
        result.items.append(Item(root_path, what))
    elif problem:
        where = f" ({root_path})" if root_path else ""
        result.kept.append((root_path or Path("."), f"the program files{where} stay: {problem}"))
    if clear_caches:
        for path, what in cache_dirs():
            if path.exists():
                result.items.append(Item(path, what + " (shared with other programs)"))
    return result


def describe(result: Plan) -> str:
    lines = ["Sluice will remove:"]
    lines += [f"  - {logs.short_path(i.path)}  ({i.what})" for i in result.items] or ["  (nothing: it is not installed here)"]
    for path, why in result.kept:
        lines.append(f"Left alone: {logs.short_path(path)}: {why}")
    return "\n".join(lines)


def _remove(path: Path) -> Optional[str]:
    """Remove a file or folder; None on success or the reason it failed. Never follows a symlink out of a folder."""
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        elif path.exists():  # a socket or another special file
            path.unlink()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return str(exc)
    return None


def running_processes(exclude: Optional[set] = None) -> list:
    """Other Sluice programs still running: (process number, what it is). Reads /proc; nothing else is needed."""
    skip = {os.getpid(), os.getppid()} | set(exclude or ())
    found = []
    proc = Path("/proc")
    try:
        entries = [e for e in proc.iterdir() if e.name.isdigit()]
    except OSError:
        return []
    for entry in entries:
        pid = int(entry.name)
        if pid in skip:
            continue
        try:
            parts = (entry / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")
        except OSError:
            continue
        parts = [p for p in parts if p]
        if not parts or "--uninstall" in parts:
            continue
        runs_sluice = (
            any(a == "-m" and b == "sluice" for a, b in zip(parts, parts[1:]))
            or Path(parts[0]).name == "sluice"
            or (len(parts) > 1 and Path(parts[1]).name == "sluice")
        )
        if runs_sluice:
            found.append((pid, " ".join(parts)[:80]))
    return found


def leftovers(result: Plan, list_devices: Optional[Callable[[], list]] = None) -> list:
    """What of Sluice is still on the computer after removing: files, virtual devices, running programs.

    Things the person chose to keep (settings, a git clone) are not leftovers. Returns plain sentences; an empty list means
    nothing of Sluice is left."""
    left = []
    for item in result.items:
        if item.path.exists() or item.path.is_symlink():
            left.append(f"{logs.short_path(item.path)} ({item.what}) is still there")
    if list_devices is not None:
        try:
            for name in list_devices():
                left.append(f"the virtual audio device {name} still exists")
        except Exception as exc:  # PipeWire not answering means there are no devices to find
            log.debug("could not list the virtual devices for the final check: %s", exc)
    for pid, command in running_processes():
        left.append(f"a Sluice program is still running (process {pid}: {command})")
    return left


def execute(
    result: Plan,
    cleanup_devices: Optional[Callable[[], int]] = None,
    say: Callable = print,
    list_devices: Optional[Callable[[], list]] = None,
    check: bool = False,
) -> int:
    """Do it. Returns 0 when everything in the plan is gone, 1 when something could not be removed.
    With ``check`` it also looks for leftovers and says what it found (or that nothing is left)."""
    if cleanup_devices is not None:
        try:
            cleanup_devices()
        except Exception as exc:  # PipeWire not running is fine: there are no devices to remove then
            say(f"Could not check for leftover devices ({exc}); continuing.")
    failures = []
    desktop_paths = {i.path for i in result.items if i.what in DESKTOP_KINDS}
    if desktop_paths:
        launcher.uninstall()
    for item in result.items:
        if item.path in desktop_paths:
            continue
        # the folder holding the running program goes last, so the rest finishes while Python can still read its files
        if result.install_root is not None and item.path == result.install_root:
            continue
        problem = _remove(item.path)
        if problem:
            failures.append((item.path, problem))
    if result.install_root is not None and any(i.path == result.install_root for i in result.items):
        problem = _remove(result.install_root)
        if problem:
            failures.append((result.install_root, problem))
    home = launcher.sluice_home()  # Sluice's own data folder, once the program and the launcher script are out of it
    try:
        if home.is_dir() and not any(home.iterdir()):
            home.rmdir()
    except OSError as exc:
        log.debug("could not remove the empty %s: %s", home, exc)
    for path, problem in failures:
        say(f"Could not remove {logs.short_path(path)}: {problem}")
    if check:
        left = leftovers(result, list_devices)
        if left:
            say("Left over:\n" + "\n".join(f"  - {line}" for line in left))
            return 1
        if not failures:
            say(
                "Checked: nothing of Sluice is left on this computer."
                if not result.kept
                else "Checked: nothing of Sluice is left except what you chose to keep."
            )
    return 1 if failures else 0


def ask_git(ask: Callable, say: Callable) -> bool:
    say("The Sluice folder is a git clone. Deleting it also deletes any changes in it that you have not committed or pushed.")
    return ask("Delete the git folder too? Type yes to delete it, anything else keeps it: ").strip().lower() in ("y", "yes")


def run(
    keep_settings: bool = False,
    assume_yes: bool = False,
    dry_run: bool = False,
    cleanup_devices: Optional[Callable[[], int]] = None,
    ask: Callable = input,
    say: Callable = print,
    clear_caches: bool = False,
    remove_git: bool = False,
    list_devices: Optional[Callable[[], list]] = None,
) -> int:
    result = plan(keep_settings, clear_caches=clear_caches, remove_git=remove_git)
    if result.asks_about_git and not assume_yes and not dry_run:
        if ask_git(ask, say):
            result = plan(keep_settings, clear_caches=clear_caches, remove_git=True)
    say(describe(result))
    if result.nothing:
        return 0
    if dry_run:
        say("(dry run) nothing was removed.")
        return 0
    if not assume_yes:
        answer = ask("Remove all of that? Type yes to continue: ").strip().lower()
        if answer not in ("y", "yes"):
            say("Nothing was removed.")
            return 1
    code = execute(result, cleanup_devices, say, list_devices=list_devices, check=True)
    if code == 0:
        say("\n".join(STAYS))
    return code


def command_for_gui(keep_settings: bool, clear_caches: bool = False, remove_git: bool = False) -> list:
    """The command the Help menu runs, after Sluice has closed, to remove itself."""
    command = [sys.executable, "-m", "sluice", "--uninstall", "--yes"]
    if keep_settings:
        command.append("--keep-settings")
    if clear_caches:
        command.append("--clear-caches")
    if remove_git and not keep_settings:
        command.append("--remove-git-folder")
    return command
