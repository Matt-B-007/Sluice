# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from sluice import __version__, whatsnew

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = """# Changelog

## 0.9.0
- **Nine.**

## 0.8.1
- Eight-one.

## 0.8.0
Intro line.
- **Eight.**
  - nested

## 0.7.0
- Seven.
"""


def test_the_changelog_is_split_into_versions_newest_first():
    notes = whatsnew.parse(SAMPLE)
    assert list(notes) == ["0.9.0", "0.8.1", "0.8.0", "0.7.0"]
    assert notes["0.8.0"].startswith("Intro line.") and "nested" in notes["0.8.0"] and "Seven" not in notes["0.8.0"]


def test_since_gives_only_what_is_newer_and_not_beyond_this_version():
    notes = whatsnew.parse(SAMPLE)
    assert whatsnew.since("0.8.1", "0.9.0", notes) == "- **Nine.**"  # one version: its notes, without a heading
    both = whatsnew.since("0.8.0", "0.9.0", notes)
    assert both.index("## 0.9.0") < both.index("## 0.8.1") and "Eight." not in both
    assert whatsnew.since("0.9.0", "0.9.0", notes) == ""
    assert whatsnew.since("0.7.0", "0.8.0", notes).startswith("Intro line.")  # never shows a version newer than the running one
    assert "Nine" not in whatsnew.since("0.7.0", "0.8.0", notes)


def test_skipping_many_versions_shows_only_the_newest_few():
    notes = {f"1.{i}.0": f"- v{i}" for i in range(9, 0, -1)}
    shown = whatsnew.since("1.0.0", "1.9.0", notes)
    assert shown.count("## ") == whatsnew.MAX_VERSIONS and "## 1.9.0" in shown and "## 1.5.0" not in shown


def test_a_missing_changelog_gives_nothing_instead_of_an_error(tmp_path):
    assert whatsnew.load(tmp_path / "nope.md") == {}
    assert whatsnew.since("0.1.0", "0.2.0", {}) == ""


def test_what_to_show_at_start_up():
    notes = whatsnew.parse(SAMPLE)
    show = lambda existed, marker, current="0.9.0": whatsnew.what_to_show(existed, marker, current, notes)  # noqa: E731
    assert show(False, "") == ""                      # a brand-new install: nothing changed for them
    assert show(True, "0.9.0") == ""                  # same version as last time
    assert show(True, "0.8.1") == "- **Nine.**"       # updated: what is new since
    assert "Eight-one" in show(True, "")              # settings from before the record was kept: from the first public version
    assert show(True, "1.0.0") == ""                  # a downgrade shows nothing


def test_the_marker_file_round_trips_and_ignores_garbage(tmp_path):
    config = tmp_path / "config.json"
    assert whatsnew.read_marker(config) == ""
    whatsnew.write_marker(config, "0.8.0")
    assert whatsnew.read_marker(config) == "0.8.0"
    whatsnew.marker_path(config).write_text("hello", encoding="utf-8")
    assert whatsnew.read_marker(config) == ""
    whatsnew.write_marker(tmp_path / "missing" / "config.json", "0.8.0")  # an unwritable place is not an error


# ----------------------------------------------- the release itself must be documented
def test_the_copy_inside_the_package_is_the_project_changelog():
    assert (ROOT / "CHANGELOG.md").read_text(encoding="utf-8") == whatsnew.BUNDLED.read_text(encoding="utf-8"), \
        "copy CHANGELOG.md to sluice/data/CHANGELOG.md"


def test_this_version_has_release_notes_written():
    notes = whatsnew.load()
    assert __version__ in notes and notes[__version__].strip(), f"CHANGELOG.md has no '## {__version__}' section"
    assert list(notes)[0] == __version__, "the newest section should be this version"


def test_the_release_workflow_builds_its_notes_from_the_same_file():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "CHANGELOG.md" in workflow


def test_the_readme_has_a_whats_new_section_for_this_version():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"## What's new in {__version__}" in readme, "update the \"What's new in ...\" section at the top of README.md"
    assert "What's new in " not in readme.replace(f"What's new in {__version__}", "").replace("What's new in this version", "")
