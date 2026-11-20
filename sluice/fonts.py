# SPDX-License-Identifier: GPL-3.0-or-later
"""The fonts Sluice ships: Inter for the Tile look's text and JetBrains Mono for its values (both SIL Open Font License 1.1; the
licences are next to the files in ``sluice/data/fonts``). They are added for Sluice alone, not installed on the system, so the Tile
look reads the same on every computer. A missing or unreadable file only means the next font in the style sheet's list is used."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("sluice.fonts")
FOLDER = Path(__file__).resolve().parent / "data" / "fonts"
FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf",
         "JetBrainsMono-Regular.ttf", "JetBrainsMono-Medium.ttf")
_loaded: list = []


def load() -> list:
    """Add the bundled fonts to the running application (once). Returns the family names that were added."""
    if _loaded:
        return list(_loaded)
    from PySide6.QtGui import QFontDatabase

    families: list = []
    for name in FILES:
        path = FOLDER / name
        if not path.is_file():
            log.info("bundled font missing: %s", name)
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            log.info("bundled font could not be read: %s", name)
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)
    _loaded.extend(families or ["(none)"])
    return families
