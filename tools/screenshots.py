#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make the README screenshots and the theme pack's previews from the demo mixer, with the meters showing some sound.

    QT_QPA_PLATFORM=offscreen python3 tools/screenshots.py            # both
    QT_QPA_PLATFORM=offscreen python3 tools/screenshots.py docs       # only docs/screenshot*.png
    QT_QPA_PLATFORM=offscreen python3 tools/screenshots.py previews   # only themes/previews/*.jpg
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DOCS = (  # file, look, theme, layout, size
    ("screenshot.png", "calm", "dark", "columns", (1456, 800)),
    ("screenshot-light.png", "calm", "light", "columns", (1456, 800)),
    ("screenshot-rows.png", "calm", "dark", "rows", (1456, 800)),
    ("screenshot-tile.png", "tile", "dark", "columns", (1456, 860)),
    ("screenshot-nexus.png", "nexus", "dark", "columns", (1456, 860)),
)
SOUND = {"game": 0.7, "chat": 0.45, "music": 0.55, "browser": 0.3, "mic": 0.6}


def shoot(app, look: str, theme_id: str, layout: str, size: tuple, theme_file: Path = None):
    from sluice import themes
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow

    mixer = Mixer.demo()
    mixer.look, mixer.layout = look, layout
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    window = MainWindow(engine, None)
    window.resize(*size)
    window.show()
    if theme_file is not None:
        folder = Path(tempfile.mkdtemp())
        theme, _notes = themes.load_file(theme_file)
        stored = themes.save_custom(theme, folder)
        window._themes_folder = lambda: folder
        window.choose_theme(stored.id)
    else:
        window.choose_theme(theme_id)
    window.meter_timer.stop()
    levels = {f"ch:{c.id}:{m.id}": SOUND.get(c.id, 0.0) for c in mixer.channels for m in mixer.mixes}
    levels.update({f"mix:{m.id}": 0.6 for m in mixer.mixes})
    engine.sample_levels = lambda *_a, **_k: levels
    for _ in range(40):
        window._update_meters()
        floor = getattr(window, "channels_widget", None)
        if hasattr(floor, "_catch_up"):
            floor._catch_up()
        app.processEvents()
    window.status_label.setText("Ready") if hasattr(window, "status_label") else None
    picture = window.grab()
    window.shutdown()
    return picture


def main(which: str = "both") -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    if which in ("both", "docs"):
        for name, look, theme, layout, size in DOCS:
            shoot(app, look, theme, layout, size).save(str(ROOT / "docs" / name))
            print("wrote docs/" + name)
    if which in ("both", "previews"):
        for path in sorted((ROOT / "themes").glob("*.json")):
            picture = shoot(app, "calm", "", "columns", (1456, 800), theme_file=path)
            picture = picture.scaled(720, 396, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            picture.save(str(ROOT / "themes" / "previews" / f"{path.stem}.jpg"), "JPG", 88)
            print("wrote themes/previews/" + path.stem + ".jpg")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "both")
