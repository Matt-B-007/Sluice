# SPDX-License-Identifier: GPL-3.0-or-later
"""Meters and faders: the level meter, the fader with its taper, the source picture and the Nexus ring."""
from __future__ import annotations

import logging
import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QAbstractSlider, QSizePolicy, QWidget

from . import themes, ui_paint, ui_icons as icons
from .model import MAX_DB, MIN_DB
from .ui_base import _is_nexus, _is_tile, db_to_fader_position, fader_position_to_db, FADER_STEPS, level_fraction

log = logging.getLogger("sluice.ui")


def meter_colors() -> tuple:
    """(green, yellow, red) of the level meters: the same meaning in every theme, a little deeper on a light background."""
    if themes.luminance(themes.color("bg")) >= 0.4:
        return "#1fbf7a", "#f2b722", "#ee4b5e"
    return "#2bd48a", "#f5c542", "#ff5c6c"


METER_FPS = 60  # 0.12.3: the meters are redrawn 60 times a second (30 before): half the wait between a sound and the bar moving
FALL_PER_S = 25.0 / 60.0  # 0.12.3: a bar falls 25 dB a second (20 before) on its 60 dB scale, like OBS's "Fast" meters
PEAK_HOLD_S = 1.5  # the peak line stays put this long
PEAK_FALL_PER_S = 0.18  # then falls about 11 dB a second


FRAME_S = 1.0 / METER_FPS  # the time between two meter updates; the window sets it when it changes its meter rate


def elapsed(_meter=None) -> float:
    """The time one meter update stands for, so the bars fall at the same speed in seconds at any refresh rate: 60 a second, or
    30 for a Nexus window that is not in use. (Counted per update rather than read from the clock, so a busy moment that
    delays a frame does not make the bar jump.)"""
    return FRAME_S


def fall(meter, frac: float) -> None:
    """The shared ballistics of a level meter: the bar jumps up to a louder level at once and falls at FALL_PER_S; the peak line
    holds for PEAK_HOLD_S, then falls. Uses and updates ``meter._level``, ``meter._peak`` and ``meter._peak_age`` (seconds)."""
    dt = elapsed(meter)
    meter._level = max(frac, meter._level - FALL_PER_S * dt)
    if frac >= meter._peak:
        meter._peak, meter._peak_age = frac, 0.0
    else:
        meter._peak_age += dt
        if meter._peak_age > PEAK_HOLD_S:
            meter._peak = max(meter._level, meter._peak - PEAK_FALL_PER_S * dt)


class LevelMeter(QWidget):
    """Peak meter: the bar jumps up with the sound and falls back slowly (about 20 dB a second), and a thin line holds the
    highest recent peak, so you can see how loud something really was. Vertical (a channel's column) or horizontal (a row)."""

    # (0.12.3: how the bar falls is in fall() above, in seconds, shared with the Tile skin's lanes)

    def __init__(self, parent: Optional[QWidget] = None, horizontal: bool = False, thickness: int = 8) -> None:
        super().__init__(parent)
        self.horizontal = horizontal
        if horizontal:
            self.setFixedHeight(thickness)
            self.setMinimumWidth(48)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(thickness)
            self.setMinimumHeight(96)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._level = 0.0
        self._peak = 0.0
        self._peak_age = 0
        self._lit: Optional[QPixmap] = None  # the full-length coloured bar, drawn once per size and theme
        self._painted = None  # (bar length, peak line) as last drawn: nothing is repainted unless this changes
        self._well = _glass_well() or QColor(themes.color("meter_bg"))
        self._peak_color = QColor(themes.color("strong"))
        self.tint: Optional[str] = None  # 0.12.2: Calm and Glass light a meter in its channel's or mix's colour, amber near the top

    def set_tint(self, color: Optional[str]) -> None:
        if color != self.tint:
            self.tint = color
            self._lit = None
            self._rounded = None
            self._painted = None
            self.update()

    def refresh_theme(self) -> None:
        """Pick up the colours of the theme in use (the track behind the bar, the peak line)."""
        self._well = _glass_well() or QColor(themes.color("meter_bg"))
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
            p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
            gradient = QLinearGradient(0, 0, width, 0) if self.horizontal else QLinearGradient(0, height, 0, 0)
            green, yellow, red = meter_colors()
            if self.tint:  # the colour of what it measures, then amber from -12 dB and red at the very top
                gradient.setColorAt(0.00, QColor(self.tint))
                gradient.setColorAt(0.76, QColor(self.tint))
                gradient.setColorAt(0.86, QColor(yellow))
                gradient.setColorAt(1.00, QColor(red))
            else:
                gradient.setColorAt(0.00, QColor(green))
                gradient.setColorAt(0.60, QColor(green))
                gradient.setColorAt(0.80, QColor(yellow))
                gradient.setColorAt(1.00, QColor(red))
            p.fillRect(QRectF(0, 0, width, height), gradient)
            p.end()
            self._lit = pixmap
        return self._lit

    def event(self, event) -> bool:
        """0.12.3: hovering over a meter says its level both ways (the scale beside it is in dB)."""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.ToolTip:
            from PySide6.QtWidgets import QToolTip
            from .ui_base import level_tip
            db = MIN_DB + self._level * -MIN_DB
            QToolTip.showText(event.globalPos(), "Silent" if self._level <= 0.001 else f"Now {level_tip(db)}", self)
            return True
        return super().event(event)

    def push(self, linear: float) -> None:
        fall(self, level_fraction(linear))
        if self._shown() != self._painted:  # a silent, settled meter costs nothing
            self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from .ui_nexus import card_backdrop
        self._backdrop = card_backdrop(self) is not None  # on a card: paint what is behind, be opaque (cheap)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, self._backdrop)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
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


def _glass_well():
    """Glass (0.11.7): a track or meter well is a see-through shade, not a solid colour, so the frosted pane shows in it."""
    if themes.current_skin() != "glass":
        return None
    from . import depth
    light = depth.luminance(themes.color("panel")) >= depth.LIGHT_PANEL
    return QColor(0, 0, 0, 34 if light else 80)


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
        self.nexus = _is_nexus() and not horizontal  # the Nexus fader: reach for it and it shows the sound it carries
        self.tile = _is_tile()
        self._reveal = False
        self._history = [0.0] * 32 if self.nexus else []  # about a second of level, kept only while the waveform is showing
        self.setOrientation(Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical)
        self.setRange(0, FADER_STEPS)
        self.setValue(round(db_to_fader_position(0.0) * FADER_STEPS))
        self.setSingleStep(8)
        self.setPageStep(60)
        self.thumb = thumb or ((16, 24) if horizontal else (32, 16))  # (width, height) of the handle
        if themes.current_skin() == "glass" and not self.tile:  # 0.12.2: Glass's pearl knob is round
            self.thumb = (24, 24)
        if horizontal:
            self.setMinimumWidth(96)
            self.setFixedHeight(self.thumb[1] + 4)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setMinimumHeight(96)
            self.setFixedWidth(self.thumb[0] + 4)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Double-click to reset to 0 dB")
        self.fill_color = themes.color("accent")
        self.valueChanged.connect(lambda _position: self.gainChanged.emit(self.gain()))
        self.valueChanged.connect(self._announce)  # 0.12.6: screen readers hear "-6.0 dB", not the handle's position
        self._announce()

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

    def _announce(self, *_args) -> None:
        from .ui_base import format_db
        self.setAccessibleDescription(format_db(self.gain() / 10.0))

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
        track = self.TRACK
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
        if themes.current_skin() == "nexus" and not self.tile:  # 0.12.2: a beam of light, not a groove
            self._paint_beam(p, track_rect, fill_rect, thumb_rect)
            p.end()
            return
        groove = track / 2.0
        glass = themes.current_skin() == "glass"
        # Calm, Nexus and Glass: the groove looks sunk in, a shade along its top inside edge (Tile shades its own below)
        ui_paint.groove(p, track_rect, _glass_well() if glass else QColor(themes.color("track")), 0 if self.tile else 60,
                        across=not self.horizontal)
        if glass and not themes.reduce_effects() and fill_rect.height() > 0 and fill_rect.width() > 0:  # Glass: the fill glows softly
            halo = QColor(self.fill_color)
            for grow, alpha in ((5, 0.10), (3, 0.16), (1.5, 0.24)):
                halo.setAlphaF(alpha)
                p.setBrush(halo)
                p.drawRoundedRect(fill_rect.adjusted(-grow, -grow, grow, grow), groove + grow, groove + grow)
        if glass and fill_rect.height() > 0 and fill_rect.width() > 0:  # 0.12.2: the fill brightens toward the knob, lit from inside
            lit = QLinearGradient(fill_rect.bottomLeft(), fill_rect.topLeft()) if not self.horizontal else \
                QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
            lit.setColorAt(0.0, QColor(self.fill_color))
            lit.setColorAt(1.0, QColor(themes.mix(self.fill_color, "#ffffff", 0.45)))
            p.setBrush(lit)
        else:
            p.setBrush(QColor(self.fill_color))
        p.drawRoundedRect(fill_rect, groove, groove)
        if self.tile:  # the Tile look: the track is a groove pressed into the key, the handle a raised white pill
            from . import skin_tile, ui_tile_paint as ui_tile
            pc = skin_tile.paint_colors()
            shape = QPainterPath()
            shape.addRoundedRect(track_rect, groove, groove)
            ui_tile.paint_groove(p, shape, track_rect, pc)
            ui_tile.paint_handle(p, thumb_rect, pc, False, focus=QColor(themes.color("focus")) if self.hasFocus() else None)
            p.end()
            return
        if self.nexus and self._reveal:
            self._paint_wave(p, track_rect)
        if self.nexus and self._reveal and not themes.reduce_effects():  # a halo round the handle while it is in use
            p.drawPixmap(QPointF(thumb_rect.center().x() - 28, thumb_rect.center().y() - 28), _glow(QColor(self.fill_color).name(), 56, self.devicePixelRatioF(), 80))
        if themes.current_skin() == "glass":  # 0.12.2: a pearl knob
            ui_paint.pearl(p, thumb_rect, QColor(themes.color("focus")) if self.hasFocus() else None, self.underMouse())
        else:
            ui_paint.handle(p, thumb_rect, themes.color("handle_hover" if self.underMouse() else "handle"), themes.color("handle_edge"),
                            focus=QColor(themes.color("focus")) if self.hasFocus() else None)
        p.end()

    def _paint_beam(self, p: QPainter, track_rect: QRectF, fill_rect: QRectF, thumb_rect: QRectF) -> None:
        """Nexus (0.12.2): the track is a faint line, the level a beam of light in the channel's colour that glows on dark themes, and
        the handle a ring of light with a dark centre."""
        thin = 3.0
        if self.horizontal:
            line = QRectF(track_rect.left(), track_rect.center().y() - thin / 2, track_rect.width(), thin)
            beam = QRectF(fill_rect.left(), line.top(), fill_rect.width(), thin)
        else:
            line = QRectF(track_rect.center().x() - thin / 2, track_rect.top(), thin, track_rect.height())
            beam = QRectF(line.left(), fill_rect.top(), thin, fill_rect.height())
        dim = QColor(themes.color("border2"))
        p.setBrush(dim)
        p.drawRoundedRect(line, thin / 2, thin / 2)
        color = QColor(self.fill_color)
        if beam.width() > 0 and beam.height() > 0:
            if _glows() and not themes.reduce_effects():
                for grow, alpha in ((5.0, 0.10), (3.0, 0.18), (1.5, 0.32)):
                    halo = QColor(color)
                    halo.setAlphaF(alpha)
                    p.setBrush(halo)
                    p.drawRoundedRect(beam.adjusted(-grow, -grow, grow, grow), thin / 2 + grow, thin / 2 + grow)
            p.setBrush(color)
            p.drawRoundedRect(beam, thin / 2, thin / 2)
        if self.nexus and self._reveal:
            self._paint_wave(p, track_rect)
        size = 18.0
        dot = QRectF(thumb_rect.center().x() - size / 2, thumb_rect.center().y() - size / 2, size, size)
        if _glows() and not themes.reduce_effects():
            p.drawPixmap(QPointF(dot.center().x() - 18, dot.center().y() - 18), _glow(color.name(), 36, self.devicePixelRatioF(), 110))
        p.setBrush(QColor(themes.color("bg")))
        p.setPen(QPen(color, 3))
        p.drawEllipse(dot.adjusted(1.5, 1.5, -1.5, -1.5))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(themes.color("focus")), 2))
            p.drawEllipse(dot.adjusted(-3, -3, 3, 3))

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


SCALE_MARKS_DB = ((12.0, "+12"), (0.0, "0"), (-10.0, "-10"), (-20.0, "-20"), (-40.0, "-40"))


class DbScale(QWidget):
    """0.12.2: the dB marks beside an upright fader (a mix card had a tall empty column there), lined up with the fader's own travel
    so the 0 mark is level with the handle at 0 dB."""

    def __init__(self, fader: "Fader") -> None:
        super().__init__()
        self.fader = fader
        self.setFixedWidth(28)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, _event) -> None:
        from PySide6.QtGui import QFont
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(p.font())
        font.setPixelSize(11)
        p.setFont(font)
        color = QColor(themes.color("text_off"))
        offset = self.fader.mapTo(self.window(), QPointF(0, 0)).y() - self.mapTo(self.window(), QPointF(0, 0)).y()
        half, span = self.fader._travel()
        for db, text in SCALE_MARKS_DB:
            y = offset + half + (1.0 - db_to_fader_position(db)) * span
            p.setPen(QPen(color, 1))
            p.drawLine(QPointF(self.width() - 5, y), QPointF(self.width() - 1, y))
            p.setPen(color)
            p.drawText(QRectF(0, y - 8, self.width() - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        p.end()


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
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
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
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
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
        """Take the newest level. The ring is repainted at most 20 times a second: the eye cannot tell, and drawing is the cost.
        (``slow`` is kept for callers; the fall is timed in seconds since 0.12.3.)"""
        if self.muted:
            linear = 0.0
        frac = level_fraction(linear)
        self._level = max(frac, self._level - 0.9 * elapsed(self))  # a ring falls faster than a bar: about 54 dB a second
        step = int(self._level * self.STEPS + 0.5) if self._level > 0.03 else 0
        if step != self._step:
            self._step = step
            self._dirty = True
            self._glow_due = True
        self._clock = getattr(self, "_clock", 0.0) + FRAME_S  # (time in meter updates, as for the bars)
        if step and not themes.reduce_effects() and self._clock - getattr(self, "_phase_at", -1.0) >= 0.1:  # shimmer: 10 a second
            self._phase_at = self._clock
            self._phase += 1
            self._dirty = True
        due = self._clock - getattr(self, "_drawn_at", -1.0) >= 0.049  # repainted at most 20 times a second
        if self._dirty and due and self.isVisible() and not self.visibleRegion().isEmpty():  # out of sight: nothing redrawn
            self._drawn_at = self._clock
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
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
        if getattr(self, "_on_card", False):
            from .ui_nexus import card_gradient
            backdrop = card_gradient(self)
            if backdrop is not None:
                p.fillRect(self.rect(), backdrop)
        ratio = self.devicePixelRatioF()
        halo = self._step > 0 and not themes.reduce_effects() and themes.current_skin() == "nexus" and _glows()
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
        strength = self._step / self.STEPS
        if halo:  # a halo that grows with the sound (dark themes only)
            p.setOpacity(min(1.0, 0.2 + strength * 0.8))
            p.drawPixmap(QPointF(0, 0), _glow(self.color, self.SIZE, ratio, 70))
            p.setOpacity(1.0)
        # 0.12.2: glowing level rings. The outer ring's arc is the level, the inner one follows it with a little shimmer; the rest of
        # each ring is a dim track. Arcs start at the top and run clockwise.
        p.setBrush(Qt.BrushStyle.NoBrush)
        track = QColor(themes.color("border2"))
        track.setAlpha(170)
        outer = QRectF(c - 34, c - 34, 68, 68)
        inner = QRectF(c - 27, c - 27, 54, 54)
        p.setPen(QPen(track, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawEllipse(outer)
        track.setAlpha(110)
        p.setPen(QPen(track, 2.5))
        p.drawEllipse(inner)
        if alive:
            color = QColor(self.color)
            span = -round(360 * 16 * min(1.0, 0.08 + 0.86 * strength))
            if halo:
                glow = QColor(color)
                glow.setAlpha(70)
                p.setPen(QPen(glow, 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(outer, 90 * 16, span)
            p.setPen(QPen(color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(outer, 90 * 16, span)
            shimmer = 0.82 + 0.12 * math.sin(phase * 1.05)
            soft = QColor(themes.mix(self.color, "#ffffff", 0.45))
            p.setPen(QPen(soft, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(inner, 90 * 16, round(span * shimmer))
        if self._pix is None:
            self._pix = self._picture_for(ratio)
        p.setOpacity(1.0 if alive and not self.muted else 0.45)
        p.save()
        p.translate(c, c)
        p.scale(0.78, 0.78)  # the picture sits inside the inner ring
        p.drawPixmap(QPointF(-18, -18), self._pix)
        p.restore()
        p.setOpacity(1.0)
        # (0.12.0: the chain badge for linked levels is in the card's header now, beside the name, not on the ring)
        if self.muted and small:  # too small for the word: the inner circle in the mute colour says it
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(themes.color("mute")), 3))
            p.drawEllipse(QPointF(c, c), 27.0, 27.0)
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
