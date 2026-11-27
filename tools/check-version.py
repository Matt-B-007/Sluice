#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks that everything that names Sluice's version agrees, before a release is made from it.

    python3 tools/check-version.py                 # the version files and the changelogs agree
    python3 tools/check-version.py --tag v0.12.2   # ...and this tag is the right one for them
    python3 tools/check-version.py --print         # prints the version (for scripts)
    python3 tools/check-version.py --new           # ...and it is newer than every version already released (git tags)

It is run by the tests and on GitHub on every push (so a mistake shows up long before a release), by the Release workflow, and by
tools/release.sh. Each problem is said in plain words with what to do about it."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$")  # 0.12.2, 0.13.0-beta.1, 1.0.0-rc.2


def read_version(root: Path = ROOT) -> str:
    match = re.search(r'^__version__ = "(.+?)"', (root / "sluice" / "__init__.py").read_text(), re.M)
    return match.group(1) if match else ""


def problems(root: Path = ROOT, tag: str = "") -> list:
    """Everything that disagrees, as sentences (empty when all is well)."""
    found = []
    version = read_version(root)
    if not version:
        return ["sluice/__init__.py has no __version__ line."]
    if not VERSION.match(version):
        found.append(f"The version {version!r} is not in the form 0.12.2 (or 0.13.0-beta.1 for a test version).")
    project = re.search(r'^version = "(.+?)"', (root / "pyproject.toml").read_text(), re.M)
    if not project or project.group(1) != version:
        found.append(
            f"pyproject.toml says {project.group(1) if project else 'nothing'} but sluice/__init__.py says {version}: "
            f"make them the same (tools/release.sh --set {version} does both)."
        )
    changelog = (root / "CHANGELOG.md").read_text()
    first = re.search(r"^## (\S+)", changelog, re.M)
    if not first or first.group(1) != version:
        found.append(
            f"CHANGELOG.md's newest section is {first.group(1) if first else 'missing'}, not {version}: "
            f"add a '## {version}' section at the top saying what changed."
        )
    copy = root / "sluice" / "data" / "CHANGELOG.md"
    if not copy.is_file() or copy.read_text() != changelog:
        found.append(
            "sluice/data/CHANGELOG.md (shown under Help > What's new) is not the same as CHANGELOG.md: copy CHANGELOG.md over it."
        )
    readme = (root / "README.md").read_text() if (root / "README.md").is_file() else ""
    if readme and f"## What's new in {version}" not in readme:
        found.append(
            f'README.md has no "## What\'s new in {version}" section: rename the old one near the top and say in a '
            f"few lines what changed (tools/release.sh --set does the renaming)."
        )
    if tag and tag != f"v{version}":
        found.append(
            f"The tag {tag} does not match the version in the code, {version}, so the release would call itself "
            f"{version} and offer itself as an update for ever. Delete the tag (git push --delete origin {tag}; "
            f"git tag -d {tag}) and release with tools/release.sh, or with Actions > Release > Run workflow on "
            f"GitHub, which make the tag from the version for you. To release {tag[1:]} instead, first run "
            f"tools/release.sh --set {tag[1:]}, add its changelog section and commit."
        )
    return found


def released_tags(root: Path = ROOT) -> list:
    """The versions already released: the repository's v* tags (fetched from GitHub by the workflow and by release.sh)."""
    import subprocess

    try:
        out = subprocess.run(["git", "tag", "--list", "v*"], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def not_newer(version: str, tags: list) -> list:
    """0.12.3: a release must be newer than everything already released, or no one is offered it. The usual slip is a test
    version numbered after the stable one it leads to, such as 0.1.1-beta.1 once 0.1.1 is out: a beta comes *before* its own
    final version, so it is older than 0.1.1. Returns the problem as a sentence, with the number to use instead."""
    sys.path.insert(0, str(ROOT))
    from sluice.update_check import is_prerelease, version_key

    mine = version_key(version)
    if not mine:
        return []
    released = [(version_key(t), t.lstrip("v")) for t in tags if version_key(t)]
    stable = [(k, t) for k, t in released if not is_prerelease(t)]
    newest = max(released, default=None)
    if newest is None or mine > newest[0]:
        return []
    if any(k == mine for k, _ in released):
        return [f"{version} has already been released. Set the next version: tools/release.sh --set <next version>."]
    if is_prerelease(version) and stable:
        top = max(stable)[1]
        major, minor, patch = (top.split(".") + ["0", "0"])[:3]
        patch_number = int(re.sub(r"\D.*", "", patch) or 0)  # (outside the f-string: Python 3.10 and 3.11 allow no \ inside one)
        suggestion = f"{major}.{minor}.{patch_number + 1}-beta.1"
        if version_key(version) <= max(stable)[0]:
            return [
                f"{version} is a test version of a version that is not newer than {top}, which is already out: a beta comes "
                f"before its own final version, so no one on {top} would be offered it. Number the test version after "
                f"it, for example {suggestion} (tools/release.sh --set {suggestion})."
            ]
    return [
        f"{version} is not newer than {newest[1]}, which is already released, so no one would be offered it. Use a higher "
        f"version (tools/release.sh --set <next version>)."
    ]


def main(argv: list) -> int:
    if "--print" in argv:
        print(read_version())
        return 0
    tag = argv[argv.index("--tag") + 1] if "--tag" in argv and argv.index("--tag") + 1 < len(argv) else ""
    found = problems(tag=tag)
    if "--new" in argv and not found:
        found = not_newer(
            read_version(), [t for t in released_tags() if t != tag]
        )  # (the tag being released is not "already out")
    for line in found:
        print(f"::error::{line}" if "GITHUB_ACTIONS" in __import__("os").environ else f"Problem: {line}", file=sys.stderr)
    if not found:
        print(f"Version {read_version()}: the version files and the changelogs agree" + (f", and {tag} matches." if tag else "."))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
