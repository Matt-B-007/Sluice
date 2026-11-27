# SPDX-License-Identifier: GPL-3.0-or-later
"""0.12.0: Sluice is installed in ~/.local/share/sluice/program, never left running from the folder it was downloaded to."""

import os
import subprocess
from pathlib import Path

import pytest

from sluice import launcher, reconnect, uninstall, update_install

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_BIN_HOME"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def sluice_folder(path: Path, git: bool = False) -> Path:
    (path / "sluice").mkdir(parents=True)
    for name in ("pyproject.toml", "install.sh", "sluice/__init__.py"):
        (path / name).write_text("x")
    if git:
        (path / ".git").mkdir()
    return path


def test_the_places(home):
    assert launcher.program_dir() == home / ".local/share/sluice/program"
    assert launcher.script_path().parent == launcher.program_dir().parent  # one Sluice folder in your data folder
    assert launcher.command_path() == home / ".local/bin/sluice"


def test_only_a_plain_download_is_offered_the_move(home, tmp_path):
    download = sluice_folder(tmp_path / "Downloads/sluice")
    assert update_install.runs_from_download(download)
    assert not update_install.runs_from_download(sluice_folder(tmp_path / "work/sluice", git=True))  # someone's own clone
    assert not update_install.runs_from_download(sluice_folder(launcher.program_dir()))  # the installed copy itself
    assert not update_install.runs_from_download(None)


def test_the_moved_copy_deletes_the_download_but_never_a_clone(home, tmp_path):
    download = sluice_folder(tmp_path / "Downloads/sluice")
    message = update_install.finish_move(download)
    assert not download.exists() and "was deleted" in message
    clone = sluice_folder(tmp_path / "work/sluice", git=True)
    assert clone.exists() and "left as it is" in update_install.finish_move(clone) and clone.exists()
    assert "now runs from" in update_install.finish_move(tmp_path / "gone")


def test_the_move_runs_install_sh_then_starts_the_new_copy_which_deletes_the_old(home, tmp_path):
    command = update_install.move_script(tmp_path / "Downloads/sluice")
    assert command[:2] == ["sh", "-c"]
    script = command[2]
    assert 'bash "$1/install.sh" --no-system --yes' in script and 'exec "$2" --finish-move "$1"' in script
    assert 'exec "$1/.venv/bin/sluice"' in script  # if install.sh fails, the old copy starts again
    assert command[4:6] == [str(tmp_path / "Downloads/sluice"), str(launcher.program_dir() / ".venv/bin/sluice")]


def test_a_restart_does_not_repeat_the_move(monkeypatch):
    monkeypatch.setattr("sys.orig_argv", ["python", "-m", "sluice", "--finish-move", "/old", "--minimized"], raising=False)
    assert "--finish-move" not in reconnect.restart_command(True) and "/old" not in reconnect.restart_command(True)


def test_uninstall_removes_the_command_only_if_it_is_ours_and_the_empty_sluice_folder(home, monkeypatch):
    command = launcher.command_path()
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n" + launcher.COMMAND_MARK + ": starts Sluice\nexec x\n")
    program = sluice_folder(launcher.program_dir())
    result = uninstall.plan(root=program)
    assert any(item.path == command for item in result.items)
    assert uninstall.execute(result, say=lambda *_: None) == 0
    assert not command.exists() and not launcher.sluice_home().exists()
    command.write_text("#!/bin/sh\nexec some-other-sluice\n")  # another program's: left alone
    assert not any(item.path == command for item in uninstall.plan(root=None).items)


def test_install_sh_installs_in_its_own_folder_and_offers_to_delete_the_download():
    text = (ROOT / "install.sh").read_text()
    assert 'target="$data_home/sluice/program"' in text
    assert "--exclude=./.venv --exclude=./.git" in text  # the download's environment and history are not copied
    assert "Delete it now? [y/N]" in text  # asked, never silent
    assert '[ -e "$download/.git" ] && safe=0' in text  # a clone is never offered for deletion
    assert "--in-place" in text and "--no-desktop" in text
    assert "Written by Sluice's install.sh" in text and launcher.COMMAND_MARK.lstrip("# ") in text


def test_a_dry_run_changes_nothing(home, tmp_path):
    env = dict(os.environ, HOME=str(home), SLUICE_ALLOW_ROOT="1", SLUICE_NO_RUST="1")
    for name in ("XDG_DATA_HOME", "XDG_BIN_HOME"):
        env.pop(name, None)
    out = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--dry-run", "--no-system"], env=env, capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert f"copy the program files from {ROOT}" in out.stdout
    assert ("would offer to delete" in out.stdout) != (ROOT / ".git").exists()  # never for a git clone
    assert not (home / ".local").exists()


def test_settings_offers_the_move_only_to_a_copy_in_its_download_folder(qapp, tmp_path, monkeypatch):
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow

    for downloaded in (True, False):
        engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
        engine.start()
        monkeypatch.setattr(update_install, "runs_from_download", lambda root, d=downloaded: d)
        win = MainWindow(engine, tmp_path / f"config-{downloaded}.json")
        try:
            win.open_settings("Updates")
            assert hasattr(win.settings_window, "move_button") == downloaded
            win.offer_move_once()
            assert ("move-out-of-download" in engine.mixer.hints_seen) == downloaded
        finally:
            win.shutdown()
