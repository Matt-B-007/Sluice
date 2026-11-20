# SPDX-License-Identifier: GPL-3.0-or-later
"""The menu bar and the Settings menu of the main window, and the menus' refreshers.

Part of the main window, split out of ``ui.py``: ``MainWindow`` inherits this class, so every method here is still a method of the window."""
from __future__ import annotations

import logging
from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QCheckBox, QMenu, QMessageBox

from . import __version__, themes
from .model import BUFFER_CHOICES, MONITOR, STREAM
from .ui_constants import DEFAULT_SIZE, DISCORD_URL, ISSUES_URL, PROJECT_URL

log = logging.getLogger("sluice.ui")


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
        """The menus, in the order other desktop apps use. A "…" ends only an item that opens a dialog asking for something;
        toggles and choices have none. Each thing lives in exactly one menu (tests/test_0103.py checks it)."""
        bar = self.menuBar()
        # File: your settings and files, and Quit.
        file_menu = bar.addMenu("&File")
        self._action(file_menu, "&Save settings", self.save_settings, QKeySequence.StandardKey.Save)
        file_menu.addSeparator()
        self._action(file_menu, "&Import settings\u2026", self.import_settings)
        self._action(file_menu, "&Export settings\u2026", self.export_settings)
        self.restore_menu = file_menu.addMenu("&Restore earlier settings")
        self.restore_menu.aboutToShow.connect(self._fill_restore_menu)
        file_menu.addSeparator()
        folders = file_menu.addMenu("Open &folder")
        folders.addAction("&Settings", self.open_settings_folder)
        folders.addAction("&Logs", self.open_log_folder)
        folders.addAction("&Themes", self.open_theme_folder)
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", self.quit_app, QKeySequence.StandardKey.Quit)

        # Mixer: what you do while mixing.
        mixer_menu = bar.addMenu("&Mixer")
        self._action(mixer_menu, "&Add channel\u2026", self.add_channel, "Ctrl+N")
        self._action(mixer_menu, "Re&fresh devices and apps", self.refresh_now, "F5")
        mixer_menu.addSeparator()
        self.recording_action = self._action(mixer_menu, "&Recording mix (a third mix)", self.toggle_recording_mix, checkable=True)
        self._action(mixer_menu, "Recording &devices for OBS", self.show_own_devices)
        mixer_menu.addSeparator()
        self.mic_action = self._action(mixer_menu, "Mute my &microphone", self.toggle_mic_mute, "Ctrl+M", checkable=True)
        self.hear_action = self._action(mixer_menu, "&Hear Broadcast", self.toggle_hear_broadcast, "Ctrl+B", checkable=True)
        self.mute_actions = {}
        used = {"a", "f", "r", "d", "m", "h"}  # the Alt-key letters the items above and below take
        for mix in self.engine.mixer.mixes:
            shortcut = {MONITOR: "Ctrl+Shift+L", STREAM: "Ctrl+Shift+B"}.get(mix.id, "")
            letter = next((c for c in mix.label if c.isalnum() and c.lower() not in used), "")  # first letter of the name nobody has yet
            used.add(letter.lower())
            text = f"Mute {mix.label.replace(letter, '&' + letter, 1)}" if letter else f"Mute {mix.label}"
            self.mute_actions[mix.id] = self._action(mixer_menu, text, partial(self.toggle_mix_mute, mix.id),
                                                     shortcut, checkable=True)
        mixer_menu.aboutToShow.connect(self._refresh_mixer_menu)

        # View: how the window looks, in three groups (the Nexus ones only show in the Nexus look).
        view_menu = bar.addMenu("&View")
        view_menu.addSection("Layout")
        self.layout_actions = {}
        layout_group = QActionGroup(self)
        for key, text in (("columns", "&Columns (a card for each channel)"), ("rows", "&Rows (a line for each channel)"),
                          ("free", "Fr&ee (nodes you place anywhere)")):
            action = view_menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(layout_group)
            action.triggered.connect(lambda _c=False, key=key: self.set_layout(key))
            self.layout_actions[key] = action
        view_menu.addSection("Appearance")
        self.look_menu = view_menu.addMenu("&Look")
        self.look_menu.aboutToShow.connect(self._fill_look_menu)
        self.theme_menu = view_menu.addMenu("&Theme")
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        self.nexus_section = view_menu.addSection("Nexus")
        self.nexus_colors_action = self._action(view_menu, "&Nexus colours on dark themes",
                                                lambda: self.set_nexus_colors(self.nexus_colors_action.isChecked()), checkable=True)
        self.nexus_colors_action.setToolTip("Nexus's deep blue and cyan on Dark, Retro Purple, Midnight Blue and Amber Console. Off: each theme "
                                            "keeps its own colours. High contrast and imported themes are never changed.")
        self.reduce_action = self._action(view_menu, "Re&duce effects", lambda: self.set_reduce_effects(self.reduce_action.isChecked()),
                                          checkable=True)
        self.reduce_action.setToolTip("For slow or busy computers: the Nexus rings stop shimmering and the faders show no waveform or glow")
        self.tile_section = view_menu.addSection("Tile")
        self.tile_colors_action = self._action(view_menu, "Tile colo&urs on built-in themes",
                                               lambda: self.set_tile_colors(self.tile_colors_action.isChecked()), checkable=True)
        self.tile_colors_action.setToolTip("White keys on Light and Paper, graphite keys on Dark, Retro Purple, Midnight Blue and Amber Console. "
                                           "Off: each theme keeps its own colours. High contrast and imported themes are never changed.")
        self.tidy_action = self._action(view_menu, "T&idy up the free layout", lambda: self.canvas.tidy() if self.layout_mode == "free" else None)
        view_menu.addSection("Desktop")
        self.widgets_menu = view_menu.addMenu("Desktop wid&gets")
        self.widgets_menu.setToolTipsVisible(True)
        self.widgets_menu.aboutToShow.connect(self._fill_widgets_menu)
        view_menu.addSection("Window")
        self.fullscreen_action = self._action(view_menu, "&Full screen", self.toggle_fullscreen, "F11", checkable=True)
        self._action(view_menu, "Reset &window size", self.reset_window_size)
        view_menu.aboutToShow.connect(self._refresh_view_menu)

        # Settings: everything that is chosen once and then left alone, in four groups.
        self.settings_menu = settings_menu = bar.addMenu("&Settings")
        settings_menu.addSection("Startup")
        background = settings_menu.addMenu("&Running in the background")
        background.addSection("When I log in")
        group = QActionGroup(self)
        self.autostart_actions = {}
        for key, text in (("off", "Do not start automatically"), ("window", "Start with the window open"),
                          ("minimized", "Start minimized")):  # the last label says where it goes: see _refresh_background_menu
            action = background.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.triggered.connect(lambda _c=False, key=key: self.set_autostart(key))
            self.autostart_actions[key] = action
        background.addSection("When I close the window")
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
        settings_menu.addSection("Audio")
        buffer_menu = settings_menu.addMenu("Audio &buffer")
        self.buffer_actions = {}
        labels = {256: "Smallest (256 frames): lowest delay, most CPU", 512: "Small (512 frames): the default",
                  1024: "Large (1024 frames): less CPU", 2048: "Largest (2048 frames): least CPU, most delay"}
        for frames in BUFFER_CHOICES:
            self.buffer_actions[frames] = self._action(buffer_menu, labels[frames], partial(self.set_buffer, frames), checkable=True)
        buffer_menu.aboutToShow.connect(self._refresh_buffer_menu)
        # "MIDI controllers and Stream Deck" is added at the end of this group by attach_controls(), in front of this heading.
        self.controllers_separator = settings_menu.addSection("Updates")
        self.auto_update_action = self._action(settings_menu, "&Update automatically when a new version is found",
                                               self.toggle_auto_update, checkable=True)
        self._action(settings_menu, "&Check for updates\u2026", self.check_for_updates)
        self.rollback_action = self._action(settings_menu, "&Go back to the previous version\u2026", self.rollback_update)
        settings_menu.addSeparator()
        self._action(settings_menu, "Reset all &settings to the defaults\u2026", self.reset_settings)
        settings_menu.aboutToShow.connect(self._refresh_settings_menu)

        # Help: how to use it, and where to go when something is wrong.
        self.help_menu = bar.addMenu("&Help")
        self._action(self.help_menu, "&Keyboard shortcuts", self.show_shortcuts, "F1")
        self.help_menu.addAction("&What's new in this version", self.show_whats_new)
        self.help_menu.addSeparator()
        report_action = self.help_menu.addAction("Save bug &report\u2026", self.save_report)
        report_action.setToolTip("Something wrong, or something looks wrong? Save this file and send it: it lists the window size, how the "
                                 "window was arranged and where each part is, as well as the audio setup.")
        self.help_menu.setToolTipsVisible(True)
        self._action(self.help_menu, "I heard a &glitch", self.mark_glitch, "Ctrl+Shift+G")
        self.help_menu.addAction("Report a &problem", partial(self.open_link, ISSUES_URL))
        self.help_menu.addSeparator()
        self.help_menu.addAction("Join the &Discord", partial(self.open_link, DISCORD_URL))
        self.help_menu.addAction("Project page on Git&Hub", partial(self.open_link, PROJECT_URL))
        self.help_menu.addSeparator()
        self.help_menu.addAction(f"&About Sluice {__version__}", self.show_about)
        self.help_menu.addSeparator()
        self.uninstall_action = self.help_menu.addAction("&Uninstall Sluice\u2026", self.uninstall_app)

        # The menus live behind the menu button (and the Settings button) in the top bar; the classic bar stays out of sight.
        self.main_menu = QMenu(self)
        for menu in (file_menu, mixer_menu, view_menu, self.help_menu):
            self.main_menu.addMenu(menu)
        bar.setVisible(False)

    def _refresh_view_menu(self) -> None:
        self.fullscreen_action.setChecked(self.isFullScreen())
        self.reduce_action.setChecked(self.engine.mixer.reduce_effects)
        self.nexus_colors_action.setChecked(self.engine.mixer.nexus_colors)
        self.tile_colors_action.setChecked(self.engine.mixer.tile_colors)
        self._show_look_items()

    def _fill_widgets_menu(self) -> None:
        """Small windows to leave on the desktop: tick one to show it, untick to close it."""
        menu = self.widgets_menu
        menu.clear()
        items = [("Microphone mute button", "mic", None, "A round button: click it to mute or unmute your microphone")]
        for mix in self.engine.mixer.mixes:
            items.append((f"{mix.label} volume dial", "dial", mix.id, f"A dial for the {mix.label} main level: scroll to change it, click to mute"))
        items.append(("Channel list", "strip", None, "Every channel on one line, in a small window"))
        for text, kind, mix, tip in items:
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(self.desktop.is_open(kind, mix))
            action.setToolTip(tip)
            action.triggered.connect(lambda _c=False, kind=kind, mix=mix: self._toggle_desktop_widget(kind, mix))
        menu.addSeparator()
        close_all = menu.addAction("Close all widgets", lambda: self.desktop.close_all(forget=True))
        close_all.setEnabled(bool(self.desktop.open_widgets))

    def _toggle_desktop_widget(self, kind: str, mix) -> None:
        was_open = self.desktop.is_open(kind, mix)
        self.desktop.toggle(kind, mix)
        if not was_open and not self.desktop.is_open(kind, mix):
            self.say("That is as many widgets as Sluice keeps. Close one first.")

    def _show_look_items(self) -> None:
        """The View items that only mean something in the Nexus look are shown only there (and Tidy up only in the looks with Free)."""
        nexus = themes.current_look() == "nexus"
        for item in (self.nexus_section, self.nexus_colors_action, self.reduce_action):
            item.setVisible(nexus)
        for item in (self.tile_section, self.tile_colors_action):
            item.setVisible(themes.current_look() == "tile")
        self.tidy_action.setVisible(themes.has_free(themes.current_look()))  # Nexus and Tile have the Free layout
        self.tidy_action.setEnabled(self.layout_mode == "free")

    def uninstall_app(self) -> None:
        """Two ways to remove Sluice, each showing exactly what it removes; then Sluice closes and a separate process does it."""
        import subprocess

        from . import uninstall

        if "Demo" in self.engine.io.label:
            QMessageBox.information(self, "Uninstall Sluice", "Demo mode changes nothing, so there is nothing to uninstall here.")
            return
        keep_plan = uninstall.plan(keep_settings=True)
        all_plan = uninstall.plan(keep_settings=False, remove_git=True)

        def listing(result) -> str:
            return uninstall.describe(result).replace("Sluice will remove:", "This will remove:")

        box = QMessageBox(self)
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
            answer = QMessageBox.question(
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
            QMessageBox.warning(self, "Uninstall Sluice", f"Could not start the uninstall: {exc}\nRun this in a terminal instead: sluice --uninstall")
            return
        self.quit_app()

    def open_link(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.information(self, "Open link", f"Sluice could not open your browser. The address is:\n\n{url}")

    def _refresh_mixer_menu(self) -> None:
        self.hear_action.setChecked(self.engine.hear_broadcast)
        self.mic_action.setChecked(self.engine.mic_muted)
        self.recording_action.setChecked(self.engine.mixer.has_recording_mix)
        for mix_id, action in self.mute_actions.items():
            action.setChecked(self.engine.mixer.mix(mix_id).mute)

    def _refresh_settings_menu(self) -> None:
        self._refresh_file_menu()
        self.auto_update_action.setChecked(self.engine.mixer.auto_update)
        self._refresh_update_menu()

    # ------------------------------------------------------------------ what the menu items do
    def toggle_recording_mix(self) -> None:
        mixer = self.engine.mixer
        turn_on = not mixer.has_recording_mix
        text = ("Add a third mix, \u201cRecording\u201d: a second virtual microphone, \u201cSluice (Recording)\u201d, with its own "
                "faders and mutes, so a recorder can get a different blend from the one your audience hears."
                if turn_on else "Remove the Recording mix and its virtual microphone.")
        ask = QMessageBox(self)
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

    def set_buffer(self, frames: int) -> None:
        self.engine.mixer.buffer_frames = frames
        self.say(f"Audio buffer set to {frames} frames. It is used the next time Sluice starts "
                 f"(running now: {self.engine.io.blocksize}).")

    def show_own_devices(self) -> None:
        from .ui import OwnDevicesDialog  # here, not at the top: ui.py imports this module

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
        self.resize(*DEFAULT_SIZE)

    def shortcut_rows(self) -> list:
        """[(keys, what it does)] taken from the menu items themselves, so this list can never disagree with the menus."""
        rows = []
        for action in self.actions():
            keys = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if keys:
                rows.append((keys, action.text().replace("&", "").rstrip("\u2026")))
        return rows

    def show_shortcuts(self) -> None:
        rows = self.shortcut_rows()
        table = "".join(f"<tr><td><b>{key}</b>&nbsp;&nbsp;&nbsp;</td><td>{what}</td></tr>" for key, what in rows)
        QMessageBox.information(self, "Keyboard shortcuts", f"<table>{table}</table><br>"
                                "Faders: scroll the mouse wheel over one, or use the arrow keys when it is selected.<br>"
                                "For buttons and knobs outside the app, see <b>Settings > MIDI controllers and Stream Deck</b>.")

