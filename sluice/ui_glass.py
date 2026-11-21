# SPDX-License-Identifier: GPL-3.0-or-later
"""Glass in the main window (0.11.7): two ways to have something behind the frosted panes.

- See-through (KDE Plasma, with KWin's blur available): the window itself is see-through, KWin blurs the wallpaper behind it, and a
  light tint of the theme's background keeps text readable. Chosen when the window is made (a window's see-through-ness is fixed
  when it first appears on Wayland), so turning it on or off takes effect at the next start.
- Elsewhere, or with "See-through window" off: Sluice paints a backdrop of soft shapes in the theme's colours behind the panes,
  with a fine grain, and the see-through panes frost it.

Reduce effects turns both off (the panes then sit on the plain gradient)."""
from __future__ import annotations

import random
from functools import lru_cache

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRadialGradient

from . import depth, desktop_place, themes

# where the soft shapes sit (fractions of the window) and how big they are (fraction of its larger side)
SHAPES = ((0.10, 0.10, 0.45), (0.45, 0.55, 0.42), (0.88, 0.05, 0.38), (0.92, 0.85, 0.42), (0.20, 0.92, 0.35))


def wants_see_through(mixer, env=None, blur=None) -> bool:
    """Whether the main window should be made see-through: Glass, the setting on, effects not reduced, and KWin's blur usable."""
    if themes.valid_look(mixer.look) != "glass" or not getattr(mixer, "see_through", True) or mixer.reduce_effects:
        return False
    if not desktop_place.kde(env):
        return False
    return (blur or desktop_place.blur()).available


@lru_cache(maxsize=1)
def grain() -> QImage:
    """A small tile of faint noise, so the backdrop reads as a surface rather than a flat gradient."""
    rng = random.Random(7)
    image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    for y in range(96):
        for x in range(96):
            value = rng.randint(0, 255)
            alpha = rng.randint(0, 10)
            image.setPixelColor(x, y, QColor(value, value, value, alpha))
    return image


@lru_cache(maxsize=4)
def backdrop(width: int, height: int, items: tuple, ratio: float) -> QPixmap:
    """The backdrop for a window this size in these colours (cached: a resize or a new theme draws it again, nothing else)."""
    from .skin_glass import backdrop_colours
    values = dict(items)
    light = depth.luminance(values["panel"]) >= depth.LIGHT_PANEL
    pixmap = QPixmap(max(1, round(width * ratio)), max(1, round(height * ratio)))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor(values["bg"]))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = max(width, height)
    strength = 0.38 if light else 0.55
    for (fx, fy, size), colour in zip(SHAPES, backdrop_colours(values)):
        centre = QPointF(fx * width, fy * height)
        radius = size * side
        gradient = QRadialGradient(centre, radius)
        inner = QColor(colour)
        inner.setAlphaF(strength)
        outer = QColor(colour)
        outer.setAlphaF(0.0)
        gradient.setColorAt(0.0, inner)
        gradient.setColorAt(0.55, QColor(inner.red(), inner.green(), inner.blue(), round(255 * strength * 0.45)))
        gradient.setColorAt(1.0, outer)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawEllipse(centre, radius, radius)
    p.drawTiledPixmap(QRectF(0, 0, width, height), QPixmap.fromImage(grain()))
    p.end()
    return pixmap


class GlassBackdrop(QObject):
    """Paints the backdrop behind the window's content and its status bar in the Glass skin: one picture the size of the window,
    each part showing its own piece of it, so the shapes run on under the status bar."""

    def __init__(self, window, *parts) -> None:
        super().__init__(window)
        self.window = window
        self.parts = []
        for part in parts:
            self.watch(part)

    def watch(self, part) -> None:
        if part is not None and part not in self.parts:
            self.parts.append(part)
            part.installEventFilter(self)

    def active(self) -> bool:
        return themes.current_look() == "glass" and not themes.see_through() and not themes.reduce_effects()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Paint and obj in self.parts and self.active():
            w = self.window
            p = QPainter(obj)
            colours = tuple(sorted(themes._current.items()))
            offset = obj.mapTo(w, obj.rect().topLeft()) if obj is not w else obj.rect().topLeft()
            p.drawPixmap(-offset.x(), -offset.y(), backdrop(w.width(), w.height(), colours, obj.devicePixelRatioF()))
            p.end()
            return True  # the backdrop instead of the sheet's plain gradient
        return False


def make_see_through(window) -> None:
    """Before the window first shows: make it see-through (the root and status bar then carry only a light tint)."""
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    themes.set_see_through(True)


def blur_window(window) -> bool:
    """Once shown: ask KWin to blur the wallpaper behind the whole window. Returns whether it was asked."""
    handle = window.windowHandle()
    if handle is None:
        return False
    from PySide6.QtGui import QRegion
    return desktop_place.blur().set(handle, True, QRegion())
