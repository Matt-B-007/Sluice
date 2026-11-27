# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings window and the top bar (0.11.5): ☰ and ⚙ together on the left, status on the right, room under the bar, and every
setting in the window bound to the same action the menus use."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QCheckBox, QRadioButton  # noqa: E402

from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_settings import SECTIONS  # noqa: E402


def make(qapp, tmp_path, skin="calm"):
    mixer = Mixer.demo()
    mixer.skin = skin
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.resize(1456, 860)
    win.show()
    qapp.processEvents()
    return win, engine


def test_the_menu_is_on_the_left_and_help_and_settings_sit_together_on_the_right(qapp, tmp_path):
    """0.13.1 (House Standard): ☰ stays on the left; Help (?) and the Settings gear sit together at the top right."""
    win, _ = make(qapp, tmp_path)
    try:
        bar = win.top_bar
        menu, help_, gear = win.menu_button.geometry(), win.help_button.geometry(), win.settings_button.geometry()
        assert menu.x() < win.app_name.geometry().x() < win.status_chip.geometry().x() < help_.x() < gear.x()
        assert gear.x() - help_.right() <= 12  # beside each other
        assert gear.right() > bar.width() - 40  # the gear is the last thing on the right
        assert win.settings_button.menu() is None  # it opens the window, not a dropdown
    finally:
        win.shutdown()


def test_there_is_room_between_the_top_bar_buttons_and_its_line(qapp, tmp_path):
    from sluice.ui_base import TOP_BAR_GAP

    for skin in ("calm", "tile"):
        win, _ = make(qapp, tmp_path, skin)
        try:
            bottom = max(w.geometry().bottom() for w in (win.menu_button, win.settings_button, win.live_chip, win.status_chip))
            assert win.top_bar.height() - 1 - bottom >= TOP_BAR_GAP, skin
        finally:
            win.shutdown()


def test_the_settings_window_has_five_sections_and_opens_from_the_gear(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        win.settings_button.click()
        qapp.processEvents()
        window = win.settings_window
        assert window.isVisible()
        assert [window.sections.item(i).text() for i in range(window.sections.count())] == list(SECTIONS)
        assert SECTIONS == (
            "General",
            "Appearance",
            "Updates",
            "Privacy",
            "Audio",
            "Controllers",
            "Setup check",
            "Advanced",
            "About & uninstall",
        )  # 0.13.1: the House Standard's order
        win.open_settings("Updates")
        assert window.pages.currentIndex() == SECTIONS.index("Updates")
        assert window is win.settings_window  # one window, kept
    finally:
        win.shutdown()


def test_every_setting_in_the_window_is_bound_to_the_action_the_menus_use(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        win.open_settings()
        window = win.settings_window
        actions = (
            [win.skin_colors_action, win.reduce_action, win.launcher_action, win.auto_update_action]
            + list(win.layout_actions.values())
            + list(win.buffer_actions.values())
            + list(win.autostart_actions.values())
            + list(win.close_actions.values())
        )
        bound = {item.action for item in window.bound}
        assert all(action in bound for action in actions)
        buffer = next(i for i in window.bound if i.action is win.buffer_actions[1024])
        assert isinstance(buffer.button, QRadioButton)
        buffer.button.click()
        assert engine.mixer.buffer_frames == 1024 and buffer.button.isChecked()
        rows = next(i for i in window.bound if i.action is win.layout_actions["rows"])
        rows.button.click()
        qapp.processEvents()
        assert engine.mixer.layout == "rows"
        win.choose_skin("tile")
        window.sections.setCurrentRow(SECTIONS.index("Appearance"))  # (0.13.1: Settings opens on General)
        window.refresh()
        colours = next(i for i in window.bound if i.action is win.skin_colors_action)
        assert (
            isinstance(colours.button, QCheckBox) and colours.button.isVisible() and not colours.button.isChecked()
        )  # (off: 0.13.1)
        colours.button.click()
        assert engine.mixer.skin_colors is True
    finally:
        win.shutdown()


def test_picking_a_look_card_changes_the_look_and_the_pictures_follow_the_theme(qapp, tmp_path):
    win, engine = make(qapp, tmp_path)
    try:
        win.open_settings("Themes and skins")
        window = win.settings_window
        window.skin_cards["tile"].click()
        qapp.processEvents()
        assert engine.mixer.skin == "tile" and window.skin_cards["tile"].isChecked()
        assert not window.skin_cards["calm"].isChecked()
        before = window.skin_cards["calm"].picture.pixmap().toImage()
        win.choose_theme("light")
        assert window.skin_cards["calm"].picture.pixmap().toImage() != before
        assert window.theme_button.text().startswith(themes.BUILT_IN["light"].name)
        assert window.theme_button.menu() is win.theme_menu  # import, export and remove live there
    finally:
        win.shutdown()


def test_the_main_menu_has_a_settings_item_with_a_shortcut(qapp, tmp_path):
    win, _ = make(qapp, tmp_path)
    try:
        assert win.open_settings_action.shortcut().toString() == "Ctrl+,"
        assert ("Ctrl+,", "Settings") in [(k.replace("Ctrl", "Ctrl"), t) for k, t in win.shortcut_rows()]
        win.open_settings_action.trigger()
        assert win.settings_window.isVisible()
    finally:
        win.shutdown()


def test_the_settings_window_looks_the_same_in_every_skin(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel, QPushButton

    seen = {}
    for skin in themes.SKINS:
        win, _ = make(qapp, tmp_path, skin)
        try:
            win.open_settings()
            qapp.processEvents()
            window = win.settings_window
            heading = next(w for w in window.findChildren(QLabel) if w.objectName() == "settingsheading")
            close = next(b for b in window.findChildren(QPushButton) if b.text() == "Close")
            card = window.skin_cards[skin]
            seen[skin] = (
                heading.fontInfo().pixelSize(),
                heading.fontInfo().bold(),
                close.sizeHint().height(),
                window.sections.font().pixelSize() if window.sections.font().pixelSize() > 0 else heading.font().pointSize(),
                card.size().toTuple(),
            )
        finally:
            win.shutdown()
    assert len(set(seen.values())) == 1, seen
