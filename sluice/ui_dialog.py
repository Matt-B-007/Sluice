# SPDX-License-Identifier: GPL-3.0-or-later
"""Sluice's own message window (0.12.2), used for every question and warning instead of the desktop's plain message box.

It is a QMessageBox underneath (so the keyboard, Escape, the default button and screen readers behave as everywhere), dressed as Sluice:
a drawn icon in a tinted tile in place of the desktop's icon, the title as a heading over the text, a comfortable width so a sentence
is not broken after three words, and the main button in the accent colour. Its looks are in the shared style sheet
(``QMessageBox#sluicemessage``), so it follows the theme in every skin.

``information``, ``warning``, ``critical`` and ``question`` take the same arguments as QMessageBox's functions of the same names and
return the same buttons. While a test has put its own function in QMessageBox's place, they call that instead, so a test can answer
them."""

from __future__ import annotations

from html import escape
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QMessageBox, QWidget

from . import themes, ui_icons as icons

Button = QMessageBox.StandardButton
KINDS = {  # kind -> (drawing, colour token of the drawing, colour token of its tile)
    "information": ("info", "accent_text", "accent_bg"),
    "question": ("info", "accent_text", "accent_bg"),
    "warning": ("info", "warn", "mute_bg"),
    "critical": ("close", "mute_fg", "mute_bg"),
}
_ORIGINAL = {name: getattr(QMessageBox, name) for name in KINDS}
MIN_TEXT_WIDTH = 380


def badge(kind: str, ratio: float = 1.0, size: int = 44) -> QPixmap:
    """The drawn icon of a message: its drawing on a rounded tile, both tinted for what kind of message it is."""
    name, ink, tile = KINDS.get(kind, KINDS["information"])
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(themes.color(tile)))
    p.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
    inner = round(size * 0.55)
    drawing = icons.render(name, themes.color(ink), round(inner * ratio))
    drawing.setDevicePixelRatio(ratio)
    p.drawPixmap((size - inner) // 2, (size - inner) // 2, drawing)
    p.end()
    return pixmap


def _rich(text: str) -> bool:
    """Whether a message is already written as HTML (Sluice's own rich messages start with a tag)."""
    stripped = text.lstrip()
    return stripped.startswith("<") and ">" in stripped


class Message(QMessageBox):
    """A QMessageBox dressed as Sluice. Use it as a QMessageBox: setText, addButton, exec, clickedButton."""

    def __init__(self, parent: Optional[QWidget] = None, kind: str = "question") -> None:
        super().__init__(parent)
        self.setObjectName("sluicemessage")
        self.kind = kind
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._dress()

    def _dress(self) -> None:
        self.setIconPixmap(badge(self.kind, self.devicePixelRatioF()))

    def setIcon(self, icon) -> None:  # noqa: N802  (Qt's name) the desktop's icons become Sluice's drawn ones
        self.kind = {
            QMessageBox.Icon.Warning: "warning",
            QMessageBox.Icon.Critical: "critical",
            QMessageBox.Icon.Information: "information",
        }.get(icon, "question")
        self._dress()

    def setWindowTitle(self, title: str) -> None:  # noqa: N802
        super().setWindowTitle(title)
        self._heading = title
        self._show_text()

    def setText(self, text: str) -> None:  # noqa: N802
        self._body = text
        self._show_text()

    def _show_text(self) -> None:
        """The title as a heading over the text (a window title is easy to miss), the text with its line breaks kept."""
        body = getattr(self, "_body", "")
        if not body:
            return
        heading = getattr(self, "_heading", "")
        html = body if _rich(body) else escape(body, quote=False).replace("\n", "<br>")
        top = (
            f"<p style='font-size:17px; font-weight:600; margin:0 0 6px 0'>{escape(heading, quote=False)}</p>" if heading else ""
        )
        super().setText(f"<div style='min-width:{MIN_TEXT_WIDTH}px'>{top}{html}</div>")

    def text(self) -> str:
        """The text as it was given (without the heading and the markup round it)."""
        return getattr(self, "_body", "") or super().text()

    def showEvent(self, event) -> None:
        self._dress()  # the screen's scale is known now
        default = self.defaultButton()
        if default is not None:
            default.setObjectName("primary")
            default.style().unpolish(default)
            default.style().polish(default)
        super().showEvent(event)


def _ask(kind: str, parent, title: str, text: str, buttons=Button.Ok, default=Button.NoButton):
    patched = getattr(QMessageBox, kind)
    if patched is not _ORIGINAL[kind]:  # a test answers for the person
        extra = [buttons] if buttons != Button.Ok or default != Button.NoButton else []
        return patched(parent, title, text, *extra, *([default] if default != Button.NoButton else []))
    box = Message(parent, kind)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if default != Button.NoButton:
        box.setDefaultButton(default)
    box.exec()
    return box.standardButton(box.clickedButton()) if box.clickedButton() is not None else Button.Cancel


def information(parent, title: str, text: str, buttons=Button.Ok, default=Button.NoButton):
    return _ask("information", parent, title, text, buttons, default)


def warning(parent, title: str, text: str, buttons=Button.Ok, default=Button.NoButton):
    return _ask("warning", parent, title, text, buttons, default)


def critical(parent, title: str, text: str, buttons=Button.Ok, default=Button.NoButton):
    return _ask("critical", parent, title, text, buttons, default)


def question(parent, title: str, text: str, buttons=Button.Yes | Button.No, default=Button.NoButton):
    return _ask("question", parent, title, text, buttons, default)


def card_panel(dialog, title: str, anchor: Optional[QWidget] = None) -> None:
    """0.12.2: dress a small dialog as a panel that drops from a card's menu (like the ☰ panel) instead of a separate window with
    a title bar: no frame, the title as a heading inside, opened next to ``anchor`` (or the pointer), closed by a click outside or
    Escape. It is still a dialog: exec() waits for it and accept/reject work as before."""
    from PySide6.QtGui import QCursor, QGuiApplication
    from PySide6.QtWidgets import QLabel

    dialog.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
    dialog.setObjectName("cardpanel")
    dialog.setWindowTitle(title)  # (read by screen readers)
    heading = QLabel(title)
    heading.setObjectName("panelheading")
    heading.setWordWrap(True)
    layout = dialog.layout()
    if layout is not None:
        layout.insertWidget(0, heading)
        layout.setContentsMargins(20, 18, 20, 16)

    def place(event, original=dialog.showEvent):
        where = anchor.mapToGlobal(anchor.rect().bottomLeft()) if anchor is not None and anchor.isVisible() else QCursor.pos()
        screen = QGuiApplication.screenAt(where) or QGuiApplication.primaryScreen()
        room = screen.availableGeometry()
        size = dialog.sizeHint().expandedTo(dialog.size())
        x = max(room.left() + 8, min(where.x(), room.right() - size.width() - 8))
        y = max(room.top() + 8, min(where.y() + 4, room.bottom() - size.height() - 8))
        dialog.move(x, y)
        original(event)

    dialog.showEvent = place
