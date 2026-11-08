# SPDX-License-Identifier: GPL-3.0-or-later
"""Small shared widgets."""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit, QSlider

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")


def parse_number(text: str) -> Optional[float]:
    """The first number in what someone typed: '-18', '-18 dB', '3.5:1', '50%', '1,5' (comma as decimal point).
    Returns None when there is no number. A bare '-inf' or 'off' counts as minus infinity."""
    cleaned = text.strip().lower().replace(",", ".")
    if re.match(r"^[-+]?\s*(inf|infinity)\b", cleaned) and cleaned.startswith("-") or cleaned in ("off", "-inf", "-inf db"):
        return float("-inf")
    match = _NUMBER.search(cleaned)
    return float(match.group()) if match else None


class ResetSlider(QSlider):
    """A slider that says so when it is double-clicked (the owner puts the value back to its default)."""

    reset_requested = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.reset_requested.emit()
        event.accept()


class ReadoutEdit(QLineEdit):
    """A value display that can also be typed into. Press Enter (or click away) to apply what was typed.

    ``entered`` carries the number typed, or None if there was no number; whoever owns the widget then sets the
    text again from the real value, so a bad entry just snaps back."""

    entered = Signal(object)

    def __init__(self, width: Optional[int] = 78) -> None:
        super().__init__()
        self.setObjectName("readout")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if width:
            self.setFixedWidth(width)
        self.setToolTip("Click and type a value, then press Enter")
        self.editingFinished.connect(self._finished)
        self.returnPressed.connect(self.clearFocus)

    def _finished(self) -> None:
        if self.isModified() or self.hasFocus():
            self.entered.emit(parse_number(self.text()))
        self.setModified(False)
