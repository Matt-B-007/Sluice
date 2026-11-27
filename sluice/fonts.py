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
         "JetBrainsMono-Regular.ttf", "JetBrainsMono-Medium.ttf",
         # 0.12.7: the Tile look's names are JetBrains Mono at weight 600 (SemiBold). Without its own file, Qt made that weight
         # from whatever the computer had, so a name fitted on one computer and was cut off on another (GitHub's).
         "JetBrainsMono-SemiBold.ttf", "JetBrainsMono-Bold.ttf")
UI_FAMILY = "Inter"
UI_POINT_SIZE = 10
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


def install(app) -> list:
    """0.12.7: add the bundled fonts and make Inter the whole application's font, before any window is made. Sluice's text
    then has the same width on every computer, whatever fonts it has installed (GitHub's test machine has little more than
    DejaVu). Called by Sluice's start-up, and by the tests' shared QApplication the same way. Returns the families added."""
    families = load()
    if UI_FAMILY in families:
        from PySide6.QtGui import QFont

        font = QFont(UI_FAMILY, UI_POINT_SIZE)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        app.setFont(font)
    else:
        log.info("Inter was not found among the bundled fonts: the system's font is used")
    return families
