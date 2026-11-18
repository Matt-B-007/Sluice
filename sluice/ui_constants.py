# SPDX-License-Identifier: GPL-3.0-or-later
"""Numbers and addresses the main window and its parts share. ``ui.py`` re-exports them, so ``ui.NAME`` still works."""
from __future__ import annotations

PROJECT_URL = "https://github.com/Matt-B-007/Sluice"
ISSUES_URL = PROJECT_URL + "/issues"
THEMES_URL = PROJECT_URL + "/tree/main/themes"
DISCORD_URL = "https://discord.gg/awDvJ5Vj2S"
AUTOSAVE_MS = 5000  # how often to look for unsaved changes
TALKING_LEVEL = 0.03  # the microphone peak (0 to 1, about -30 dB) above which the tray icon lights up
TALKING_HOLD = 0.35  # seconds it stays lit after the last sound, so it does not flicker between words
TRAY_WATCH_MS = 200  # how often the hidden window's tray watcher looks at the microphone
CLOSE_HINT = "closechoice"  # in hints_seen once the close choice has been made or the first-close question answered
AUTO_UPDATE_DELAY_MS = 20000  # the automatic update (if switched on) looks once, this long after start-up
DEFAULT_SIZE = (1456, 800)  # wide enough for five channels beside the two master cards
