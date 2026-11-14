# SPDX-License-Identifier: GPL-3.0-or-later
"""Uninstall: lists exactly what it removes, never removes what it should not, and removes everything it lists."""
from pathlib import Path

import pytest

from sluice import desktop, logs, uninstall
from sluice.model import config_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, sub in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                      ("XDG_STATE_HOME", ".local/state")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def make_folder(base: Path) -> Path:
    root = base / "apps" / "Sluice"
    (root / "sluice").mkdir(parents=True)
    for name in ("pyproject.toml", "install.sh", "sluice/__init__.py"):
        (root / name).write_text("x")
    (root / ".venv" / "bin").mkdir(parents=True)
    return root


def lived_in(home: Path) -> Path:
    root = make_folder(home)
    desktop.launcher_path().parent.mkdir(parents=True)
    desktop.launcher_path().write_text("x")
    desktop.script_path().parent.mkdir(parents=True)
    desktop.script_path().write_text("x")
    config_path().parent.mkdir(parents=True)
    config_path().write_text("{}")
    logs.state_dir().mkdir(parents=True)
    (logs.state_dir() / "sluice.log").write_text("x")
    return root


def test_the_plan_lists_what_exists_and_nothing_else(home):
    root = lived_in(home)
    result = uninstall.plan(root=root)
    paths = {i.path for i in result.items}
    assert {desktop.launcher_path(), desktop.script_path(), config_path().parent, logs.state_dir(), root} <= paths
    assert desktop.autostart_path() not in paths  # it was never created
    text = uninstall.describe(result)
    assert "~" in text and str(home) not in text.replace("~", "")  # no personal path is printed


def test_keeping_settings_leaves_only_that_folder(home):
    root = lived_in(home)
    result = uninstall.plan(keep_settings=True, root=root)
    assert config_path().parent not in {i.path for i in result.items}
    assert any(p == config_path().parent for p, _ in result.kept)
    assert uninstall.execute(result) == 0
    assert config_path().exists() and not root.exists() and not logs.state_dir().exists()
    assert not desktop.launcher_path().exists()


def test_everything_listed_is_removed(home):
    root = lived_in(home)
    result = uninstall.plan(root=root)
    assert uninstall.execute(result) == 0
    assert not any(i.path.exists() for i in result.items)
    assert uninstall.plan(root=root).nothing


def test_a_git_checkout_is_never_removed(home):
    root = lived_in(home)
    (root / ".git").mkdir()
    result = uninstall.plan(root=root)
    assert root not in {i.path for i in result.items}
    assert "git checkout" in uninstall.describe(result)
    uninstall.execute(result)
    assert root.exists()


@pytest.mark.parametrize("where", ["home", "parent", "root"])
def test_an_important_folder_is_refused(home, where):
    target = {"home": home, "parent": home.parent, "root": Path("/")}[where]
    assert uninstall.folder_problem(target)


def test_a_folder_that_is_not_sluice_is_refused(home):
    other = home / "stuff"
    other.mkdir()
    assert "does not look like a Sluice folder" in uninstall.folder_problem(other)
    assert uninstall.folder_problem(None)


def test_asking_first_and_refusing_removes_nothing(home):
    root = lived_in(home)
    code = uninstall.run(ask=lambda _: "no", say=lambda *_: None)
    assert code == 1 and root.exists() and config_path().exists()


def test_dry_run_changes_nothing_and_yes_skips_the_question(home, monkeypatch):
    root = lived_in(home)
    monkeypatch.setattr(uninstall.selfupdate, "install_root", lambda *a: root)
    assert uninstall.run(dry_run=True, say=lambda *_: None) == 0 and root.exists()
    assert uninstall.run(assume_yes=True, ask=lambda _: pytest.fail("asked"), say=lambda *_: None) == 0
    assert not root.exists() and not config_path().exists()


def test_a_failure_is_reported_not_hidden(home, monkeypatch):
    root = lived_in(home)
    monkeypatch.setattr(uninstall, "_remove", lambda path: "permission denied" if path == config_path().parent else None)
    said = []
    assert uninstall.execute(uninstall.plan(root=root), say=said.append) == 1
    assert any("permission denied" in line for line in said)


def test_leftover_devices_are_cleaned_first_and_a_missing_server_is_fine(home):
    root = lived_in(home)
    order = []

    def devices():
        order.append("devices")
        raise OSError("no server")

    assert uninstall.execute(uninstall.plan(root=root), devices, say=lambda *_: None) == 0
    assert order == ["devices"] and not root.exists()


def test_the_old_pwmix_folders_go_too(home):
    root = lived_in(home)
    old = home / ".config" / "pwmix"
    old.mkdir(parents=True)
    result = uninstall.plan(root=root)
    assert old in {i.path for i in result.items}
    uninstall.execute(result)
    assert not old.exists()


def test_the_command_the_menu_runs(home):
    assert uninstall.command_for_gui(True)[-3:] == ["--uninstall", "--yes", "--keep-settings"]
    assert uninstall.command_for_gui(False)[-2:] == ["--uninstall", "--yes"]
