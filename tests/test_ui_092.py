# SPDX-License-Identifier: GPL-3.0-or-later
"""0.9.2 in the window: three mixes, the mic mute on its strip, presets, the menus, reset, links, the voice check."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pedalboard")

from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QToolButton  # noqa: E402

from sluice import presets, room, ui as ui_module  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import MONITOR, RECORDING, STREAM, Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_effects import EffectsDialog  # noqa: E402
from sluice.ui_room import MeasureVoiceDialog  # noqa: E402

SR = 48000


def make(qapp, tmp_path, three=False, mixer=None):
    system = MockSystem()
    system.add_demo_streams()
    mixer = mixer or Mixer.demo()
    if three:
        mixer.set_recording_mix(True)
    io = NullIO(realtime=False)
    engine = Engine(mixer, system, io, NullLinker())
    engine.start()
    return MainWindow(engine, config_file=tmp_path / "config.json"), engine, io


@pytest.fixture
def two(qapp, tmp_path):
    win, engine, io = make(qapp, tmp_path)
    yield win, engine, io
    win.shutdown()


@pytest.fixture
def three(qapp, tmp_path):
    win, engine, io = make(qapp, tmp_path, three=True)
    yield win, engine, io
    win.shutdown()


def strip_for(win, channel_id):
    return next(s for s in win.strips if s.channel.id == channel_id)


def menu_of(win, name):
    return next(a.menu() for a in win.menuBar().actions() if a.menu() and a.text().replace("&", "") == name)


def texts(menu):
    return [a.text().replace("&", "") for a in menu.actions() if a.text()]


# ------------------------------------------------------------------- the third mix
def test_with_three_mixes_the_strips_are_wide_enough_for_their_labels(three):
    win, _, _ = three
    assert [m.mix.id for m in win.mix_strips] == [MONITOR, STREAM, RECORDING]
    for strip in win.strips:
        assert strip.width() == ui_module.CHANNEL_WIDTH_THREE
    mic = strip_for(win, "mic")
    names = [label.text() for label in mic.findChildren(QLabel) if label.objectName() == "tag"]
    assert names[-3:] == ["LISTEN", "BROADCAST", "RECORDING"]
    assert all(r.property("compact") is True for r in mic.readouts.values())


def test_every_column_label_fits_its_column_and_says_in_full_what_it_is_on_hover(three):
    from PySide6.QtGui import QFontMetrics

    win, _, _ = three
    win.show()
    QTest.qWait(50)
    mic = strip_for(win, "mic")
    for label in (l for l in mic.findChildren(QLabel) if l.objectName() == "tag" and l.text() in ("LISTEN", "BROADCAST", "RECORDING")):
        needed = QFontMetrics(label.font()).horizontalAdvance(label.text())  # the font carries the style sheet's size and spacing
        assert label.width() >= needed, (label.text(), label.width(), needed)
        assert label.toolTip()
    for readout in mic.readouts.values():
        assert readout.width() >= QFontMetrics(readout.font()).horizontalAdvance("-18.0 dB")
    tips = {l.text(): l.toolTip() for l in mic.findChildren(QLabel) if l.objectName() == "tag" and l.toolTip()}
    assert "audience" in tips["BROADCAST"] and "recorder" in tips["RECORDING"] and "hear" in tips["LISTEN"]
    win.hide()


def test_two_mixes_keep_the_old_width_and_get_the_add_a_mix_strip(two):
    win, _, _ = two
    assert all(s.width() == ui_module.CHANNEL_WIDTH for s in win.strips)
    assert win.add_mix_button is not None and "Recording" in win.add_mix_button.text()
    assert win.add_mix_button.width() == ui_module.ADD_MIX_WIDTH
    assert "restarts" in win.add_mix_button.toolTip()


def test_the_add_a_mix_strip_starts_the_recording_mix_change(two, monkeypatch):
    win, engine, _ = two
    asked = []

    def fake_exec(self):
        asked.append(self.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)  # "Not now"
    win.add_mix_button.click()
    assert asked and "Recording" in asked[0] and "restart" in asked[0]
    assert not engine.mixer.has_recording_mix  # nothing changes until the person agrees


def test_with_the_third_mix_there_is_no_add_strip_and_the_mix_can_be_removed_from_its_own_strip(three, monkeypatch):
    win, engine, _ = three
    assert win.add_mix_button is None
    strip = win.mix_strips[-1]
    button = next(b for b in strip.findChildren(QToolButton) if b.objectName() == "menu")
    action = next(a for a in button.menu().actions() if "Remove the Recording mix" in a.text())
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: asked.append(self.text()) or 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    action.trigger()
    assert asked and "Remove the Recording mix" in asked[0] and engine.mixer.has_recording_mix
    for other in win.mix_strips[:2]:
        assert not [b for b in other.findChildren(QToolButton) if b.objectName() == "menu"]


def test_the_faders_line_up_across_strips_with_and_without_a_microphone(three):
    win, _, _ = three
    win.show()
    QTest.qWait(100)
    heights = {s.channel.id: s.faders[MONITOR].height() for s in win.strips}
    tops = {s.channel.id: s.faders[MONITOR].mapTo(win, s.faders[MONITOR].rect().topLeft()).y() for s in win.strips}
    assert len(set(heights.values())) == 1 and len(set(tops.values())) == 1, (heights, tops)
    win.hide()


# ------------------------------------------------------------------- the mic mute on the Mic strip
def test_only_strips_with_a_microphone_show_the_mute_button_and_the_rest_keep_their_sources_list(two):
    win, engine, _ = two
    win.show()
    QTest.qWait(50)
    mic, browser = strip_for(win, "mic"), strip_for(win, "browser")
    assert mic.mic_row.isVisibleTo(win) and not browser.mic_row.isVisibleTo(win)
    assert mic.sources_scroll.height() < browser.sources_scroll.height()
    # give the Browser channel a microphone: it gets the button, and loses the same height from its list
    browser.engine.add_device("browser", "")
    browser.refresh_sources()
    assert browser.mic_row.isVisibleTo(win) and browser.sources_scroll.height() == mic.sources_scroll.height()
    browser.engine.remove_device("browser", "")
    browser.refresh_sources()
    assert not browser.mic_row.isVisibleTo(win)
    win.hide()


def test_the_status_bar_no_longer_has_a_mic_button(two):
    win, _, _ = two
    assert not hasattr(win, "mic_button")
    assert not [b for b in win.statusBar().findChildren(QPushButton) if "Mic" in b.text() or "MIC" in b.text()]


def test_muting_on_the_strip_is_shown_everywhere_the_mic_state_is(two):
    win, engine, _ = two
    button = strip_for(win, "mic").mic_button
    button.click()
    assert engine.mic_muted and button.isChecked() and button.text() == "MIC MUTED"
    win._refresh_mixer_menu()
    assert win.mic_action.isChecked()
    win.mic_action.trigger()
    assert not engine.mic_muted and button.text() == "Mic live" and not button.isChecked()
    assert "live" in win.status_label.text()


def test_a_second_microphone_channel_shows_the_same_state_on_its_strip(two):
    win, engine, _ = two
    engine.add_channel("Headset")
    engine.add_device(engine.mixer.channels[-1].id, "")
    win.rebuild_channels()
    buttons = [s.mic_button for s in win.strips if s.channel.devices]
    assert len(buttons) == 2
    win.toggle_mic_mute()
    assert all(b.text() == "MIC MUTED" for b in buttons)


def test_the_mute_button_works_in_the_three_mix_layout_too(three):
    win, engine, _ = three
    strip_for(win, "mic").mic_button.click()
    assert engine.mic_muted


# ------------------------------------------------------------------- presets in the Effects window
def open_effects(win, engine, channel="mic"):
    return EffectsDialog(engine, engine.mixer.channel(channel), win)


def choice(dialog, axis, name):
    return dialog._choice_buttons[(axis, name)]


def ticked(dialog, axis):
    return [n for (a, n), b in dialog._choice_buttons.items() if a == axis and b.isChecked()]


def test_a_new_install_shows_room_normal_and_voice_natural_ticked(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    assert ticked(dialog, "room") == ["Normal"] and ticked(dialog, "style") == ["Natural"]
    assert choice(dialog, "room", "Normal").text() == "\u2713 Normal"
    assert choice(dialog, "style", "Natural").text() == "\u2713 Natural"
    assert not dialog._axis_reset["room"].isVisibleTo(dialog)


def test_picking_a_room_changes_it_says_what_was_set_and_jumps_to_the_reducer(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    dialog.list.setCurrentRow(0)
    choice(dialog, "room", "Noisy").click()
    assert ticked(dialog, "room") == ["Noisy"] and ticked(dialog, "style") == ["Natural"]
    assert dialog.preset_feedback.isVisibleTo(dialog)
    assert dialog.preset_feedback.text() == "Room: Noisy. Echo Reducer 12 dB, 0.8 s; Noise Reducer 18 dB."
    assert dialog.preset_feedback.text() in win.status_label.text()
    assert dialog.title.text() == "Echo Reducer"
    assert dialog._rows["reduction_db"].value == 12 and dialog._rows["reverb_time"].value == pytest.approx(0.8)


def test_a_tiny_nudge_shows_changed_and_reset_puts_it_back(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    choice(dialog, "room", "Noisy").click()
    dialog._rows["reduction_db"].set_value(12.01)
    assert dialog._axis_status["room"].text() == "Noisy (changed)"
    assert dialog._axis_reset["room"].isVisibleTo(dialog)
    assert choice(dialog, "room", "Noisy").text() == "Noisy"  # no check mark any more
    dialog._axis_reset["room"].click()
    assert dialog._axis_status["room"].text() == "" and choice(dialog, "room", "Noisy").text() == "\u2713 Noisy"


def test_bypassing_a_reducer_updates_the_choices_too(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    names = [e.type for e in engine.mixer.channel("mic").effects]
    from PySide6.QtCore import Qt

    dialog.list.item(names.index("echo_reducer")).setCheckState(Qt.CheckState.Unchecked)
    assert dialog._axis_status["room"].text().endswith("(changed)")


def test_a_choice_on_a_channel_without_the_effects_adds_them(two):
    win, engine, _ = two
    dialog = open_effects(win, engine, "music")  # no effects at all
    assert dialog._axis_status["room"].text() == "not on this channel yet"
    choice(dialog, "style", "Broadcast").click()
    assert [e.type for e in engine.mixer.channel("music").effects] == ["highpass", "eq", "compressor", "limiter"]
    assert ticked(dialog, "style") == ["Broadcast"]


def test_your_own_preset_is_ticked_when_it_matches_and_keeps_the_gate_threshold(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    presets.save_user(dialog._presets_file(), {"Mine": presets.snapshot(engine.mixer.channel("mic").effects)})
    dialog._update_presets_button()
    dialog._user_presets(reload=True)
    dialog._update_presets_button()
    assert dialog.mine_button.text().startswith("\u2713 Mine")


def test_saving_is_always_possible_even_after_a_tiny_change_and_deleting_works(two, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    win, engine, _ = two
    dialog = open_effects(win, engine)
    dialog._rows or dialog.list.setCurrentRow(0)
    effect = next(e for e in engine.mixer.channel("mic").effects if e.type == "compressor")
    engine.set_effect_param(effect.id, "ratio", 2.51)
    dialog._update_presets_button()
    menu = dialog.mine_button.menu()
    menu.aboutToShow.emit()
    save = next(a for a in menu.actions() if a.text().startswith("Save as my preset"))
    assert save.isEnabled()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mine", True)))
    dialog._save_preset()
    assert dialog.mine_button.text().startswith("\u2713 Mine")
    stored = presets.load_user(dialog._presets_file())["Mine"]
    assert next(e for e in stored if e["type"] == "compressor")["params"]["ratio"] == 2.51
    dialog._delete_preset("Mine")
    assert "Mine" not in presets.load_user(dialog._presets_file())
    assert dialog.mine_button.text() == "My presets \u25be"


def test_hear_my_original_microphone_switches_the_chain_off_and_closing_restores_it(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    dialog.compare_button.click()
    assert engine.chain_compare("mic") and dialog.compare_button.text() == "Back to my effects"
    dialog.done(0)
    assert not engine.chain_compare("mic")


def test_the_quiet_microphone_prompt_appears_only_after_watching_for_a_while(two, monkeypatch):
    win, engine, io = two
    dialog = open_effects(win, engine)
    monkeypatch.setattr(engine, "channel_input_peak_db", lambda cid: -32.0)
    dialog._check_level()
    assert not dialog.level_prompt.isVisibleTo(dialog)
    dialog._speech_started -= 10.0
    dialog._check_level()
    assert dialog.level_prompt.isVisibleTo(dialog) and dialog.level_button.isVisibleTo(dialog)
    loud = open_effects(win, engine)
    monkeypatch.setattr(engine, "channel_input_peak_db", lambda cid: -17.0)
    loud._check_level()
    loud._speech_started -= 10.0
    loud._check_level()
    assert not loud.level_prompt.isVisibleTo(loud)


def test_the_measure_my_room_tip_is_shown_once_and_measuring_picks_the_room(two):
    win, engine, _ = two
    first = open_effects(win, engine)
    assert first.room_hint.isVisibleTo(first) and "measure_room" in engine.mixer.hints_seen
    second = open_effects(win, engine)
    assert not second.room_hint.isVisibleTo(second)
    second._room_measured(room.RoomResult("ok", -40.0, -42.0, ""))
    assert ticked(second, "room") == ["Noisy"]


# ------------------------------------------------------------------- the Compressor hint
def feed(io, engine, amplitude, blocks=40):
    tone = (amplitude * np.sin(2 * np.pi * 300 * np.arange(SR) / SR)).astype(np.float32)
    io.fixed_inputs = {c.id: np.stack((tone, tone)) if c.id == "mic" else np.zeros((2, 1), dtype=np.float32)
                       for c in engine.mixer.channels}
    for _ in range(blocks):
        io.process_once(512)


def compressor_page(win, engine):
    dialog = open_effects(win, engine)
    names = [e.type for e in engine.mixer.channel("mic").effects]
    dialog.list.setCurrentRow(names.index("compressor"))
    return dialog


def test_the_compressor_says_when_it_has_nothing_to_do(two):
    win, engine, io = two
    dialog = compressor_page(win, engine)
    feed(io, engine, 0.03)  # a quiet voice: about -30 dB, above the gate but below the Compressor (starts near -25 dB)
    dialog._update_activity()
    assert "Not doing anything" in dialog.activity_label.text() and "Threshold" in dialog.activity_label.text()


def test_the_compressor_says_when_it_is_working(two):
    win, engine, io = two
    dialog = compressor_page(win, engine)
    feed(io, engine, 0.7)
    dialog._update_activity()
    assert dialog.activity_label.text().startswith("Working")


def test_the_compressor_hint_waits_for_sound_and_stops_when_the_page_changes(two):
    win, engine, io = two
    dialog = compressor_page(win, engine)
    dialog._update_activity()
    assert "Waiting for sound" in dialog.activity_label.text()
    assert dialog._timer.isActive()
    dialog.list.setCurrentRow(0)  # another page: no stale label is touched any more
    assert dialog._compressor is None
    dialog._update_activity()  # must not raise on the deleted label


def test_the_hint_follows_the_threshold_slider(two):
    win, engine, io = two
    dialog = compressor_page(win, engine)
    feed(io, engine, 0.03)  # about -30 dB
    dialog._update_activity()
    assert "Not doing anything" in dialog.activity_label.text()
    dialog._rows["threshold_db"].set_value(-45.0)
    feed(io, engine, 0.03, blocks=5)
    dialog._update_activity()
    assert dialog.activity_label.text().startswith("Working")


# ------------------------------------------------------------------- the voice level check
def talk(rms_db):
    t = np.arange(int(SR * 6.5)) / SR
    tone = np.sin(2 * np.pi * 300 * t) * np.where((t % 0.7) < 0.4, 10 ** (rms_db / 20) * np.sqrt(2), 1e-5)
    return np.stack((tone, tone)).astype(np.float32)


def run_voice_dialog(win, engine, io, rms_db):
    applied = []
    dialog = MeasureVoiceDialog(engine, engine.mixer.channel("mic"), applied.append, win)
    io.streamed_inputs = {"mic": talk(rms_db)}
    dialog.primary.click()
    for _ in range(int(room.VOICE_SECONDS * SR / 512) + 2):
        io.process_once(512)
    dialog.tick()
    return dialog, applied


def test_the_voice_check_offers_to_add_the_missing_level(two):
    win, engine, io = two
    dialog, applied = run_voice_dialog(win, engine, io, -29.0)
    assert dialog.result.status == "too_quiet" and dialog.primary.isEnabled()
    assert dialog.primary.text() == "Add 9 dB" and "using the Gain effect" in dialog.text.text()
    dialog.primary.click()
    assert len(applied) == 1 and applied[0] == pytest.approx(9.0, abs=0.7)


def test_a_good_voice_level_just_says_so(two):
    win, engine, io = two
    dialog, applied = run_voice_dialog(win, engine, io, -20.0)
    assert "good level" in dialog.text.text() and applied == []
    assert dialog.primary.text() == "Try again"


def test_the_voice_check_can_be_stopped_midway(two):
    win, engine, io = two
    dialog = MeasureVoiceDialog(engine, engine.mixer.channel("mic"), lambda _: None, win)
    io.streamed_inputs = {"mic": talk(-25.0)}
    dialog.primary.click()
    assert dialog.listening
    dialog.reject()
    assert not dialog.listening and engine.measure_room_progress("mic") == 0.0


def test_applying_the_voice_gain_uses_and_creates_the_gain_effect(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    mic = engine.mixer.channel("mic")
    assert not [e for e in mic.effects if e.type == "gain"]
    dialog._apply_voice_gain(9.0)
    gain = next(e for e in mic.effects if e.type == "gain")
    assert gain.params["gain_db"] == pytest.approx(9.0) and "Gain on Mic is now +9.0 dB" in win.status_label.text()
    dialog._apply_voice_gain(-3.0)
    assert gain.params["gain_db"] == pytest.approx(6.0)
    dialog._apply_voice_gain(40.0)
    assert gain.params["gain_db"] == 24.0  # the effect's own limit
    assert len([e for e in mic.effects if e.type == "gain"]) == 1


def test_the_voice_button_is_on_the_gate_and_the_compressor_pages_of_a_microphone_channel(two):
    win, engine, _ = two
    dialog = open_effects(win, engine)
    names = [e.type for e in engine.mixer.channel("mic").effects]
    for kind in ("noise_gate", "compressor"):
        dialog.list.setCurrentRow(names.index(kind))
        labels = [b.text() for b in dialog.params_area.widget().findChildren(QPushButton)]
        assert "Check my voice level…" in labels, kind


# ------------------------------------------------------------------- the reorganised menus
def test_the_menus_hold_the_agreed_items(two):
    win, _, _ = two
    assert [a.text().replace("&", "") for a in win.menuBar().actions()] == ["File", "Mixer", "Settings", "View", "Help"]
    assert texts(menu_of(win, "Help"))[-4:] == ["Report a problem…", "Join the Discord…", "Project page on GitHub…",
                                                f"About Sluice {ui_module.__version__}"]


def test_every_shortcut_survived_the_move(two):
    win, _, _ = two
    keys = {}
    for name in ("File", "Mixer", "View", "Help"):
        for action in menu_of(win, name).actions():
            if action.shortcut().toString():
                keys[action.text().replace("&", "")] = action.shortcut().toString()
    assert keys["Add channel…"] == "Ctrl+N" and keys["Refresh devices and apps"] == "F5"
    assert keys["Mute my microphone"] == "Ctrl+M" and keys["Hear Broadcast"] == "Ctrl+B"
    assert keys["Mute Listen"] == "Ctrl+Shift+L" and keys["Mute Broadcast"] == "Ctrl+Shift+B"
    assert keys["Full screen"] == "F11" and keys["Keyboard shortcuts"] == "F1" and keys["Save settings"] == "Ctrl+S"
    assert "Quit" in texts(menu_of(win, "File"))  # its Ctrl+Q is the platform's standard Quit key


def test_the_settings_menu_ticks_follow_the_real_state(two, tmp_path, monkeypatch):
    from sluice import desktop

    win, engine, _ = two
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    engine.mixer.auto_update = True
    engine.mixer.close_action = "tray"
    win._refresh_settings_menu()
    assert win.auto_update_action.isChecked()
    assert [k for k, a in win.close_actions.items() if a.isChecked()] == ["tray"]
    assert [k for k, a in win.autostart_actions.items() if a.isChecked()] == [desktop.autostart_state()]


def test_the_minimized_start_option_says_where_it_goes(two):
    win, _, _ = two
    text = win.autostart_actions["minimized"].text()
    assert "Start minimized" in text and "system tray" in text and "taskbar" not in text


def test_the_controllers_item_lives_in_settings_between_the_options_and_reset(two):
    win, _, _ = two

    class Controls:
        shown = 0

        def show_dialog(self):
            Controls.shown += 1

        def close(self):
            pass

    win.attach_controls(Controls())
    settings = menu_of(win, "Settings")
    names = texts(settings)
    assert names.index("MIDI controllers and Stream Deck…") < names.index("Reset all settings to the defaults…")
    next(a for a in settings.actions() if a.text().startswith("&MIDI")).trigger()
    assert Controls.shown == 1
    assert "Controllers" not in [a.text().replace("&", "") for a in win.menuBar().actions()]


# ------------------------------------------------------------------- reset to defaults
def test_reset_keeps_a_copy_writes_the_defaults_and_protects_them_from_the_old_state(two, tmp_path, monkeypatch):
    win, engine, _ = two
    engine.mixer.theme = "purple"
    engine.add_channel("Extra")
    win.save_settings()
    before = json.loads((tmp_path / "config.json").read_text())
    assert before["theme"] == "purple"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    win.reset_settings()
    fresh = json.loads((tmp_path / "config.json").read_text())
    assert fresh == Mixer.default().to_dict() and fresh["theme"] == "dark"
    assert json.loads((tmp_path / "config.before-reset.json").read_text()) == before
    assert win._keep_settings_file and "Close Sluice and start it again" in win.status_label.text()
    win.shutdown()  # quitting must not write the old settings back
    assert json.loads((tmp_path / "config.json").read_text()) == fresh


def test_reset_does_nothing_when_you_say_no(two, tmp_path, monkeypatch):
    win, engine, _ = two
    win.save_settings()
    before = (tmp_path / "config.json").read_text()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win.reset_settings()
    assert (tmp_path / "config.json").read_text() == before and not (tmp_path / "config.before-reset.json").exists()
    assert not win._keep_settings_file


def test_reset_in_demo_mode_has_nothing_to_reset(qapp):
    win, _, _ = make(qapp, __import__("pathlib").Path("/nonexistent"))
    win.config_file = None
    win.reset_settings()
    assert "Demo mode" in win.status_label.text()
    win.shutdown()


def test_reset_mentions_what_is_kept(two, monkeypatch):
    win, _, _ = two
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No))
    win.reset_settings()
    assert "presets" in asked[0] and "config.before-reset.json" in asked[0]


# ------------------------------------------------------------------- links
def test_the_help_links_open_the_right_pages(two, monkeypatch):
    win, _, _ = two
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    help_menu = menu_of(win, "Help")
    for label in ("Report a problem…", "Join the Discord…", "Project page on GitHub…"):
        next(a for a in help_menu.actions() if a.text() == label).trigger()
    assert opened == [ui_module.ISSUES_URL, ui_module.DISCORD_URL, ui_module.PROJECT_URL]
    assert ui_module.DISCORD_URL == "https://discord.gg/awDvJ5Vj2S" and ui_module.ISSUES_URL.endswith("/Sluice/issues")


def test_a_browser_that_cannot_be_opened_still_shows_the_address(two, monkeypatch):
    win, _, _ = two
    shown = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: False))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    win.open_link(ui_module.DISCORD_URL)
    assert shown and ui_module.DISCORD_URL in shown[0]


def test_about_has_the_links(two, monkeypatch):
    win, _, _ = two
    shown = []
    monkeypatch.setattr(QMessageBox, "about", staticmethod(lambda *a, **k: shown.append(a[2])))
    win.show_about()
    for url in (ui_module.DISCORD_URL, ui_module.PROJECT_URL, ui_module.ISSUES_URL):
        assert f'href="{url}"' in shown[0]


def test_the_discord_link_is_the_same_everywhere():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    chooser = root / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    assert ui_module.DISCORD_URL in readme
    if chooser.exists():
        assert ui_module.DISCORD_URL in chooser.read_text()


# ------------------------------------------------------------------- the dropout label
def test_the_dropout_label_reads_well_and_explains_itself(two):
    win, engine, io = two
    engine._quiet_until = 0.0
    from sluice import events
    events.clear()    # starting the engine just now changed links: that is not what this test is about
    io.xruns, io.xruns_ours = 1, 0
    win._tick_engine()
    assert win.perf_label.text().endswith("1 dropout")
    io.xruns, io.xruns_ours = 12, 1
    win._tick_engine()
    assert win.perf_label.text().endswith("12 dropouts · mostly elsewhere")
    assert "pw-top" in win.perf_label.toolTip() and "any other program" in win.perf_label.toolTip()


def test_the_dropout_label_keeps_its_tooltip_while_the_number_does_not_change(two):
    win, engine, io = two
    win._tick_engine()
    tip = win.perf_label.toolTip()
    win._tick_engine()
    assert win.perf_label.toolTip() == tip and "dropout" in tip


# ------------------------------------------------------------------- the larger buffer offer
def test_a_larger_buffer_is_offered_after_three_dropouts_and_taken_with_one_click(two):
    win, engine, io = two
    assert engine.larger_buffer_offer() is None
    win._update_buffer_offer()
    assert not win.buffer_offer.isVisibleTo(win)
    engine._xrun_base = engine.io.xruns - 3
    engine.mixer.buffer_frames = engine.io.blocksize
    bigger = engine.larger_buffer_offer()
    assert bigger is not None and bigger > engine.io.blocksize
    win._update_buffer_offer()
    assert win.buffer_offer.text() == f"Try a larger buffer ({bigger})"
    win.buffer_offer.click()
    assert engine.mixer.buffer_frames == bigger
    assert not win.buffer_offer.isVisibleTo(win)  # the choice waits for the next start: no second offer
