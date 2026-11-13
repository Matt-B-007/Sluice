# SPDX-License-Identifier: GPL-3.0-or-later
"""Themes: the colour sets, reading a theme file safely, the saved choice, and switching in the window."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from sluice import themes
from sluice.model import Mixer


# ------------------------------------------------------------------- the built-in colour sets
@pytest.mark.parametrize("theme", list(themes.BUILT_IN.values()), ids=lambda t: t.id)
def test_every_built_in_theme_is_complete_and_valid(theme):
    assert set(theme.colors) == set(themes.TOKEN_NAMES)
    for name, value in theme.colors.items():
        assert themes.normalize_hex(value) == value, name  # already lower-case #rrggbb
    sheet = themes.build_style(theme.colors)
    assert "$" not in sheet  # every placeholder was filled


@pytest.mark.parametrize("theme", list(themes.BUILT_IN.values()), ids=lambda t: t.id)
def test_every_built_in_theme_is_readable(theme):
    assert themes.contrast_problems(theme.colors, strict=True) == []


def test_each_theme_looks_different():
    sheets = {t.id: themes.build_style(t.colors) for t in themes.BUILT_IN.values()}
    assert len(set(sheets.values())) == len(sheets)


def test_the_colours_with_a_fixed_meaning_are_the_same_everywhere():
    # Red on Mute and teal on Limiter must mean the same in every theme; only their shade may be tuned.
    for theme in themes.BUILT_IN.values():
        assert theme.colors["limiter"] and theme.colors["mute"]
    assert themes.BUILT_IN["dark"].colors["mute"] == "#ef5258"


def test_the_default_theme_is_dark_and_dark_is_the_old_look():
    assert themes.DEFAULT == "dark"
    assert themes.BUILT_IN["dark"].colors["bg"] == "#181b20"
    assert themes.BUILT_IN["dark"].colors["panel"] == "#232830"


def test_switching_back_to_a_theme_reuses_its_style_sheet():
    colors = themes.BUILT_IN["light"].colors
    assert themes.build_style(colors) is themes.build_style(dict(colors))


# ------------------------------------------------------------------- reading a theme file
def test_a_theme_file_only_needs_a_name_and_the_colours_it_changes():
    theme, notes = themes.parse({"name": "Moonlight", "colors": {"accent": "#7c5cff"}})
    assert theme.name == "Moonlight" and theme.base == "dark" and notes == []
    assert theme.colors["accent"] == "#7c5cff"
    assert theme.colors["bg"] == themes.DARK["bg"]  # left out: from the base theme
    light, _ = themes.parse({"name": "Paper", "base": "light", "colors": {}})
    assert light.colors["bg"] == themes.LIGHT["bg"]


def test_short_hex_values_and_capitals_are_accepted_and_normalised():
    theme, _ = themes.parse({"name": "x", "colors": {"accent": "#ABC", "bg": "#0A0B0C"}})
    assert theme.colors["accent"] == "#aabbcc" and theme.colors["bg"] == "#0a0b0c"


@pytest.mark.parametrize("bad", [
    "red", "#12345", "#gggggg", "rgb(1,2,3)", "", 7, None, ["#fff"],
    "#fff; } QWidget { background: url(http://x/y) }",   # an attempt to add rules to the style sheet
    "#ffffff\n} QPushButton{",
    "url(file:///etc/passwd)",
])
def test_anything_that_is_not_a_plain_hex_colour_is_refused(bad):
    with pytest.raises(themes.ThemeError):
        themes.parse({"name": "x", "colors": {"accent": bad}})


def test_a_theme_cannot_carry_anything_but_colours():
    theme, notes = themes.parse({"name": "x", "colors": {"accent": "#123456", "stylesheet": "QWidget{}", "evil": "#fff"},
                                 "stylesheet": "QWidget { display: none }"})
    assert "stylesheet" not in theme.colors and "evil" not in theme.colors
    assert len(notes) == 2 and all("ignored" in n for n in notes)
    sheet = themes.build_style(theme.colors)
    assert "display: none" not in sheet and "QWidget{}" not in sheet


@pytest.mark.parametrize("data", [[], "text", 5, None, {"name": ""}, {"name": 5}, {"name": "x", "base": "blue"},
                                  {"name": "x", "colors": []}, {"name": "x", "colors": "#fff"}])
def test_a_file_that_is_not_a_theme_is_refused_with_a_message(data):
    with pytest.raises(themes.ThemeError) as raised:
        themes.parse(data)
    assert str(raised.value)


def test_names_are_tidied_and_kept_short():
    theme, _ = themes.parse({"name": "  My   very   " + "long " * 30 + "theme  "})
    assert len(theme.name) <= 40 and "  " not in theme.name


def test_a_theme_named_like_a_built_in_one_gets_its_own_id():
    theme, _ = themes.parse({"name": "Dark"})
    assert theme.id == "custom:dark-custom" and themes.slug("System") == "system-custom"
    assert themes.slug("!!!") == "theme"


def test_load_file_reads_json_and_names_unnamed_themes_after_the_file(tmp_path):
    path = tmp_path / "ocean-blue.json"
    path.write_text(json.dumps({"colors": {"accent": "#00aaff"}}))
    theme, _ = themes.load_file(path)
    assert theme.name == "Ocean Blue"


def test_load_file_refuses_damaged_huge_and_missing_files(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(themes.ThemeError):
        themes.load_file(bad)
    huge = tmp_path / "huge.json"
    huge.write_text(json.dumps({"name": "x", "pad": "a" * (themes.MAX_FILE_BYTES + 10)}))
    with pytest.raises(themes.ThemeError, match="too large"):
        themes.load_file(huge)
    with pytest.raises(themes.ThemeError):
        themes.load_file(tmp_path / "missing.json")


# ------------------------------------------------------------------- contrast
def test_contrast_ratio_matches_the_usual_definition():
    assert themes.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert themes.contrast_ratio("#777777", "#777777") == pytest.approx(1.0)


def test_unreadable_text_is_reported_in_plain_words():
    theme, _ = themes.parse({"name": "x", "colors": {"text": "#232830", "panel": "#232830"}})
    problems = themes.contrast_problems(theme.colors)
    assert any("channel strips" in p for p in problems)
    assert all("contrast" in p for p in problems)


def test_a_theme_that_only_changes_the_accent_is_still_readable():
    theme, _ = themes.parse({"name": "x", "colors": {"accent": "#ff00ff"}})
    assert themes.contrast_problems(theme.colors) == []


# ------------------------------------------------------------------- the folder of imported themes
def test_imported_themes_are_stored_listed_and_removed(tmp_path):
    folder = tmp_path / "themes"
    theme, _ = themes.parse({"name": "Moonlight", "colors": {"accent": "#7c5cff"}})
    stored = themes.save_custom(theme, folder)
    assert stored.id == "custom:moonlight" and (folder / "moonlight.json").is_file()
    listed = themes.custom_themes(folder)
    assert [t.id for t in listed] == ["custom:moonlight"] and listed[0].colors["accent"] == "#7c5cff"
    assert themes.resolve("custom:moonlight", True, folder).name == "Moonlight"
    assert themes.remove_custom("custom:moonlight", folder) and themes.custom_themes(folder) == []


def test_importing_the_same_name_again_replaces_it(tmp_path):
    folder = tmp_path / "themes"
    for accent in ("#111111", "#222222"):
        theme, _ = themes.parse({"name": "Same", "colors": {"accent": accent}})
        themes.save_custom(theme, folder)
    listed = themes.custom_themes(folder)
    assert len(listed) == 1 and listed[0].colors["accent"] == "#222222"


def test_a_stored_theme_can_be_exported_and_imported_again_unchanged(tmp_path):
    original = themes.BUILT_IN["purple"]
    path = tmp_path / "out.json"
    path.write_text(json.dumps(themes.export_dict(themes.Theme("custom:x", "Mine", "dark", original.colors))))
    again, notes = themes.load_file(path)
    assert notes == [] and again.colors == original.colors and again.name == "Mine"


def test_removing_a_theme_can_never_reach_outside_the_folder(tmp_path):
    folder = tmp_path / "themes"
    folder.mkdir()
    outside = tmp_path / "precious.json"
    outside.write_text("{}")
    for sneaky in ("custom:../precious", "custom:..", "custom:", "custom:/etc/passwd", "custom:.hidden", "dark", ""):
        assert not themes.remove_custom(sneaky, folder)
    assert outside.exists()


def test_a_damaged_file_in_the_folder_is_skipped(tmp_path):
    folder = tmp_path / "themes"
    folder.mkdir()
    (folder / "broken.json").write_text("{nope")
    (folder / "fine.json").write_text(json.dumps({"name": "Fine"}))
    (folder / "notes.txt").write_text("hello")
    assert [t.name for t in themes.custom_themes(folder)] == ["Fine"]
    assert themes.custom_themes(tmp_path / "nowhere") == [] and themes.custom_themes(None) == []


def test_the_folder_is_capped_so_a_crowded_one_cannot_slow_the_menu(tmp_path):
    folder = tmp_path / "themes"
    folder.mkdir()
    for i in range(themes.MAX_CUSTOM + 15):
        (folder / f"t{i:03d}.json").write_text(json.dumps({"name": f"T{i}"}))
    assert len(themes.custom_themes(folder)) == themes.MAX_CUSTOM


# ------------------------------------------------------------------- which theme a saved choice means
def test_resolve_follows_the_system_and_falls_back_to_dark(tmp_path):
    assert themes.resolve("system", system_dark=True).id == "dark"
    assert themes.resolve("system", system_dark=False).id == "light"
    assert themes.resolve("purple").id == "purple"
    for unknown in ("nonsense", "", "custom:missing", None, 5):
        assert themes.resolve(unknown, True, tmp_path).id == "dark"


def test_the_theme_is_saved_with_the_settings_and_junk_is_ignored():
    mixer = Mixer.default()
    assert mixer.theme == "dark"
    mixer.theme = "purple"
    assert Mixer.from_dict(mixer.to_dict()).theme == "purple"
    for junk in (5, None, "", "x" * 200, ["dark"]):
        data = Mixer.default().to_dict()
        data["theme"] = junk
        assert Mixer.from_dict(data).theme == "dark"
    old = Mixer.default().to_dict()
    del old["theme"]  # settings saved by an older version
    assert Mixer.from_dict(old).theme == "dark"


# ------------------------------------------------------------------- in the window
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.ui import LevelMeter, MainWindow  # noqa: E402


@pytest.fixture
def win(qapp, tmp_path):
    system = MockSystem()
    system.add_demo_streams()
    engine = Engine(Mixer.demo(), system, NullIO(realtime=False), NullLinker())
    engine.start()
    window = MainWindow(engine, config_file=tmp_path / "config.json")
    yield window
    window.shutdown()
    themes.set_current(themes.DARK)


def _theme_menu(win):
    settings = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Settings")
    menu = next(a.menu() for a in settings.actions() if a.menu() and a.text().replace("&", "") == "Theme")
    win._fill_theme_menu()
    return menu


def test_the_theme_menu_lists_the_themes_and_ticks_the_one_in_use(win):
    menu = _theme_menu(win)
    items = [(a.text().replace("&", ""), a.isChecked()) for a in menu.actions() if a.text() and a.isCheckable()]
    assert items == [("Dark", True), ("Light", False), ("High contrast", False), ("Retro Purple", False),
                     ("Midnight Blue", False), ("Amber Console", False), ("Paper", False), ("Match my system", False)]
    tail = [a.text().replace("&", "") for a in menu.actions() if a.text() and not a.isCheckable()]
    assert tail == ["Import theme…", "Export current theme…", "Get more themes…"]


def test_choosing_a_theme_changes_the_window_the_setting_and_the_tick(win):
    dark_sheet = win.styleSheet()
    menu = _theme_menu(win)
    next(a for a in menu.actions() if a.text() == "Retro Purple").trigger()
    assert win.engine.mixer.theme == "purple" and win.styleSheet() != dark_sheet
    assert themes.BUILT_IN["purple"].colors["bg"] in win.styleSheet()
    assert "Retro Purple" in win.status_label.text()
    menu = _theme_menu(win)
    assert [a.text() for a in menu.actions() if a.isChecked()] == ["Retro Purple"]
    assert win.autosave_timer.isActive()  # the choice is part of the settings that save themselves
    assert json.loads(win._snapshot())["theme"] == "purple"


def test_the_palette_follows_the_theme_for_dialogs_and_tooltips(win):
    from PySide6.QtGui import QColor, QGuiApplication, QPalette

    win.apply_theme("light")
    palette = QGuiApplication.palette()
    assert palette.color(QPalette.ColorRole.Window) == QColor(themes.LIGHT["bg"])
    assert palette.color(QPalette.ColorRole.ToolTipBase) == QColor(themes.LIGHT["popup"])
    win.apply_theme("dark")
    assert QGuiApplication.palette().color(QPalette.ColorRole.Window) == QColor(themes.DARK["bg"])


def test_the_meters_pick_up_the_new_colours(win):
    from PySide6.QtGui import QColor

    meters = win.findChildren(LevelMeter)
    assert meters and all(m._well == QColor(themes.DARK["well"]) for m in meters)
    meters[0]._lit_pixmap()
    win.apply_theme("light")
    assert all(m._well == QColor(themes.LIGHT["well"]) for m in meters)
    assert all(m._lit is None for m in meters)  # redrawn in the new colours on the next paint


def test_match_my_system_follows_the_desktop(win, monkeypatch):
    monkeypatch.setattr(win, "_system_is_dark", lambda: False)
    win.choose_theme("system")
    assert win.engine.mixer.theme == "system" and themes.LIGHT["bg"] in win.styleSheet()
    assert "following your system" in win.status_label.text()
    monkeypatch.setattr(win, "_system_is_dark", lambda: True)
    win._on_system_scheme_changed()  # the desktop switched while Sluice was running
    assert themes.DARK["bg"] in win.styleSheet()
    win.apply_theme("purple")
    before = win.styleSheet()
    monkeypatch.setattr(win, "_system_is_dark", lambda: False)
    win._on_system_scheme_changed()  # not following the system any more: nothing changes
    assert win.styleSheet() == before


def test_the_saved_theme_is_used_when_the_window_starts(qapp, tmp_path):
    mixer = Mixer.demo()
    mixer.theme = "contrast"
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    window = MainWindow(engine, config_file=tmp_path / "config.json")
    try:
        assert themes.BUILT_IN["contrast"].colors["accent"] in window.styleSheet()
    finally:
        window.shutdown()
        themes.set_current(themes.DARK)


def _write(path, **data):
    path.write_text(json.dumps(data))
    return path


def test_importing_a_theme_stores_it_applies_it_and_lists_it(win, tmp_path):
    source = _write(tmp_path / "mine.json", name="Moonlight", colors={"accent": "#7c5cff"})
    stored = win.import_theme_from(source)
    assert stored.id == "custom:moonlight" and win.engine.mixer.theme == "custom:moonlight"
    assert (tmp_path / "themes" / "moonlight.json").is_file()
    assert "#7c5cff" in win.styleSheet() and "imported" in win.status_label.text()
    menu = _theme_menu(win)
    assert ("Moonlight", True) in [(a.text(), a.isChecked()) for a in menu.actions() if a.isCheckable()]
    assert any(a.menu() and "Remove" in a.text() for a in menu.actions())


def test_a_hard_to_read_theme_asks_first_and_is_not_kept_on_no(win, tmp_path, monkeypatch):
    source = _write(tmp_path / "faint.json", name="Faint", colors={"text": "#232830", "panel": "#232830", "bg": "#232830"})
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No))
    with pytest.raises(themes.ThemeError):
        win.import_theme_from(source)
    assert asked and "may be hard to read" in asked[0] and "Faint" in asked[0]
    assert win.engine.mixer.theme == "dark" and not (tmp_path / "themes").exists()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    assert win.import_theme_from(source).name == "Faint"
    assert (tmp_path / "themes" / "faint.json").is_file()


def test_a_bad_theme_file_changes_nothing(win, tmp_path):
    before = win.styleSheet()
    for source in (_write(tmp_path / "a.json", name="A", colors={"accent": "url(x)"}), tmp_path / "missing.json"):
        with pytest.raises(themes.ThemeError):
            win.import_theme_from(source)
    assert win.styleSheet() == before and win.engine.mixer.theme == "dark"
    assert not (tmp_path / "themes").exists()


def test_import_theme_shows_the_problem_in_a_message_box(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    bad = _write(tmp_path / "bad.json", name="Bad", colors={"bg": "nope"})
    shown = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    win.import_theme()
    assert shown and "not a colour" in shown[0]


def test_export_writes_a_file_that_imports_back(win, tmp_path):
    win.apply_theme("purple")
    target = tmp_path / "export.json"
    win.export_theme_to(target)
    data = json.loads(target.read_text())
    assert data["name"] == "Retro Purple copy" and set(data["colors"]) == set(themes.TOKEN_NAMES)
    stored = win.import_theme_from(target)
    assert stored.colors == themes.BUILT_IN["purple"].colors


def test_removing_the_theme_in_use_goes_back_to_dark(win, tmp_path):
    win.import_theme_from(_write(tmp_path / "m.json", name="Moonlight", colors={"accent": "#7c5cff"}))
    win.remove_theme("custom:moonlight")
    assert win.engine.mixer.theme == "dark" and not (tmp_path / "themes" / "moonlight.json").exists()
    assert themes.DARK["bg"] in win.styleSheet()


def test_a_saved_choice_that_lost_its_file_shows_dark_and_says_so(win, tmp_path):
    win.engine.mixer.theme = "custom:gone"
    assert win.current_theme().id == "dark"
    menu = _theme_menu(win)
    assert any("no longer in the themes folder" in a.text() for a in menu.actions())


def test_demo_mode_has_no_themes_folder(qapp):
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    window = MainWindow(engine, config_file=None)
    try:
        with pytest.raises(themes.ThemeError, match="Demo mode"):
            window.import_theme_from("whatever.json")
        window.open_theme_folder()
        assert "Demo mode" in window.status_label.text()
        window.apply_theme("light")  # the built-in ones work everywhere
        assert themes.LIGHT["bg"] in window.styleSheet()
    finally:
        window.shutdown()
        themes.set_current(themes.DARK)


def test_the_dialogs_that_set_their_own_colours_use_the_theme(win):
    from sluice import ui_whatsnew

    win.apply_theme("light")
    dialog = ui_whatsnew.NotesDialog("t", "h", "see `code` and [a link](https://example.com)", "", "", win)
    css = dialog.view.document().defaultStyleSheet()
    assert themes.LIGHT["link"] in css and themes.LIGHT["code"] in css


def test_get_more_themes_opens_the_collection_on_the_project_page(win, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    from sluice import ui

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    menu = _theme_menu(win)
    action = next(a for a in menu.actions() if a.text().replace("&", "") == "Get more themes…")
    action.trigger()
    assert opened == [ui.THEMES_URL] and ui.THEMES_URL == ui.PROJECT_URL + "/tree/main/themes"


def test_an_imported_copy_of_a_built_in_theme_shows_the_built_in_one_ticked(win, tmp_path):
    folder = tmp_path / "themes"
    folder.mkdir()
    (folder / "midnight-blue.json").write_text(json.dumps(themes.export_dict(themes.BUILT_IN["midnight"])))
    win.engine.mixer.theme = "custom:midnight-blue"
    menu = _theme_menu(win)
    items = [(a.text().replace("&", ""), a.isChecked()) for a in menu.actions() if a.text() and a.isCheckable()]
    assert items.count(("Midnight Blue", True)) == 1 and sum(1 for n, _ in items if n == "Midnight Blue") == 1
    assert win.current_theme().name == "Midnight Blue"


def test_the_window_tick_sends_the_heartbeat(win, monkeypatch):
    from sluice import logs

    beats = []
    monkeypatch.setattr(logs, "heartbeat", lambda: beats.append(1))
    win._tick_engine()
    assert beats == [1]
