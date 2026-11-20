# SPDX-License-Identifier: GPL-3.0-or-later
"""0.11.0: the Look setting (shapes and sizes of the window, apart from the colour theme)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sluice import themes
from sluice.model import Mixer


def test_every_theme_builds_a_complete_style_sheet_in_every_look():
    for theme in themes.BUILT_IN.values():
        for look in themes.LOOKS:
            sheet = themes.build_style(theme.colors, look)
            assert sheet.strip() and "$" not in sheet.replace("$$", ""), (theme.id, look)


def test_the_original_look_is_the_old_sheet_not_the_current_one():
    colors = themes.DARK
    current, original = themes.build_style(colors, "calm"), themes.build_style(colors, "original")
    assert current != original
    assert "border-radius: 24px" in current and "border-radius: 24px" not in original.split("Rules for parts added")[0]
    assert "QFrame#strip" in original and "QPushButton#primary" in original  # the later parts are not left bare


def test_an_unknown_look_falls_back_to_the_default():
    assert themes.valid_look("original") == "original"
    assert themes.valid_look("nexus9") == themes.DEFAULT_LOOK and themes.valid_look(None) == themes.DEFAULT_LOOK
    assert themes.build_style(themes.DARK, "nexus9") == themes.build_style(themes.DARK, "calm")


def test_the_look_is_saved_and_read_back_and_a_bad_value_is_ignored():
    mixer = Mixer.default() if hasattr(Mixer, "default") else Mixer([], [])
    assert mixer.look == "calm"
    mixer.look = "original"
    data = json.loads(json.dumps(mixer.to_dict()))
    assert data["look"] == "original"
    assert Mixer.from_dict(data).look == "original"
    data["look"] = "sparkly"
    assert Mixer.from_dict(data).look == "calm"
    del data["look"]
    assert Mixer.from_dict(data).look == "calm"


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
    before = win.styleSheet()
    win.choose_look("original")
    assert engine.mixer.look == "original" and win.styleSheet() != before
    assert win.styleSheet() == themes.build_style(themes.look_colors(win.current_theme(), "original"), "original")
    win.choose_look("nonsense")  # unknown: treated as the default look
    assert engine.mixer.look == "calm" and win.styleSheet() == before
    win.choose_look("original")
    engine.save_config(tmp_path / "saved.json")
    assert Mixer.load(tmp_path / "saved.json").look == "original"


def test_the_look_menu_lists_the_looks_with_the_current_one_ticked(rig):
    win, engine = rig
    win._fill_look_menu()
    actions = {a.text(): a.isChecked() for a in win.look_menu.actions() if a.isCheckable()}
    assert set(actions) == set(themes.LOOKS.values())
    assert actions[themes.LOOKS["calm"]] and not actions[themes.LOOKS["original"]]
    win.choose_look("original")
    win._fill_look_menu()
    assert {a.text(): a.isChecked() for a in win.look_menu.actions()}[themes.LOOKS["original"]]


def test_both_looks_fit_the_buttons_in_both_layouts(rig):
    win, engine = rig
    for look in themes.LOOKS:
        win.choose_look(look)
        for layout in ("columns", "rows"):
            win.set_layout(layout)
            for strip in win.strips:
                assert strip.width() > 0 and strip.height() > 0


def test_the_original_look_has_the_parts_of_0_9_7_and_still_works(rig):
    win, engine = rig
    win.choose_look("original")
    assert win.menuBar().isVisibleTo(win) and not win.top_bar.isVisibleTo(win) and win.orig_apps_bar.isVisibleTo(win)
    strip = next(s for s in win.strips if s.channel.id == "game")
    assert strip.original and strip.link.text() == "LINK" and strip.add_button.text() == "+ Add device or app"
    assert all(m.text() == "M" for m in strip.mutes.values())
    assert strip.fx_button.text().startswith("Effects")
    assert strip.width() == 180 and win.mix_strips[0].mute.text() == "M" and win.mix_strips[0].limiter.text() == "LIM"
    assert win.add_mix_button is not None and win.add_mix_button.objectName() == "addmix"
    # the controls still drive the engine
    strip.mutes["monitor"].click()
    assert engine.mixer.channel("game").mutes["monitor"] is True
    before = engine.mixer.channel("game").linked
    strip.link.click()
    assert engine.mixer.channel("game").linked is (not before)
    fader = strip.faders["monitor"]
    fader.setGain(-100)
    assert engine.mixer.channel("game").levels["monitor"] == -10.0
    win.mix_strips[0].limiter.click()
    win.choose_look("calm")  # and back: the Calm parts return
    assert win.top_bar.isVisibleTo(win) and not win.menuBar().isVisibleTo(win)
    assert not any(s.original for s in win.strips) and win.strips[0].link.text() == ""


def test_the_original_look_shows_the_0_9_7_colours_for_built_in_themes_only(rig):
    win, engine = rig
    dark = themes.BUILT_IN["dark"]
    assert themes.look_colors(dark, "calm") == dark.colors
    original = themes.look_colors(dark, "original")
    assert original["bg"] == "#181b20" and original["fill"] == "#2c5f48" and set(themes.TOKEN_NAMES) <= set(original)
    custom = themes.Theme("custom:mine", "Mine", "dark", {**themes.DARK, "accent": "#ff0000"})
    assert themes.look_colors(custom, "original") == custom.colors


def test_the_original_look_is_chosen_before_the_window_exists(qapp, tmp_path):
    mixer = Mixer.demo()
    mixer.look = "original"
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.show()
    try:
        assert win.strips and all(s.original for s in win.strips) and win.menuBar().isVisibleTo(win)
    finally:
        win.shutdown()
        themes.set_look("calm")


# ----------------------------------------------------------------------------- Nexus (0.11.1)
def test_nexus_is_a_look_with_its_own_dark_and_a_style_that_adds_to_calm(rig):
    win, engine = rig
    assert "nexus" in themes.LOOKS and themes.LOOKS["nexus"] == "Nexus"
    dark = themes.BUILT_IN["dark"]
    nexus = themes.look_colors(dark, "nexus")
    assert nexus["bg"] == "#05080f" and nexus["accent"] == "#22e5ff" and set(themes.TOKEN_NAMES) <= set(nexus)
    assert themes.look_colors(themes.BUILT_IN["paper"], "nexus") == themes.BUILT_IN["paper"].colors  # other themes keep their colours
    calm_sheet = themes.build_style(nexus, "calm")
    assert themes.build_style(nexus, "nexus").startswith(calm_sheet) and len(themes.build_style(nexus, "nexus")) > len(calm_sheet)
    win.choose_look("nexus")
    assert engine.mixer.look == "nexus" and win.styleSheet() == themes.build_style(themes.look_colors(win.current_theme(), "nexus"), "nexus")
    win._fill_look_menu()
    assert {a.text(): a.isChecked() for a in win.look_menu.actions()}["Nexus"]
    for look in themes.LOOKS:
        win.choose_look(look)
        for layout in ("columns", "rows"):
            win.set_layout(layout)
            assert win.strips
    win.choose_look("calm")
    win.set_layout("columns")


def test_nexus_channel_and_mix_cards_have_rings_that_follow_the_sound_and_other_looks_do_not(rig):
    win, engine = rig
    win.choose_look("nexus")
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
    win.choose_look("calm")
    assert all(s.ring is None for s in win.strips) and all(m.ring is None for m in win.mix_strips)
    win.choose_look("original")
    assert all(s.ring is None for s in win.strips)
    win.choose_look("calm")


def test_free_layout_belongs_to_nexus_and_nodes_open_cards_and_remember_places(rig):
    win, engine = rig
    win.set_layout("free")
    assert win.layout_mode == "columns"  # not in Calm
    win.choose_look("nexus")
    assert win.layout_mode == "free" and len(win.canvas.nodes) == len(win.strips) + len(win.mix_strips)
    node = next(iter(win.canvas.nodes.values()))
    win.canvas.toggle(node)
    assert win.canvas.open_node is node and not node.card.isHidden()
    win.canvas.toggle(node)
    assert win.canvas.open_node is None and node.card.isHidden()
    node.move(300, 300)
    win.canvas.remember(node)
    assert engine.mixer.free_positions[node.key] == [300, 300]
    win._rebuild_free()
    assert win.canvas.nodes[node.key].pos().x() == 300
    win.canvas.tidy()
    assert engine.mixer.free_positions == {}
    win._update_meters()
    win.choose_look("calm")
    assert win.layout_mode == "columns" and engine.mixer.layout == "free"  # the choice is kept


def test_reduce_effects_is_saved_and_stops_the_waveform(rig):
    win, engine = rig
    win.choose_look("nexus")
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
    themes.set_look("calm")
    themes.set_reduce_effects(False)
    assert report.look_summary() == "Look: calm. Layout shown: columns (saved as free). Effects reduced: no.\n"
    themes.set_look("nexus")
    themes.set_reduce_effects(True)
    assert report.look_summary() == "Look: nexus. Layout shown: free. Effects reduced: yes.\n"
    cfg.write_text("not json")
    assert "Layout shown: columns" in report.look_summary()
    themes.set_look("calm")
    themes.set_reduce_effects(False)


def test_free_canvas_grows_to_hold_every_node(rig):
    win, engine = rig
    win.choose_look("nexus")
    win.set_layout("free")
    key = next(iter(win.canvas.nodes))
    engine.mixer.free_positions[key] = [100, 1500]
    win._rebuild_free()
    win.canvas.add_node  # the canvas is the one the window now holds
    win.set_layout("columns")
    win.set_layout("free")
    node = win.canvas.nodes[key]
    assert node.y() == 1500 and win.canvas.minimumHeight() >= 1500 + node.height()


def test_nexus_colours_apply_to_the_dark_themes_and_can_be_switched_off(rig):
    win, engine = rig
    win.choose_look("nexus")
    for theme_id in ("dark", "purple", "midnight", "amber"):
        win.choose_theme(theme_id)
        assert themes.color("bg") == "#05080f"
    win.choose_theme("contrast")  # made to be read: never changed
    assert themes.color("bg") != "#05080f"
    win.choose_theme("light")
    assert themes.color("bg") != "#05080f"
    win.choose_theme("midnight")
    win.set_nexus_colors(False)
    assert themes.color("bg") == themes.BUILT_IN["midnight"].colors["bg"] and not engine.mixer.nexus_colors
    win.choose_theme("dark")
    assert themes.color("bg") == themes.BUILT_IN["dark"].colors["bg"]
    win.set_nexus_colors(True)
    assert themes.color("bg") == "#05080f"
    win.choose_look("calm")
    assert themes.color("bg") != "#05080f"


def test_nexus_colours_setting_is_saved_and_defaults_on():
    from sluice.model import Mixer
    assert Mixer.demo().nexus_colors is True
    data = Mixer.demo().to_dict()
    assert data["nexus_colors"] is True
    data["nexus_colors"] = False
    assert Mixer.from_dict(data).nexus_colors is False
    del data["nexus_colors"]
    assert Mixer.from_dict(data).nexus_colors is True


def test_halos_are_drawn_once_and_reused_and_stop_with_reduce_effects(rig):
    from sluice import ui
    win, engine = rig
    win.choose_look("nexus")
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
    from sluice.ui_looks import CompareLooksDialog, draw_preview
    win, engine = rig
    dialog = CompareLooksDialog(win)
    assert set(dialog.buttons) == set(themes.LOOKS)
    assert not dialog.buttons["calm"].isEnabled()  # the one in use
    dialog.buttons["nexus"].click()
    assert engine.mixer.look == "nexus"
    assert not dialog.buttons["nexus"].isEnabled() and dialog.buttons["calm"].isEnabled()
    colors = themes.look_colors(win.current_theme(), "original")
    for look in themes.LOOKS:
        assert not draw_preview(look, colors).isNull()


def test_the_look_menu_offers_compare_looks(rig):
    win, _ = rig
    win._fill_look_menu()
    assert any("Compare looks" in a.text() for a in win.look_menu.actions())


def test_an_older_rust_engine_is_noticed_and_a_newer_or_missing_one_is_not():
    from sluice import spectral
    assert spectral.rust_is_older("0.9.6", "0.10.1")
    assert spectral.rust_is_older("0.10.0", "0.10.1")
    assert not spectral.rust_is_older("0.10.1", "0.10.1")
    assert not spectral.rust_is_older("0.11.0", "0.10.1")
    assert not spectral.rust_is_older("", "0.10.1")  # no Rust at all is not "older"
