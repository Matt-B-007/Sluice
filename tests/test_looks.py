# SPDX-License-Identifier: GPL-3.0-or-later
"""The Look setting (shapes and sizes of the window, apart from the colour theme)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sluice import themes
from sluice.model import Mixer


def test_every_theme_builds_a_complete_style_sheet_in_every_look():
    for theme in themes.BUILT_IN.values():
        for skin in themes.SKINS:
            sheet = themes.build_style(theme.colors, skin)
            assert sheet.strip() and "$" not in sheet.replace("$$", ""), (theme.id, skin)


def test_an_unknown_look_falls_back_to_the_default():
    assert themes.valid_skin("original") == themes.DEFAULT_SKIN  # 0.12.0: retired
    assert themes.valid_skin("nexus9") == themes.DEFAULT_SKIN and themes.valid_skin(None) == themes.DEFAULT_SKIN
    assert themes.build_style(themes.DARK, "nexus9") == themes.build_style(themes.DARK, "calm")


def test_the_look_is_saved_and_read_back_and_a_bad_value_is_ignored():
    mixer = Mixer.default() if hasattr(Mixer, "default") else Mixer([], [])
    assert mixer.skin == "calm"
    mixer.skin = "tile"
    data = json.loads(json.dumps(mixer.to_dict()))
    assert data["skin"] == "tile" and "look" not in data and "widget_look" not in data  # 0.12.3: the old keys are gone
    assert Mixer.from_dict(data).skin == "tile"
    old = {k: v for k, v in data.items() if k not in ("skin", "widget_skin", "skin_colors")}
    old["look"] = "tile"
    assert Mixer.from_dict(old).skin == "tile"  # settings written by 0.11 still load
    old["look"], old["widget_look"] = "original", "original"  # 0.12.0: the Original skin is retired: such settings show Calm
    assert Mixer.from_dict(old).skin == "calm" and Mixer.from_dict(old).widget_skin == "calm"
    data["skin"] = "sparkly"
    assert Mixer.from_dict(data).skin == "calm"
    del data["skin"]
    assert Mixer.from_dict(data).skin == "calm"


# ----------------------------------------------------------------------------- the window
import pytest  # noqa: E402

pytest.importorskip("PySide6")

from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402


@pytest.fixture
def rig(qapp, tmp_path):
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.show()
    yield win, engine
    win.shutdown()


def test_choosing_a_look_restyles_the_window_and_is_remembered(rig, tmp_path):
    win, engine = rig
    sheet = lambda: win.centralWidget().styleSheet()  # noqa: E731  (the skin dresses the window's content)
    before = sheet()
    win.choose_skin("tile")
    assert engine.mixer.skin == "tile" and sheet() != before
    assert sheet() == themes.build_style(themes.skin_colors(win.current_theme(), "tile"), "tile")
    # menus and dialogs: Calm in the theme's own colours, narrowed so none of it reaches the mixer
    from PySide6.QtWidgets import QApplication

    shared = QApplication.instance().styleSheet()  # 0.11.7: on the application, so menus of other windows (tray, widgets) get it
    assert shared == themes.shared_style(themes.skin_colors(win.current_theme(), "calm"))
    assert all(
        rule.startswith(("QDialog", "QMessageBox", "QMenu", "QToolTip", "QLabel#menuheading", "QFrame#menupanel"))
        for rule in shared.splitlines()
        if "{" in rule
    )
    win.choose_skin("nonsense")  # unknown: treated as the default look
    assert engine.mixer.skin == "calm" and sheet() == before
    win.choose_skin("tile")
    engine.save_config(tmp_path / "saved.json")
    assert Mixer.load(tmp_path / "saved.json").skin == "tile"


def test_the_look_menu_lists_the_looks_with_the_current_one_ticked(rig):
    win, engine = rig
    win._fill_skin_menu()
    actions = {a.text(): a.isChecked() for a in win.skin_menu.actions() if a.isCheckable()}
    assert set(actions) == set(themes.SKINS.values())
    assert actions[themes.SKINS["calm"]] and not actions[themes.SKINS["tile"]]
    win.choose_skin("tile")
    win._fill_skin_menu()
    assert {a.text(): a.isChecked() for a in win.skin_menu.actions()}[themes.SKINS["tile"]]


def test_both_looks_fit_the_buttons_in_both_layouts(rig):
    win, engine = rig
    for skin in themes.SKINS:
        win.choose_skin(skin)
        for layout in ("columns", "rows"):
            win.set_layout(layout)
            for strip in win.strips:
                assert strip.width() > 0 and strip.height() > 0


def test_bug_report_says_which_look_and_layout_are_on_screen(tmp_path, monkeypatch):
    from sluice import report

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"layout": "free"}))
    monkeypatch.setattr(report, "config_path", lambda: cfg)
    themes.set_skin("calm")
    themes.set_reduce_effects(False)
    assert report.skin_summary() == "Skin: calm. Layout shown: columns (saved as free). Effects reduced: no.\n"
    themes.set_skin("tile")
    themes.set_reduce_effects(True)
    cfg.write_text(json.dumps({"layout": "rows"}))
    assert report.skin_summary() == "Skin: tile. Layout shown: rows. Effects reduced: yes.\n"
    cfg.write_text("not json")
    assert "Layout shown: columns" in report.skin_summary()
    themes.set_skin("calm")
    themes.set_reduce_effects(False)


def test_the_engine_checks_devices_less_often_while_the_window_is_hidden(rig):
    win, engine = rig
    from sluice.engine import REFRESH_SECONDS

    win.show()
    win._window_state_changed()
    assert engine.refresh_seconds == REFRESH_SECONDS
    win.hide()
    win._window_state_changed()
    assert engine.refresh_seconds > REFRESH_SECONDS
    win.show()
    win._window_state_changed()
    assert engine.refresh_seconds == REFRESH_SECONDS


def test_compare_skins_opens_settings_with_a_picture_of_each(rig):
    """0.12.2: Compare skins is Settings > Themes and skins (one window fewer), where every skin has its picture."""
    from sluice.ui_skins import draw_preview

    win, engine = rig
    win.compare_skins()
    settings = win.settings_window
    assert settings.isVisible() and set(settings.skin_cards) == set(themes.SKINS)
    settings.skin_cards["tile"].click()
    assert engine.mixer.skin == "tile"
    colors = themes.skin_colors(win.current_theme(), "calm")
    for skin in themes.SKINS:
        assert not draw_preview(skin, colors).isNull()
    settings.close()


def test_the_look_menu_offers_compare_looks(rig):
    win, _ = rig
    win._fill_skin_menu()
    assert any("Compare skins" in a.text() for a in win.skin_menu.actions())


def test_an_older_rust_engine_is_noticed_and_a_newer_or_missing_one_is_not():
    from sluice import spectral

    assert spectral.rust_is_older("0.9.6", "0.10.1")
    assert spectral.rust_is_older("0.10.0", "0.10.1")
    assert not spectral.rust_is_older("0.10.1", "0.10.1")
    assert not spectral.rust_is_older("0.11.0", "0.10.1")
    assert not spectral.rust_is_older("", "0.10.1")  # no Rust at all is not "older"


def test_nexus_and_glass_were_retired_and_saved_choices_show_the_closest_skin(tmp_path):
    """0.13.1 (House Standard): two skins are kept, Calm and Tile; there is no blur. A saved Nexus shows Tile, Glass shows Calm,
    for the window and for the desktop widgets."""
    from sluice import themes
    from sluice.model import Mixer

    assert set(themes.SKINS) == {"calm", "tile"}
    assert themes.valid_skin("nexus") == "tile" and themes.valid_skin("glass") == "calm"
    data = Mixer.demo().to_dict()
    data["widget_skin"] = "glass"
    assert Mixer.from_dict(data).widget_skin == "calm"
    data["widget_skin"] = "nexus"
    assert Mixer.from_dict(data).widget_skin == "tile"


def test_the_compact_list_can_be_chosen_for_a_second_screen():
    """0.13.1: from Nexus, the "second screen beside a game" use: the compact list at any window size."""
    from sluice import sizing
    from sluice.model import Mixer

    assert sizing.plan_for(1920, 1080, "list", "tile").mode == "mini"
    assert sizing.plan_for(1920, 1080, "columns", "tile").mode == "columns"
    data = Mixer.demo().to_dict()
    data["layout"] = "list"
    assert Mixer.from_dict(data).layout == "list"
