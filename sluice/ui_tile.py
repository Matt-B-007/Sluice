# SPDX-License-Identifier: GPL-3.0-or-later
"""The Tile look's channel tiles (chosen direction, 2026-11-19).

A folded tile is 264 x 232: a header (tinted icon well, name, source line, link toggle, overflow menu), one lane for each mix
(Listen with headphones, Broadcast with waves: a mute button, one track that is both the fader and the meter, and the value in
dB) and a footer (the effects button and the fold-out chevron). Every main control works while the tile is folded; folding it
out adds detail and never repeats a control: bigger lanes with a dB scale, the effects as chips in chain order that switch on and
off, and the apps on the channel, each with a small meter and a Move button.

The track: a soft fill is the fader position, a brighter fill is the live signal, a thin tick holds the peak. Muted, the track is
striped, the handle grey and the button red. Clipping turns the peak tick and the track's outline red, and the source line says
when it clipped. A linked channel shows a short bar joining its handles. A tile with the keyboard focus has a 1.5 px ring in its
channel's colour and a soft halo.

Tiles are dragged by their header: the tile lifts (tilted a little, a deeper shadow) and a dashed "Drop here" slot shows where it
will land. The compact list uses mini tiles: one lane each, with the Listen/Broadcast switch at the top.

Everything here paints with the theme's colours (``look_tile.paint_colors``) and caches what it can: a tile's surface, shadow and
focus halo are one pixmap, redrawn only when its size, focus or theme changes."""
from __future__ import annotations

from functools import partial
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import look_tile, themes
from . import ui_icons as icons
from .flow import FlowLayout
from .model import MIN_DB
from .ui import (EMPTY_HINTS, ChannelStrip, ElidedLabel, Fader, SourcePicture, db_to_fader_position, format_db, level_fraction,
                 mute_tip)
from .ui_widgets import ReadoutEdit

TILE_W, TILE_H = 264, 232      # a folded tile
OPEN_W = 360                   # a folded-out tile (its height follows what it holds)
LANE_EXTRA_H = 38              # each lane past the second (the Recording mix) makes a folded tile this much taller
SHADOW = (10, 6, 10, 14)       # left, top, right, bottom: the room around a tile for its shadow and halo
PAD = 14                       # inside the tile's edge
SKIRT = 6                      # the key's thick lower edge, inside the tile's footprint
RADIUS = 12.0
CLIP_HOLD = 2.0                # seconds the track stays outlined in red after a clip
CLIP_NOTE = 60.0               # seconds the source line says when it clipped
FREE_STEP = (TILE_W + SHADOW[0] + SHADOW[2] + 6, TILE_H + SHADOW[1] + SHADOW[3] + 6)  # the Free layout's grid for tiles
SCALE_MARKS = ((MIN_DB, "-∞"), (-40.0, "-40"), (-20.0, "-20"), (-10.0, "-10"), (0.0, "0"), (6.0, "+6"), (12.0, "+12"))


# ----------------------------------------------------------------------------- painting helpers
_SHADOWS: dict = {}


def _box_blur(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    if r < 1:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad), axis=axis, dtype=np.float32)
    n = 2 * r + 1
    return (c[n:] - c[:-n]) / n if axis == 0 else (c[:, n:] - c[:, :-n]) / n


def soft_shape(width: float, height: float, blur: int, alpha: float, color: str, ratio: float, radius: float = RADIUS) -> tuple:
    """A blurred rounded rectangle (a shadow or a halo) as (pixmap, pad): draw it ``pad`` points up and left of the shape.
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
    rgba[..., 0] = (tint.blue() * premultiply).astype(np.uint8)   # ARGB32 in memory on little-endian machines: B, G, R, A
    rgba[..., 1] = (tint.green() * premultiply).astype(np.uint8)
    rgba[..., 2] = (tint.red() * premultiply).astype(np.uint8)
    rgba[..., 3] = a
    image = QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_ARGB32_Premultiplied).copy()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    if len(_SHADOWS) > 64:
        _SHADOWS.clear()
    _SHADOWS[key] = (pixmap, pad)
    return pixmap, pad


def paint_surface(p: QPainter, rect: QRectF, ratio: float, focus: Optional[str] = None, lifted: bool = False,
                  shadow: bool = True, radius: float = RADIUS, skirt: int = SKIRT) -> None:
    """One key, in ``rect`` (its whole footprint): the soft shadow under it, its skirt (the thick lower edge), the face lit from above,
    and the halo and ring when it has the focus. Painted once into a cached pixmap by whoever owns the key."""
    pc = look_tile.paint_colors()
    face = rect.adjusted(0, 0, 0, -skirt)
    if shadow:
        blur, alpha, drop = (12, pc["shadow"] * 2.0, skirt + 6) if lifted else (7, pc["shadow"] * 1.5, skirt + 2)
        pixmap, pad = soft_shape(face.width(), face.height(), blur, alpha, "#000000", ratio, radius)
        p.drawPixmap(QPointF(face.x() - pad, face.y() - pad + drop), pixmap)
    if focus:
        pixmap, pad = soft_shape(face.width(), face.height() + skirt, 6, 0.55, focus, ratio, radius)
        p.drawPixmap(QPointF(face.x() - pad, face.y() - pad), pixmap)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(pc["skirt_dark"]))
    p.drawRoundedRect(face.translated(0, skirt + 1), radius, radius)
    p.setBrush(QColor(pc["skirt"]))
    p.drawRoundedRect(face.translated(0, skirt), radius, radius)
    gradient = QLinearGradient(face.topLeft(), face.bottomLeft())
    gradient.setColorAt(0.0, QColor(pc["face_top"]))
    gradient.setColorAt(1.0, QColor(pc["face_bottom"]))
    p.setBrush(gradient)
    edge = QColor(0, 0, 0, 14 if pc["light"] else 60)
    p.setPen(QPen(edge, 1))
    p.drawRoundedRect(face.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    highlight = QColor(255, 255, 255, 255 if pc["light"] else 24)  # the lit top edge
    p.setPen(QPen(highlight, 1))
    p.drawLine(QPointF(face.left() + radius, face.top() + 1.5), QPointF(face.right() - radius, face.top() + 1.5))
    if focus:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(focus), 1.5))
        p.drawRoundedRect(face.adjusted(0.75, 0.75, -0.75, -0.75), radius - 0.5, radius - 0.5)


def face_gradient(widget: QWidget, frame) -> Optional[QLinearGradient]:
    """The key face's gradient in ``widget``'s own coordinates, so a widget on the face can paint the face behind itself (and be
    opaque: Qt then repaints only that widget, not the key under it, when it changes)."""
    if frame is None:
        return None
    face = frame.face_rect()
    top = widget.mapFrom(frame, QPoint(0, round(face.top()))).y()
    bottom = widget.mapFrom(frame, QPoint(0, round(face.bottom()))).y()
    pc = look_tile.paint_colors()
    gradient = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
    gradient.setColorAt(0.0, QColor(pc["face_top"]))
    gradient.setColorAt(1.0, QColor(pc["face_bottom"]))
    return gradient


def frame_of(widget: QWidget):
    """The TileFrame a widget sits on, or None."""
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, TileFrame):
        parent = parent.parentWidget()
    return parent


_STRIPES: dict = {}
_HANDLES: dict = {}


def stripe_brush(base: str, stripe: str) -> QBrush:
    """The diagonal stripes of a muted track, as one small tile Qt repeats (not forty lines a frame)."""
    key = (base, stripe)
    brush = _STRIPES.get(key)
    if brush is None:
        tile = QPixmap(8, 8)
        tile.fill(QColor(base))
        q = QPainter(tile)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setPen(QPen(QColor(stripe), 2.5))
        for offset in (-8, 0, 8):
            q.drawLine(QPointF(offset, 8), QPointF(offset + 8, 0))
        q.end()
        brush = QBrush(tile)
        _STRIPES[key] = brush
    return brush


def paint_groove(p: QPainter, shape: QPainterPath, track: QRectF, pc: dict) -> None:
    """A groove pressed into the face: dark at its top edge (in shadow), a faint light line at its bottom edge."""
    p.save()
    p.setClipPath(shape)
    shade = QLinearGradient(track.topLeft(), QPointF(track.left(), track.top() + min(5.0, track.height() / 2)))
    shade.setColorAt(0.0, QColor(0, 0, 0, round(255 * pc["groove_shadow"] * 0.55)))
    shade.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(track, shade)
    p.restore()
    light = QColor(255, 255, 255, 230 if pc["light"] else 14)
    p.setPen(QPen(light, 1))
    r = track.height() / 2.0
    p.drawLine(QPointF(track.left() + r, track.bottom() + 0.5), QPointF(track.right() - r, track.bottom() + 0.5))


def paint_handle(p: QPainter, thumb: QRectF, pc: dict, muted: bool) -> None:
    """A raised white handle with a soft shadow and a grip line."""
    radius = min(thumb.width(), thumb.height()) / 2.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 70 if pc["light"] else 130))
    p.drawRoundedRect(thumb.translated(0, 1.5), radius, radius)
    if muted:
        p.setBrush(QColor(pc["handle_muted"]))
    else:
        gradient = QLinearGradient(thumb.topLeft(), thumb.bottomLeft())
        gradient.setColorAt(0.0, QColor(pc["handle"]))
        gradient.setColorAt(1.0, QColor(pc["handle_bottom"]))
        p.setBrush(gradient)
    if pc["light"]:
        p.setPen(QPen(QColor(0, 0, 0, 30), 1))
    p.drawRoundedRect(thumb, radius, radius)
    p.setPen(QPen(QColor(0, 0, 0, 55), 1.2))
    centre = thumb.center().x()
    p.drawLine(QPointF(centre, thumb.top() + 5), QPointF(centre, thumb.bottom() - 5))


def paint_slot(p: QPainter, rect: QRectF) -> None:
    """Where a dragged tile will land: a dashed outline and "Drop here"."""
    pc = look_tile.paint_colors()
    floor = QColor(pc["track"])
    floor.setAlpha(110)
    pen = QPen(QColor(pc["dashed"]), 1.5, Qt.PenStyle.CustomDashLine)
    pen.setDashPattern([5, 4])
    p.setPen(pen)
    p.setBrush(floor)
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), RADIUS, RADIUS)
    p.setPen(QColor(pc["text2"]))
    font = QFont(p.font())
    font.setPixelSize(12)
    p.setFont(font)
    band = QRectF(rect.left(), rect.bottom() - 40, rect.width(), 30)  # the lifted tile hangs over the middle: the label is below it
    p.drawText(band, Qt.AlignmentFlag.AlignCenter, "Drop here")


class TileFrame(QFrame):
    """The painted part of a tile: everything under its controls. ``margins`` is the room left round the tile for its shadow."""

    def __init__(self, margins: tuple = SHADOW, radius: float = RADIUS) -> None:
        super().__init__()
        self.setObjectName("tileframe")
        self.margins = margins
        self.radius = radius
        self.focus_color: Optional[str] = None
        self.slot = False
        self.shadow = True
        self.lifted = False
        self._cache = None
        self._cache_key = None

    def tile_rect(self) -> QRectF:
        left, top, right, bottom = self.margins
        return QRectF(self.rect()).adjusted(left, top, -right, -bottom)

    def face_rect(self) -> QRectF:
        """The key's top face (its footprint without the skirt)."""
        return self.tile_rect().adjusted(0, 0, 0, -SKIRT)

    def set_focus_color(self, color: Optional[str]) -> None:
        if color != self.focus_color:
            self.focus_color = color
            self.update()

    def set_slot(self, on: bool) -> None:
        self.slot = on
        self.update()

    def set_lifted(self, on: bool) -> None:
        if on != self.lifted:
            self.lifted = on
            self.update()

    def refresh_theme(self) -> None:
        self._cache = None
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        if self.slot:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_slot(p, self.tile_rect())
            p.end()
            return
        ratio = self.devicePixelRatioF()
        key = (self.size(), self.focus_color, ratio, themes.generation(), self.shadow, self.lifted, self.radius)
        if self._cache is None or key != self._cache_key:
            pixmap = QPixmap(max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_surface(q, self.tile_rect(), ratio, self.focus_color, lifted=self.lifted, shadow=self.shadow, radius=self.radius)
            q.end()
            self._cache, self._cache_key = pixmap, key
        p.drawPixmap(0, 0, self._cache)
        p.end()


class IconWell(QWidget):
    """The channel's tinted icon well: its identity colour, faint behind and full on the drawing (or its first letter)."""

    def __init__(self, color: str, icon: str, letter: str, size: int = 32) -> None:
        super().__init__()
        self.color, self.icon_name, self.letter, self.size_ = color, icon, (letter[:1] or "?").upper(), size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pc = look_tile.paint_colors()
        well = QColor(themes.mix(pc["surface"], self.color, 0.16 if not pc["light"] else 0.14))
        edge = QColor(themes.mix(pc["surface"], self.color, 0.30))
        p.setPen(QPen(edge, 1))
        p.setBrush(well)
        r = self.size_ * 0.28
        p.drawRoundedRect(QRectF(0.5, 0.5, self.size_ - 1, self.size_ - 1), r, r)
        if self.icon_name:
            ratio = self.devicePixelRatioF()
            px = round(self.size_ * 0.56)
            pixmap = icons.render(self.icon_name, self.color, round(px * ratio))
            pixmap.setDevicePixelRatio(ratio)
            offset = (self.size_ - px) / 2.0
            p.drawPixmap(QPointF(offset, offset), pixmap)
        else:
            font = QFont(p.font())
            font.setPixelSize(round(self.size_ * 0.44))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(self.color))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.letter)
        p.end()


# ----------------------------------------------------------------------------- the track: fader and meter in one
class TileLane(Fader):
    """One lane's track: the fader and the meter in one. A soft fill up to the handle is the fader position; a brighter fill is the
    live signal (on the fader's own scale, so a full-scale signal through a fader at 0 dB reaches the handle); a thin tick holds
    the peak. Muted: striped, with a grey handle. Clipping: a red tick and a red outline. Keyboard, wheel and double-click work as
    on every Sluice fader. Repaints only when what it shows changes."""

    FALL = 0.011        # as LevelMeter: about 20 dB a second at 30 frames a second
    HOLD_FRAMES = 45
    PEAK_FALL = 0.006

    def __init__(self, color: str, on_clip=None) -> None:
        super().__init__(horizontal=True, thumb=(12, 18))
        self.set_fill(color)
        self.big = False
        self.muted = False
        self.link_up = self.link_down = False
        self.on_clip = on_clip
        self._level = 0.0
        self._peak = 0.0
        self._peak_age = 0
        self._clip_at = -1e9
        self._painted = None
        self.setMinimumWidth(72)
        self.setFixedHeight(28)
        self.setToolTip("Drag, scroll or use the arrow keys to set the level. Double-click for 0 dB.\n"
                        "Soft fill: the fader. Bright fill: the live signal. Tick: the recent peak.")

    # -- state
    def set_big(self, on: bool) -> None:
        self.big = on
        self.thumb = (14, 22) if on else (12, 18)
        self.setFixedHeight(44 if on else 28)
        self.update()

    def set_muted(self, on: bool) -> None:
        if on != self.muted:
            self.muted = on
            self.update()

    def set_links(self, up: bool, down: bool) -> None:
        if (up, down) != (self.link_up, self.link_down):
            self.link_up, self.link_down = up, down
            self.update()

    def clipping(self) -> bool:
        return time.monotonic() - self._clip_at < CLIP_HOLD

    def refresh_theme(self) -> None:
        self._painted = None
        self.update()

    # -- the meter
    def push(self, linear: float) -> None:
        if linear >= 0.999:
            self._clip_at = time.monotonic()
            if self.on_clip is not None:
                self.on_clip()
        frac = level_fraction(linear)
        self._level = max(frac, self._level - self.FALL)
        if frac >= self._peak:
            self._peak, self._peak_age = frac, 0
        else:
            self._peak_age += 1
            if self._peak_age > self.HOLD_FRAMES:
                self._peak = max(self._level, self._peak - self.PEAK_FALL)
        if self._shown() != self._painted:  # a silent, settled track costs nothing
            self.update()

    def _x_for(self, db: float) -> float:
        half, span = self._travel()
        return half + db_to_fader_position(db) * span

    def _shown(self) -> tuple:
        live = round(self._x_for(MIN_DB * (1.0 - self._level))) if self._level > 0.005 else -1
        peak = round(self._x_for(MIN_DB * (1.0 - self._peak))) if self._peak > 0.02 else -1
        return live, peak, self.clipping()

    def _track_rect(self) -> QRectF:
        height = 12.0 if self.big else 8.0
        centre = 14.0
        return QRectF(0.5, centre - height / 2.0, self.width() - 1.0, height)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._frame = frame_of(self)
        # On a key the track paints the face behind itself, so a meter frame repaints only the track, never the key under it.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, self._frame is not None)

    def _base_and_overlay(self, pc: dict, track: QRectF, shape: QPainterPath) -> tuple:
        """What does not move, drawn once per size, state and theme: (base, overlay). The base is the face behind the track, the
        groove (or its stripes) and the dB scale; the overlay is the groove's shading, drawn over the fills so they sit in it."""
        frame = getattr(self, "_frame", None)
        face = frame.face_rect() if frame is not None else None
        offsets = ((self.mapFrom(frame, QPoint(0, round(face.top()))).y(), self.mapFrom(frame, QPoint(0, round(face.bottom()))).y())
                   if frame is not None else None)
        ratio = self.devicePixelRatioF()
        key = (self.size(), ratio, themes.generation(), self.muted, self.big, offsets)
        if getattr(self, "_base_key", None) != key:
            def canvas() -> QPixmap:
                pixmap = QPixmap(max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio)))
                pixmap.setDevicePixelRatio(ratio)
                pixmap.fill(Qt.GlobalColor.transparent)
                return pixmap
            base, overlay = canvas(), canvas()
            q = QPainter(base)
            background = face_gradient(self, frame)
            if background is not None:
                q.fillRect(QRectF(0, 0, self.width(), self.height()), background)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(stripe_brush(pc["track"], pc["stripe"]) if self.muted else QColor(pc["track"]))
            q.drawPath(shape)
            if self.big:
                self._paint_scale(q, track, pc)
            q.end()
            q = QPainter(overlay)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_groove(q, shape, track, pc)
            q.end()
            self._base, self._overlay, self._base_key = base, overlay, key
        return self._base, self._overlay

    def _handle_pixmap(self, pc: dict) -> tuple:
        """The handle (with its shadow) as a picture, and where its top-left sits relative to the handle's own rectangle."""
        tw, th = self.thumb
        ratio = self.devicePixelRatioF()
        key = (tw, th, ratio, themes.generation(), self.muted)
        cached = _HANDLES.get(key)
        if cached is None:
            room = 3
            pixmap = QPixmap(int((tw + 2 * room) * ratio), int((th + 2 * room) * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_handle(q, QRectF(room, room, tw, th), pc, self.muted)
            q.end()
            cached = (pixmap, room)
            if len(_HANDLES) > 32:
                _HANDLES.clear()
            _HANDLES[key] = cached
        return cached

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        pc = look_tile.paint_colors()
        track = self._track_rect()
        radius = track.height() / 2.0
        shape = QPainterPath()
        shape.addRoundedRect(track, radius, radius)
        base, overlay = self._base_and_overlay(pc, track, shape)
        p.drawPixmap(0, 0, base)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = float(round(self._centre()))
        live, peak, clipping = self._shown()
        if not self.muted:  # the fills: pills from the left end of the groove (no clip path: a frame must stay cheap)
            p.setPen(Qt.PenStyle.NoPen)
            color = QColor(self.fill_color)
            soft = QColor(color)
            soft.setAlphaF(0.28)
            p.setBrush(soft)
            p.drawRoundedRect(QRectF(track.left(), track.top(), max(track.height(), centre - track.left()), track.height()), radius, radius)
            if live >= 0:
                p.setBrush(color)
                p.drawRoundedRect(QRectF(track.left(), track.top(), max(track.height(), live - track.left()), track.height()), radius, radius)
        p.drawPixmap(0, 0, overlay)
        if clipping:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pc["red"]), 1))
            p.drawPath(shape)
        if peak >= 0 and not self.muted:
            tick = QColor(pc["red"]) if clipping else QColor(pc["text"])
            if not clipping:
                tick.setAlphaF(0.8)
            p.setPen(QPen(tick, 2))
            p.drawLine(QPointF(peak, track.top() - 2), QPointF(peak, track.bottom() + 2))
        tw, th = self.thumb
        thumb = QRectF(centre - tw / 2.0, track.center().y() - th / 2.0, tw, th)
        if self.link_up or self.link_down:  # the short bar that joins a linked channel's handles
            p.setPen(QPen(QColor(pc["text2"]), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            if self.link_up:
                p.drawLine(QPointF(centre, 0), QPointF(centre, thumb.top()))
            if self.link_down:
                p.drawLine(QPointF(centre, thumb.bottom()), QPointF(centre, self.height()))
        handle, room = self._handle_pixmap(pc)
        p.drawPixmap(QPointF(thumb.left() - room, thumb.top() - room), handle)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pc["focus"]), 2))
            p.drawRoundedRect(thumb.adjusted(-2.5, -2.5, 2.5, 2.5), tw / 2.0 + 2.5, tw / 2.0 + 2.5)
        p.end()
        self._painted = (live, peak, clipping)

    _scale_font = None

    def _paint_scale(self, p: QPainter, track: QRectF, pc: dict) -> None:
        if TileLane._scale_font is None:
            font = QFont(look_tile.VALUE_FAMILIES[0])
            font.setFamilies(look_tile.VALUE_FAMILIES)
            font.setPixelSize(9)
            TileLane._scale_font = (font, QFontMetrics(font))
        font, metrics = TileLane._scale_font
        p.setFont(font)
        top = track.bottom() + 4
        last_right = -1e9
        bar = round(self._centre()) if self.link_down else None  # the link bar runs down through the scale here
        for db, text in SCALE_MARKS:
            x = self._x_for(db)
            p.setPen(QPen(QColor(pc["text_off"]), 1))
            p.drawLine(QPointF(x, top), QPointF(x, top + 3))
            width = metrics.horizontalAdvance(text)
            left = max(0.0, min(self.width() - width, x - width / 2.0))
            if left < last_right + 4:
                continue  # too close to the last label: the tick says enough
            if bar is not None and left - 3 < bar < left + width + 3:
                continue
            p.setPen(QColor(pc["text_off"]))
            p.drawText(QRectF(left, top + 4, width + 1, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text)
            last_right = left + width


class TileLanes(QWidget):
    """The lanes of a tile, one under another. For a linked channel it draws the part of the link bar between two tracks (each
    track draws its own stub from the handle to its edge), so the bar joins the handles even when they are not lined up."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tilelanes")
        self.lanes: list = []
        self.linked = False
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(10)

    def add_lane(self, row: QWidget, lane: TileLane) -> None:
        self.box.addWidget(row)
        self.lanes.append(lane)
        lane.valueChanged.connect(lambda _v: self.update())

    def set_linked(self, on: bool) -> None:
        self.linked = on
        for i, lane in enumerate(self.lanes):
            lane.set_links(on and i > 0, on and i < len(self.lanes) - 1)
        self.update()

    def paintEvent(self, _event) -> None:
        if not self.linked or len(self.lanes) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(look_tile.paint_colors()["text2"]), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap,
                      Qt.PenJoinStyle.RoundJoin))
        for upper, lower in zip(self.lanes, self.lanes[1:]):
            a = upper.mapTo(self, QPoint(round(upper._centre()), upper.height()))
            b = lower.mapTo(self, QPoint(round(lower._centre()), 0))
            mid = (a.y() + b.y()) / 2.0
            path = QPainterPath(QPointF(a))
            path.lineTo(QPointF(a.x(), mid))
            path.lineTo(QPointF(b.x(), mid))
            path.lineTo(QPointF(b))
            p.drawPath(path)
        p.end()


class AppMeter(QWidget):
    """A small level bar beside an app in a folded-out tile."""

    def __init__(self, color: str) -> None:
        super().__init__()
        self.color = color
        self.setFixedSize(40, 6)
        self._level = 0.0
        self._painted = -1

    def push(self, linear: float) -> None:
        frac = level_fraction(linear)
        self._level = max(frac, self._level - 0.011)
        shown = int(self._level * self.width())
        if shown != self._painted:
            self.update()

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        shape = QPainterPath()
        shape.addRoundedRect(rect, 3, 3)
        pc = look_tile.paint_colors()
        p.setClipPath(shape)
        p.fillRect(rect, QColor(pc["track"]))
        shown = int(self._level * self.width())
        if shown > 0:
            p.fillRect(QRectF(0, 0, shown, rect.height()), QColor(self.color))
        p.setClipping(False)
        paint_groove(p, shape, rect.adjusted(0, 0, 0, -1), pc)
        p.end()
        self._painted = shown


class TileGrip(QWidget):
    """The header's icon, name and source line: the handle a tile is moved by. A click focuses the tile; a double-click on the name
    renames the channel."""

    def __init__(self, owner) -> None:
        super().__init__()
        self.setObjectName("tilegrip")
        self.owner = owner
        self._press: Optional[QPoint] = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._dragging = False
            self.owner.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        point = event.globalPosition().toPoint()
        mover = self.owner.mover()
        if mover is None:
            return
        if not self._dragging and (point - self._press).manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            mover.begin(self.owner, self._press)
        if self._dragging:
            mover.move(point)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            if self._dragging:
                mover = self.owner.mover()
                if mover is not None:
                    mover.drop(event.globalPosition().toPoint())
            self._press = None
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        rename = getattr(self.owner, "rename", None)
        title = getattr(self.owner, "title", None)
        if rename is not None and title is not None and title.geometry().contains(title.parentWidget().mapFrom(self, event.position().toPoint())):
            rename()
        event.accept()


def _focus_tracker(widget) -> None:
    """Give a tile its focus ring while it or any control on it has the keyboard focus."""
    app = QApplication.instance()

    def changed(_old, new) -> None:
        try:
            inside = new is not None and (new is widget or widget.isAncestorOf(new))
            widget.frame.set_focus_color(widget.tint if inside else None)
        except RuntimeError:  # the tile is gone
            pass

    app.focusChanged.connect(changed)
    widget.destroyed.connect(lambda *_a: _disconnect(app, changed))


def _disconnect(app, slot) -> None:
    try:
        app.focusChanged.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("tilesection")
    return label


def _small_button(name: str, tip: str, object_name: str = "tileicon", checkable: bool = False, size: int = 28) -> QPushButton:
    button = QPushButton()
    button.setObjectName(object_name)
    button.setFixedSize(size, size)
    button.setToolTip(tip)
    button.setAccessibleName(tip.split(":")[0].split(".")[0])
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setIcon(icons.icon(name, themes.color("text2"), 16))
    button.setIconSize(QSize(16, 16))
    return button


# ----------------------------------------------------------------------------- the channel tile
class TileStrip(ChannelStrip):
    """A channel as a tile. It is a ChannelStrip underneath (the same menus, engine calls and model syncing), with the Tile
    look's parts: lanes instead of fader columns, the source line instead of the chip list, and a fold-out for the detail."""

    def __init__(self, channel, engine, window, free: bool = False) -> None:
        self.free = free
        self.tint = look_tile.channel_color(channel)
        # Columns keeps the tiles you folded out across rebuilds; Free starts with all folded (one opens at a time there)
        self.expanded = channel.id in getattr(window, "tile_open", set()) and not free
        self._clip_at: Optional[float] = None
        self._ticks = 0
        self._playing: set = set()
        self.app_meters: list = []
        self.lane_rows: dict = {}
        self.key = channel.id   # as a node of the Free layout: the tile is its own node and has no card to fold out beside it
        self.card = None
        self.strip = self
        self.is_open = False
        super().__init__(channel, engine, window, rows=False)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAccessibleName(f"{channel.label} channel tile")
        self._extend_menu()
        _focus_tracker(self)
        self._apply_open()

    def _make_frame(self, rows: bool) -> QFrame:
        return TileFrame()

    def mover(self):
        return self.window.tile_mover()

    # ------------------------------------------------------------------ building
    def _build_columns(self) -> None:
        root = self.layout_root
        left, top, right, bottom = SHADOW
        root.setContentsMargins(left + PAD, top + PAD - 2, right + PAD, bottom + SKIRT + 8)
        root.setSpacing(0)
        channel = self.channel

        # Header: the icon well, the name and the source line (the grip the tile moves by), then link and the overflow menu.
        self.grip = TileGrip(self)
        grip = QHBoxLayout(self.grip)
        grip.setContentsMargins(0, 0, 0, 0)
        grip.setSpacing(10)
        self.well = IconWell(self.tint, look_tile.channel_icon(channel), channel.label)
        grip.addWidget(self.well)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        self.title.setObjectName("tilename")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.source_line = ElidedLabel("")
        self.source_line.setObjectName("tilesource")
        self.source_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts.addWidget(self.title)
        texts.addWidget(self.source_line)
        grip.addLayout(texts, 1)
        self.grip.setToolTip("Drag to move this tile. Double-click the name to rename.")
        self.mic_button.setObjectName("tilemute")
        self.mic_button.setFixedSize(28, 28)
        self.link.setObjectName("tileicon")
        self.link.setFixedSize(28, 28)
        self.menu_button.setObjectName("tileplain")
        self.menu_button.setFixedSize(28, 28)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        head.addWidget(self.grip, 1)
        head.addWidget(self.mic_button)
        head.addWidget(self.link)
        head.addWidget(self.menu_button)
        self.head = QWidget()
        self.head.setObjectName("tilerow")
        self.head.setFixedHeight(36)
        self.head.setLayout(head)
        root.addWidget(self.head)
        root.addSpacing(14)

        self.empty_hint = QLabel(EMPTY_HINTS.get(channel.id, "Add the apps for this channel."))
        self.empty_hint.setObjectName("tilehint")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.hide()
        root.addWidget(self.empty_hint)
        self.add_button.setObjectName("tileadd")
        self.add_button.setFixedHeight(28)
        self.add_button.hide()
        root.addWidget(self.add_button)

        # The lanes: one for each mix, the main controls, always there.
        self.lanes_box = TileLanes()
        for mix in self.engine.mixer.mixes:
            self.lanes_box.add_lane(self._lane_row(mix), self.faders[mix.id])
        root.addWidget(self.lanes_box)

        # The fold-out: effects as chips and the apps on the channel. Filled when the tile is folded out.
        self.details = QWidget()
        self.details.setObjectName("tiledetails")
        self.details_box = QVBoxLayout(self.details)
        self.details_box.setContentsMargins(0, 16, 0, 0)
        self.details_box.setSpacing(8)
        self.details.hide()
        root.addWidget(self.details)
        root.addStretch(1)
        root.addSpacing(12)

        # Footer: the effects button and the fold-out chevron.
        self.fx_button.setObjectName("tilefx")
        self.fx_button.setFixedHeight(28)
        self.fx_button.setIconSize(QSize(16, 16))
        self.fx_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.chevron = _small_button("chevron_down", "Fold out: bigger lanes, the effects and the apps", "tileplain")
        self.chevron.clicked.connect(self.toggle_open)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(8)
        foot.addWidget(self.fx_button)
        foot.addStretch(1)
        foot.addWidget(self.chevron)
        self.footer = QWidget()
        self.footer.setObjectName("tilefoot")
        self.footer.setFixedHeight(28)
        self.footer.setLayout(foot)
        root.addWidget(self.footer)

        # ChannelStrip's Columns parts that a tile does not have (so nothing that looks for them breaks)
        self.tools = self.tag_row = self.faders_box = self.read_row = self.mute_row = self.filler = None
        self.sources_scroll = None
        self.tags = []
        self.ring = None

    def _lane_row(self, mix) -> QWidget:
        lane, _meter = self._make_controls(mix, horizontal=True)
        row = QWidget()
        row.setObjectName("tilerow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        mute, readout = self.mutes[mix.id], self.readouts[mix.id]
        line.addWidget(mute, 0, Qt.AlignmentFlag.AlignTop)
        line.addWidget(lane, 1, Qt.AlignmentFlag.AlignTop)
        line.addWidget(readout, 0, Qt.AlignmentFlag.AlignTop)
        row.setFixedHeight(30)
        self.lane_rows[mix.id] = row
        return row

    def _make_controls(self, mix, horizontal: bool) -> tuple:
        lane = TileLane(self.tint, self._clipped)
        lane.setAccessibleName(f"{self.channel.label}, {mix.label} level and meter")
        lane.gainChanged.connect(partial(self._on_level, mix.id))
        readout = ReadoutEdit(None)
        readout.setObjectName("tilevalue")
        readout.setFixedSize(66, 28)
        readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        readout.setAccessibleName(f"{self.channel.label}, {mix.label} level in decibels")
        readout.setToolTip("Scroll over the number to change the level (hold Shift for fine steps), or click and type a level in dB "
                           "(for example -12) and press Enter")
        readout.wheel_steps = True
        readout.wheeled.connect(partial(self._wheel_level, mix.id))
        readout.entered.connect(partial(self._typed_level, mix.id))
        mute = QPushButton("")
        mute.setObjectName("tilemute")
        mute.setCheckable(True)
        mute.setFixedSize(28, 28)
        mute.setIconSize(QSize(16, 16))
        mute.setCursor(Qt.CursorShape.PointingHandCursor)
        mute.setAccessibleName(f"Mute {self.channel.label} in {mix.label}")
        mute.toggled.connect(partial(self._on_mute, mix.id))
        mute.toggled.connect(lambda _on, m=mix: self._show_mute(m))
        self.faders[mix.id] = lane
        self.meters[mix.id] = lane   # the window's meter timer pushes the level into the same track
        self.readouts[mix.id], self.mutes[mix.id] = readout, mute
        return lane, lane

    def _extend_menu(self) -> None:
        menu = self.menu
        first = menu.actions()[0] if menu.actions() else None
        self.fold_action = QAction_(menu, "Fold out", self.toggle_open)
        menu.insertAction(first, self.fold_action)
        if not self.free:
            self.earlier_action = QAction_(menu, "Move earlier", lambda: self.window.move_tile(self.channel.id, -1))
            self.later_action = QAction_(menu, "Move later", lambda: self.window.move_tile(self.channel.id, 1))
            menu.insertAction(first, self.earlier_action)
            menu.insertAction(first, self.later_action)
        menu.insertSeparator(first)

        def refresh() -> None:
            self.fold_action.setText("Fold in" if self.expanded else "Fold out")
            if not self.free:
                ids = [c.id for c in self.engine.mixer.channels]
                index = ids.index(self.channel.id) if self.channel.id in ids else 0
                self.earlier_action.setEnabled(index > 0)
                self.later_action.setEnabled(index < len(ids) - 1)

        menu.aboutToShow.connect(refresh)

    # ------------------------------------------------------------------ folding out
    def toggle_open(self) -> None:
        canvas = getattr(self.window, "canvas", None) if self.free else None
        if canvas is not None:  # the Free layout keeps one tile folded out at a time
            canvas.toggle(self)
        else:
            self.set_open(not self.expanded)

    def set_open(self, on: bool) -> None:
        """Fold out or in (the Free layout calls this too)."""
        if on == self.expanded:
            return
        self.expanded = on
        self.is_open = on
        opened = getattr(self.window, "tile_open", None)
        if opened is None:
            opened = self.window.tile_open = set()
        (opened.add if on else opened.discard)(self.channel.id)
        self.frame.set_lifted(on and self.free)  # over its neighbours in Free: a deeper shadow says so
        self._apply_open()

    def _apply_open(self) -> None:
        big = self.expanded
        for mix_id, row in self.lane_rows.items():
            self.faders[mix_id].set_big(big)
            row.setFixedHeight(46 if big else 30)
        self.lanes_box.box.setSpacing(6 if big else 14)
        self.fx_button.setVisible(not big and not self._empty)   # the chips take its place: folding out never repeats a control
        self.chevron.setIcon(icons.icon("chevron_up" if big else "chevron_down", themes.color("text2"), 16))
        self.chevron.setToolTip("Fold in" if big else "Fold out: bigger lanes, the effects and the apps")
        self.chevron.setAccessibleName("Fold in" if big else "Fold out")
        if big:
            self._fill_details()
        else:
            self._clear_details()
        self.details.setVisible(big and not self._empty)
        self._apply_size()

    def _apply_size(self) -> None:
        left, top, right, bottom = SHADOW
        width = (OPEN_W if self.expanded else TILE_W) + left + right
        if self.expanded and not self._empty:
            self.layout_root.activate()
            height = self.layout_root.totalHeightForWidth(width) if self.layout_root.hasHeightForWidth() \
                else self.layout_root.totalSizeHint().height()
            height = max(height, TILE_H + top + bottom)
        else:
            height = TILE_H + LANE_EXTRA_H * max(0, len(self.engine.mixer.mixes) - 2) + top + bottom
        self.setFixedSize(width, height)

    def _clear_details(self) -> None:
        self.app_meters = []
        while self.details_box.count():
            item = self.details_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _fill_details(self) -> None:
        self._clear_details()
        box = self.details_box
        channel = self.channel
        box.addWidget(_section("EFFECTS"))
        chips = QWidget()
        chips.setObjectName("tilerow")
        flow = FlowLayout(chips, 6)
        for effect in channel.effects:
            chip = QPushButton(effect.name)
            chip.setObjectName("fxchip")
            chip.setCheckable(True)
            chip.setChecked(not effect.bypass)
            chip.setFixedHeight(24)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"{effect.name}: {'on' if not effect.bypass else 'off'}. Click to switch it "
                            f"{'off' if not effect.bypass else 'on'}.")
            chip.setAccessibleName(f"{effect.name} effect")
            chip.toggled.connect(partial(self._toggle_effect, effect.id))
            flow.addWidget(chip)
        add = QPushButton("+ Add")
        add.setObjectName("fxadd")
        add.setFixedHeight(24)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("Add or change effects on this channel")
        add.setAccessibleName(f"Add an effect to {channel.label}")
        add.clicked.connect(self.open_effects)
        flow.addWidget(add)
        box.addWidget(chips)
        box.addSpacing(6)
        box.addWidget(_section("APPS"))
        for device in channel.devices:
            text, tip = self._device_text(device)
            box.addWidget(self._app_row("device", device, text, tip, SourcePicture(text, device=True, size=18)))
        for app in channel.apps:
            label = self.engine.app_label(app)
            box.addWidget(self._app_row("app", app, label, f"{label}\nApp: {app}",
                                        SourcePicture(label, self.engine.app_icon(app), app, size=18)))
        if not channel.devices and not channel.apps:
            nothing = QLabel("Nothing here yet")
            nothing.setObjectName("tilenote")
            box.addWidget(nothing)
        more = QPushButton("+ Add app or device")
        more.setObjectName("tileadd")
        more.setFixedHeight(26)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setAccessibleName(f"Add app or device to {channel.label}")
        more.setMenu(self.add_menu)
        box.addWidget(more)
        self._playing = self._playing_keys()

    def _app_row(self, kind: str, key: str, text: str, tip: str, picture: QWidget) -> QWidget:
        row = QWidget()
        row.setObjectName("tilerow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        name = ElidedLabel(text)
        name.setObjectName("tileappname")
        name.setToolTip(tip)
        meter = AppMeter(self.tint)
        meter.setToolTip("Level while it plays (this channel's level: Sluice measures channels, not single apps)" if kind == "app"
                         else "This device's level")
        move = QPushButton("Move")
        move.setObjectName("tilemove")
        move.setFixedHeight(24)
        move.setCursor(Qt.CursorShape.PointingHandCursor)
        move.setToolTip(f"Move {text} to another channel")
        move.setAccessibleName(f"Move {text} to another channel")
        menu = QMenu(move)
        menu.aboutToShow.connect(partial(self._fill_move_menu, menu, kind, key, text))
        move.setMenu(menu)
        line.addWidget(picture)
        line.addWidget(name, 1)
        line.addWidget(meter)
        line.addWidget(move)
        row.setFixedHeight(26)
        self.app_meters.append((kind, key, meter))
        return row

    def _fill_move_menu(self, menu: QMenu, kind: str, key: str, text: str) -> None:
        menu.clear()
        for other in self.engine.mixer.channels:
            if other.id == self.channel.id:
                continue
            action = menu.addAction(f"To {other.label}", partial(self._move_source, kind, key, text, other.id))
            action.setEnabled(not (kind == "device" and key in other.devices))
        menu.addSeparator()
        if kind == "app":
            menu.addAction("Out of the mixer", partial(self._move_source, kind, key, text, None))
        else:
            menu.addAction(f"Remove from {self.channel.label}", partial(self._move_source, kind, key, text, None))

    def _move_source(self, kind: str, key: str, text: str, target: Optional[str]) -> None:
        if kind == "app":
            self.engine.assign_app(key, target)
        else:
            self.engine.remove_device(self.channel.id, key)
            if target is not None:
                self.engine.add_device(target, key)
        self.window.refresh_sources()
        if target is None:
            self.window.say(f"{text} is no longer in the mixer." if kind == "app" else f"{text} removed from {self.channel.label}.")
        else:
            self.window.say(f"{text} moved to {self.engine.mixer.channel(target).label}.")

    def _toggle_effect(self, effect_id: str, on: bool) -> None:
        self.engine.set_effect_bypass(self.channel.id, effect_id, not on)
        self._update_fx_button()
        chip = self.sender()
        effect = next((e for e in self.channel.effects if e.id == effect_id), None)
        if isinstance(chip, QPushButton) and effect is not None:
            chip.setToolTip(f"{effect.name}: {'on' if on else 'off'}. Click to switch it {'off' if on else 'on'}.")

    def _playing_keys(self) -> set:
        keys: set = set()
        for stream in getattr(self.engine, "streams", []):
            if self.engine.channel_for_stream(stream) is self.channel:
                keys |= set(stream.names) | {stream.assign_key}
        return keys

    def open_effects(self) -> None:
        super().open_effects()
        if self.expanded:
            self._fill_details()
            self._apply_size()

    # ------------------------------------------------------------------ the window's meter timer
    def _clipped(self) -> None:
        first = self._clip_at is None or time.time() - self._clip_at > 1.0
        self._clip_at = time.time()
        if first:
            self._show_source_line()

    def after_meters(self, loudest: float) -> None:
        """Called after the lanes got their levels: ages the "Clipped" note and feeds the app meters of a folded-out tile."""
        self._ticks += 1
        if self._clip_at is not None and self._ticks % 15 == 0:
            self._show_source_line()
        if self.expanded and self.app_meters:
            if self._ticks % 30 == 0:
                self._playing = self._playing_keys()
            for kind, key, meter in self.app_meters:
                meter.push(loudest if kind == "device" or key in self._playing else 0.0)

    def _show_source_line(self) -> None:
        clipped = False
        if self._clip_at is not None:
            age = time.time() - self._clip_at
            if age < CLIP_NOTE:
                clipped = True
                text = "Clipped just now" if age < 2 else f"Clipped {int(age)} s ago"
            else:
                self._clip_at = None
        if not clipped:
            text = self._sources_summary()
        if text != self.source_line.text():
            self.source_line.setText(text)
            self.source_line.setToolTip(self._sources_summary() if clipped else text)
        if bool(self.source_line.property("clipped")) != clipped:
            self.source_line.setProperty("clipped", clipped)
            self.source_line.style().unpolish(self.source_line)
            self.source_line.style().polish(self.source_line)

    # ------------------------------------------------------------------ ChannelStrip parts, as a tile shows them
    def refresh_theme(self) -> None:
        text2 = themes.color("text2")
        self.fx_button.setIcon(icons.icon("sliders", text2, 16))
        self.link.setIcon(icons.icon("link", themes.color("accent_text") if self.link.isChecked() else text2, 16))
        self.link.setIconSize(QSize(16, 16))
        self.menu_button.setIcon(icons.icon("more", text2, 18))
        self.chevron.setIcon(icons.icon("chevron_up" if self.expanded else "chevron_down", text2, 16))
        self.frame.refresh_theme()
        for mix in self.engine.mixer.mixes:
            self._show_mute(mix)
        self.show_mic_state()

    def _show_mute(self, mix) -> None:
        button = self.mutes.get(mix.id)
        if button is None:
            return
        muted = button.isChecked()
        button.setIcon(icons.icon(look_tile.LANE_ICONS.get(mix.id, "speaker"), themes.color("mute_fg" if muted else "text2"), 16))
        button.setToolTip(mute_tip(mix, muted))
        lane = self.faders.get(mix.id)
        if lane is not None:
            lane.set_muted(muted)
        readout = self.readouts.get(mix.id)
        if readout is not None and not readout.hasFocus():
            readout.setText("Muted" if muted else format_db(self.channel.levels.get(mix.id, 0.0)))
            if bool(readout.property("muted")) != muted:
                readout.setProperty("muted", muted)
                readout.style().unpolish(readout)
                readout.style().polish(readout)

    def set_empty(self, empty: bool) -> None:
        if empty == self._empty:
            return
        self._empty = empty
        self.lanes_box.setVisible(not empty)
        self.footer.setVisible(not empty)
        self.link.setVisible(not empty)
        self.empty_hint.setVisible(empty)
        self.add_button.setVisible(empty)
        self._apply_open()

    def refresh_sources(self) -> None:
        self._show_source_line()
        self._update_fx_button()
        self.show_mic_state()
        if self.expanded and hasattr(self, "details_box"):
            self._fill_details()
            self._apply_size()

    def _update_fx_button(self) -> None:
        effects = self.channel.effects
        count, active = len(effects), len([e for e in effects if not e.bypass])
        if count == 0:
            text = "No effects"
        elif active == count:
            text = "1 effect" if count == 1 else f"{count} effects"
        else:
            text = f"{active} of {count} on"
        self.fx_button.setText(text)
        self.fx_button.setToolTip("Add effects to this channel" if count == 0 else f"Open this channel's effects: {active} of {count} are on")
        if bool(self.fx_button.property("none")) != (count == 0):
            self.fx_button.setProperty("none", count == 0)
            self.fx_button.style().unpolish(self.fx_button)
            self.fx_button.style().polish(self.fx_button)

    def sync_from_model(self) -> None:
        super().sync_from_model()
        self.link.setIcon(icons.icon("link", themes.color("accent_text") if self.channel.linked else themes.color("text2"), 16))
        self.lanes_box.set_linked(bool(self.channel.linked))

    def _on_link(self, on: bool) -> None:
        super()._on_link(on)
        self.link.setIcon(icons.icon("link", themes.color("accent_text") if on else themes.color("text2"), 16))

    # ------------------------------------------------------------------ moving
    def set_slot(self, on: bool) -> None:
        """While the tile is being dragged it stays in place as the dashed "Drop here" slot."""
        if on:
            self._slot_hidden = [w for w in self.frame.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
                                 if w.isVisible()]
            for widget in self._slot_hidden:
                widget.hide()
        else:
            for widget in getattr(self, "_slot_hidden", []):
                widget.show()
            self._slot_hidden = []
        self.frame.set_slot(on)


def QAction_(menu: QMenu, text: str, slot):  # noqa: N802  (an action owned by the menu, not yet placed in it)
    from PySide6.QtGui import QAction

    action = QAction(text, menu)
    action.triggered.connect(lambda _checked=False: slot())
    return action


# ----------------------------------------------------------------------------- a mix as a tile (the Free layout)
class TileMixNode(QWidget):
    """Listen or Broadcast as a tile in the Free layout: the master lane works here; the chevron folds the full mix card out beside
    it (its device, Limiter and the rest)."""

    def __init__(self, canvas, strip, color: str) -> None:
        super().__init__()
        self.canvas, self.strip, self.card, self.key = canvas, strip, strip, strip.mix.id
        self.tint = color
        self.is_open = False
        mix = strip.mix
        self.mix = mix
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAccessibleName(f"{mix.label} mix tile")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = TileFrame()
        outer.addWidget(self.frame)
        root = QVBoxLayout(self.frame)
        left, top, right, bottom = SHADOW
        root.setContentsMargins(left + PAD, top + PAD - 2, right + PAD, bottom + SKIRT + 8)
        root.setSpacing(0)
        self.grip = TileGrip(self)
        grip = QHBoxLayout(self.grip)
        grip.setContentsMargins(0, 0, 0, 0)
        grip.setSpacing(10)
        grip.addWidget(IconWell(color, look_tile.LANE_ICONS.get(mix.id, "speaker"), mix.label))
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = ElidedLabel(mix.label)
        self.title.setObjectName("tilename")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.source_line = ElidedLabel("")
        self.source_line.setObjectName("tilesource")
        self.source_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts.addWidget(self.title)
        texts.addWidget(self.source_line)
        grip.addLayout(texts, 1)
        self.grip.setFixedHeight(36)
        root.addWidget(self.grip)
        root.addSpacing(14)
        self.lane = TileLane(color)
        self.lane.setAccessibleName(f"{mix.label} level and meter")
        self.lane.gainChanged.connect(self._on_level)
        self.mute = QPushButton("")
        self.mute.setObjectName("tilemute")
        self.mute.setCheckable(True)
        self.mute.setFixedSize(28, 28)
        self.mute.setIconSize(QSize(16, 16))
        self.mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute.setAccessibleName(f"Mute {mix.label}")
        self.mute.toggled.connect(self._on_mute)
        self.readout = QLabel("")
        self.readout.setObjectName("tilevalue")
        self.readout.setFixedSize(66, 28)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row = QWidget()
        row.setObjectName("tilerow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(self.mute)
        line.addWidget(self.lane, 1)
        line.addWidget(self.readout)
        row.setFixedHeight(28)
        root.addWidget(row)
        root.addStretch(1)
        self.note = QLabel("")
        self.note.setObjectName("tilenote")
        self.chevron = _small_button("chevron_down", "Fold out the full card: device, Limiter and more", "tileplain")
        self.chevron.clicked.connect(lambda: self.canvas.toggle(self))
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addWidget(self.note, 1)
        foot.addWidget(self.chevron)
        footer = QWidget()
        footer.setObjectName("tilefoot")
        footer.setFixedHeight(28)
        footer.setLayout(foot)
        root.addWidget(footer)
        self.setFixedSize(TILE_W + left + right, 168 + top + bottom)
        _focus_tracker(self)
        self.refresh()

    def mover(self):
        return self.canvas.window_.tile_mover()

    def _on_level(self, tenths: int) -> None:
        self.strip.engine.set_master(self.mix.id, tenths / 10.0)
        self.strip.sync_from_model()

    def _on_mute(self, on: bool) -> None:
        self.strip.engine.set_master_mute(self.mix.id, on)
        self.strip.sync_from_model()

    def set_open(self, on: bool) -> None:
        self.is_open = on
        self.chevron.setIcon(icons.icon("chevron_up" if on else "chevron_down", themes.color("text2"), 16))

    def push_level(self, linear: float, _slow: float = 1.0) -> None:
        self.lane.push(linear)

    def refresh_theme(self) -> None:
        self.frame.refresh_theme()
        self.refresh()

    def refresh(self) -> None:
        mix = self.mix
        for widget in (self.lane, self.mute):
            widget.blockSignals(True)
        self.lane.setGain(round(mix.gain_db * 10))
        self.mute.setChecked(bool(mix.mute))
        for widget in (self.lane, self.mute):
            widget.blockSignals(False)
        self.lane.set_muted(bool(mix.mute))
        self.mute.setIcon(icons.icon("speaker_off" if mix.mute else "speaker", themes.color("mute_fg" if mix.mute else "text2"), 16))
        self.mute.setToolTip(f"Unmute {mix.label}" if mix.mute else f"Mute {mix.label}")
        self.readout.setText("Muted" if mix.mute else format_db(mix.gain_db))
        if bool(self.readout.property("muted")) != bool(mix.mute):
            self.readout.setProperty("muted", bool(mix.mute))
            self.readout.style().unpolish(self.readout)
            self.readout.style().polish(self.readout)
        self.source_line.setText(self.device_text())
        self.note.setText("Limiter on" if mix.limiter else "Limiter off")
        self.set_open(self.is_open)

    def device_text(self) -> str:
        """What the mix plays to or is offered as, from the engine (not from the card's picker, which may not be filled yet)."""
        mix, engine = self.mix, self.strip.engine
        if getattr(self.strip, "combo", None) is None:  # Broadcast and Recording are devices other apps pick
            return f"Sends to {mix.source_description}"
        if mix.device is None:
            return "No output"
        name = mix.device or engine.default_sink
        description = next((d.description for d in engine.sinks if d.name == name), None)
        if not mix.device:
            return f"{description} (system default)" if description else "System default output"
        return description or f"{mix.device} (missing)"

    def set_slot(self, on: bool) -> None:
        for widget in self.frame.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            widget.setVisible(not on)
        self.frame.set_slot(on)


# ----------------------------------------------------------------------------- moving a tile
class TileGhost(QWidget):
    """The lifted tile under the pointer while it is moved: a picture of it, turned a little, on a deeper shadow."""

    ANGLE = 2.0
    ROOM = 44

    def __init__(self, parent: QWidget, picture: QPixmap, tile_rect: QRectF) -> None:
        super().__init__(parent)
        self.picture, self.tile_rect = picture, tile_rect
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        size = picture.deviceIndependentSize()
        self.resize(int(size.width()) + 2 * self.ROOM, int(size.height()) + 2 * self.ROOM)

    LIFT = QPoint(-10, -22)  # lifted up off the tray: the slot's "Drop here" shows below it

    def place(self, top_left: QPoint) -> None:
        self.move(top_left - QPoint(self.ROOM, self.ROOM) + self.LIFT)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = self.picture.deviceIndependentSize()
        centre = QPointF(self.ROOM + size.width() / 2.0, self.ROOM + size.height() / 2.0)
        p.translate(centre)
        p.rotate(self.ANGLE)
        p.scale(1.02, 1.02)
        p.translate(-size.width() / 2.0, -size.height() / 2.0)
        pc = look_tile.paint_colors()
        pixmap, pad = soft_shape(self.tile_rect.width(), self.tile_rect.height(), 20, pc["shadow"] * 2.6, "#000000",
                                 self.devicePixelRatioF())
        p.drawPixmap(QPointF(self.tile_rect.x() - pad, self.tile_rect.y() - pad + 14), pixmap)
        p.drawPixmap(QPointF(0, 0), self.picture)
        p.end()


class TileMover(QObject):
    """Moves a tile. In Columns the tile's place becomes the "Drop here" slot, which moves through the other tiles as the pointer
    does; dropping keeps that order (and saves it). In Free the tile goes where it is dropped. Escape puts it back."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.tile = None
        self.ghost: Optional[TileGhost] = None

    def active(self) -> bool:
        return self.tile is not None

    def begin(self, tile, press_global: QPoint) -> None:
        if self.tile is not None:
            self.cancel()
        self.tile = tile
        self.free = self.window.layout_mode == "free"
        self.offset = tile.mapFromGlobal(press_global)
        self.start_pos = tile.pos()
        self.start_order = self._order()
        picture = tile.grab()
        self.ghost = TileGhost(self.window, picture, tile.frame.tile_rect())
        self.ghost.show()
        self.ghost.raise_()
        tile.set_slot(True)
        QApplication.instance().installEventFilter(self)
        self.move(press_global)

    def move(self, point: QPoint) -> None:
        if self.tile is None:
            return
        self.ghost.place(self.window.mapFromGlobal(point) - self.offset)
        if not self.free:
            self._reorder(point)

    def drop(self, point: QPoint) -> None:
        tile = self.tile
        if tile is None:
            return
        if self.free:
            canvas = self.window.canvas
            spot = canvas.clamped(canvas.mapFromGlobal(point) - self.offset, tile)
            tile.move(spot)
            canvas.fit(tile)
            canvas.remember(tile)
            if canvas.open_node is tile and tile.card is not None:
                canvas.place_card(tile)
        else:
            self.window.commit_tile_order([s.channel.id for s in self._strips_in_flow()])
        self._end()

    def cancel(self) -> None:
        tile = self.tile
        if tile is None:
            return
        if self.free:
            tile.move(self.start_pos)
        else:
            flow = self.window.channels_row
            for wanted, channel_id in enumerate(self.start_order):
                strip = next((s for s in self._strips_in_flow() if s.channel.id == channel_id), None)
                current = self._flow_index(strip)
                if strip is not None and current is not None:
                    item = flow.takeAt(current)
                    flow.insertWidget(self._first_strip_index() + wanted, item.widget())
        self._end()

    def eventFilter(self, _obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.tile is not None:
            self.cancel()
            return True
        return False

    def _end(self) -> None:
        QApplication.instance().removeEventFilter(self)
        if self.ghost is not None:
            self.ghost.hide()
            self.ghost.deleteLater()
            self.ghost = None
        if self.tile is not None:
            try:
                self.tile.set_slot(False)
            except RuntimeError:
                pass
        self.tile = None

    # -- the Columns flow
    def _strips_in_flow(self) -> list:
        flow = getattr(self.window, "channels_row", None)
        if flow is None:
            return []
        out = []
        for i in range(flow.count()):
            widget = flow.itemAt(i).widget()
            if widget is not None and hasattr(widget, "channel"):
                out.append(widget)
        return out

    def _flow_index(self, widget) -> Optional[int]:
        flow = self.window.channels_row
        for i in range(flow.count()):
            if flow.itemAt(i).widget() is widget:
                return i
        return None

    def _first_strip_index(self) -> int:
        flow = self.window.channels_row
        for i in range(flow.count()):
            widget = flow.itemAt(i).widget()
            if widget is not None and hasattr(widget, "channel"):
                return i
        return 0

    def _order(self) -> list:
        return [s.channel.id for s in self._strips_in_flow()]

    def _reorder(self, point: QPoint) -> None:
        flow = self.window.channels_row
        area = self.window.channels_widget
        local = area.mapFromGlobal(point)
        for strip in self._strips_in_flow():
            if strip is self.tile or not strip.geometry().contains(local):
                continue
            target, current = self._flow_index(strip), self._flow_index(self.tile)
            if target is None or current is None:
                return
            item = flow.takeAt(current)
            flow.insertWidget(target, item.widget())
            flow.activate()
            return


# ----------------------------------------------------------------------------- mini tiles (the compact list)
class MiniTile(QWidget):
    """One channel in the compact list: its icon well, name, one lane (the mix chosen at the top of the list), value and mute."""

    MARGINS = (4, 2, 4, 10)

    def __init__(self, text: str, color: str, icon: str) -> None:
        super().__init__()
        self.setObjectName("minitile")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = TileFrame(self.MARGINS, radius=10)
        outer.addWidget(self.frame)
        line = QHBoxLayout(self.frame)
        left, top, right, bottom = self.MARGINS
        line.setContentsMargins(left + 10, top + 7, right + 10, bottom + SKIRT + 7)
        line.setSpacing(8)
        self.well = IconWell(color, icon, text, 24)
        self.name = ElidedLabel(text)
        self.name.setObjectName("tilename")
        self.name.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.name.setFixedWidth(84)
        self.name.setToolTip(text)
        self.fader = TileLane(color)
        self.fader.setMinimumWidth(64)
        self.readout = QLabel("0.0 dB")
        self.readout.setObjectName("tilevalue")
        self.readout.setFixedWidth(62)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.mute = QPushButton("")
        self.mute.setObjectName("tilemute")
        self.mute.setCheckable(True)
        self.mute.setFixedSize(28, 28)
        self.mute.setIconSize(QSize(16, 16))
        self.mute.setCursor(Qt.CursorShape.PointingHandCursor)
        line.addWidget(self.well)
        line.addWidget(self.name)
        line.addWidget(self.fader, 1)
        line.addWidget(self.readout)
        line.addWidget(self.mute)
        self.setFixedHeight(28 + 14 + SKIRT + top + bottom)

    def refresh_theme(self) -> None:
        self.frame.refresh_theme()


# ----------------------------------------------------------------------------- the tray, and keys for the other cards
class KeyBackground:
    """A raised key behind any widget (the Listen and Broadcast cards, a row of the Rows layout): drawn once per size and theme."""

    def __init__(self, margins: tuple, radius: float = RADIUS) -> None:
        self.margins, self.radius = margins, radius
        self._cache = None
        self._key = None

    def face_rect(self, widget: QWidget) -> QRectF:
        left, top, right, bottom = self.margins
        return QRectF(widget.rect()).adjusted(left, top, -right, -bottom - SKIRT)

    def draw(self, widget: QWidget, p: QPainter, focus: Optional[str] = None) -> None:
        ratio = widget.devicePixelRatioF()
        key = (widget.size(), ratio, themes.generation(), focus)
        if self._cache is None or key != self._key:
            pixmap = QPixmap(max(1, int(widget.width() * ratio)), max(1, int(widget.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            left, top, right, bottom = self.margins
            paint_surface(q, QRectF(widget.rect()).adjusted(left, top, -right, -bottom), ratio, focus, radius=self.radius)
            q.end()
            self._cache, self._key = pixmap, key
        p.drawPixmap(0, 0, self._cache)


class TrayPainter:
    """The tray the keys sit in: a plate lit from above with a thick front lip. Drawn once per size and theme."""

    LIP = 8

    def __init__(self) -> None:
        self._cache = None
        self._key = None

    def reset(self) -> None:
        self._cache = None

    def draw(self, widget: QWidget, p: QPainter) -> None:
        ratio = widget.devicePixelRatioF()
        key = (widget.size(), ratio, themes.generation())
        if self._cache is None or key != self._key:
            pc = look_tile.paint_colors()
            pixmap = QPixmap(max(1, int(widget.width() * ratio)), max(1, int(widget.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            plate = QRectF(widget.rect()).adjusted(1, 1, -1, -1 - self.LIP)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(pc["tray_lip"]))
            q.drawRoundedRect(plate.translated(0, self.LIP), 24, 24)
            gradient = QLinearGradient(plate.topLeft(), plate.bottomLeft())
            gradient.setColorAt(0.0, QColor(pc["tray_top"]))
            gradient.setColorAt(1.0, QColor(pc["tray_bottom"]))
            q.setBrush(gradient)
            q.drawRoundedRect(plate, 24, 24)
            q.setPen(QPen(QColor(255, 255, 255, 255 if pc["light"] else 18), 1))
            q.drawLine(QPointF(plate.left() + 24, plate.top() + 1.5), QPointF(plate.right() - 24, plate.top() + 1.5))
            q.end()
            self._cache, self._key = pixmap, key
        p.drawPixmap(0, 0, self._cache)


class TileTray(QWidget):
    """The tray behind the Columns layout's tiles."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tiletray")
        self.tray = TrayPainter()

    def refresh_theme(self) -> None:
        self.tray.reset()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self.tray.draw(self, p)
        p.end()
