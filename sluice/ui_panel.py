# SPDX-License-Identifier: GPL-3.0-or-later
"""The ☰ panel (0.11.7): one flat panel in the same design as the Settings window, in place of the old File / Mixer / View / Help
submenus behind the ☰ button. Built from the window's own actions, so every shortcut, check mark and test hook is the same thing as
before: the panel only shows the actions and triggers them.

- three tiles: Mute my microphone, Add channel, Refresh
- Quick mutes: Listen, Broadcast, Hear Broadcast
- Mixer and desktop: desktop widgets, show or hide them, the Recording mix, devices for OBS, full screen, hide to tray
- Help: shortcuts, what's new, a glitch, a bug report, a problem; GitHub, Discord and About
- at the bottom: Settings… and Quit

Columns and Rows are in the top bar (and Settings). What is set once and left alone (the skin, the theme, the buffer, startup, updates, your settings files) is in the Settings window.
Up and Down move between the rows, Enter or Space uses one, Escape closes."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import themes, ui_icons as icons
from .ui_base import plain


class Switch(QCheckBox):
    """An on/off switch drawn as a pill and a knob: a check box underneath (screen readers call it one, tests find it as one)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def hitButton(self, pos) -> bool:  # the whole pill toggles it (a check box only counts its little square)
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:
        from PySide6.QtGui import QColor

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        # 0.13.1-beta.3: on a light theme an "off" switch had a dark knob (it read as a third state): a white knob on a greyer track
        light = themes.luminance(themes.color("bg")) >= 0.4
        off_track = themes.mix(themes.color("border"), themes.color("text_dim"), 0.6) if light else themes.color("border")
        track = QColor(themes.color("accent") if on else off_track)
        if not self.isEnabled():
            track.setAlphaF(0.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 11, 11)
        p.setBrush(QColor("#ffffff") if on or light else QColor(themes.color("text2")))
        x = self.width() - 19 if on else 3
        p.drawEllipse(x, 3, 16, 16)
        if self.hasFocus():
            from PySide6.QtGui import QPen

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(themes.color("accent")), 2))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 10, 10)


class PanelRow(QPushButton):
    """One row: an icon, the action's name, and on the right its shortcut as a keycap, a switch (for an on/off action) or a ›."""

    def __init__(self, panel, action, icon: str, submenu=None, closes: bool = True) -> None:
        super().__init__()
        self.panel, self.action, self.icon_name, self.submenu, self.closes = panel, action, icon, submenu, closes
        self.setObjectName("panelrow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.show_key = True
        box = QHBoxLayout(self)
        box.setContentsMargins(10, 0, 10, 0)
        box.setSpacing(12)
        self.picture = QLabel()
        self.picture.setObjectName("panelicon")
        self.name = QLabel()
        self.name.setObjectName("panelname")
        box.addWidget(self.picture)
        box.addWidget(self.name, 1)
        self.key = QLabel()
        self.key.setObjectName("keycap")
        self.key.setFixedHeight(22)
        self.key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.switch = Switch()
        self.switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.switch.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.more = QLabel()
        for part in (self.key, self.switch, self.more):
            part.hide()
            box.addWidget(part, 0, Qt.AlignmentFlag.AlignVCenter)
        for part in (self.picture, self.name, self.key, self.more):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.clicked.connect(self.use)

    def refresh(self) -> None:
        a = self.action
        text = plain(a.text(), keep_dots=True) if a is not None else self.accessibleName()
        if a is not None:
            text = text.split(" (")[0]  # "Recording mix (a third mix)" reads "Recording mix" here
        self.name.setText(text)
        self.setAccessibleName(text)
        color = themes.color("text2")
        self.picture.setPixmap(icons.icon(self.icon_name, color).pixmap(18, 18))
        keys = a.shortcut().toString() if a is not None else ""
        self.key.setText(keys)
        self.key.setVisible(self.show_key and bool(keys) and not (a is not None and a.isCheckable()))
        self.switch.setVisible(a is not None and a.isCheckable())
        if a is not None and a.isCheckable():
            self.switch.setChecked(a.isChecked())
            self.switch.setAccessibleName(text)  # (it only shows the state: the row is what is clicked or focused)
            self.setAccessibleDescription(("on" if a.isChecked() else "off") + (f", {keys}" if keys else ""))
        else:
            self.setAccessibleDescription(keys)
        if self.submenu is not None:
            self.more.setPixmap(icons.icon("chevron_right", themes.color("text_dim")).pixmap(16, 16))
            self.more.show()
        self.setVisible(a is None or a.isVisible())
        self.setEnabled(a is None or a.isEnabled())

    def use(self) -> None:
        if self.submenu is not None:
            self.submenu.popup(self.mapToGlobal(QPoint(self.width() - 8, 0)))
            return
        if self.closes:
            self.panel.close()
        if self.action is not None:
            self.action.trigger()
        if not self.closes:
            self.panel.refresh()


class PanelTile(QPushButton):
    """A big square button at the top of the panel (the things done most)."""

    def __init__(self, panel, action, icon: str, short: str) -> None:
        super().__init__()
        self.panel, self.action, self.icon_name, self.short = panel, action, icon, short
        self.setObjectName("paneltile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(4)
        self.picture, self.name, self.key = QLabel(), QLabel(), QLabel()
        self.name.setObjectName("tilename")
        self.key.setObjectName("tilekey")
        for part in (self.picture, self.name, self.key):
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            box.addWidget(part)
        self.clicked.connect(self.use)

    def refresh(self) -> None:
        a = self.action
        on = a.isCheckable() and a.isChecked()
        for target in (self, self.name):
            target.setProperty("on", on)
            target.style().unpolish(target)
            target.style().polish(target)
        name = {"mic": "Mic muted" if on else "Mute my mic"}.get(self.icon_name, self.short)
        icon = "mic_off" if (self.icon_name == "mic" and on) else self.icon_name
        color = themes.color("mute") if on else themes.color("text")
        self.picture.setPixmap(icons.icon(icon, color).pixmap(20, 20))
        self.name.setText(name)
        self.key.setText(a.shortcut().toString())
        self.setAccessibleName(name)
        self.setAccessibleDescription(a.shortcut().toString())

    def use(self) -> None:
        self.action.trigger()
        if self.action.isCheckable():
            self.panel.refresh()  # a toggle: stay open, show the new state
        else:
            self.panel.close()


class MenuPanel(QWidget):
    """The ☰ panel: a popup holding one rounded card (#menupanel), styled by the shared sheet in the theme's colours."""

    WIDTH = 380

    def __init__(self, window) -> None:
        super().__init__(window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.window_ = window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName("Sluice menu")
        self.rows: list = []
        self.tiles: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("menupanel")
        self.card.setFixedWidth(self.WIDTH)
        outer.addWidget(self.card)
        column = QVBoxLayout(self.card)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(2)
        w = window
        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        for action, icon, short in (
            (w.mic_action, "mic", "Mute my mic"),
            (w.add_channel_action, "plus", "Add channel"),
            (w.refresh_action, "refresh", "Refresh"),
        ):
            tile = PanelTile(self, action, icon, short)
            self.tiles.append(tile)
            tiles.addWidget(tile)
        column.addLayout(tiles)
        column.addSpacing(6)

        self._section(column, "Quick mutes")
        mutes = QHBoxLayout()
        mutes.setSpacing(8)
        self.mute_buttons = []
        for action, icon in [
            (a, {"monitor": "headphones", "stream": "broadcast"}.get(mix, "record")) for mix, a in w.mute_actions.items()
        ] + [(w.hear_action, "speaker")]:
            button = QPushButton()
            button.setObjectName("panelchip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, a=action: (a.trigger(), self.refresh()))
            button.action, button.icon_name = action, icon
            self.mute_buttons.append(button)
            mutes.addWidget(button)
        column.addLayout(mutes)
        column.addSpacing(4)

        self._section(column, "Mixer and desktop")
        self._row(column, None, "widgets", submenu=w.widgets_menu, name="Desktop widgets")
        self._row(column, w.widgets_toggle_action, "eye")
        self._row(column, w.recording_action, "record", closes=False)
        self._row(column, w.own_devices_action, "camera")
        self._row(column, w.fullscreen_action, "fullscreen")
        self._row(column, w.hide_action, "tray")

        self._section(column, "Help")
        self._row(column, w.shortcuts_action, "keyboard")
        self._row(column, w.whats_new_action, "star")
        self._row(column, w.glitch_action, "pulse")
        self._row(column, w.report_action, "bug")
        self._row(column, w.tour_action, "info")  # 0.13.1-beta.3: was "Report a problem" a second time
        links = QHBoxLayout()
        links.setContentsMargins(40, 2, 10, 4)
        links.setSpacing(14)
        for text, action in (("GitHub", w.github_action), ("Discord", w.discord_action), ("About Sluice", w.about_action)):
            link = QPushButton(text)
            link.setObjectName("panellink")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(lambda _c=False, a=action: (self.close(), a.trigger()))
            links.addWidget(link)
        links.addStretch(1)
        column.addLayout(links)

        line = QFrame()
        line.setObjectName("panelline")
        line.setFixedHeight(1)
        column.addSpacing(4)
        column.addWidget(line)
        column.addSpacing(6)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.settings_row = PanelRow(self, w.open_settings_action, "gear")
        self.settings_row.setObjectName("panelfoot")
        self.rows.append(self.settings_row)
        self.quit_row = PanelRow(self, w.quit_action, "quit")
        self.quit_row.setObjectName("panelfoot")
        self.quit_row.setFixedWidth(108)
        self.quit_row.show_key = False  # (Ctrl+Q still works; the button is too small to say so)
        for row in (self.settings_row, self.quit_row):
            row.setFixedHeight(40)
        self.rows.append(self.quit_row)
        foot.addWidget(self.settings_row, 1)
        foot.addWidget(self.quit_row)
        column.addLayout(foot)

    # ------------------------------------------------------------------ building
    def _section(self, column, text: str) -> None:
        label = QLabel(text.upper())
        label.setObjectName("panelsection")
        column.addWidget(label)

    def _row(self, column, action, icon: str, submenu=None, closes: bool = True, name: str = "") -> PanelRow:
        row = PanelRow(self, action, icon, submenu, closes)
        if name:
            row.setAccessibleName(name)
        self.rows.append(row)
        column.addWidget(row)
        return row

    # ------------------------------------------------------------------ showing
    def refresh(self) -> None:
        w = self.window_
        for refresher in ("_refresh_mixer_menu", "_refresh_view_menu", "_refresh_file_menu", "_show_layout_choice"):
            getattr(w, refresher, lambda: None)()
        for item in self.tiles + self.rows:
            item.refresh()
        for button in self.mute_buttons:
            a = button.action
            button.setChecked(a.isChecked())
            label = plain(a.text(), keep_dots=True)
            short = label.replace("Mute ", "") if label.startswith("Mute ") else label
            button.setText(short)
            button.setIcon(icons.icon(button.icon_name, themes.color("mute") if a.isChecked() else themes.color("text2"), 14))
            button.setAccessibleName(label)
            button.setAccessibleDescription(
                ("on" if a.isChecked() else "off") + (f", {a.shortcut().toString()}" if a.shortcut().toString() else "")
            )
            button.setVisible(a.isVisible())

    def focusable(self) -> list:
        order = self.tiles + self.mute_buttons + [r for r in self.rows if r is not self.quit_row]
        order.append(self.quit_row)
        return [item for item in order if item.isVisible() and item.isEnabled()]

    def popup_under(self, button) -> None:
        self.refresh()
        self.adjustSize()
        spot = button.mapToGlobal(QPoint(0, button.height() + 8))
        screen = button.screen().availableGeometry() if button.screen() is not None else None
        if screen is not None:
            spot.setX(max(screen.left() + 8, min(spot.x(), screen.right() - self.width() - 8)))
            spot.setY(max(screen.top() + 8, min(spot.y(), screen.bottom() - self.height() - 8)))
        self.move(spot)
        self.show()
        items = self.focusable()
        if items:
            items[0].setFocus(Qt.FocusReason.PopupFocusReason)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            items = self.focusable()
            if not items:
                return
            current = self.focusWidget()
            index = items.index(current) if current in items else -1
            step = 1 if key in (Qt.Key.Key_Down, Qt.Key.Key_Tab) else -1
            items[(index + step) % len(items)].setFocus(Qt.FocusReason.TabFocusReason)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.focusWidget()
            if isinstance(current, QAbstractButton):
                current.click()
                return
        super().keyPressEvent(event)
