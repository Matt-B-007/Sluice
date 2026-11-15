# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sluice import desktop


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)  # never run update-desktop-database in tests
    return tmp_path / "share"


def _with_project_on_path() -> dict:
    """The launch script leaves the start folder, so a Sluice that is only importable from a source checkout (as in
    these tests) needs saying where it is. A real install does not."""
    root = str(Path(desktop.__file__).resolve().parents[1])
    return {**os.environ, "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", "")}


def test_launcher_text_is_a_valid_desktop_entry():
    text = desktop.launcher_text("/home/me/sluice/.venv/bin/python")
    lines = dict(line.split("=", 1) for line in text.strip().splitlines() if "=" in line)
    assert text.startswith("[Desktop Entry]\n")
    assert lines["Type"] == "Application" and lines["Name"] == "Sluice" and lines["Terminal"] == "false"
    assert lines["Exec"] == "/home/me/sluice/.venv/bin/python -m sluice"
    with_script = desktop.launcher_text("/home/me/sluice/.venv/bin/python", Path("/home/me/.local/share/sluice/sluice-launch"))
    assert "Exec=/home/me/.local/share/sluice/sluice-launch\n" in with_script
    assert lines["Icon"] == "sluice" and lines["StartupWMClass"] == "sluice"
    assert lines["Categories"].endswith(";") and "Audio" in lines["Categories"]


def test_exec_quotes_paths_with_spaces_and_reserved_characters():
    assert desktop._quote("/usr/bin/python3") == "/usr/bin/python3"
    assert desktop._quote("/home/my user/venv/bin/python") == '"/home/my user/venv/bin/python"'
    assert desktop._quote('/a"b$c`d%e') == '"/a\\"b\\$c\\`d%%e"'
    assert 'Exec="/home/my user/v/bin/python" -m sluice' in desktop.launcher_text("/home/my user/v/bin/python")


def test_install_writes_the_launcher_and_icon_and_uninstall_removes_them(data_home):
    assert not desktop.is_installed()
    launcher = desktop.install("/x/python")
    assert launcher == data_home / "applications" / "sluice.desktop" and desktop.is_installed()
    assert os.access(launcher, os.X_OK)
    icon = data_home / "icons" / "hicolor" / "scalable" / "apps" / "sluice.svg"
    assert icon.read_text().lstrip().startswith("<svg") and "Sluice" in icon.read_text()
    for path in desktop.png_icon_paths():  # PNG sizes too, for desktops that ignore SVG
        assert path.is_file() and path.read_bytes().startswith(b"\x89PNG")
    assert len(desktop.png_icon_paths()) == 8
    desktop.install("/y/python")  # again: just rewrites
    assert "/y/python -m sluice" in desktop.script_path().read_text()
    assert os.access(desktop.script_path(), os.X_OK) and "launcher.log" in desktop.script_path().read_text()
    assert str(desktop.script_path()) in launcher.read_text()
    assert "no longer exists" in desktop.launcher_problem()  # /y/python is not a real file
    desktop.install(sys.executable)
    assert desktop.launcher_problem() is None
    assert desktop.uninstall() is True and not launcher.exists() and not icon.exists()
    assert not any(path.exists() for path in desktop.png_icon_paths())
    assert desktop.uninstall() is False


def test_the_bundled_icons_ship_with_the_package():
    assert desktop.bundled_icon().is_file()
    assert all(desktop.bundled_png(size).is_file() for size in desktop.PNG_SIZES)


def test_command_line_installs_and_removes(tmp_path):
    env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "share"), "XDG_STATE_HOME": str(tmp_path / "s"),
           "XDG_CONFIG_HOME": str(tmp_path / "c"), "PATH": "/nonexistent:" + os.defpath, "QT_QPA_PLATFORM": "offscreen"}

    def run(*args):
        return subprocess.run([sys.executable, "-m", "sluice", *args], env=env, capture_output=True, text=True, timeout=60)

    first = run("--install-desktop")
    assert first.returncode == 0 and "applications menu" in first.stdout
    desktop_file = tmp_path / "share" / "applications" / "sluice.desktop"
    assert desktop_file.is_file() and "sluice-launch" in desktop_file.read_text()
    assert sys.executable in (tmp_path / "share" / "sluice" / "sluice-launch").read_text()
    assert run("--uninstall-desktop").stdout.startswith("Removed Sluice")
    assert not desktop_file.exists()
    assert "was not in" in run("--uninstall-desktop").stdout


def test_the_launch_script_really_starts_sluice_and_logs(tmp_path, data_home, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    desktop.install(sys.executable)
    result = subprocess.run([str(desktop.script_path()), "--version"], capture_output=True, text=True, timeout=60, env=_with_project_on_path())
    assert result.returncode == 0
    log = (tmp_path / "state" / "sluice" / "launcher.log").read_text()
    assert "starting (--version)" in log and "sluice " in log


def test_autostart_modes(data_home, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert desktop.autostart_state() == "off"
    desktop.set_autostart("window", sys.executable)
    text = desktop.autostart_path().read_text()
    assert "--startup" in text and "--minimized" not in text and "X-GNOME-Autostart-enabled=true" in text
    assert desktop.autostart_state() == "window" and os.access(desktop.script_path(), os.X_OK)
    desktop.set_autostart("minimized", sys.executable)
    assert desktop.autostart_state() == "minimized" and "--startup --minimized" in desktop.autostart_path().read_text()
    desktop.set_autostart("off")
    assert desktop.autostart_state() == "off" and not desktop.autostart_path().exists()
    desktop.set_autostart("window", sys.executable)
    desktop.uninstall()  # removing the launcher also removes the autostart entry
    assert desktop.autostart_state() == "off"
    with pytest.raises(ValueError):
        desktop.set_autostart("sometimes")


def test_the_launch_script_reports_failure_and_waits_only_at_startup(tmp_path, data_home, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    desktop.install("/bin/false")  # a "Python" that always fails
    result = subprocess.run([str(desktop.script_path()), "--minimized"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "exited with code 1" in (tmp_path / "state" / "sluice" / "launcher.log").read_text()


def test_the_launch_script_is_not_fooled_by_a_folder_named_sluice_in_the_start_folder(tmp_path, data_home, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / "home" / "sluice" / "sluice").mkdir(parents=True)  # like ~/sluice (the project) with no __init__ in it
    desktop.install(sys.executable)
    text = desktop.script_path().read_text()
    assert text.index('cd "$dir"') < text.index("-m sluice")  # leaves the start folder before starting Python
    result = subprocess.run([str(desktop.script_path()), "--version"], capture_output=True, text=True, timeout=60,
                            cwd=tmp_path / "home", env=_with_project_on_path())
    assert result.returncode == 0
