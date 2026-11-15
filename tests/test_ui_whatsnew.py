# SPDX-License-Identifier: GPL-3.0-or-later
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from sluice import __version__, whatsnew  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_whatsnew import NotesDialog  # noqa: E402
from sluice.updates import UpdateResult  # noqa: E402


@pytest.fixture
def make(qapp, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(NotesDialog, "open", lambda self: shown.append(self))  # record, do not put a window on screen
    windows = []

    def build(config_exists=True, marker=None, with_config=True):
        config = tmp_path / "config.json"
        if config_exists:
            Mixer.default().save(config)
        if marker:
            whatsnew.write_marker(config, marker)
        engine = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
        engine.start()
        win = MainWindow(engine, config_file=config if with_config else None)
        windows.append(win)
        win.show()
        return win, config, shown

    yield build
    for win in windows:
        win.shutdown()


def test_a_new_install_is_not_told_what_is_new(make):
    win, config, shown = make(config_exists=False)
    assert whatsnew.read_marker(config) == __version__  # remembered from the very first start
    win._maybe_show_whats_new()
    assert shown == []


def test_after_an_update_the_notes_appear_once_and_are_remembered(make):
    win, config, shown = make(marker="0.7.0")
    win._maybe_show_whats_new()
    assert len(shown) == 1
    dialog = shown[0]
    assert __version__ in dialog.heading.text() and "Measure my room" in dialog.view.toPlainText()
    assert whatsnew.read_marker(config) == __version__
    win._maybe_show_whats_new()
    assert len(shown) == 1  # only once


def test_settings_from_before_the_record_was_kept_count_as_the_first_public_version(make):
    win, config, shown = make(config_exists=True, marker=None)
    assert whatsnew.read_marker(config) == ""  # an existing install is not assumed to be new
    win._maybe_show_whats_new()
    assert len(shown) == 1 and "Measure my room" in shown[0].view.toPlainText()


def test_starting_the_same_version_again_shows_nothing(make):
    win, _, shown = make(marker=__version__)
    win._maybe_show_whats_new()
    assert shown == []


def test_a_start_minimized_at_login_waits_until_the_window_is_opened(make):
    win, config, shown = make(marker="0.7.0")
    win.isMinimized = lambda: True
    win._maybe_show_whats_new()
    assert shown == [] and whatsnew.read_marker(config) == "0.7.0" and not win._whats_new_done  # nothing lost
    win.isMinimized = lambda: False
    win._maybe_show_whats_new()
    assert len(shown) == 1


def test_demo_mode_never_shows_it(make):
    win, _, shown = make(with_config=False)
    win._maybe_show_whats_new()
    assert shown == []


def test_help_menu_shows_the_notes_of_this_version(make):
    win, _, shown = make(marker=__version__)
    help_menu = next(a.menu() for a in win.menuBar().actions() if a.menu() and a.text().replace("&", "") == "Help")
    action = next(a for a in help_menu.actions() if a.text().startswith("What's new"))
    action.trigger()
    assert len(shown) == 1 and shown[0].view.toPlainText().strip() and __version__ in shown[0].windowTitle()


def test_an_available_update_shows_what_it_changes_before_you_download(make):
    win, _, shown = make(marker=__version__)
    result = UpdateResult("available", __version__, "9.9.9", "https://example.com/download", notes="- **A new thing.**")
    win._show_update_result(result)
    dialog = shown[0]
    assert "9.9.9" in dialog.heading.text() and "A new thing" in dialog.view.toPlainText()
    assert dialog.main_button is not None and dialog.main_button.text() == "Open download page"
    assert dialog.main_url == "https://example.com/download"


def test_an_update_without_notes_says_so(make):
    win, _, shown = make(marker=__version__)
    win._show_update_result(UpdateResult("available", __version__, "9.9.9", "https://example.com/d"))
    assert "No release notes" in shown[0].view.toPlainText()
