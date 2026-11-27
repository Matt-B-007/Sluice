# SPDX-License-Identifier: GPL-3.0-or-later
"""0.13.1 (House Standard): the top bar's right end, Ctrl+K command search, ?, the update dialog's Skip this version, the
uninstall dialog, the Report dialog and the tour."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sluice import uninstall, update_check  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402


@pytest.fixture
def win(qapp, tmp_path):
    mixer = Mixer.demo()
    mixer.hints_seen.append("firstrun")
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    window = MainWindow(engine, config_file=tmp_path / "config.json")
    window.show()
    qapp.processEvents()
    yield window
    window.shutdown()


def available(latest="9.9.9"):
    return update_check.UpdateResult(status="available", current="0.13.1-beta.1", latest=latest, notes="Notes", page="")


def test_the_top_right_holds_the_update_pill_then_help_then_settings(win):
    row = win.settings_button.parentWidget().layout()
    order = [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget() is not None]
    assert order[-3:] == [win.update_pill, win.help_button, win.settings_button]
    assert not win.update_pill.isVisibleTo(win)  # only when there is an update
    assert "Ctrl+," in win.settings_button.toolTip()


def test_the_daily_look_shows_the_pill_and_a_skipped_version_does_not(win, qapp):
    win._daily_result(available())
    assert win.update_pill.isVisibleTo(win) and "9.9.9" in win.update_pill.text()
    win.skip_version("9.9.9")
    assert not win.update_pill.isVisibleTo(win) and win.engine.mixer.skipped_version == "9.9.9"
    win._daily_result(available())
    assert not win.update_pill.isVisibleTo(win)
    win._daily_result(available("9.9.10"))  # a newer one is offered again
    assert win.update_pill.isVisibleTo(win)


def test_the_daily_look_waits_a_day_and_can_be_turned_off(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "_update_check", lambda *a, **k: calls.append(1) or available())
    win.engine.mixer.last_update_check = 0.0
    win.engine.mixer.check_daily = False
    win._daily_check()
    assert win.engine.mixer.last_update_check == 0.0
    win.engine.mixer.check_daily = True
    win._daily_check()
    first = win.engine.mixer.last_update_check
    assert first > 0
    win._daily_check()  # not again within a day
    assert win.engine.mixer.last_update_check == first


def test_the_update_dialog_has_update_now_later_and_skip(win, monkeypatch):
    from sluice import update_install

    monkeypatch.setattr(update_install, "offer_problem", lambda *a: "")
    win._show_update_result(available())
    dialog = win._notes_dialog
    assert dialog.windowTitle() == "Sluice 9.9.9 is available"
    # on a beta with the normal channel chosen, it says so (the House Standard's wording)
    assert "You're on beta 0.13.1-beta.1" in dialog.heading.text()
    win.engine.mixer.update_channel = "beta"
    win._show_update_result(available())
    dialog = win._notes_dialog
    assert "You have 0.13.1-beta.1." in dialog.heading.text()
    assert dialog.action_button.text() == "Update now" and dialog.close_button.text() == "Later"
    dialog.extra_button.click()
    assert win.engine.mixer.skipped_version == "9.9.9" and not dialog.isVisible()


def test_skipped_version_and_daily_check_are_saved():
    mixer = Mixer.demo()
    mixer.skipped_version, mixer.check_daily, mixer.last_update_check = "1.2.3", False, 123.0
    again = Mixer.from_dict(mixer.to_dict())
    assert (again.skipped_version, again.check_daily, again.last_update_check) == ("1.2.3", False, 123.0)
    assert Mixer.from_dict({}).check_daily is True


def test_command_search_finds_menu_items_channels_and_settings(win, qapp, monkeypatch):
    from sluice import ui_command

    labels = [label for label, _ in ui_command.commands(win)]
    assert any(label.startswith("Help › Report a problem") for label in labels)
    assert "Settings › Appearance" in labels
    assert any(label.startswith("Mute Mic in") or label.startswith("Unmute Mic in") for label in labels)
    assert ui_command.matches("Settings › Appearance", "set app")
    win.command_action.trigger()
    search = win.command_search
    search.search.setText("mute mic")
    assert search.results.count() >= 1
    first = search.results.item(0).text()
    channel = win.engine.mixer.channels[0]
    before = dict(channel.mutes)
    search.run_selected()
    qapp.processEvents()
    assert first.split(" ")[0] in ("Mute", "Unmute") and channel.mutes != before


def test_question_mark_opens_the_shortcuts_page_but_not_while_typing(win):
    from PySide6.QtGui import QKeySequence

    found = [a for a in win.actions() if a.shortcut() == QKeySequence("?")]
    assert found and found[0].shortcutContext() == Qt.ShortcutContext.WindowShortcut


def test_the_uninstall_dialog_keeps_settings_unless_asked(qapp):
    from sluice.ui_uninstall import UninstallDialog

    keep, everything = uninstall.Plan(keep_settings=True), uninstall.Plan(keep_settings=False)
    dialog = UninstallDialog(keep, everything)
    assert dialog.delete_settings.text() == "Also delete my settings and logs" and not dialog.delete_settings.isChecked()
    assert not dialog.caches.isChecked()
    assert dialog.uninstall_button.text() == "Uninstall" and dialog.uninstall_button.objectName() == "danger"
    assert dialog.cancel_button.isDefault()  # Enter never uninstalls
    dialog.delete_settings.setChecked(True)
    assert dialog.listing.text()
    dialog.close()


def test_help_button_opens_the_help_menu(win, monkeypatch):
    shown = []
    monkeypatch.setattr(win.help_menu, "exec", lambda *a: shown.append(1))
    win.help_button.click()
    assert shown == [1]
    QApplication.processEvents()


def test_every_icon_is_a_bundled_lucide_icon_with_its_licence(qapp):
    from sluice import ui_icons

    assert set(ui_icons.NAMES) <= set(ui_icons.LUCIDE)
    for name in ui_icons.NAMES:
        svg = ui_icons._lucide_svg(name)
        assert svg is not None and b"currentColor" in svg and b"lucide" in svg, name
    assert "ISC" in (ui_icons.ICON_DIR / "LICENSE").read_text()
    bundled = {p.stem for p in ui_icons.ICON_DIR.glob("*.svg")}
    assert bundled == set(ui_icons.LUCIDE.values())  # only the icons Sluice uses
    pixmap = ui_icons.render("gear", "#ff0000", 24).toImage()
    assert any(pixmap.pixelColor(x, y).red() > 200 for x in range(24) for y in range(24))  # drawn in the colour asked for


@pytest.mark.parametrize("skin", ["calm", "tile"])
def test_the_broadcast_device_name_ends_in_an_ellipsis_on_a_narrow_card_and_is_copied_whole(qapp, tmp_path, skin):
    """0.13.1: on a narrow card the button showed "Sends to: Sluice (Broadcas", cut off; now it ends in an ellipsis."""
    from PySide6.QtGui import QGuiApplication

    from sluice.ui_base import ElidedButton

    mixer = Mixer.demo()
    mixer.skin = skin
    mixer.hints_seen.append("firstrun")
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    window = MainWindow(engine, config_file=tmp_path / "config.json")
    window.show()
    try:
        strip = next(s for s in window.mix_strips if s.mix.kind != "monitor")
        if getattr(strip, "fold", None) is not None:  # Tile: the button is in the folded-out details
            strip.fold.setChecked(True)
            qapp.processEvents()
        button = strip.device_button
        assert button.isVisible()
        assert (
            isinstance(button, ElidedButton)
            and f"\u201c{strip.mix.source_description}\u201d" in button.full_text()
            or (button.full_text() == f"Sends to: {strip.mix.source_description}")
        )
        for width in (400, 180, 90):
            button.setFixedWidth(width)
            qapp.processEvents()
            shown = button.text()
            assert button.fontMetrics().horizontalAdvance(shown) <= width - ElidedButton.PADDING + 1, (width, shown)
            assert shown == button.full_text() or shown.endswith("…")
        button.click()
        assert QGuiApplication.clipboard().text() == strip.mix.source_description  # the whole name, never the shortened one
    finally:
        window.shutdown()
