# SPDX-License-Identifier: GPL-3.0-or-later
"""The Glass skin, KDE's blur behind Glass widgets, and the desktop widgets' own skin and theme (0.11.6)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from sluice import desktop_place, themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402


def make(qapp, tmp_path, look="calm", theme="dark"):
    mixer = Mixer.demo()
    mixer.look, mixer.theme = look, theme
    mixer.hints_seen.append("firstrun")
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.resize(1456, 860)
    win.show()
    for _ in range(4):
        qapp.processEvents()
    return win, engine


def test_glass_is_a_skin_with_see_through_panes_on_a_tinted_backdrop():
    assert themes.LOOKS["glass"] == "Glass"
    for theme in ("dark", "light"):
        sheet = themes.build_style(themes.look_colors(themes.BUILT_IN[theme], "glass"), "glass")
        assert "qlineargradient" in sheet.split("QWidget#root")[-1].split("}")[0]  # the backdrop wash
        strip = sheet.split("QFrame#strip, QFrame#row, QFrame#mix {")[-1].split("}")[0]
        assert "rgba(" in strip and "border-top" in strip  # see-through, with a lit top edge
        assert "$" not in sheet  # every value filled in


def test_glass_skin_is_saved_and_loaded(tmp_path):
    mixer = Mixer.demo()
    mixer.look, mixer.widget_look, mixer.widget_theme = "glass", "glass", "light"
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.save_config(tmp_path / "c.json")
    loaded = Mixer.load(tmp_path / "c.json")
    assert (loaded.look, loaded.widget_look, loaded.widget_theme) == ("glass", "glass", "light")


def test_an_unknown_widget_skin_is_the_window_s():
    import json
    import tempfile
    from pathlib import Path
    folder = Path(tempfile.mkdtemp())
    (folder / "c.json").write_text(json.dumps({"widget_look": "chrome", "widget_theme": 5}))
    loaded = Mixer.load(folder / "c.json")
    assert (loaded.widget_look, loaded.widget_theme) == ("", "")


def test_dressed_as_swaps_the_skin_and_colours_and_puts_them_back():
    themes.set_look("calm")
    themes.set_current(dict(themes.DARK))
    before = (themes.current_look(), themes.color("panel"), themes.generation())
    light = themes.look_colors(themes.BUILT_IN["light"], "glass")
    with themes.dressed_as("glass", light):
        assert themes.current_look() == "glass" and themes.color("panel") == light["panel"]
        inside = themes.generation()
        assert inside < 0 and inside != before[2]
    assert (themes.current_look(), themes.color("panel"), themes.generation()) == before
    with themes.dressed_as("glass", light):
        assert themes.generation() == inside  # the same skin and colours keep the same number (caches keep their entry)
    with themes.dressed_as(None, None):
        assert themes.generation() == before[2]


def test_the_widgets_can_have_their_own_skin_and_theme(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, look="calm", theme="dark")
    try:
        win.desktop.open("channel", channel="system")
        widget = win.desktop.open_widgets[("channel", None, "system")]
        assert win.desktop.dressing() == (None, None)  # the default: as the window
        seen = []
        original = widget.paintEvent
        widget.paintEvent = lambda event: (seen.append((themes.current_look(), themes.color("panel"))), original(event))
        win.set_widget_dress(look="glass", theme="light")
        widget.grab()
        light_panel = themes.look_colors(themes.BUILT_IN["light"], "glass")["panel"]
        assert seen[-1] == ("glass", light_panel)
        assert themes.current_look() == "calm" and engine.mixer.look == "calm"  # the window keeps its own
        assert widget.height() == widget.insets()[0] + widget.header_height() + 2 * 36 - 6 + widget.insets()[1]
        win.set_widget_dress(look="", theme="")
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
        assert skins == [""] + list(themes.LOOKS)
        assert window.widget_skin.itemText(0) == "Same as the window"
        window.widget_skin.setCurrentIndex(skins.index("glass"))
        window.widget_skin.activated.emit(skins.index("glass"))
        assert engine.mixer.widget_look == "glass"
        index = window.widget_theme.findData("light")
        window.widget_theme.activated.emit(index)
        assert engine.mixer.widget_theme == "light"
    finally:
        win.shutdown()


class FakeBlurLibrary:
    def __init__(self):
        self.calls = []

        def function(window, on, region):
            self.calls.append((window.value, on, region.value))
        setattr(self, desktop_place.BLUR_SYMBOL, function)


def test_blur_behind_uses_kwindoweffects_on_kde_only():
    lib = FakeBlurLibrary()
    blur = desktop_place.Blur(loader=lambda: lib, env={"XDG_CURRENT_DESKTOP": "KDE"})
    assert blur.available
    assert blur.set(object(), True, pointers=(0x1000, 0x2000))
    assert lib.calls == [(0x1000, True, 0x2000)]
    assert not desktop_place.Blur(loader=lambda: lib, env={"XDG_CURRENT_DESKTOP": "GNOME"}).available
    missing = desktop_place.Blur(loader=lambda: None, env={"XDG_CURRENT_DESKTOP": "KDE"})
    assert not missing.available and "KWindowSystem" in missing.reason
    assert not missing.set(object(), True)


def test_the_blur_function_name_is_the_one_kwindowsystem_exports():
    # void KWindowEffects::enableBlurBehind(QWindow *, bool, const QRegion &), as nm -D lists it in libKF6WindowSystem.so.6
    assert desktop_place.BLUR_SYMBOL == "_ZN14KWindowEffects16enableBlurBehindEP7QWindowbRK7QRegion"
    assert len("KWindowEffects") == 14 and len("enableBlurBehind") == 16


def test_every_skin_draws_a_preview(qapp):
    from sluice.ui_skins import BLURBS, draw_preview
    for look in themes.LOOKS:
        assert look in BLURBS
        assert not draw_preview(look, themes.look_colors(themes.BUILT_IN["dark"], look)).isNull()
