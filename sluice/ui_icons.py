# SPDX-License-Identifier: GPL-3.0-or-later
"""The small line icons of the interface, drawn with Qt so they take the colour of the theme and stay sharp at any scale.

Every icon is a 24 x 24 drawing made of strokes (2 pixels wide, round ends), the same way as the icons of the design
mock-ups. ``icon(name, color)`` returns a QIcon; nothing is read from disk.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

NAMES = ("speaker", "speaker_off", "mic", "mic_off", "link", "sliders", "plus", "menu", "gear", "more", "chevron_down")


def _speaker(p: QPainter, crossed: bool) -> None:
    body = QPainterPath()
    body.moveTo(4, 9.5)
    body.lineTo(8, 9.5)
    body.lineTo(13, 5.5)
    body.lineTo(13, 18.5)
    body.lineTo(8, 14.5)
    body.lineTo(4, 14.5)
    body.closeSubpath()
    p.drawPath(body)
    if crossed:
        p.drawLine(QPointF(17, 9), QPointF(22, 15))
        p.drawLine(QPointF(22, 9), QPointF(17, 15))
    else:
        p.drawArc(QRectF(10, 7.5, 9, 9), -50 * 16, 100 * 16)
        p.drawArc(QRectF(8, 4.5, 15, 15), -50 * 16, 100 * 16)


def _mic(p: QPainter, crossed: bool) -> None:
    p.drawRoundedRect(QRectF(9, 3, 6, 11), 3, 3)
    p.drawArc(QRectF(5.5, 7, 13, 11), 180 * 16, 180 * 16)
    p.drawLine(QPointF(12, 18), QPointF(12, 21))
    p.drawLine(QPointF(9, 21), QPointF(15, 21))
    if crossed:
        p.drawLine(QPointF(4, 4), QPointF(20, 20))


def _link(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(3, 8.5, 11, 7), 3.5, 3.5)
    p.drawRoundedRect(QRectF(10, 8.5, 11, 7), 3.5, 3.5)


def _sliders(p: QPainter) -> None:
    for y, x in ((6, 9), (12, 15), (18, 8)):
        p.drawLine(QPointF(4, y), QPointF(20, y))
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(x, y), 2.2, 2.2)
        p.setBrush(Qt.BrushStyle.NoBrush)


def _gear(p: QPainter) -> None:
    p.drawEllipse(QPointF(12, 12), 3, 3)
    for angle in range(0, 360, 45):
        p.save()
        p.translate(12, 12)
        p.rotate(angle)
        p.drawLine(QPointF(0, -6.5), QPointF(0, -9))
        p.restore()
    p.drawEllipse(QPointF(12, 12), 6.5, 6.5)


def _draw(name: str, p: QPainter) -> None:
    if name in ("speaker", "speaker_off"):
        _speaker(p, name == "speaker_off")
    elif name in ("mic", "mic_off"):
        _mic(p, name == "mic_off")
    elif name == "link":
        _link(p)
    elif name == "sliders":
        _sliders(p)
    elif name == "plus":
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "menu":
        for y in (7, 12, 17):
            p.drawLine(QPointF(4, y), QPointF(20, y))
    elif name == "gear":
        _gear(p)
    elif name == "more":
        p.setBrush(p.pen().color())
        for y in (5.5, 12, 18.5):
            p.drawEllipse(QPointF(12, y), 1.5, 1.5)
    elif name == "chevron_down":
        p.drawLine(QPointF(6, 9), QPointF(12, 15))
        p.drawLine(QPointF(12, 15), QPointF(18, 9))
    else:
        raise ValueError(f"no icon called {name}")


@lru_cache(maxsize=256)
def _pixmap(name: str, color: str, size: int, ratio: float) -> QPixmap:
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    pen = QPen(QColor(color), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    _draw(name, p)
    p.end()
    return pixmap


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """A QIcon of the named drawing in ``color`` (a #rrggbb string). Sharp on screens with a scale factor of 1, 1.5 or 2."""
    result = QIcon()
    for ratio in (1.0, 2.0):
        result.addPixmap(_pixmap(name, color, size, ratio))
    return result
