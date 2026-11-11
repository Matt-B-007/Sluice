# SPDX-License-Identifier: GPL-3.0-or-later
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton  # noqa: E402

from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import MONITOR, STREAM, Mixer  # noqa: E402
from sluice.ui import MainWindow, format_db, level_fraction  # noqa: E402
from sluice.ui_effects import EffectsDialog, ParamRow, format_value  # noqa: E402
from sluice.ui_widgets import parse_number  # noqa: E402


@pytest.fixture
def app(qapp):
    return qapp


@pytest.fixture
def ui(app, tmp_path):
    system = MockSystem()
    system.add_demo_streams()
    engine = Engine(Mixer.demo(), system, NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    yield win, system, engine
    win.shutdown()


def strip_for(win, channel_id):
    return next(s for s in win.strips if s.channel.id == channel_id)


def sinks(system):
    return {s.key: s.sink for s in system.streams}


def test_window_layout(ui):
    win, _, _ = ui
    assert [s.channel.id for s in win.strips] == ["mic", "browser", "game", "chat", "music", "system"]
    assert [m.mix.id for m in win.mix_strips] == [MONITOR, STREAM]
    assert set(strip_for(win, "mic").faders) == {MONITOR, STREAM}


def test_buttons_and_faders_reflect_the_model(ui):
    win, _, _ = ui
    mic = strip_for(win, "mic")
    assert mic.mutes[MONITOR].isChecked() and not mic.mutes[STREAM].isChecked()
    assert not mic.link.isChecked()
    assert strip_for(win, "game").link.isChecked()
    music = strip_for(win, "music")
    assert music.readouts[MONITOR].text() == "-8.0 dB"
    assert music.readouts[STREAM].text() == "-18.0 dB"


def test_mute_button_changes_the_mix(ui):
    win, _, engine = ui
    game = strip_for(win, "game")
    game.mutes[STREAM].click()
    assert engine.mixer.channel("game").mutes[STREAM] is True
    game.mutes[STREAM].click()
    assert engine.mixer.channel("game").mutes[STREAM] is False


def test_linked_faders_move_together_and_unlinked_ones_do_not(ui):
    win, _, engine = ui
    game = strip_for(win, "game")
    game.faders[MONITOR].setGain(-120)
    assert game.faders[STREAM].gain() == -120
    assert engine.mixer.channel("game").levels == {MONITOR: -12.0, STREAM: -12.0}
    assert game.readouts[STREAM].text() == "-12.0 dB"

    music = strip_for(win, "music")
    music.faders[MONITOR].setGain(-30)
    assert engine.mixer.channel("music").levels == {MONITOR: -3.0, STREAM: -18.0}

    music.link.click()  # linking snaps the stream fader to the monitor level
    assert music.faders[STREAM].gain() == -30


def test_double_click_resets_a_fader(ui):
    win, _, engine = ui
    music = strip_for(win, "music")
    QTest.mouseDClick(music.faders[MONITOR], Qt.MouseButton.LeftButton)
    assert engine.mixer.channel("music").levels[MONITOR] == 0.0


def test_mix_strip_controls(ui):
    win, _, engine = ui
    stream = win.mix_strips[1]
    stream.fader.setGain(-60)
    assert engine.mixer.mix(STREAM).gain_db == pytest.approx(-6.0)
    assert stream.readout.text() == "-6.0 dB"
    stream.mute.click()
    stream.limiter.click()
    assert engine.mixer.mix(STREAM).mute is True
    assert engine.mixer.mix(STREAM).limiter is False


def test_monitor_device_picker(ui):
    win, system, engine = ui
    combo = win.mix_strips[0].combo
    index = combo.findData(system.sinks[1].name)
    assert index >= 0
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    assert engine.mixer.mix(MONITOR).device == system.sinks[1].name
    assert ("sluice:out_monitor_L", f"{system.sinks[1].name}:in_L") in engine.linker.links


def test_combo_keeps_a_missing_saved_device(app):
    system = MockSystem()
    mixer = Mixer.default()
    mixer.mix(MONITOR).device = "alsa_output.unplugged"
    engine = Engine(mixer, system, NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine)
    combo = win.mix_strips[0].combo
    assert combo.currentData() == "alsa_output.unplugged"
    assert "missing" in combo.currentText()
    win.shutdown()


def test_adding_and_removing_a_device_chip(ui):
    win, system, engine = ui
    game = strip_for(win, "game")
    usb = system.sources[2].name
    game._add_device(usb)
    assert usb in engine.mixer.channel("game").devices
    assert ("%s:out_L" % usb, "sluice:in_game_L") in engine.linker.links
    game._remove_device(usb)
    assert usb not in engine.mixer.channel("game").devices


def test_add_menu_lists_devices_and_apps_and_disables_what_is_already_there(ui):
    win, system, _ = ui
    music = strip_for(win, "music")
    music._build_add_menu()
    top = {a.text(): a for a in music.add_menu.actions() if a.menu()}
    assert set(top) == {"Microphone or input device"}  # apps and games are one searchable dialog, not a submenu
    assert [a.text() for a in music.add_menu.actions() if not a.menu() and a.text()] == ["App or game\u2026"]
    devices = {a.text(): a for a in top["Microphone or input device"].menu().actions()}
    assert devices["Blue Yeti Microphone"].isEnabled()


def test_moving_an_app_between_channels_through_the_ui(ui):
    win, system, engine = ui
    strip_for(win, "chat")._add_app("firefox")
    assert sinks(system)["firefox"] == "sluice_ch_chat"
    strip_for(win, "game")._add_app("firefox")
    assert sinks(system)["firefox"] == "sluice_ch_game"
    assert engine.mixer.channel("chat").apps == ["discord"]
    strip_for(win, "game")._remove_app("firefox")
    assert sinks(system)["firefox"] == system.default_snk


def test_apps_bar_assigns_apps(ui):
    win, system, _ = ui
    bar = win.apps_bar
    labels = [b.text() for b in bar.findChildren(QPushButton)]
    assert any("Spotify" in t and "Music" in t for t in labels)
    bar._assign("firefox", "chat")
    assert sinks(system)["firefox"] == "sluice_ch_chat"
    bar._assign("firefox", None)
    assert sinks(system)["firefox"] == system.default_snk


def test_add_and_delete_channels(ui):
    win, system, engine = ui
    engine.add_channel("Karaoke")
    win.rebuild_channels()
    assert len(win.strips) == 7
    assert "sluice_ch_karaoke" in system.null_sinks
    win.remove_channel("music")
    assert [s.channel.id for s in win.strips] == ["mic", "browser", "game", "chat", "system", "karaoke"]
    assert sinks(system)["spotify"] == system.default_snk


def test_rename_through_the_strip(ui, monkeypatch):
    win, system, _ = ui
    from sluice import ui as ui_module

    monkeypatch.setattr(ui_module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Voice", True)))
    chat = strip_for(win, "chat")
    chat.rename()
    assert chat.title.text() == "Voice"
    assert system.null_sinks["sluice_ch_chat"][0] == "Sluice (Voice) output"


def test_meters_update_without_error(ui):
    win, _, _ = ui
    for _ in range(5):
        win._update_meters()
    assert win.strips[0].meters[STREAM]._level >= 0.0


def test_tick_refreshes_the_apps_bar(ui):
    win, system, _ = ui
    system.streams.append(type(system.streams[0])(77, "obs", "OBS Studio", system.sinks[0].name))
    win.engine._last_rules = 0.0
    win._tick_engine()
    assert any("OBS Studio" in b.text() for b in win.apps_bar.findChildren(QPushButton))


def test_shutdown_saves_and_cleans_up(ui, tmp_path):
    win, system, engine = ui
    engine.set_level("game", MONITOR, -9.0)
    win.shutdown()
    win.shutdown()  # idempotent
    assert system.cleaned_up
    assert Mixer.load(tmp_path / "config.json").channel("game").levels[MONITOR] == pytest.approx(-9.0)


# --------------------------------------------------------------------- effects dialog
def test_effects_dialog_adds_edits_bypasses_orders_and_removes(ui):
    win, _, engine = ui
    chat = engine.mixer.channel("chat")
    dialog = EffectsDialog(engine, chat, win)
    assert dialog.list.count() == 0
    dialog._add_builtin("compressor", "Compressor")
    dialog._add_builtin("eq", "3-Band EQ")
    assert [e.name for e in chat.effects] == ["3-Band EQ", "Compressor"]  # kept in the best order whatever the click order

    dialog.list.setCurrentRow(1)
    rows = dialog.params_area.widget().findChildren(ParamRow)
    assert [r.info.key for r in rows][:2] == ["threshold_db", "ratio"]
    rows[0].slider.setValue(0)  # threshold to its minimum
    assert chat.effects[1].params["threshold_db"] == -60

    item = dialog.list.item(0)
    item.setCheckState(Qt.CheckState.Unchecked)
    assert chat.effects[0].bypass is True

    dialog.list.setCurrentRow(1)
    assert not dialog.up.isEnabled() and not dialog.down.isEnabled()  # built-in effects cannot be moved
    dialog._move(-1)
    assert [e.name for e in chat.effects] == ["3-Band EQ", "Compressor"]
    dialog._remove()
    assert [e.name for e in chat.effects] == ["3-Band EQ"]
    dialog.close()


def test_effects_button_counts_active_effects(ui):
    win, _, engine = ui
    mic = strip_for(win, "mic")
    assert mic.fx_button.text() == "Effects (7/7 on)"
    engine.set_effect_bypass("mic", engine.mixer.channel("mic").effects[0].id, True)
    mic._update_fx_button()
    assert mic.fx_button.text() == "Effects (6/7 on)"


def test_a_vst3_that_cannot_load_is_reported_and_not_added(ui, monkeypatch, tmp_path):
    win, _, engine = ui
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    dialog = EffectsDialog(engine, engine.mixer.channel("chat"), win)
    dialog._add_vst3(str(tmp_path / "Missing.vst3"))
    assert engine.mixer.channel("chat").effects == []
    assert warnings and "not found" in warnings[0]
    dialog._add_vst3(str(tmp_path / "not_a_plugin.txt"))
    assert "ends in .vst3" in warnings[1]
    dialog.close()


def test_helpers():
    assert format_db(0.0) == "0.0 dB"
    assert format_db(-6.04) == "-6.0 dB"
    assert format_db(3.0) == "+3.0 dB"
    assert format_db(-60.0) == "-inf dB"
    assert level_fraction(1.0) == pytest.approx(1.0)
    assert level_fraction(0.0) == 0.0
    assert 0.0 < level_fraction(0.1) < 1.0
    assert format_value(-18.0, "dB", False) == "-18.0 dB"
    assert format_value(3.0, ":1", False) == "3.0:1"
    assert format_value(1000.0, "Hz", False) == "1000 Hz"
    assert format_value(0.5, "", True) == "50%"


def test_help_menu_saves_a_bug_report(ui, tmp_path, monkeypatch):
    win, _, _ = ui
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    help_menu = next(a.menu() for a in win.menuBar().actions() if a.menu() and a.text().replace("&", "") == "Help")
    from sluice import __version__

    assert [a.text().replace("&", "") for a in help_menu.actions() if a.text()] == [
        "Keyboard shortcuts", "What's new in this version\u2026", "Check for updates\u2026",
        "Go back to the previous version\u2026", "Save bug report\u2026", "Open log folder", "Report a problem\u2026",
        "Join the Discord\u2026", "Project page on GitHub\u2026", f"About Sluice {__version__}"]
    target = tmp_path / "report.txt"
    win.save_report_to(target)
    assert target.read_text().startswith("sluice bug report")
    assert "Bug report saved" in win.status_label.text()


def test_controls_window_learns_a_midi_control(ui, tmp_path):
    from sluice.midi import MidiEvent
    from sluice.ui_controls import Controls, ControllersDialog

    win, system, engine = ui
    controls = Controls(engine, win, tmp_path / "controls.json", demo=True)
    try:
        controls.hub.device_paths  # property exists
        controls.hub._ports["fake"] = object()  # pretend a device is plugged in so Learn is allowed
        dialog = ControllersDialog(controls, win)
        dialog.channel.setCurrentIndex(dialog.channel.findData("music"))
        dialog.mix.setCurrentIndex(dialog.mix.findData("listen"))
        dialog._learn()
        assert controls.hub.learning is not None
        controls.hub.dispatch(MidiEvent("cc", 1, 21, 64))
        assert [b.source for b in controls.hub.bindings] == ["cc:1:21"]
        assert controls.hub.bindings[0].channel == "music" and controls.hub.bindings[0].mix == "listen"
        assert (tmp_path / "controls.json").exists()
        # the bound fader now moves the mixer and the strip follows
        controls.hub.dispatch(MidiEvent("cc", 1, 21, 127))
        assert engine.mixer.channel("music").levels["monitor"] == 0.0
        assert strip_for(win, "music").faders["monitor"].gain() == 0
        dialog._remove() if dialog.list.setCurrentRow(0) is None else None
        assert controls.hub.bindings == []
        dialog.close()
    finally:
        controls.hub._ports.pop("fake", None)
        controls.close()


def test_add_menu_offers_output_monitors_but_not_the_one_a_mix_plays_into(ui):
    from sluice.backend import Device

    win, system, engine = ui
    system.sources.append(Device("alsa_output.usb-Headset.analog-stereo.monitor", "Monitor of Headset", monitor=True))
    system.sources.append(Device("alsa_output.hdmi.monitor", "Monitor of HDMI", monitor=True))
    engine.refresh_devices()
    music = strip_for(win, "music")
    music._build_add_menu()
    top = {a.text(): a for a in music.add_menu.actions() if a.menu()}
    heard = {a.text(): a for a in top["Sound playing on an output device"].menu().actions()}
    assert heard["Monitor of HDMI"].isEnabled()
    looping = next(t for t in heard if t.startswith("Monitor of Headset"))
    assert "would loop" in looping and not heard[looping].isEnabled()  # Listen plays into the headset
    inputs = [a.text() for a in top["Microphone or input device"].menu().actions()]
    assert not any("Monitor of" in t for t in inputs)  # real inputs and monitors are kept apart


def test_one_picker_for_playing_installed_and_typed_apps(ui, monkeypatch):
    from sluice.apps import AppEntry, Catalog
    from sluice.ui import Chip
    from sluice.ui_apps import AppPickerDialog

    win, system, engine = ui
    engine.catalog = Catalog([
        AppEntry("Half-Life 2", "steam:220", "game", frozenset({"steam:220", "half-life 2"})),
        AppEntry("Krita", "krita", "app", frozenset({"krita"})),
        AppEntry("Spotify", "spotify", "app", frozenset({"spotify"})),
    ])
    owner = lambda key: "Music" if key == "spotify" else None  # noqa: E731
    dialog = AppPickerDialog(engine.catalog, "Game", owner, running=[("Firefox", "firefox"), ("Spotify", "spotify")])
    texts = lambda: [dialog.list.item(i).text() for i in range(dialog.list.count())]  # noqa: E731
    assert texts()[:2] == ["Firefox   (playing now)", "Spotify   (playing now)   now in Music"]  # playing apps first, no duplicates
    assert len(texts()) == 4 and not any("by name" in t for t in texts())

    dialog.games_only.setChecked(True)
    assert texts() == ["Half-Life 2   (game)"]
    dialog.games_only.setChecked(False)
    dialog.search.setText("kri")
    assert texts() == ["Krita", "Add \u201ckri\u201d by name"]  # a typed name can always be added
    dialog.search.setText("Obscure Game.exe")
    assert texts() == ["Add \u201cObscure Game.exe\u201d by name"]
    dialog.list.item(0).setSelected(True)
    assert dialog.selected_keys() == ["obscure game.exe"]
    dialog.search.setText("krita")  # an exact match needs no "by name" row
    assert texts() == ["Krita"]

    monkeypatch.setattr(AppPickerDialog, "exec", lambda self: True)
    monkeypatch.setattr(AppPickerDialog, "selected_keys", lambda self: ["steam:220", "my own thing"])
    strip_for(win, "game")._add_installed()
    assert engine.mixer.channel("game").apps[-2:] == ["steam:220", "my own thing"]
    chips = [c.label.text() for c in strip_for(win, "game").findChildren(Chip)]
    assert any("Half-Life 2" in t for t in chips) and any("my own thing" in t for t in chips)


def test_removing_an_app_says_what_happens_to_its_sound(ui):
    win, system, engine = ui
    strip_for(win, "music")._remove_app("spotify")
    assert "plays straight to your normal output" in win.status_label.text()
    assert sinks(system)["spotify"] == system.default_snk


def test_hear_broadcast_swaps_what_the_listen_output_plays(ui):
    win, system, engine = ui
    listen = next(s for s in win.mix_strips if s.hear is not None)
    assert not listen.hear.isChecked() and not engine.hear_broadcast

    def listen_sources():
        return {out for out, inp in engine.desired_links()[0] if inp.startswith("alsa_output.usb-Headset")}

    assert any("out_monitor" in o for o in listen_sources()) and not any("out_stream" in o for o in listen_sources())
    listen.hear.click()
    assert engine.hear_broadcast and "Broadcast mix" in win.status_label.text()
    assert any("out_stream" in o for o in listen_sources()) and not any("out_monitor" in o for o in listen_sources())
    # the audience's own feed is untouched
    assert any(out.startswith("sluice:out_stream") and inp.startswith("sluice_stream") for out, inp in engine.desired_links()[0])
    listen.hear.click()
    assert not engine.hear_broadcast and any("out_monitor" in o for o in listen_sources())


def test_version_is_shown_and_about_and_update_menu_exist(ui):
    from sluice import __version__

    win, *_ = ui
    assert __version__ in win.windowTitle()
    assert any(label.text() == f"v{__version__}" for label in win.statusBar().findChildren(QLabel))
    help_menu = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Help")
    help_actions = [a.text() for a in help_menu.actions()]
    assert "Check for updates\u2026" in help_actions and f"About Sluice {__version__}" in help_actions


def test_check_for_updates_reports_each_outcome(ui, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from sluice.updates import UpdateResult

    win, *_ = ui
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    for result, expect in [
        (UpdateResult("not_configured", "0.3.2"), "no download address"),
        (UpdateResult("up_to_date", "0.3.2"), "latest version"),
        (UpdateResult("error", "0.3.2", message="offline"), "offline"),
    ]:
        win._show_update_result(result)
        assert expect in shown[-1]
    win._update_check = lambda current: UpdateResult("up_to_date", current)
    win.check_for_updates()
    assert "Checking" in win.status_label.text()
    for _ in range(100):  # the answer comes back from a worker thread
        QTest.qWait(20)
        if "latest version" in win.status_label.text():
            break
    assert "is the latest version" in win.status_label.text()


def test_wheel_scrolls_the_channels_sideways_smoothly(app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QWidget

    from sluice.ui import SmoothScrollArea

    area = SmoothScrollArea()
    area.setWidgetResizable(False)
    inner = QWidget()
    inner.resize(3000, 100)
    area.setWidget(inner)
    area.resize(400, 140)
    area.show()
    bar = area.horizontalScrollBar()
    assert bar.maximum() > 0

    def wheel(angle_y, pixel_y=0):
        return QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, pixel_y), QPoint(0, angle_y),
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)

    area.wheelEvent(wheel(-120))  # one notch down scrolls right
    assert area._animation.endValue() == SmoothScrollArea.STEP
    area._animation.setCurrentTime(area._animation.duration())
    assert bar.value() == SmoothScrollArea.STEP
    area.wheelEvent(wheel(120))   # and back
    area._animation.setCurrentTime(area._animation.duration())
    assert bar.value() == 0
    area.wheelEvent(wheel(120))   # cannot go past the start
    area._animation.setCurrentTime(area._animation.duration())
    assert bar.value() == 0
    area.wheelEvent(wheel(0, pixel_y=-30))  # touchpad: follows the finger directly
    assert bar.value() == 30
    area.close()


def test_multichannel_outputs_are_labelled_and_listed_after_stereo_ones(ui):
    from sluice.backend import Device
    from sluice.ui import DeviceCombo

    combo = DeviceCombo()
    combo.populate([Device("big", "Interface", channels=17), Device("a", "Headphones"), Device("b", "Speakers")], "")
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels == ["Default", "None", "Headphones", "Speakers", "Interface  [17 channels]"]
    assert "first two channels" in combo.itemData(4, Qt.ItemDataRole.ToolTipRole)
    assert "first two channels" not in combo.itemData(2, Qt.ItemDataRole.ToolTipRole)


def _menu(win, name):
    return next(a.menu() for a in win.menuBar().actions() if a.menu() and a.text().replace("&", "") == name)


def _texts(menu):
    return [a.text().replace("&", "") for a in menu.actions() if a.text()]


def test_menu_bar_has_the_usual_menus_in_the_usual_order(ui):
    win, _, engine = ui
    class FakeControls:
        shown = 0

        def show_dialog(self):
            FakeControls.shown += 1

        def close(self):
            pass

    win.attach_controls(FakeControls())
    names = [a.text().replace("&", "") for a in win.menuBar().actions()]
    assert names == ["File", "Mixer", "Settings", "View", "Help"]
    assert _texts(_menu(win, "File")) == ["Save settings", "Export settings…", "Import settings…",
                                          "Restore earlier settings", "Open settings folder", "Quit"]
    assert _texts(_menu(win, "Mixer"))[:4] == ["Add channel…", "Refresh devices and apps", "Recording devices for OBS…",
                                               "Third mix: Recording…"]
    assert "Hear Broadcast" in _texts(_menu(win, "Mixer")) and "Mute my microphone" in _texts(_menu(win, "Mixer"))
    assert _texts(_menu(win, "Settings")) == [
        "Theme", "Audio buffer", "Start when I log in", "When I close the window", "Add Sluice to the applications menu",
        "Update automatically when a new version is found", "MIDI controllers and Stream Deck…",
        "Reset all settings to the defaults…"]
    assert _texts(_menu(win, "View")) == ["Full screen", "Reset window size"]


def test_mixer_menu_toggles_follow_the_real_state(ui):
    win, _, engine = ui
    menu = _menu(win, "Mixer")
    hear = next(a for a in menu.actions() if a.text().replace("&", "") == "Hear Broadcast")
    mute_listen = next(a for a in menu.actions() if a.text().replace("&", "") == "Mute Listen")
    win._refresh_mixer_menu()
    assert not hear.isChecked() and not mute_listen.isChecked()

    hear.trigger()
    assert engine.hear_broadcast and next(s for s in win.mix_strips if s.hear).hear.isChecked()
    win._refresh_mixer_menu()
    assert hear.isChecked()
    win.mix_strips[0].hear.setChecked(False)  # turned off with the button: the menu tick is now stale...
    hear.trigger()  # ...and the menu still does the right thing (turns it on again, never inverts)
    assert engine.hear_broadcast
    hear.trigger()
    assert not engine.hear_broadcast

    mute_listen.trigger()
    assert engine.mixer.mix("monitor").mute and next(s for s in win.mix_strips if s.mix.id == "monitor").mute.isChecked()
    mute_listen.trigger()
    assert not engine.mixer.mix("monitor").mute


def test_add_channel_refresh_and_fullscreen_actions(ui, monkeypatch):
    win, system, engine = ui
    from PySide6.QtWidgets import QInputDialog

    before = len(engine.mixer.channels)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Extra", True)))
    next(a for a in _menu(win, "Mixer").actions() if a.text().startswith("&Add channel")).trigger()
    assert len(engine.mixer.channels) == before + 1 and len(win.strips) == before + 1
    next(a for a in _menu(win, "Mixer").actions() if a.text().startswith("&Refresh")).trigger()
    assert "refreshed" in win.status_label.text()
    win.toggle_fullscreen()
    win.toggle_fullscreen()
    assert not win.isFullScreen()


def test_save_export_and_import_settings(ui, tmp_path):
    win, _, engine = ui
    import json

    config = tmp_path / "config.json"
    win.save_settings()
    assert config.exists() and "saved" in win.status_label.text()

    engine.set_level("music", "monitor", -12.0)
    exported = tmp_path / "out" / "mine.json"
    exported.parent.mkdir()
    win.export_settings_to(exported)
    assert json.loads(exported.read_text())["channels"]

    with pytest.raises(ValueError):
        win.import_settings_from(tmp_path / "missing.json")
    junk = tmp_path / "junk.json"
    junk.write_text('{"hello": 1}')
    with pytest.raises(ValueError):
        win.import_settings_from(junk)
    assert json.loads(config.read_text()) != {"hello": 1}  # a bad file never replaces the real settings

    win.import_settings_from(exported)
    assert (tmp_path / "config.before-import.json").exists()  # the previous settings are kept
    engine.set_level("music", "monitor", 0.0)  # more changes before quitting
    win.shutdown()  # quitting after an import must not overwrite the imported file
    assert Mixer.load(config).channel("music").levels["monitor"] == -12.0


def test_fader_taper_is_smooth_monotonic_and_puts_zero_db_near_the_top():
    from sluice.model import MAX_DB, MIN_DB
    from sluice.ui import db_to_fader_position, fader_position_to_db

    assert fader_position_to_db(0.0) == MIN_DB and fader_position_to_db(1.0) == MAX_DB
    assert fader_position_to_db(0.75) == pytest.approx(0.0)
    steps = [fader_position_to_db(i / 1000) for i in range(1001)]
    assert all(a < b for a, b in zip(steps, steps[1:]))
    for db in (-60, -45.5, -30, -12.3, 0, 3.5, 12):
        assert fader_position_to_db(db_to_fader_position(db)) == pytest.approx(db, abs=1e-6)
    # the working range gets most of the travel: -30 dB to +12 dB spans 75% of the fader
    assert db_to_fader_position(12) - db_to_fader_position(-30) == pytest.approx(0.75)
    # and no part of the fader is a cliff: 1% of travel is never more than 5.2 dB
    assert max(b - a for a, b in zip(steps[::10], steps[10::10])) < 5.2


def test_fader_value_roundtrip_and_wheel(ui):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from sluice.ui import Fader

    fader = Fader()
    assert fader.gain() == 0
    seen = []
    fader.gainChanged.connect(seen.append)
    for tenths in (-600, -300, -123, 0, 45, 120):
        fader.setGain(tenths)
        assert abs(fader.gain() - tenths) <= 1  # the fader has 1000 steps: tenths of a dB survive the round trip
    fader.setGain(0)
    seen.clear()
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    fader.wheelEvent(event)
    assert fader.gain() == pytest.approx(10, abs=1)  # one notch is about 1 dB
    fader.mouseDoubleClickEvent(type("E", (), {"accept": lambda self: None})())
    assert fader.gain() == 0


def test_meter_falls_slowly_and_holds_its_peak():
    from sluice.ui import LevelMeter

    meter = LevelMeter()
    meter.push(1.0)
    assert meter._level == 1.0
    for _ in range(30):  # one second at 30 frames a second
        meter.push(0.0)
    assert 0.6 < meter._level < 0.75  # about 20 dB down after a second, not nearly empty
    assert meter._peak == 1.0  # the peak line is still held
    for _ in range(60):
        meter.push(0.0)
    assert meter._peak < 1.0


def test_channel_menu_and_dialog_turn_on_an_own_recording_device(ui):
    win, system, engine = ui
    from sluice.ui import OwnDevicesDialog

    music = strip_for(win, "music")
    music.toggle_separate()
    assert engine.mixer.channel("music").separate and "sluice_solo_music" in system.null_sinks
    assert "Sluice (Music)" in win.status_label.text() and "only Music" in win.status_label.text()
    assert "Sluice (Music)" in music.title.toolTip()
    music.toggle_separate()
    assert not engine.mixer.channel("music").separate and "sluice_solo_music" not in system.null_sinks

    dialog = OwnDevicesDialog(engine, win)
    assert set(dialog.boxes) == {c.id for c in engine.mixer.channels}
    dialog.boxes["game"].setChecked(True)
    assert engine.mixer.channel("game").separate and "sluice_solo_game" in system.null_sinks
    assert "Sluice (Game)" in strip_for(win, "game").title.toolTip()  # the rebuilt strip knows
    dialog.boxes["game"].setChecked(False)
    assert not engine.mixer.channel("game").separate
    dialog.close()
    assert "Recording devices for OBS" in " ".join(_texts(_menu(win, "Mixer")))


def test_file_menu_adds_and_removes_the_applications_menu_entry(ui, tmp_path, monkeypatch):
    from sluice import desktop

    win, _, _ = ui
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)
    action = next(a for a in _menu(win, "Settings").actions() if "applications menu" in a.text())
    win._refresh_file_menu()
    assert not action.isChecked()
    action.trigger()
    assert desktop.is_installed() and "applications menu" in win.status_label.text()
    win._refresh_file_menu()
    assert action.isChecked()
    action.trigger()
    assert not desktop.is_installed()


def test_effect_values_can_be_typed_and_double_click_resets_to_the_default(ui):
    win, _, engine = ui
    mic = engine.mixer.channel("mic")
    dialog = EffectsDialog(engine, mic, win)
    dialog.list.setCurrentRow(5)  # Compressor
    rows = {r.info.key: r for r in dialog.params_area.widget().findChildren(ParamRow)}
    threshold = rows["threshold_db"]
    compressor = mic.effects[5]

    threshold.readout.setText("-27.5 dB")
    threshold.readout.entered.emit(parse_number(threshold.readout.text()))
    assert compressor.params["threshold_db"] == -27.5  # exactly what was typed, not a slider step
    assert threshold.readout.text() == "-27.5 dB"

    threshold.readout.entered.emit(parse_number("999"))  # out of range: clamped to the top of the range
    assert compressor.params["threshold_db"] == 0
    threshold.readout.setText("abc")
    threshold.readout.entered.emit(parse_number("abc"))  # not a number: snaps back, nothing changes
    assert compressor.params["threshold_db"] == 0 and threshold.readout.text() == "0.0 dB"

    threshold.slider.reset_requested.emit()  # double-click
    assert compressor.params["threshold_db"] == -18
    rows["ratio"].readout.entered.emit(parse_number("4:1"))
    assert compressor.params["ratio"] == 4
    rows["ratio"].slider.reset_requested.emit()
    assert compressor.params["ratio"] == 3 and rows["makeup_db"].info.default == 2
    dialog.close()


def test_number_parsing():
    assert parse_number("-18 dB") == -18 and parse_number("3.5:1") == 3.5 and parse_number("1,5") == 1.5
    assert parse_number("50%") == 50 and parse_number("  +4") == 4 and parse_number("") is None
    assert parse_number("-inf dB") == float("-inf") and parse_number("off") == float("-inf")
    assert parse_number("loud") is None


def test_fader_readouts_can_be_typed_into(ui):
    win, _, engine = ui
    music = strip_for(win, "music")
    music.readouts["monitor"].entered.emit(-12.5)
    assert engine.mixer.channel("music").levels["monitor"] == -12.5
    assert music.readouts["monitor"].text() == "-12.5 dB"
    music.readouts["monitor"].entered.emit(None)  # nonsense: the real value comes back
    assert music.readouts["monitor"].text() == "-12.5 dB"
    music.readouts["monitor"].entered.emit(500.0)  # clamped to +12
    assert engine.mixer.channel("music").levels["monitor"] == 12.0
    music.readouts["monitor"].entered.emit(float("-inf"))
    assert engine.mixer.channel("music").levels["monitor"] == -60.0 and music.readouts["monitor"].text() == "-inf dB"
    win.mix_strips[1].readout.entered.emit(-6.0)
    assert engine.mixer.mix(STREAM).gain_db == -6.0 and win.mix_strips[1].readout.text() == "-6.0 dB"


def test_meters_stop_while_the_window_is_hidden(ui):
    win, _, _ = ui
    win.show()
    assert win.meter_timer.isActive()
    win.hide()
    assert not win.meter_timer.isActive()
    win.show()
    assert win.meter_timer.isActive()
    win.hide()
    win.shutdown()
    win.show()  # after shutdown nothing starts again
    assert not win.meter_timer.isActive()


def test_a_settled_meter_does_not_repaint():
    from sluice.ui import LevelMeter

    meter = LevelMeter()
    meter.resize(12, 140)
    updates = []
    meter.update = lambda *a: updates.append(1)
    meter.push(0.0)
    meter._painted = meter._shown()  # as if it had just been drawn
    updates.clear()
    for _ in range(20):
        meter.push(0.0)
    assert updates == []  # silence, nothing moving: no repaint at all
    meter.push(0.5)
    assert updates  # a level change repaints
    meter._painted = meter._shown()
    updates.clear()
    meter.push(0.5)
    assert updates == [] or meter._shown() != meter._painted


def test_view_menu_picks_the_audio_buffer(ui):
    win, _, engine = ui
    menu = next(a.menu() for a in _menu(win, "Settings").actions() if a.menu() and "buffer" in a.text())
    win._refresh_buffer_menu()
    assert [a.isChecked() for a in menu.actions()] == [False, True, False, False]  # 512 is the default
    next(a for a in menu.actions() if "1024" in a.text()).trigger()
    assert engine.mixer.buffer_frames == 1024 and "next time" in win.status_label.text()
    win._refresh_buffer_menu()
    assert [a.isChecked() for a in menu.actions()] == [False, False, True, False]


def test_enter_in_a_value_box_does_not_open_the_add_menu(ui):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win, _, engine = ui
    dialog = EffectsDialog(engine, engine.mixer.channel("mic"), win)
    dialog.show()
    dialog.list.setCurrentRow(3)
    rows = dialog.params_area.widget().findChildren(ParamRow)
    rows[0].readout.setFocus()
    QTest.keyClick(rows[0].readout, Qt.Key.Key_Return)
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert not dialog.add_button.menu().isVisible()
    assert not any(b.autoDefault() for b in dialog.findChildren(type(dialog.add_button)))
    dialog.close()


def test_start_when_i_log_in_menu(ui, monkeypatch, tmp_path):
    from sluice import desktop

    win, _, _ = ui
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    win._refresh_file_menu()
    assert win.autostart_actions["off"].isChecked()
    win.autostart_actions["minimized"].trigger()
    assert desktop.autostart_state() == "minimized"
    win._refresh_file_menu()
    assert win.autostart_actions["minimized"].isChecked() and not win.autostart_actions["off"].isChecked()
    win.autostart_actions["off"].trigger()
    assert desktop.autostart_state() == "off"


def test_a_second_start_brings_the_window_forward(ui):
    win, _, engine = ui
    from sluice.control import ControlApi

    seen = []
    api = ControlApi(engine, on_change=seen.append)
    assert api.handle({"cmd": "show"}) == {"ok": True}
    assert seen == ["show"]
    win.showMinimized()
    win.bring_to_front()
    assert not win.isMinimized()


def test_settings_save_themselves_when_something_changes(ui, tmp_path):
    win, _, engine = ui
    config = tmp_path / "config.json"
    assert not config.exists()
    win._autosave()  # a brand-new install gets its settings file straight away
    assert config.is_file()
    first = config.read_text()
    win._autosave()
    assert config.read_text() == first  # nothing changed: nothing written
    config.write_text("marker")
    win._autosave()
    assert config.read_text() == "marker"  # still unchanged, so the file is left alone
    engine.mixer.set_level("music", MONITOR, -9.0)
    win._autosave()
    assert '"monitor": -9.0' in config.read_text()  # a change is saved without anyone pressing Save


def test_autosave_never_overwrites_freshly_imported_settings(ui, tmp_path):
    win, _, engine = ui
    win._autosave()
    config = tmp_path / "config.json"
    config.write_text("imported")
    win._keep_settings_file = True  # what "Import settings" sets
    engine.mixer.set_level("music", MONITOR, -3.0)
    win._autosave()
    assert config.read_text() == "imported"


def test_restore_earlier_settings_menu_lists_and_restores_a_backup(ui, tmp_path):
    from sluice.model import make_backup

    win, _, engine = ui
    config = tmp_path / "config.json"
    win._fill_restore_menu()
    assert [a.text() for a in win.restore_menu.actions()] == ["No earlier versions yet"]
    engine.mixer.save(config)  # the current file: the standard layout
    old_text = config.read_text()
    engine.mixer.set_level("music", MONITOR, -9.0)
    made = make_backup(config, "something else", now=1e9)
    assert made is not None
    win._fill_restore_menu()
    assert len(win.restore_menu.actions()) == 1 and "channels" in win.restore_menu.actions()[0].text()
    engine.mixer.set_level("music", MONITOR, -2.0)
    win.restore_backup(made, confirm=False)
    assert config.read_text() == old_text
    assert (tmp_path / "config.before-import.json").is_file() and win._keep_settings_file


def test_closing_the_window_quits_or_minimizes_as_chosen(ui):
    win, _, engine = ui
    win.show()
    assert engine.mixer.close_action == "quit"
    win.close_actions["minimize"].trigger()
    assert engine.mixer.close_action == "minimize"
    win._refresh_file_menu()
    assert win.close_actions["minimize"].isChecked() and not win.close_actions["quit"].isChecked()
    win.close()  # the window's X button
    assert not win._closed  # still running (offscreen Qt cannot really minimize, so the window state is not checked)
    assert "still running" in win.status_label.text()
    win.quit_app()  # File > Quit always quits
    assert win._closed


def test_closing_quits_by_default(ui):
    win, _, _ = ui
    win.show()
    win.close()
    assert win._closed


# ------------------------------------------------------------- 0.9.0 additions
def _mic_button(win):
    return next(s for s in win.strips if s.channel.id == "mic").mic_button


def test_the_mic_strip_button_and_menu_item_mute_the_microphone(ui):
    win, _, engine = ui
    button = _mic_button(win)
    assert button.text() == "Mic live" and not engine.mic_muted
    button.click()
    assert engine.mic_muted and button.text() == "MIC MUTED" and button.isChecked()
    win.mic_action.trigger()
    assert not engine.mic_muted and button.text() == "Mic live"
    engine.set_mic_muted(True)  # something else (a controller, `sluice ctl mic-mute`) changed it
    win.sync_from_model()
    assert button.text() == "MIC MUTED"


def test_the_mixer_menu_offers_the_recording_mix_and_the_mic_mute(ui):
    win, _, engine = ui
    menu = next(a.menu() for a in win.menuBar().actions() if a.menu() and a.text().replace("&", "") == "Mixer")
    texts = [a.text().replace("&", "") for a in menu.actions() if a.text()]
    assert "Mute my microphone" in texts and any(t.startswith("Third mix: Recording") for t in texts)
    assert not win.recording_action.isChecked()


def test_effects_window_explains_the_reducers_and_can_compare_them(ui):
    from PySide6.QtWidgets import QLabel, QPushButton

    from sluice.ui_effects import EffectsDialog

    win, _, engine = ui
    mic = engine.mixer.channel("mic")
    dialog = EffectsDialog(engine, mic, win)
    names = [e.type for e in mic.effects]
    dialog.list.setCurrentRow(names.index("echo_reducer"))
    labels = " ".join(label.text() for label in dialog.params_area.widget().findChildren(QLabel))
    assert "16 ms" in labels and "Room echo time" in labels
    buttons = {b.text(): b for b in dialog.params_area.widget().findChildren(QPushButton)}
    assert "Measure my room's echo…" in buttons
    assert not dialog.new_hint.isVisibleTo(dialog)  # this channel already has them
    buttons["Compare: switch both reducers off / on"].click()
    assert all(e.bypass for e in mic.effects if e.type in ("echo_reducer", "noise_reducer"))
    dialog.list.setCurrentRow(names.index("echo_reducer"))
    next(b for b in dialog.params_area.widget().findChildren(QPushButton) if b.text().startswith("Compare")).click()
    assert not any(e.bypass for e in mic.effects if e.type in ("echo_reducer", "noise_reducer"))
    dialog._update_activity()
    dialog.close()


def test_a_channel_without_a_microphone_is_warned_about_the_reducers(ui):
    from PySide6.QtWidgets import QLabel

    from sluice.model import Effect, new_effect_id
    from sluice.ui_effects import EffectsDialog

    win, _, engine = ui
    music = engine.mixer.channel("music")
    engine.add_effect("music", Effect(new_effect_id(), "builtin", "Noise Reducer", type="noise_reducer"))
    dialog = EffectsDialog(engine, music, win)
    dialog.list.setCurrentRow(0)
    assert "no microphone" in " ".join(label.text() for label in dialog.params_area.widget().findChildren(QLabel))
    dialog.close()


def test_an_older_voice_chain_is_told_about_the_new_effects(ui):
    from sluice.ui_effects import EffectsDialog

    win, _, engine = ui
    mic = engine.mixer.channel("mic")
    for effect in [e for e in mic.effects if e.type in ("echo_reducer", "noise_reducer")]:
        engine.remove_effect("mic", effect.id)
    dialog = EffectsDialog(engine, mic, win)
    assert dialog.new_hint.isVisibleTo(dialog)
    dialog.close()


def test_presets_apply_from_the_effects_window_and_can_be_saved(ui, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QInputDialog

    from sluice import presets
    from sluice.ui_effects import EffectsDialog

    win, _, engine = ui
    mic = engine.mixer.channel("mic")
    dialog = EffectsDialog(engine, mic, win)
    dialog._build_presets_menu()
    menu = dialog.presets_button.menu()
    assert "Light touch" in [a.text() for a in menu.actions()]
    next(a for a in menu.actions() if a.text() == "Light touch").trigger()
    assert next(e for e in mic.effects if e.type == "noise_reducer").params["reduction_db"] == 6
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("My room", True)))
    dialog._save_preset()
    assert "My room" in presets.load_user(tmp_path / "presets.json")
    dialog._build_presets_menu()
    assert "My room" in [a.text() for a in dialog.presets_button.menu().actions()]
    dialog._delete_preset("My room")
    assert presets.load_user(tmp_path / "presets.json") == {}
    dialog.close()


def test_a_lost_audio_server_starts_the_wait_to_reconnect(ui, monkeypatch):
    win, _, engine = ui
    called = []
    monkeypatch.setattr(win, "_begin_reconnect", lambda: called.append(1))
    win._tick_engine()
    assert not called
    engine.server_lost = True
    win._tick_engine()
    assert called == [1]


def test_reconnecting_restarts_only_when_the_server_answers(ui, monkeypatch):
    from sluice import reconnect

    win, _, engine = ui
    restarted = []
    monkeypatch.setattr(reconnect, "restart_self", lambda show_window=False: restarted.append(1))
    answers = iter([False, True])
    monkeypatch.setattr(reconnect, "server_is_back", lambda: next(answers))
    win._begin_reconnect()
    win._try_reconnect()
    assert not restarted
    win._try_reconnect()
    assert restarted == [1]


# ------------------------------------------------------------------ system tray
@pytest.fixture
def tray(monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))


def test_tray_mode_shows_an_icon_and_closing_hides_the_window_into_it(ui, tray):
    win, _, engine = ui
    win.show()
    assert not win.tray_active
    win.close_actions["tray"].trigger()
    assert engine.mixer.close_action == "tray" and win.tray_active
    win._refresh_file_menu()
    assert win.close_actions["tray"].isChecked()
    win.close()  # the X button
    assert not win._closed and not win.isVisible() and "system tray" in win.status_label.text()
    win.bring_to_front()  # the tray icon's click, or starting Sluice a second time
    assert win.isVisible()
    win.quit_app()
    assert win._closed and not win.tray_active


def test_the_tray_menu_shows_mutes_and_quits(ui, tray):
    win, _, engine = ui
    win.show()
    win.close_actions["tray"].trigger()
    win.hide()
    win._refresh_tray_menu()
    assert win._tray_show.text() == "Show Sluice" and not win._tray_mic.isChecked()
    win._tray_mic.trigger()
    assert engine.mic_muted and "muted" in win._tray.toolTip()
    win._refresh_tray_menu()
    assert win._tray_mic.isChecked()
    win._tray_show.trigger()
    assert win.isVisible()
    win._refresh_tray_menu()
    assert win._tray_show.text() == "Hide Sluice"
    from PySide6.QtWidgets import QSystemTrayIcon

    win.isActiveWindow = lambda: True
    win._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)  # a click while it is in front hides it
    assert not win.isVisible()
    win._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert win.isVisible()
    win._on_tray_activated(QSystemTrayIcon.ActivationReason.Context)  # a right-click is for the menu only
    assert win.isVisible()


def test_without_a_system_tray_the_window_falls_back_to_the_taskbar(ui):
    from PySide6.QtWidgets import QSystemTrayIcon

    assert not QSystemTrayIcon.isSystemTrayAvailable()  # the offscreen test platform has none
    win, _, engine = ui
    win.show()
    win.close_actions["tray"].trigger()
    assert engine.mixer.close_action == "tray" and not win.tray_active and "taskbar" in win.status_label.text()
    win.close()
    assert not win._closed  # never closed, never lost: it is minimized, and Quit still works
    win.quit_app()
    assert win._closed


def test_a_minimized_start_goes_to_the_tray_when_there_is_one(ui, tray):
    win, _, engine = ui
    engine.mixer.close_action = "tray"
    win.start_minimized()
    assert win.tray_active and not win.isVisible()
    win.quit_app()


def test_the_tray_icon_is_there_from_the_start_when_saved_that_way(app, tmp_path, tray):
    engine = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.mixer.close_action = "tray"
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    try:
        assert win.tray_active
    finally:
        win.shutdown()
    assert not win.tray_active
