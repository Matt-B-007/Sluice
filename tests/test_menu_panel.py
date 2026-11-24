# SPDX-License-Identifier: GPL-3.0-or-later
"""The ☰ panel (0.11.7): one flat panel built from the window's actions, usable from the keyboard and by a screen reader."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402


def make(qapp, tmp_path, skin="calm"):
    mixer = Mixer.demo()
    mixer.skin = skin
    mixer.hints_seen.append("firstrun")
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.show()
    for _ in range(3):
        qapp.processEvents()
    return win, engine


def open_panel(qapp, win):
    win.menu_button.click()
    qapp.processEvents()
    return win.menu_panel


def test_the_menu_button_opens_the_panel_with_its_groups(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        panel = open_panel(qapp, win)
        assert panel.isVisible() and win.menu_button.menu() is None  # a panel, not the old nested menus
        sections = [label.text() for label in panel.findChildren(type(panel.rows[0].name)) if label.objectName() == "panelsection"]
        assert sections == ["QUICK MUTES", "MIXER AND DESKTOP", "HELP"]  # 0.12.0: Columns and Rows are in the top bar
        assert [t.name.text() for t in panel.tiles] == ["Mute my mic", "Add channel", "Refresh"]
        names = [r.name.text() for r in panel.rows]
        assert names[-2:] == ["Settings…", "Quit"]
        for wanted in ("Desktop widgets", "Show or hide my widgets", "Recording mix", "Full screen", "Hide to tray",
                       "Keyboard shortcuts", "I heard a glitch", "Save bug report…", "Report a problem"):
            assert wanted in names
        # the shortcuts it shows are the actions' own (so they can never disagree with what the keys do)
        row = next(r for r in panel.rows if r.name.text() == "Show or hide my widgets")
        assert row.key.text() == "Ctrl+Shift+W" and row.key.isVisible()
    finally:
        win.shutdown()


def test_the_panel_works_from_the_keyboard(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        panel = open_panel(qapp, win)
        items = panel.focusable()
        assert panel.focusWidget() is items[0]
        QTest.keyClick(panel, Qt.Key.Key_Down)
        assert panel.focusWidget() is items[1]
        QTest.keyClick(panel, Qt.Key.Key_Up)
        QTest.keyClick(panel, Qt.Key.Key_Up)
        assert panel.focusWidget() is items[-1]  # round to the bottom (Quit)
        QTest.keyClick(panel, Qt.Key.Key_Escape)
        assert not panel.isVisible()
    finally:
        win.shutdown()


def test_everything_in_the_panel_has_a_name_for_a_screen_reader(qapp, tmp_path):
    from PySide6.QtWidgets import QAbstractButton
    win, _ = make(qapp, tmp_path)
    try:
        panel = open_panel(qapp, win)
        unnamed = [b for b in panel.findChildren(QAbstractButton) if b.isVisible() and not (b.accessibleName() or b.text())]
        assert unnamed == []
        mic = panel.tiles[0]
        assert mic.accessibleDescription() == "Ctrl+M"
    finally:
        win.shutdown()


def test_the_panel_drives_the_same_actions(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        panel = open_panel(qapp, win)
        mic = panel.tiles[0]
        mic.click()
        assert win.mic_action.isChecked() and panel.isVisible() and mic.name.text() == "Mic muted"  # a toggle keeps it open
        mic.click()
        assert not win.mic_action.isChecked()
        listen = panel.mute_buttons[0]
        listen.click()
        assert win.mute_actions["monitor"].isChecked() and listen.isChecked()
        hide = next(r for r in panel.rows if r.name.text() == "Hide to tray")
        win._update_tray = lambda: None
        win._tray = type("Tray", (), {"isVisible": lambda self: True, "hide": lambda self: None})()
        hide.click()
        assert not panel.isVisible() and not win.isVisible()
    finally:
        win._tray = None
        win.shutdown()


@pytest.mark.parametrize("skin", list(themes.SKINS))
def test_the_panel_looks_the_same_in_every_skin(qapp, tmp_path, skin):
    """The panel is styled by the shared sheet (the theme's colours), never by a skin."""
    win, _ = make(qapp, tmp_path, skin)
    try:
        panel = open_panel(qapp, win)
        assert panel.card.width() == panel.WIDTH and all(r.height() in (36, 40) for r in panel.rows)
        assert panel.rows[0].name.font().pixelSize() == 14
    finally:
        win.shutdown()
