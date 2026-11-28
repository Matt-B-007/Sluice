# SPDX-License-Identifier: GPL-3.0-or-later
"""0.13.1-beta.3: the fixes from the click-everything pass over 0.13.1-beta.2 (settings switches that showed the wrong state,
the Effects window on an app channel, Reset, duplicate channel names, the command search, the grid, wording)."""

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402

from sluice import setup_check, themes, uninstall  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402

SOURCES = Path(__file__).resolve().parent.parent / "sluice"


def make(qapp, tmp_path, setup=None):
    mixer = Mixer.demo()
    mixer.hints_seen.append("firstrun")
    if setup:
        setup(mixer)
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    window = MainWindow(engine, config_file=tmp_path / "config.json")
    window.show()
    qapp.processEvents()
    return window


@pytest.fixture
def win(qapp, tmp_path):
    window = make(qapp, tmp_path)
    yield window
    window.shutdown()


def bound_to(settings, action):
    return next(item for item in settings.bound if item.action is action)


def test_settings_switches_show_what_is_really_on(qapp, tmp_path):
    def setup(mixer):
        mixer.check_daily = True
        mixer.devices_follow_broadcast = True

    window = make(qapp, tmp_path, setup)
    try:
        window.open_settings("Updates")
        qapp.processEvents()
        settings = window.settings_window
        daily = bound_to(settings, window.check_daily_action)
        assert daily.button.isChecked()  # it showed "off" while the daily look was on
        daily.button.click()  # ...so the first click turned it off instead of on
        qapp.processEvents()
        assert window.engine.mixer.check_daily is False and not daily.button.isChecked()
        daily.button.click()
        qapp.processEvents()
        assert window.engine.mixer.check_daily is True and daily.button.isChecked()
        assert bound_to(settings, window.follow_action).button.isChecked() == window.engine.mixer.devices_follow_broadcast
    finally:
        window.shutdown()


def test_the_uninstall_list_follows_both_boxes(qapp, tmp_path):
    from sluice.ui_uninstall import UninstallDialog

    seen = []

    def plan(everything, caches):
        seen.append((everything, caches))
        return uninstall.plan(keep_settings=not everything, clear_caches=caches, root=tmp_path / "app")

    dialog = UninstallDialog(plan(False, False), plan(True, False), None, plan=plan)
    dialog.caches.setChecked(True)
    assert seen[-1] == (False, True)
    dialog.delete_settings.setChecked(True)
    assert seen[-1] == (True, True)
    dialog.close()


def test_a_skipped_version_is_not_installed_by_itself(win, monkeypatch):
    from sluice import update_check, update_install

    staged = []
    result = update_check.UpdateResult(status="available", current="0.1", latest="9.9.9", notes="", page="")
    monkeypatch.setattr(update_install, "unavailable_reason", lambda root: "")
    monkeypatch.setattr(update_install, "offer_problem", lambda root, r: "")
    win._update_check = lambda *a, **k: result
    win._stage_update = lambda r, root: staged.append(r.latest) or "staged"
    win.engine.mixer.auto_update = True
    win.engine.mixer.skipped_version = "9.9.9"
    win._auto_update_started = False
    threads = []
    import threading

    real = threading.Thread

    def remember(*args, **kwargs):
        thread = real(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(threading, "Thread", remember)
    win._auto_update_check()
    for thread in threads:
        thread.join(5)
    assert staged == []


def test_two_channels_cannot_share_a_name_and_a_long_one_is_said_to_be_cut(win):
    name, problem = win.channel_name("  game ")
    assert name == "game" and "already" in problem  # "Game" exists (whatever the capitals)
    assert win.channel_name("Listen")[1]  # a mix's name is taken too
    assert win.channel_name("   ")[1]
    name, problem = win.channel_name("A name that is much longer than twenty-four")
    assert len(name) <= 24 and problem == ""
    game = next(c for c in win.engine.mixer.channels if c.label == "Game")
    assert win.channel_name("Game", renaming=game.id) == ("Game", "")  # renaming a channel to its own name is fine


def test_effects_window_speaks_of_the_channel_it_is_on(win, qapp):
    from sluice.ui_effects import EffectsDialog

    mixer = win.engine.mixer
    mic = next(c for c in mixer.channels if c.devices)
    app = next(c for c in mixer.channels if not c.devices)
    for channel, voice in ((mic, True), (app, False)):
        dialog = EffectsDialog(win.engine, channel, win)
        qapp.processEvents()
        texts = [label.text() for label in dialog.findChildren(QLabel)]
        assert any(text == f"{channel.label} effects" for text in texts)
        assert (dialog.compare_button.text() == "Hear my original microphone") is voice
        assert dialog.live.voice is voice
        assert dialog.close_button.text() == "Close"
        assert dialog.minimumHeight() <= 480  # it needed 892 pixels of height
        dialog.close()


def test_reset_this_effect_and_where_the_compare_button_is(win, qapp):
    from sluice.ui_effects import EffectsDialog

    mic = next(c for c in win.engine.mixer.channels if c.devices)
    dialog = EffectsDialog(win.engine, mic, win)
    qapp.processEvents()
    by_type = {effect.type: row for row, effect in enumerate(mic.effects)}
    for kind, compare in (("noise_gate", False), ("compressor", False), ("limiter", False), ("noise_reducer", True)):
        if kind not in by_type:
            continue
        dialog.list.setCurrentRow(by_type[kind])
        qapp.processEvents()
        buttons = [b.text() for b in dialog.findChildren(QPushButton) if b.isVisibleTo(dialog)]
        assert any(text.startswith("Compare: switch both reducers") for text in buttons) is compare, kind
        assert "Reset this effect" in buttons
    gate = mic.effects[by_type["noise_gate"]]
    instance = win.engine.effect_instance(gate.id)
    info = next(i for i in instance.param_infos() if i.default is not None)
    win.engine.set_effect_param(gate.id, info.key, info.lo if info.default != info.lo else info.hi)
    dialog._reset_effect(gate)  # (the Room and Voice style Reset buttons never touched the Noise Gate)
    assert gate.params.get(info.key, info.default) == pytest.approx(info.default)
    dialog.close()


def test_command_search_says_when_nothing_matches():
    from sluice import ui_command

    assert ui_command.matches("Theme › Light", "theme li")
    assert ui_command.matches("Show the “Play to” devices in apps’ own sound settings", "play to")
    assert not ui_command.matches("Effects on Browser", "rows")  # (a word typed starts a word of the label)


def test_off_is_one_word_and_the_mix_mute_hints_make_sense(win):
    from sluice.ui_base import format_db, format_level, mix_mute_tip

    assert format_db(-60.0) == "off" and format_level(-60.0).startswith("off")
    listen, broadcast = win.engine.mixer.mixes[0], win.engine.mixer.mixes[1]
    assert mix_mute_tip(listen, True).startswith("Listen is muted: you hear nothing") and "nobody" not in mix_mute_tip(
        listen, True
    )
    assert "Ctrl+Shift+L" in mix_mute_tip(listen, False) and "Ctrl+Shift+B" in mix_mute_tip(broadcast, False)


def test_a_fader_tells_screen_readers_its_level_before_it_is_moved(win, qapp):
    strip = next(s for s in win.strips if s.channel.label == "Game")
    fader = next(iter(strip.faders.values()))
    level = next(iter(strip.channel.levels.values()))
    assert level != 0.0 and fader.accessibleDescription() != "0.0 dB"  # (every fader said "0.0 dB" until it was moved)
    fader.blockSignals(True)
    fader.setValue(fader.minimum())
    fader.blockSignals(False)
    assert fader.accessibleDescription() == "off"


def test_the_grid_is_painted_not_styled(win, qapp):
    from sluice.ui_nexus import CardFloor, GridFloor

    assert "repeat" not in win.styleSheet() + win.centralWidget().styleSheet()  # (the rule that blackened Rows is gone)
    assert isinstance(win.channels_widget, CardFloor) and themes.grid_on()
    win.set_layout("rows")
    qapp.processEvents()
    assert isinstance(win.channels_widget, GridFloor)
    image = win.channels_widget.grab().toImage()
    assert image.pixelColor(2, 2).lightness() > 0 or themes.luminance(themes.color("bg")) < 0.1
    corner = image.pixelColor(1, 1)
    assert abs(corner.lightness() - themes.luminance(themes.color("bg")) * 255) < 40  # the theme's background, not black


def test_ticked_boxes_have_a_tick_and_radios_are_round():
    css = themes.build_style(dict(themes.DARK))
    box = re.search(r"QCheckBox::indicator:checked \{([^}]*)\}", css).group(1)
    assert "image: url(" in box
    radio = re.search(r"QRadioButton::indicator:checked \{([^}]*)\}", css).group(1)
    assert "qradialgradient" in radio and "4px solid" not in radio  # (a 4-pixel border made it a square, and moved the text)


def test_setup_check_lists_the_signature_checker():
    part = setup_check.BY_KEY["cryptography"]
    assert not part.required and "signature" in part.purpose
    ok, _reason = part.check()
    assert ok is True  # (the tests need it installed)


def test_update_window_has_one_obvious_button(qapp):
    from sluice.ui_whatsnew import NotesDialog

    ran = []
    dialog = NotesDialog(
        "Sluice 9 is available",
        "Sluice 9 is available",
        "notes",
        "Open download page",
        "https://example.invalid/",
        action=lambda: ran.append(1),
        action_label="Update now",
        extra=("Skip this version", lambda: None),
        close_label="Later",
    )
    buttons = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "Open download page" not in buttons and len(buttons) == 4
    assert dialog.action_button.isDefault() and not dialog.close_button.isDefault()
    dialog.close()


def test_no_message_points_at_a_menu_that_is_gone():
    old = re.compile(r"(File|View|Mixer|Window) (>|›) |Help > Uninstall")
    for path in sorted(SOURCES.glob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if '"""' in line or not old.search(code):
                continue
            assert "System Settings > Window" in code, f"{path.name}:{number}: {line.strip()}"


def test_the_compact_list_has_a_whole_rule_above_the_mix_row():
    css = themes.build_style(dict(themes.DARK))
    assert "QFrame#hrule" in css and '"hrule"' in (SOURCES / "ui_mini.py").read_text()
