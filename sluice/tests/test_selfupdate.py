# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from sluice import selfupdate
from sluice.selfupdate import UpdateError
from sluice.updates import UpdateResult, check, find_assets

PROJECT = Path(__file__).resolve().parent.parent
DEPS = 'dependencies = [\n    "numpy>=1.24",\n    "pulsectl>=23.5",\n]\n'
ZIP_URL = "https://github.com/Matt-B-007/Sluice/releases/download/v1.1.0/sluice-v1.1.0.zip"
SUM_URL = ZIP_URL + ".sha256"


def pyproject(deps=DEPS):
    return f'[project]\nname = "sluice"\nversion = "x"\n{deps}\n[project.optional-dependencies]\ndev = ["pytest"]\n'


def tree_files(version, deps=DEPS, extra=None):
    files = {
        "pyproject.toml": pyproject(deps),
        "install.sh": "#!/bin/sh\n",
        "sluice/__init__.py": f'__version__ = "{version}"\n',
        "sluice/code.py": f"# code of {version}\n",
        "README.md": f"readme {version}\n",
    }
    files.update(extra or {})
    return files


def make_root(tmp_path, version="1.0.0"):
    root = tmp_path / "install" / "sluice"
    for name, text in tree_files(version, extra={"docs/old.md": "old docs\n"}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    (root / ".venv").mkdir()
    (root / ".venv" / "keep.txt").write_text("my environment")
    (root / "mine.txt").write_text("my own file")
    return root


def make_zip(path, files, prefix="sluice/"):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(prefix + name, text)
    return path


class FakeNet:
    """Stands in for the download functions: serves one zip and a checksum file."""

    def __init__(self, tmp_path, files=None, version="1.1.0", checksum=None, prefix="sluice/"):
        self.zip = make_zip(tmp_path / "release.zip", files or tree_files(version), prefix)
        digest = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.checksum_text = checksum if checksum is not None else f"{digest}  sluice-v{version}.zip\n"
        self.fetched = []

    def fetch_text(self, url):
        self.fetched.append(url)
        return self.checksum_text

    def download(self, url, dest, progress=None):
        self.fetched.append(url)
        shutil.copy(self.zip, dest)
        if progress:
            progress(10, 10)


def result(version="1.1.0", zip_url=ZIP_URL, checksum_url=SUM_URL):
    return UpdateResult("available", "1.0.0", version, "https://example.com/r", zip_url=zip_url, checksum_url=checksum_url)


def fake_run_ok(version):
    def run(command, **kwargs):
        if "pip" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, version + "\n", "")

    return run


def stage_it(root, net, res=None, run=None):
    return selfupdate.stage(res or result(), root, fetch_text=net.fetch_text, download=net.download,
                            run=run or fake_run_ok("1.1.0"))


# ------------------------------------------------------------------------------------------ release asset discovery
def test_the_zip_and_its_checksum_are_found_among_a_releases_assets():
    release = {"tag_name": "v1.1.0", "html_url": "https://github.com/x/y/releases/tag/v1.1.0", "assets": [
        {"name": "sluice-1.1.0.tar.gz", "browser_download_url": "https://github.com/a/sluice-1.1.0.tar.gz"},
        {"name": "sluice-v1.1.0.zip", "browser_download_url": ZIP_URL},
        {"name": "sluice-v1.1.0.zip.sha256", "browser_download_url": SUM_URL},
    ]}
    assert find_assets(release) == (ZIP_URL, SUM_URL)
    found = check("1.0.0", url="https://x.example/releases", fetch=lambda u, t: [release])
    assert found.zip_url == ZIP_URL and found.checksum_url == SUM_URL
    assert find_assets({"assets": [{"name": "sluice-v1.1.0.zip", "browser_download_url": ZIP_URL}]}) == ("", "")  # no checksum
    assert find_assets({"assets": [{"name": "sluice-v1.zip", "browser_download_url": "http://x/sluice-v1.zip"},
                                   {"name": "sluice-v1.zip.sha256", "browser_download_url": "http://x/s"}]}) == ("", "")
    assert find_assets({}) == ("", "")
    same = check("1.1.0", url="https://x.example/releases", fetch=lambda u, t: [release])
    assert same.status == "up_to_date" and same.zip_url == ""


def test_checksum_files_are_read_strictly():
    h = "a" * 64
    assert selfupdate.parse_checksum(f"{h}  sluice-v1.zip\n", "sluice-v1.zip") == h
    assert selfupdate.parse_checksum(f"{h} *sluice-v1.zip", "sluice-v1.zip") == h
    assert selfupdate.parse_checksum(h, "sluice-v1.zip") == h
    assert selfupdate.parse_checksum(f"{h.upper()}  ./sluice-v1.zip", "sluice-v1.zip") == h
    assert selfupdate.parse_checksum(f"{h}  other.zip", "sluice-v1.zip") == ""
    assert selfupdate.parse_checksum("not a hash  sluice-v1.zip", "sluice-v1.zip") == ""
    assert selfupdate.parse_checksum("", "x") == ""


def test_dependencies_are_read_from_pyproject_without_the_optional_ones():
    assert selfupdate.dependencies(pyproject()) == ["numpy>=1.24", "pulsectl>=23.5"]
    assert selfupdate.dependencies("[project]\nname='x'\n") == []


# ------------------------------------------------------------------------------------------------------ whether
def test_where_updating_is_allowed(tmp_path):
    root = make_root(tmp_path)
    assert selfupdate.install_root(str(root / "sluice" / "updates.py")) == root.resolve()
    assert selfupdate.install_root(str(tmp_path / "site-packages" / "sluice" / "x.py")) is None
    assert selfupdate.unavailable_reason(root) == ""
    assert "not installed from the release zip" in selfupdate.unavailable_reason(None)
    (root / ".git").mkdir()
    assert "git pull" in selfupdate.unavailable_reason(root)  # a developer's checkout is never overwritten
    assert "git pull" in selfupdate.offer_problem(root, result())


def test_a_release_without_a_checksum_cannot_be_installed_automatically(tmp_path):
    root = make_root(tmp_path)
    assert selfupdate.offer_problem(root, result(checksum_url="")) != ""
    assert selfupdate.offer_problem(root, result()) == ""


# ------------------------------------------------------------------------------------------------------- staging
def test_a_good_release_is_downloaded_checked_and_left_waiting(tmp_path):
    root = make_root(tmp_path)
    net = FakeNet(tmp_path)
    assert stage_it(root, net) == "1.1.0"
    waiting = selfupdate.staged(root)
    assert waiting and waiting["version"] == "1.1.0"
    assert selfupdate.disk_version(root / ".update" / "tree") == "1.1.0"
    assert not list((root / ".update").glob("*.zip"))  # the zip itself is not kept
    assert selfupdate.disk_version(root) == "1.0.0"  # nothing of the installed version has changed yet
    assert (root / "sluice" / "code.py").read_text() == "# code of 1.0.0\n"
    assert net.fetched[0] == SUM_URL and ZIP_URL in net.fetched
    again = FakeNet(tmp_path)
    assert stage_it(root, again) == "1.1.0" and again.fetched == []  # already waiting: nothing is fetched twice


def test_a_download_that_does_not_match_its_checksum_is_refused(tmp_path):
    root = make_root(tmp_path)
    net = FakeNet(tmp_path, checksum=f"{'0' * 64}  sluice-v1.1.0.zip\n")
    with pytest.raises(UpdateError, match="checksum"):
        stage_it(root, net)
    assert not (root / ".update").exists()
    unreadable = FakeNet(tmp_path, checksum="garbage")
    with pytest.raises(UpdateError, match="could not be read"):
        stage_it(root, unreadable)


def test_a_release_that_is_not_the_promised_version_is_refused(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(UpdateError, match="not 1.1.0"):
        stage_it(root, FakeNet(tmp_path, files=tree_files("1.0.5")))
    with pytest.raises(UpdateError, match="missing"):
        stage_it(root, FakeNet(tmp_path, files={"sluice/__init__.py": '__version__ = "1.1.0"\n'}))
    assert not (root / ".update").exists()


def test_only_newer_versions_and_only_https_from_github_are_taken(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    net = FakeNet(tmp_path)
    monkeypatch.delenv("SLUICE_UPDATE_URL", raising=False)
    with pytest.raises(UpdateError, match="already installed"):
        stage_it(root, net, res=result(version="1.0.0"))
    with pytest.raises(UpdateError, match="https"):
        stage_it(root, net, res=result(zip_url="http://github.com/x/sluice-v1.1.0.zip"))
    with pytest.raises(UpdateError, match="only downloaded from github.com"):
        stage_it(root, net, res=result(zip_url="https://evil.example/sluice-v1.1.0.zip"))
    assert net.fetched == []
    monkeypatch.setenv("SLUICE_UPDATE_URL", "https://mirror.example/releases")  # a deliberately chosen feed
    assert stage_it(root, net, res=result(zip_url="https://mirror.example/sluice-v1.1.0.zip",
                                          checksum_url="https://mirror.example/sluice-v1.1.0.zip.sha256")) == "1.1.0"


def test_unsafe_archives_are_refused(tmp_path):
    def build(name, content=b"x", mode=None):
        path = tmp_path / "bad.zip"
        with zipfile.ZipFile(path, "w") as archive:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, content)
        return path

    with pytest.raises(UpdateError, match="unsafe path"):
        selfupdate.extract(build("sluice/../../evil.txt"), tmp_path / "out1")
    with pytest.raises(UpdateError, match="unsafe path"):
        selfupdate.extract(build("/etc/evil.txt"), tmp_path / "out2")
    with pytest.raises(UpdateError, match="link"):
        selfupdate.extract(build("sluice/link", b"/etc/passwd", mode=0o120777), tmp_path / "out3")
    notzip = tmp_path / "x.zip"
    notzip.write_bytes(b"this is not a zip")
    with pytest.raises(UpdateError, match="not a valid zip"):
        selfupdate.extract(notzip, tmp_path / "out4")
    assert not (tmp_path / "evil.txt").exists() and not Path("/etc/evil.txt").exists()


def test_an_oversized_archive_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "MAX_UNPACKED_BYTES", 10)
    path = make_zip(tmp_path / "big.zip", {"a.txt": "x" * 100})
    with pytest.raises(UpdateError, match="unreasonable size"):
        selfupdate.extract(path, tmp_path / "out")


def test_a_zip_without_a_wrapping_folder_is_unpacked_as_it_is(tmp_path):
    path = make_zip(tmp_path / "flat.zip", tree_files("1.1.0"), prefix="")
    tree = selfupdate.extract(path, tmp_path / "flat")
    assert (tree / "pyproject.toml").is_file() and selfupdate.disk_version(tree) == "1.1.0"


def test_new_packages_are_installed_first_and_a_failure_changes_nothing(tmp_path):
    root = make_root(tmp_path)
    new_deps = 'dependencies = [\n    "numpy>=1.24",\n    "pulsectl>=23.5",\n    "brandnew>=1",\n]\n'
    calls = []

    def run_ok(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    net = FakeNet(tmp_path, files=tree_files("1.1.0", deps=new_deps))
    stage_it(root, net, run=run_ok)
    assert len(calls) == 1 and calls[0][1:4] == ["-m", "pip", "install"] and "brandnew>=1" in calls[0]
    shutil.rmtree(root / ".update")

    def run_fail(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "ERROR: no matching distribution\nfor brandnew")

    with pytest.raises(UpdateError, match="could not be installed"):
        stage_it(root, net, run=run_fail)
    assert selfupdate.staged(root) is None and selfupdate.disk_version(root) == "1.0.0"
    calls.clear()
    stage_it(root, FakeNet(tmp_path), run=run_ok)  # same packages as installed: pip is not run at all
    assert calls == []


# ------------------------------------------------------------------------------------------ installing and going back
def test_installing_replaces_the_program_keeps_your_files_and_can_be_undone(tmp_path):
    root = make_root(tmp_path)
    stage_it(root, FakeNet(tmp_path, files=tree_files("1.1.0", extra={"NEW.md": "brand new file"})))
    assert selfupdate.previous_version(root) == ""
    assert selfupdate.apply_staged(root, run=fake_run_ok("1.1.0")) == "1.1.0"
    assert selfupdate.disk_version(root) == "1.1.0"
    assert (root / "sluice" / "code.py").read_text() == "# code of 1.1.0\n" and (root / "NEW.md").is_file()
    assert (root / ".venv" / "keep.txt").read_text() == "my environment"  # untouched
    assert (root / "mine.txt").read_text() == "my own file"
    assert (root / "docs" / "old.md").is_file()  # a folder the release does not contain is left alone
    assert selfupdate.staged(root) is None and not (root / ".update").exists()
    assert selfupdate.previous_version(root) == "1.0.0"

    assert selfupdate.rollback(root) == "1.0.0"
    assert selfupdate.disk_version(root) == "1.0.0"
    assert (root / "sluice" / "code.py").read_text() == "# code of 1.0.0\n"
    assert not (root / "NEW.md").exists()  # a file the update added is removed again
    assert (root / ".venv" / "keep.txt").is_file() and (root / "mine.txt").is_file()
    assert selfupdate.previous_version(root) == "" and not (root / ".previous").exists()
    with pytest.raises(UpdateError, match="no earlier version"):
        selfupdate.rollback(root)


def test_nothing_waiting_means_nothing_happens(tmp_path):
    root = make_root(tmp_path)
    assert selfupdate.apply_staged(root) is None
    assert selfupdate.disk_version(root) == "1.0.0"


def test_new_code_that_does_not_load_is_never_installed(tmp_path):
    root = make_root(tmp_path)
    stage_it(root, FakeNet(tmp_path))

    def broken(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "Traceback...\nImportError: no module named nothing")

    with pytest.raises(UpdateError, match="did not start properly"):
        selfupdate.apply_staged(root, run=broken)
    assert selfupdate.disk_version(root) == "1.0.0" and (root / "sluice" / "code.py").read_text() == "# code of 1.0.0\n"
    assert selfupdate.staged(root) is None  # the bad download is thrown away
    stage_it(root, FakeNet(tmp_path))
    with pytest.raises(UpdateError, match="did not start properly"):
        selfupdate.apply_staged(root, run=fake_run_ok("9.9.9"))  # loads, but reports another version


def test_a_failure_half_way_through_the_swap_puts_the_old_files_back(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    stage_it(root, FakeNet(tmp_path, files=tree_files("1.1.0", extra={"NEW.md": "new"})))
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 5:
            raise OSError("disk went away")
        return real(src, dst)

    monkeypatch.setattr(selfupdate.os, "replace", flaky)
    with pytest.raises(UpdateError, match="as it was"):
        selfupdate.apply_staged(root, run=fake_run_ok("1.1.0"))
    monkeypatch.setattr(selfupdate.os, "replace", real)
    assert selfupdate.disk_version(root) == "1.0.0"
    assert (root / "sluice" / "code.py").read_text() == "# code of 1.0.0\n"
    assert (root / "README.md").read_text() == "readme 1.0.0\n" and (root / "install.sh").is_file()
    assert not (root / "NEW.md").exists() and (root / ".venv" / "keep.txt").is_file()


def test_a_stale_waiting_update_is_dropped(tmp_path):
    root = make_root(tmp_path, version="1.2.0")  # already newer than what is waiting
    stage_dir = root / ".update" / "tree"
    for name, text in tree_files("1.1.0").items():
        (stage_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (stage_dir / name).write_text(text)
    (root / ".update" / "ready.json").write_text(json.dumps({"version": "1.1.0"}))
    assert selfupdate.apply_staged(root) is None
    assert not (root / ".update").exists() and selfupdate.disk_version(root) == "1.2.0"


def test_closing_sluice_installs_a_waiting_update_and_never_raises(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    stage_it(root, FakeNet(tmp_path))
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: root)
    monkeypatch.setattr(subprocess, "run", fake_run_ok("1.1.0"))
    assert selfupdate.apply_staged_quietly() == "1.1.0" and selfupdate.disk_version(root) == "1.1.0"
    assert selfupdate.apply_staged_quietly() is None  # nothing left
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert selfupdate.apply_staged_quietly() is None  # an error is logged, not raised, so closing always works


def test_a_git_checkout_is_never_changed_when_closing(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    stage_it(root, FakeNet(tmp_path))
    (root / ".git").mkdir()
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: root)
    assert selfupdate.apply_staged_quietly() is None and selfupdate.disk_version(root) == "1.0.0"


def test_the_real_check_accepts_this_very_program_as_new_code(tmp_path):
    """No fakes: copy this project as 'version 9.9.9' and let the real try-out start it in a separate process."""
    root = make_root(tmp_path)
    new = tmp_path / "new"
    shutil.copytree(PROJECT / "sluice", new / "sluice", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "install.sh"):
        shutil.copy(PROJECT / name, new / name)
    init = new / "sluice" / "__init__.py"
    init.write_text(init.read_text().replace(selfupdate.disk_version(PROJECT), "9.9.9"))
    files = {str(p.relative_to(new)): p.read_text(errors="replace") for p in new.rglob("*") if p.is_file()}
    net = FakeNet(tmp_path, files=files, version="9.9.9")
    stage_it(root, net, res=result(version="9.9.9", zip_url=ZIP_URL.replace("1.1.0", "9.9.9"),
                                   checksum_url=SUM_URL.replace("1.1.0", "9.9.9")),
             run=lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    assert selfupdate.apply_staged(root) == "9.9.9"  # the default runner: a real process imports the new code
    assert selfupdate.disk_version(root) == "9.9.9"


def test_the_try_out_rejects_code_that_really_cannot_be_imported(tmp_path):
    root = make_root(tmp_path)  # a "release" whose sluice package has no engine module: the real try-out must fail
    stage_it(root, FakeNet(tmp_path))
    with pytest.raises(UpdateError, match="did not start properly"):
        selfupdate.apply_staged(root)
    assert selfupdate.disk_version(root) == "1.0.0"


# ----------------------------------------------------------------------------------------------- the command line
def test_sluice_rollback_on_the_command_line(tmp_path, monkeypatch, capsys):
    from sluice import __main__ as entry

    root = make_root(tmp_path)
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: root)
    monkeypatch.setattr(entry, "_acquire_lock", lambda: object())
    monkeypatch.setattr(entry.logs, "setup", lambda debug=False, session=True: None)
    monkeypatch.setattr(entry.logs, "shutdown", lambda: None)
    assert entry.main(["--rollback"]) == 1 and "no earlier version" in capsys.readouterr().err
    stage_it(root, FakeNet(tmp_path))
    selfupdate.apply_staged(root, run=fake_run_ok("1.1.0"))
    monkeypatch.setattr(entry, "_acquire_lock", lambda: None)  # Sluice is running
    assert entry.main(["--rollback"]) == 1 and "is running" in capsys.readouterr().err
    assert selfupdate.disk_version(root) == "1.1.0"
    monkeypatch.setattr(entry, "_acquire_lock", lambda: object())
    assert entry.main(["--rollback"]) == 0 and "Went back to Sluice 1.0.0" in capsys.readouterr().out
    assert selfupdate.disk_version(root) == "1.0.0"


def test_downloads_follow_only_https_redirects():
    import urllib.error
    import urllib.request

    handler = selfupdate._HttpsOnly()
    request = urllib.request.Request("https://github.com/x")
    with pytest.raises(urllib.error.URLError, match="not https"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "http://evil.example/x")


def test_settings_remember_automatic_updates_and_default_to_off():
    from sluice.model import Mixer

    mixer = Mixer.default()
    assert mixer.auto_update is False and mixer.to_dict()["auto_update"] is False
    mixer.auto_update = True
    assert Mixer.from_dict(mixer.to_dict()).auto_update is True
    data = mixer.to_dict()
    data["auto_update"] = "yes"  # anything that is not exactly true means off
    assert Mixer.from_dict(data).auto_update is False
    del data["auto_update"]  # a settings file from before 0.9.1
    assert Mixer.from_dict(data).auto_update is False


def test_this_python_can_run_the_try_out_snippet_syntax():
    compile(selfupdate._CHECK, "<check>", "exec")
    assert sys.executable
