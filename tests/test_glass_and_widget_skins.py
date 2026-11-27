# SPDX-License-Identifier: GPL-3.0-or-later
"""The desktop widgets' own skin and theme (0.11.6; the Glass skin and its KDE blur were retired in 0.13.1)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402


def make(qapp, tmp_path, skin="calm", theme="dark"):
    mixer = Mixer.demo()
    mixer.skin, mixer.theme = skin, theme
    mixer.hints_seen.append("firstrun")
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.resize(1456, 860)
    win.show()
    for _ in range(4):
        qapp.processEvents()
    return win, engine


def test_an_unknown_widget_skin_is_the_window_s():
    import json
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    (folder / "c.json").write_text(json.dumps({"widget_look": "chrome", "widget_theme": 5}))
    loaded = Mixer.load(folder / "c.json")
    assert (loaded.widget_skin, loaded.widget_theme) == ("", "")


def test_dressed_as_swaps_the_skin_and_colours_and_puts_them_back():
    themes.set_skin("calm")
    themes.set_current(dict(themes.DARK))
    before = (themes.current_skin(), themes.color("panel"), themes.generation())
    light = themes.skin_colors(themes.BUILT_IN["light"], "tile")
    with themes.dressed_as("tile", light):
        assert themes.current_skin() == "tile" and themes.color("panel") == light["panel"]
        inside = themes.generation()
        assert inside < 0 and inside != before[2]
    assert (themes.current_skin(), themes.color("panel"), themes.generation()) == before
    with themes.dressed_as("tile", light):
        assert themes.generation() == inside  # the same skin and colours keep the same number (caches keep their entry)
    with themes.dressed_as(None, None):
        assert themes.generation() == before[2]


def test_the_widgets_can_have_their_own_skin_and_theme(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, skin="calm", theme="dark")
    try:
        win.desktop.open("channel", channel="system")
        widget = win.desktop.open_widgets[("channel", None, "system")]
        assert win.desktop.dressing() == (None, None)  # the default: as the window
        seen = []
        original = widget.paintEvent
        widget.paintEvent = lambda event: (seen.append((themes.current_skin(), themes.color("panel"))), original(event))
        win.set_widget_dress(skin="tile", theme="light")  # (0.13.1: Glass was retired; Tile is the other skin)
        widget.grab()
        light_panel = themes.skin_colors(themes.BUILT_IN["light"], "tile")["panel"]
        assert seen[-1] == ("tile", light_panel)
        assert themes.current_skin() == "calm" and engine.mixer.skin == "calm"  # the window keeps its own
        win.set_widget_dress(skin="", theme="")
        widget.grab()
        assert seen[-1][0] == "calm"
    finally:
        win.shutdown()


def test_the_settings_window_offers_the_widgets_skin_and_theme(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        win.open_settings()
        window = win.settings_window
        skins = [window.widget_skin.itemData(i) for i in range(window.widget_skin.count())]
        assert skins == [""] + list(themes.SKINS)
        assert window.widget_skin.itemText(0) == "Same as the window"
        window.widget_skin.setCurrentIndex(skins.index("tile"))
        window.widget_skin.activated.emit(skins.index("tile"))
        assert engine.mixer.widget_skin == "tile"
        index = window.widget_theme.findData("light")
        window.widget_theme.activated.emit(index)
        assert engine.mixer.widget_theme == "light"
    finally:
        win.shutdown()


def test_every_skin_draws_a_preview(qapp):
    from sluice.ui_skins import BLURBS, draw_preview

    for skin in themes.SKINS:
        assert skin in BLURBS
        assert not draw_preview(skin, themes.skin_colors(themes.BUILT_IN["dark"], skin)).isNull()
