# SPDX-License-Identifier: GPL-3.0-or-later
"""0.12.2: the one-line installer (get.sh), the Stable and Beta channels, and versions that sort as people mean them."""
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from sluice import update_check
from sluice.update_check import is_newer, is_prerelease, pick_release, version_key

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("older,newer", [
    ("0.12.2", "0.13.0-beta.1"), ("0.13.0-beta.1", "0.13.0-beta.2"), ("0.13.0-beta.2", "0.13.0-rc.1"),
    ("0.13.0-rc.1", "0.13.0"), ("0.13.0", "0.13.1"), ("v0.9.9", "v0.10.0"), ("0.13.0-alpha", "0.13.0-beta"),
])
def test_versions_sort_as_people_mean_them(older, newer):
    assert is_newer(newer, older) and not is_newer(older, newer)


def test_a_beta_is_not_the_same_as_its_final_release():
    """Before 0.12.2 "-beta" was dropped: 0.13.0-beta.1 and 0.13.0 were equal, so beta users were never offered 0.13.0."""
    assert version_key("0.13.0-beta.1") != version_key("0.13.0") and is_newer("0.13.0", "0.13.0-beta.1")
    assert is_prerelease("0.13.0-beta.1") and is_prerelease("v1.0.0rc2") and not is_prerelease("0.13.0")


RELEASES = [
    {"tag_name": "v0.13.0-beta.2", "prerelease": True}, {"tag_name": "v0.13.0-beta.1", "prerelease": True},
    {"tag_name": "v0.12.3", "prerelease": False, "draft": True}, {"tag_name": "v0.12.2", "prerelease": False},
    {"tag_name": "v0.12.1", "prerelease": False},
]


def test_stable_takes_only_full_releases_and_beta_takes_the_newest():
    assert pick_release(RELEASES, "stable")["tag_name"] == "v0.12.2"  # (drafts never count)
    assert pick_release(RELEASES, "beta")["tag_name"] == "v0.13.0-beta.2"
    marked_only_by_name = [{"tag_name": "v0.14.0-beta.1"}, {"tag_name": "v0.13.0"}]
    assert pick_release(marked_only_by_name, "stable")["tag_name"] == "v0.13.0"
    # the name decides, not GitHub's tick: every release before 0.12.2 was ticked as a pre-release by the old workflow
    old_workflow = [{"tag_name": "v0.12.1", "prerelease": True}, {"tag_name": "v0.12.0", "prerelease": True}]
    assert pick_release(old_workflow, "stable")["tag_name"] == "v0.12.1"


def test_check_follows_the_channel_and_can_go_back_to_stable():
    fetch = lambda url, timeout: [dict(r, html_url="https://example.org/r") for r in RELEASES]  # noqa: E731
    assert update_check.check("0.12.2", fetch=fetch).status == "up_to_date"
    beta = update_check.check("0.12.2", fetch=fetch, channel="beta")
    assert beta.status == "available" and beta.latest == "0.13.0-beta.2"
    assert update_check.check("0.13.0-beta.2", fetch=fetch, channel="stable").status == "up_to_date"  # waits for stable
    back = update_check.check("0.13.0-beta.2", fetch=fetch, channel="stable", allow_older=True)
    assert back.status == "available" and back.latest == "0.12.2"  # "Go to the latest stable now"


def test_the_channel_is_saved():
    from sluice.model import Mixer
    mixer = Mixer.demo()
    assert mixer.update_channel == "stable"
    mixer.update_channel = "beta"
    assert Mixer.from_dict(json.loads(json.dumps(mixer.to_dict()))).update_channel == "beta"
    data = mixer.to_dict()
    data["update_channel"] = "nightly"
    assert Mixer.from_dict(data).update_channel == "stable"


def test_settings_offers_stable_and_beta(qapp, tmp_path, monkeypatch):
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    try:
        win.open_settings("Updates")
        win.channel_actions["beta"].trigger()
        assert engine.mixer.update_channel == "beta" and "Beta" in win.status_label.text()
        win.set_update_channel("stable", ask=False)
        assert engine.mixer.update_channel == "stable" and win.channel_actions["stable"].isChecked()
    finally:
        win.shutdown()


# ----------------------------------------------------------------------------- get.sh, run for real against a local "GitHub"
def release(tmp_path: Path, tag: str, version: str) -> dict:
    folder = tmp_path / "rel"
    folder.mkdir(exist_ok=True)
    zip_path = folder / f"sluice-{tag}.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("sluice/install.sh", '#!/usr/bin/env bash\necho "installing ' + version + ' with: $*"\n'
                   'echo "from get: ${SLUICE_FROM_GET:-}"\npwd > "$HOME/install-ran-in"\n')
        z.writestr("sluice/sluice/__init__.py", f'__version__ = "{version}"\n')
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (folder / f"sluice-{tag}.zip.sha256").write_text(f"{digest}  sluice-{tag}.zip\n")
    url = zip_path.as_uri()
    return {"tag_name": tag, "prerelease": "beta" in tag, "assets": [
        {"name": zip_path.name, "browser_download_url": url}, {"name": zip_path.name + ".sha256", "browser_download_url": url + ".sha256"}]}


def run_get(tmp_path: Path, releases: list, *args: str) -> subprocess.CompletedProcess:
    feed = tmp_path / "releases.json"
    feed.write_text(json.dumps(releases))
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), SLUICE_RELEASES_URL=feed.as_uri(), SLUICE_ALLOW_ROOT="1", TMPDIR=str(tmp_path))
    script = (ROOT / "get.sh").read_text()
    return subprocess.run(["bash", "-s", "--", *args], input=script, capture_output=True, text=True, env=env, timeout=120)


def test_get_sh_installs_the_latest_stable_release_and_leaves_nothing(tmp_path):
    releases = [release(tmp_path, "v0.13.0-beta.1", "0.13.0-beta.1"), release(tmp_path, "v0.12.2", "0.12.2")]
    out = run_get(tmp_path, releases, "--no-system")
    assert out.returncode == 0, out.stderr
    assert "matches its checksum" in out.stdout and "installing 0.12.2 with: --yes --no-system" in out.stdout
    assert "from get: 1" in out.stdout  # so install.sh does not offer to delete get.sh's own download
    assert not list(tmp_path.glob("sluice-get.*"))  # the download is gone


def test_get_sh_beta_and_a_particular_version(tmp_path):
    releases = [release(tmp_path, "v0.13.0-beta.1", "0.13.0-beta.1"), release(tmp_path, "v0.12.2", "0.12.2"),
                release(tmp_path, "v0.12.1", "0.12.1")]
    assert "installing 0.13.0-beta.1" in run_get(tmp_path, releases, "--beta").stdout
    assert "installing 0.12.1" in run_get(tmp_path, releases, "--version", "0.12.1").stdout


def test_get_sh_refuses_a_download_that_does_not_match_its_checksum(tmp_path):
    rel = release(tmp_path, "v0.12.2", "0.12.2")
    (tmp_path / "rel" / "sluice-v0.12.2.zip.sha256").write_text("0" * 64 + "  sluice-v0.12.2.zip\n")
    out = run_get(tmp_path, [rel])
    assert out.returncode != 0 and "does not match its checksum" in out.stderr and "installing" not in out.stdout


def test_get_sh_says_plainly_when_there_is_nothing_to_install(tmp_path):
    out = run_get(tmp_path, [{"tag_name": "v0.12.2", "assets": []}])
    assert out.returncode != 0 and "no stable release with a downloadable zip" in out.stderr


def test_the_double_click_installer_and_the_release_tool_are_there():
    desktop = (ROOT / "Install Sluice.desktop").read_text()
    assert "Terminal=true" in desktop and "install.sh" in desktop and "%k" in desktop
    assert os.access(ROOT / "get.sh", os.X_OK) and os.access(ROOT / "tools" / "make-release.sh", os.X_OK)
    assert "--prerelease" in (ROOT / "tools" / "make-release.sh").read_text()


# ----------------------------------------------------------------------------- releasing: the tag can never disagree with the code
def _load_checker():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_version", ROOT / "tools" / "check-version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_version_files_and_the_changelogs_agree():
    """What the Release workflow checks, checked on every test run, so a release never fails on it."""
    assert _load_checker().problems() == []


def test_a_tag_that_does_not_match_the_code_is_explained(tmp_path):
    checker = _load_checker()
    version = checker.read_version()
    assert checker.problems(tag=f"v{version}") == []
    (wrong,) = checker.problems(tag="v99.0.0")
    assert "does not match" in wrong and "Run workflow" in wrong and "release.sh --set 99.0.0" in wrong


def test_release_sh_sets_a_new_version_everywhere(tmp_path):
    import shutil
    for name in ("sluice/__init__.py", "pyproject.toml", "CHANGELOG.md", "sluice/data/CHANGELOG.md", "tools/release.sh",
                 "tools/check-version.py", "README.md"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    out = subprocess.run(["bash", "tools/release.sh", "--set", "0.99.0-beta.1"], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    checker = _load_checker()
    assert checker.problems(tmp_path) == [] and checker.read_version(tmp_path) == "0.99.0-beta.1"
    assert "(say what changed)" in (tmp_path / "CHANGELOG.md").read_text()  # and release.sh refuses to tag until it is written
    assert "## What's new in 0.99.0-beta.1\n\n- (say what changed)" in (tmp_path / "README.md").read_text()
    bad = subprocess.run(["bash", "tools/release.sh", "--set", "0.99"], cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode != 0 and "not a version" in (bad.stderr + bad.stdout)


def test_the_release_workflow_makes_test_versions_pre_releases_and_nothing_else():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    script = (ROOT / "scripts" / "check.sh").read_text()  # 0.12.5: the tag check is in the one check script
    assert "check.sh shell python release" in workflow and 'check-version.py --tag "$TAG" --new' in script
    assert "workflow_dispatch" in workflow
    assert "startsWith(github.ref_name, 'v0.')" not in workflow  # every 0.x used to be a pre-release, hiding it from Stable


@pytest.mark.parametrize("version,tags,ok,says", [
    ("0.1.1-beta.1", ["v0.1.0", "v0.1.1"], False, "0.1.2-beta.1"),  # the slip: a beta of a version that is already out
    ("0.1.2-beta.1", ["v0.1.0", "v0.1.1"], True, ""),
    ("0.1.2", ["v0.1.1", "v0.1.2-beta.3"], True, ""),               # the final version after its betas
    ("0.1.2-beta.2", ["v0.1.1", "v0.1.2-beta.3"], False, "0.1.2-beta.3"),
    ("0.1.1", ["v0.1.0", "v0.1.1"], False, "already been released"),
    ("0.1.0", ["v0.1.1"], False, "not newer than 0.1.1"),
    ("0.0.9", ["v0.1.1"], False, "not newer than 0.1.1"),
    ("0.1.0", [], True, ""),                                        # the very first release
])
def test_a_release_must_be_newer_than_everything_already_out(version, tags, ok, says):
    """0.12.3: no one is ever offered a version that is not newer than what is out, so releasing one is refused."""
    found = _load_checker().not_newer(version, tags)
    assert (found == []) == ok and (ok or says in found[0])


def test_check_version_new_reads_the_released_tags_from_git(tmp_path):
    import shutil
    for name in ("sluice/__init__.py", "sluice/update_check.py", "pyproject.toml", "CHANGELOG.md", "sluice/data/CHANGELOG.md",
                 "tools/check-version.py", "README.md"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True)  # noqa: E731
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    version = _load_checker().read_version()
    run = lambda *a: subprocess.run(["python3", "tools/check-version.py", *a], cwd=tmp_path, capture_output=True, text=True)  # noqa: E731
    git("tag", "v0.0.1")
    assert run("--tag", f"v{version}", "--new").returncode == 0
    git("tag", f"v{version}")  # pushed as the release tag: it is the one being released, not "already out"
    assert run("--tag", f"v{version}", "--new").returncode == 0
    git("tag", "v99.0.0")
    out = run("--tag", f"v{version}", "--new")
    assert out.returncode == 1 and "not newer than 99.0.0" in out.stderr


def test_a_release_without_its_zip_is_never_offered():
    """0.12.3: a release made by hand (StowLock's v0.13.0 had only notes) or one whose build failed is skipped, so no one is
    offered an update that cannot be installed."""
    zip_assets = lambda tag: [  # noqa: E731
        {"name": f"sluice-{tag}.zip", "browser_download_url": f"https://example.org/sluice-{tag}.zip"},
        {"name": f"sluice-{tag}.zip.sha256", "browser_download_url": f"https://example.org/sluice-{tag}.zip.sha256"}]
    releases = [{"tag_name": "v0.13.0", "assets": []},
                {"tag_name": "v0.12.3", "assets": [zip_assets("v0.12.3")[0]]},  # the zip but no checksum
                {"tag_name": "v0.12.2", "assets": zip_assets("v0.12.2"), "html_url": "https://example.org/r"}]
    assert pick_release(releases, "stable")["tag_name"] == "v0.12.2"
    result = update_check.check("0.12.1", fetch=lambda url, timeout: releases)
    assert result.status == "available" and result.latest == "0.12.2" and result.zip_url.endswith("v0.12.2.zip")
    assert update_check.check("0.12.2", fetch=lambda url, timeout: releases).status == "up_to_date"


def test_the_release_is_published_only_once_its_files_are_attached():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "draft: true" in workflow and "--draft=false" in workflow and 'sluice-${TAG}.zip.sha256' in workflow


# ----------------------------------------------------------------------------- 0.12.3: quicker voice meters
def test_meters_update_60_times_a_second_and_fall_25_db_a_second(qapp):
    from sluice import ui_meters
    from sluice.ui_meters import LevelMeter
    assert ui_meters.METER_FPS == 60 and abs(ui_meters.FALL_PER_S * 60 - 25.0) < 1e-9
    ui_meters.FRAME_S = 1.0 / ui_meters.METER_FPS  # the rate while Sluice's window is the one in use
    meter = LevelMeter()
    meter.push(1.0)
    for _ in range(ui_meters.METER_FPS):  # one second of silence
        meter.push(0.0)
    assert abs((1.0 - meter._level) * 60 - 25.0) < 0.5  # 25 dB down on the 60 dB scale


def test_a_microphone_meter_shows_the_sound_before_the_effects():
    """The noise and echo reducers each hold back about 16 ms; a mic's meter is measured before them so it follows the voice."""
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    try:
        mic = next(c for c in engine.mixer.channels if c.devices)
        app = next(c for c in engine.mixer.channels if not c.devices)
        engine.graph.channels[mic.id].input_peak = 0.5
        engine.graph.channels[mic.id].peak = 0.1  # what came out of the effects (still held back by them)
        engine.graph.channels[app.id].input_peak = 0.5
        engine.graph.channels[app.id].peak = 0.1
        levels = engine.levels()
        monitor = engine.mixer.mixes[0].id
        expect = 0.5 * engine.mixer.route_gain(mic, engine.mixer.mixes[0])
        assert abs(levels[f"ch:{mic.id}:{monitor}"] - min(1.0, expect)) < 1e-9
        assert abs(levels[f"ch:{app.id}:{monitor}"] - min(1.0, 0.1 * engine.mixer.route_gain(app, engine.mixer.mixes[0]))) < 1e-9
        assert engine.graph.take_peaks()[f"in:{mic.id}"] == 0.0  # taken: the next reading starts again
    finally:
        engine.shutdown()
