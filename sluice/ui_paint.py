# SPDX-License-Identifier: GPL-3.0-or-later
"""The drawing every skin shares (0.12.0): the groove a fader runs in, the pill-shaped handle on it, and soft shadows.

Before 0.12.0 each place drew its own: the window's fader (Calm), the Tile keys, the Tile lane and the desktop
widgets each had a copy of the same shadow, groove and handle code. They now all call these two functions with their own
colours, so a fix or a change to how a fader is drawn is made once.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


def groove(
    p: QPainter,
    rect: QRectF,
    brush=None,
    shade_alpha: int = 0,
    shade_depth: float = 3.0,
    across: bool = False,
    light_line: Optional[QColor] = None,
) -> QPainterPath:
    """A rounded groove: filled with ``brush`` (None: not filled, for a groove whose inside is drawn already), shaded along its top
    inside edge (its left edge when ``across``, for a sideways groove whose top edge is its length) so it looks pressed in, and
    with a faint ``light_line`` under it. Returns its shape, for clipping what is drawn inside it."""
    radius = min(rect.width(), rect.height()) / 2.0
    shape = QPainterPath()
    shape.addRoundedRect(rect, radius, radius)
    if brush is not None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)
        p.drawRoundedRect(rect, radius, radius)
        p.restore()
    if shade_alpha > 0:
        p.save()
        p.setClipPath(shape)
        end = rect.topLeft() + (
            QPointF(min(shade_depth, rect.width() / 2), 0) if across else QPointF(0, min(shade_depth, rect.height() / 2))
        )
        shade = QLinearGradient(rect.topLeft(), end)
        shade.setColorAt(0.0, QColor(0, 0, 0, shade_alpha))
        shade.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(rect, shade)
        p.restore()
    if light_line is not None:
        p.save()
        p.setPen(QPen(light_line, 1))
        r = rect.height() / 2.0
        p.drawLine(QPointF(rect.left() + r, rect.bottom() + 0.5), QPointF(rect.right() - r, rect.bottom() + 0.5))
        p.restore()
    return shape


def handle(
    p: QPainter,
    rect: QRectF,
    brush,
    edge=None,
    shadow_alpha: int = 70,
    grip: Optional[QColor] = None,
    focus: Optional[QColor] = None,
) -> None:
    """A fader's handle: a pill on a soft shadow 1.5 px below it, with an optional ``edge`` (a QPen or a colour for a 1 px line),
    a ``grip`` line across its middle, and a ``focus`` ring round it when the fader has the keyboard."""
    radius = min(rect.width(), rect.height()) / 2.0
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, shadow_alpha))
    p.drawRoundedRect(rect.translated(0, 1.5), radius, radius)
    p.setBrush(brush if isinstance(brush, (QBrush, QLinearGradient)) else QColor(brush))
    if edge is not None:
        p.setPen(edge if isinstance(edge, QPen) else QPen(QColor(edge), 1))
    p.drawRoundedRect(rect, radius, radius)
    if grip is not None:
        p.setPen(QPen(grip, 1.2))
        centre = rect.center().x()
        p.drawLine(QPointF(centre, rect.top() + 5), QPointF(centre, rect.bottom() - 5))
    if focus is not None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(focus, 2))
        p.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
    p.restore()


# ----------------------------------------------------------------------------- shadows and halos
_SHADOWS: dict = {}
SHADOW_CACHE = 320


def _box_blur(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    if r < 1:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad), axis=axis, dtype=np.float32)
    n = 2 * r + 1
    return (c[n:] - c[:-n]) / n if axis == 0 else (c[:, n:] - c[:, :-n]) / n


def soft_shape(width: float, height: float, blur: int, alpha: float, color: str, ratio: float, radius: float = 12.0) -> tuple:
    """A blurred rounded rectangle, the one way every skin makes a shadow or a halo, as (pixmap, pad): draw it ``pad`` points up
    and left of the shape.
    Blurred once with numpy (three box passes, close to a Gaussian) and cached by size, so it costs nothing to draw again."""
    key = (round(width), round(height), blur, round(alpha, 3), color, round(ratio, 2), round(radius))
    hit = _SHADOWS.get(key)
    if hit is not None:
        return hit
    pad = blur * 2
    w, h = max(1, int((width + 2 * pad) * ratio)), max(1, int((height + 2 * pad) * ratio))
    mask = QImage(w, h, QImage.Format.Format_Grayscale8)
    mask.fill(0)
    p = QPainter(mask)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(QRectF(pad * ratio, pad * ratio, width * ratio, height * ratio), radius * ratio, radius * ratio)
    p.end()
    stride = mask.bytesPerLine()
    a = np.frombuffer(mask.constBits(), dtype=np.uint8, count=stride * h).reshape(h, stride)[:, :w].astype(np.float32)
    r = max(1, int(blur * ratio / 2))
    for _ in range(3):
        a = _box_blur(_box_blur(a, r, 0), r, 1)
    a = np.clip(a * alpha, 0, 255).astype(np.uint8)
    tint = QColor(color)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    premultiply = a.astype(np.float32) / 255.0
    rgba[..., 0] = (tint.blue() * premultiply).astype(np.uint8)  # ARGB32 in memory on little-endian machines: B, G, R, A
    rgba[..., 1] = (tint.green() * premultiply).astype(np.uint8)
    rgba[..., 2] = (tint.red() * premultiply).astype(np.uint8)
    rgba[..., 3] = a
    image = QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_ARGB32_Premultiplied).copy()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    while len(_SHADOWS) >= SHADOW_CACHE:  # the oldest first: Nexus keeps eight steps of glow for each card
        _SHADOWS.pop(next(iter(_SHADOWS)))
    _SHADOWS[key] = (pixmap, pad)
    return pixmap, pad
