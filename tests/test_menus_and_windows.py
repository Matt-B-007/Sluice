# SPDX-License-Identifier: GPL-3.0-or-later
"""Every menu and every window opened from them, in every skin (0.11.6): headings that show their words (no blank bands), room
between each item and its shortcut, no shortcut used twice, and windows with nothing cut off, overlapping or outside them."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402

from layout_checks import window_problems  # noqa: E402
from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_menus import SHORTCUT_GAP, plain  # noqa: E402

SKINS = list(themes.SKINS)


def make(qapp, tmp_path, skin):
    mixer = Mixer.demo()
    mixer.skin = skin
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.resize(1456, 860)
    win.show()
    qapp.processEvents()
    return win, engine


def all_menus(win):
    win._fill_theme_menu()
    win._fill_skin_menu()
    win._fill_widgets_menu()
    win._refresh_view_menu()
    menus, todo = [], [win.theme_menu, win.widgets_menu]
    todo += list(win.action_groups)
    while todo:
        menu = todo.pop()
        if menu in menus:
            continue
        menus.append(menu)
        todo += [a.menu() for a in menu.actions() if a.menu() is not None]
    return menus


@pytest.mark.parametrize("skin", SKINS)
def test_menus_have_word_headings_and_room_before_every_shortcut(qapp, tmp_path, skin):
    win, _ = make(qapp, tmp_path, skin)
    try:
        problems = []
        for menu in all_menus(win):
            name = plain(menu.title()) or "☰"
            menu.ensurePolished()
            menu.aboutToShow.emit()  # what opening it does: some menus refill, and each widens itself with the skin's font in place
            shown = [a for a in menu.actions() if a.isVisible()]
            if shown and shown[0].isSeparator():
                problems.append((name, "starts with a blank band"))
            for a, b in zip(shown, shown[1:]):
                if a.isSeparator() and b.isSeparator():
                    problems.append((name, "two lines in a row"))
                if a.property("heading") and (b.property("heading") or b.isSeparator()):
                    problems.append((name, f"heading {a.text()!r} has nothing under it"))
            if shown and shown[-1].property("heading"):
                problems.append((name, "ends with a heading"))
            menu.ensurePolished()
            metrics = menu.fontMetrics()
            names = [
                metrics.horizontalAdvance(plain(a.text())) for a in shown if not a.isSeparator() and not a.property("heading")
            ]
            keys = [
                metrics.horizontalAdvance(a.shortcut().toString(QKeySequence.SequenceFormat.NativeText))
                for a in shown
                if not a.shortcut().isEmpty()
            ]
            if names and keys:
                room = (
                    max(menu.width(), menu.minimumWidth(), menu.sizeHint().width())
                    - max(names)
                    - max(keys)
                    - 2 * 24
                    - 2 * 22
                    - 2 * 9
                )
                if room < SHORTCUT_GAP - 1:
                    problems.append((name, "shortcuts too close to the names", room))
            for a in shown:
                text = plain(a.text())
                if "..." in a.text():
                    problems.append((name, f"{text!r} uses three dots instead of …"))
        assert problems == []
    finally:
        win.shutdown()


def test_no_shortcut_is_used_twice_and_all_are_in_the_list(qapp, tmp_path):
    win, _ = make(qapp, tmp_path, "calm")
    try:
        keys = [a.shortcut().toString() for a in win.actions() if not a.shortcut().isEmpty()]
        assert len(keys) == len(set(keys)), sorted(keys)
        listed = {k for k, _ in win.shortcut_rows()}
        assert (
            set(
                a.shortcut().toString(QKeySequence.SequenceFormat.NativeText) for a in win.actions() if not a.shortcut().isEmpty()
            )
            == listed
        )
        for wanted in (
            "Ctrl+Q",
            "Ctrl+,",
            "Ctrl+S",
            "Ctrl+N",
            "F5",
            "Ctrl+1",
            "Ctrl+2",
            "Ctrl+Shift+W",
            "F11",
            "Ctrl+0",
            "Ctrl+M",
            "Ctrl+Shift+L",
            "Ctrl+Shift+B",
            "Ctrl+H",
            "Ctrl+Shift+G",
            "F1",
        ):
            assert wanted in keys, wanted
        assert "Ctrl+B" not in keys  # Hear Broadcast moved away from Mute Broadcast's Ctrl+Shift+B
    finally:
        win.shutdown()


def test_ctrl_shift_w_closes_and_reopens_the_widgets_you_had(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "calm")
    try:
        win.desktop.open("mic")
        win.desktop.open("mix", "stream")
        win.toggle_my_widgets()
        assert not win.desktop.open_widgets
        win.toggle_my_widgets()
        assert win.desktop.is_open("mic", None) and win.desktop.is_open("mix", "stream")
    finally:
        win.shutdown()


def test_widgets_put_away_come_back_after_a_restart(qapp, tmp_path):
    """0.11.7: Ctrl+Shift+W remembered the widgets only while Sluice ran; quitting (or an update's restart) lost them."""
    from sluice.model import Mixer

    win, engine = make(qapp, tmp_path, "calm")
    try:
        win.desktop.open("channel", channel="mic", x=300, y=200)
        win.toggle_my_widgets()
        assert not win.desktop.open_widgets and engine.mixer.hidden_widgets
        engine.save_config(tmp_path / "saved.json")
    finally:
        win.shutdown()
    mixer = Mixer.load(tmp_path / "saved.json")
    assert [w["channel"] for w in mixer.hidden_widgets] == ["mic"] and not mixer.desktop_widgets
    mixer.skin = "calm"
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker

    engine2 = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine2.start()
    win2 = MainWindow(engine2, tmp_path / "config2.json")
    try:
        win2.toggle_my_widgets()
        assert win2.desktop.is_open("channel", None, "mic") and not engine2.mixer.hidden_widgets
    finally:
        win2.shutdown()


@pytest.mark.parametrize("skin", SKINS)
def test_windows_opened_from_the_menus_have_nothing_cut_off_or_overlapping(qapp, tmp_path, skin):
    from sluice.ui_channel import OwnDevicesDialog

    win, engine = make(qapp, tmp_path, skin)
    found = []
    try:
        win.open_settings()
        settings = win.settings_window
        for index in range(settings.sections.count()):
            settings.sections.setCurrentRow(index)
            qapp.processEvents()
            found += window_problems(settings, f"{skin}/settings/{settings.sections.item(index).text()}")
        settings.close()
        dialog = OwnDevicesDialog(engine, win)
        dialog.show()
        qapp.processEvents()
        found += window_problems(dialog, f"{skin}/recording devices")
        dialog.close()
        win.show_whats_new()
        qapp.processEvents()
        found += window_problems(win._notes_dialog, f"{skin}/what's new")
        win._notes_dialog.close()
        strip = next(s for s in win.strips if s.channel.id == "mic")
        from sluice.ui_effects import EffectsDialog

        effects = EffectsDialog(engine, strip.channel, win)  # the menu runs it with exec(); show it without blocking
        effects.show()
        qapp.processEvents()
        found += window_problems(effects, f"{skin}/effects")
        effects.close()
        assert found == []
    finally:
        win.shutdown()


def test_settings_window_can_be_used_from_the_keyboard(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win, engine = make(qapp, tmp_path, "calm")
    try:
        win.open_settings("Appearance")  # 0.13.1: Settings opens on General
        window = win.settings_window
        cards = [window.skin_cards[k] for k in themes.SKINS]
        assert all(card.focusPolicy() & Qt.FocusPolicy.TabFocus for card in cards)
        assert all(card.accessibleName().endswith(" skin") for card in cards)
        cards[0].setFocus()
        QTest.keyClick(cards[0], Qt.Key.Key_Right)
        assert window.focusWidget() is cards[1]  # (hasFocus() needs the window to be active, which a test screen may not give)
        QTest.keyClick(cards[1], Qt.Key.Key_Left)
        assert window.focusWidget() is cards[0]
        cards[1].setFocus()
        QTest.keyClick(cards[1], Qt.Key.Key_Space)
        assert engine.mixer.skin == list(themes.SKINS)[1]
        assert window.sections.accessibleName() == "Settings sections"
    finally:
        win.shutdown()


def test_a_suspended_window_hides_into_the_tray_on_wayland(qapp, tmp_path):
    """0.11.7: Wayland never says a window was minimized, so Sluice stayed in the taskbar. KWin marks a minimized window suspended
    (Qt: not exposed); when that comes right after the window was in use and the tray is on, Sluice hides into the tray."""
    from sluice.ui_tray import SuspendWatcher

    win, engine = make(qapp, tmp_path, "calm")
    try:
        watcher = SuspendWatcher(win)
        win._tray = type("Tray", (), {"isVisible": lambda self: True, "hide": lambda self: None})()
        watcher.note_active()
        now = watcher.last_active + 0.3
        assert not watcher.check(now=now, exposed=True) and win.isVisible()  # still shown: nothing to do
        assert not watcher.check(now=watcher.last_active + 5, exposed=False)  # not in use just before (another desktop, say)
        assert watcher.check(now=now, exposed=False) and not win.isVisible() and watcher.seen == 1
        win.show()
        win._tray = None  # no tray: never hide (nothing would bring it back)
        watcher.note_active()
        assert not watcher.check(now=watcher.last_active + 0.3, exposed=False) and win.isVisible()
    finally:
        win._tray = None
        win.shutdown()


def test_ctrl_w_hides_into_the_tray_or_minimizes(qapp, tmp_path):
    win, engine = make(qapp, tmp_path, "calm")
    try:
        assert win.hide_action.shortcut().toString() == "Ctrl+W"
        win._update_tray = lambda: None
        win._tray = type("Tray", (), {"isVisible": lambda self: True, "hide": lambda self: None})()
        win.hide_action.trigger()
        assert not win.isVisible()
    finally:
        win._tray = None
        win.shutdown()
