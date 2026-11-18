# SPDX-License-Identifier: GPL-3.0-or-later
"""No button may be bigger than the space made for it: a style sheet's border and minimum height once added 2 px to the microphone
mute button of the Mic card, so its bottom edge was cut off."""
import pytest

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QPushButton

from sluice import themes
from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import Mixer
from sluice.ui import MainWindow


def _window(qapp, tmp_path, layout, theme):
    system = MockSystem()
    system.add_demo_streams()
    mixer = Mixer.demo()
    mixer.layout, mixer.theme = layout, theme
    engine = Engine(mixer, system, NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    win.resize(1456, 800)
    win.show()
    qapp.processEvents()
    return win


def _problems(win):
    found = []
    for strip in win.strips:
        for button in strip.findChildren(QPushButton):
            if not button.isVisibleTo(strip):
                continue
            name = f"{strip.channel.id}/{button.objectName() or button.accessibleName() or button.text()}"
            fixed = button.minimumSize() == button.maximumSize() and button.minimumSize().height() > 0
            if fixed and button.size() != button.maximumSize():
                found.append(f"{name} was made {button.maximumSize().width()}x{button.maximumSize().height()} but is "
                             f"{button.width()}x{button.height()}")
            parent = button.parentWidget()
            while parent is not None and parent is not strip.parentWidget():
                rect = QRect(button.mapTo(parent, QPoint(0, 0)), button.size())
                if not parent.rect().contains(rect):
                    found.append(f"{name} sticks out of {parent.objectName() or type(parent).__name__}: {rect.getRect()} in {parent.rect().getRect()}")
                    break
                parent = parent.parentWidget()
    return found


@pytest.mark.parametrize("layout", ["columns", "rows"])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_no_button_on_a_channel_is_cut_off_or_resized_by_the_style(qapp, tmp_path, layout, theme):
    win = _window(qapp, tmp_path, layout, theme)
    try:
        assert _problems(win) == []
    finally:
        win.shutdown()
        themes.set_current(themes.DARK)


def test_the_self_check_can_tell_which_effects_engine_is_used():
    """The check once built a throw-away effects toolbox around a dummy object, which always failed; the failure was silently dropped
    until 0.10.3 started reporting it ("effects: unknown (AttributeError ...)")."""
    from sluice import diagnose
    from sluice.effects import native_backend

    assert native_backend() in ("rust", "python")
    ok, text = diagnose._engine()
    assert ok and "effects: unknown" not in text and f"effects: {native_backend()}" in text
