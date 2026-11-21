# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings window (0.11.5): everything that is chosen once and then left alone, in five sections, opened by the ⚙ button beside
the ☰ menu in the top bar.

- Themes and skins: the skin (how things are shaped and drawn; a live picture of each, in the theme in use), the theme (the colours),
  the skin's own colours, reduce effects, the layout, and the desktop widgets' own skin and theme
- Audio: the audio buffer
- Startup and background: starting at login, what closing the window does, the applications menu entry
- Controllers: MIDI controllers and Stream Deck
- Updates: automatic updates, checking now, going back a version, and resetting every setting

Every control here is bound to one of the window's actions (``window.autostart_actions``, ``window.buffer_actions`` and the rest). The
action keeps the state and does the work, as before; this window only shows it and changes it, so nothing is done in two places."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QRadioButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from . import themes

SECTIONS = ("Themes and skins", "Audio", "Startup and background", "Controllers", "Updates")


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settingsheading")
    return label


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _plain(text: str) -> str:
    """A menu label as plain text: no Alt-key ampersand and no trailing "…" (a button here says what it opens on its own)."""
    return text.split("\t")[0].replace("&&", "\0").replace("&", "").replace("\0", "&")


class _Bound:
    """A check box or radio button that shows an action's state and triggers the action when clicked."""

    def __init__(self, button: QAbstractButton, action: QAction) -> None:
        self.button, self.action = button, action
        button.clicked.connect(self._clicked)

    def _clicked(self) -> None:
        if self.button.isChecked() != self.action.isChecked() or not self.action.isCheckable():
            self.action.trigger()
        self.refresh()

    def refresh(self) -> None:
        self.button.blockSignals(True)
        self.button.setText(_plain(self.action.text()))
        self.button.setChecked(self.action.isChecked())
        self.button.setEnabled(self.action.isEnabled())
        self.button.setVisible(self.action.isVisible())
        self.button.setToolTip(self.action.toolTip() if self.action.toolTip() != _plain(self.action.text()) else "")
        self.button.blockSignals(False)


class LookCard(QPushButton):
    """A look as a picture in the colours of the theme in use; click it to use that look."""

    def __init__(self, look_id: str) -> None:
        super().__init__()
        self.look_id = look_id
        self.setObjectName("lookcard")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{themes.LOOKS[look_id]} skin")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.picture = QLabel()
        self.picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.caption = QLabel(themes.LOOKS[look_id])
        self.caption.setObjectName("lookname")
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(6)
        box.addWidget(self.picture)
        box.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignHCenter)
        from .ui_skins import H, W
        self.setFixedSize(W + 16, H + 44)

    def keyPressEvent(self, event) -> None:
        """The arrow keys move between the skin cards (0.11.6), like a row of radio buttons; Space or Enter picks one."""
        step = {Qt.Key.Key_Right: 1, Qt.Key.Key_Down: 1, Qt.Key.Key_Left: -1, Qt.Key.Key_Up: -1}.get(event.key())
        if step is None:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.click()
                return
            super().keyPressEvent(event)
            return
        cards = [c for c in (self.parentWidget().findChildren(LookCard) if self.parentWidget() else []) if c.isVisible()]
        if self in cards:
            cards[(cards.index(self) + step) % len(cards)].setFocus(Qt.FocusReason.TabFocusReason)

    def show_preview(self, theme) -> None:
        from .ui_skins import BLURBS, draw_preview
        self.picture.setPixmap(draw_preview(self.look_id, themes.look_colors(theme, self.look_id), self.devicePixelRatioF()))
        self.setToolTip(BLURBS.get(self.look_id, ""))


class SettingsWindow(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ = window
        self.setObjectName("settings")
        self.setWindowTitle("Sluice settings")
        self.bound: list = []
        self.sections = QListWidget()
        self.sections.setObjectName("settingssections")
        self.sections.setAccessibleName("Settings sections")
        self.sections.addItems(list(SECTIONS))
        self.sections.setFixedWidth(220)
        self.pages = QStackedWidget()
        for build in (self._appearance, self._audio, self._startup, self._controllers, self._updates):
            page = QWidget()
            column = QVBoxLayout(page)
            column.setContentsMargins(24, 16, 24, 16)
            column.setSpacing(12)
            build(column)
            column.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.setCurrentRow(0)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        close.setDefault(True)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(close)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addLayout(body, 1)
        outer.addLayout(foot)
        self.resize(940, 620)

    # ------------------------------------------------------------------ building the pages
    def _bind(self, column: QVBoxLayout, action: QAction, radio: QButtonGroup = None) -> QAbstractButton:
        button = QRadioButton() if radio is not None else QCheckBox()
        if radio is not None:
            radio.addButton(button)
        column.addWidget(button)
        self.bound.append(_Bound(button, action))
        return button

    def _action_button(self, column, text: str, action_or_slot, tip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        if isinstance(action_or_slot, QAction):
            button.clicked.connect(lambda _c=False, a=action_or_slot: a.trigger())
        else:
            button.clicked.connect(lambda _c=False, s=action_or_slot: s())
        row = QHBoxLayout()
        row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)
        return button

    def _appearance(self, column: QVBoxLayout) -> None:
        w = self.window_
        column.addWidget(_heading("Skin"))
        column.addWidget(_note("How the window and the desktop widgets are shaped and drawn. Each picture is drawn in the theme you are using."))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.look_cards = {}
        for index, look_id in enumerate(themes.LOOKS):
            card = LookCard(look_id)
            card.clicked.connect(lambda _c=False, look_id=look_id: self._choose_look(look_id))
            grid.addWidget(card, index // 2, index % 2)
            self.look_cards[look_id] = card
        holder = QHBoxLayout()
        holder.addLayout(grid)
        holder.addStretch(1)
        column.addLayout(holder)
        column.addWidget(_heading("Theme"))
        column.addWidget(_note("The colours, in any skin. Import a theme file, export the one you use, or remove one you imported."))
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themepicker")
        self.theme_button.setMenu(w.theme_menu)
        self.theme_button.setAccessibleName("Theme")
        row = QHBoxLayout()
        row.addWidget(self.theme_button)
        row.addStretch(1)
        column.addLayout(row)
        self._bind(column, w.look_colors_action)
        self._bind(column, w.reduce_action)
        column.addWidget(_heading("Layout"))
        group = QButtonGroup(self)
        for action in w.layout_actions.values():
            self._bind(column, action, group)
        column.addWidget(_heading("Desktop widgets"))
        column.addWidget(_note("The widgets you keep on the desktop can have a skin and a theme of their own, for example Glass "
                               "widgets over your wallpaper with the window in Calm."))
        self.widget_skin = QComboBox()
        self.widget_skin.setAccessibleName("Desktop widgets' skin")
        self.widget_skin.activated.connect(self._widget_skin_chosen)
        self.widget_theme = QComboBox()
        self.widget_theme.setAccessibleName("Desktop widgets' theme")
        self.widget_theme.activated.connect(self._widget_theme_chosen)
        for label, combo in (("Skin", self.widget_skin), ("Theme", self.widget_theme)):
            row = QHBoxLayout()
            row.setSpacing(12)
            name = QLabel(label)
            name.setMinimumWidth(64)
            name.setBuddy(combo)
            row.addWidget(name)
            row.addWidget(combo)
            row.addStretch(1)
            column.addLayout(row)

    def _audio(self, column: QVBoxLayout) -> None:
        w = self.window_
        column.addWidget(_heading("Audio buffer"))
        column.addWidget(_note("How much sound Sluice handles at a time. A smaller buffer means less delay; a larger one uses less "
                               "CPU and is less likely to drop out. It is used the next time Sluice starts."))
        group = QButtonGroup(self)
        for action in w.buffer_actions.values():
            self._bind(column, action, group)

    def _startup(self, column: QVBoxLayout) -> None:
        w = self.window_
        column.addWidget(_heading("When I log in"))
        group = QButtonGroup(self)
        for action in w.autostart_actions.values():
            self._bind(column, action, group)
        column.addWidget(_heading("When I close the window"))
        group = QButtonGroup(self)
        for action in w.close_actions.values():
            self._bind(column, action, group)
        self.no_tray = _note(w.no_tray_note.text())
        column.addWidget(self.no_tray)
        column.addWidget(_heading("Applications menu"))
        self._bind(column, w.launcher_action)

    def _controllers(self, column: QVBoxLayout) -> None:
        column.addWidget(_heading("MIDI controllers and Stream Deck"))
        column.addWidget(_note("Turn a knob or press a key on a controller to move a fader, mute a channel or mute your microphone."))
        self.controllers_button = self._action_button(column, "Set up controllers", self._open_controllers)
        self.controllers_missing = _note("Controllers are not available in this copy of Sluice.")
        column.addWidget(self.controllers_missing)

    def _updates(self, column: QVBoxLayout) -> None:
        w = self.window_
        column.addWidget(_heading("Updates"))
        self._bind(column, w.auto_update_action)
        self._action_button(column, "Check for updates now", w.check_for_updates)
        self.rollback_button = self._action_button(column, "Go back to the previous version", w.rollback_action)
        column.addWidget(_heading("Start again"))
        column.addWidget(_note("Put every setting back to how it was when Sluice was new. Your settings are backed up first."))
        self._action_button(column, "Reset all settings to the defaults", w.reset_settings)

    # ------------------------------------------------------------------ keeping it up to date
    def _choose_look(self, look_id: str) -> None:
        self.window_.choose_look(look_id)
        self.refresh()

    def _widget_skin_chosen(self, index: int) -> None:
        self.window_.set_widget_dress(look=self.widget_skin.itemData(index) or "")

    def _widget_theme_chosen(self, index: int) -> None:
        self.window_.set_widget_dress(theme=self.widget_theme.itemData(index) or "")

    def _fill_widget_choices(self) -> None:
        """The skins and themes the desktop widgets can have, "Same as the window" first, with the one in use chosen."""
        w = self.window_
        mixer = w.engine.mixer
        skins = [("Same as the window", "")] + [(name, look_id) for look_id, name in themes.LOOKS.items()]
        choices = [("Same as the window", "")] + [(t.name, t.id) for t in themes.BUILT_IN.values()]
        choices.append((themes.SYSTEM_LABEL, themes.SYSTEM))
        choices += [(t.name, t.id) for t in themes.custom_themes(w._themes_folder())]
        for combo, items, chosen in ((self.widget_skin, skins, mixer.widget_look), (self.widget_theme, choices, mixer.widget_theme)):
            combo.blockSignals(True)
            combo.clear()
            for label, data in items:
                combo.addItem(label, data)
            index = combo.findData(chosen)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _open_controllers(self) -> None:
        controls = getattr(self.window_, "controls", None)
        if controls is not None:
            controls.show_dialog()

    def refresh(self) -> None:
        """Show the real state of every setting (the window's own refreshers bring the actions up to date first)."""
        w = self.window_
        w._refresh_settings_menu()
        w._refresh_buffer_menu()
        w._refresh_view_menu()
        w._show_layout_choice()
        theme = w.current_theme()
        look = themes.valid_look(w.engine.mixer.look)
        for look_id, card in self.look_cards.items():
            card.blockSignals(True)
            card.setChecked(look_id == look)
            card.blockSignals(False)
            card.show_preview(theme)
        self.theme_button.setText(f"{theme.name}  ▾")
        self._fill_widget_choices()
        for item in self.bound:
            item.refresh()
        self.no_tray.setVisible(w.no_tray_note.isVisible())
        rollback = w.rollback_action
        self.rollback_button.setText(_plain(rollback.text()).rstrip("…"))
        self.rollback_button.setEnabled(rollback.isEnabled())
        has_controls = getattr(w, "controls", None) is not None
        self.controllers_button.setVisible(has_controls)
        self.controllers_missing.setVisible(not has_controls)

    def open_at(self, section: str = "") -> None:
        if section in SECTIONS:
            self.sections.setCurrentRow(SECTIONS.index(section))
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()
