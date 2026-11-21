# SPDX-License-Identifier: GPL-3.0-or-later
"""Meters and faders: the level meter, the fader with its taper, the source picture and the Nexus ring."""
from __future__ import annotations

import logging
import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QAbstractSlider, QSizePolicy, QWidget

from . import themes, ui_icons as icons
from .model import MAX_DB, MIN_DB
from .ui_base import _is_nexus, _is_original, _is_tile, db_to_fader_position, fader_position_to_db, FADER_STEPS, level_fraction

log = logging.getLogger("sluice.ui")


def meter_colors() -> tuple:
    """(green, yellow, red) of the level meters: the same meaning in every theme, a little deeper on a light background."""
    if themes.luminance(themes.color("bg")) >= 0.4:
        return "#1fbf7a", "#f2b722", "#ee4b5e"
    return "#2bd48a", "#f5c542", "#ff5c6c"


class LevelMeter(QWidget):
    """Peak meter: the bar jumps up with the sound and falls back slowly (about 20 dB a second), and a thin line holds the
    highest recent peak, so you can see how loud something really was. Vertical (a channel's column) or horizontal (a row)."""

    FALL = 0.011        # bar fall per frame at 30 frames a second, on a 60 dB scale (about 20 dB a second)
    HOLD_FRAMES = 45    # the peak line stays put for 1.5 seconds
    PEAK_FALL = 0.006

    def __init__(self, parent: Optional[QWidget] = None, horizontal: bool = False, thickness: int = 8) -> None:
        super().__init__(parent)
        self.horizontal = horizontal
        self.original = _is_original() and not horizontal  # the 0.9.7 meter: square, segmented, a 12-pixel column
        if horizontal:
            self.setFixedHeight(thickness)
            self.setMinimumWidth(48)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(12 if self.original else thickness)
            self.setMinimumHeight(140 if self.original else 96)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._level = 0.0
        self._peak = 0.0
        self._peak_age = 0
        self._lit: Optional[QPixmap] = None  # the full-length coloured bar, drawn once per size and theme
        self._painted = None  # (bar length, peak line) as last drawn: nothing is repainted unless this changes
        self._well = QColor(themes.color("well" if self.original else "meter_bg"))
        self._peak_color = QColor(themes.color("strong"))

    def refresh_theme(self) -> None:
        """Pick up the colours of the theme in use (the track behind the bar, the peak line)."""
        self._well = QColor(themes.color("well" if self.original else "meter_bg"))
        self._peak_color = QColor(themes.color("strong"))
        self._lit = None
        self._rounded = None
        self._painted = None
        self.update()

    def _length(self) -> int:
        return self.width() if self.horizontal else self.height()

    def _shown(self) -> tuple:
        length = self._length()
        return int(length * self._level), (int(length * self._peak) if self._peak > 0.02 else -1)

    def resizeEvent(self, event) -> None:
        self._lit = None
        self._rounded = None
        self._painted = None
        super().resizeEvent(event)

    def _rounded_pixmaps(self) -> tuple:
        """(well, lit bar), each already cut to the meter's rounded shape: painting then needs no clip path, which is most of a
        meter frame's cost. Made once per size and theme."""
        if getattr(self, "_rounded", None) is None:
            ratio = self.devicePixelRatioF()
            rect = QRectF(self.rect())
            radius = min(rect.width(), rect.height()) / 2
            shape = QPainterPath()
            shape.addRoundedRect(rect, radius, radius)
            out = []
            for source in (None, self._lit_pixmap()):
                pixmap = QPixmap(max(1, int(rect.width() * ratio)), max(1, int(rect.height() * ratio)))
                pixmap.setDevicePixelRatio(ratio)
                pixmap.fill(Qt.GlobalColor.transparent)
                q = QPainter(pixmap)
                q.setRenderHint(QPainter.RenderHint.Antialiasing)
                q.setClipPath(shape)
                if source is None:
                    q.fillRect(rect, self._well)
                else:
                    q.drawPixmap(0, 0, source)
                q.end()
                out.append(pixmap)
            self._rounded = tuple(out)
        return self._rounded

    def _lit_pixmap(self) -> QPixmap:
        if self._lit is None:
            ratio = self.devicePixelRatioF()
            width, height = self.width(), self.height()
            pixmap = QPixmap(max(1, int(width * ratio)), max(1, int(height * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            p = QPainter(pixmap)
            gradient = QLinearGradient(0, 0, width, 0) if self.horizontal else QLinearGradient(0, height, 0, 0)
            green, yellow, red = meter_colors()
            gradient.setColorAt(0.00, QColor(green))
            gradient.setColorAt(0.60, QColor(green))
            gradient.setColorAt(0.80, QColor(yellow))
            gradient.setColorAt(1.00, QColor(red))
            if self.original:  # 0.9.7: a deeper green, and thin lines in the colour of the well make the segments
                gradient = QLinearGradient(0, height, 0, 0)
                gradient.setColorAt(0.00, QColor("#1c9a58"))
                gradient.setColorAt(0.68, QColor("#3ddc84"))
                gradient.setColorAt(0.84, QColor("#f5c542"))
                gradient.setColorAt(1.00, QColor("#ef5258"))
            p.fillRect(QRectF(0, 0, width, height), gradient)
            if self.original:
                p.setPen(self._well)
                for y in range(0, height, 3):
                    p.drawLine(0, y, width, y)
            p.end()
            self._lit = pixmap
        return self._lit

    def push(self, linear: float) -> None:
        frac = level_fraction(linear)
        self._level = max(frac, self._level - self.FALL)
        if frac >= self._peak:
            self._peak, self._peak_age = frac, 0
        else:
            self._peak_age += 1
            if self._peak_age > self.HOLD_FRAMES:
                self._peak = max(self._level, self._peak - self.PEAK_FALL)
        if self._shown() != self._painted:  # a silent, settled meter costs nothing
            self.update()

    def _paint_original(self) -> None:
        p = QPainter(self)
        rect = self.rect()
        p.fillRect(rect, self._well)
        height = rect.height()
        fill, peak = self._shown()
        ratio = self.devicePixelRatioF()
        if fill > 0:
            top = height - fill + 1
            p.drawPixmap(0, top, self._lit_pixmap(), 0, int(top * ratio), int(rect.width() * ratio), int(fill * ratio))
        if peak >= 0:
            p.setPen(self._peak_color)
            p.drawLine(rect.left(), rect.bottom() - peak, rect.right(), rect.bottom() - peak)
        p.end()
        self._painted = (fill, peak)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from .ui_nexus import card_backdrop
        self._backdrop = not self.original and card_backdrop(self) is not None  # on a card: paint what is behind, be opaque (cheap)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, self._backdrop)

    def paintEvent(self, _event) -> None:
        if self.original:
            self._paint_original()
            return
        p = QPainter(self)
        if getattr(self, "_backdrop", False):
            from .ui_nexus import card_backdrop
            brush = card_backdrop(self)
            if brush is not None:
                p.fillRect(self.rect(), brush)
        rect = QRectF(self.rect())
        radius = min(rect.width(), rect.height()) / 2
        well, lit = self._rounded_pixmaps()
        p.drawPixmap(0, 0, well)
        fill, peak = self._shown()
        ratio = self.devicePixelRatioF()
        if fill > 0:
            if self.horizontal:
                p.drawPixmap(0, 0, lit, 0, 0, int(fill * ratio), int(rect.height() * ratio))
            else:
                top = self.height() - fill
                p.drawPixmap(0, top, lit, 0, int(top * ratio), int(rect.width() * ratio), int(fill * ratio))
        if 0 <= peak < radius or peak > self._length() - radius:  # a peak line in a rounded end is cut to the shape
            shape = QPainterPath()
            shape.addRoundedRect(rect, radius, radius)
            p.setClipPath(shape)
        if peak >= 0:
            p.setPen(QPen(self._peak_color, 2))
            if self.horizontal:
                p.drawLine(peak, 0, peak, self.height())
            else:
                p.drawLine(0, self.height() - peak, self.width(), self.height() - peak)
        p.end()
        self._painted = (fill, peak)


class Fader(QAbstractSlider):
    """Gain fader, painted by Sluice: a slim track (8 pixels), a fill in the channel's colour and a pill-shaped handle.

    Its public value is in tenths of a dB (``gain()``, ``setGain()``, ``gainChanged``); the handle follows ``FADER_TAPER``.
    Double-click resets to 0 dB, the wheel moves 1 dB, the arrow keys, Page Up/Down, Home and End move it from the keyboard,
    and a blue ring shows when it has the keyboard focus."""

    gainChanged = Signal(int)
    TRACK = 8

    def __init__(self, horizontal: bool = False, thumb: Optional[tuple] = None) -> None:
        super().__init__()
        self.horizontal = horizontal
        self.original = _is_original() and not horizontal  # the 0.9.7 fader: a grey groove, a dark green fill, a squarish handle
        self.nexus = _is_nexus() and not horizontal  # the Nexus fader: reach for it and it shows the sound it carries
        self.tile = _is_tile()
        self._reveal = False
        self._history = [0.0] * 32 if self.nexus else []  # about a second of level, kept only while the waveform is showing
        self.setOrientation(Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical)
        self.setRange(0, FADER_STEPS)
        self.setValue(round(db_to_fader_position(0.0) * FADER_STEPS))
        self.setSingleStep(8)
        self.setPageStep(60)
        self.thumb = thumb or ((16, 24) if horizontal else ((28, 22) if self.original else (32, 16)))  # (width, height) of the handle
        if horizontal:
            self.setMinimumWidth(96)
            self.setFixedHeight(self.thumb[1] + 4)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setMinimumHeight(140 if self.original else 96)
            self.setFixedWidth(34 if self.original else self.thumb[0] + 4)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Double-click to reset to 0 dB")
        self.fill_color = themes.color("accent")
        self.valueChanged.connect(lambda _position: self.gainChanged.emit(self.gain()))

    def set_fill(self, color: str) -> None:
        self.fill_color = color
        self.update()

    def _wants_wave(self) -> bool:
        return self.nexus and not themes.reduce_effects() and (self.underMouse() or self.hasFocus() or self.isSliderDown())

    def _update_reveal(self) -> None:
        wanted = self._wants_wave()
        if wanted != self._reveal:
            self._reveal = wanted
            if wanted:
                self._history = [0.0] * len(self._history)  # start from silence: only what happens while you look is shown

    def feed(self, linear: float) -> None:
        """One level reading, from the window's meter timer. Only called while the waveform is showing."""
        self._history.pop(0)
        self._history.append(level_fraction(linear))
        self.update()

    def _paint_wave(self, p: QPainter, track_rect: QRectF) -> None:
        """The sound behind the track, as bars of the last second: newest at the top, wider when louder. One stroke, no allocation per bar."""
        count = len(self._history)
        top, height = 6.0, self.height() - 12.0
        mid = track_rect.center().x()
        reach = self.width() / 2.0 - 2.0
        path = QPainterPath()
        for i, level in enumerate(self._history):
            if level < 0.02:
                continue
            y = top + height * (1.0 - i / (count - 1.0))
            path.moveTo(mid - reach * level, y)
            path.lineTo(mid + reach * level, y)
        color = QColor(self.fill_color)
        color.setAlpha(170)
        p.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)

    def refresh_theme(self) -> None:
        self.update()

    def gain(self) -> int:
        return round(fader_position_to_db(self.value() / FADER_STEPS) * 10)

    def setGain(self, tenths: int) -> None:
        self.setValue(round(db_to_fader_position(tenths / 10.0) * FADER_STEPS))

    # -- geometry: where the handle's centre sits for a value, and the value for a pointer position
    def _travel(self) -> tuple:
        length = self.width() if self.horizontal else self.height()
        half = (self.thumb[0] if self.horizontal else self.thumb[1]) / 2.0
        return half, max(1.0, length - 2 * half)

    def _centre(self) -> float:
        half, span = self._travel()
        fraction = self.value() / FADER_STEPS
        if self.horizontal:
            return half + fraction * span
        return half + (1.0 - fraction) * span

    def _value_at(self, pos) -> int:
        half, span = self._travel()
        coordinate = pos.x() if self.horizontal else pos.y()
        fraction = (coordinate - half) / span
        if not self.horizontal:
            fraction = 1.0 - fraction
        return round(max(0.0, min(1.0, fraction)) * FADER_STEPS)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setSliderDown(True)
            self._update_reveal()
            self.setValue(self._value_at(event.position()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown():
            self.setValue(self._value_at(event.position()))
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            self._update_reveal()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.setGain(0)
        event.accept()

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / 120.0
        self.setGain(max(int(MIN_DB * 10), min(int(MAX_DB * 10), self.gain() + int(round(notches * 10)))))
        event.accept()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = float(round(self._centre()))  # whole pixels: a handle on a half pixel is blurry
        tw, th = self.thumb
        track = 10 if self.original else self.TRACK
        if self.horizontal:
            y = (self.height() - track) / 2.0
            track_rect = QRectF(0, y, self.width(), track)
            fill_rect = QRectF(0, y, centre, track)
            thumb_rect = QRectF(centre - tw / 2.0, (self.height() - th) / 2.0, tw, th)
        else:
            x = (self.width() - track) / 2.0
            track_rect = QRectF(x, 0, track, self.height())
            fill_rect = QRectF(x, centre, track, self.height() - centre)
            thumb_rect = QRectF((self.width() - tw) / 2.0, centre - th / 2.0, tw, th)
        p.setPen(Qt.PenStyle.NoPen)
        groove = 3.0 if self.original else track / 2.0
        p.setBrush(QColor(themes.color("well" if self.original else "track")))
        p.drawRoundedRect(track_rect, groove, groove)
        if not self.original and not self.tile:  # Calm and Nexus: the groove looks sunk in, a shade along its top inside edge
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(track_rect, groove, groove)
            p.setClipPath(clip)
            shade = QLinearGradient(track_rect.topLeft(), track_rect.topLeft() + QPointF(0, 3) if self.horizontal
                                    else track_rect.topLeft() + QPointF(3, 0))
            shade.setColorAt(0.0, QColor(0, 0, 0, 60))
            shade.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(track_rect, shade)
            p.restore()
        p.setBrush(QColor(themes.color("fill") if self.original else self.fill_color))
        p.drawRoundedRect(fill_rect, groove, groove)
        if self.tile:  # the Tile look: the track is a groove pressed into the key, the handle a raised white pill
            from . import skin_tile, ui_tile_paint as ui_tile
            pc = skin_tile.paint_colors()
            shape = QPainterPath()
            shape.addRoundedRect(track_rect, groove, groove)
            ui_tile.paint_groove(p, shape, track_rect, pc)
            ui_tile.paint_handle(p, thumb_rect, pc, False)
            if self.hasFocus():
                radius = min(tw, th) / 2.0
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(themes.color("focus")), 2))
                p.drawRoundedRect(thumb_rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
            p.end()
            return
        if self.nexus and self._reveal:
            self._paint_wave(p, track_rect)
        radius = 4.0 if self.original else min(tw, th) / 2.0
        if self.nexus and self._reveal and not themes.reduce_effects():  # a halo round the handle while it is in use
            p.drawPixmap(QPointF(thumb_rect.center().x() - 28, thumb_rect.center().y() - 28), _glow(QColor(self.fill_color).name(), 56, self.devicePixelRatioF(), 80))
        if not self.original:
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawRoundedRect(thumb_rect.translated(0, 1.5), radius, radius)
        p.setBrush(QColor(themes.color("handle_hover" if self.underMouse() else "handle")))
        p.setPen(QPen(QColor(themes.color("handle_edge")), 1))
        p.drawRoundedRect(thumb_rect, radius, radius)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(themes.color("focus")), 2))
            p.drawRoundedRect(thumb_rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
        p.end()

    def enterEvent(self, event) -> None:
        self._update_reveal()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._update_reveal()
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self._update_reveal()
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._update_reveal()
        self.update()
        super().focusOutEvent(event)


class SourcePicture(QWidget):
    """The small picture in front of a source: the app's or game's own icon (a letter when it has none), or a microphone for a device.
    Drawn at the screen's real pixel density, so it stays sharp at 125%, 150% and 200%."""

    def __init__(self, label: str, spec: str = "", key: str = "", device: bool = False, size: int = 20) -> None:
        super().__init__()
        self.label, self.spec, self.key, self.device, self.size_ = label, spec, key, device, size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        if self.device:
            ratio = self.devicePixelRatioF()
            pixmap = icons.render("mic", themes.color("text2"), round(self.size_ * ratio))
            pixmap.setDevicePixelRatio(ratio)
            p.drawPixmap(0, 0, pixmap)
        else:
            p.drawPixmap(0, 0, icons.app_pixmap(self.spec, self.label, self.size_, self.devicePixelRatioF(), self.key))
        p.end()


_GLOWS: dict = {}
_RING_CACHE: dict = {}   # the Nexus rings' pictures, shared by every ring (oldest dropped first)
RING_CACHE_SIZE = 160


def _glows() -> bool:
    """Glow belongs to dark themes: on a light one, neon on white looks washed out (0.11.5)."""
    from . import depth
    return depth.depth_colors(themes._current)["glow"]


def _glow(color: str, diameter: int, ratio: float, peak: int = 90) -> QPixmap:
    """A soft round glow in a colour, drawn once and kept: painting it again is one cheap copy of an image (no blur effect that redraws)."""
    key = (color, diameter, round(ratio * 100), peak)
    pix = _GLOWS.get(key)
    if pix is None:
        size = max(2, round(diameter * ratio))
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        gradient = QRadialGradient(size / 2.0, size / 2.0, size / 2.0)
        for stop, alpha in ((0.0, peak), (0.55, peak // 3), (1.0, 0)):
            c = QColor(color)
            c.setAlpha(alpha)
            gradient.setColorAt(stop, c)
        painter = QPainter(pix)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(0, 0, size, size)
        painter.end()
        pix.setDevicePixelRatio(ratio)
        if len(_GLOWS) > 48:
            _GLOWS.clear()
        _GLOWS[key] = pix
    return pix


class NexusRing(QWidget):
    """The Nexus look's meter: a ring of short bars around a picture. The bars stand up with the sound and fall back; the picture is the
    app's or game's own icon (the first one on the channel), dimmed while it is silent.

    Kept light on purpose: one number per channel, the bars drawn as one stroke from a table of angles worked out once, the level
    rounded to 16 steps so a steady sound is not redrawn, the shimmer moving every third tick, and nothing at all redrawn while it is
    silent and settled."""

    BARS = 36
    SIZE = 84
    STEPS = 16
    _ANGLES = tuple((math.cos(2 * math.pi * i / 36 - math.pi / 2), math.sin(2 * math.pi * i / 36 - math.pi / 2)) for i in range(36))

    SMALL = 48  # 0.11.6: the Rows layout's ring, beside the name

    def __init__(self, color: str, picture, size: int = SIZE) -> None:
        super().__init__()
        self.color, self._picture_for, self._pix = color, picture, None
        self.size_ = size
        self._level, self._step, self._phase, self._tick = 0.0, 0, 0, 0
        self._dirty, self._gate = False, 0
        self.linked, self.muted, self._badge = False, False, None
        self.on_glow = None  # the Nexus floor: told how loud the card is, in 16 steps, so its glow follows the sound
        self._glow_due = False
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def refresh_source(self) -> None:
        self._pix = None
        self.update()

    def refresh_theme(self) -> None:
        self._pix = self._badge = None
        self.update()

    def set_color(self, color: str) -> None:
        if color != self.color:
            self.color = color
            self.update()

    def set_state(self, linked: bool, muted: bool) -> None:
        """What to show beside the sound: a chain badge when this channel's levels are linked, MUTED when every mix of it is muted."""
        if (linked, muted) != (self.linked, self.muted):
            self.linked, self.muted = linked, muted
            self.update()

    def push(self, linear: float, slow: float = 1.0) -> None:
        """Take the newest level. The ring is repainted at half the meter rate (15 times a second): the eye cannot tell, and drawing is the
        cost. ``slow`` is 2 when the meters run at half rate, so the bars fall back at the same speed in seconds."""
        if self.muted:
            linear = 0.0
        frac = level_fraction(linear)
        self._level = max(frac, self._level - 0.03 * slow)
        step = int(self._level * self.STEPS + 0.5) if self._level > 0.03 else 0
        if step != self._step:
            self._step = step
            self._dirty = True
            self._glow_due = True
        if step and not themes.reduce_effects():
            self._tick += 1
            if self._tick % 3 == 0:
                self._phase += 1
                self._dirty = True
        self._gate ^= 1
        if self._dirty and self._gate and self.isVisible() and not self.visibleRegion().isEmpty():  # out of sight: nothing redrawn
            self._dirty = False
            self.update()
            if self._glow_due and self.on_glow is not None:  # the card's glow on the Nexus floor moves with the ring
                self._glow_due = False
                self.on_glow(self._step / self.STEPS)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from .ui_nexus import card_gradient
        self._on_card = card_gradient(self) is not None  # on a glass card: paint the card behind the ring and be opaque (cheap)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, self._on_card)

    PHASES = 6  # the shimmer goes round in six steps, so a ring has at most 16 x 6 pictures (kept, a few dozen at a time)

    def paintEvent(self, _event) -> None:
        """The card behind the ring (it is opaque on a glass card), then the ring itself: one picture per (level step, shimmer step,
        state), drawn once and kept, so a moving ring costs a copy of a small picture (0.11.5)."""
        p = QPainter(self)
        if getattr(self, "_on_card", False):
            from .ui_nexus import card_gradient
            backdrop = card_gradient(self)
            if backdrop is not None:
                p.fillRect(self.rect(), backdrop)
        ratio = self.devicePixelRatioF()
        halo = self._step > 0 and not themes.reduce_effects() and themes.current_look() == "nexus" and _glows()
        key = (self._step, self._phase % self.PHASES if self._step else 0, self.color, self.muted, self.linked, halo,
               round(ratio * 100), themes.generation(), id(self._pix), self.size_)
        picture = _RING_CACHE.get(key)
        if picture is None:
            picture = self._draw_ring(ratio, halo)
            if len(_RING_CACHE) >= RING_CACHE_SIZE:
                _RING_CACHE.pop(next(iter(_RING_CACHE)))
            _RING_CACHE[key] = picture
        p.drawPixmap(0, 0, picture)
        p.end()

    def _draw_ring(self, ratio: float, halo: bool) -> QPixmap:
        picture = QPixmap(round(self.size_ * ratio), round(self.size_ * ratio))
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.GlobalColor.transparent)
        p = QPainter(picture)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = self.size_ < self.SIZE
        p.scale(self.size_ / self.SIZE, self.size_ / self.SIZE)  # drawn on the 84 px design, at the ring's own size
        c = self.SIZE / 2.0
        alive = self._step > 0
        phase = self._phase % self.PHASES
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(themes.color("border2")), 1))
        p.drawEllipse(QPointF(c, c), 25.0, 25.0)
        strength = self._step / self.STEPS
        if halo:  # a halo that grows with the sound (dark themes only)
            p.setOpacity(min(1.0, 0.25 + strength))
            p.drawPixmap(QPointF(0, 0), _glow(self.color, self.SIZE, ratio))
            p.setOpacity(1.0)
        path = QPainterPath()
        for i, (cos, sin) in enumerate(self._ANGLES):
            length = 2.0 + (14.0 * strength * (0.55 + 0.45 * abs(math.sin(i * 1.3 + phase * 1.05))) if alive else 0.0)
            path.moveTo(c + cos * 28, c + sin * 28)
            path.lineTo(c + cos * (28 + length), c + sin * (28 + length))
        pen_color = QColor(self.color) if alive else QColor(themes.color("text_off"))
        if not alive:
            pen_color.setAlpha(120)
        p.setPen(QPen(pen_color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        if self._pix is None:
            self._pix = self._picture_for(ratio)
        p.setOpacity(1.0 if alive and not self.muted else 0.45)
        p.drawPixmap(QPointF(c - 18, c - 18), self._pix)
        p.setOpacity(1.0)
        if self.linked and not small:  # (a row shows it on its own link button)
            if self._badge is None:
                self._badge = icons.render("link", themes.color("accent"), round(14 * ratio))
                self._badge.setDevicePixelRatio(ratio)
            p.setBrush(QColor(themes.color("accent_bg")))
            p.setPen(QPen(QColor(themes.color("accent")), 1))
            p.drawEllipse(QPointF(14, 14), 10.0, 10.0)
            p.drawPixmap(QPointF(7, 7), self._badge)
        if self.muted and small:  # too small for the word: the inner circle in the mute colour says it
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(themes.color("mute")), 3))
            p.drawEllipse(QPointF(c, c), 25.0, 25.0)
        elif self.muted:
            p.setBrush(QColor(themes.color("mute_bg")))
            p.setPen(QPen(QColor(themes.color("mute")), 1))
            p.drawRoundedRect(QRectF(c - 21, self.SIZE - 14, 42, 13), 6.5, 6.5)
            font = p.font()
            font.setPixelSize(9)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(themes.color("mute_fg")))
            p.drawText(QRectF(c - 21, self.SIZE - 14, 42, 13), int(Qt.AlignmentFlag.AlignCenter), "MUTED")
        p.end()
        return picture
