# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt interface: channels on the left, the two mixes on the right, running apps along the bottom."""
from __future__ import annotations

from functools import partial
import json
import logging
import math
from pathlib import Path
import threading
import time
from typing import Optional

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFontMetrics, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (
    QAbstractSlider,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import efficiency, rawmic, __version__, logs, report, selfupdate, sizing, themes, updates, whatsnew
from . import ui_icons as icons
from .engine import Engine
from .flow import FlowLayout
from .model import MAX_DB, MIN_DB, MONITOR, RECORDING, STREAM, Channel, Mix, Mixer, linear_to_db, list_backups
from .ui_constants import (AUTO_UPDATE_DELAY_MS, AUTOSAVE_MS, CLOSE_HINT, DEFAULT_SIZE, DISCORD_URL, ISSUES_URL, PROJECT_URL,
                           TALKING_HOLD, TALKING_LEVEL, THEMES_URL, TRAY_WATCH_MS)
from .ui_desktop import DesktopWidgetManager
from .ui_effects import EffectsDialog
from .ui_menus import MenusMixin
from .ui_mini import MiniStrip
from .ui_themes import ThemesMixin, _palette_for
from .ui_tray import TrayMixin
from .ui_updating import UpdatingMixin, _UpdateBridge
from .ui_widgets import ReadoutEdit

log = logging.getLogger("sluice.ui")
# Names that moved to other modules but are still reachable as ``ui.NAME`` (the tests and other code use them there).
__all__ = ["AUTO_UPDATE_DELAY_MS", "AUTOSAVE_MS", "CLOSE_HINT", "DEFAULT_SIZE", "DISCORD_URL", "ISSUES_URL", "PROJECT_URL", "TALKING_HOLD",
           "TALKING_LEVEL", "THEMES_URL", "TRAY_WATCH_MS", "_palette_for"]
NONE_DATA = "__none__"  # combo item data for "no device" (Qt dislikes None)
ORIGINAL_CHANNEL_WIDTH = 180        # the Original look: a channel strip with two mixes, as in 0.9.7
ORIGINAL_CHANNEL_WIDTH_THREE = 232  # ...and with the third mix
ORIGINAL_MIX_WIDTH = 132
ORIGINAL_SOURCES_HEIGHT = 84
MIC_ROW = 26                 # the Original look's mic button row
ADD_MIX_WIDTH = 84           # the Original look's "+ Recording mix" strip
SOURCES_HEIGHT = 80  # the list of a channel's devices and apps: always this tall, so every card is the same height
COLUMN_WIDTH = 80            # one mix's column on a channel card: the fader, its meter, the level and the mute button
CHANNEL_WIDTH = 2 * COLUMN_WIDTH + 32     # a channel card with two mixes (Listen and Broadcast)
CHANNEL_WIDTH_THREE = 3 * COLUMN_WIDTH + 32   # ...and with the optional third one
MIX_WIDTH = 224              # a master card in the Columns layout
FIRST_RUN_WIDTH = 560
ROW_NAME_WIDTH = 148         # the Rows layout: the name and what is on the channel
ROW_TOOLS_WIDTH = 148        # ...the Effects and Link buttons
ROW_CELL_MIN = 210           # ...and the least width of one mix's slider, level and mute button
LAYOUTS = ("columns", "rows", "free")
EMPTY_HINTS = {"mic": "Your microphone goes here.", "browser": "Chrome, Firefox and other browsers.",
               "game": "Games and anything loud.", "chat": "Discord and voice chat.", "music": "Spotify, VLC and players.",
               "system": "Notification sounds and everything else."}
MIX_TAGS = {MONITOR: "LISTEN", STREAM: "BROADCAST", RECORDING: "RECORDING"}
MIX_HEADINGS = {MONITOR: "you hear", STREAM: "audience hears", RECORDING: "recorder hears"}
MIX_NAMES = {MONITOR: "Listen: what you hear", STREAM: "Broadcast: what your audience hears",
             RECORDING: "Recording: what your recorder hears"}


def channel_width(mix_count: int) -> int:
    if themes.current_look() == "original":
        return ORIGINAL_CHANNEL_WIDTH if mix_count <= 2 else ORIGINAL_CHANNEL_WIDTH_THREE
    return CHANNEL_WIDTH if mix_count <= 2 else CHANNEL_WIDTH_THREE


def _is_nexus(rows: bool = False) -> bool:
    """True in the Nexus look (the Columns layout; the Rows layout keeps its own shape until Nexus has one)."""
    return themes.current_look() == "nexus" and not rows


def _is_original(rows: bool = False) -> bool:
    """True in the Original look (the Columns layout only: the Rows layout did not exist in 0.9.7)."""
    return themes.current_look() == "original" and not rows

STYLE = themes.build_style(themes.DARK)  # the default look; MainWindow.apply_theme() sets the chosen one


def level_fraction(linear: float) -> float:
    """Map a linear amplitude to 0..1 along a -60 dB .. 0 dB meter scale."""
    return max(0.0, min(1.0, (linear_to_db(linear) - MIN_DB) / -MIN_DB))


def format_db(db: float) -> str:
    if db <= MIN_DB:
        return "-inf dB"
    return "0.0 dB" if abs(db) < 0.05 else f"{db:+.1f} dB"


class ElidedLabel(QLabel):
    """A one-line label that ends in an ellipsis when its text does not fit, instead of being cut off (and that never makes its
    layout wider than the room there is)."""

    def __init__(self, text: str = "", tip_when_cut: bool = False) -> None:
        super().__init__(text)
        self._full = text
        self._tip_when_cut = tip_when_cut  # the whole text as a tooltip while it is cut
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._show_fitting()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._show_fitting()

    def _show_fitting(self) -> None:
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, max(8, self.width()))
        QLabel.setText(self, shown)
        if self._tip_when_cut:
            self.setToolTip(self._full if shown != self._full else "")

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().minimumSizeHint().height())


def elide(text: str, width: int, widget: QWidget) -> str:
    return QFontMetrics(widget.font()).elidedText(text, Qt.TextElideMode.ElideRight, width)


# ----------------------------------------------------------------------- basics
# Fader taper: (position 0..1 along the fader, dB). Most of the travel is spent between -30 dB and +12 dB, where
# you actually mix, and the quiet end is squeezed together. A straight dB scale spends most of the fader on levels
# nobody uses, so a small move near the top changes the sound far less than a small move near the bottom.
FADER_TAPER = ((0.0, MIN_DB), (0.14, -40.0), (0.25, -30.0), (0.38, -20.0), (0.55, -10.0), (0.75, 0.0), (1.0, MAX_DB))
FADER_STEPS = 1000


def fader_position_to_db(position: float) -> float:
    position = max(0.0, min(1.0, position))
    for (p0, d0), (p1, d1) in zip(FADER_TAPER, FADER_TAPER[1:]):
        if position <= p1:
            return d0 + (d1 - d0) * (position - p0) / (p1 - p0)
    return MAX_DB


def db_to_fader_position(db: float) -> float:
    db = max(MIN_DB, min(MAX_DB, db))
    for (p0, d0), (p1, d1) in zip(FADER_TAPER, FADER_TAPER[1:]):
        if db <= d1:
            return p0 + (p1 - p0) * (db - d0) / (d1 - d0)
    return 1.0


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
        self._painted = None
        self.update()

    def _length(self) -> int:
        return self.width() if self.horizontal else self.height()

    def _shown(self) -> tuple:
        length = self._length()
        return int(length * self._level), (int(length * self._peak) if self._peak > 0.02 else -1)

    def resizeEvent(self, event) -> None:
        self._lit = None
        self._painted = None
        super().resizeEvent(event)

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

    def paintEvent(self, _event) -> None:
        if self.original:
            self._paint_original()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = min(rect.width(), rect.height()) / 2
        shape = QPainterPath()
        shape.addRoundedRect(rect, radius, radius)
        p.setClipPath(shape)
        p.fillRect(rect, self._well)
        fill, peak = self._shown()
        ratio = self.devicePixelRatioF()
        lit = self._lit_pixmap()
        if fill > 0:
            if self.horizontal:
                p.drawPixmap(0, 0, lit, 0, 0, int(fill * ratio), int(rect.height() * ratio))
            else:
                top = self.height() - fill
                p.drawPixmap(0, top, lit, 0, int(top * ratio), int(rect.width() * ratio), int(fill * ratio))
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
        p.setBrush(QColor(themes.color("fill") if self.original else self.fill_color))
        p.drawRoundedRect(fill_rect, groove, groove)
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


class DeviceCombo(QComboBox):
    """Device picker. Item data: '' = system default, NONE_DATA = disabled, else a device name. ``prefix`` is drawn before the
    chosen name on the closed box ("Output: ...") and is not part of the list."""

    about_to_show = Signal()

    def __init__(self, prefix: str = "") -> None:
        super().__init__()
        self.prefix = prefix
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.setFixedHeight(40)

    def showPopup(self) -> None:
        self.about_to_show.emit()
        super().showPopup()

    def paintEvent(self, _event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = (self.prefix + option.currentText) if option.currentText or self.prefix else ""
        room = max(16, self.width() - 12 * 2 - 24)
        option.currentText = QFontMetrics(self.font()).elidedText(text, Qt.TextElideMode.ElideRight, room)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

    def populate(self, devices, current: Optional[str], default_description: Optional[str] = None) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItem(f"{default_description} (system default)" if default_description else "Default", "")
        self.setItemData(0, "Follow the system default device", Qt.ItemDataRole.ToolTipRole)
        self.addItem("None", NONE_DATA)
        names = set()
        # stereo devices first; multichannel interfaces after them, labelled, because only their first two channels are used
        for device in sorted(devices, key=lambda d: d.channels > 2):
            multi = device.channels > 2
            self.addItem(f"{device.description}  [{device.channels} channels]" if multi else device.description, device.name)
            tip = device.name
            if multi:
                tip += (f"\n{device.channels}-channel device: Sluice plays into its first two channels, which may not be "
                        "your headphones. If a stereo entry for the same hardware exists, use that.")
            self.setItemData(self.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
            names.add(device.name)
        wanted = NONE_DATA if current is None else current
        if wanted not in ("", NONE_DATA) and wanted not in names:
            self.addItem(f"{wanted} (missing)", wanted)
        self.setCurrentIndex(max(0, self.findData(wanted)))
        self.blockSignals(False)

    def selected_device(self) -> Optional[str]:
        data = self.currentData()
        return None if data == NONE_DATA else data


def _toggle(text: str, object_name: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setObjectName(object_name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def _slot(widget: QWidget, height: int = 40) -> QWidget:
    """Fixed-height holder so faders line up across strips with different headers."""
    box = QWidget()
    box.setFixedHeight(height)
    inner = QVBoxLayout(box)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
    return box


def _label(text: str, name: str = "", center: bool = True) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    if center:
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


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


MIX_ICONS = {MONITOR: "headphones", STREAM: "broadcast", RECORDING: "mic"}


_GLOWS: dict = {}


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

    def __init__(self, color: str, picture) -> None:
        super().__init__()
        self.color, self._picture_for, self._pix = color, picture, None
        self._level, self._step, self._phase, self._tick = 0.0, 0, 0, 0
        self._dirty, self._gate = False, 0
        self.linked, self.muted, self._badge = False, False, None
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def refresh_source(self) -> None:
        self._pix = None
        self.update()

    def refresh_theme(self) -> None:
        self._pix = self._badge = None
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
        if step and not themes.reduce_effects():
            self._tick += 1
            if self._tick % 3 == 0:
                self._phase += 1
                self._dirty = True
        self._gate ^= 1
        if self._dirty and self._gate:
            self._dirty = False
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.SIZE / 2.0
        alive = self._step > 0
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(themes.color("border2")), 1))
        p.drawEllipse(QPointF(c, c), 25.0, 25.0)
        strength = self._step / self.STEPS
        if alive and not themes.reduce_effects() and themes.current_look() == "nexus":  # a soft halo that grows with the sound (Nexus only)
            p.setOpacity(min(1.0, 0.25 + strength))
            p.drawPixmap(QPointF(0, 0), _glow(self.color, self.SIZE, self.devicePixelRatioF()))
            p.setOpacity(1.0)
        path = QPainterPath()
        for i, (cos, sin) in enumerate(self._ANGLES):
            length = 2.0 + (14.0 * strength * (0.55 + 0.45 * abs(math.sin(i * 1.3 + self._phase * 1.05))) if alive else 0.0)
            path.moveTo(c + cos * 28, c + sin * 28)
            path.lineTo(c + cos * (28 + length), c + sin * (28 + length))
        pen_color = QColor(self.color) if alive else QColor(themes.color("text_off"))
        if not alive:
            pen_color.setAlpha(120)
        p.setPen(QPen(pen_color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        if self._pix is None:
            self._pix = self._picture_for(self.devicePixelRatioF())
        p.setOpacity(1.0 if alive and not self.muted else 0.45)
        p.drawPixmap(QPointF(c - 18, c - 18), self._pix)
        p.setOpacity(1.0)
        if self.linked:
            if self._badge is None:
                ratio = self.devicePixelRatioF()
                self._badge = icons.render("link", themes.color("accent"), round(14 * ratio))
                self._badge.setDevicePixelRatio(ratio)
            p.setBrush(QColor(themes.color("accent_bg")))
            p.setPen(QPen(QColor(themes.color("accent")), 1))
            p.drawEllipse(QPointF(14, 14), 10.0, 10.0)
            p.drawPixmap(QPointF(7, 7), self._badge)
        if self.muted:
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


class MixHeading(QWidget):
    """A column heading of the Rows layout: an icon and "LISTEN · you hear", in the colour of that mix."""

    def __init__(self, mix_id: str, text: str) -> None:
        super().__init__()
        self.mix_id = mix_id
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 0, 0)
        row.setSpacing(8)
        self.picture = QLabel()
        self.picture.setFixedSize(18, 18)
        self.text = QLabel(text)
        self.text.setObjectName("mixheading")
        self.text.setProperty("mix", mix_id)
        row.addWidget(self.picture)
        row.addWidget(self.text, 1)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        color = themes.mix_colors(themes._current).get({MONITOR: "listen", STREAM: "broadcast"}.get(self.mix_id, ""), themes.color("text2"))
        ratio = self.devicePixelRatioF()
        pixmap = icons.render(MIX_ICONS.get(self.mix_id, "speaker"), color, round(18 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        self.picture.setPixmap(pixmap)


class Chip(QFrame):
    """A source on a channel: a device or an app (with its picture), and a remove button."""

    def __init__(self, text: str, tooltip: str, on_remove, picture: Optional[SourcePicture] = None) -> None:
        super().__init__()
        original = _is_original()
        self.setObjectName("chip" if original else "sourcechip")
        if not original:
            self.setFixedHeight(32)
        row = QHBoxLayout(self)
        row.setContentsMargins(*((6, 1, 2, 1) if original else (8, 0, 4, 0)))
        row.setSpacing(2 if original else 8)
        self.picture = picture
        if picture is not None:
            row.addWidget(picture)
        self.label = QLabel(elide(text, 118 if original else (88 if picture is not None else 120), self))
        self.label.setObjectName("chiptext")
        self.label.setToolTip(tooltip or text)
        close = QToolButton()
        close.setObjectName("remove")
        close.setText("×")
        if not original:
            close.setFixedSize(24, 24)
        close.setToolTip("Remove")
        close.setAccessibleName(f"Remove {text}")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(on_remove)
        row.addWidget(self.label, 1)
        row.addWidget(close)


# --------------------------------------------------------------------- channels
def own_device_message(channel: Channel, on: bool) -> str:
    if not on:
        return f"{channel.label} is no longer offered as its own recording device."
    return (f"\u201c{channel.solo_description}\u201d is now available in OBS and other recorders. It carries only "
            f"{channel.label}, after its effects, and does not follow the faders or mute buttons.")


class OwnDevicesDialog(QDialog):
    """One list of channels with a tick for each one that should also be its own recording device."""

    def __init__(self, engine: Engine, window: "MainWindow") -> None:
        super().__init__(window)
        self.engine, self.window_ = engine, window
        self.setWindowTitle("Recording devices for OBS")
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tick a channel to make it show up as its own microphone, so OBS or another recorder can record just that "
            "channel (for example one track for your mic and another for the game).\n\n"
            "Each one carries only that channel, after its effects. It ignores the faders and mute buttons, so what you "
            "record does not change when you adjust the live mix. In OBS add an Audio Input Capture and choose "
            "\u201cSluice (channel name)\u201d, for example \u201cSluice (Game)\u201d.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.boxes: dict = {}
        for channel in engine.mixer.channels:
            box = QCheckBox(f"{channel.label}   \u2192   {channel.solo_description}")
            box.setChecked(channel.separate)
            box.toggled.connect(partial(self._toggled, channel.id))
            layout.addWidget(box)
            self.boxes[channel.id] = box
        layout.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        close.accepted.connect(self.accept)
        layout.addWidget(close)

    def _toggled(self, channel_id: str, on: bool) -> None:
        channel = self.engine.mixer.channel(channel_id)
        self.engine.set_separate(channel_id, on)
        self.window_.say(own_device_message(channel, on))
        self.window_.rebuild_channels()  # the strips' menus and tooltips follow


MIX_MUTE_TIPS = {MONITOR: "what you hear", STREAM: "what your audience hears", RECORDING: "what your recorder hears"}


def mute_tip(mix, muted: bool) -> str:
    what = MIX_MUTE_TIPS.get(mix.id, f"the {mix.label} mix")
    return f"Muted: {what} has none of this channel. Click to unmute." if muted else f"Mute this channel in {what}"


class RowCard(QFrame):
    """A channel row of the Rows layout: a card with a bar in the channel's colour along its left edge."""

    def __init__(self, color: str) -> None:
        super().__init__()
        self.setObjectName("row")
        self.bar_color = color

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)
        p.setClipPath(shape)
        p.fillRect(QRectF(0, 0, 8, self.height()), QColor(self.bar_color))
        p.end()


def _icon_button(name: str, tip: str, size: int, checkable: bool = False, compact: bool = False) -> QPushButton:
    button = QPushButton()
    button.setObjectName("iconbutton")
    button.setFixedSize(size, size)
    button.setToolTip(tip)
    button.setAccessibleName(tip.split(":")[0])
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setCheckable(checkable)
    if compact:
        button.setProperty("compact", True)
    return button


class ChannelStrip(QWidget):
    """One channel: a card in the Columns layout (faders side by side) or a row in the Rows layout (sliders along the row)."""

    def __init__(self, channel: Channel, engine: Engine, window: "MainWindow", rows: bool = False) -> None:
        super().__init__()
        self.setObjectName("channelstrip")
        self.rows = rows
        self.original = _is_original(rows)  # the Original look: the strip as it was in 0.9.7 (text buttons, a colour bar on top)
        self.nexus = _is_nexus(rows)        # the Nexus look: a ring meter with the app's picture above the name
        self.ring = None
        mixes = len(engine.mixer.mixes)
        self.channel, self.engine, self.window = channel, engine, window
        self.compact = mixes > 2  # three fader columns share the strip
        self.faders: dict = {}
        self.meters: dict = {}
        self.readouts: dict = {}
        self.mutes: dict = {}
        self._empty = False

        self.frame = RowCard(channel.color) if rows else QFrame()
        if not rows:
            self.frame.setObjectName("strip")
            self.setFixedWidth(channel_width(mixes))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)
        self.layout_root = QVBoxLayout(self.frame) if not rows else QHBoxLayout(self.frame)
        if rows:
            self.layout_root.setContentsMargins(24, 8, 24, 8)
            self.layout_root.setSpacing(16)
        elif self.original:
            self.layout_root.setContentsMargins(8, 8, 8, 8)
            self.layout_root.setSpacing(6)
        else:
            self.layout_root.setContentsMargins(16, 16, 16, 16)
            self.layout_root.setSpacing(16)

        self.title = QLabel(channel.label)
        self.title.setObjectName("title" if self.original else "name")
        if self.original:
            self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setToolTip(self._title_tip())
        self.title.mouseDoubleClickEvent = lambda _e: self.rename()
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.dot.setStyleSheet(f"background: {channel.color}; border-radius: 6px;")

        # A channel with a microphone gets the mute button for every microphone, right on the card.
        if self.original:
            self.mic_button = QPushButton()
            self.mic_button.setObjectName("micmute")
            self.mic_button.setCheckable(True)
            self.mic_button.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.mic_button = _icon_button("mic", "", 32, checkable=True, compact=True)
            self.mic_button.setObjectName("micmute")
        self.mic_button.clicked.connect(lambda _checked=False: self.window.toggle_mic_mute())

        if self.original:
            self.menu_button = QToolButton()
            self.menu_button.setObjectName("menu")
            self.menu_button.setText("\u22ee")
            self.menu_button.setToolTip("Channel options")
            self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        else:
            self.menu_button = _icon_button("more", "Channel options", 32, compact=True)
            self.menu_button.setObjectName("plain")

        self.fx_button = QPushButton()
        if not self.original:
            self.fx_button.setProperty("compact", True)
            self.fx_button.setFixedHeight(32)
        self.fx_button.setToolTip("Open this channel's effects")
        self.fx_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fx_button.clicked.connect(self.open_effects)

        if self.original:
            self.link = _toggle("LINK", "link", "Link levels: moving one fader moves the other")
        else:
            self.link = _icon_button("link", "Link levels: moving one fader moves the other", 32, checkable=True, compact=True)
            self.link.setObjectName("link")
        self.link.toggled.connect(self._on_link)

        self.add_button = QPushButton(("+ Add device or app" if self.original else "+ Add app or device") if not rows else "")
        self.add_button.setObjectName("add" if self.original else "addchip")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setToolTip("Add an app, a game or a device to this channel")
        self.add_button.setAccessibleName(f"Add app or device to {channel.label}")
        self.add_menu = QMenu(self.add_button)
        self.add_menu.aboutToShow.connect(self._build_add_menu)
        self.add_button.setMenu(self.add_menu)
        self.menu = QMenu(self.menu_button)
        self._build_options_menu()
        self.menu_button.setMenu(self.menu)

        if rows:
            self._build_rows()
        elif self.original:
            self._build_columns_original()
        else:
            self._build_columns()
        self.refresh_sources()
        self.sync_from_model()
        self.refresh_theme()

    # ------------------------------------------------------------------ building
    def _title_tip(self) -> str:
        c = self.channel
        return (f"Also recordable as “{c.solo_description}”. Double-click to rename" if c.separate
                else "Double-click to rename")

    def _build_options_menu(self) -> None:
        menu = self.menu
        self.add_menu.setTitle("Add app or device")
        menu.addMenu(self.add_menu)
        menu.addAction("Rename…", self.rename)
        self.separate_action = menu.addAction("")
        self.separate_action.setCheckable(True)
        self.separate_action.setToolTip("Offer this channel on its own as a microphone-style input, so OBS, Discord or a game "
                                        "can use just this channel (after its effects). Not needed for the Broadcast mix.")
        self.separate_action.triggered.connect(lambda _checked=False: self.toggle_separate())

        def refresh_menu() -> None:
            self.separate_action.setText(f"Also offer as its own input: “{self.channel.solo_description}”")
            self.separate_action.setChecked(self.channel.separate)

        menu.aboutToShow.connect(refresh_menu)
        refresh_menu()
        menu.addAction("Delete channel", self.delete)

    def _build_columns(self) -> None:
        layout = self.layout_root
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.dot)
        head.addWidget(self.title, 1)
        head.addWidget(self.mic_button)
        head.addWidget(self.menu_button)
        self.head = QWidget()
        self.head.setFixedHeight(32)
        head.setContentsMargins(0, 0, 0, 0)
        self.head.setLayout(head)
        if self.nexus:
            self.ring = NexusRing(self.channel.color, self._ring_picture)
            self.dot.hide()
            layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.head)
        self.empty_hint = _label(EMPTY_HINTS.get(self.channel.id, "Add the apps for this channel."), "hint", center=False)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.hide()
        layout.addWidget(self.empty_hint)

        # Sources: devices and apps feeding this channel, in a list that is always 80 pixels tall so every card is the same height.
        self.sources_box = QWidget()
        self.sources_box.setObjectName("sources")
        self.sources_layout = QVBoxLayout(self.sources_box)
        self.sources_layout.setContentsMargins(0, 0, 0, 0)
        self.sources_layout.setSpacing(8)
        self.sources_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(SOURCES_HEIGHT)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sources_scroll = scroll
        scroll.setWidget(self.sources_box)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.sources_box.setStyleSheet("QWidget#sources { background: transparent; }")
        layout.addWidget(scroll)
        self.add_button.setFixedHeight(32)
        layout.addWidget(self.add_button)  # always in view, under the list: however many sources there are, adding one is one click

        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(self.fx_button, 1)
        tools.addWidget(self.link)
        self.tools = QWidget()
        self.tools.setFixedHeight(32)
        tools.setContentsMargins(0, 0, 0, 0)
        self.tools.setLayout(tools)
        layout.addWidget(self.tools)

        mixes = self.engine.mixer.mixes
        self.tags = []
        tag_row = QHBoxLayout()
        tag_row.setSpacing(0)
        for mix in mixes:
            tag = _label(MIX_TAGS.get(mix.id, mix.label.upper()), "tag")
            tag.setToolTip(MIX_NAMES.get(mix.id, mix.label))
            tag.setFixedWidth(COLUMN_WIDTH)
            tag.setProperty("mix", mix.id)
            tag.setProperty("narrow", True)  # 11 px, no letter spacing: BROADCAST must fit 80 px even in a wide fallback font
            tag_row.addWidget(tag)
            self.tags.append(tag)
        self.tag_row = QWidget()
        self.tag_row.setFixedHeight(16)
        tag_row.setContentsMargins(0, 0, 0, 0)
        self.tag_row.setLayout(tag_row)
        layout.addWidget(self.tag_row)

        faders = QHBoxLayout()
        faders.setSpacing(0)
        reads = QHBoxLayout()
        reads.setSpacing(0)
        mutes = QHBoxLayout()
        mutes.setSpacing(0)
        for mix in mixes:
            fader, meter = self._make_controls(mix, horizontal=False)
            column = QWidget()
            column.setFixedWidth(COLUMN_WIDTH)
            inner = QHBoxLayout(column)
            inner.setContentsMargins(6, 0, 8, 0)
            inner.setSpacing(16)
            inner.addWidget(fader)
            inner.addWidget(meter)
            faders.addWidget(column)
            readout = self.readouts[mix.id]
            readout.setFixedWidth(COLUMN_WIDTH)
            reads.addWidget(readout)
            mute = self.mutes[mix.id]
            mute.setFixedSize(COLUMN_WIDTH - 8, 40)
            holder = QWidget()
            holder.setFixedWidth(COLUMN_WIDTH)
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(mute, 0, Qt.AlignmentFlag.AlignCenter)
            mutes.addWidget(holder)
        self.faders_box = QWidget()
        faders.setContentsMargins(0, 0, 0, 0)
        self.faders_box.setLayout(faders)
        layout.addWidget(self.faders_box, 1)
        self.read_row = QWidget()
        self.read_row.setFixedHeight(24)
        reads.setContentsMargins(0, 0, 0, 0)
        self.read_row.setLayout(reads)
        layout.addWidget(self.read_row)
        self.mute_row = QWidget()
        mutes.setContentsMargins(0, 0, 0, 0)
        self.mute_row.setLayout(mutes)
        layout.addWidget(self.mute_row)
        self.filler = QWidget()  # takes the space of the faders while a channel is empty (first run), so the card keeps its shape
        self.filler.hide()
        layout.addWidget(self.filler, 1)

    def _build_columns_original(self) -> None:
        """The channel strip of 0.9.7: a bar in the channel's colour, the name with its menu, SOURCES, a dashed add button, then
        Effects, LINK and one fader column for each mix. It keeps the same parts as the Calm card, so everything still works."""
        layout = self.layout_root
        accent = QFrame()
        accent.setObjectName("accent")
        accent.setFixedHeight(4)
        accent.setStyleSheet(f"background: {self.channel.color};")
        layout.addWidget(accent)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addSpacing(18)
        head.addWidget(self.title, 1)
        head.addWidget(self.menu_button)
        self.head = QWidget()
        self.head.setLayout(head)
        layout.addWidget(self.head)
        self.mic_row = _slot(self.mic_button, MIC_ROW)
        layout.addWidget(self.mic_row)
        self.empty_hint = _label(EMPTY_HINTS.get(self.channel.id, "Add the apps for this channel."), "hint", center=False)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.hide()
        layout.addWidget(self.empty_hint)
        self.sources_tag = _label("SOURCES", "tag")
        layout.addWidget(self.sources_tag)
        self.sources_box = QWidget()
        self.sources_box.setObjectName("sources")
        self.sources_layout = QVBoxLayout(self.sources_box)
        self.sources_layout.setContentsMargins(0, 0, 0, 0)
        self.sources_layout.setSpacing(3)
        self.sources_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sources_scroll = scroll
        scroll.setWidget(self.sources_box)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.sources_box.setStyleSheet("QWidget#sources { background: transparent; }")
        layout.addWidget(scroll)
        layout.addWidget(self.add_button)
        tools = QVBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)
        tools.addWidget(self.fx_button)
        tools.addWidget(self.link)
        self.tools = QWidget()
        self.tools.setLayout(tools)
        layout.addWidget(self.tools)

        mixes = self.engine.mixer.mixes
        width = (channel_width(len(mixes)) - 16 - 6 * (len(mixes) - 1)) // len(mixes)  # one fader column for each mix
        self.tags = []
        tag_row, faders, reads, mutes = QHBoxLayout(), QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        for box in (tag_row, faders, reads, mutes):
            box.setSpacing(6)
            box.setContentsMargins(0, 0, 0, 0)
        for mix in mixes:
            tag = _label(MIX_TAGS.get(mix.id, mix.label.upper()), "tag")
            tag.setToolTip(MIX_NAMES.get(mix.id, mix.label))
            tag.setFixedWidth(width)
            tag.setProperty("mix", mix.id)
            tag_row.addWidget(tag)
            self.tags.append(tag)
            fader, meter = self._make_controls(mix, horizontal=False)
            column = QWidget()
            column.setFixedWidth(width)
            inner = QHBoxLayout(column)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(2)
            inner.addStretch(1)
            inner.addWidget(fader)
            inner.addWidget(meter)
            inner.addStretch(1)
            faders.addWidget(column)
            self.readouts[mix.id].setFixedWidth(width)
            reads.addWidget(self.readouts[mix.id])
            self.mutes[mix.id].setFixedWidth(width)
            mutes.addWidget(self.mutes[mix.id])
        for attr, box in (("tag_row", tag_row), ("faders_box", faders), ("read_row", reads), ("mute_row", mutes)):
            widget = QWidget()
            widget.setLayout(box)
            setattr(self, attr, widget)
        layout.addWidget(self.tag_row)
        layout.addWidget(self.faders_box, 1)
        layout.addWidget(self.read_row)
        layout.addWidget(self.mute_row)
        self.filler = QWidget()
        self.filler.hide()
        layout.addWidget(self.filler, 1)

    def _build_rows(self) -> None:
        layout = self.layout_root
        layout.setContentsMargins(24, 8, 24, 8)
        layout.addSpacing(0)
        block = QVBoxLayout()
        block.setSpacing(4)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(self.title, 1)
        name_row.addWidget(self.mic_button)
        block.addLayout(name_row)
        self.sources_text = ElidedLabel("")
        self.sources_text.setObjectName("hint")
        block.addWidget(self.sources_text)
        name = QWidget()
        name.setFixedWidth(ROW_NAME_WIDTH)
        block.setContentsMargins(8, 0, 0, 0)
        name.setLayout(block)
        layout.addWidget(name)
        self.add_button.setIcon(icons.icon("plus", themes.color("text_dim"), 18))
        self.add_button.setFixedSize(32, 32)
        self.add_button.setProperty("iconly", True)
        self.add_button.setToolTip("Add an app, a game or a device to this channel")
        layout.addWidget(self.add_button)
        layout.addWidget(self.menu_button)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(self.fx_button, 1)
        tools.addWidget(self.link)
        box = QWidget()
        box.setFixedWidth(ROW_TOOLS_WIDTH)
        tools.setContentsMargins(0, 0, 0, 0)
        box.setLayout(tools)
        layout.addWidget(box)
        for mix in self.engine.mixer.mixes:
            fader, meter = self._make_controls(mix, horizontal=True)
            cell = QHBoxLayout()
            cell.setSpacing(16)
            sliders = QVBoxLayout()
            sliders.setSpacing(4)
            sliders.addWidget(meter)
            sliders.addWidget(fader)
            cell.addLayout(sliders, 1)
            readout = self.readouts[mix.id]
            readout.setFixedWidth(72)
            readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cell.addWidget(readout)
            mute = self.mutes[mix.id]
            mute.setFixedSize(40, 40)
            cell.addWidget(mute)
            holder = QFrame()
            holder.setObjectName("mixcell")
            holder.setProperty("mix", mix.id)  # a tinted panel in the colour of its mix: Listen and Broadcast cannot be mistaken
            holder.setMinimumWidth(ROW_CELL_MIN)
            cell.setContentsMargins(12, 8, 8, 8)
            holder.setLayout(cell)
            layout.addWidget(holder, 1)

    def _make_controls(self, mix: Mix, horizontal: bool) -> tuple:
        fader = Fader(horizontal=horizontal)
        fader.set_fill(self.channel.color)
        fader.setAccessibleName(f"{self.channel.label}, {mix.label} level")
        fader.gainChanged.connect(partial(self._on_level, mix.id))
        meter = LevelMeter(horizontal=horizontal)
        meter.setAccessibleName(f"{self.channel.label}, {mix.label} meter")
        readout = ReadoutEdit(None)
        readout.setProperty("compact", self.compact)
        readout.setAccessibleName(f"{self.channel.label}, {mix.label} level in decibels")
        readout.setToolTip("Scroll over the number to change the level (hold Shift for fine steps), or click and type a level in dB (for example -12) and press Enter")
        readout.wheel_steps = True
        readout.wheeled.connect(partial(self._wheel_level, mix.id))
        readout.entered.connect(partial(self._typed_level, mix.id))
        mute = QPushButton("M" if self.original else "")
        mute.setObjectName("mute")
        mute.setCheckable(True)
        mute.setCursor(Qt.CursorShape.PointingHandCursor)
        mute.setAccessibleName(f"Mute {self.channel.label} in {mix.label}")
        mute.toggled.connect(partial(self._on_mute, mix.id))
        mute.toggled.connect(lambda _on, m=mix: self._show_mute(m))
        self.faders[mix.id], self.meters[mix.id] = fader, meter
        self.readouts[mix.id], self.mutes[mix.id] = readout, mute
        return fader, meter

    def _ring_picture(self, ratio: float) -> QPixmap:
        """The picture in the middle of the ring: the first app on the channel, a microphone for a device, or the channel's letter."""
        channel, engine = self.channel, self.engine
        if channel.apps:
            app = channel.apps[0]
            return icons.app_pixmap(engine.app_icon(app), engine.app_label(app), 36, ratio, app)
        if channel.devices:
            pixmap = icons.render("mic", themes.color("text2"), round(36 * ratio))
            pixmap.setDevicePixelRatio(ratio)
            return pixmap
        return icons.app_pixmap("", channel.label, 36, ratio, channel.id)

    # ------------------------------------------------------------------ theme
    def refresh_theme(self) -> None:
        """Icons and the few colours set in code, from the theme in use."""
        text2, muted = themes.color("text2"), themes.color("text_dim")
        if not self.original:  # the Original look has text on its buttons, no icons
            self.fx_button.setIcon(icons.icon("sliders", text2, 18))
            self.link.setIcon(icons.icon("link", themes.color("accent_text") if self.link.isChecked() else muted, 18))
            self.menu_button.setIcon(icons.icon("more", muted, 20))
        if self.rows:
            self.add_button.setIcon(icons.icon("plus", muted, 18))
        for mix in self.engine.mixer.mixes:
            self._show_mute(mix)
        self.show_mic_state()

    def _show_mute(self, mix: Mix) -> None:
        button = self.mutes.get(mix.id)
        if button is None:
            return
        muted = button.isChecked()
        if not self.original:
            button.setIcon(icons.icon("speaker_off" if muted else "speaker", themes.color("mute_fg" if muted else "text"), 20))
            button.setIconSize(QSize(20, 20))
        button.setToolTip(mute_tip(mix, muted))

    # ------------------------------------------------------------------ sources
    def set_empty(self, empty: bool) -> None:
        """First run: a channel with nothing on it shows only its name, a hint and the add button."""
        if self.rows or empty == self._empty:
            return
        self._empty = empty
        for widget in (self.tools, self.tag_row, self.faders_box, self.read_row, self.mute_row, self.sources_scroll):
            widget.setVisible(not empty)
        self.empty_hint.setVisible(empty)
        self.frame.setProperty("empty", empty)
        self.frame.style().unpolish(self.frame)
        self.frame.style().polish(self.frame)
        self.filler.setVisible(empty)

    def refresh_sources(self) -> None:
        if self.rows:
            self.sources_text.setText(self._sources_summary())
            self.sources_text.setToolTip(self.sources_text.text())
        else:
            while self.sources_layout.count():
                item = self.sources_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.hide()          # hidden at once: the old chips must not show for the moment before they are deleted
                    widget.deleteLater()
            if not self.channel.devices and not self.channel.apps:
                if self.original:
                    nothing = _label("Nothing yet.\nAdd a mic, or an app\nthat should play here.", "hint")
                else:
                    nothing = QLabel("Nothing here yet")
                    nothing.setObjectName("hint")
                self.sources_layout.addWidget(nothing)
            for device in self.channel.devices:
                text, tip = self._device_text(device)
                if self.original:
                    self.sources_layout.addWidget(Chip("\U0001f3a4 " + text, tip + "\nInput device", partial(self._remove_device, device)))
                else:
                    self.sources_layout.addWidget(Chip(text, tip + "\nInput device", partial(self._remove_device, device),
                                                       SourcePicture(text, device=True)))
            for app in self.channel.apps:
                label = self.engine.app_label(app)
                if self.original:
                    self.sources_layout.addWidget(Chip("\u25b6 " + label, f"{label}\nApp: {app}", partial(self._remove_app, app)))
                else:
                    self.sources_layout.addWidget(Chip(label, f"{label}\nApp: {app}", partial(self._remove_app, app),
                                                       SourcePicture(label, self.engine.app_icon(app), app)))
        self._update_fx_button()
        self.show_mic_state()
        if self.ring is not None:
            self.ring.refresh_source()

    def _sources_summary(self) -> str:
        names = [self._device_text(d)[0] for d in self.channel.devices] + [self.engine.app_label(a) for a in self.channel.apps]
        return ", ".join(names) if names else "Nothing here yet"

    def show_mic_state(self) -> None:
        has_mic = bool(self.channel.devices)
        muted = self.engine.mic_muted
        if self.original:
            self.mic_row.setVisible(has_mic)
            self.sources_scroll.setFixedHeight(ORIGINAL_SOURCES_HEIGHT - MIC_ROW - 6 if has_mic else ORIGINAL_SOURCES_HEIGHT)
            self.mic_button.blockSignals(True)
            self.mic_button.setChecked(muted)
            self.mic_button.blockSignals(False)
            self.mic_button.setText("MIC MUTED" if muted else "Mic live")
            self.mic_button.setToolTip("Microphones are muted. Click to unmute every microphone (Ctrl+M)." if muted else
                                       "Mute or unmute every microphone, including the Sluice (Mic) device other apps listen to (Ctrl+M).")
            self.mic_button.setAccessibleName("Unmute microphones" if muted else "Mute microphones")
            return
        self.mic_button.setVisible(has_mic)
        self.mic_button.blockSignals(True)
        self.mic_button.setChecked(muted)
        self.mic_button.blockSignals(False)
        self.mic_button.setIcon(icons.icon("mic_off" if muted else "mic", themes.color("mute_fg" if muted else "text2"), 20))
        self.mic_button.setIconSize(QSize(20, 20))
        self.mic_button.setToolTip("Microphones are muted. Click to unmute every microphone (Ctrl+M)." if muted else
                                   "Microphone is live. Click to mute every microphone, including the Sluice (Mic) device "
                                   "other apps listen to (Ctrl+M).")
        self.mic_button.setAccessibleName("Unmute microphones" if muted else "Mute microphones")

    def _device_text(self, device: str) -> tuple:
        if device == "":
            return "Default mic", "Follows the system default microphone"
        for d in self.engine.sources:
            if d.name == device:
                return d.description, device
        return f"{device} (missing)", device

    def _build_add_menu(self) -> None:
        menu = self.add_menu
        menu.clear()
        engine = self.engine

        devices = menu.addMenu("Microphone or input device")
        action = devices.addAction("System default microphone", partial(self._add_device, ""))
        action.setEnabled("" not in self.channel.devices)
        inputs = [d for d in engine.sources if not d.monitor]
        if inputs:
            devices.addSeparator()
        for d in inputs:
            action = devices.addAction(d.description, partial(self._add_device, d.name))
            action.setEnabled(d.name not in self.channel.devices)

        monitors = [d for d in engine.sources if d.monitor]
        if monitors:
            loops = {engine.resolve_mix_sink(m) for m in engine.mixer.mixes}
            heard = menu.addMenu("Sound playing on an output device")
            for d in monitors:
                node = d.name[: -len(".monitor")]
                action = heard.addAction(d.description + ("  (your own output: would loop)" if node in loops else ""),
                                         partial(self._add_device, d.name))
                action.setEnabled(d.name not in self.channel.devices and node not in loops)

        menu.addAction("App or game\u2026", self._add_installed)

    def _add_device(self, device: str) -> None:
        self.engine.add_device(self.channel.id, device)
        self.refresh_sources()

    def _remove_device(self, device: str) -> None:
        self.engine.remove_device(self.channel.id, device)
        self.refresh_sources()

    def _add_app(self, key: str) -> None:
        self.engine.assign_app(key, self.channel.id)
        self.window.refresh_sources()

    def _remove_app(self, key: str) -> None:
        label = self.engine.app_label(key)
        self.engine.assign_app(key, None)
        self.window.refresh_sources()
        self.window.say(f"{label} is no longer in the mixer: it plays straight to your normal output, so you can still hear it.")

    def _add_installed(self) -> None:
        from .ui_apps import AppPickerDialog

        def owner_of(key: str) -> Optional[str]:
            for channel in self.engine.mixer.channels:
                if key in channel.apps:
                    return channel.label if channel.id != self.channel.id else None
            return None

        running, seen = [], set()
        for stream in self.engine.streams:
            if stream.assign_key not in seen:
                seen.add(stream.assign_key)
                running.append((stream.name, stream.assign_key))
        dialog = AppPickerDialog(self.engine.catalog, self.channel.label, owner_of, self, running=running)
        if dialog.exec():
            for key in dialog.selected_keys():
                self.engine.assign_app(key, self.channel.id)
            self.window.refresh_sources()

    # ------------------------------------------------------------------ actions
    def rename(self) -> None:
        text, ok = QInputDialog.getText(self, "Rename channel", "Name:", text=self.channel.label)
        if ok and text.strip():
            self.engine.rename_channel(self.channel.id, text)
            self.title.setText(self.channel.label)
            self.window.refresh_sources()

    def delete(self) -> None:
        answer = QMessageBox.question(
            self, "Delete channel", f"Delete “{self.channel.label}”? Apps on it go back to your default output."
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.window.remove_channel(self.channel.id)

    def open_effects(self) -> None:
        EffectsDialog(self.engine, self.channel, self.window).exec()
        self._update_fx_button()

    def _update_fx_button(self) -> None:
        active = [e for e in self.channel.effects if not e.bypass]
        count = len(self.channel.effects)
        if self.original:
            self.fx_button.setText("Effects" if count == 0 else f"Effects ({len(active)}/{count} on)")
        else:
            self.fx_button.setText("Effects" if count == 0 else (f"{count} effect" if count == 1 else f"{count} effects") if len(active) == count else f"{len(active)} of {count} on")
        self.fx_button.setToolTip("Open this channel's effects" if count == 0 else
                                  f"Open this channel's effects: {len(active)} of {count} are on")

    def _on_level(self, mix_id: str, value: int) -> None:
        db = value / 10.0
        self.engine.set_level(self.channel.id, mix_id, db)
        self.sync_from_model()

    def _typed_level(self, mix_id: str, number) -> None:
        if number is not None and number == number:
            self.engine.set_level(self.channel.id, mix_id, max(MIN_DB, min(MAX_DB, number)))
        self.sync_from_model()  # shows the real value again, also when what was typed was not a number

    def _wheel_level(self, mix_id: str, notches: float) -> None:
        fader = self.faders[mix_id]
        fader.setGain(max(int(MIN_DB * 10), min(int(MAX_DB * 10), fader.gain() + int(round(notches * 10)))))

    def _on_mute(self, mix_id: str, on: bool) -> None:
        self.engine.set_mute(self.channel.id, mix_id, on)

    def toggle_separate(self) -> None:
        on = not self.channel.separate  # from the real state, not from a tick mark that might be stale
        self.engine.set_separate(self.channel.id, on)
        self.window.say(own_device_message(self.channel, on))
        self.title.setToolTip(self._title_tip())

    def _on_link(self, on: bool) -> None:
        self.engine.set_linked(self.channel.id, on)
        if not self.original:
            self.link.setIcon(icons.icon("link", themes.color("accent_text") if on else themes.color("text_dim"), 18))
        self.sync_from_model()

    def sync_from_model(self) -> None:
        channel = self.channel
        widgets = [self.link, *self.faders.values(), *self.mutes.values()]
        for widget in widgets:
            widget.blockSignals(True)
        self.link.setChecked(channel.linked)
        if not self.original:
            self.link.setIcon(icons.icon("link", themes.color("accent_text") if channel.linked else themes.color("text_dim"), 18))
        for mix_id, fader in self.faders.items():
            db = channel.levels.get(mix_id, 0.0)
            fader.setGain(round(db * 10))
            self.readouts[mix_id].setText(format_db(db))
            self.mutes[mix_id].setChecked(bool(channel.mutes.get(mix_id)))
        for widget in widgets:
            widget.blockSignals(False)
        for mix in self.engine.mixer.mixes:
            self._show_mute(mix)
        self.show_mic_state()
        if self.ring is not None:
            mixes = self.engine.mixer.mixes
            self.ring.set_state(channel.linked, bool(mixes) and all(channel.mutes.get(m.id) for m in mixes))
        node = getattr(self, "node", None)
        if node is not None:
            node.refresh()


# ------------------------------------------------------------------------ mixes
MIX_EYEBROWS = {MONITOR: "FOR YOU", STREAM: "FOR YOUR AUDIENCE", RECORDING: "FOR RECORDING"}


class MixStrip(QFrame):
    """A mix's master card: its device, a fader with a meter, the level, Mute, Limiter and one action. Vertical in the Columns
    layout, with sliders along it in the Rows layout."""

    def __init__(self, mix: Mix, engine: Engine, on_remove=None, on_add_recording=None, rows: bool = False) -> None:
        super().__init__()
        self.setObjectName("mix")
        self.rows = rows
        self.original = _is_original(rows)
        self.ring = None
        if not rows:
            self.setFixedWidth(ORIGINAL_MIX_WIDTH if self.original else MIX_WIDTH)
        self.mix, self.engine = mix, engine
        if self.original:
            self._build_original(mix, on_remove)
            return

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16 if not rows else 8)
        if _is_nexus(rows):  # a ring with the mix's letter in it, in the mix's colour
            mixc = themes.mix_colors(themes._current)
            color = mixc.get({MONITOR: "listen", STREAM: "broadcast"}.get(mix.id, ""), themes.color("accent"))
            if mix.id == RECORDING:
                color = themes.color("mute")
            self.ring = NexusRing(color, lambda ratio, mix=mix, color=color: icons.app_pixmap("", mix.label, 36, ratio, mix.id))
            layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)

        head = QHBoxLayout()
        head.setSpacing(8)
        names = QVBoxLayout()
        names.setSpacing(4)
        eyebrow = _label(MIX_EYEBROWS.get(mix.id, "MIX"), "tag", center=False)
        eyebrow.setProperty("mix", mix.id)
        eyebrow.setProperty("narrow", True)  # 11 px, no letter spacing: FOR YOUR AUDIENCE must fit the card even in a wider fallback font
        names.addWidget(eyebrow)
        self.setProperty("mix", mix.id)
        title = QLabel(mix.label)
        title.setObjectName("title")
        names.addWidget(title)
        head.addLayout(names, 1)
        self.readout = ReadoutEdit(None)
        self.readout.setProperty("big", True)
        self.readout.setAccessibleName(f"{mix.label} level in decibels")
        self.readout.setToolTip("Scroll over the number to change the level (hold Shift for fine steps), or click and type a level in dB (for example -6) and press Enter")
        self.readout.wheel_steps = True
        self.readout.wheeled.connect(self._wheel_gain)
        self.readout.entered.connect(self._typed_gain)
        if on_remove is not None:  # the optional third mix can be taken away again from its own card
            menu_button = _icon_button("more", "Options for this mix", 32, compact=True)
            menu_button.setObjectName("plain")
            menu = QMenu(menu_button)
            menu.addAction("Remove the Recording mix…", on_remove)
            menu_button.setMenu(menu)
            self.menu_button = menu_button
            head.addWidget(menu_button, 0, Qt.AlignmentFlag.AlignTop)
        else:
            self.menu_button = None
        if rows:
            self.readout.setFixedWidth(96)
            self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            head.addWidget(self.readout)
        layout.addLayout(head)

        self.combo: Optional[DeviceCombo] = None
        self.device_button: Optional[QPushButton] = None
        if mix.kind == MONITOR:
            self.combo = DeviceCombo("Output: ")
            self.combo.setToolTip("Where you hear the mix")
            self.combo.setAccessibleName("Listen output device")
            self.combo.activated.connect(self._on_device)
            layout.addWidget(self.combo)
        else:
            self.device_button = QPushButton(f"Sends to: {mix.source_description}")
            self.device_button.setObjectName("devicebutton")
            self.device_button.setFixedHeight(40)
            self.device_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.device_button.setToolTip(f"The device your streaming or recording app should pick: “{mix.source_description}”. "
                                          "Click to copy the name.")
            self.device_button.clicked.connect(self._copy_device_name)
            layout.addWidget(self.device_button)

        self.fader = Fader(horizontal=rows, thumb=(32, 24) if rows else (32, 16))
        self.fader.set_fill(themes.color("accent"))
        self.fader.setAccessibleName(f"{mix.label} level")
        self.fader.gainChanged.connect(self._on_gain)
        self.meter = LevelMeter(horizontal=rows, thickness=8 if rows else 16)
        self.meter.setAccessibleName(f"{mix.label} meter")
        if rows:
            layout.addStretch(1)
            layout.addWidget(self.meter)
            layout.addWidget(self.fader)
        else:
            row = QHBoxLayout()
            row.setSpacing(40)
            row.addStretch(1)
            row.addWidget(self.fader)
            row.addWidget(self.meter)
            row.addStretch(1)
            layout.addLayout(row, 1)
            layout.addWidget(self.readout)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.mute = QPushButton()
        self.mute.setObjectName("mute")
        self.mute.setCheckable(True)
        self.mute.setFixedSize(64, 40)
        self.mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute.setAccessibleName(f"Mute {mix.label}")
        self.limiter = QPushButton("Limiter on")
        self.limiter.setObjectName("limiter")
        self.limiter.setCheckable(True)
        self.limiter.setFixedHeight(40)
        self.limiter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.limiter.setToolTip("Limiter: stops peaks from clipping")
        self.mute.toggled.connect(lambda on: self.engine.set_master_mute(self.mix.id, on))
        self.mute.toggled.connect(lambda _on: self._show_toggles())
        self.limiter.toggled.connect(lambda on: self.engine.set_limiter(self.mix.id, on))
        self.limiter.toggled.connect(lambda _on: self._show_toggles())
        buttons.addWidget(self.mute)
        buttons.addWidget(self.limiter, 1)
        layout.addLayout(buttons)

        # one action at the foot of the card: Listen checks the Broadcast, Broadcast offers the optional third mix
        self.hear: Optional[QPushButton] = None
        self.add_button: Optional[QPushButton] = None
        if mix.kind == MONITOR:
            self.hear = QPushButton("Hear Broadcast")
            self.hear.setObjectName("quiet")
            self.hear.setCheckable(True)
            self.hear.setFixedHeight(40)
            self.hear.setCursor(Qt.CursorShape.PointingHandCursor)
            self.hear.setToolTip("Check what your audience hears: your output plays the Broadcast mix instead of the Listen mix. "
                                 "Turn it off to go back. It always starts off.")
            self.hear.toggled.connect(self._on_hear)
            layout.addWidget(self.hear)
        elif mix.id == STREAM and on_add_recording is not None:
            self.add_button = QPushButton("Add a recording mix")
            self.add_button.setObjectName("quiet")
            self.add_button.setFixedHeight(40)
            self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.add_button.setToolTip("Add a third mix, “Recording”: a second virtual microphone with its own faders "
                                       "and mutes, so a recorder can get a different blend from the one your audience hears. "
                                       "Sluice restarts to add it.")
            self.add_button.clicked.connect(on_add_recording)
            layout.addWidget(self.add_button)
        else:
            spacer = QWidget()
            spacer.setFixedHeight(40)
            layout.addWidget(spacer)
        self.sync_from_model()
        self.refresh_theme()

    def _build_original(self, mix: Mix, on_remove) -> None:
        """The master card of 0.9.7: FOR YOU, the name, a hint, the device, the fader and meter, the level, M and LIM. The same parts
        as the Calm card, so everything still works (the optional Recording mix has its own strip beside the cards)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        eyebrow = ElidedLabel(MIX_EYEBROWS.get(mix.id, "MIX"), tip_when_cut=True)  # a wider fallback font ends in "..." instead of being cut
        eyebrow.setObjectName("tag")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eyebrow.setProperty("narrow", True)  # 11 px, no letter spacing
        layout.addWidget(eyebrow)
        title = _label(mix.label, "title")
        self.menu_button = None
        if on_remove is None:
            layout.addWidget(title)
        else:
            head = QHBoxLayout()
            head.setSpacing(0)
            head.addWidget(title, 1)
            self.menu_button = QToolButton()
            self.menu_button.setObjectName("menu")
            self.menu_button.setText("\u22ee")
            self.menu_button.setToolTip("Options for this mix")
            self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(self.menu_button)
            menu.addAction("Remove the Recording mix\u2026", on_remove)
            self.menu_button.setMenu(menu)
            head.addWidget(self.menu_button)
            layout.addLayout(head)
        self.combo = None
        self.device_button = None
        if mix.kind == MONITOR:
            layout.addWidget(_label("You hear this", "hint"))
            self.combo = DeviceCombo("")
            self.combo.setFixedHeight(30)
            self.combo.setToolTip("Where you hear the mix")
            self.combo.setAccessibleName("Listen output device")
            self.combo.activated.connect(self._on_device)
            layout.addWidget(_slot(self.combo, 30))
        else:
            layout.addWidget(_label("Audience hears this" if mix.id == STREAM else "Recorder hears this", "hint"))
            self.device_button = QPushButton(f"Record from\n\u201c{mix.source_description}\u201d")
            self.device_button.setObjectName("hintbutton")
            self.device_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.device_button.setToolTip(f"The device your streaming or recording app should pick: \u201c{mix.source_description}\u201d. "
                                          "Click to copy the name.")
            self.device_button.clicked.connect(self._copy_device_name)
            layout.addWidget(_slot(self.device_button, 30))
        self.fader, self.meter = Fader(), LevelMeter()
        self.fader.setAccessibleName(f"{mix.label} level")
        self.fader.gainChanged.connect(self._on_gain)
        self.meter.setAccessibleName(f"{mix.label} meter")
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addStretch(1)
        row.addWidget(self.fader)
        row.addWidget(self.meter)
        row.addStretch(1)
        layout.addLayout(row, 1)
        self.hear = None
        self.add_button = None
        if mix.kind == MONITOR:
            self.hear = _toggle("Hear Broadcast", "link",
                                "Check what your audience hears: your output plays the Broadcast mix instead of the Listen mix. "
                                "Turn it off to go back. It always starts off.")
            self.hear.toggled.connect(self._on_hear)
            layout.addWidget(self.hear)
        self.readout = ReadoutEdit(None)
        self.readout.setAccessibleName(f"{mix.label} level in decibels")
        self.readout.setToolTip("Scroll over the number to change the level (hold Shift for fine steps), or click and type a level in dB (for example -6) and press Enter")
        self.readout.wheel_steps = True
        self.readout.wheeled.connect(self._wheel_gain)
        self.readout.entered.connect(self._typed_gain)
        layout.addWidget(self.readout)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.mute = _toggle("M", "mute")
        self.limiter = _toggle("LIM", "limiter", "Limiter: stops peaks from clipping")
        self.mute.setAccessibleName(f"Mute {mix.label}")
        self.mute.toggled.connect(lambda on: self.engine.set_master_mute(self.mix.id, on))
        self.mute.toggled.connect(lambda _on: self._show_toggles())
        self.limiter.toggled.connect(lambda on: self.engine.set_limiter(self.mix.id, on))
        buttons.addWidget(self.mute)
        buttons.addWidget(self.limiter)
        layout.addLayout(buttons)
        self.sync_from_model()
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self.fader.set_fill(themes.color("accent"))
        if self.menu_button is not None and not self.original:
            self.menu_button.setIcon(icons.icon("more", themes.color("text_dim"), 20))
        self._show_toggles()

    def _show_toggles(self) -> None:
        muted = self.mute.isChecked()
        if self.original:
            self.mute.setToolTip(f"Muted: nobody hears {MIX_MUTE_TIPS.get(self.mix.id, 'this mix')}. Click to unmute." if muted
                                 else "Mute this whole mix")
            return
        self.mute.setIcon(icons.icon("speaker_off" if muted else "speaker", themes.color("mute_fg" if muted else "text"), 20))
        self.mute.setIconSize(QSize(20, 20))
        what = MIX_MUTE_TIPS.get(self.mix.id, f"the {self.mix.label} mix")
        self.mute.setToolTip(f"Muted: nobody hears {what}. Click to unmute." if muted else f"Mute {what}")
        on = self.limiter.isChecked()
        self.limiter.setText("Limiter on" if on else "Limiter off")

    def sync_from_model(self) -> None:
        for widget in (self.fader, self.mute, self.limiter):
            widget.blockSignals(True)
        self.fader.setGain(round(self.mix.gain_db * 10))
        self.mute.setChecked(self.mix.mute)
        self.limiter.setChecked(self.mix.limiter)
        if self.hear is not None:
            self.hear.blockSignals(True)
            self.hear.setChecked(self.engine.hear_broadcast)
            self.hear.blockSignals(False)
        for widget in (self.fader, self.mute, self.limiter):
            widget.blockSignals(False)
        self.readout.setText(format_db(self.mix.gain_db))
        self._show_toggles()
        node = getattr(self, "node", None)
        if node is not None:
            node.refresh()

    def populate_devices(self) -> None:
        if self.combo:
            default = self.engine.default_sink
            description = next((d.description for d in self.engine.sinks if d.name == default), None) if default else None
            self.combo.populate(self.engine.sinks, self.mix.device, description)

    def _copy_device_name(self) -> None:
        QGuiApplication.clipboard().setText(self.mix.source_description)
        window = self.window()
        if hasattr(window, "say"):
            window.say(f"Copied “{self.mix.source_description}”. Choose it as the microphone in your streaming or recording app.")

    def _on_hear(self, on: bool) -> None:
        self.engine.set_hear_broadcast(on)
        self.window().say("Your output now plays the Broadcast mix: this is what your audience hears." if on
                          else "Your output is back on the Listen mix.")

    def _typed_gain(self, number) -> None:
        if number is not None and number == number:
            self.engine.set_master(self.mix.id, max(MIN_DB, min(MAX_DB, number)))
        self.sync_from_model()

    def _wheel_gain(self, notches: float) -> None:
        self.fader.setGain(max(int(MIN_DB * 10), min(int(MAX_DB * 10), self.fader.gain() + int(round(notches * 10)))))

    def _on_gain(self, value: int) -> None:
        db = value / 10.0
        self.readout.setText(format_db(db))
        self.engine.set_master(self.mix.id, db)

    def _on_device(self, _index: int) -> None:
        self.engine.set_mix_device(self.mix.id, self.combo.selected_device())


# ------------------------------------------------------------------- playing now
class AppsBar(QPushButton):
    """"Playing now · 3": a button that lists the apps making sound and lets you choose the channel each one plays into."""

    def __init__(self, engine: Engine, window: "MainWindow") -> None:
        super().__init__()
        self.engine, self.window = engine, window
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Which apps are playing and which channel each one is on")
        self.menu = QMenu(self)
        self.menu.aboutToShow.connect(self._fill)
        self.setMenu(self.menu)
        self.refresh()

    def _streams(self) -> list:
        seen, found = set(), []
        for stream in self.engine.streams:
            if stream.key not in seen:
                seen.add(stream.key)
                found.append(stream)
        return found

    def refresh(self) -> None:
        count = len(self._streams())
        self.setText(f"Playing now · {count}" if count else "Playing now")

    def _fill(self) -> None:
        menu = self.menu
        menu.clear()
        streams = self._streams()
        if not streams:
            menu.addAction("No app is playing sound. Start something and it shows up here.").setEnabled(False)
        for stream in streams:
            owner = self.engine.channel_for_stream(stream)
            sub = menu.addMenu(f"{stream.name}  ›  {owner.label}" if owner else f"{stream.name}  ›  plays directly")
            sub.setIcon(QIcon(icons.app_pixmap(self.engine.app_icon(stream.assign_key), stream.name, 20, self.devicePixelRatioF(), stream.assign_key)))
            for channel in self.engine.mixer.channels:
                action = sub.addAction(channel.label, partial(self._assign, stream.assign_key, channel.id))
                action.setCheckable(True)
                action.setChecked(owner is not None and owner.id == channel.id)
            sub.addSeparator()
            sub.addAction("Play directly (not in the mixer)", partial(self._assign, stream.assign_key, None))

    def _assign(self, key: str, channel_id: Optional[str]) -> None:
        self.engine.assign_app(key, channel_id)
        self.window.refresh_sources()
        if channel_id is None:
            self.window.say(f"{self.engine.app_label(key)} is no longer in the mixer: it plays straight to your normal output.")


class NexusNode(QFrame):
    """A channel or a mix in the Free layout: its ring, its name and its levels. Drag it anywhere; click it (or press Enter) to open its
    full card beside it; click empty space or press Escape to close the card. Light: one small widget per channel; the card it opens is
    the same card the other layouts show, and is not drawn while it is closed."""

    WIDTH, HEIGHT = 150, 150

    def __init__(self, canvas: "FreeCanvas", key: str, title: str, color: str, picture, card: QWidget, strip) -> None:
        super().__init__()
        self.setObjectName("nexusnode")
        self.canvas, self.key, self.card, self.strip = canvas, key, card, strip
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{title}: press Enter to open its controls")
        self.ring = NexusRing(color, picture)
        self.name = QLabel(title)
        self.name.setObjectName("name")
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chips = QLabel("")
        self.chips.setObjectName("nodechips")
        self.chips.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chips.setTextFormat(Qt.TextFormat.RichText)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.name)
        layout.addWidget(self.chips)
        self._press = None
        self._dragging = False
        self.is_open = False
        self.refresh()

    def set_open(self, on: bool) -> None:
        self.is_open = on
        self.setProperty("open", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def refresh(self) -> None:
        """The level of each mix as a small chip, red and struck through when that mix is muted; the ring shows linked and muted."""
        colors = {MONITOR: themes.mix_colors(themes._current).get("listen", "#22e5ff"),
                  STREAM: themes.mix_colors(themes._current).get("broadcast", "#ffb020"), RECORDING: themes.color("mute")}
        strip = self.strip
        if hasattr(strip, "channel"):
            channel, mixes = strip.channel, strip.engine.mixer.mixes
            parts = []
            for mix in mixes:
                letter = MIX_TAGS.get(mix.id, mix.label.upper())[0]
                tint = colors.get(mix.id, themes.color("text2"))
                if channel.mutes.get(mix.id):
                    parts.append(f'<span style="color:{tint}">{letter}</span> <span style="color:{themes.color("mute_fg")}"><s>off</s></span>')
                else:
                    parts.append(f'<span style="color:{tint}">{letter}</span> {format_db(channel.levels.get(mix.id, 0.0)).replace(" dB", "")}')
            self.chips.setText("&nbsp;&nbsp;".join(parts))
            self.ring.set_state(channel.linked, bool(mixes) and all(channel.mutes.get(m.id) for m in mixes))
        else:
            mix = strip.mix
            state = f'<span style="color:{themes.color("mute_fg")}"><s>muted</s></span>' if mix.mute else format_db(mix.gain_db)
            self.chips.setText(state + ("&nbsp;&nbsp;LIM" if mix.limiter else ""))
            self.ring.set_state(False, mix.mute)

    # -- drag and click
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = (event.globalPosition().toPoint(), self.pos())
            self._dragging = False
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press is None:
            return
        start, origin = self._press
        delta = event.globalPosition().toPoint() - start
        if not self._dragging and delta.manhattanLength() < 5:
            return
        self._dragging = True
        self.move(self.canvas.clamped(origin + delta, self))
        if self.is_open:
            self.canvas.place_card(self)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            if self._dragging:
                self.canvas.remember(self)
            else:
                self.canvas.toggle(self)
            self._press = None
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.canvas.toggle(self)
        elif event.key() == Qt.Key.Key_Escape:
            self.canvas.close_card()
        else:
            super().keyPressEvent(event)


class FreeCanvas(QWidget):
    """The Free layout: nodes you place anywhere, remembered between runs. The cards live here too, hidden until a node opens one."""

    COLUMNS, STEP_X, STEP_Y, TOP, MIX_X = 4, 170, 176, 64, 760

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.setObjectName("freecanvas")
        self.window_ = window
        self.nodes: dict = {}
        self.open_node: Optional[NexusNode] = None
        self.setMinimumSize(640, 440)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.add_button = QPushButton("+  Add channel", self)
        self.add_button.setObjectName("addchip")
        self.add_button.setFixedSize(150, 36)
        self.add_button.move(24, 12)
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setToolTip("Add a channel for another app or group of apps")
        self.add_button.clicked.connect(window.add_channel)
        self.tidy_button = QPushButton("Tidy up", self)
        self.tidy_button.setObjectName("quiet")
        self.tidy_button.setFixedHeight(36)
        self.tidy_button.move(186, 12)
        self.tidy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tidy_button.setToolTip("Put every node back in its grid place")
        self.tidy_button.clicked.connect(self.tidy)

    def default_position(self, index: int, mix: bool) -> QPoint:
        if mix:
            return QPoint(self.MIX_X, self.TOP + index * self.STEP_Y)
        return QPoint(24 + (index % self.COLUMNS) * self.STEP_X, self.TOP + (index // self.COLUMNS) * self.STEP_Y)

    def add_node(self, node: NexusNode, index: int, mix: bool) -> None:
        node.setParent(self)
        saved = self.window_.engine.mixer.free_positions.get(node.key)
        spot = QPoint(*saved) if saved else self.default_position(index, mix)
        spot = QPoint(max(0, min(spot.x(), 4000)), max(0, min(spot.y(), 4000)))
        # The canvas grows to hold every node (and scrolls), so many channels never pile up at the bottom edge.
        self.setMinimumSize(max(self.minimumWidth(), spot.x() + node.width() + 24), max(self.minimumHeight(), spot.y() + node.height() + 24))
        node.move(spot)
        node.card.setParent(self)
        node.card.hide()
        self.nodes[node.key] = node
        node.show()

    def clamped(self, point: QPoint, node: QWidget) -> QPoint:
        return QPoint(max(0, min(point.x(), max(0, self.width() - node.width()))), max(0, min(point.y(), max(0, self.height() - node.height()))))

    def remember(self, node: NexusNode) -> None:
        self.window_.engine.mixer.free_positions[node.key] = [node.x(), node.y()]

    def tidy(self) -> None:
        self.window_.engine.mixer.free_positions.clear()
        self.close_card()
        channels = mixes = 0
        for node in self.nodes.values():
            is_mix = not hasattr(node.strip, "channel")
            node.move(self.default_position(mixes if is_mix else channels, is_mix))
            mixes, channels = (mixes + 1, channels) if is_mix else (mixes, channels + 1)
        self.window_.say("Every node is back in its place.")

    def place_card(self, node: NexusNode) -> None:
        card = node.card
        card.resize(card.width(), card.sizeHint().height())
        right = node.x() + node.width() + 8
        x = right if right + card.width() <= self.width() else max(0, node.x() - 8 - card.width())
        y = max(0, min(node.y(), max(0, self.height() - card.height())))
        card.move(x, y)
        card.raise_()

    def toggle(self, node: NexusNode) -> None:
        was = self.open_node is node
        self.close_card()
        if not was:
            self.open_node = node
            node.set_open(True)
            node.card.show()
            self.place_card(node)

    def close_card(self) -> None:
        node = self.open_node
        if node is not None:
            node.card.hide()
            node.set_open(False)
            self.open_node = None

    def clear_channels(self) -> None:
        self.close_card()
        for key in [k for k, n in self.nodes.items() if hasattr(n.strip, "channel")]:
            node = self.nodes.pop(key)
            node.card.hide()
            node.card.deleteLater()
            node.hide()
            node.deleteLater()

    def mousePressEvent(self, event) -> None:
        self.close_card()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_card()
        else:
            super().keyPressEvent(event)


class OriginalAppsBar(QFrame):
    """The Original look's "Playing now" strip: a chip for each app making sound, on the channel it plays into, as in 0.9.7. Click a
    chip to choose the channel. It does what the Calm look's "Playing now" button does."""

    def __init__(self, engine: Engine, window: "MainWindow") -> None:
        super().__init__()
        self.setObjectName("apps")
        self.engine, self.window = engine, window
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(10, 6, 10, 6)
        self.row.setSpacing(6)
        self.refresh()

    def refresh(self) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.row.addWidget(_label("Playing now:", "tag", center=False))
        seen = set()
        for stream in self.engine.streams:
            if stream.key in seen:
                continue
            seen.add(stream.key)
            self.row.addWidget(self._chip(stream))
        if not seen:
            nobody = ElidedLabel("No app is playing sound. Start something and it shows up here.")
            nobody.setObjectName("hint")
            self.row.addWidget(nobody, 1)
        self.row.addStretch(1)

    def _chip(self, stream) -> QPushButton:
        owner = self.engine.channel_for_stream(stream)
        button = QPushButton(f"{stream.name}  \u203a  {owner.label}" if owner else stream.name)
        button.setObjectName("appassigned" if owner else "app")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("Click to choose which channel this app plays into")
        menu = QMenu(button)
        for channel in self.engine.mixer.channels:
            action = menu.addAction(channel.label, partial(self._assign, stream.assign_key, channel.id))
            action.setCheckable(True)
            action.setChecked(owner is not None and owner.id == channel.id)
        menu.addSeparator()
        menu.addAction("Play directly (not in the mixer)", partial(self._assign, stream.assign_key, None))
        button.setMenu(menu)
        return button

    def _assign(self, key: str, channel_id: Optional[str]) -> None:
        self.engine.assign_app(key, channel_id)
        self.window.refresh_sources()
        if channel_id is None:
            self.window.say(f"{self.engine.app_label(key)} is no longer in the mixer: it plays straight to your normal output.")


class FirstRun(QFrame):
    """Shown until the first app is on a channel: three steps and a note about the demo. Nothing is routed until you add something."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.setObjectName("firstrun")
        self.window = window
        self.setFixedWidth(FIRST_RUN_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)
        head = QVBoxLayout()
        head.setSpacing(8)
        title = QLabel("Let's set up your mixer")
        title.setObjectName("title")
        head.addWidget(title)
        intro = QLabel("Three steps. You can change everything later, and nothing is routed until you add something.")
        intro.setWordWrap(True)
        intro.setObjectName("intro")
        head.addWidget(intro)
        layout.addLayout(head)
        self.buttons = []
        steps = (
            ("1", "Choose your microphone", "Pick the one you speak into and it goes on the Mic channel.", "Choose microphone", True,
             window.first_run_microphone),
            ("2", "Add your apps", "Games, Discord, your browser and music players each get a channel, so you can balance them "
             "separately.", "Add apps", False, window.first_run_apps),
            ("3", "Pick Sluice in your streaming app", "In OBS or Discord, choose “Sluice (Broadcast)” as the microphone. "
             "That is the processed sound.", "Show me how", False, window.first_run_streaming),
            ("4", "Make it look like yours", "Three looks and a choice of colours. Compare them side by side now, or change them later "
             "under View.", "Compare looks", False, window.compare_looks),
        )
        for number, name, text, button_text, primary, slot in steps:
            row = QHBoxLayout()
            row.setSpacing(16)
            badge = QLabel(number)
            badge.setObjectName("step" if primary else "stepoff")
            badge.setFixedSize(32, 32)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            body = QVBoxLayout()
            body.setSpacing(8)
            heading = QLabel(name)
            heading.setStyleSheet("font-weight: 600;")
            body.addWidget(heading)
            detail = _label(text, "hint", center=False)
            detail.setWordWrap(True)
            body.addWidget(detail)
            button = QPushButton(button_text)
            if primary:
                button.setObjectName("primary")
            button.setFixedHeight(40)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            row.addLayout(body, 1)
            layout.addLayout(row)
            self.buttons.append(button)
        layout.addStretch(1)
        self.demo_link = QLabel("Prefer to look around first? <a href=\"demo\">Try the demo</a>. "
                                "It changes nothing on your computer.")
        self.demo_link.setObjectName("hint")
        self.demo_link.setWordWrap(True)
        self.demo_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.demo_link.linkActivated.connect(lambda _href: window.first_run_demo())
        layout.addWidget(self.demo_link)


class SmoothScrollArea(QScrollArea):
    """A scroll area whose mouse wheel scrolls sideways with a short animation (touchpads scroll directly)."""

    STEP = 110  # pixels per wheel notch

    def __init__(self) -> None:
        super().__init__()
        self._animation = QPropertyAnimation(self.horizontalScrollBar(), b"value", self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def wheelEvent(self, event) -> None:
        bar = self.horizontalScrollBar()
        if bar.maximum() <= 0:
            super().wheelEvent(event)
            return
        pixels = event.pixelDelta()
        if not pixels.isNull():  # touchpad: already smooth, follow the finger exactly
            self._animation.stop()
            bar.setValue(bar.value() - (pixels.x() or pixels.y()))
            event.accept()
            return
        angle = event.angleDelta()
        notches = (angle.x() or angle.y()) / 120.0
        if notches == 0:
            event.ignore()
            return
        running = self._animation.state() == QPropertyAnimation.State.Running
        base = self._animation.endValue() if running else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), int(base - notches * self.STEP)))
        self._animation.stop()
        self._animation.setStartValue(bar.value())
        self._animation.setEndValue(target)
        self._animation.start()
        event.accept()


class MainWindow(MenusMixin, ThemesMixin, TrayMixin, UpdatingMixin, QMainWindow):
    def __init__(self, engine: Engine, config_file: Optional[Path] = None, notice: str = "") -> None:
        super().__init__()
        self.engine = engine
        self.config_file = config_file
        self._closed = False
        self._quitting = False
        # What's new: a start with no settings and no record is a new install (nothing has changed for them), so that
        # is written down now; an older record, or settings without one, means an update, shown once the window is open.
        self._config_existed = config_file is not None and config_file.exists()
        self._reconnecting = False
        self._tray = None
        self._tray_state = "idle"
        self._voice_until = 0.0
        self._whats_new_done = config_file is None  # demo mode: nothing to remember
        self._notes_dialog = None
        if config_file is not None and not self._config_existed and not whatsnew.read_marker(config_file):
            whatsnew.write_marker(config_file, __version__)
        self.controls = None  # set by attach_controls()
        self.setWindowTitle(f"Sluice {__version__}")
        self.apply_theme()  # before anything is built, so every widget (and the meters) starts in the chosen colours
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):  # "Match my system" follows the desktop while Sluice is running
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        self._keep_settings_file = False  # set after "Import settings": quitting must not overwrite what was imported
        self._build_menus()
        self._update_check = updates.check  # replaced in tests
        self._update_bridge = _UpdateBridge()
        self._update_bridge.done.connect(self._show_update_result)
        self._update_bridge.progress.connect(self._update_progress)
        self._update_bridge.staged.connect(self._update_staged)
        self._update_bridge.quiet.connect(self._auto_update_staged)
        self._stage_update = selfupdate.stage  # replaced in tests
        self._update_progress_dialog = None
        self._auto_update_started = False
        QTimer.singleShot(AUTO_UPDATE_DELAY_MS, self._auto_update_check)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # the window starts with nothing highlighted; Tab moves to the first control
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 24, 24, 8)
        outer.setSpacing(24)
        self._outer = outer
        self.top_bar = self._build_top_bar()
        outer.addWidget(self.top_bar)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        outer.addWidget(self.content, 1)
        self.orig_apps_bar = OriginalAppsBar(engine, self)  # the Original look's "Playing now" strip under the cards
        outer.addWidget(self.orig_apps_bar)
        self.apps_bar = AppsBar(engine, self)
        self.apps_bar.setFixedHeight(40)
        self.apps_button_holder.addWidget(self.apps_bar)
        self.strips: list = []
        self.mix_strips: list = []
        self.add_mix_button: Optional[QPushButton] = None
        self.first_run: Optional[FirstRun] = None
        self._plan = None
        self._plan_size = QSize(*DEFAULT_SIZE)
        self._relayouts = 0
        self._plan_ready = False
        self._told = set()  # one-time notes already shown this session
        self.layout_mode, self._dock = "columns", "right"
        self._refresh_plan()
        self._build_content()

        self.status_label = ElidedLabel(notice or "Ready", tip_when_cut=True)
        self.status_label.setObjectName("status")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.status_label, 1)
        self.buffer_offer = QPushButton("")
        self.buffer_offer.setFlat(True)
        self.buffer_offer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.buffer_offer.clicked.connect(self.accept_buffer_offer)
        self.buffer_offer.hide()
        self.statusBar().addPermanentWidget(self.buffer_offer)
        self.raw_mic_button = QPushButton("")
        self.raw_mic_button.setFlat(True)
        self.raw_mic_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.raw_mic_button.setStyleSheet(f"color: {themes.color('warn')};")
        self.raw_mic_button.clicked.connect(self.show_raw_mic)
        self.raw_mic_button.hide()
        self.statusBar().addPermanentWidget(self.raw_mic_button)
        # the Original look keeps what the top bar shows (health, version, demo) in the status bar, as 0.9.7 did
        demo = "Demo" in engine.io.label
        self.orig_perf = QLabel("")
        self.orig_perf.setObjectName("status")
        self.orig_version = QLabel(f"v{__version__}")
        self.orig_version.setObjectName("status")
        self.orig_version.setToolTip("The Sluice version you are running. Please include it in bug reports.")
        self.orig_demo = QLabel("Demo mode (no audio is touched)")
        self.orig_demo.setObjectName("demo")
        self.orig_demo.setVisible(False)
        self._orig_demo_wanted = demo
        for widget in (self.orig_perf, self.orig_version, self.orig_demo):
            self.statusBar().addPermanentWidget(widget)
        self._apply_chrome()
        self.repopulate_devices()
        self._show_layout_choice()
        self.refresh_theme_widgets()
        root.setFocus(Qt.FocusReason.OtherFocusReason)

        self.desktop = DesktopWidgetManager(self)
        self.tracker = efficiency.Tracker()  # how much CPU and memory Sluice itself uses, for the bug report
        self.tracker.engine = engine
        efficiency.activate(self.tracker)
        self.tray_timer = QTimer(self)  # watches the microphone for the tray icon, only while the window is hidden in the tray
        self.tray_timer.timeout.connect(self._tray_tick)
        self._update_tray()  # the tray icon is there from the start if Sluice is set to run in the tray
        self.setMinimumSize(360, 300)  # smaller than the cards need: the compact list takes over below that (see sizing.py)
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(0)
        self._relayout_timer.timeout.connect(self._relayout)
        self.resize(*DEFAULT_SIZE)
        self._apply_step()
        self._plan_ready = True
        report.set_window_source(self._report_info)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._update_meters)
        self.meter_timer.start(33)
        self._meter_slow = 1.0
        self.engine_timer = QTimer(self)
        self.engine_timer.timeout.connect(self._tick_engine)
        self.engine_timer.start(500)
        # Settings save themselves: every few seconds, if (and only if) something changed since the last save.
        self._saved_snapshot: Optional[str] = self._snapshot() if config_file is not None and config_file.exists() else None
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start(AUTOSAVE_MS)
        self.desktop.restore()  # the widgets left on the desktop last time

    # ------------------------------------------------------------------ the top bar and the content
    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedHeight(40)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        self.menu_button = _icon_button("menu", "Menu: file, mixer, view and help", 40)
        self.menu_button.setMenu(self.main_menu)
        row.addWidget(self.menu_button)
        name = QLabel("Sluice")
        name.setObjectName("appname")
        self.app_name = name
        row.addWidget(name)
        version = QLabel(f"v{__version__}")
        version.setObjectName("version")
        version.setToolTip("The Sluice version you are running. Please include it in bug reports.")
        row.addSpacing(-8)
        self.version_label = version
        row.addWidget(version)
        demo = "Demo" in self.engine.io.label
        self.live_chip = QLabel("Demo mode" if demo else "\u25cf  Live")
        self.live_chip.setObjectName("demo" if demo else "livechip")
        self.live_chip.setToolTip(self.engine.io.label)
        row.addWidget(self.live_chip)
        row.addStretch(1)

        self.layout_frame = QFrame()
        self.layout_frame.setObjectName("segmented")
        segments = QHBoxLayout(self.layout_frame)
        segments.setContentsMargins(4, 4, 4, 4)
        segments.setSpacing(4)
        self.layout_buttons = {}
        for key, text, tip in (("columns", "Columns", "A card for each channel, faders standing up"),
                               ("rows", "Rows", "A line for each channel, sliders lying down"),
                               ("free", "Free", "Nodes you place anywhere; click one to open its controls")):
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"{text} layout")
            button.clicked.connect(lambda _c=False, key=key: self.set_layout(key))
            segments.addWidget(button)
            self.layout_buttons[key] = button
        row.addWidget(self.layout_frame)

        self.apps_button_holder = QHBoxLayout()
        self.apps_button_holder.setContentsMargins(0, 0, 0, 0)
        row.addLayout(self.apps_button_holder)

        self.status_chip = QFrame()
        self.status_chip.setObjectName("statuschip")
        self.status_chip.setFixedHeight(40)
        chip = QHBoxLayout(self.status_chip)
        chip.setContentsMargins(16, 0, 16, 0)
        chip.setSpacing(12)
        self.perf_dot = QLabel()
        self.perf_dot.setFixedSize(8, 8)
        self.perf_label = QLabel("")
        self.perf_label.setObjectName("dropouts")
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(16)
        self.rate_label = QLabel("")
        self.rate_label.setObjectName("ratetext")
        dropouts = QHBoxLayout()
        dropouts.setSpacing(8)
        dropouts.addWidget(self.perf_dot)
        dropouts.addWidget(self.perf_label)
        chip.addLayout(dropouts)
        chip.addWidget(divider)
        chip.addWidget(self.rate_label)
        self.status_divider = divider
        self._show_perf()
        row.addWidget(self.status_chip)

        self.settings_button = QPushButton("Settings")
        self.settings_button.setFixedHeight(40)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip("Start at login, audio buffer, controllers, updates and more")
        self.settings_button.setMenu(self.settings_menu)
        row.addWidget(self.settings_button)
        return bar

    def _show_perf(self) -> None:
        """The health chip: dropouts first, the sample rate and the buffer small beside it, the explanation on hover."""
        text = self.engine.dropout_text()
        self.perf_label.setText(text)
        self.rate_label.setText(self.engine.rate_text())
        tip = (self.engine.dropout_tooltip() + "\n\n" + "Sample rate and buffer size: a smaller buffer means less delay, a "
               "larger one means fewer dropouts. Change it in Settings > Audio buffer.")
        for widget in (self.status_chip, self.perf_label, self.rate_label):
            widget.setToolTip(tip)
        total, _ours = self.engine.dropout_counts()
        color = themes.color("live_fg") if total == 0 else themes.color("warn")
        self.perf_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        if hasattr(self, "orig_perf"):
            self.orig_perf.setText(text)
            self.orig_perf.setToolTip(tip)

    def _apply_chrome(self) -> None:
        """Show the window frame of the look in use: the Calm look has the top bar and keeps the menus behind its buttons; the
        Original look has the menu bar across the top, the "Playing now" strip under the cards, and its details in the status bar."""
        original = themes.current_look() == "original"
        self.top_bar.setVisible(not original)
        self.menuBar().setVisible(original)
        self.orig_apps_bar.setVisible(original)
        for widget in (self.orig_perf, self.orig_version):
            widget.setVisible(original)
        self.orig_demo.setVisible(original and self._orig_demo_wanted)
        margins, spacing = ((12, 12, 12, 6), 8) if original else ((24, 24, 24, 8), 24)
        self._outer.setContentsMargins(*margins)
        self._outer.setSpacing(spacing)

    def _restructure_for_look(self) -> None:
        """A different look has different parts, not only different colours: rebuild the cards in it."""
        self._apply_chrome()
        self._tune_meter_rate()
        self._refresh_plan()
        self._apply_step()
        self._build_content()
        self._show_layout_choice()
        self._refresh_apps()
        self._show_perf()

    def _refresh_apps(self) -> None:
        self.apps_bar.refresh()
        self.orig_apps_bar.refresh()

    def _effective_layout(self, mode: str) -> str:
        """The layout actually shown for a saved choice at the window's size: Free belongs to the Nexus look, so any other look shows
        Columns, and a window too small for cards shows the compact list. The saved choice is never changed by any of this."""
        size = self._plan_size
        return sizing.plan_for(size.width(), size.height(), mode, themes.current_look()).mode

    def _refresh_plan(self) -> bool:
        """Work out how the window should be arranged at its size now; True when the cards have to be rebuilt for it."""
        size = self._plan_size
        plan = sizing.plan_for(size.width(), size.height(), self.engine.mixer.layout, themes.current_look(), self._plan)
        changed = self._plan is None or (plan.mode, plan.dock) != (self._plan.mode, self._plan.dock)
        self._plan = plan
        self.layout_mode, self._dock = plan.mode, plan.dock
        return changed

    def _apply_step(self) -> None:
        """Show as much of the top bar as the width allows (the same few controls, in the same places, only fewer of them)."""
        if not hasattr(self, "version_label") or self._plan is None:
            return
        step = self._plan.step
        compact, mini = step in ("compact", "mini"), step == "mini"
        self.version_label.setVisible(not compact)
        self.live_chip.setVisible(not compact)
        self.rate_label.setVisible(not compact)
        self.status_divider.setVisible(not compact)
        self.apps_bar.setVisible(step in ("roomy", "standard"))
        self.app_name.setVisible(not mini)
        self.layout_frame.setVisible(not mini)
        self.settings_button.setText("" if mini else "Settings")
        self.settings_button.setFixedWidth(44) if mini else self.settings_button.setMaximumWidth(16777215)
        self.settings_button.setAccessibleName("Settings")
        self._outer.setContentsMargins(*self._margins_for(step))
        if themes.current_look() == "original":  # its strip and status bar are cut down the same way
            self.orig_apps_bar.setVisible(step != "mini")
            self.orig_version.setVisible(step != "mini")
            self.orig_demo.setVisible(self._orig_demo_wanted and not compact)

    def _margins_for(self, step: str) -> tuple:
        original = themes.current_look() == "original"
        if original:
            return (12, 12, 12, 6)
        return {"roomy": (24, 24, 24, 8), "standard": (24, 24, 24, 8), "compact": (16, 16, 16, 6), "mini": (10, 10, 10, 6)}[step]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._plan_size = event.size()
        if getattr(self, "_plan_ready", False):
            self._relayout_timer.start()

    def _report_info(self) -> dict:
        """What the bug report says about the window: its size, the screen, the arrangement and where the main parts are."""
        screen = self.screen()
        geometry = screen.geometry() if screen is not None else None
        plan = self._plan
        parts = [f"window            {self.width()}x{self.height()}"]

        def where(name: str, widget) -> None:
            if widget is None or not widget.isVisible():
                return
            top = widget.mapTo(self, widget.rect().topLeft())
            parts.append(f"{name:<18}x={top.x()} y={top.y()} {widget.width()}x{widget.height()}")

        where("top bar", getattr(self, "top_bar", None))
        scroll = getattr(self, "channel_scroll", None)
        where("channel area", scroll)
        if scroll is not None and scroll.isVisible():
            vertical, sideways = scroll.verticalScrollBar(), scroll.horizontalScrollBar()
            parts.append(f"{'':<18}content {scroll.widget().width()}x{scroll.widget().height()}; scrolls "
                         f"{vertical.maximum()} px down, {sideways.maximum()} px across")
        for strip in self.strips[:12]:
            where(f"card {strip.channel.id}", strip)
        for strip in self.mix_strips:
            where(f"mix {strip.mix.id}", strip)
        if getattr(self, "mini", None) is not None:
            where("compact list", self.mini)
        return {
            "width": self.width(), "height": self.height(), "fullscreen": self.isFullScreen(),
            "screen": f"{geometry.width()}x{geometry.height()}" if geometry is not None else "unknown",
            "scale": f"{screen.devicePixelRatio():g}" if screen is not None else "?",
            "step": plan.step if plan else "?", "mode": plan.mode if plan else "?", "dock": plan.dock if plan else "?",
            "chosen": self._chosen_layout(), "relayouts": self._relayouts,
            "nexus_colors": bool(self.engine.mixer.nexus_colors), "layout": "\n".join(parts),
        }

    def _relayout(self) -> None:
        """After the window changed size: arrange it for the new size (rebuilding the cards only if the arrangement changed)."""
        was_mini = self.layout_mode == "mini"
        changed = self._refresh_plan()
        self._apply_step()
        if changed:
            if self.layout_mode == "mini" and not was_mini and "mini" not in self._told:
                self._told.add("mini")
                self.say("The window is small, so Sluice shows a compact list. Make the window larger for the full cards.")
            self._relayouts += 1
            self._build_content()
            self._show_layout_choice()
            self.sync_from_model()

    def _build_free(self) -> None:
        """The Free layout (Nexus): the cards exist as in the other layouts, hidden, and a node for each opens one."""
        engine = self.engine
        self.mix_strips = [
            MixStrip(m, engine, self.toggle_recording_mix if m.id == RECORDING else None,
                     self.toggle_recording_mix if m.id == STREAM and not engine.mixer.has_recording_mix else None, rows=False)
            for m in engine.mixer.mixes]
        self.add_mix_button = next((s.add_button for s in self.mix_strips if s.add_button is not None), None)
        for strip in self.mix_strips:
            if strip.combo:
                strip.combo.about_to_show.connect(self._on_popup)
        self.canvas = FreeCanvas(self)
        self.channels_widget = self.canvas
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.canvas)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")  # the floor is the window's colour in every theme
        scroll.viewport().setAutoFillBackground(False)
        self.channel_scroll = scroll
        self.content_layout.addWidget(scroll)
        colors = themes.mix_colors(themes._current)
        for index, strip in enumerate(self.mix_strips):
            mix = strip.mix
            color = {MONITOR: colors["listen"], STREAM: colors["broadcast"]}.get(mix.id, themes.color("mute"))
            node = NexusNode(self.canvas, mix.id, mix.label, color,
                             lambda ratio, mix=mix: icons.app_pixmap("", mix.label, 36, ratio, mix.id), strip, strip)
            strip.node = node
            if strip.ring is not None:
                strip.ring.hide()
            self.canvas.add_node(node, index, True)
        self.channels_row = None
        self.rebuild_channels()
        self.repopulate_devices()
        self.refresh_theme_widgets()

    def _rebuild_free(self) -> None:
        self.canvas.clear_channels()
        self.first_run = None
        self.strips = [ChannelStrip(c, self.engine, self, rows=False) for c in self.engine.mixer.channels]
        for index, strip in enumerate(self.strips):
            node = NexusNode(self.canvas, strip.channel.id, strip.channel.label, strip.channel.color, strip._ring_picture, strip, strip)
            strip.node = node
            if strip.ring is not None:
                strip.ring.hide()  # the node beside the card already shows it
            self.canvas.add_node(node, index, False)
            strip.refresh_sources()
        self.refresh_theme_widgets()

    def _build_mini(self) -> None:
        """The compact list, for a window too small for the cards. The cards still exist, hidden, as in the Free layout, so the
        tray, the controllers and the bug report see the same window; the list drives the same engine calls."""
        engine = self.engine
        self.mix_strips = [
            MixStrip(m, engine, self.toggle_recording_mix if m.id == RECORDING else None,
                     self.toggle_recording_mix if m.id == STREAM and not engine.mixer.has_recording_mix else None, rows=False)
            for m in engine.mixer.mixes]
        self.add_mix_button = next((s.add_button for s in self.mix_strips if s.add_button is not None), None)
        for strip in self.mix_strips:
            if strip.combo:
                strip.combo.about_to_show.connect(self._on_popup)
        self.channels_row = None
        self.mini = MiniStrip(self)
        self.channels_widget = self.mini
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.mini)
        self.channel_scroll = scroll
        self.content_layout.addWidget(scroll)
        self.rebuild_channels()
        self.repopulate_devices()
        self.refresh_theme_widgets()

    def _rebuild_mini(self) -> None:
        for strip in getattr(self, "_mini_hidden", []):
            strip.deleteLater()
        self.first_run = None
        self.strips = [ChannelStrip(c, self.engine, self, rows=False) for c in self.engine.mixer.channels]
        self._mini_hidden = list(self.strips) + list(self.mix_strips)
        for strip in self.strips:
            strip.refresh_sources()
        self.mini.rebuild()
        self.refresh_theme_widgets()

    def _build_content(self) -> None:
        """The channels and the two master cards, in the chosen layout. Rebuilt when the layout is switched."""
        for strip in getattr(self, "_mini_hidden", []):
            strip.deleteLater()  # the hidden cards behind the compact list, from before
        self._mini_hidden = []
        self.mini = None
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if self.layout_mode == "free":
            self._build_free()
            return
        if self.layout_mode == "mini":
            self._build_mini()
            return
        rows = self.layout_mode == "rows"
        original = _is_original(rows)
        bottom = self._dock == "bottom" and not original
        self.mix_strips = [
            MixStrip(m, self.engine, self.toggle_recording_mix if m.id == RECORDING else None,
                     self.toggle_recording_mix if m.id == STREAM and not self.engine.mixer.has_recording_mix and not original else None,
                     rows=rows or bottom)
            for m in self.engine.mixer.mixes]
        self.add_mix_button = next((s.add_button for s in self.mix_strips if s.add_button is not None), None)
        if original and not self.engine.mixer.has_recording_mix:  # 0.9.7: the third mix is one click away in a strip of its own
            self.add_mix_button = QPushButton("+\nAdd a\nRecording\nmix")
            self.add_mix_button.setObjectName("addmix")
            self.add_mix_button.setFixedWidth(ADD_MIX_WIDTH)
            self.add_mix_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            self.add_mix_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.add_mix_button.setToolTip("Add a third mix, \u201cRecording\u201d: a second virtual microphone with its own faders "
                                           "and mutes, so a recorder can get a different blend from the one your audience hears. "
                                           "Sluice restarts to add it.")
            self.add_mix_button.clicked.connect(self.toggle_recording_mix)
        for strip in self.mix_strips:
            if strip.combo:
                strip.combo.about_to_show.connect(self._on_popup)
        self.channels_widget = QWidget()
        self.channels_widget.setObjectName("channels")
        page = QHBoxLayout()
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(8 if original else 24)
        if rows:
            self.channels_row = QVBoxLayout(self.channels_widget)
            self.channels_row.setContentsMargins(0, 0, 8, 0)
            self.channels_row.setSpacing(16)
            scroll = QScrollArea()
        else:
            self.channels_row = FlowLayout(self.channels_widget, 8 if original else 16)  # the cards wrap onto new lines as the window narrows
            self.channels_row.setContentsMargins(0, 0, 8, 8)
            scroll = QScrollArea()
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.channels_widget)
        self.channel_scroll = scroll
        if rows:
            left = QVBoxLayout()
            left.setSpacing(16)
            left.addWidget(self._row_headings())
            left.addWidget(scroll, 1)
            page.addLayout(left, 1)
            if bottom:
                masters = QHBoxLayout()
                masters.setSpacing(16)
                for strip in self.mix_strips:
                    masters.addWidget(strip, 1)
                masters.setContentsMargins(0, 0, 0, 0)
            else:
                masters = QVBoxLayout()
                masters.setSpacing(16)
                for strip in self.mix_strips:
                    masters.addWidget(strip, 1)
                holder = QWidget()
                holder.setFixedWidth(304)
                holder.setLayout(masters)
                masters.setContentsMargins(0, 0, 0, 0)
                page.addWidget(holder)
        elif bottom:
            page.addWidget(scroll, 1)
            masters = QHBoxLayout()
            masters.setSpacing(16)
            for strip in self.mix_strips:
                masters.addWidget(strip, 1)
            masters.setContentsMargins(0, 0, 0, 0)
        else:
            page.addWidget(scroll, 1)
            if original:
                divider = QFrame()
                divider.setObjectName("divider")
                page.addWidget(divider)
            masters = QHBoxLayout()
            masters.setSpacing(8 if original else 16)
            for strip in self.mix_strips:
                masters.addWidget(strip)
            if original and self.add_mix_button is not None:
                masters.addWidget(self.add_mix_button)
            holder = QWidget()
            holder.setLayout(masters)
            masters.setContentsMargins(0, 0, 0, 16)
            page.addWidget(holder)
        if bottom:  # narrow: Listen and Broadcast in a bar under the channels, everything still in view
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(12)
            column.addLayout(page, 1)
            bar = QWidget()
            bar.setObjectName("masterbar")
            bar.setLayout(masters)
            column.addWidget(bar)
            page = column
        wrapper = QWidget()
        wrapper.setLayout(page)
        self.content_layout.addWidget(wrapper)
        self.rebuild_channels()
        self.repopulate_devices()
        self.refresh_theme_widgets()

    def _row_headings(self) -> QWidget:
        """The Rows layout's column headings: CHANNEL, LISTEN · you hear, BROADCAST · audience hears."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(24, 0, 32, 0)
        row.setSpacing(16)
        first = _label("CHANNEL", "tag", center=False)
        first.setFixedWidth(8 + ROW_NAME_WIDTH + 32 + 32 + 16 + 16 + ROW_TOOLS_WIDTH - 24)
        row.addWidget(first)
        for mix in self.engine.mixer.mixes:
            heading = MixHeading(mix.id, f"{MIX_TAGS.get(mix.id, mix.label.upper())} \u00b7 {MIX_HEADINGS.get(mix.id, mix.label.lower())}")
            heading.setMinimumWidth(ROW_CELL_MIN)
            row.addWidget(heading, 1)
        return box

    def refresh_theme_widgets(self) -> None:
        """Tell every widget that paints itself or sets icons that the colours changed."""
        for widget in self.findChildren(QWidget):
            refresh = getattr(widget, "refresh_theme", None)
            if refresh is not None:
                refresh()
        if hasattr(self, "menu_button"):
            self.menu_button.setIcon(icons.icon("menu", themes.color("text"), 18))
            self.settings_button.setIcon(icons.icon("gear", themes.color("text"), 18))
            self._show_perf()

    def set_layout(self, mode: str) -> None:
        if mode not in LAYOUTS:
            return
        self.engine.mixer.layout = mode
        if self._refresh_plan():
            self._apply_step()
            self._build_content()
        self._show_layout_choice()

    def _chosen_layout(self) -> str:
        """The layout chosen in the settings as it applies to the look in use (the compact list does not change the choice)."""
        mode = self.engine.mixer.layout
        if mode == "free" and not themes.has_free(themes.current_look()):
            return "columns"
        return mode if mode in LAYOUTS else "columns"

    def _show_layout_choice(self) -> None:
        chosen = self._chosen_layout()
        for key, button in self.layout_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == chosen)
            button.blockSignals(False)
        for key, action in self.layout_actions.items():
            action.setChecked(key == chosen)
        nexus = themes.has_free(themes.current_look())  # Free belongs to Nexus and Tile
        if "free" in self.layout_buttons:
            self.layout_buttons["free"].setVisible(nexus)
        if "free" in self.layout_actions:
            self.layout_actions["free"].setVisible(nexus)
        if hasattr(self, "nexus_colors_action"):
            self._show_look_items()

    # ------------------------------------------------------------------ first run
    def _needs_first_run(self) -> bool:
        mixer = self.engine.mixer
        return "firstrun" not in mixer.hints_seen and not any(c.apps for c in mixer.channels) and self.config_file is not None

    def _update_first_run(self) -> None:
        wanted = self._needs_first_run()
        if not wanted and self.first_run is not None:
            if any(c.apps for c in self.engine.mixer.channels) and "firstrun" not in self.engine.mixer.hints_seen:
                self.engine.mixer.hints_seen.append("firstrun")  # an app is on a channel: this screen has done its job
            self.first_run.hide()
            self.first_run.deleteLater()
            self.first_run = None
        for strip in self.strips:
            strip.set_empty(wanted and not strip.channel.apps and strip.channel.id != "mic" and not strip.rows
                            and self.layout_mode != "free")
        if wanted and self.first_run is None and self.layout_mode == "columns":
            self.first_run = FirstRun(self)
            self.channels_row.insertWidget(0, self.first_run)

    def first_run_microphone(self) -> None:
        strip = next((s for s in self.strips if s.channel.id == "mic"), None) or (self.strips[0] if self.strips else None)
        if strip is not None:
            strip.add_menu.popup(strip.menu_button.mapToGlobal(strip.menu_button.rect().bottomLeft()))

    def first_run_apps(self) -> None:
        strip = next((s for s in self.strips if s.channel.id != "mic"), None)
        if strip is not None:
            strip._add_installed()

    def first_run_streaming(self) -> None:
        QMessageBox.information(
            self, "Pick Sluice in your streaming app",
            "In OBS, add an Audio Input Capture and choose \u201cSluice (Broadcast)\u201d. In Discord, open Voice & Video and "
            "choose it as the microphone. That is your mic and your apps together, after the effects you set up.\n\n"
            "To check it yourself, press \u201cHear Broadcast\u201d on the Listen card.")

    def first_run_demo(self) -> None:
        QMessageBox.information(
            self, "Try the demo",
            "The demo shows a full mixer with made-up sound and changes nothing on your computer.\n\n"
            "Close Sluice, then start it again with:  sluice --demo")

    # ------------------------------------------------------------------- menus
    # ------------------------------------------------------------------- settings files
    def _snapshot(self) -> str:
        return json.dumps(self.engine.mixer.to_dict(), sort_keys=True)

    def _autosave(self) -> None:
        if self._closed or self.config_file is None or self._keep_settings_file:
            return
        snapshot = self._snapshot()
        if snapshot == self._saved_snapshot:
            return
        try:
            self.engine.save_config(self.config_file, backups=True)
            self._saved_snapshot = self._snapshot()
            log.debug("settings saved automatically")
        except OSError as exc:  # try again next time; do not interrupt someone who is mixing
            log.warning("automatic save failed: %s", exc)

    def save_settings(self) -> None:
        if self.config_file is None:
            self.say("Demo mode: settings are not saved.")
            return
        try:
            self.engine.save_config(self.config_file, backups=True)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self._keep_settings_file = False
        self._saved_snapshot = self._snapshot()
        self.say(f"Settings saved to {self.config_file}.")

    def export_settings_to(self, path) -> None:
        self.engine.save_config(Path(path))
        self.say(f"Settings exported to {logs.short_path(path)}.")

    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", str(Path.home() / "sluice-settings.json"),
                                              "Settings (*.json)")
        if path:
            try:
                self.export_settings_to(path)
            except OSError as exc:
                QMessageBox.warning(self, "Could not export the settings", str(exc))

    def import_settings_from(self, path) -> None:
        """Check a settings file and make it the saved settings. It takes effect the next time Sluice starts."""
        import json
        import shutil

        if self.config_file is None:
            raise ValueError("Demo mode does not use saved settings.")
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"That file could not be read as settings: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("channels"), list) or not data["channels"] \
                or data.get("version") != Mixer.default().to_dict()["version"]:
            raise ValueError("That file does not look like Sluice settings.")
        if self.config_file.exists():
            shutil.copy2(self.config_file, self.config_file.with_name("config.before-import.json"))
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, self.config_file)
        self._keep_settings_file = True
        self.say("Settings imported. Close Sluice and start it again to use them.")

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", str(Path.home()), "Settings (*.json)")
        if not path:
            return
        try:
            self.import_settings_from(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Could not import the settings", str(exc))
            return
        QMessageBox.information(
            self, "Settings imported",
            "The settings are saved. Close Sluice and start it again to use them.\n\n"
            "Until then Sluice keeps what you have now, and it will not overwrite the imported file when you quit. "
            "Your previous settings were kept as config.before-import.json.")

    def _fill_restore_menu(self) -> None:
        self.restore_menu.clear()
        backups = list_backups(self.config_file) if self.config_file is not None else []
        if not backups:
            self.restore_menu.addAction("No earlier versions yet").setEnabled(False)
            return
        for path in backups:
            try:
                when = time.strftime("%b %d, %I:%M %p", time.strptime(path.stem[len("config-"):][:15], "%Y%m%d-%H%M%S"))
                count = len(json.loads(path.read_text()).get("channels", []))
                label = f"{when}  ({count} channels)"
            except (OSError, ValueError):
                label = path.stem
            self.restore_menu.addAction(label, partial(self.restore_backup, path))

    def restore_backup(self, path, confirm: bool = True) -> None:
        if confirm and QMessageBox.question(
                self, "Restore earlier settings",
                "Go back to these settings? Your current ones are kept as config.before-import.json.\n\n"
                "The change takes effect the next time Sluice starts.") != QMessageBox.StandardButton.Yes:
            return
        self._autosave()  # make sure what you have now is on disk first
        try:
            self.import_settings_from(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not restore", str(exc))
            return
        self.say("Earlier settings restored. Close Sluice and start it again to use them.")

    def reset_settings(self) -> None:
        """Put the settings back to how a fresh Sluice starts. The current ones are kept; it takes effect at the next start."""
        import shutil

        if self.config_file is None:
            self.say("Demo mode: there are no saved settings to reset.")
            return
        ask = QMessageBox.question(
            self, "Reset all settings",
            "Put every setting back to how a fresh Sluice starts?\n\nThat means the default channels, levels, effects, theme "
            "and options. Your effect presets and controller assignments are kept.\n\nYour current settings are kept as "
            "config.before-reset.json, and the change takes effect the next time Sluice starts.")
        if ask != QMessageBox.StandardButton.Yes:
            return
        self._autosave()  # what you have now is on disk first, so the copy below is the latest
        try:
            if self.config_file.exists():
                shutil.copy2(self.config_file, self.config_file.with_name("config.before-reset.json"))
            Mixer.default().save(self.config_file)
        except OSError as exc:
            QMessageBox.warning(self, "Could not reset the settings", str(exc))
            return
        self._keep_settings_file = True  # quitting must not write the old settings back over the fresh ones
        self.say("Settings reset. Close Sluice and start it again to use them. Your old settings are in config.before-reset.json.")

    def bring_to_front(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh_file_menu(self) -> None:
        from . import desktop

        self.launcher_action.setChecked(desktop.is_installed())
        self._refresh_background_menu()

    def set_close_action(self, mode: str) -> None:
        self.engine.mixer.close_action = mode
        if CLOSE_HINT not in self.engine.mixer.hints_seen:
            self.engine.mixer.hints_seen.append(CLOSE_HINT)  # they know the choice exists: no need for the first-close question
        self._update_tray()
        if mode == "quit":
            self.say("Closing the window will quit Sluice.")
        elif mode == "tray" and not self.tray_active:
            self.say("No system tray was found on this desktop, so closing the window will minimize it to the taskbar instead. "
                     "Use File > Quit to exit.")
        elif mode == "tray":
            self.say("Closing or minimizing the window will keep Sluice running in the system tray. Click its icon to bring "
                     "the window back; right-click it for Quit.")
        else:
            self.say("Closing the window will keep Sluice running, minimized to the taskbar. Use File > Quit to exit.")

    # ---------------------------------------------------------------- outside control
    def attach_controls(self, controls) -> None:
        self.controls = controls
        action = QAction("&MIDI controllers and Stream Deck\u2026", self.settings_menu)
        action.triggered.connect(lambda _checked=False: controls.show_dialog())
        self.settings_menu.insertAction(self.controllers_separator, action)

    def sync_from_model(self) -> None:
        """Show the model's current values (after something other than the mouse changed them)."""
        for strip in self.strips:
            strip.sync_from_model()
        for strip in self.mix_strips:
            strip.sync_from_model()
        if getattr(self, "mini", None) is not None:
            self.mini.sync_from_model()
        self._show_mic_state()  # a controller or `sluice ctl mic-mute` may have changed it
        self._refresh_tray_icon()
        self._sync_tray_timer()

    # ---------------------------------------------------------------- channels
    def rebuild_channels(self) -> None:
        if self.layout_mode == "free":
            self._rebuild_free()
            self._update_first_run()
            return
        if self.layout_mode == "mini":
            self._rebuild_mini()
            return
        rows = self.layout_mode == "rows"
        while self.channels_row.count():
            item = self.channels_row.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.first_run = None
        self.strips = [ChannelStrip(c, self.engine, self, rows=rows) for c in self.engine.mixer.channels]
        for strip in self.strips:
            if rows:
                strip.setMaximumHeight(104)
            self.channels_row.addWidget(strip, 1 if rows else 0)
        add = QPushButton("+  Add channel")
        add.setObjectName("addchannel")
        if _is_original(rows):  # 0.9.7 had no such button: a channel is added from Mixer > Add channel
            add.hide()
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("Add a channel for another app or group of apps")
        add.clicked.connect(self.add_channel)
        if rows:
            add.setFixedHeight(48)
            self.channels_row.addWidget(add)
            self.channels_row.addStretch(0)
        else:
            add.setFixedSize(160, 56)
            self.channels_row.addWidget(add)
        self.refresh_theme_widgets()
        self._update_first_run()

    def add_channel(self) -> None:
        text, ok = QInputDialog.getText(self, "New channel", "Name (for example Game, Music, Browser):")
        if ok and text.strip():
            self.engine.add_channel(text)
            self.rebuild_channels()

    def remove_channel(self, channel_id: str) -> None:
        self.engine.remove_channel(channel_id)
        self.rebuild_channels()
        self._refresh_apps()

    def refresh_sources(self) -> None:
        for strip in self.strips:
            strip.refresh_sources()
        self._refresh_apps()
        self._update_first_run()

    # ----------------------------------------------------------------- devices
    def repopulate_devices(self) -> None:
        for strip in self.mix_strips:
            strip.populate_devices()

    def _on_popup(self) -> None:
        self.engine.refresh_devices()
        self.repopulate_devices()

    # ------------------------------------------------------------------ timers
    def _update_meters(self) -> None:
        levels = self.engine.sample_levels()
        for strip in self.strips:
            loudest = 0.0
            for mix_id, meter in strip.meters.items():
                level = levels.get(f"ch:{strip.channel.id}:{mix_id}", 0.0)
                meter.push(level)
                loudest = max(loudest, level)
                fader = strip.faders[mix_id]
                if fader._reveal:  # the waveform is only fed while someone is looking at it
                    fader.feed(level)
            if strip.ring is not None:
                strip.ring.push(loudest, self._meter_slow)
            node = getattr(strip, "node", None)
            if node is not None:
                node.ring.push(loudest, self._meter_slow)
        for strip in self.mix_strips:
            level = levels.get(f"mix:{strip.mix.id}", 0.0)
            strip.meter.push(level)
            if strip.fader._reveal:
                strip.fader.feed(level)
            if strip.ring is not None:
                strip.ring.push(level, self._meter_slow)
            node = getattr(strip, "node", None)
            if node is not None:
                node.ring.push(level, self._meter_slow)
        self.tracker.meter_tick()
        self._refresh_tray_icon()

    def _begin_reconnect(self) -> None:
        from . import reconnect

        self._reconnecting = True
        self._reconnect_waited = 0.0
        self.say("The audio server (PipeWire) stopped. Waiting for it to come back: Sluice will then restart itself.")
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(int(reconnect.POLL_SECONDS * 1000))
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._reconnect_timer.start()

    def _try_reconnect(self) -> None:
        from . import reconnect

        self._reconnect_waited += reconnect.POLL_SECONDS
        if reconnect.server_is_back():
            self._reconnect_timer.stop()
            self.shutdown()  # saves the settings first
            reconnect.restart_self()
        elif self._reconnect_waited > reconnect.GIVE_UP_SECONDS:
            self._reconnect_timer.stop()
            self.say("The audio server did not come back. Start the audio server, then restart Sluice.")

    def _tick_engine(self) -> None:
        if self.engine.server_lost and not self._reconnecting and not self._closed:
            self._begin_reconnect()
        logs.heartbeat()
        self.tracker.sample()
        self.tracker.maybe_write()
        changed = self.engine.tick()
        if "devices" in changed:
            self.repopulate_devices()
        if changed:
            self.refresh_sources()
        errors = self.engine.take_errors()
        if errors:
            self.status_label.setText(errors[-1])
        for notice in self.engine.take_notices():
            self.status_label.setText(notice)
        text = self.engine.dropout_text()
        if text != self.perf_label.text():  # the tooltip explains the number, so it only changes when the number does
            self._show_perf()
        self._update_buffer_offer()
        self._update_raw_mic()

    def _update_raw_mic(self) -> None:
        """A warning in the status bar while an app listens to the raw microphone instead of the one with effects."""
        warnings = self.engine.raw_mic
        self.raw_mic_button.setVisible(bool(warnings))
        if warnings:
            app, text = next(iter(warnings.items()))
            more = f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else ""
            self.raw_mic_button.setText(rawmic.short(app) + more)
            self.raw_mic_button.setToolTip(text + "\nClick for details.")

    def show_raw_mic(self) -> None:
        warnings = dict(self.engine.raw_mic)
        if not warnings:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Raw microphone")
        box.setText("\n\n".join(warnings.values()))
        box.setInformativeText("Nothing is wrong with Sluice. If that is what you want, you can stop the reminder.")
        dismiss = box.addButton("Don't remind me about " + ("these apps" if len(warnings) > 1 else next(iter(warnings))),
                                QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is dismiss:
            for app in warnings:
                self.engine.dismiss_raw_mic(app)
            self._update_raw_mic()

    def _update_buffer_offer(self) -> None:
        bigger = self.engine.larger_buffer_offer()
        self.buffer_offer.setVisible(bigger is not None)
        if bigger is not None:
            self.buffer_offer.setText(f"Try a larger buffer ({bigger})")
            self.buffer_offer.setToolTip(f"Dropouts keep coming. This saves {bigger} frames as the audio buffer (now "
                                         f"{self.engine.io.blocksize}); it is used the next time Sluice starts. "
                                         "More room for slow moments, a little more delay.")

    def accept_buffer_offer(self) -> None:
        bigger = self.engine.larger_buffer_offer()
        if bigger is not None:
            self.set_buffer(bigger)
            self._refresh_buffer_menu()
        self._update_buffer_offer()

    # ------------------------------------------------------------------- help
    def say(self, text: str) -> None:
        self.status_label.setText(text)

    def show_about(self) -> None:
        import platform

        from PySide6 import __version__ as pyside_version

        QMessageBox.about(
            self, "About Sluice",
            f"<b>Sluice {__version__}</b><br>An open-source virtual audio mixer for PipeWire.<br><br>"
            f"License: GPL-3.0-or-later<br>Python {platform.python_version()}, PySide6 {pyside_version}<br>"
            f"Log: {logs.short_path(logs.log_path())}<br><br>"
            f'<a href="{PROJECT_URL}">Project page</a> &nbsp;·&nbsp; <a href="{DISCORD_URL}">Join the Discord</a> '
            f'&nbsp;·&nbsp; <a href="{ISSUES_URL}">Report a problem</a>',
        )

    def check_for_updates(self) -> None:
        self.say("Checking for updates...")
        check = self._update_check

        def work() -> None:
            self._update_bridge.done.emit(check(__version__))

        threading.Thread(target=work, name="sluice-update-check", daemon=True).start()

    # -------------------------------------------------------------- what's new
    def show_notes(self, title: str, heading: str, markdown: str, main_label: str = "", main_url: str = "",
                   action=None, action_label: str = "") -> None:
        from .ui_whatsnew import NotesDialog

        self._notes_dialog = NotesDialog(title, heading, markdown, main_label, main_url, self,
                                         action=action, action_label=action_label)
        self._notes_dialog.open()  # does not block: a start-up notice must never hold up the window

    def show_whats_new(self) -> None:
        notes = whatsnew.notes_for(__version__) or "No release notes are included with this build. See the releases page for the list of changes."
        self.show_notes(f"What's new in Sluice {__version__}", f"What's new in Sluice {__version__}", notes)

    def _maybe_show_whats_new(self) -> None:
        """Once after an update, when the window is really on screen (a start minimized at login waits until it is opened)."""
        if self._whats_new_done or self._closed or self.config_file is None:
            return
        if not self.isVisible() or self.isMinimized():
            return
        self._whats_new_done = True
        marker = whatsnew.read_marker(self.config_file)
        text = whatsnew.what_to_show(self._config_existed, marker, __version__)
        whatsnew.write_marker(self.config_file, __version__)
        if text:
            self.show_notes(f"What's new in Sluice {__version__}", f"Sluice was updated to {__version__}. What's new:", text)

    def _show_update_result(self, result) -> None:
        if result.status == "available":
            self.say(f"Version {result.latest} is available (you have {result.current}).")
            problem = selfupdate.offer_problem(selfupdate.install_root(), result)
            notes = result.notes or "No release notes were published for this version."
            if problem:
                notes += f"\n\n---\n\n*Sluice cannot install this by itself: {problem}*"
            self.show_notes(
                "Update available", f"Sluice {result.latest} is available. You are running {result.current}.", notes,
                "Open download page" if result.page else "", result.page,
                action=None if problem else partial(self.start_update, result), action_label="Update now")
        elif result.status == "up_to_date":
            self.say(f"Sluice {result.current} is the latest version.")
            QMessageBox.information(self, "Up to date", f"You are running the latest version ({result.current}).")
        elif result.status == "not_configured":
            self.say(f"Sluice {result.current}. Update checking is not set up yet.")
            QMessageBox.information(
                self, "Check for updates",
                f"You are running Sluice {result.current}.\n\nThis build has no download address to check yet. "
                "Until there is one, new versions arrive as a new zip file.")
        else:
            self.say(f"Could not check for updates: {result.message}")
            QMessageBox.warning(self, "Could not check for updates", result.message or "Unknown error.")

    def save_report_to(self, path) -> None:
        written = report.write_report(Path(path))
        self.status_label.setText(f"Bug report saved to {logs.short_path(written)}. Your user name and computer name are replaced; look it over before sharing it.")

    def save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save bug report", str(Path.home() / report.default_name()), "Text files (*.txt)"
        )
        if path:
            try:
                self.save_report_to(path)
            except Exception as exc:  # a file problem, or something unexpected while building the report
                log.warning("could not save the bug report: %s", exc, exc_info=True)
                QMessageBox.warning(
                    self, "Could not save the report",
                    f"The report could not be saved to:\n{path}\n\n{type(exc).__name__}: {exc}\n\n"
                    "Try another folder, or run  sluice --report  in a terminal. Details are in the log "
                    "(File > Open folder).")

    def mark_glitch(self) -> None:
        self.say(self.engine.mark_glitch())

    def open_log_folder(self) -> None:
        folder = logs.state_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ---------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if report._window_source == self._report_info:
            report.set_window_source(None)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            try:
                hints.colorSchemeChanged.disconnect(self._on_system_scheme_changed)
            except (RuntimeError, TypeError):
                pass
        if self._tray is not None:
            self._tray.hide()  # no ghost icon after Sluice is gone
        self.meter_timer.stop()
        self.tray_timer.stop()
        self.engine_timer.stop()
        self.autosave_timer.stop()
        self.desktop.close_all()  # they stay in the saved list and come back next time
        self.tracker.write()  # so `sluice --report` can show how this session went
        if efficiency.ACTIVE is self.tracker:
            efficiency.activate(None)
        if self.controls is not None:
            self.controls.close()
        self.engine.shutdown(save_to=None if self._keep_settings_file else self.config_file)

    def _should_ask_close_choice(self, saving: bool) -> bool:
        """The first time the window is closed with the default setting (Quit), on a desktop with a system tray, ask once whether to
        quit or keep running in the tray, so nobody loses the mixer by accident or never learns the tray exists."""
        mixer = self.engine.mixer
        return (mixer.close_action == "quit" and CLOSE_HINT not in mixer.hints_seen and not self._quitting and not self._closed
                and not saving and self.config_file is not None and self.isVisible() and self._tray_possible())

    def _ask_close_choice(self) -> bool:
        """Ask what closing should do. True: carry on closing (the setting is now what they chose, or a quit this once); False: stay."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Close Sluice?")
        box.setText("Quit Sluice, or keep it running in the system tray?")
        box.setInformativeText("In the tray the mixer keeps working while the window is out of the way, and you can mute your microphone "
                               "from the tray icon. You can change this any time in Settings > Running in the background.")
        tray = box.addButton("Keep running in the tray", QMessageBox.ButtonRole.AcceptRole)
        quit_button = box.addButton("Quit Sluice", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        remember = QCheckBox("Do not ask again when I choose Quit")
        box.setCheckBox(remember)
        box.setDefaultButton(tray)
        box.exec()
        clicked = box.clickedButton()
        if clicked is tray:
            self.set_close_action("tray")  # remembered: closing now keeps it running in the tray from here on
            return True
        if clicked is quit_button:
            if remember.isChecked():
                self.set_close_action("quit")  # remembered: the question never comes again
            return True
        return False

    def closeEvent(self, event) -> None:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        saving = bool(app is not None and app.isSavingSession())  # True during a logout or shutdown: always let it close
        if self._should_ask_close_choice(saving) and not self._ask_close_choice():
            event.ignore()  # they cancelled: the window stays
            return
        if self.engine.mixer.close_action in ("minimize", "tray") and not self._quitting and not self._closed and not saving:
            event.ignore()
            if self.tray_active:
                self.hide()
                self.say("Sluice is still running in the system tray.")
            else:
                self.showMinimized()
                self.say("Sluice is still running. Click it in the taskbar to bring it back, or use File > Quit.")
            return
        self.shutdown()
        event.accept()

    # Nobody can see the meters while the window is hidden or minimised, so they stop (and cost nothing).
    def _set_meters_running(self, on: bool) -> None:
        if self._closed:
            return
        if on and not self.meter_timer.isActive():
            self.meter_timer.start(self._meter_interval())
        elif not on and self.meter_timer.isActive():
            self.meter_timer.stop()
        self._window_state_changed()

    def _meter_interval(self) -> int:
        """33 ms normally; 66 ms in Nexus while this window is not the one in use (it is still live, for a second screen beside a game)."""
        slow = themes.current_look() == "nexus" and self.isVisible() and not self.isActiveWindow()
        self._meter_slow = 2.0 if slow else 1.0
        return 66 if slow else 33

    def _tune_meter_rate(self) -> None:
        if self.meter_timer.isActive():
            wanted = self._meter_interval()
            if self.meter_timer.interval() != wanted:
                self.meter_timer.setInterval(wanted)

    def showEvent(self, event) -> None:
        self._set_meters_running(not self.isMinimized())
        if not self._whats_new_done:
            QTimer.singleShot(700, self._maybe_show_whats_new)
        super().showEvent(event)

    def _minimize_to_tray(self) -> None:
        if self.tray_active and self.isMinimized() and not self._closed:
            self.hide()
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)  # so showing it again is not minimized

    def hideEvent(self, event) -> None:
        self._set_meters_running(False)
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.ActivationChange and not self._closed:
            self._tune_meter_rate()
        if event.type() == QEvent.Type.WindowStateChange:
            self._set_meters_running(self.isVisible() and not self.isMinimized())
            if self.tray_active and self.isMinimized() and not self._closed:
                QTimer.singleShot(0, self._minimize_to_tray)
        super().changeEvent(event)
