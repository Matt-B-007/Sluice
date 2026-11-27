"""0.12.6 (House Standard): every visible interactive control has a name a screen reader can say, and faders and effect
sliders say their value in dB or the effect's own unit, not the handle's position. Buttons that show text are named by it."""
import pytest
from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox, QLineEdit, QScrollBar,
                               QStackedWidget, QWidget)

from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer

INTERACTIVE = (QAbstractButton, QAbstractSlider, QComboBox, QLineEdit, QAbstractSpinBox)


def unnamed(root: QWidget) -> list:
    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not widget.isVisible() or isinstance(widget, QScrollBar) or not isinstance(widget, INTERACTIVE):
            continue  # scroll bars are announced by their role
        name = widget.accessibleName() or (widget.text() if isinstance(widget, QAbstractButton) else "")
        if not name.strip():
            found.append(f"{type(widget).__name__} in {type(widget.parent()).__name__} (tooltip: {widget.toolTip()[:50]!r})")
    return found


@pytest.fixture
def window(qapp, tmp_path, request):
    from sluice.ui import MainWindow
    mixer = Mixer.demo()
    mixer.skin = getattr(request, "param", "calm")
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.resize(1400, 900)
    win.show()
    for _ in range(5):
        qapp.processEvents()
    yield win
    win.shutdown()


@pytest.mark.parametrize("window", ["calm", "tile", "nexus", "glass"], indirect=True)
def test_every_control_in_the_window_has_a_name(window):
    assert unnamed(window) == []


def test_faders_say_their_level_in_db(window):
    strip = window.strips[0]
    fader = next(iter(strip.faders.values()))
    fader.setGain(-60)
    assert fader.accessibleDescription() == "-6.0 dB" and "level" in fader.accessibleName()


def test_settings_and_dialogs_have_names_for_every_control(window, qapp):
    from sluice.ui_apps import AppPickerDialog
    from sluice.ui_channel import OwnDevicesDialog
    from sluice.ui_effects import EffectsDialog
    from sluice.ui_settings import SettingsWindow
    engine = window.engine
    mic = engine.mixer.channel("mic")
    dialogs = [SettingsWindow(window), EffectsDialog(engine, mic, window), OwnDevicesDialog(engine, window),
               AppPickerDialog(engine.catalog, "Game", lambda key: None, window)]
    try:
        for dialog in dialogs:
            dialog.show()
        qapp.processEvents()
        for dialog in dialogs:
            assert unnamed(dialog) == [], type(dialog).__name__
        pages = dialogs[0].findChild(QStackedWidget)
        for index in range(pages.count() if pages else 0):  # every Settings section, not only the first
            pages.setCurrentIndex(index)
            qapp.processEvents()
            assert unnamed(pages.currentWidget()) == [], f"Settings section {index}"
    finally:
        for dialog in dialogs:
            dialog.close()


def test_effect_sliders_say_their_value(window):
    from sluice.ui_effects import EffectsDialog, ParamRow
    dialog = EffectsDialog(window.engine, window.engine.mixer.channel("mic"), window)
    try:
        row = dialog.findChildren(ParamRow)[0]
        assert row.slider.accessibleName() == row.info.label
        row.set_value(row.info.lo)
        assert row.slider.accessibleDescription() and row.readout.accessibleName().endswith("value")
    finally:
        dialog.close()
