# SPDX-License-Identifier: GPL-3.0-or-later
"""``sluice --self-test --quick`` (House Standard): can this copy of Sluice start, load its window code and resources, and read
the settings? A few seconds, no network, no audio server and no outside tools, so the updater can run it on a new version
before swapping it in. ``sluice --self-test`` on its own is the full check (the same as ``--diagnose``)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Optional

QUICK_STEPS = ("the window code", "the icons and logo", "the fonts", "the themes", "the settings")


def quick(config_file: Optional[Path] = None, say: Callable[[str], None] = print) -> int:
    """0 when every step works, 1 (naming the step) when one does not. Touches nothing: the settings are only read."""
    started = time.monotonic()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window is shown
    step = QUICK_STEPS[0]
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(["sluice-self-test"])
        import importlib

        importlib.import_module("sluice.ui")  # the whole window: every module it imports

        step = QUICK_STEPS[1]
        from PySide6.QtGui import QIcon

        from . import launcher, ui_icons

        if QIcon(str(launcher.bundled_icon())).isNull() or ui_icons.tray_icon("idle").isNull():
            raise RuntimeError("an icon could not be drawn")
        step = QUICK_STEPS[2]
        from . import fonts

        fonts.load()
        step = QUICK_STEPS[3]
        from . import themes

        for theme in themes.BUILT_IN.values():
            if "$" in themes.build_style(themes.finish(theme.colors), "calm").replace("$$", ""):
                raise RuntimeError(f"the {theme.name} theme's style sheet is incomplete")
        step = QUICK_STEPS[4]
        from .model import Mixer, config_path

        path = Path(config_file) if config_file else config_path()
        if path.is_file():
            Mixer.load(path)  # read only
        del app
    except Exception as exc:  # noqa: BLE001 - the point is to report any failure, in words
        say(f"sluice: quick self-test failed at {step}: {type(exc).__name__}: {exc}")
        return 1
    from . import __version__

    say(f"sluice {__version__}: quick self-test passed in {time.monotonic() - started:.1f} s")
    return 0
