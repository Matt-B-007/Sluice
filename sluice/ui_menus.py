# SPDX-License-Identifier: GPL-3.0-or-later
"""The menus of the main window, and the menus' refreshers.

The window's actions, grouped as File, Mixer, Window, Settings and Help. They are shown by the ☰ panel (``ui_panel``) and the Settings
window (``ui_settings``), which is bound to the same actions, so each setting is done in one place. 0.12.0: there is no menu bar
any more (it was the Original skin's); the groups are kept only to hold the actions and their shortcuts.

Part of the main window, split out of ``ui.py``: ``MainWindow`` inherits this class, so every method here is still a method of the window."""
from __future__ import annotations

import logging
from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QCheckBox, QLabel, QMenu, QMessageBox, QWidgetAction

from . import ui_dialog
from . import themes
from .model import BUFFER_CHOICES, MONITOR, STREAM
from .ui_base import DISCORD_URL, ISSUES_URL, PROJECT_URL, default_size

log = logging.getLogger("sluice.ui")


MENU_HEADING = "menuheading"


def heading(menu: QMenu, text: str) -> QAction:
    """A small heading over a group of menu items (0.11.6). Qt's own section headings show only as a line with this style sheet,
    which left a blank band at the top of a menu; this one shows its words. It cannot be chosen."""
    label = QLabel(text.upper())
    label.setObjectName(MENU_HEADING)
    action = QWidgetAction(menu)
    action.setDefaultWidget(label)
    action.setEnabled(False)
    action.setText(text)
    action.setProperty("heading", True)
    if any(not a.property("heading") for a in menu.actions()):
        label.setProperty("first", False)
    else:
        label.setProperty("first", True)
    menu.addAction(action)
    return action


SHORTCUT_GAP = 24  # pixels at least between an item's name and its shortcut, in every menu


def keep_shortcut_gap(menu: QMenu) -> None:
    """Make ``menu`` wide enough that every shortcut sits at least SHORTCUT_GAP from the longest name (0.11.6). Qt puts the names
    on the left and the shortcuts on the right, and with a style sheet it can leave only a few pixels between them in a narrow menu
    (it did beside Settings…); a wider menu moves the shortcuts away."""
    metrics = menu.fontMetrics()
    names = [metrics.horizontalAdvance(plain(a.text()) + "\u2026" * a.text().endswith("\u2026")) for a in menu.actions()
             if a.isVisible() and not a.isSeparator() and not a.property("heading")]
    keys = [metrics.horizontalAdvance(a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)) for a in menu.actions()
            if a.isVisible() and not a.shortcut().isEmpty()]
    if not names or not keys:
        return
    # the item's padding on both sides, room for a tick or a submenu arrow, the menu's own padding and border
    menu.setMinimumWidth(max(names) + SHORTCUT_GAP + max(keys) + 2 * 24 + 2 * 22 + 2 * 9)


def watch_shortcut_gaps(menu: QMenu) -> None:
    keep_shortcut_gap(menu)  # now, and again whenever it opens (items can change)
    menu.aboutToShow.connect(lambda menu=menu: keep_shortcut_gap(menu))
    for action in menu.actions():
        if action.menu() is not None:
            watch_shortcut_gaps(action.menu())


from .ui_base import plain  # noqa: E402,F401  (here too, for the callers that import it from the menus)


class MenusMixin:
    def _action(self, menu: QMenu, text: str, slot, shortcut=None, checkable: bool = False) -> QAction:
        action = menu.addAction(text)
        action.setCheckable(checkable)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
            self.addAction(action)  # the menu bar is out of sight (the menu button holds the menus): shortcuts belong to the window
        action.triggered.connect(lambda _checked=False: slot())
        return action

    def _build_menus(self) -> None:
        """The menus (0.11.6): each split into small groups under a heading, in the order other desktop apps use. A "…" ends only
        an item that opens a window or asks something; toggles, choices, links and submenus have none. Each thing lives in exactly
        one group (tests/test_crash_trail_and_menus.py checks it). The groups are never shown as menus themselves (0.12.0)."""
        self.action_groups: list = []

        def holder(title: str) -> QMenu:
            menu = QMenu(title, self)
            self.action_groups.append(menu)
            return menu

        # File: your settings and files, and Quit.
        file_menu = holder("&File")
        self.save_settings_action = self._action(file_menu, "&Save settings", self.save_settings, "Ctrl+S")
        file_menu.addSeparator()
        self.import_action = self._action(file_menu, "&Import settings\u2026", self.import_settings)
        self.export_action = self._action(file_menu, "&Export settings\u2026", self.export_settings)
        self.restore_menu = file_menu.addMenu("&Restore earlier settings")
        self.restore_menu.aboutToShow.connect(self._fill_restore_menu)
        self._action(file_menu, "Reset all se&ttings to the defaults\u2026", self.reset_settings)
        file_menu.addSeparator()
        self.folders_menu = folders = file_menu.addMenu("Open &folder")
        folders.addAction("&Settings", self.open_settings_folder)
        folders.addAction("&Logs", self.open_log_folder)
        folders.addAction("&Themes", self.open_theme_folder)
        file_menu.addSeparator()
        self.quit_action = self._action(file_menu, "&Quit", self.quit_app, "Ctrl+Q")
        file_menu.aboutToShow.connect(self._refresh_file_menu)

        # Mixer: what you do while mixing, in three groups.
        mixer_menu = holder("&Mixer")
        heading(mixer_menu, "Channels")
        self.add_channel_action = self._action(mixer_menu, "&Add channel\u2026", self.add_channel, "Ctrl+N")
        self.refresh_action = self._action(mixer_menu, "Re&fresh devices and apps", self.refresh_now, "F5")
        heading(mixer_menu, "Mixes")
        self.recording_action = self._action(mixer_menu, "&Recording mix (a third mix)", self.toggle_recording_mix, checkable=True)
        self.own_devices_action = self._action(mixer_menu, "Recording &devices for OBS\u2026", self.show_own_devices)
        heading(mixer_menu, "Quick mutes")
        self.mic_action = self._action(mixer_menu, "Mute my &microphone", self.toggle_mic_mute, "Ctrl+M", checkable=True)
        self.mute_actions = {}
        used = {"a", "f", "r", "d", "m", "h"}  # the Alt-key letters the other items take
        for mix in self.engine.mixer.mixes:
            shortcut = {MONITOR: "Ctrl+Shift+L", STREAM: "Ctrl+Shift+B"}.get(mix.id, "")
            letter = next((c for c in mix.label if c.isalnum() and c.lower() not in used), "")  # first letter of the name nobody has yet
            used.add(letter.lower())
            text = f"Mute {mix.label.replace(letter, '&' + letter, 1)}" if letter else f"Mute {mix.label}"
            self.mute_actions[mix.id] = self._action(mixer_menu, text, partial(self.toggle_mix_mute, mix.id),
                                                     shortcut or None, checkable=True)
        # H for hear: kept away from Ctrl+Shift+B (Mute Broadcast), which does nearly the opposite
        self.hear_action = self._action(mixer_menu, "&Hear Broadcast", self.toggle_hear_broadcast, "Ctrl+H", checkable=True)
        mixer_menu.aboutToShow.connect(self._refresh_mixer_menu)

        # Window: how the window is laid out and drawn, the desktop widgets, and the window itself. (Columns and Rows are also
        # in the top bar; the skin, theme and effects switches are shown only in Settings.)
        view_menu = holder("&Window")
        heading(view_menu, "Layout")
        self.layout_actions = {}
        layout_group = QActionGroup(self)
        for key, text, keys in (("columns", "&Columns (a card for each channel)", "Ctrl+1"),
                                ("rows", "&Rows (a line for each channel)", "Ctrl+2")):
            action = self._action(view_menu, text, partial(self.set_layout, key), keys, checkable=True)
            action.setActionGroup(layout_group)
            self.layout_actions[key] = action
        heading(view_menu, "Themes and skins")
        self.skin_menu = view_menu.addMenu("S&kin")
        self.skin_menu.aboutToShow.connect(self._fill_skin_menu)
        self.theme_menu = view_menu.addMenu("&Theme")
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        self.skin_colors_action = self._action(view_menu, "Skin's own colo&urs on Dark and Light",
                                               lambda: self.set_skin_colors(self.skin_colors_action.isChecked()), checkable=True)
        self.skin_colors_action.setToolTip("Nexus's deep blue and cyan, and Tile's graphite and white keys, on the Dark and Light themes. "
                                           "Every other theme always keeps its own colours. Off: Dark and Light keep theirs too.")
        self.nexus_section = self.reduce_action = None
        self.reduce_action = self._action(view_menu, "Re&duce effects", lambda: self.set_reduce_effects(self.reduce_action.isChecked()),
                                          checkable=True)
        self.nexus_section = self.reduce_action  # (0.11.5 had a Nexus heading here; the item shows only in Nexus)
        self.see_through_action = self._action(view_menu, "S&ee-through window (Glass on KDE Plasma)",
                                               lambda: self.set_see_through(self.see_through_action.isChecked()), checkable=True)
        self.see_through_action.setToolTip("Your wallpaper shows through the window, blurred by KWin. Takes effect the next time "
                                           "Sluice starts. Off, or on other desktops: Sluice paints a soft backdrop behind the panes.")
        self.reduce_action.setToolTip("For slow or busy computers: the Nexus rings stop shimmering and the cards do not glow")
        heading(view_menu, "Desktop")
        self.widgets_menu = view_menu.addMenu("Desktop wid&gets")
        self.widgets_menu.setToolTipsVisible(True)
        self.widgets_menu.aboutToShow.connect(self._fill_widgets_menu)
        self.widgets_toggle_action = self._action(view_menu, "Show or hide &my widgets", self.toggle_my_widgets, "Ctrl+Shift+W")
        self.widgets_toggle_action.setToolTip("Closes the desktop widgets that are open, or opens again the ones you had")
        heading(view_menu, "Window")
        self.fullscreen_action = self._action(view_menu, "&Full screen", self.toggle_fullscreen, "F11", checkable=True)
        self.reset_size_action = self._action(view_menu, "Reset &window size", self.reset_window_size, "Ctrl+0")
        self.hide_action = self._action(view_menu, "&Hide to tray", self.hide_to_tray, "Ctrl+W")
        view_menu.aboutToShow.connect(self._refresh_view_menu)

        # Settings: the same groups as the Settings window, which shows them.
        self.settings_menu = settings_menu = holder("&Settings")
        heading(settings_menu, "Startup and background")
        background = settings_menu.addMenu("&Running in the background")
        heading(background, "When I log in")
        group = QActionGroup(self)
        self.autostart_actions = {}
        for key, text in (("off", "Do not start automatically"), ("window", "Start with the window open"),
                          ("minimized", "Start minimized")):  # the last label says where it goes: see _refresh_background_menu
            action = background.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.triggered.connect(lambda _c=False, key=key: self.set_autostart(key))
            self.autostart_actions[key] = action
        heading(background, "When I close the window")
        close_group = QActionGroup(self)
        self.close_actions = {}
        for key, text in (("quit", "Quit Sluice"), ("minimize", "Keep running in the taskbar"),
                          ("tray", "Keep running in the tray")):
            action = background.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(close_group)
            action.triggered.connect(lambda _c=False, key=key: self.set_close_action(key))
            self.close_actions[key] = action
        background.addSeparator()
        self.no_tray_note = background.addAction("This desktop has no system tray, so \u201ctray\u201d falls back to the taskbar.")
        self.no_tray_note.setEnabled(False)
        background.aboutToShow.connect(self._refresh_background_menu)
        self.background_menu = background
        self.launcher_action = self._action(settings_menu, "Add Sluice to the &applications menu", self.toggle_launcher, checkable=True)
        heading(settings_menu, "Audio")
        buffer_menu = settings_menu.addMenu("Audio &buffer")
        self.buffer_actions = {}
        labels = {256: "Smallest (256 frames): lowest delay, most CPU", 512: "Small (512 frames): the default",
                  1024: "Large (1024 frames): less CPU", 2048: "Largest (2048 frames): least CPU, most delay"}
        for frames in BUFFER_CHOICES:
            self.buffer_actions[frames] = self._action(buffer_menu, labels[frames], partial(self.set_buffer, frames), checkable=True)
        buffer_menu.aboutToShow.connect(self._refresh_buffer_menu)
        self.controllers_heading = heading(settings_menu, "Controllers")
        self.controllers_heading.setVisible(False)  # until attach_controls() puts its item under it
        # "MIDI controllers and Stream Deck…" is put here by attach_controls(), in front of the next heading.
        self.controllers_separator = heading(settings_menu, "Updates")
        self.auto_update_action = self._action(settings_menu, "&Update automatically when a new version is found",
                                               self.toggle_auto_update, checkable=True)
        self._action(settings_menu, "&Check for updates\u2026", self.check_for_updates)
        self.rollback_action = self._action(settings_menu, "&Go back to the previous version\u2026", self.rollback_update)
        # 0.12.2: which versions to look for (a list of choices, like Audio buffer)
        channel_menu = settings_menu.addMenu("Which &versions")
        self.channel_actions = {
            "stable": self._action(channel_menu, "Stable: tested releases (recommended)",
                                   partial(self.set_update_channel, "stable"), checkable=True),
            "beta": self._action(channel_menu, "Beta: new features first, may have rough edges",
                                 partial(self.set_update_channel, "beta"), checkable=True),
        }
        channel_menu.aboutToShow.connect(self._refresh_settings_menu)
        settings_menu.aboutToShow.connect(self._refresh_settings_menu)

        # Help: learning it, when something is wrong, the community, and about.
        self.help_menu = holder("&Help")
        self.help_menu.setToolTipsVisible(True)
        heading(self.help_menu, "Learn")
        self.shortcuts_action = self._action(self.help_menu, "&Keyboard shortcuts", self.show_shortcuts, "F1")
        self.whats_new_action = self.help_menu.addAction("&What's new in this version", self.show_whats_new)
        heading(self.help_menu, "Something wrong")
        self.glitch_action = self._action(self.help_menu, "I heard a &glitch", self.mark_glitch, "Ctrl+Shift+G")
        self.report_action = report_action = self.help_menu.addAction("Save bug &report\u2026", self.save_report)
        report_action.setToolTip("Something wrong, or something looks wrong? Save this file and send it: it lists the window size, how the "
                                 "window was arranged and where each part is, as well as the audio setup.")
        self.problem_action = self.help_menu.addAction("Report a &problem", partial(self.open_link, ISSUES_URL))
        heading(self.help_menu, "Community")
        self.discord_action = self.help_menu.addAction("Join the &Discord", partial(self.open_link, DISCORD_URL))
        self.github_action = self.help_menu.addAction("Project page on Git&Hub", partial(self.open_link, PROJECT_URL))
        heading(self.help_menu, "About")
        self.about_action = self.help_menu.addAction("&About Sluice", self.show_about)
        self.help_menu.addSeparator()  # kept apart, so it is not clicked by mistake
        self.uninstall_action = self.help_menu.addAction("&Uninstall Sluice\u2026", self.uninstall_app)

        self.open_settings_action = self._action(file_menu, "Setti&ngs\u2026", self.open_settings, "Ctrl+,")
        for menu in self.action_groups:
            watch_shortcut_gaps(menu)

    def toggle_my_widgets(self) -> None:
        """Ctrl+Shift+W: put the open desktop widgets away (remembered with the settings, so this survives a restart or an update),
        or bring the same ones back where they were."""
        desktop, mixer = self.desktop, self.engine.mixer
        if desktop.open_widgets:
            mixer.hidden_widgets = [dict(spec) for spec in mixer.desktop_widgets]
            desktop.close_all(forget=True)
            self.say("Desktop widgets put away. Ctrl+Shift+W brings them back.")
            return
        specs, mixer.hidden_widgets = list(mixer.hidden_widgets), []
        if not specs:
            self.say("No desktop widgets to bring back. Choose some in View > Desktop widgets.")
            return
        for spec in specs:
            desktop.reopen(spec)

    def show_panel(self) -> None:
        """The ☰ button: the panel (0.11.7), built once from the actions."""
        from .ui_panel import MenuPanel

        if getattr(self, "menu_panel", None) is None:
            self.menu_panel = MenuPanel(self)
        self.menu_panel.popup_under(self.menu_button)

    def open_settings(self, section: str = "") -> None:
        """The Settings window (one, kept): Appearance, Audio, Startup and background, Controllers and Updates."""
        from .ui_settings import SettingsWindow

        if getattr(self, "settings_window", None) is None:
            self.settings_window = SettingsWindow(self)
        self.settings_window.open_at(section)

    def _refresh_view_menu(self) -> None:
        self.fullscreen_action.setChecked(self.isFullScreen())
        self.see_through_action.setChecked(self.engine.mixer.see_through)
        from . import desktop_place
        self.see_through_action.setVisible(desktop_place.kde() and themes.valid_skin(self.engine.mixer.skin) == "glass")
        self.reduce_action.setChecked(self.engine.mixer.reduce_effects)
        self.skin_colors_action.setChecked(self.engine.mixer.skin_colors)
        self._show_skin_items()

    def _fill_widgets_menu(self) -> None:
        """Small windows to leave on the desktop: tick one to show it, untick to close it."""
        menu = self.widgets_menu
        menu.clear()
        items = [("Microphone mute button", "mic", None, None, "A round button: click it to mute or unmute your microphone")]
        for mix in self.engine.mixer.mixes:
            items.append((f"{mix.label} volume dial", "dial", mix.id, None,
                          f"A dial for the {mix.label} main level: scroll to change it, click to mute"))
        items.append(("Channel list", "strip", None, None, "Every channel on one line, in a small window"))
        self._widget_items(menu, items)
        menu.addSeparator()  # 0.11.5: one mix or one channel, with its sliders
        items = [(f"{mix.label} mix", "mix", mix.id, None, f"The {mix.label} mix with its slider, Mute and the Limiter")
                 for mix in self.engine.mixer.mixes]
        self._widget_items(menu, items)
        channels = menu.addMenu("Channels")
        channels.setToolTipsVisible(True)
        self._widget_items(channels, [(channel.label, "channel", None, channel.id,
                                       f"{channel.label} with a slider and a mute button for each mix") for channel in self.engine.mixer.channels])
        menu.addSeparator()
        close_all = menu.addAction("Close all widgets", lambda: self.desktop.close_all(forget=True))
        close_all.setEnabled(bool(self.desktop.open_widgets))

    def _widget_items(self, menu, items) -> None:
        for text, kind, mix, channel, tip in items:
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(self.desktop.is_open(kind, mix, channel))
            action.setToolTip(tip)
            action.triggered.connect(lambda _c=False, kind=kind, mix=mix, channel=channel: self._toggle_desktop_widget(kind, mix, channel))

    def _toggle_desktop_widget(self, kind: str, mix, channel=None) -> None:
        was_open = self.desktop.is_open(kind, mix, channel)
        self.desktop.toggle(kind, mix, channel)
        if not was_open and not self.desktop.is_open(kind, mix, channel):
            self.say("That is as many widgets as Sluice keeps. Close one first.")

    def _show_skin_items(self) -> None:
        """The View items that only mean something in some skins are shown only there (Reduce effects: Nexus and, 0.11.7, Glass)."""
        self.reduce_action.setVisible(themes.current_skin() in ("nexus", "glass"))
        self.skin_colors_action.setVisible(themes.current_skin() in ("nexus", "tile"))

    def uninstall_app(self) -> None:
        """Two ways to remove Sluice, each showing exactly what it removes; then Sluice closes and a separate process does it."""
        import subprocess

        from . import uninstall

        if "Demo" in self.engine.io.label:
            self.say("Demo mode changes nothing, so there is nothing to uninstall here.")
            return
        keep_plan = uninstall.plan(keep_settings=True)
        all_plan = uninstall.plan(keep_settings=False, remove_git=True)

        def listing(result) -> str:
            return uninstall.describe(result).replace("Sluice will remove:", "This will remove:")

        box = ui_dialog.Message(self)
        box.setWindowTitle("Uninstall Sluice")
        box.setText("How much of Sluice should be removed?")
        box.setInformativeText(
            "Uninstall, keep my settings\n" + listing(keep_plan) +
            "\n\nRemove everything\n" + listing(all_plan).replace("\n  (nothing: it is not installed here)", "") +
            "\n\nBoth close Sluice first and remove these a moment later, then check that nothing was missed. "
            + " ".join(uninstall.STAYS))
        caches = QCheckBox("Also clear download caches (pip and cargo; other programs use them too)")
        caches.setToolTip("Clears ~/.cache/pip and ~/.cargo/registry. Programs that use them just download again when they need to.")
        box.setCheckBox(caches)
        keep_button = box.addButton("Uninstall, keep my settings", QMessageBox.ButtonRole.AcceptRole)
        everything_button = box.addButton("Remove everything", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (keep_button, everything_button):
            return
        keep = clicked is keep_button
        remove_git = False
        if not keep and all_plan.git_folder:
            answer = ui_dialog.question(
                self, "Delete the git folder?",
                "The Sluice folder is a git clone. Deleting it also deletes any changes in it that you have not committed "
                "or pushed.\n\nDelete it too?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            remove_git = answer == QMessageBox.StandardButton.Yes
        command = uninstall.command_for_gui(keep, clear_caches=caches.isChecked(), remove_git=remove_git)
        script = ('sleep 4; out=$("$@" 2>&1); '
                  'command -v notify-send >/dev/null 2>&1 && notify-send "Sluice uninstall" "$out"; exit 0')
        try:
            # a few seconds' wait lets this process finish closing (it holds the single-copy lock until then)
            subprocess.Popen(["sh", "-c", script, "sluice-uninstall", *command], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            ui_dialog.warning(self, "Uninstall Sluice", f"Could not start the uninstall: {exc}\nRun this in a terminal instead: sluice --uninstall")
            return
        self.quit_app()

    def open_link(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            ui_dialog.information(self, "Open link", f"Sluice could not open your browser. The address is:\n\n{url}")

    def _refresh_mixer_menu(self) -> None:
        self.hear_action.setChecked(self.engine.hear_broadcast)
        self.mic_action.setChecked(self.engine.mic_muted)
        self.recording_action.setChecked(self.engine.mixer.has_recording_mix)
        for mix_id, action in self.mute_actions.items():
            action.setChecked(self.engine.mixer.mix(mix_id).mute)

    def _refresh_settings_menu(self) -> None:
        self._refresh_file_menu()
        self.auto_update_action.setChecked(self.engine.mixer.auto_update)
        for name, action in getattr(self, "channel_actions", {}).items():
            action.setChecked(self.engine.mixer.update_channel == name)
        self._refresh_update_menu()

    # ------------------------------------------------------------------ what the menu items do
    def toggle_recording_mix(self) -> None:
        mixer = self.engine.mixer
        turn_on = not mixer.has_recording_mix
        text = ("Add a third mix, \u201cRecording\u201d: a second virtual microphone, \u201cSluice (Recording)\u201d, with its own "
                "faders and mutes, so a recorder can get a different blend from the one your audience hears."
                if turn_on else "Remove the Recording mix and its virtual microphone.")
        ask = ui_dialog.Message(self)
        ask.setWindowTitle("Recording mix")
        ask.setText(text + "\n\nSluice has to restart to do this. Your settings are saved first.")
        restart = ask.addButton("Restart now", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        self.recording_action.setChecked(mixer.has_recording_mix)
        if ask.clickedButton() is not restart:
            return
        mixer.set_recording_mix(turn_on)
        from . import reconnect

        self.shutdown()  # saves the settings
        reconnect.restart_self(show_window=True)

    def toggle_mic_mute(self) -> None:
        self.engine.set_mic_muted(not self.engine.mic_muted)  # from the real state, like the other toggles
        self._show_mic_state()
        self._refresh_tray_icon()
        self._sync_tray_timer()
        self.say("Your microphone is muted everywhere, including Sluice (Mic)." if self.engine.mic_muted
                 else "Your microphone is live.")

    def _show_mic_state(self) -> None:
        for strip in self.strips:
            strip.show_mic_state()

    def toggle_hear_broadcast(self) -> None:
        on = not self.engine.hear_broadcast  # from the real state, so a stale tick mark can never invert it
        self.engine.set_hear_broadcast(on)
        self.sync_from_model()
        self.say("Your output now plays the Broadcast mix: this is what your audience hears." if on
                 else "Your output is back on the Listen mix.")

    def toggle_mix_mute(self, mix_id: str) -> None:
        mix = self.engine.mixer.mix(mix_id)
        self.engine.set_master_mute(mix_id, not mix.mute)
        self.sync_from_model()
        self.say(f"{mix.label} is {'muted' if mix.mute else 'on'}.")

    def _refresh_buffer_menu(self) -> None:
        for frames, action in self.buffer_actions.items():
            action.setChecked(frames == self.engine.mixer.buffer_frames)

    def set_buffer(self, frames: int, ask: bool = True) -> None:
        """Save the buffer size. PipeWire fixes it when Sluice connects, so it takes effect at a restart: offer one now (0.12.1)."""
        old = self.engine.mixer.buffer_frames
        self.engine.mixer.buffer_frames = frames
        running = self.engine.io.blocksize
        if frames != old:
            log.info("audio buffer set to %s frames (running: %s; used from the next start)", frames, running)
        self._refresh_buffer_menu()
        self._show_perf()
        if not self.engine.buffer_pending():
            self.say(f"Audio buffer: {frames} frames.")
            return
        if ask and self.config_file is not None:
            box = ui_dialog.Message(self)
            box.setWindowTitle("Audio buffer")
            box.setText(f"Sluice runs at {running} frames now. {frames} frames takes effect when Sluice starts again.")
            box.setInformativeText("Restart now? The sound stops for a moment, then everything comes back as it was.")
            now = box.addButton("Restart now", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("At the next start", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is now:
                self.restart_for_buffer()
                return
        self.say(f"Audio buffer set to {frames} frames: used the next time Sluice starts (running now: {running}).")

    def restart_for_buffer(self) -> None:
        from . import reconnect

        self.shutdown()  # saves the settings, stops the audio
        reconnect.restart_self(show_window=True)

    def show_own_devices(self) -> None:
        from .ui_channel import OwnDevicesDialog  # here, not at the top: the window imports this module

        OwnDevicesDialog(self.engine, self).exec()

    def refresh_now(self) -> None:
        self.engine.refresh_devices()
        self.repopulate_devices()
        self.refresh_sources()
        self.say("Devices and apps refreshed.")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def reset_window_size(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        self.resize(*default_size(self._screen_area()))

    def shortcut_rows(self) -> list:
        """[(keys, what it does)] taken from the menu items themselves, so this list can never disagree with the menus."""
        rows = []
        for action in self.actions():
            keys = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if keys:
                rows.append((keys, plain(action.text())))
        return rows

    def show_shortcuts(self) -> None:
        rows = self.shortcut_rows()
        table = "".join(f"<tr><td><b>{key}</b>&nbsp;&nbsp;&nbsp;</td><td>{what}</td></tr>" for key, what in rows)
        ui_dialog.information(self, "Keyboard shortcuts", f"<table>{table}</table><br>"
                                "Faders: scroll the mouse wheel over one, or use the arrow keys when it is selected.<br>"
                                "For buttons and knobs outside the app, see <b>Settings > Controllers</b>.")

