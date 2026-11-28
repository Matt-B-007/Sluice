# SPDX-License-Identifier: GPL-3.0-or-later
"""Meters and faders: the level meter, the fader with its taper and the source picture."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractSlider, QSizePolicy, QWidget

from . import themes, ui_paint, ui_icons as icons
from .model import MAX_DB, MIN_DB
from .ui_base import _is_tile, db_to_fader_position, fader_position_to_db, FADER_STEPS, level_fraction

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
        self._well = QColor(themes.color("meter_bg"))
        self._peak_color = QColor(themes.color("strong"))
        self.tint: Optional[str] = None  # 0.12.2: Calm lights a meter in its channel's or mix's colour, amber near the top

    def set_tint(self, color: Optional[str]) -> None:
        if color != self.tint:
            self.tint = color
            self._lit = None
            self._rounded = None
            self._painted = None
            self.update()

    def refresh_theme(self) -> None:
        """Pick up the colours of the theme in use (the track behind the bar, the peak line)."""
        self._well = QColor(themes.color("meter_bg"))
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
            p.setRenderHints(
                QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
            )  # 0.12.2: smooth edges everywhere
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
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )  # 0.12.2: smooth edges everywhere
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
        self.tile = _is_tile()
        self.setOrientation(Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical)
        self.setRange(0, FADER_STEPS)
        self.setValue(round(db_to_fader_position(0.0) * FADER_STEPS))
        self.setSingleStep(8)
        self.setPageStep(60)
        self.thumb = thumb or ((16, 24) if horizontal else (32, 16))  # (width, height) of the handle
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

    def refresh_theme(self) -> None:
        self.update()

    def _announce(self, *_args) -> None:
        from .ui_base import format_db

        text = format_db(self.gain() / 10.0)
        if text != self.accessibleDescription():
            self.setAccessibleDescription(text)

    def sliderChange(self, change) -> None:  # noqa: N802
        """0.13.1-beta.3: also when the value is set without signals (at start, or by a linked fader): screen readers were told
        "0.0 dB" for every fader until it was first moved by hand."""
        super().sliderChange(change)
        if change == QAbstractSlider.SliderChange.SliderValueChange:
            self._announce()

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
        groove = track / 2.0
        # Calm: the groove looks sunk in, a shade along its top inside edge (Tile shades its own below)
        ui_paint.groove(p, track_rect, QColor(themes.color("track")), 0 if self.tile else 60, across=not self.horizontal)
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
        ui_paint.handle(
            p,
            thumb_rect,
            themes.color("handle_hover" if self.underMouse() else "handle"),
            themes.color("handle_edge"),
            focus=QColor(themes.color("focus")) if self.hasFocus() else None,
        )
        p.end()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
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
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )  # 0.12.2: smooth edges everywhere
        if self.device:
            ratio = self.devicePixelRatioF()
            pixmap = icons.render("mic", themes.color("text2"), round(self.size_ * ratio))
            pixmap.setDevicePixelRatio(ratio)
            p.drawPixmap(0, 0, pixmap)
        else:
            p.drawPixmap(0, 0, icons.app_pixmap(self.spec, self.label, self.size_, self.devicePixelRatioF(), self.key))
        p.end()
