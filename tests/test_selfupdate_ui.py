# SPDX-License-Identifier: GPL-3.0-or-later
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from sluice import __version__, selfupdate  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_whatsnew import NotesDialog  # noqa: E402
from sluice.updates import UpdateResult  # noqa: E402

ZIP = "https://github.com/Matt-B-007/Sluice/releases/download/v9.9.9/sluice-v9.9.9.zip"


@pytest.fixture
def make(qapp, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(NotesDialog, "open", lambda self: shown.append(self))
    windows = []

    def build(auto=False):
        config = tmp_path / "config.json"
        mixer = Mixer.default()
        mixer.auto_update = auto
        mixer.save(config)
        engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
        engine.start()
        win = MainWindow(engine, config_file=config)
        windows.append(win)
        win.show()
        return win, shown

    yield build
    for win in windows:
        win.shutdown()


def offer(zip_url=ZIP, checksum=ZIP + ".sha256"):
    return UpdateResult("available", __version__, "9.9.9", "https://example.com/r", notes="- **New.**",
                        zip_url=zip_url, checksum_url=checksum)


def updatable(monkeypatch, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "pyproject.toml").write_text("x")
    (root / "install.sh").write_text("x")
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: root)
    return root


def test_an_update_that_can_be_installed_offers_update_now(make, monkeypatch, tmp_path):
    updatable(monkeypatch, tmp_path)
    win, shown = make()
    win._show_update_result(offer())
    dialog = shown[0]
    assert dialog.action_button is not None and dialog.action_button.text() == "Update now"
    assert dialog.main_button is not None and dialog.main_button.text() == "Open download page"  # still there too
    assert "cannot install this by itself" not in dialog.view.toPlainText()


def test_an_update_that_cannot_be_installed_says_why_and_keeps_the_download_page(make, monkeypatch):
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: None)
    win, shown = make()
    win._show_update_result(offer())
    dialog = shown[0]
    assert dialog.action_button is None and dialog.main_button is not None
    assert "cannot install this by itself" in dialog.view.toPlainText()


def test_a_release_without_a_checksum_is_not_installed_by_itself(make, monkeypatch, tmp_path):
    updatable(monkeypatch, tmp_path)
    win, shown = make()
    win._show_update_result(offer(checksum=""))
    assert shown[0].action_button is None and "checksum" in shown[0].view.toPlainText()


def run_update(win, qapp, timeout=5.0):
    """Start the update and let its worker thread and the signals it sends finish."""
    import time

    end = time.time() + timeout
    while time.time() < end and any(t.name == "sluice-update" for t in threading.enumerate()):
        qapp.processEvents()
        time.sleep(0.01)
    for _ in range(5):
        qapp.processEvents()


def test_update_now_downloads_then_asks_and_restarts_only_when_told(make, monkeypatch, tmp_path, qapp):
    updatable(monkeypatch, tmp_path)
    win, _ = make()
    calls = []
    win._stage_update = lambda res, root, progress=None: (progress(5, 10), calls.append(res.latest), res.latest)[2]
    asked, restarted = [], []
    win._ask_restart_for_update = lambda version: asked.append(version) or False
    monkeypatch.setattr(win, "restart_into_update", lambda: restarted.append(True))
    win.start_update(offer())
    run_update(win, qapp)
    assert calls == ["9.9.9"] and asked == ["9.9.9"] and restarted == []
    assert "installed when Sluice restarts or closes" in win.status_label.text()
    win._ask_restart_for_update = lambda version: True
    win.start_update(offer())
    run_update(win, qapp)
    assert restarted == [True]


def test_a_failed_update_shows_the_reason_and_changes_nothing(make, monkeypatch, tmp_path, qapp):
    updatable(monkeypatch, tmp_path)
    win, _ = make()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warnings.append(text))

    def refuse(res, root, progress=None):
        raise selfupdate.UpdateError("The downloaded file does not match its checksum.")

    win._stage_update = refuse
    win.start_update(offer())
    run_update(win, qapp)
    assert warnings and "checksum" in warnings[0] and "Could not update" in win.status_label.text()
    win._stage_update = lambda res, root, progress=None: (_ for _ in ()).throw(RuntimeError("surprise"))
    win.start_update(offer())
    run_update(win, qapp)
    assert "RuntimeError" in warnings[-1]


def test_restarting_into_an_update_saves_installs_and_restarts_in_that_order(make, monkeypatch):
    win, _ = make()
    order = []
    monkeypatch.setattr(win, "shutdown", lambda: order.append("shutdown"))
    monkeypatch.setattr(selfupdate, "apply_staged_quietly", lambda: order.append("install"))
    from sluice import reconnect

    monkeypatch.setattr(reconnect, "restart_self", lambda: order.append("restart"))
    win.restart_into_update()
    assert order == ["shutdown", "install", "restart"]


def test_automatic_updates_are_off_by_default_and_do_nothing_then(make, monkeypatch, tmp_path, qapp):
    updatable(monkeypatch, tmp_path)
    win, _ = make(auto=False)
    win._update_check = lambda current: (_ for _ in ()).throw(AssertionError("no request may be made"))
    win._auto_update_check()
    assert not win.auto_update_action.isChecked() and win._auto_update_started is False


def test_automatic_update_downloads_in_the_background_and_waits_for_closing(make, monkeypatch, tmp_path, qapp):
    updatable(monkeypatch, tmp_path)
    win, shown = make(auto=True)
    staged = []
    win._update_check = lambda current: offer()
    win._stage_update = lambda res, root, progress=None: staged.append(res.latest) or res.latest
    win._auto_update_check()
    win._auto_update_check()  # a second call does nothing
    import time

    end = time.time() + 5
    while time.time() < end and not staged:
        time.sleep(0.01)
    while time.time() < end and "installed when you close" not in win.status_label.text():
        qapp.processEvents()
        time.sleep(0.01)
    assert staged == ["9.9.9"] and "installed when you close Sluice" in win.status_label.text()
    assert shown == []  # no dialog: it must never interrupt a call or a game


def test_automatic_update_skips_a_copy_that_cannot_update_itself(make, monkeypatch):
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: None)
    win, _ = make(auto=True)
    win._update_check = lambda current: (_ for _ in ()).throw(AssertionError("no request may be made"))
    win._auto_update_check()
    assert win._auto_update_started is False


def test_turning_automatic_updates_on_asks_first_and_off_does_not(make, monkeypatch, tmp_path):
    updatable(monkeypatch, tmp_path)
    win, _ = make()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    win.auto_update_action.trigger()
    assert win.engine.mixer.auto_update is False and not win.auto_update_action.isChecked()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.auto_update_action.trigger()
    assert win.engine.mixer.auto_update is True
    win.auto_update_action.trigger()  # off needs no question
    assert win.engine.mixer.auto_update is False


def test_automatic_updates_cannot_be_turned_on_where_they_cannot_work(make, monkeypatch):
    monkeypatch.setattr(selfupdate, "install_root", lambda *a: None)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: shown.append(text))
    win, _ = make()
    win.auto_update_action.trigger()
    assert win.engine.mixer.auto_update is False and not win.auto_update_action.isChecked() and shown


def test_go_back_is_only_enabled_when_there_is_something_to_go_back_to(make, monkeypatch):
    win, _ = make()
    monkeypatch.setattr(selfupdate, "previous_version", lambda root: "")
    win._refresh_update_menu()
    assert not win.rollback_action.isEnabled()
    monkeypatch.setattr(selfupdate, "previous_version", lambda root: "0.9.0")
    win._refresh_update_menu()
    assert win.rollback_action.isEnabled() and "0.9.0" in win.rollback_action.text()


def test_going_back_asks_then_restores_and_restarts(make, monkeypatch, tmp_path):
    root = updatable(monkeypatch, tmp_path)
    win, _ = make()
    monkeypatch.setattr(selfupdate, "previous_version", lambda r: "0.9.0")
    order = []
    monkeypatch.setattr(selfupdate, "rollback", lambda r: order.append(("rollback", r)))
    monkeypatch.setattr(win, "shutdown", lambda: order.append("shutdown"))
    from sluice import reconnect

    monkeypatch.setattr(reconnect, "restart_self", lambda: order.append("restart"))
    clicked = {"which": "cancel"}

    def fake_exec(self):
        buttons = {b.text(): b for b in self.buttons()}
        self._chosen = buttons["Cancel"] if clicked["which"] == "cancel" else buttons["Go back and restart"]
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self._chosen)
    win.rollback_update()
    assert order == []
    clicked["which"] = "go"
    win.rollback_update()
    assert order == ["shutdown", ("rollback", root), "restart"]
