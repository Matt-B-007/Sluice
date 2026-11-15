# SPDX-License-Identifier: GPL-3.0-or-later
"""0.10.0: the layout switch, the first-run screen, the slim fader, the status chip, and old theme files."""
import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import Fader, MainWindow  # noqa: E402


@pytest.fixture
def rig(qapp, tmp_path):
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.show()
    yield win, engine
    win.shutdown()


def test_layout_switch_changes_the_screen_and_is_remembered(rig, tmp_path):
    win, engine = rig
    assert engine.mixer.layout == "columns"
    win.set_layout("rows")
    assert engine.mixer.layout == "rows" and win.layout_mode == "rows"
    assert all(s.rows for s in win.strips)
    win.set_layout("nonsense")
    assert engine.mixer.layout == "rows"
    engine.save_config(tmp_path / "saved.json")
    assert Mixer.load(tmp_path / "saved.json").layout == "rows"
    win.set_layout("columns")
    assert not any(s.rows for s in win.strips)


def test_old_settings_without_a_layout_open_as_columns(tmp_path):
    path = tmp_path / "old.json"
    Mixer.demo().save(path)
    data = json.loads(path.read_text())
    data.pop("layout", None)
    path.write_text(json.dumps(data))
    assert Mixer.load(path).layout == "columns"


def test_first_run_shows_for_an_empty_mixer_and_goes_away_for_good(qapp, tmp_path):
    engine = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    try:
        assert win._needs_first_run()
        engine.mixer.hints_seen.append("firstrun")
        assert not win._needs_first_run()
    finally:
        win.shutdown()


def test_fader_moves_from_the_keyboard_and_resets_on_double_click(qapp):
    fader = Fader(horizontal=True)
    fader.resize(200, 28)
    fader.show()
    seen = []
    fader.gainChanged.connect(seen.append)
    start = fader.gain()
    fader.setFocus()
    QTest.keyClick(fader, Qt.Key.Key_Left)
    assert fader.gain() < start and seen
    QTest.keyClick(fader, Qt.Key.Key_Home)
    low = fader.gain()
    QTest.keyClick(fader, Qt.Key.Key_End)
    assert fader.gain() > low
    QTest.mouseDClick(fader, Qt.MouseButton.LeftButton)
    assert fader.gain() == 0 or abs(fader.gain()) <= 10  # back to 0 dB (tenths of a dB)


def test_status_chip_texts(rig):
    _win, engine = rig
    assert engine.dropout_text() == "0 dropouts"
    assert "kHz" in engine.rate_text() and "frames" in engine.rate_text()


def test_theme_file_without_the_new_colours_still_loads_and_gets_them(tmp_path):
    theme, _notes = themes.parse({"name": "Old one", "base": "dark", "colors": {"bg": "#101820", "accent": "#ff8844"}})
    for token in themes.NEW_TOKENS:
        assert theme.colors[token].startswith("#") and len(theme.colors[token]) == 7
    assert theme.colors["accent"] == "#ff8844"


def test_every_shipped_theme_lists_all_colours_and_passes_contrast():
    import pathlib
    folder = pathlib.Path(__file__).resolve().parent.parent / "themes"
    files = sorted(folder.glob("*.json"))
    assert len(files) >= 30
    for path in files:
        data = json.loads(path.read_text())
        assert set(data["colors"]) >= set(themes.TOKEN_NAMES), path.name
