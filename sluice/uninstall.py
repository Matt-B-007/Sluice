# SPDX-License-Identifier: GPL-3.0-or-later
"""Remove Sluice completely, in steps you can see first.

``sluice --uninstall`` lists what it would remove, asks, and then removes it:

1. leftover virtual audio devices (only when PipeWire answers),
2. the applications-menu entry, the start-at-login entry, the launcher script and the icons,
3. your settings and logs (``--keep-settings`` keeps the settings folder: channels, effects, presets, controller bindings),
4. the Sluice folder itself, including its virtual environment.

Everything is inside your own home folder; nothing needs root. It only removes a folder that really is a Sluice folder
(it has Sluice's own files), never a git checkout, and never your home folder.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import desktop, logs, selfupdate
from .model import config_path


@dataclass
class Item:
    path: Path
    what: str


@dataclass
class Plan:
    items: list = field(default_factory=list)   # Items that exist and will be removed
    kept: list = field(default_factory=list)    # (path, why) that are left alone
    install_root: Optional[Path] = None

    @property
    def nothing(self) -> bool:
        return not self.items


def _home() -> Path:
    return Path.home()


def _legacy_dirs() -> list:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or (_home() / ".config")) / "pwmix"
    state = Path(os.environ.get("XDG_STATE_HOME") or (_home() / ".local" / "state")) / "pwmix"
    return [config, state]


def folder_problem(root: Optional[Path]) -> str:
    """Why the Sluice folder will not be removed, or '' when it is safe to."""
    if root is None:
        return "this copy of Sluice is not in a Sluice folder (for example a pip install): remove it with pip"
    root = root.resolve()
    if root in (_home().resolve(), Path("/"), _home().resolve().parent) or root == Path(root.anchor):
        return "that folder is too important to remove"
    if (root / ".git").exists():
        return "it is a git checkout: delete it yourself if you want it gone"
    if not all((root / name).exists() for name in ("pyproject.toml", "install.sh", "sluice/__init__.py")):
        return "it does not look like a Sluice folder"
    if not os.access(root.parent, os.W_OK):
        return "its parent folder is not writable"
    return ""


def plan(keep_settings: bool = False, root: Optional[Path] = None) -> Plan:
    result = Plan(install_root=root if root is not None else selfupdate.install_root())
    for path, what in ((desktop.launcher_path(), "applications-menu entry"),
                       (desktop.autostart_path(), "start-at-login entry"),
                       (desktop.script_path(), "launcher script"),
                       (desktop.icon_path(), "icon"),
                       *[(p, "icon") for p in desktop.png_icon_paths()]):
        if path.exists():
            result.items.append(Item(path, what))
    settings = config_path().parent
    if settings.exists():
        if keep_settings:
            result.kept.append((settings, "your settings, presets and controller bindings (you chose to keep them)"))
        else:
            result.items.append(Item(settings, "settings, presets and controller bindings"))
    if logs.state_dir().exists():
        result.items.append(Item(logs.state_dir(), "logs and notes"))
    for path in _legacy_dirs():
        if path.exists():
            result.items.append(Item(path, "settings or logs from the old name (pwmix)"))
    problem = folder_problem(result.install_root)
    if result.install_root is not None and not problem:
        result.items.append(Item(result.install_root, "the Sluice folder, with its virtual environment"))
    elif problem:
        where = f" ({result.install_root})" if result.install_root else ""
        result.kept.append((result.install_root or Path("."), f"the program files{where} stay: {problem}"))
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
    except FileNotFoundError:
        return None
    except OSError as exc:
        return str(exc)
    return None


def execute(result: Plan, cleanup_devices: Optional[Callable[[], int]] = None, say: Callable = print) -> int:
    """Do it. Returns 0 when everything in the plan is gone, 1 when something could not be removed."""
    if cleanup_devices is not None:
        try:
            cleanup_devices()
        except Exception as exc:  # PipeWire not running is fine: there are no devices to remove then
            say(f"Could not check for leftover devices ({exc}); continuing.")
    failures = []
    desktop_paths = {i.path for i in result.items if i.what in ("applications-menu entry", "start-at-login entry",
                                                                  "launcher script", "icon")}
    if desktop_paths:
        desktop.uninstall()
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
    for path, problem in failures:
        say(f"Could not remove {logs.short_path(path)}: {problem}")
    return 1 if failures else 0


def run(keep_settings: bool = False, assume_yes: bool = False, dry_run: bool = False,
        cleanup_devices: Optional[Callable[[], int]] = None, ask: Callable = input, say: Callable = print) -> int:
    result = plan(keep_settings)
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
    code = execute(result, cleanup_devices, say)
    if code == 0:
        say("Sluice was removed. Nothing else was installed: it only used the places listed above.\n"
            "If an app is silent, restart it (some apps remember their last output). System packages such as "
            "PipeWire were not touched.")
    return code


def command_for_gui(keep_settings: bool) -> list:
    """The command the Help menu runs, after Sluice has closed, to remove itself."""
    return [sys.executable, "-m", "sluice", "--uninstall", "--yes"] + (["--keep-settings"] if keep_settings else [])
