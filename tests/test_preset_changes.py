# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep, save as new, or undo a change made to one of your own presets."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pedalboard")

from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

from sluice import presets  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_effects import EffectsDialog  # noqa: E402


@pytest.fixture
def rig(qapp, tmp_path):
    engine = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    yield win, engine
    win.shutdown()


def compressor(engine):
    return next(e for e in engine.mixer.channel("mic").effects if e.type == "compressor")


def saved_ratio(dialog, name="Mine"):
    return next(e for e in presets.load_user(dialog._presets_file())[name] if e["type"] == "compressor")["params"]["ratio"]


def with_preset(rig, monkeypatch):
    win, engine = rig
    dialog = EffectsDialog(engine, engine.mixer.channel("mic"), win)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mine", True)))
    dialog._save_preset()
    return dialog, engine


def test_no_note_until_a_preset_of_yours_is_changed(rig, monkeypatch):
    dialog, engine = with_preset(rig, monkeypatch)
    assert dialog.mine_changed_row.isHidden()
    engine.set_effect_param(compressor(engine).id, "ratio", 3.5)
    dialog._update_presets_button()
    assert not dialog.mine_changed_row.isHidden() and "Mine" in dialog.mine_changed_label.text()


def test_update_asks_first_and_does_nothing_on_no(rig, monkeypatch):
    dialog, engine = with_preset(rig, monkeypatch)
    old = saved_ratio(dialog)
    engine.set_effect_param(compressor(engine).id, "ratio", 3.5)
    dialog._update_presets_button()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No))
    dialog.mine_update_button.click()
    assert asked and "Mine" in asked[0] and "gone" in asked[0]
    assert saved_ratio(dialog) == old and not dialog.mine_changed_row.isHidden()


def test_update_on_yes_replaces_the_preset_and_the_note_goes_away(rig, monkeypatch):
    dialog, engine = with_preset(rig, monkeypatch)
    engine.set_effect_param(compressor(engine).id, "ratio", 3.5)
    dialog._update_presets_button()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dialog.mine_update_button.click()
    assert saved_ratio(dialog) == 3.5
    assert dialog.mine_changed_row.isHidden() and dialog.mine_button.text().startswith("My preset: Mine")


def test_undo_puts_everything_back_without_touching_the_saved_preset(rig, monkeypatch):
    dialog, engine = with_preset(rig, monkeypatch)
    old = compressor(engine).params["ratio"]
    engine.set_effect_param(compressor(engine).id, "ratio", 3.5)
    dialog._update_presets_button()
    dialog.mine_undo_button.click()
    assert compressor(engine).params["ratio"] == old and saved_ratio(dialog) == old
    assert dialog.mine_changed_row.isHidden()


def test_save_as_new_keeps_the_old_preset_and_the_new_one_becomes_the_one_being_edited(rig, monkeypatch):
    dialog, engine = with_preset(rig, monkeypatch)
    old = saved_ratio(dialog)
    engine.set_effect_param(compressor(engine).id, "ratio", 3.5)
    dialog._update_presets_button()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mine two", True)))
    dialog.mine_new_button.click()
    assert saved_ratio(dialog, "Mine") == old and saved_ratio(dialog, "Mine two") == 3.5
    assert dialog.mine_changed_row.isHidden() and dialog.mine_button.text().startswith("My preset: Mine two")


def test_built_in_choices_get_no_update_note(rig):
    win, engine = rig
    dialog = EffectsDialog(engine, engine.mixer.channel("mic"), win)
    dialog._choose("room", "Noisy")
    engine.set_effect_param(next(e for e in engine.mixer.channel("mic").effects if e.type == "noise_reducer").id, "reduction_db", 3.0)
    dialog._update_presets_button()
    assert dialog.mine_changed_row.isHidden()  # Room and Voice style have their own Reset, and are never overwritten


def test_a_deleted_preset_leaves_no_note(rig, monkeypatch):
    dialog, engine = with_preset(rig, monkeypatch)
    engine.set_effect_param(compressor(engine).id, "ratio", 3.5)
    dialog._update_presets_button()
    dialog._delete_preset("Mine")
    assert dialog.mine_changed_row.isHidden()
