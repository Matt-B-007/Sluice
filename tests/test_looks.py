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
    assert data["skin"] == "tile" and data["look"] == "tile"  # 0.12.0: "skin", and the old key for going back to 0.11
    assert Mixer.from_dict(data).skin == "tile"
    old = {k: v for k, v in data.items() if k not in ("skin", "widget_skin", "skin_colors")}
    assert Mixer.from_dict(old).skin == "tile"  # settings written by 0.11 still load
    old["look"], old["widget_look"] = "original", "original"  # 0.12.0: the Original skin is retired: such settings show Calm
    assert Mixer.from_dict(old).skin == "calm" and Mixer.from_dict(old).widget_skin == "calm"
    data["skin"] = "sparkly"
    assert Mixer.from_dict(data).skin == "calm"
    del data["skin"], data["look"]
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
    assert all(rule.startswith(("QDialog", "QMessageBox", "QMenu", "QToolTip", "QLabel#menuheading", "QFrame#menupanel"))
               for rule in shared.splitlines() if "{" in rule)
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


def test_nexus_is_a_look_with_its_own_dark_and_a_style_that_adds_to_calm(rig):
    win, engine = rig
    assert "nexus" in themes.SKINS and themes.SKINS["nexus"] == "Nexus"
    dark = themes.BUILT_IN["dark"]
    nexus = themes.skin_colors(dark, "nexus")
    assert nexus["bg"] == "#05080f" and nexus["accent"] == "#22e5ff" and set(themes.TOKEN_NAMES) <= set(nexus)
    assert themes.skin_colors(themes.BUILT_IN["paper"], "nexus") == themes.finish(themes.BUILT_IN["paper"].colors)  # others keep theirs
    calm_sheet = themes.build_style(nexus, "calm")
    nexus_sheet = themes.build_style(nexus, "nexus")  # the Calm sheet (with Nexus's Listen and Broadcast colours) and Nexus's rules after it
    assert nexus_sheet.split("\n")[1] == calm_sheet.split("\n")[1] and len(nexus_sheet) > len(calm_sheet) and "$glass" not in nexus_sheet
    win.choose_skin("nexus")
    assert engine.mixer.skin == "nexus" and win.centralWidget().styleSheet() == themes.build_style(themes.skin_colors(win.current_theme(), "nexus"), "nexus")
    win._fill_skin_menu()
    assert {a.text(): a.isChecked() for a in win.skin_menu.actions()}["Nexus"]
    for skin in themes.SKINS:
        win.choose_skin(skin)
        for layout in ("columns", "rows"):
            win.set_layout(layout)
            assert win.strips
    win.choose_skin("calm")
    win.set_layout("columns")


def test_nexus_channel_and_mix_cards_have_rings_that_follow_the_sound_and_other_looks_do_not(rig):
    win, engine = rig
    win.choose_skin("nexus")
    assert all(s.ring is not None for s in win.strips) and all(m.ring is not None for m in win.mix_strips)
    ring = win.strips[0].ring
    assert ring._level == 0.0
    ring.push(0.5)
    assert ring._level > 0.1 and ring._step > 0
    for _ in range(80):  # the bars fall back by themselves when the sound stops
        ring.push(0.0)
    assert ring._level <= 0.03 and ring._step == 0
    win._update_meters()  # the window feeds every ring without error
    pixmap = ring.grab()
    assert not pixmap.isNull()
    game = next(s for s in win.strips if s.channel.id == "game")
    assert game.ring._picture_for(1.0).width() >= 36  # the picture is the app's own icon (or its letter)
    win.choose_skin("calm")
    assert all(s.ring is None for s in win.strips) and all(m.ring is None for m in win.mix_strips)
    win.choose_skin("tile")
    assert all(s.ring is None for s in win.strips)
    win.choose_skin("calm")


def test_reduce_effects_is_saved_and_stops_the_waveform(rig):
    win, engine = rig
    win.choose_skin("nexus")
    win.set_reduce_effects(True)
    assert engine.mixer.reduce_effects and themes.reduce_effects()
    fader = next(iter(win.strips[0].faders.values()))
    fader._reveal = True
    fader._update_reveal()
    assert not fader._reveal
    win.set_reduce_effects(False)


def test_bug_report_says_which_look_and_layout_are_on_screen(tmp_path, monkeypatch):
    from sluice import report
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"layout": "free"}))
    monkeypatch.setattr(report, "config_path", lambda: cfg)
    themes.set_skin("calm")
    themes.set_reduce_effects(False)
    assert report.skin_summary() == "Skin: calm. Layout shown: columns (saved as free). Effects reduced: no.\n"
    themes.set_skin("nexus")
    themes.set_reduce_effects(True)
    cfg.write_text(json.dumps({"layout": "rows"}))
    assert report.skin_summary() == "Skin: nexus. Layout shown: rows. Effects reduced: yes.\n"
    cfg.write_text("not json")
    assert "Layout shown: columns" in report.skin_summary()
    themes.set_skin("calm")
    themes.set_reduce_effects(False)


def test_nexus_colours_apply_to_dark_only_and_can_be_switched_off(rig):
    win, engine = rig
    win.choose_skin("nexus")
    win.choose_theme("dark")
    assert themes.color("bg") == "#05080f"
    for theme_id in ("purple", "midnight", "amber", "contrast", "light"):  # every other theme keeps its own colours (0.11.5)
        win.choose_theme(theme_id)
        assert themes.color("bg") == themes.BUILT_IN[theme_id].colors["bg"]
    win.choose_theme("dark")
    win.set_skin_colors(False)
    assert themes.color("bg") == themes.BUILT_IN["dark"].colors["bg"] and not engine.mixer.skin_colors
    win.set_skin_colors(True)
    assert themes.color("bg") == "#05080f"
    win.choose_skin("calm")
    assert themes.color("bg") != "#05080f"


def test_halos_are_drawn_once_and_reused_and_stop_with_reduce_effects(rig):
    from sluice import ui
    win, engine = rig
    win.choose_skin("nexus")
    ring = win.strips[0].ring
    ring.push(0.5)
    ring.grab()
    before = len(ui._GLOWS)
    assert before >= 1
    ring.push(0.45)
    ring.grab()
    assert len(ui._GLOWS) == before  # reused, not drawn again
    win.set_reduce_effects(True)
    ring.push(0.6)
    ring.grab()
    assert len(ui._GLOWS) == before
    win.set_reduce_effects(False)


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


def test_compare_looks_shows_every_look_and_picks_one(rig):
    from sluice.ui_skins import CompareSkinsDialog, draw_preview
    win, engine = rig
    dialog = CompareSkinsDialog(win)
    assert set(dialog.buttons) == set(themes.SKINS)
    assert not dialog.buttons["calm"].isEnabled()  # the one in use
    dialog.buttons["nexus"].click()
    assert engine.mixer.skin == "nexus"
    assert not dialog.buttons["nexus"].isEnabled() and dialog.buttons["calm"].isEnabled()
    colors = themes.skin_colors(win.current_theme(), "calm")
    for skin in themes.SKINS:
        assert not draw_preview(skin, colors).isNull()


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
