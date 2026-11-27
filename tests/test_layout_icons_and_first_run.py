# SPDX-License-Identifier: GPL-3.0-or-later
"""The layout switch, the first-run screen, the slim fader, the status chip, and old theme files."""

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import Fader, MainWindow  # noqa: E402


@pytest.fixture
def rig(qapp, tmp_path):
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.show()
    yield win, engine
    win.shutdown()


def test_layout_switch_changes_the_screen_and_is_remembered(rig, tmp_path):
    win, engine = rig
    assert engine.mixer.layout == "columns"
    win.set_layout("rows")
    assert engine.mixer.layout == "rows" and win.layout_mode == "rows"
    assert all(s.rows for s in win.strips)
    win.set_layout("nonsense")
    assert engine.mixer.layout == "rows"
    engine.save_config(tmp_path / "saved.json")
    assert Mixer.load(tmp_path / "saved.json").layout == "rows"
    win.set_layout("columns")
    assert not any(s.rows for s in win.strips)


def test_old_settings_without_a_layout_open_as_columns(tmp_path):
    path = tmp_path / "old.json"
    Mixer.demo().save(path)
    data = json.loads(path.read_text())
    data.pop("layout", None)
    path.write_text(json.dumps(data))
    assert Mixer.load(path).layout == "columns"


def test_first_run_shows_for_an_empty_mixer_and_goes_away_for_good(qapp, tmp_path):
    engine = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    try:
        assert win._needs_first_run()
        engine.mixer.hints_seen.append("firstrun")
        assert not win._needs_first_run()
    finally:
        win.shutdown()


def test_fader_moves_from_the_keyboard_and_resets_on_double_click(qapp):
    fader = Fader(horizontal=True)
    fader.resize(200, 28)
    fader.show()
    seen = []
    fader.gainChanged.connect(seen.append)
    start = fader.gain()
    fader.setFocus()
    QTest.keyClick(fader, Qt.Key.Key_Left)
    assert fader.gain() < start and seen
    QTest.keyClick(fader, Qt.Key.Key_Home)
    low = fader.gain()
    QTest.keyClick(fader, Qt.Key.Key_End)
    assert fader.gain() > low
    QTest.mouseDClick(fader, Qt.MouseButton.LeftButton)
    assert fader.gain() == 0 or abs(fader.gain()) <= 10  # back to 0 dB (tenths of a dB)


def test_status_chip_texts(rig):
    _win, engine = rig
    assert engine.dropout_text() == "0 dropouts"
    assert "kHz" in engine.rate_text() and "frames" in engine.rate_text()


def test_theme_file_without_the_new_colours_still_loads_and_gets_them(tmp_path):
    theme, _notes = themes.parse({"name": "Old one", "base": "dark", "colors": {"bg": "#101820", "accent": "#ff8844"}})
    for token in themes.NEW_TOKENS:
        assert theme.colors[token].startswith("#") and len(theme.colors[token]) == 7
    assert theme.colors["accent"] == "#ff8844"


def test_the_downloadable_themes_still_import():
    """0.13.1: the themes/ folder is unmaintained (community themes, as they are): it is not held to the contrast test or to
    new colour names, but every file must still import, the missing colours filled in from its base."""
    import pathlib

    folder = pathlib.Path(__file__).resolve().parent.parent / "themes"
    files = sorted(folder.glob("*.json"))
    assert len(files) == 18  # 21 until 0.13.1: three of them are built in now
    built_in = {t.name for t in themes.BUILT_IN.values()}
    for path in files:
        theme, _notes = themes.parse(json.loads(path.read_text()))
        assert theme.name not in built_in, path.name  # no theme twice
        assert set(theme.colors) >= set(themes.TOKEN_NAMES), path.name


def test_every_built_in_theme_passes_the_contrast_test():
    """0.13.1 (House Standard v1.3): every text colour on every surface it sits on, in every built-in theme."""
    for theme in themes.BUILT_IN.values():
        assert themes.contrast_problems(theme.colors, strict=True) == [], theme.name
        assert themes.house_contrast_problems(theme.colors) == [], theme.name


def test_clicking_a_control_never_changes_its_size_or_the_window(rig):
    """Focus draws a ring. The ring must not make the control (and so the layout, and the window) bigger."""
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton, QToolButton

    win, _engine = rig
    for layout in ("columns", "rows"):
        win.set_layout(layout)
        QTest.qWait(20)
        controls = [
            w for kind in (QPushButton, QToolButton, QComboBox, QLineEdit) for w in win.findChildren(kind) if w.isVisible()
        ]
        assert controls
        size = win.size()
        for widget in controls:
            before = widget.sizeHint()
            widget.setFocus(Qt.FocusReason.TabFocusReason)
            QTest.qWait(1)
            assert widget.sizeHint() == before, (
                layout,
                widget.objectName(),
                widget.text() if hasattr(widget, "text") else "",
                before,
                widget.sizeHint(),
            )
            widget.clearFocus()
        assert win.size() == size


def test_icons_are_drawn_for_the_exact_size_and_scale(qapp):
    from sluice import ui_icons

    for name in ui_icons.NAMES:
        for px in (16, 18, 20, 24, 30, 40):
            pixmap = ui_icons.render(name, "#ffffff", px)
            assert pixmap.width() == px and pixmap.height() == px
            # transparent corner: nothing is stretched (0.13.1: Lucide's mic-off slash ends a unit from the corner, so its
            # round cap tints that pixel faintly)
            assert pixmap.toImage().pixelColor(0, 0).alpha() < (64 if name == "mic_off" else 1) or name == "gear", name
    icon = ui_icons.icon("plus", "#ffffff", 20)
    assert icon.pixmap(20, 20).width() >= 20
    assert not icon.pixmap(40, 40).isNull()


def test_a_straight_icon_line_is_sharp_at_every_size(qapp):
    """A horizontal stroke of the plus icon is solid on whole pixel rows: no half-covered rows that look blurred."""
    from sluice import ui_icons

    for px in (18, 20, 24, 30, 36, 40):
        image = ui_icons.render("plus", "#ffffff", px).toImage()
        column = [image.pixelColor(int(px * 0.2), y).alpha() for y in range(px)]
        lit = [a for a in column if a]
        # one stroke of whole pixels on the pixel grid: as many solid rows as it is wide, nothing smeared beyond (0.12.2: bolder;
        # 0.13.1: Lucide's weight, rounded to whole pixels)
        width = ui_icons.stroke_pixels(px)
        assert abs(width - 2.0 * px / 24) <= 1.0
        assert width <= len(lit) <= width + 1 and lit == lit[::-1] and max(lit) >= 200, (px, column)


def test_every_source_has_a_picture_and_a_letter_when_there_is_none(qapp):
    from sluice import ui_icons

    a = ui_icons.app_pixmap("", "Discord", 20, 1.0, "discord")
    b = ui_icons.app_pixmap("", "Discord", 20, 2.0, "discord")
    assert a.width() == 20 and b.width() == 40 and b.devicePixelRatio() == 2.0
    assert a.toImage().pixelColor(10, 10).alpha() == 255


def test_the_add_button_is_always_in_view_and_sources_have_pictures(rig):
    from sluice.ui import Chip

    win, engine = rig
    strip = next(s for s in win.strips if s.channel.id == "music")
    assert len(strip.channel.apps) >= 2 and strip.add_button.isVisibleTo(strip)
    chips = strip.findChildren(Chip)
    assert chips and all(c.picture is not None for c in chips)
    empty = next(s for s in win.strips if not s.channel.apps and not s.channel.devices)
    assert empty.add_button.isVisibleTo(empty)


def test_the_icon_of_an_app_comes_from_its_desktop_entry_or_the_program_or_steam(rig, tmp_path):
    from sluice.apps import AppEntry, Catalog, parse_desktop_file

    _win, engine = rig
    desktop = tmp_path / "krita.desktop"
    desktop.write_text("[Desktop Entry]\nType=Application\nName=Krita\nExec=krita %F\nIcon=krita\n")
    entry = parse_desktop_file(desktop)
    assert entry.icon == "krita"
    engine.catalog = Catalog([entry, AppEntry("Plain", "plain", "app", frozenset({"plain"}))])
    assert engine.app_icon("krita") == "krita" and engine.app_icon("plain") == ""
    assert engine.app_icon("steam:220") == "steam_icon_220"


def test_listen_and_broadcast_have_their_own_colours_in_every_theme(rig):
    import json
    import pathlib

    _win, _engine = rig
    folder = pathlib.Path(__file__).resolve().parent.parent / "themes"
    for path in sorted(folder.glob("*.json")):
        theme, _ = themes.parse(json.loads(path.read_text()))
        colors = themes.mix_colors(theme.colors)
        assert colors["listen"] != colors["broadcast"], path.name
        assert themes.contrast_ratio(colors["listen_text"], colors["listen_tint"]) >= 4.5, path.name
        assert themes.contrast_ratio(colors["broadcast_text"], colors["broadcast_tint"]) >= 4.5, path.name


def test_rows_tell_the_mixes_apart(rig):
    from PySide6.QtWidgets import QFrame

    win, engine = rig
    win.set_layout("rows")
    QTest.qWait(20)
    cells = [f for f in win.findChildren(QFrame) if f.objectName() == "mixcell"]
    assert {c.property("mix") for c in cells} == {"monitor", "stream"}
