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


def test_glass_is_a_skin_with_see_through_panes_on_a_tinted_backdrop():
    assert themes.SKINS["glass"] == "Glass"
    for theme in ("dark", "light"):
        sheet = themes.build_style(themes.skin_colors(themes.BUILT_IN[theme], "glass"), "glass")
        assert "qlineargradient" in sheet.split("QWidget#root {")[1].split("}")[0]  # the backdrop wash (under the painted shapes)
        strip = sheet.split("QFrame#strip, QFrame#row, QFrame#mix {")[-1].split("}")[0]
        assert "rgba(" in strip and "border-top" in strip  # see-through, with a lit top edge
        assert "$" not in sheet  # every value filled in


def test_glass_skin_is_saved_and_loaded(tmp_path):
    mixer = Mixer.demo()
    mixer.skin, mixer.widget_skin, mixer.widget_theme = "glass", "glass", "light"
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.save_config(tmp_path / "c.json")
    loaded = Mixer.load(tmp_path / "c.json")
    assert (loaded.skin, loaded.widget_skin, loaded.widget_theme) == ("glass", "glass", "light")


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
    light = themes.skin_colors(themes.BUILT_IN["light"], "glass")
    with themes.dressed_as("glass", light):
        assert themes.current_skin() == "glass" and themes.color("panel") == light["panel"]
        inside = themes.generation()
        assert inside < 0 and inside != before[2]
    assert (themes.current_skin(), themes.color("panel"), themes.generation()) == before
    with themes.dressed_as("glass", light):
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
        win.set_widget_dress(skin="glass", theme="light")
        widget.grab()
        light_panel = themes.skin_colors(themes.BUILT_IN["light"], "glass")["panel"]
        assert seen[-1] == ("glass", light_panel)
        assert themes.current_skin() == "calm" and engine.mixer.skin == "calm"  # the window keeps its own
        assert widget.height() == widget.insets()[0] + widget.header_height() + 2 * 36 - 6 + widget.insets()[1]
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
        window.widget_skin.setCurrentIndex(skins.index("glass"))
        window.widget_skin.activated.emit(skins.index("glass"))
        assert engine.mixer.widget_skin == "glass"
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


KDE = {"XDG_CURRENT_DESKTOP": "KDE"}
SYSTEM = ("6.12.0", "/usr/lib/qt6/plugins")


def test_blur_behind_uses_kwindoweffects_on_kde_only():
    lib = FakeBlurLibrary()
    paths = []
    blur = desktop_place.Blur(loader=lambda: lib, env=KDE, qt_version="6.12.0", system=SYSTEM, add_path=paths.append)
    assert blur.available
    assert blur.set(object(), True, pointers=(0x1000, 0x2000))
    assert lib.calls == [(0x1000, True, 0x2000)]
    assert paths == ["/usr/lib/qt6/plugins"]  # told where KDE keeps its plugins, before the first call
    assert not desktop_place.Blur(loader=lambda: lib, env={"XDG_CURRENT_DESKTOP": "GNOME"}).available
    missing = desktop_place.Blur(loader=lambda: None, env=KDE, qt_version="6.12.0", system=SYSTEM, add_path=paths.append)
    assert not missing.available and "KWindowSystem" in missing.reason
    assert not missing.set(object(), True)


def test_the_blur_function_name_is_the_one_kwindowsystem_exports():
    # void KWindowEffects::enableBlurBehind(QWindow *, bool, const QRegion &), as nm -D lists it in libKF6WindowSystem.so.6
    assert desktop_place.BLUR_SYMBOL == "_ZN14KWindowEffects16enableBlurBehindEP7QWindowbRK7QRegion"
    assert len("KWindowEffects") == 14 and len("enableBlurBehind") == 16


def test_every_skin_draws_a_preview(qapp):
    from sluice.ui_skins import BLURBS, draw_preview
    for skin in themes.SKINS:
        assert skin in BLURBS
        assert not draw_preview(skin, themes.skin_colors(themes.BUILT_IN["dark"], skin)).isNull()


def test_blur_is_not_tried_when_the_system_qt_is_another_version_or_has_no_plugins(tmp_path):
    """0.11.6: Sluice's own Qt (PySide6) looked for KDE's window-system plugin in its own folder, found none ("Could not find any
    platform plugin") and blurred nothing. Now the system's plugin folder is added, and only when the versions match."""
    lib = FakeBlurLibrary()
    other = desktop_place.Blur(loader=lambda: lib, env=KDE, qt_version="6.12.0", system=("6.9.2", "/usr/lib/qt6/plugins"),
                               add_path=lambda p: None)
    assert not other.available and "6.9.2" in other.reason and "6.12.0" in other.reason
    none = desktop_place.Blur(loader=lambda: lib, env=KDE, qt_version="6.12.0", system=("", None), add_path=lambda p: None)
    assert not none.available and "plugins" in none.reason
    lib_dir = tmp_path / "lib"
    (lib_dir / "qt6" / "plugins" / "kf6" / "kwindowsystem").mkdir(parents=True)
    (lib_dir / "libQt6Core.so.6.12.1").write_text("")
    assert desktop_place.system_qt((str(tmp_path / "nothing"), str(lib_dir))) == ("6.12.1", lib_dir / "qt6" / "plugins")
    assert desktop_place.same_minor("6.12.1", "6.12.0") and not desktop_place.same_minor("6.11.0", "6.12.0")


# ---------------------------------------------------------------- real Glass (0.11.7)
@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("see", [False, True])
def test_text_on_glass_panes_reads_over_what_is_behind_them(theme, see):
    """The readability guard: a pane is as see-through as it can be while the theme's text still reads at 4.5:1 over every colour
    the backdrop puts behind it (and, for a see-through window, over a white, black or grey wallpaper through the window's tint)."""
    from sluice import depth
    from sluice.skin_glass import backdrop_colours, glass_values
    values = dict(themes.skin_colors(themes.BUILT_IN[theme], "glass"))
    values.update(themes.mix_colors(values, "glass"))
    glass = glass_values(values, see)
    alpha = glass["glass_pane_alpha"]
    assert alpha <= 0.6  # still glass: well under the 0.8 a solid-looking card would need
    bg = values["bg"]
    if see:
        behind = [depth.mix(wall, bg, 0.45 if theme == "light" else 0.40) for wall in ("#ffffff", "#000000", "#808080")]
    else:
        behind = [depth.mix(bg, c, 0.55 if theme == "dark" else 0.35) for c in backdrop_colours(values)] + [bg]
    for colour in behind:
        assert depth.contrast(values["text"], depth.mix(colour, values["panel"], alpha)) >= 4.5, (theme, see, colour)


def test_the_window_is_made_see_through_only_on_kde_with_blur_in_glass():
    from sluice import ui_glass
    mixer = Mixer.demo()
    mixer.skin = "glass"

    class Blur:
        available = True

    kde = {"XDG_CURRENT_DESKTOP": "KDE"}
    assert ui_glass.wants_see_through(mixer, kde, Blur())
    assert not ui_glass.wants_see_through(mixer, {"XDG_CURRENT_DESKTOP": "GNOME"}, Blur())
    Blur.available = False
    assert not ui_glass.wants_see_through(mixer, kde, Blur())
    Blur.available = True
    mixer.see_through = False
    assert not ui_glass.wants_see_through(mixer, kde, Blur())
    mixer.see_through, mixer.reduce_effects = True, True
    assert not ui_glass.wants_see_through(mixer, kde, Blur())
    mixer.reduce_effects, mixer.skin = False, "calm"
    assert not ui_glass.wants_see_through(mixer, kde, Blur())


def test_the_see_through_setting_is_saved(tmp_path):
    mixer = Mixer.demo()
    mixer.see_through = False
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.save_config(tmp_path / "c.json")
    assert Mixer.load(tmp_path / "c.json").see_through is False
    import json
    (tmp_path / "old.json").write_text(json.dumps({"look": "glass"}))
    assert Mixer.load(tmp_path / "old.json").see_through is True  # on unless turned off


def test_glass_paints_a_backdrop_behind_the_panes_unless_effects_are_reduced(qapp, tmp_path):
    """Without a see-through window, Sluice paints soft shapes in the theme's colours behind the panes (the old flat gradient
    was too close to the panes' own colour for them to look like glass)."""
    from PySide6.QtGui import QColor
    win, engine = make(qapp, tmp_path, skin="glass")
    try:
        assert win.glass_backdrop.active()
        picture = win.centralWidget().grab().toImage()
        bg = QColor(themes.color("bg"))
        corner = picture.pixelColor(10, 10)  # a shape's centre sits near the top left corner
        assert abs(corner.red() - bg.red()) + abs(corner.green() - bg.green()) + abs(corner.blue() - bg.blue()) > 30
        win.set_reduce_effects(True)
        assert not win.glass_backdrop.active()
    finally:
        win.shutdown()
        themes.set_reduce_effects(False)


def test_choosing_glass_while_running_says_the_window_turns_see_through_at_the_next_start(qapp, tmp_path, monkeypatch):
    from sluice import ui_glass
    win, engine = make(qapp, tmp_path, skin="calm")
    try:
        monkeypatch.setattr(ui_glass, "wants_see_through", lambda mixer, *a: mixer.skin == "glass")
        win.choose_skin("glass")
        assert "next time Sluice starts" in win.status_label.text()
    finally:
        win.shutdown()


@pytest.mark.parametrize("skin", [skin for skin in themes.SKINS if skin != "glass"])
def test_a_see_through_window_in_a_solid_skin_shows_nothing_through(skin):
    """The window's see-through-ness is fixed at start; switching from Glass to another skin while it runs must leave the window
    solid: the window's body and its status bar are painted in the theme's background in every other skin."""
    colors = themes.skin_colors(themes.BUILT_IN["dark"], skin)
    sheet = themes.build_style(colors, skin, see=True)
    status = sheet.split("QStatusBar {")[1].split("}")[0]
    assert "background: #" in status and "rgba" not in status
    assert "rgba" not in sheet.split("QWidget#root")[1].split("}")[0] if "QWidget#root" in sheet else True
    glass = themes.build_style(themes.skin_colors(themes.BUILT_IN["dark"], "glass"), "glass", see=True)
    assert "rgba" in glass.split('QWidget#root[seethrough="true"] {')[1].split("}")[0]  # only Glass lets it through
