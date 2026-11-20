# SPDX-License-Identifier: GPL-3.0-or-later
"""Put Sluice in the desktop's applications menu (and take it out again).

This writes two small files into the user's own folders (nothing needs root and nothing outside the user's home
is touched): a launcher in ``~/.local/share/applications`` and the icon in ``~/.local/share/icons``.
The launcher starts the same Python that is running now, so it keeps working from a virtual environment.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

APP_ID = "sluice"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))


def launcher_path() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def icon_path() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def png_icon_paths() -> list:
    """Every size of the PNG icon, as installed. Some desktops and older launchers ignore SVG icons."""
    return [data_home() / "icons" / "hicolor" / f"{s}x{s}" / "apps" / f"{APP_ID}.png" for s in PNG_SIZES]


def bundled_icon() -> Path:
    return Path(__file__).with_name("data") / "sluice.svg"


def bundled_png(size: int) -> Path:
    return Path(__file__).with_name("data") / "png" / f"sluice-{size}.png"


def _quote(arg: str) -> str:
    """One argument of a desktop-file ``Exec`` line (spaces, quotes and the characters the format reserves)."""
    if arg and all(c.isalnum() or c in "-_./+:=@%," for c in arg):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`").replace("%", "%%")
    return f'"{escaped}"'


def script_path() -> Path:
    return data_home() / "sluice" / "sluice-launch"


def script_text(python: Optional[str] = None) -> str:
    """A tiny shell script the menu entry runs. A launcher has no terminal, so when Sluice cannot start (a missing
    library, a second copy already running) the reason would vanish; this keeps it in launcher.log."""
    return (
        "#!/bin/sh\n"
        "# Written by 'sluice --install-desktop'. Errors from starting Sluice from the menu end up in launcher.log.\n"
        'dir="${XDG_STATE_HOME:-$HOME/.local/state}/sluice"\n'
        'mkdir -p "$dir"\n'
        'log="$dir/launcher.log"\n'
        "# Start from a neutral folder: from the home folder, a project folder named 'sluice' there would be taken for\n"
        "# the Sluice package itself and hide the installed one.\n"
        'cd "$dir" || cd /\n'
        'if [ -f "$log" ] && [ "$(wc -c < "$log")" -gt 200000 ]; then : > "$log"; fi\n'
        'echo "--- $(date) starting ($*)" >> "$log"\n'
        "# At login PipeWire may still be starting: wait for it (up to 30 s) instead of falling back to demo mode.\n"
        'if [ "$1" = "--startup" ]; then\n'
        "    shift\n"
        "    for i in $(seq 1 30); do pactl info >/dev/null 2>&1 && break; sleep 1; done\n"
        "fi\n"
        f'{shlex.quote(python or sys.executable)} -m sluice "$@" >> "$log" 2>&1\n'
        "code=$?\n"
        'if [ "$code" -ne 0 ]; then\n'
        '    echo "sluice exited with code $code" >> "$log"\n'
        '    command -v notify-send >/dev/null 2>&1 && notify-send -i sluice "Sluice could not start" "Details: $log"\n'
        "fi\n"
        "exit $code\n"
    )


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def autostart_path() -> Path:
    return config_home() / "autostart" / f"{APP_ID}.desktop"


AUTOSTART_MODES = ("off", "window", "minimized")


def autostart_text(minimized: bool, python: Optional[str] = None, script: Optional[Path] = None) -> str:
    args = " --startup --minimized" if minimized else " --startup"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Sluice\n"
        "Comment=Starts the Sluice audio mixer when you log in\n"
        f"Exec={_quote(str(script or script_path()))}{args}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-GNOME-Autostart-Delay=3\n"
    )


def autostart_state() -> str:
    """'off', 'window' or 'minimized': what logging in does now."""
    try:
        text = autostart_path().read_text(encoding="utf-8")
    except OSError:
        return "off"
    return "minimized" if "--minimized" in text else "window"


def set_autostart(mode: str, python: Optional[str] = None) -> None:
    """Start Sluice at login ('window' or 'minimized'), or stop doing so ('off'). Needs the launcher script, which it writes."""
    if mode not in AUTOSTART_MODES:
        raise ValueError(f"mode must be one of {AUTOSTART_MODES}")
    path = autostart_path()
    if mode == "off":
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    script = script_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(script_text(python), encoding="utf-8")
    script.chmod(0o755)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(autostart_text(mode == "minimized", python, script), encoding="utf-8")


def launcher_text(python: Optional[str] = None, script: Optional[Path] = None) -> str:
    exec_line = _quote(str(script)) if script else f"{_quote(python or sys.executable)} -m sluice"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Sluice\n"
        "GenericName=Audio Mixer\n"
        "Comment=Virtual audio mixer for PipeWire: channels, a Listen mix, a Broadcast mix and VST3 effects\n"
        f"Exec={exec_line}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Audio;Mixer;\n"
        "Keywords=audio;mixer;pipewire;stream;obs;microphone;vst;\n"
        f"StartupWMClass={APP_ID}\n"
    )


def install(python: Optional[str] = None) -> Path:
    """Write the launcher and the icon. Returns the launcher's path. Raises OSError if it cannot."""
    icon = icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled_icon(), icon)
    for size, target in zip(PNG_SIZES, png_icon_paths()):
        if bundled_png(size).is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bundled_png(size), target)
    script = script_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(script_text(python), encoding="utf-8")
    script.chmod(0o755)
    launcher = launcher_path()
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(launcher_text(python, script), encoding="utf-8")
    launcher.chmod(0o755)
    _refresh_menu_cache(launcher.parent)
    tool = shutil.which("gtk-update-icon-cache")
    if tool:
        try:
            subprocess.run([tool, "-q", "-t", str(data_home() / "icons" / "hicolor")], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    return launcher


def uninstall() -> bool:
    """Remove the launcher and the icon. Returns True if anything was removed."""
    removed = False
    for path in (launcher_path(), autostart_path(), script_path(), icon_path(), *png_icon_paths()):
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            pass
    _refresh_menu_cache(launcher_path().parent)
    return removed


def is_installed() -> bool:
    return launcher_path().is_file()


def launcher_problem() -> Optional[str]:
    """None if there is no launcher or it looks fine; otherwise what is wrong with it (it points at a Python that is gone)."""
    if not launcher_path().is_file():
        return None
    try:
        text = script_path().read_text(encoding="utf-8")
    except OSError:
        return "the launcher's start script is missing; run: sluice --install-desktop"
    for line in text.splitlines():
        if " -m sluice " in line and not line.startswith(("#", "echo")):
            parts = shlex.split(line)
            if parts and not os.access(parts[0], os.X_OK):
                return f"the launcher points at {parts[0]}, which no longer exists; run: sluice --install-desktop"
    return None


def _refresh_menu_cache(applications: Path) -> None:
    """Ask the desktop to notice the change right away. Optional: failing to do so is harmless."""
    tool = shutil.which("update-desktop-database")
    if tool and applications.is_dir():
        try:
            subprocess.run([tool, str(applications)], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
