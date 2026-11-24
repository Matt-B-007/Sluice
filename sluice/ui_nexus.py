# SPDX-License-Identifier: GPL-3.0-or-later
"""The Nexus cards (0.11.5; called "glass" inside until 0.12.0, when that word became the Glass skin's alone): the floor under the
cards paints each card's shadow and its glow, and the glow grows with the sound coming through the card. The cards are lit at the
top and have an outline from the accent colour (also Calm's soft floor, without the glow); on light
themes there is no glow, and each card has a 3 px top edge in its channel's colour instead.

Painting the glow on the floor, round the card and never under it, keeps it cheap: when the sound changes, only the ring of floor
round that card is repainted, so no control on the card is redrawn. The glow and shadow pictures are blurred once per size and colour
and kept (``ui_paint.soft_shape``); a frame of glow is one copy of a picture at some opacity."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRegion
from PySide6.QtWidgets import QFrame, QWidget

from . import depth, themes

GLOW_ROOM = 18      # how far round a card its glow reaches (the floor repaints this ring, no more)
GLOW_STEPS = 6      # steps of glow: plenty for the eye, and each step is one picture blurred once
GLOW_HZ = 10        # a card's glow follows its sound ten times a second at most (the ring itself moves at fifteen)
RADIUS = 20


class CardFloor(QWidget):
    """The floor under Nexus cards: a shadow under each card and a glow round it that follows its sound."""

    def __init__(self, object_name: str = "channels", soft: bool = False) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.soft = soft  # the Calm look: a light touch of depth, a soft shadow and no glow
        self._cards: dict = {}   # id(card) -> [card, colour, glow shown 0..1, glow wanted 0..1]
        from PySide6.QtCore import QTimer
        self._pacer = QTimer(self)  # brings the glows that changed up to date, at most GLOW_HZ times a second
        self._pacer.setInterval(1000 // GLOW_HZ)
        self._pacer.timeout.connect(self._catch_up)

    def add(self, card: QWidget, color: str) -> None:
        self._cards[id(card)] = [card, color, 0.0, 0.0]
        card.destroyed.connect(lambda _o=None, key=id(card): self._cards.pop(key, None))

    def set_color(self, card: QWidget, color: str) -> None:
        entry = self._cards.get(id(card))
        if entry is not None and entry[1] != color:
            entry[1] = color
            self._repaint_round(card)

    def set_glow(self, card: QWidget, amount: float) -> None:
        entry = self._cards.get(id(card))
        if entry is None:
            return
        amount = 0.0 if themes.reduce_effects() else round(max(0.0, min(1.0, amount)) * GLOW_STEPS) / GLOW_STEPS
        entry[3] = amount
        if amount != entry[2] and not self._pacer.isActive():
            self._pacer.start()

    def _catch_up(self) -> None:
        glows = self._glows()
        waiting = False
        for entry in self._cards.values():
            if entry[3] != entry[2]:
                entry[2] = entry[3]
                waiting = True
                if glows:
                    self._repaint_round(entry[0])
        if not waiting:
            self._pacer.stop()

    def glow_of(self, card: QWidget) -> float:
        entry = self._cards.get(id(card))
        return entry[2] if entry is not None else 0.0

    def refresh_theme(self) -> None:
        self.update()

    def _glows(self) -> bool:
        return depth.depth_colors(themes._current)["glow"] and not themes.reduce_effects()

    def _repaint_round(self, card: QWidget) -> None:
        """Repaint the floor round a card (its glow and shadow), not under it: the card and its controls are left alone."""
        rect = card.geometry()
        if not self.isVisible() or not card.isVisible():
            return
        around = QRegion(rect.adjusted(-GLOW_ROOM, -GLOW_ROOM, GLOW_ROOM, GLOW_ROOM + 12))
        for other, *_rest in self._cards.values():  # never under a card (this one or a neighbour): no control is redrawn
            if other.isVisible():
                g = other.geometry()  # all of the card but its rounded corners, where the floor shows through
                around = around.subtracted(QRegion(g.adjusted(0, RADIUS, 0, -RADIUS))).subtracted(QRegion(g.adjusted(RADIUS, 0, -RADIUS, 0)))
        self.update(around)

    def _static_layer(self, d: dict, ratio: float):
        """Every card's shadow, drawn once into one picture and kept until a card moves or the theme changes: a frame of glow then
        copies the part of it that is being repainted, instead of drawing every shadow again."""
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt
        from .ui_tile_paint import soft_shape

        cards = tuple((card.geometry().getRect(), card.isVisible()) for card, *_rest in self._cards.values())
        key = (self.size().toTuple(), round(ratio * 100), themes.generation(), cards, self.soft)
        if getattr(self, "_static_key", None) == key:
            return self._static
        layer = QPixmap(max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio)))
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        q = QPainter(layer)
        if d["shadow_alpha"] > 0:
            for card, *_rest in self._cards.values():
                if not card.isVisible():
                    continue
                rect = card.geometry()
                strength = (1.5 if not d["light"] else 1.3) * (0.55 if self.soft else 1.0)
                pixmap, pad = soft_shape(rect.width() - 12, rect.height() - 6, 10 if self.soft else 12, d["shadow_alpha"] * strength,
                                         d["shadow"], ratio, RADIUS if not self.soft else 24)
                drop = (12 if not d["light"] else 7) * (0.6 if self.soft else 1.0)
                q.drawPixmap(QPointF(rect.x() + 6 - pad, rect.y() + 3 - pad + drop), pixmap)
        q.end()
        self._static, self._static_key = layer, key
        return layer

    def paintEvent(self, event) -> None:
        from PySide6.QtCore import QRectF
        from .ui_tile_paint import soft_shape

        d = depth.depth_colors(themes._current)
        glows = d["glow"] and not themes.reduce_effects() and not self.soft
        ratio = self.devicePixelRatioF()
        p = QPainter(self)
        area = event.rect()
        layer = self._static_layer(d, ratio)
        p.drawPixmap(QRectF(area), layer, QRectF(area.x() * ratio, area.y() * ratio, area.width() * ratio, area.height() * ratio))
        if glows:
            for card, color, glow, _wanted in list(self._cards.values()):
                if glow <= 0.01 or not card.isVisible():
                    continue
                rect = card.geometry()
                if not rect.adjusted(-GLOW_ROOM, -GLOW_ROOM, GLOW_ROOM, GLOW_ROOM).intersects(area):
                    continue
                # one picture per step of glow (eight), blurred once and kept: no painting at reduced opacity, which is slow
                pixmap, pad = soft_shape(rect.width(), rect.height(), 7, round(0.9 * (0.18 + 0.62 * glow), 3), color, ratio, RADIUS)
                p.drawPixmap(QPointF(rect.x() - pad, rect.y() - pad), pixmap)
        p.end()


def card_edge_sheet(object_name: str, tint: str) -> str:
    """The per-card part of a Nexus card: a top edge in the card's colour (3 px on light themes, a 1 px lit line on dark ones)."""
    d = depth.depth_colors(themes._current)
    if d["light"]:
        return f"QFrame#{object_name} {{ border-top: 3px solid {tint}; }}"
    return f"QFrame#{object_name} {{ border-top: 1px solid {themes.mix(themes.color('panel'), tint, 0.75)}; }}"


def floor_of(widget: QWidget):
    """The CardFloor a card sits on, or None."""
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, CardFloor):
        parent = parent.parentWidget()
    return parent



_card_cache: tuple = (None, None)


def _card_colors() -> dict:
    global _card_cache
    if _card_cache[0] != themes.generation():
        from .skin_nexus import card_values
        _card_cache = (themes.generation(), card_values(themes._current))
    return _card_cache[1]


def card_backdrop(widget: QWidget):
    """What is behind ``widget`` on its card, as a brush in its own coordinates: the card gradient in Nexus, the card's plain colour
    in Calm, or None (another look, or not on a card). A widget that paints this first can be opaque, so a meter frame redraws only
    the meter, not the card and the floor under it (0.11.5)."""
    skin = themes.current_skin()
    if skin == "nexus":
        return card_gradient(widget)
    if skin != "calm":
        return None
    card = widget.parentWidget()
    while card is not None and not (isinstance(card, QFrame) and card.objectName() in ("strip", "mix")):
        card = card.parentWidget()
    if card is None or card.objectName() == "strip" and card.parentWidget() is not None and card.property("rows"):
        return None
    return QColor(themes.color("panel" if card.objectName() == "strip" else "mix"))


def card_gradient(widget: QWidget):
    """The Nexus card's own gradient (as the style sheet paints it) in ``widget``'s coordinates, or None when it is not on a card.
    A widget that paints this behind itself can be opaque, so Qt redraws only that widget, not the card under it, when it changes:
    the Nexus ring does, so a moving ring costs one small picture instead of the whole card."""
    card = widget.parentWidget()
    while card is not None and not (isinstance(card, QFrame) and card.objectName() in ("strip", "mix")):
        card = card.parentWidget()
    if card is None:
        return None
    top = widget.mapFrom(card, QPoint(0, 0)).y()
    bottom = top + card.height()
    g = _card_colors()
    gradient = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
    gradient.setColorAt(0.0, QColor(g["card_top"]))
    gradient.setColorAt(0.4, QColor(themes.color("panel")))
    gradient.setColorAt(1.0, QColor(g["card_bottom"]))
    return gradient
