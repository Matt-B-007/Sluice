# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings window (0.11.5; 0.11.7 redrawn in the ☰ panel's design: grouped rows, switches, an icon per section): everything that
is chosen once and then left alone, in six sections, opened by the ⚙ button beside the ☰ button in the top bar.

- Themes and skins: the skin (how things are shaped and drawn; a live picture of each, in the theme in use), the theme (the colours),
  the skin's own colours, reduce effects, the layout, and the desktop widgets' own skin and theme
- Audio: the audio buffer
- Startup and background: starting at login, what closing the window does, the applications menu entry
- Controllers: MIDI controllers and Stream Deck
- Updates: automatic updates, checking now, going back a version, rebuilding the audio engine, uninstalling
- Backup and reset (0.11.7): saving, importing and exporting your settings, earlier copies, their folders, resetting them all

Every control here is bound to one of the window's actions (``window.autostart_actions``, ``window.buffer_actions`` and the rest). The
action keeps the state and does the work, as before; this window only shows it and changes it, so nothing is done in two places."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import themes, ui_icons as icons
from .ui_base import plain
from .ui_panel import Switch

# 0.13.1: the House Standard's order: General, Appearance, Updates, Privacy, Sluice's own sections, Advanced, About & uninstall
SECTIONS = ("General", "Appearance", "Updates", "Privacy", "Audio", "Controllers", "Setup check", "Advanced", "About & uninstall")
SECTION_ICONS = ("power", "palette", "refresh", "eye", "wave", "sliders", "checklist", "save", "info")
OLD_SECTION_NAMES = {"Themes and skins": "Appearance", "Startup and background": "General", "Backup and reset": "Advanced"}
SETUP = "Setup check"


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settingsheading")
    return label


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


class _Bound:
    """A check box or radio button that shows an action's state and triggers the action when clicked."""

    def __init__(self, button: QAbstractButton, action: QAction, row=None, name=None) -> None:
        self.button, self.action, self.row, self.name = button, action, row, name
        button.clicked.connect(self._clicked)

    def _clicked(self) -> None:
        if self.button.isChecked() != self.action.isChecked() or not self.action.isCheckable():
            self.action.trigger()
        self.refresh()

    def refresh(self) -> None:
        self.button.blockSignals(True)
        if not isinstance(self.button, Switch):  # a switch's name is the label beside it
            self.button.setText(plain(self.action.text(), keep_dots=True))
        self.button.setChecked(self.action.isChecked())
        self.button.setEnabled(self.action.isEnabled())
        self.button.setVisible(self.action.isVisible())
        self.button.setToolTip(
            self.action.toolTip() if self.action.toolTip() != plain(self.action.text(), keep_dots=True) else ""
        )
        self.button.setAccessibleName(plain(self.action.text(), keep_dots=True))
        self.button.blockSignals(False)
        if self.name is not None:  # a switch row: the name is a label beside it
            self.name.setText(plain(self.action.text(), keep_dots=True))
        if self.row is not None:
            self.row.setVisible(self.action.isVisible())


class SkinCard(QPushButton):
    """A look as a picture in the colours of the theme in use; click it to use that look."""

    def __init__(self, skin_id: str) -> None:
        super().__init__()
        self.skin_id = skin_id
        self.setObjectName("lookcard")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{themes.SKINS[skin_id]} skin")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.picture = QLabel()
        self.picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.caption = QLabel(themes.SKINS[skin_id])
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
        cards = [c for c in (self.parentWidget().findChildren(SkinCard) if self.parentWidget() else []) if c.isVisible()]
        if self in cards:
            cards[(cards.index(self) + step) % len(cards)].setFocus(Qt.FocusReason.TabFocusReason)

    def show_preview(self, theme) -> None:
        from .ui_skins import BLURBS, draw_preview

        self.picture.setPixmap(draw_preview(self.skin_id, themes.skin_colors(theme, self.skin_id), self.devicePixelRatioF()))
        self.setToolTip(BLURBS.get(self.skin_id, ""))


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
        self.sections.setIconSize(QSize(18, 18))
        for name, icon in zip(SECTIONS, SECTION_ICONS):
            self.sections.addItem(name)
            self.sections.item(self.sections.count() - 1).setData(Qt.ItemDataRole.UserRole, icon)
        self.sections.setFixedWidth(240)
        self.pages = QStackedWidget()
        self.setup_results: list = []
        for name, build in zip(
            SECTIONS,
            (
                self._startup,
                self._appearance,
                self._updates,
                self._privacy,
                self._audio,
                self._controllers,
                self._setup,
                self._backup,
                self._about,
            ),
        ):
            page = QWidget()
            column = QVBoxLayout(page)
            column.setContentsMargins(28, 20, 28, 20)
            column.setSpacing(10)
            title = QLabel(name)
            title.setObjectName("settingstitle")
            column.addWidget(title)
            column.addSpacing(4)
            build(column)
            column.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.currentRowChanged.connect(lambda _row: self.isVisible() and self.refresh())
        self.sections.currentRowChanged.connect(
            lambda row: row == SECTIONS.index(SETUP) and not self.setup_results and self.check_setup()
        )
        self.sections.setCurrentRow(0)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        close.setDefault(True)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)
        foot = QHBoxLayout()
        self.version_note = QLabel()
        self.version_note.setObjectName("hint")
        foot.addWidget(self.version_note)
        foot.addStretch(1)
        foot.addWidget(close)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addLayout(body, 1)
        outer.addLayout(foot)
        self.resize(1000, 680)

    # ------------------------------------------------------------------ building the pages
    def _group(self, column: QVBoxLayout, heading: str = "", note: str = "") -> QVBoxLayout:
        """A rounded group of rows under a small heading (0.11.7), as in the ☰ panel."""
        if heading:
            column.addSpacing(6)
            column.addWidget(_heading(heading))
        if note:
            column.addWidget(_note(note))
        frame = QFrame()
        frame.setObjectName("settingsgroup")
        box = QVBoxLayout(frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        column.addWidget(frame)
        return box

    def _row(self, group: QVBoxLayout, name: str, control: QWidget = None, hint: str = "") -> tuple:
        """One row: a name (and a hint under it) on the left, a control on the right. Returns (row, name label)."""
        row = QFrame()
        row.setObjectName("settingsrow")
        row.setProperty("first", group.count() == 0)
        box = QHBoxLayout(row)
        box.setContentsMargins(16, 10, 16, 10)
        box.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(2)
        label = QLabel(name)
        label.setObjectName("rowname")
        label.setWordWrap(True)
        text.addWidget(label)
        if hint:
            under = QLabel(hint)
            under.setObjectName("rowhint")
            under.setWordWrap(True)
            text.addWidget(under)
        box.addLayout(text, 1)
        if control is not None:
            box.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
            label.setBuddy(control)
        row.setMinimumHeight(48)
        group.addWidget(row)
        return row, label

    def _bind(self, column, action: QAction, radio: QButtonGroup = None, hint: str = "") -> QAbstractButton:
        """A setting bound to its action: a switch in a row for an on/off one, a radio button in a row for a choice."""
        if radio is not None:
            button = QRadioButton()
            radio.addButton(button)
            if (
                isinstance(column, QVBoxLayout)
                and column.parentWidget() is not None
                and column.parentWidget().objectName() == "settingsgroup"
            ):
                row = QFrame()
                row.setObjectName("settingsrow")
                row.setProperty("first", column.count() == 0)
                box = QHBoxLayout(row)
                box.setContentsMargins(16, 8, 16, 8)
                box.addWidget(button)
                row.setMinimumHeight(44)
                column.addWidget(row)
                self.bound.append(_Bound(button, action, row))
            else:
                column.addWidget(button)
                self.bound.append(_Bound(button, action))
            return button
        button = Switch()
        row, name = self._row(
            column,
            plain(action.text(), keep_dots=True),
            button,
            hint or (action.toolTip() if action.toolTip() != plain(action.text(), keep_dots=True) else ""),
        )
        self.bound.append(_Bound(button, action, row, name))
        return button

    def _action_button(self, column, text: str, action_or_slot, tip: str = "", name: str = "", hint: str = "") -> QPushButton:
        """A button that does something: alone on a line, or (in a group) at the right of a row named ``name``."""
        button = QPushButton(text)
        button.setToolTip(tip)
        if isinstance(action_or_slot, QAction):
            button.clicked.connect(lambda _c=False, a=action_or_slot: a.trigger())
        else:
            button.clicked.connect(lambda _c=False, s=action_or_slot: s())
        if name:
            self._row(column, name, button, hint)
            return button
        row = QHBoxLayout()
        row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)
        return button

    def _appearance(self, column: QVBoxLayout) -> None:
        w = self.window_
        column.addWidget(_heading("Skin"))
        column.addWidget(
            _note(
                "How the window and the desktop widgets are shaped and drawn. Each picture is drawn in the theme you are using."
            )
        )
        grid = QGridLayout()
        grid.setSpacing(12)
        self.skin_cards = {}
        for index, skin_id in enumerate(themes.SKINS):
            card = SkinCard(skin_id)
            card.clicked.connect(lambda _c=False, skin_id=skin_id: self._choose_skin(skin_id))
            grid.addWidget(card, index // 2, index % 2)
            self.skin_cards[skin_id] = card
        holder = QHBoxLayout()
        holder.addLayout(grid)
        holder.addStretch(1)
        column.addLayout(holder)
        window = self._group(column, "Window")
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themepicker")
        icons.dropdown(self.theme_button)  # 0.12.2: a drawn chevron, not a typed ▾
        self.theme_button.setMenu(w.theme_menu)
        self.theme_button.setAccessibleName("Theme")
        self.theme_button.setMinimumWidth(200)
        self._row(window, "Theme", self.theme_button, "The colours, in any skin. Import, export or remove themes from its menu.")
        self._bind(window, w.skin_colors_action)
        self._bind(window, w.reduce_action)
        layout = self._group(column, "Layout")
        group = QButtonGroup(self)
        for action in w.layout_actions.values():
            self._bind(layout, action, group)
        self._levels(column)
        widgets = self._group(
            column,
            "Desktop widgets",
            "The widgets you keep on the desktop can have a skin and a theme of their "
            "own, for example Tile widgets with the window in Calm.",
        )
        self.widget_skin = QComboBox()
        self.widget_skin.setAccessibleName("Desktop widgets' skin")
        self.widget_skin.activated.connect(self._widget_skin_chosen)
        self.widget_theme = QComboBox()
        self.widget_theme.setAccessibleName("Desktop widgets' theme")
        self.widget_theme.activated.connect(self._widget_theme_chosen)
        for label, combo in (("Skin", self.widget_skin), ("Theme", self.widget_theme)):
            combo.setMinimumWidth(200)
            self._row(widgets, label, combo)

    def _levels(self, column: QVBoxLayout) -> None:
        """0.12.3: dB, percent or both."""
        group = self._group(
            column,
            "Show levels as",
            "Percent is the scale your desktop's volume slider uses: 100% is 0 dB "
            "and 50% is about -18 dB. You can type either into a level's number box (for example -12 or 50%).",
        )
        choice = QButtonGroup(self)
        for action in self.window_.units_actions.values():
            self._bind(group, action, choice)

    def _audio(self, column: QVBoxLayout) -> None:
        w = self.window_
        group = self._group(
            column,
            "Audio buffer",
            "How much sound Sluice handles at a time. A smaller buffer means less delay; a "
            "larger one uses less CPU and is less likely to drop out. It takes effect when Sluice starts again: Sluice offers to "
            "restart now.",
        )
        choice = QButtonGroup(self)
        for action in w.buffer_actions.values():
            self._bind(group, action, choice)
        # 0.12.4
        devices = self._group(
            column,
            "Recording devices for OBS",
            "A channel's own recording device, such as \u201cSluice "
            "(Game)\u201d, carries just that channel. With this on, an app channel's device follows its Broadcast "
            "fader and mute, so muting Broadcast mutes it in OBS too. A microphone's device always stays on, "
            "because voice chats such as Discord often use it.",
        )
        self._bind(devices, w.follow_action)
        self._bind(devices, w.devices_action)  # 0.12.6: one switch for every app channel (each can still turn its own off)
        play_to = self._group(
            column,
            "Where apps play in",
            "Each channel has a \u201cPlay to Sluice (\u2026)\u201d device that its apps play into. Sluice keeps them hidden, so OBS "
            "cannot record one by mistake (it is from before your faders) and apps\u2019 sound menus stay short; Sluice puts every "
            "app on its channel itself.",
        )
        self._bind(play_to, w.play_to_action)

    def _startup(self, column: QVBoxLayout) -> None:
        w = self.window_
        login = self._group(column, "When I log in")
        group = QButtonGroup(self)
        for action in w.autostart_actions.values():
            self._bind(login, action, group)
        closing = self._group(column, "When I close the window")
        group = QButtonGroup(self)
        for action in w.close_actions.values():
            self._bind(closing, action, group)
        self.no_tray = _note(w.no_tray_note.text())
        column.addWidget(self.no_tray)
        menu = self._group(column, "Applications menu")
        self._bind(menu, w.launcher_action)

    def _controllers(self, column: QVBoxLayout) -> None:
        # 0.12.2: the controllers page itself, here, instead of a button that opened another window
        self.controllers_box = QVBoxLayout()
        self.controllers_box.setSpacing(8)
        heading = QLabel("MIDI controllers and Stream Deck")
        heading.setObjectName("grouphead")
        self.controllers_box.addWidget(heading)
        self.controllers_box.addWidget(_note("Turn a knob or press a key to move a fader, mute a channel or your mic."))
        column.addLayout(self.controllers_box)
        self.controllers_panel = None
        self.controllers_missing = _note("Controllers are not available in this copy of Sluice.")
        column.addWidget(self.controllers_missing)

    def _updates(self, column: QVBoxLayout) -> None:
        w = self.window_
        # 0.13.1-beta.2: one box: how Sluice looks for new versions, which ones it takes, and the buttons
        group = self._group(
            column,
            "New versions",
            "Stable gets tested releases. Beta also gets test versions before they are released, to try new features first.",
        )
        self._bind(group, w.check_daily_action)
        self._bind(group, w.auto_update_action)
        choice = QButtonGroup(self)
        for action in w.channel_actions.values():
            self._bind(group, action, choice)
        self._action_button(group, "Check now", w.check_for_updates, name="Check for updates")
        self.rollback_button = self._action_button(group, "Go back", w.rollback_action, name="Go back to the previous version")
        if w.runs_from_download():  # 0.12.0: installed the old way, in the folder it was downloaded to
            where = self._group(column, "Where Sluice is installed")
            self.move_button = self._action_button(
                where,
                "Move",
                w.move_install,
                name="Move Sluice to its own folder",
                hint="Sluice runs from the folder you downloaded. Moving it puts it in ~/.local/share/sluice and deletes that "
                "folder; your settings stay.",
            )
        engine = self._group(column, "Audio engine")
        self.rebuild_button = self._action_button(
            engine,
            "Rebuild",
            w.rebuild_engine,
            name="Rebuild the audio engine",
            hint="Builds the Rust engine again from the copy that came with this Sluice.",
        )
        self.rebuild_hint = self.rebuild_button.parentWidget().findChildren(QLabel)[-1]

    # ------------------------------------------------------------------ the setup check (0.12.0)
    def _setup(self, column: QVBoxLayout) -> None:
        column.addWidget(
            _note(
                "What Sluice uses from your system: what each part is for, whether it is here, and the command that "
                "installs it. Sluice never installs anything itself: copy a command and run it in a terminal, then "
                "press Check again."
            )
        )
        self.setup_summary = QLabel()
        self.setup_summary.setObjectName("settingsheading")
        self.setup_summary.setWordWrap(True)
        column.addWidget(self.setup_summary)
        holder = QWidget()
        self.setup_column = QVBoxLayout(holder)
        self.setup_column.setContentsMargins(0, 0, 0, 0)
        self.setup_column.setSpacing(10)
        column.addWidget(holder)
        again = QHBoxLayout()
        self.setup_again = QPushButton("Check again")
        self.setup_again.setAccessibleName("Check the setup again")
        self.setup_again.clicked.connect(self.check_setup)
        again.addWidget(self.setup_again)
        again.addStretch(1)
        column.addLayout(again)

    def check_setup(self) -> list:
        """Look at every part again (the PulseAudio and JACK checks connect, so this takes a moment) and show the result."""
        from PySide6.QtWidgets import QApplication

        from . import setup_check

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.setup_results = setup_check.check_all()
        finally:
            QApplication.restoreOverrideCursor()
        self._show_setup(self.setup_results)
        return self.setup_results

    def _show_setup(self, results: list) -> None:
        from . import setup_check

        while self.setup_column.count():
            item = self.setup_column.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.setup_commands: dict = {}
        needed, optional = setup_check.summary(results)
        if needed:
            self.setup_summary.setText(f"Sluice needs {len(needed)} more part{'s' if len(needed) > 1 else ''} to play sound.")
        elif optional:
            self.setup_summary.setText(
                f"Everything Sluice needs is here. {len(optional)} optional part"
                f"{'s are' if len(optional) > 1 else ' is'} missing."
            )
        else:
            self.setup_summary.setText("Everything is here.")
        for heading, required in (("Needed", True), ("Optional", False)):
            frame = QFrame()
            frame.setObjectName("settingsgroup")
            box = QVBoxLayout(frame)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)
            head = _heading(heading)
            self.setup_column.addWidget(head)
            self.setup_column.addWidget(frame)
            for result in results:
                if result.part.required == required:
                    self._setup_row(box, result)
        # lay the new rows out now, not a frame later: a row with a command is taller, and a wrapped label needs two passes (one to
        # learn its width, one to take the height that width gives it)
        from PySide6.QtCore import QCoreApplication, QEvent

        for _ in range(2):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)

    def _setup_row(self, group: QVBoxLayout, result) -> None:
        if result.ok:
            text, name = "Installed", "setupok"
        elif not result.applies:
            text, name = "Not used here", "setupidle"
        elif result.ok is None:
            text, name = "–", "setupidle"
        else:
            text, name = "Missing", "setupneeded" if result.part.required else "setupmissing"
        status = QLabel(text)
        status.setObjectName(name)
        status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        reason = result.reason[:1].upper() + result.reason[1:].rstrip(".") + "." if result.reason and result.applies else ""
        hint = result.part.purpose + (f"\n{reason}" if reason else "")
        shown = status
        if result.ok:  # 0.12.2: a drawn tick beside "Installed", not a typed ✓
            shown = QWidget()
            pair = QHBoxLayout(shown)
            pair.setContentsMargins(0, 0, 0, 0)
            pair.setSpacing(6)
            tick = QLabel()
            tick.setPixmap(icons.icon("check", themes.color("live_fg"), 16).pixmap(QSize(16, 16), self.devicePixelRatioF()))
            pair.addStretch(1)
            pair.addWidget(tick)
            pair.addWidget(status)
        row, _label = self._row(group, result.part.name, shown, hint)
        status.setAccessibleName(f"{result.part.name}: {text}")
        if result.missing and result.command:
            # the command on its own line under the row's text (a wrapping label straight in the column, so the row grows with it
            # at any width), and Copy under it
            text_box = row.layout().itemAt(0).layout()
            command = QLabel(result.command)
            command.setObjectName("setupcommand")
            command.setWordWrap(True)
            command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            copy = QPushButton("Copy")
            copy.setAccessibleName(f"Copy the command for {result.part.name}")
            copy.clicked.connect(lambda _checked=False, c=result.command, b=copy: self._copy_command(c, b))
            text_box.addSpacing(4)
            text_box.addWidget(command)
            text_box.addWidget(copy, 0, Qt.AlignmentFlag.AlignLeft)
            self.setup_commands[result.part.key] = (command, copy)

    def _copy_command(self, command: str, button: QPushButton) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(command)
        button.setText("Copied")
        QTimer.singleShot(1500, lambda: button.setText("Copy"))

    def _privacy(self, column: QVBoxLayout) -> None:
        """0.13.1 (House Standard): what Sluice never collects, and where its reports and logs stay."""
        w = self.window_
        group = self._group(
            column,
            "What Sluice sends",
            "Nothing, by itself. There is no telemetry and no account. Sluice uses "
            "the internet only for updates: when you check for one, or if automatic updates are on (Updates).",
        )
        group.addWidget(
            _note(
                "Never collected: your audio, settings, logs or reports, the names of your devices, apps, channels or "
                "games, usage statistics, crash reports, or anything that identifies you or your computer."
            )
        )
        reports = self._group(
            column,
            "Bug reports",
            "A report stays on this computer until you send it yourself. Before saving, "
            "Sluice replaces your home folder, user name, computer name, network and hardware addresses, serial "
            "numbers, Steam account number and any token with placeholders. Device and app names stay in.",
        )
        self._action_button(reports, "Report…", w.report_action, name="Report a problem")
        self._action_button(reports, "Open…", w.open_log_folder, name="Open the log folder")

    def _about(self, column: QVBoxLayout) -> None:
        """0.13.1 (House Standard): about Sluice, then the red Uninstall box, always last."""
        from . import __version__

        w = self.window_
        about = self._group(
            column,
            f"Sluice {__version__}",
            "A virtual audio mixer for PipeWire, for streaming and gaming. Free software under the GNU GPL, version 3 or later.",
        )
        self._action_button(about, "Open", w.show_about, name="About Sluice")
        self._action_button(about, "Open", w.show_whats_new, name="What's new in this version")
        remove = self._group(column, "Uninstall")
        remove.parentWidget().setProperty("danger", True)  # the red box (House Standard: always last)
        button = self._action_button(
            remove,
            "Uninstall…",
            w.uninstall_action,
            name="Uninstall Sluice",
            hint="Removes Sluice, its virtual devices and its launcher. Your settings stay unless you "
            "choose otherwise. You are asked first.",
        )
        button.setObjectName("danger")

    def _backup(self, column: QVBoxLayout) -> None:
        w = self.window_
        group = self._group(
            column,
            "Your settings",
            "Sluice saves your settings by itself; these are for keeping a copy or moving them to another computer.",
        )
        self._action_button(group, "Save", w.save_settings_action, name="Save settings now", hint="Ctrl+S")
        self._action_button(group, "Import…", w.import_action, name="Import settings")
        self._action_button(group, "Export…", w.export_action, name="Export settings")
        restore = QPushButton("Choose…")
        restore.setMenu(w.restore_menu)
        restore.setAccessibleName("Restore earlier settings")
        self._row(group, "Restore earlier settings", restore, "Copies Sluice kept before big changes.")
        folders = QPushButton("Open…")
        folders.setMenu(w.folders_menu)
        folders.setAccessibleName("Open folder")
        self._row(group, "Open folder", folders, "Settings, logs and themes.")
        reset = self._group(column, "Start again")
        self._action_button(
            reset,
            "Reset…",
            w.reset_settings,
            name="Reset all settings to the defaults",
            hint="Every setting back to how it was when Sluice was new. Your settings are backed up first.",
        )

    # ------------------------------------------------------------------ keeping it up to date
    def _choose_skin(self, skin_id: str) -> None:
        self.window_.choose_skin(skin_id)
        self.refresh()

    def _widget_skin_chosen(self, index: int) -> None:
        self.window_.set_widget_dress(skin=self.widget_skin.itemData(index) or "")

    def _widget_theme_chosen(self, index: int) -> None:
        self.window_.set_widget_dress(theme=self.widget_theme.itemData(index) or "")

    def _fill_widget_choices(self) -> None:
        """The skins and themes the desktop widgets can have, "Same as the window" first, with the one in use chosen."""
        w = self.window_
        mixer = w.engine.mixer
        skins = [("Same as the window", "")] + [(name, skin_id) for skin_id, name in themes.SKINS.items()]
        choices = [("Same as the window", "")] + [(t.name, t.id) for t in themes.BUILT_IN.values()]
        choices.append((themes.SYSTEM_LABEL, themes.SYSTEM))
        choices += [(t.name, t.id) for t in themes.custom_themes(w._themes_folder())]
        for combo, items, chosen in (
            (self.widget_skin, skins, mixer.widget_skin),
            (self.widget_theme, choices, mixer.widget_theme),
        ):
            combo.blockSignals(True)
            combo.clear()
            for label, data in items:
                combo.addItem(label, data)
            index = combo.findData(chosen)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def refresh(self) -> None:
        """Show the real state of every setting (the window's own refreshers bring the actions up to date first)."""
        w = self.window_
        w._refresh_settings_menu()
        w._refresh_buffer_menu()
        w._refresh_view_menu()
        w._show_layout_choice()
        theme = w.current_theme()
        skin = themes.valid_skin(w.engine.mixer.skin)
        for skin_id, card in self.skin_cards.items():
            card.blockSignals(True)
            card.setChecked(skin_id == skin)
            card.blockSignals(False)
            card.show_preview(theme)
        self.theme_button.setText(theme.name)
        self._fill_widget_choices()
        for item in self.bound:
            item.refresh()
        self.no_tray.setVisible(w.no_tray_note.isVisible())
        rollback = w.rollback_action
        self.rollback_button.setEnabled(rollback.isEnabled())
        self.rollback_button.setToolTip(plain(rollback.text()))
        controls = getattr(w, "controls", None)
        has_controls = controls is not None and hasattr(controls, "hub")
        if has_controls and self.controllers_panel is None:
            from .ui_controllers import ControllersPanel

            self.controllers_panel = ControllersPanel(controls, self)
            self.controllers_box.addWidget(self.controllers_panel)
        self.controllers_missing.setVisible(not has_controls)
        for index in range(self.sections.count()):
            item = self.sections.item(index)
            selected = index == self.sections.currentRow()
            item.setIcon(
                icons.icon(item.data(Qt.ItemDataRole.UserRole), themes.color("accent_text" if selected else "text2"), 18)
            )
        from . import __version__

        self.version_note.setText(f"Sluice {__version__}")
        offer = w.engine_rebuild_state()
        self.rebuild_button.setEnabled(offer[0])
        self.rebuild_hint.setText(offer[1])

    def open_at(self, section: str = "") -> None:
        section = OLD_SECTION_NAMES.get(section, section)
        if section in SECTIONS:
            self.sections.setCurrentRow(SECTIONS.index(section))
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()
