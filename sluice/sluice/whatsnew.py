# SPDX-License-Identifier: GPL-3.0-or-later
"""Release notes: what changed in each version, read from the changelog that ships inside the package.

``CHANGELOG.md`` (in the project folder) is the one place the notes are written; ``sluice/data/CHANGELOG.md`` is a
copy of it so an installed Sluice can show them (a test fails if the two differ). GitHub release pages are built
from the same file, so the window, the update check and the release page all say the same thing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .updates import parse_version

BUNDLED = Path(__file__).resolve().parent / "data" / "CHANGELOG.md"
SECTION = re.compile(r"^## (\d+(?:\.\d+)*)\s*$", re.MULTILINE)
MAX_VERSIONS = 4          # when someone skips many versions, show at most this many of the newest
FIRST_PUBLIC = "0.7.0"    # settings from before Sluice recorded the last version it showed belong to this one


def parse(text: str) -> dict:
    """{version: notes} in the order they appear in the file (newest first). Notes keep their Markdown."""
    found = list(SECTION.finditer(text))
    notes = {}
    for index, match in enumerate(found):
        end = found[index + 1].start() if index + 1 < len(found) else len(text)
        notes[match.group(1)] = text[match.end():end].strip()
    return notes


def load(path: Optional[Path] = None) -> dict:
    try:
        return parse((path or BUNDLED).read_text(encoding="utf-8"))
    except OSError:
        return {}


def notes_for(version: str, notes: Optional[dict] = None) -> str:
    return (load() if notes is None else notes).get(version, "")


def since(last_seen: str, current: str, notes: Optional[dict] = None) -> str:
    """Markdown with the notes of every version after ``last_seen`` up to ``current``, newest first.
    Empty if there is nothing to show (not newer, or no notes written)."""
    notes = load() if notes is None else notes
    wanted = [v for v in notes if parse_version(v) > parse_version(last_seen) and parse_version(v) <= parse_version(current)]
    wanted.sort(key=parse_version, reverse=True)
    wanted = wanted[:MAX_VERSIONS]
    if not wanted:
        return ""
    if len(wanted) == 1:
        return notes[wanted[0]]
    return "\n\n".join(f"## {v}\n\n{notes[v]}" for v in wanted)


# --------------------------------------------------------------------- last version shown
def marker_path(config_file: Path) -> Path:
    return config_file.with_name("last_version")


def read_marker(config_file: Path) -> str:
    try:
        text = marker_path(config_file).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text if parse_version(text) else ""


def write_marker(config_file: Path, version: str) -> None:
    try:
        marker_path(config_file).write_text(version + "\n", encoding="utf-8")
    except OSError:
        pass  # not being able to remember only means the notes may show once more


def what_to_show(config_file_existed: bool, marker: str, current: str, notes: Optional[dict] = None) -> str:
    """The Markdown to show at start-up after an update, or "" for nothing.
    A brand-new install (no settings yet) and a start on the same version show nothing."""
    if marker == current:
        return ""
    if not marker:
        if not config_file_existed:
            return ""  # first ever start: nothing has changed for this person
        marker = FIRST_PUBLIC  # settings exist but no record: they come from the first public version
    return since(marker, current, notes)
