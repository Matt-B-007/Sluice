# SPDX-License-Identifier: GPL-3.0-or-later
"""Checking for updates, installing them in place and going back, for the main window.

Part of the main window, split out of ``ui.py``: ``MainWindow`` inherits this class, so every method here is still a method of the window."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from . import __version__, selfupdate

log = logging.getLogger("sluice.ui")


class _UpdateBridge(QObject):
    """Carries the answer of the update check from its worker thread back to the window."""

    done = Signal(object)
    progress = Signal(int, int)  # bytes downloaded so far, total (0 = unknown)
    staged = Signal(object)      # (version, "") when an update was downloaded and verified, ("", message) when it was not
    quiet = Signal(object)       # the same, for the automatic update: no dialogs


class UpdatingMixin:
    # ----------------------------------------------------------- updating in place
    def start_update(self, result) -> None:
        """Download and check the new version (nothing changes yet), then offer to restart into it."""
        root = selfupdate.install_root()
        problem = selfupdate.offer_problem(root, result)
        if problem:
            QMessageBox.information(self, "Update", problem)
            return
        dialog = QProgressDialog(f"Downloading Sluice {result.latest}\u2026", "", 0, 100, self)
        dialog.setWindowTitle("Updating Sluice")
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setValue(0)
        self._update_progress_dialog = dialog
        self.say(f"Downloading Sluice {result.latest}\u2026")
        bridge, stage = self._update_bridge, self._stage_update

        def work() -> None:
            try:
                version = stage(result, root, progress=lambda done, total: bridge.progress.emit(done, total))
                bridge.staged.emit((version, ""))
            except selfupdate.UpdateError as exc:
                bridge.staged.emit(("", str(exc)))
            except Exception as exc:  # anything unexpected is still just "could not update"
                log.exception("update failed")
                bridge.staged.emit(("", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, name="sluice-update", daemon=True).start()

    def _update_progress(self, done: int, total: int) -> None:
        dialog = self._update_progress_dialog
        if dialog is not None and total > 0:
            dialog.setValue(min(99, int(done * 100 / total)))

    def _close_progress(self) -> None:
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.close()
            self._update_progress_dialog = None

    def _update_staged(self, outcome) -> None:
        self._close_progress()
        version, message = outcome
        if not version:
            self.say(f"Could not update: {message.splitlines()[0] if message else 'unknown error'}")
            QMessageBox.warning(self, "Could not update", message or "Unknown error.")
            return
        self.say(f"Sluice {version} is downloaded and checked. It is installed when Sluice restarts or closes.")
        if self._ask_restart_for_update(version):
            self.restart_into_update()

    def _ask_restart_for_update(self, version: str) -> bool:
        ask = QMessageBox(self)
        ask.setWindowTitle("Update ready")
        ask.setText(f"Sluice {version} was downloaded and checked.\n\nRestart now to start using it? Your settings are saved "
                    "first. If you choose later, it is installed the next time you close Sluice.")
        restart = ask.addButton("Restart now", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        return ask.clickedButton() is restart

    def restart_into_update(self) -> None:
        from . import reconnect

        self.shutdown()  # saves the settings, stops the audio
        selfupdate.apply_staged_quietly()
        reconnect.restart_self(show_window=True)

    def _refresh_update_menu(self) -> None:
        previous = selfupdate.previous_version(selfupdate.install_root())
        self.rollback_action.setEnabled(bool(previous))
        self.rollback_action.setText(f"Go back to version {previous}\u2026" if previous else "Go back to the previous version\u2026")

    def toggle_auto_update(self) -> None:
        mixer = self.engine.mixer
        turn_on = not mixer.auto_update
        if turn_on:
            reason = selfupdate.unavailable_reason(selfupdate.install_root())
            if reason:
                self.auto_update_action.setChecked(False)
                QMessageBox.information(self, "Update automatically", reason)
                return
            ask = QMessageBox.question(
                self, "Update automatically",
                "Sluice will ask GitHub once, shortly after it starts, whether there is a newer version. If there is, it "
                "downloads it, checks it against its checksum, and installs it the next time you close Sluice. It never "
                "restarts or changes anything while it is running, and you can go back with Settings > Go back to the previous "
                "version.\n\nTurn this on?")
            if ask != QMessageBox.StandardButton.Yes:
                self.auto_update_action.setChecked(False)
                return
        mixer.auto_update = turn_on
        self.auto_update_action.setChecked(turn_on)
        self.say("Sluice will download new versions by itself and install them when you close it." if turn_on
                 else "Automatic updates are off. Settings > Check for updates still works.")

    def _auto_update_check(self) -> None:
        """Once, a little after start-up, only if the user turned it on: fetch a newer version and leave it waiting."""
        if self._auto_update_started or self._closed or self.config_file is None or not self.engine.mixer.auto_update:
            return
        root = selfupdate.install_root()
        if selfupdate.unavailable_reason(root):
            return
        self._auto_update_started = True
        check, stage, bridge = self._update_check, self._stage_update, self._update_bridge

        def work() -> None:
            try:
                result = check(__version__)
                if result.status != "available" or selfupdate.offer_problem(root, result):
                    return
                bridge.quiet.emit((stage(result, root), ""))
            except selfupdate.UpdateError as exc:
                bridge.quiet.emit(("", str(exc)))
            except Exception:
                log.exception("automatic update failed")

        threading.Thread(target=work, name="sluice-auto-update", daemon=True).start()

    def _auto_update_staged(self, outcome) -> None:
        version, message = outcome
        if version:
            self.say(f"Sluice {version} was downloaded and checked. It is installed when you close Sluice.")
        else:
            log.info("automatic update did not go ahead: %s", message)
            self.say("An automatic update could not be installed. Settings > Check for updates shows why.")

    def rollback_update(self) -> None:
        root = selfupdate.install_root()
        previous = selfupdate.previous_version(root)
        if not previous:
            QMessageBox.information(self, "Go back", "There is no earlier version to go back to.")
            return
        ask = QMessageBox(self)
        ask.setWindowTitle("Go back to the previous version")
        ask.setText(f"Go back to Sluice {previous}?\n\nSluice restarts. Your settings are kept, but a newer version may have "
                    "saved things an older one does not understand, so a backup of your settings is a good idea first "
                    "(File > Export settings).")
        go = ask.addButton("Go back and restart", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        if ask.clickedButton() is not go:
            return
        self.shutdown()
        try:
            selfupdate.rollback(root)
        except selfupdate.UpdateError as exc:
            log.warning("rollback failed: %s", exc)
        from . import reconnect

        reconnect.restart_self(show_window=True)

