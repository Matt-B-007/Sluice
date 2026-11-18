# SPDX-License-Identifier: GPL-3.0-or-later
"""The system tray icon, its menu and the hidden-window watcher of the main window.

Part of the main window, split out of ``ui.py``: ``MainWindow`` inherits this class, so every method here is still a method of the window."""
from __future__ import annotations

import logging
import time
from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from . import ui_icons as icons
from .model import config_path
from .ui_constants import TALKING_HOLD, TALKING_LEVEL, TRAY_WATCH_MS

log = logging.getLogger("sluice.ui")


class TrayMixin:
    # ------------------------------------------------------------------ system tray
    @property
    def tray_active(self) -> bool:
        """True while the tray icon is on screen: then closing or minimizing the window hides it into the tray."""
        return self._tray is not None and self._tray.isVisible()

    def _update_tray(self) -> None:
        """Show the tray icon exactly while the close setting is 'tray' (and the desktop has a tray)."""
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        want = self.engine.mixer.close_action == "tray" and not self._closed and QSystemTrayIcon.isSystemTrayAvailable()
        if not want:
            if self._tray is not None:
                self._tray.hide()
            self._sync_tray_timer()
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(icons.tray_icon("idle"), self)
            self._tray_state = "idle"
            self._voice_until = 0.0
            menu = QMenu(self)
            self._tray_show = menu.addAction("Show Sluice", self.bring_to_front)
            menu.addSeparator()
            self._tray_mic = menu.addAction("Mute my microphone", self.toggle_mic_mute)
            self._tray_mic.setCheckable(True)
            self._tray_mutes = {}
            for mix in self.engine.mixer.mixes:
                action = menu.addAction(f"Mute {mix.label}", partial(self.toggle_mix_mute, mix.id))
                action.setCheckable(True)
                self._tray_mutes[mix.id] = action
            self._tray_hear = menu.addAction("Hear Broadcast", self.toggle_hear_broadcast)
            self._tray_hear.setCheckable(True)
            menu.addSeparator()
            menu.addAction("Quit", self.quit_app)
            menu.aboutToShow.connect(self._refresh_tray_menu)
            self._tray.setContextMenu(menu)
            self._tray_menu = menu  # keep a reference: Qt does not own a tray icon's menu
            self._tray.activated.connect(self._on_tray_activated)
        self._refresh_tray_icon(force=True)
        self._tray.show()
        self._sync_tray_timer()

    def _window_state_changed(self) -> None:
        """The window was shown, hidden or minimized: tell the efficiency tracker, and start or stop the tray watcher."""
        showing = self.isVisible() and not self.isMinimized()
        self.tracker.set_state("open" if showing else ("tray" if self.tray_active else "background"))
        self._sync_tray_timer()

    def _sync_tray_timer(self) -> None:
        """With the window hidden in the tray nothing reads the microphone level, so the tray icon would never light up. A light
        watcher (5 times a second) does that, and only while it is needed: not with the window showing (the meter timer does it
        then), not with the microphone muted (the icon is fixed), and not with no tray icon."""
        meters = getattr(self, "meter_timer", None)
        want = (self.tray_active and not (meters is not None and meters.isActive()) and not self.engine.mic_muted and not self._closed)
        if want and not self.tray_timer.isActive():
            self.tray_timer.start(TRAY_WATCH_MS)
        elif not want and self.tray_timer.isActive():
            self.tray_timer.stop()

    def _tray_tick(self) -> None:
        self.engine.levels()  # reads the microphone level (and clears the peaks, as the meters would)
        self.tracker.meter_tick()
        self._refresh_tray_icon()

    def _tray_tooltip(self) -> str:
        return "Sluice" + (" (microphone muted)" if self.engine.mic_muted else "")

    def _refresh_tray_icon(self, force: bool = False) -> None:
        """Muted: a red badge. Talking: lit up (the engine's microphone level, held for a moment so it does not flicker). Else plain."""
        if self._tray is None or not (force or self._tray.isVisible()):
            return
        if self.engine.mic_muted:
            state = "muted"
        else:
            now = time.monotonic()
            if self.engine.mic_level > TALKING_LEVEL:
                self._voice_until = now + TALKING_HOLD
            state = "talking" if now < self._voice_until else "idle"
        if state != self._tray_state or force:
            self._tray_state = state
            self._tray.setIcon(icons.tray_icon(state))  # only when it changes: nothing is redrawn while the state is steady
        self._tray.setToolTip(self._tray_tooltip())

    def _refresh_tray_menu(self) -> None:
        self._tray_show.setText("Hide Sluice" if self.isVisible() and not self.isMinimized() else "Show Sluice")
        self._tray_mic.setChecked(self.engine.mic_muted)
        for mix_id, action in self._tray_mutes.items():
            action.setChecked(self.engine.mixer.mix(mix_id).mute)
        self._tray_hear.setChecked(self.engine.hear_broadcast)

    def _on_tray_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # a plain click: show it, or hide it if it is already in front
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.hide()
            else:
                self.bring_to_front()

    def start_minimized(self) -> None:
        """Start without showing the window: into the tray if that is how Sluice is set to run, else to the taskbar."""
        self._update_tray()
        if self.tray_active:
            self.say("Sluice is running in the system tray.")
            self._set_meters_running(False)  # the window was never shown, so no hide event will stop the meters (or start the tray watcher)
        else:
            self.showMinimized()

    def quit_app(self) -> None:
        """Really quit (File > Quit, Ctrl+Q), whatever closing the window is set to do."""
        self._quitting = True
        self.close()

    def _tray_possible(self) -> bool:
        from PySide6.QtWidgets import QSystemTrayIcon

        return QSystemTrayIcon.isSystemTrayAvailable()

    def _refresh_background_menu(self) -> None:
        """Tick the current choices and say, in the labels, where Sluice will actually go."""
        from . import desktop

        state = desktop.autostart_state()
        for key, action in self.autostart_actions.items():
            action.setChecked(key == state)
        for key, action in self.close_actions.items():
            action.setChecked(key == self.engine.mixer.close_action)
        in_tray = self.engine.mixer.close_action == "tray" and self._tray_possible()
        self.autostart_actions["minimized"].setText("Start minimized to the tray" if in_tray else "Start minimized to the taskbar")
        self.no_tray_note.setVisible(not self._tray_possible())

    def set_autostart(self, mode: str) -> None:
        from . import desktop

        try:
            desktop.set_autostart(mode)
        except OSError as exc:
            QMessageBox.warning(self, "Could not change start-up", str(exc))
            return
        self.say({"off": "Sluice will not start by itself.",
                  "window": "Sluice will start when you log in, with its window open.",
                  "minimized": "Sluice will start when you log in, minimized to the "
                               + ("tray." if self.engine.mixer.close_action == "tray" and self._tray_possible() else "taskbar.")}[mode])

    def toggle_launcher(self) -> None:
        from . import desktop

        try:
            if desktop.is_installed():
                desktop.uninstall()
                self.say("Sluice was removed from the applications menu.")
            else:
                desktop.install()
                self.say("Sluice is now in the applications menu: search for \u201cSluice\u201d in your launcher.")
        except OSError as exc:
            QMessageBox.warning(self, "Could not change the applications menu", str(exc))

    def open_settings_folder(self) -> None:
        folder = (self.config_file or config_path()).parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

