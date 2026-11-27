# SPDX-License-Identifier: GPL-3.0-or-later
"""Checking for updates, installing them in place and going back, for the main window.

Part of the main window, split out of ``ui.py``: ``MainWindow`` inherits this class, so every method here is still a method of the window."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from . import ui_dialog
from . import __version__, update_install

log = logging.getLogger("sluice.ui")


class _UpdateBridge(QObject):
    """Carries the answer of the update check from its worker thread back to the window."""

    done = Signal(object)
    progress = Signal(int, int)  # bytes downloaded so far, total (0 = unknown)
    staged = Signal(object)  # (version, "") when an update was downloaded and verified, ("", message) when it was not
    quiet = Signal(object)  # the same, for the automatic update: no dialogs
    engine_rebuilt = Signal(str)  # 0.11.6: "" when the Rust engine was rebuilt, else what went wrong
    daily = Signal(object)  # 0.13.1: the daily look's answer: only the update pill shows it


class UpdatingMixin:
    # ----------------------------------------------------------- updating in place
    def start_update(self, result) -> None:
        """Download and check the new version (nothing changes yet), then offer to restart into it."""
        root = update_install.install_root()
        problem = update_install.offer_problem(root, result)
        if problem:
            ui_dialog.information(self, "Update", problem)
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
            except update_install.UpdateError as exc:
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
            ui_dialog.warning(self, "Could not update", message or "Unknown error.")
            return
        self.say(f"Sluice {version} is downloaded and checked. It is installed when Sluice restarts or closes.")
        if self._ask_restart_for_update(version):
            self.restart_into_update()

    def _ask_restart_for_update(self, version: str) -> bool:
        ask = ui_dialog.Message(self)
        ask.setWindowTitle("Update ready")
        ask.setText(
            f"Sluice {version} was downloaded and checked.\n\nRestart now to start using it? Your settings are saved "
            "first. If you choose later, it is installed the next time you close Sluice."
        )
        restart = ask.addButton("Restart now", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        return ask.clickedButton() is restart

    # ------------------------------------------------------------------ Stable or Beta (0.12.2)
    def set_update_channel(self, channel: str, ask: bool = True) -> None:
        from .update_check import is_prerelease

        mixer = self.engine.mixer
        before, mixer.update_channel = mixer.update_channel, channel if channel in ("stable", "beta") else "stable"
        for name, action in getattr(self, "channel_actions", {}).items():
            action.setChecked(mixer.update_channel == name)
        if mixer.update_channel == before:
            return
        log.info("update channel: %s", mixer.update_channel)
        if mixer.update_channel == "beta":
            self.say("Updates: Beta. Sluice also offers test versions, which bring new features first and may have rough edges.")
            return
        if not is_prerelease(__version__) or not ask:
            self.say("Updates: Stable. Sluice offers only tested releases.")
            return
        box = ui_dialog.Message(self)
        box.setWindowTitle("Back to Stable")
        box.setText(f"You are running a beta, {__version__}.")
        box.setInformativeText(
            "Stay on it until a stable version is newer, or go to the latest stable version now? "
            "Your settings are kept either way."
        )
        now = box.addButton("Go to the latest stable now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Stay until stable is newer", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not now:
            self.say(f"Updates: Stable. You stay on {__version__} until a stable version is newer.")
            return
        self.say("Looking for the latest stable version\u2026")
        check = self._update_check

        def work() -> None:
            self._update_bridge.done.emit(check(__version__, channel="stable", allow_older=True))

        threading.Thread(target=work, name="sluice-update-check", daemon=True).start()

    # ------------------------------------------------------------------ moving out of the download folder (0.12.0)
    def runs_from_download(self) -> bool:
        return self.config_file is not None and update_install.runs_from_download(update_install.install_root())

    def offer_move_once(self) -> None:
        """A little after start-up, once: Sluice installed before 0.12.0 runs from the folder it was downloaded to."""
        seen = self.engine.mixer.hints_seen
        if self._closed or "move-out-of-download" in seen or not self.runs_from_download():
            return
        seen.append("move-out-of-download")
        self.say(
            "Sluice runs from the folder you downloaded. Settings > Updates > Move moves it to its own folder, so the "
            "download can go."
        )

    def move_install(self) -> None:
        """Move Sluice to ~/.local/share/sluice/program and delete the download folder. Done after Sluice closes."""
        import subprocess

        root = update_install.install_root()
        if not update_install.runs_from_download(root):
            self.say("Sluice already runs from its own folder.")
            return
        from .launcher import program_dir

        ask = ui_dialog.Message(self)
        ask.setWindowTitle("Move Sluice to its own folder")
        ask.setText(
            f"Sluice runs from the folder you downloaded:\n{root}\n\nIt can move itself to {program_dir()} (with its "
            "menu entry and the sluice command) and then delete that folder. Your settings stay as they are.\n\n"
            "Sluice closes, the move takes a minute or two (it needs the internet for its Python packages), and "
            "Sluice starts again by itself. If anything goes wrong, it keeps running from where it is now."
        )
        move = ask.addButton("Move and restart", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        if ask.clickedButton() is not move:
            return
        try:
            subprocess.Popen(
                update_install.move_script(root),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            ui_dialog.warning(self, "Move Sluice", f"Could not start the move: {exc}\nIn a terminal, run:\n  {root}/install.sh")
            return
        self.quit_app()

    def restart_into_update(self) -> None:
        from . import reconnect

        self.shutdown()  # saves the settings, stops the audio
        update_install.apply_staged_quietly()
        reconnect.restart_self(show_window=True)

    def _refresh_update_menu(self) -> None:
        previous = update_install.previous_version(update_install.install_root())
        self.rollback_action.setEnabled(bool(previous))
        self.rollback_action.setText(
            f"&Go back to version {previous}\u2026" if previous else "&Go back to the previous version\u2026"
        )

    def toggle_check_daily(self) -> None:
        mixer = self.engine.mixer
        mixer.check_daily = not mixer.check_daily
        self.check_daily_action.setChecked(mixer.check_daily)
        self.save_settings()
        self.say(
            "Sluice looks for a new version once a day."
            if mixer.check_daily
            else "Sluice no longer looks for new versions by itself. Settings > Check now still works."
        )

    def toggle_auto_update(self) -> None:
        mixer = self.engine.mixer
        turn_on = not mixer.auto_update
        if turn_on:
            reason = update_install.unavailable_reason(update_install.install_root())
            if reason:
                self.auto_update_action.setChecked(False)
                ui_dialog.information(self, "Update automatically", reason)
                return
            ask = ui_dialog.question(
                self,
                "Update automatically",
                "Sluice will ask GitHub once, shortly after it starts, whether there is a newer version. If there is, it "
                "downloads it, checks it against its checksum, and installs it the next time you close Sluice. It never "
                "restarts or changes anything while it is running, and you can go back with Settings > Go back to the previous "
                "version.\n\nTurn this on?",
            )
            if ask != QMessageBox.StandardButton.Yes:
                self.auto_update_action.setChecked(False)
                return
        mixer.auto_update = turn_on
        self.auto_update_action.setChecked(turn_on)
        self.say(
            "Sluice will download new versions by itself and install them when you close it."
            if turn_on
            else "Automatic updates are off. Settings > Check for updates still works."
        )

    def _auto_update_check(self) -> None:
        """Once, a little after start-up, only if the user turned it on: fetch a newer version and leave it waiting."""
        if self._auto_update_started or self._closed or self.config_file is None or not self.engine.mixer.auto_update:
            return
        root = update_install.install_root()
        if update_install.unavailable_reason(root):
            return
        self._auto_update_started = True
        check, stage, bridge = self._update_check, self._stage_update, self._update_bridge

        def work() -> None:
            try:
                result = check(__version__, channel=self.engine.mixer.update_channel)
                if result.status != "available" or update_install.offer_problem(root, result):
                    return
                bridge.quiet.emit((stage(result, root), ""))
            except update_install.UpdateError as exc:
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
        root = update_install.install_root()
        previous = update_install.previous_version(root)
        if not previous:
            self.say("There is no earlier version to go back to.")
            return
        ask = ui_dialog.Message(self)
        ask.setWindowTitle("Go back to the previous version")
        ask.setText(
            f"Go back to Sluice {previous}?\n\nSluice restarts. Your settings are kept, but a newer version may have "
            "saved things an older one does not understand, so a backup of your settings is a good idea first "
            "(File > Export settings)."
        )
        go = ask.addButton("Go back and restart", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        if ask.clickedButton() is not go:
            return
        self.shutdown()
        try:
            update_install.rollback(root)
        except update_install.UpdateError as exc:
            log.warning("rollback failed: %s", exc)
        from . import reconnect

        reconnect.restart_self(show_window=True)
