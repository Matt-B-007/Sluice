# SPDX-License-Identifier: GPL-3.0-or-later
"""Uninstall: lists exactly what it removes, never removes what it should not, and removes everything it lists."""

from pathlib import Path

import pytest

from sluice import launcher, logs, uninstall
from sluice.model import config_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, sub in (
        ("HOME", ""),
        ("XDG_CONFIG_HOME", ".config"),
        ("XDG_DATA_HOME", ".local/share"),
        ("XDG_STATE_HOME", ".local/state"),
    ):
        monkeypatch.setenv(name, str(tmp_path / sub))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    # 0.13.1: no Sluice running, whatever runs on the computer (the final check reads the real process list: an open Sluice
    # made these tests fail on the developer's computer only)
    monkeypatch.setattr(uninstall, "running_processes", lambda exclude=None: [])
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
    launcher.launcher_path().parent.mkdir(parents=True, exist_ok=True)
    launcher.launcher_path().write_text("x")
    launcher.script_path().parent.mkdir(parents=True, exist_ok=True)
    launcher.script_path().write_text("x")
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text("{}")
    logs.state_dir().mkdir(parents=True, exist_ok=True)
    (logs.state_dir() / "sluice.log").write_text("x")
    return root


def test_the_plan_lists_what_exists_and_nothing_else(home):
    root = lived_in(home)
    result = uninstall.plan(root=root)
    paths = {i.path for i in result.items}
    assert {launcher.launcher_path(), launcher.script_path(), config_path().parent, logs.state_dir(), root} <= paths
    assert launcher.autostart_path() not in paths  # it was never created
    text = uninstall.describe(result)
    assert "~" in text and str(home) not in text.replace("~", "")  # no personal path is printed


def test_keeping_settings_leaves_only_that_folder(home):
    root = lived_in(home)
    result = uninstall.plan(keep_settings=True, root=root)
    assert config_path().parent not in {i.path for i in result.items}
    assert any(p == config_path().parent for p, _ in result.kept)
    assert uninstall.execute(result) == 0
    # 0.13.1-beta.3: the box reads "Also delete my settings and logs", so with it unticked the logs stay too (they were removed)
    assert config_path().exists() and not root.exists() and logs.state_dir().exists()
    assert any(p == logs.state_dir() for p, _ in result.kept)
    assert not launcher.launcher_path().exists()


def test_everything_listed_is_removed(home):
    root = lived_in(home)
    result = uninstall.plan(root=root)
    assert uninstall.execute(result) == 0
    assert not any(i.path.exists() for i in result.items)
    assert uninstall.plan(root=root).nothing


def test_a_git_clone_stays_unless_you_say_it_may_go(home):
    root = lived_in(home)
    (root / ".git").mkdir()
    result = uninstall.plan(root=root)
    assert root not in {i.path for i in result.items}
    assert result.git_folder and result.asks_about_git
    assert "git clone" in uninstall.describe(result)
    uninstall.execute(result)
    assert root.exists()


def test_a_git_clone_is_removed_when_asked_and_the_list_warns(home):
    root = lived_in(home)
    (root / ".git").mkdir()
    result = uninstall.plan(root=root, remove_git=True)
    assert root in {i.path for i in result.items} and not result.asks_about_git
    assert "unpushed" in uninstall.describe(result)
    assert uninstall.execute(result) == 0 and not root.exists()


def test_keeping_settings_never_removes_a_git_clone_even_if_asked(home):
    root = lived_in(home)
    (root / ".git").mkdir()
    result = uninstall.plan(keep_settings=True, root=root, remove_git=True)
    assert root not in {i.path for i in result.items} and not result.asks_about_git


def test_the_git_question_is_asked_on_the_command_line(home, monkeypatch):
    root = lived_in(home)
    (root / ".git").mkdir()
    monkeypatch.setattr(uninstall.update_install, "install_root", lambda *a: root)
    answers = iter(["yes", "yes"])
    assert uninstall.run(ask=lambda _: next(answers), say=lambda *_: None) == 0
    assert not root.exists()
    root = lived_in(home)
    (root / ".git").mkdir()
    answers = iter(["no", "yes"])
    uninstall.run(ask=lambda _: next(answers), say=lambda *_: None)
    assert root.exists() and not config_path().exists()


def test_lock_and_socket_files_are_removed(home, monkeypatch):
    runtime = home / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    (runtime / "sluice.lock").write_text("1 0.10.0")
    (runtime / "sluice-control.sock").write_text("")
    root = lived_in(home)
    result = uninstall.plan(root=root)
    assert {runtime / "sluice.lock", runtime / "sluice-control.sock"} <= {i.path for i in result.items}
    assert uninstall.execute(result) == 0
    assert not (runtime / "sluice.lock").exists()


def test_the_crash_log_and_the_build_folders_go_with_their_folders(home):
    root = lived_in(home)
    (logs.state_dir() / "crash.log").write_text("x")
    for sub in (".update", ".previous", "rust/sluice_dsp/target"):
        (root / sub).mkdir(parents=True)
        (root / sub / "f").write_text("x")
    assert uninstall.execute(uninstall.plan(root=root)) == 0
    assert not root.exists() and not logs.state_dir().exists()


def test_caches_are_cleared_only_when_asked(home, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("CARGO_HOME", str(home / ".cargo"))
    for path, _ in uninstall.cache_dirs():
        path.mkdir(parents=True)
        (path / "x").write_text("x")
    root = lived_in(home)
    plain = uninstall.plan(root=root)
    assert not any("download cache" in i.what for i in plain.items)
    asked = uninstall.plan(root=root, clear_caches=True)
    assert sum("download cache" in i.what for i in asked.items) == 2
    assert "shared with other programs" in uninstall.describe(asked)
    uninstall.execute(plain)
    assert all(p.exists() for p, _ in uninstall.cache_dirs())
    assert uninstall.execute(asked) == 0
    assert not any(p.exists() for p, _ in uninstall.cache_dirs())


def test_the_final_check_says_nothing_is_left_or_names_what_is(home):
    root = lived_in(home)
    said = []
    result = uninstall.plan(root=root)
    assert uninstall.execute(result, say=said.append, list_devices=lambda: [], check=True) == 0
    assert any("nothing of Sluice is left" in line for line in said)
    root = lived_in(home)
    said = []
    result = uninstall.plan(root=root)
    code = uninstall.execute(result, say=said.append, list_devices=lambda: ["sluice_listen"], check=True)
    assert code == 1 and any("sluice_listen" in line for line in said)


def test_the_check_names_a_file_that_could_not_be_removed(home, monkeypatch):
    root = lived_in(home)
    monkeypatch.setattr(uninstall, "_remove", lambda path: "busy" if path == logs.state_dir() else None)
    said = []
    assert uninstall.execute(uninstall.plan(root=root), say=said.append, check=True) == 1
    assert any("still there" in line for line in said)


def test_keeping_settings_says_so_in_the_final_check(home):
    root = lived_in(home)
    said = []
    assert uninstall.execute(uninstall.plan(keep_settings=True, root=root), say=said.append, check=True) == 0
    assert any("except what you chose to keep" in line for line in said)


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
    monkeypatch.setattr(uninstall.update_install, "install_root", lambda *a: root)
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
    full = uninstall.command_for_gui(False, clear_caches=True, remove_git=True)
    assert "--clear-caches" in full and "--remove-git-folder" in full
    assert "--remove-git-folder" not in uninstall.command_for_gui(True, remove_git=True)


def test_a_sluice_still_running_is_named_in_the_final_check(home, monkeypatch):
    """The real behaviour the fake list above hides: uninstalling while Sluice is open says so."""
    monkeypatch.setattr(uninstall, "running_processes", lambda exclude=None: [(4242, "python -m sluice")])
    result = uninstall.plan(keep_settings=False, root=make_folder(home))
    left = uninstall.leftovers(result)
    assert "a Sluice program is still running (process 4242: python -m sluice)" in left


def test_the_real_process_list_finds_a_running_sluice(a_sluice_is_running):
    """The pretend Sluice the whole test run has open is what the real check finds."""
    assert any(pid == a_sluice_is_running.pid for pid, _command in uninstall.running_processes())
