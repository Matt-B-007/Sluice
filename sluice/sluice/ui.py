# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt interface: channels on the left, the two mixes on the right, running apps along the bottom."""
from __future__ import annotations

from functools import partial
import json
import logging
from pathlib import Path
import threading
import time
from typing import Optional

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFontMetrics, QGuiApplication, QIcon, QKeySequence,
                           QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap)
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
    QProgressDialog,
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

from . import rawmic, __version__, logs, report, selfupdate, themes, updates, whatsnew
from . import ui_icons as icons
from .engine import Engine
from .model import BUFFER_CHOICES, MAX_DB, MIN_DB, MONITOR, RECORDING, STREAM, Channel, Mix, Mixer, config_path, linear_to_db, list_backups
from .ui_effects import EffectsDialog
from .ui_widgets import ReadoutEdit

log = logging.getLogger("sluice.ui")
AUTOSAVE_MS = 5000  # how often to look for unsaved changes
AUTO_UPDATE_DELAY_MS = 20000  # the automatic update (if switched on) looks once, this long after start-up
NONE_DATA = "__none__"  # combo item data for "no device" (Qt dislikes None)
SOURCES_HEIGHT = 80  # the list of a channel's devices and apps: always this tall, so every card is the same height
DEFAULT_SIZE = (1456, 800)  # wide enough for five channels beside the two master cards
COLUMN_WIDTH = 80            # one mix's column on a channel card: the fader, its meter, the level and the mute button
CHANNEL_WIDTH = 2 * COLUMN_WIDTH + 32     # a channel card with two mixes (Listen and Broadcast)
CHANNEL_WIDTH_THREE = 3 * COLUMN_WIDTH + 32   # ...and with the optional third one
MIX_WIDTH = 224              # a master card in the Columns layout
FIRST_RUN_WIDTH = 560
ROW_NAME_WIDTH = 176         # the Rows layout: the name and what is on the channel
ROW_TOOLS_WIDTH = 176        # ...the Effects and Link buttons
ROW_CELL_MIN = 280           # ...and the least width of one mix's slider, level and mute button
LAYOUTS = ("columns", "rows")
EMPTY_HINTS = {"mic": "Your microphone goes here.", "browser": "Chrome, Firefox and other browsers.",
               "game": "Games and anything loud.", "chat": "Discord and voice chat.", "music": "Spotify, VLC and players.",
               "system": "Notification sounds and everything else."}
MIX_TAGS = {MONITOR: "LISTEN", STREAM: "BROADCAST", RECORDING: "RECORDING"}
MIX_HEADINGS = {MONITOR: "you hear", STREAM: "audience hears", RECORDING: "recorder hears"}
MIX_NAMES = {MONITOR: "Listen: what you hear", STREAM: "Broadcast: what your audience hears",
             RECORDING: "Recording: what your recorder hears"}
DISCORD_URL = "https://discord.gg/awDvJ5Vj2S"
PROJECT_URL = "https://github.com/Matt-B-007/Sluice"
ISSUES_URL = PROJECT_URL + "/issues"
THEMES_URL = PROJECT_URL + "/tree/main/themes"


def channel_width(mix_count: int) -> int:
    return CHANNEL_WIDTH if mix_count <= 2 else CHANNEL_WIDTH_THREE

STYLE = themes.build_style(themes.DARK)  # the default look; MainWindow.apply_theme() sets the chosen one


def level_fraction(linear: float) -> float:
    """Map a linear amplitude to 0..1 along a -60 dB .. 0 dB meter scale."""
    return max(0.0, min(1.0, (linear_to_db(linear) - MIN_DB) / -MIN_DB))


def format_db(db: float) -> str:
    if db <= MIN_DB:
        return "-inf dB"
    return "0.0 dB" if abs(db) < 0.05 else f"{db:+.1f} dB"


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

    def refresh_theme(self) -> None:
        """Pick up the colours of the theme in use (the track behind the bar, the peak line)."""
        self._well = QColor(themes.color("meter_bg"))
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
            p.fillRect(QRectF(0, 0, width, height), gradient)
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

    def paintEvent(self, _event) -> None:
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

    def set_fill(self, color: str) -> None:
        self.fill_color = color
        self.update()

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
        p.setBrush(QColor(themes.color("track")))
        p.drawRoundedRect(track_rect, track / 2.0, track / 2.0)
        p.setBrush(QColor(self.fill_color))
        p.drawRoundedRect(fill_rect, track / 2.0, track / 2.0)
        radius = min(tw, th) / 2.0
        shadow = QColor(0, 0, 0, 70)
        p.setBrush(shadow)
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
        self.setObjectName("sourcechip")
        self.setFixedHeight(32)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 4, 0)
        row.setSpacing(8)
        self.picture = picture
        if picture is not None:
            row.addWidget(picture)
        self.label = QLabel(elide(text, 88 if picture is not None else 120, self))
        self.label.setObjectName("chiptext")
        self.label.setToolTip(tooltip or text)
        close = QToolButton()
        close.setObjectName("remove")
        close.setText("×")
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
        else:
            self.layout_root.setContentsMargins(16, 16, 16, 16)
            self.layout_root.setSpacing(16)

        self.title = QLabel(channel.label)
        self.title.setObjectName("name")
        self.title.setToolTip(self._title_tip())
        self.title.mouseDoubleClickEvent = lambda _e: self.rename()
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.dot.setStyleSheet(f"background: {channel.color}; border-radius: 6px;")

        # A channel with a microphone gets the mute button for every microphone, right on the card.
        self.mic_button = _icon_button("mic", "", 32, checkable=True, compact=True)
        self.mic_button.setObjectName("micmute")
        self.mic_button.clicked.connect(lambda _checked=False: self.window.toggle_mic_mute())

        self.menu_button = _icon_button("more", "Channel options", 32, compact=True)
        self.menu_button.setObjectName("plain")

        self.fx_button = QPushButton()
        self.fx_button.setProperty("compact", True)
        self.fx_button.setFixedHeight(32)
        self.fx_button.setToolTip("Open this channel's effects")
        self.fx_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fx_button.clicked.connect(self.open_effects)

        self.link = _icon_button("link", "Link levels: moving one fader moves the other", 32, checkable=True, compact=True)
        self.link.setObjectName("link")
        self.link.toggled.connect(self._on_link)

        self.add_button = QPushButton("+ Add app or device" if not rows else "")
        self.add_button.setObjectName("addchip")
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
        self.sources_text = QLabel("")
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
        readout.setToolTip("Click and type a level in dB (for example -12), then press Enter")
        readout.entered.connect(partial(self._typed_level, mix.id))
        mute = QPushButton()
        mute.setObjectName("mute")
        mute.setCheckable(True)
        mute.setCursor(Qt.CursorShape.PointingHandCursor)
        mute.setAccessibleName(f"Mute {self.channel.label} in {mix.label}")
        mute.toggled.connect(partial(self._on_mute, mix.id))
        mute.toggled.connect(lambda _on, m=mix: self._show_mute(m))
        self.faders[mix.id], self.meters[mix.id] = fader, meter
        self.readouts[mix.id], self.mutes[mix.id] = readout, mute
        return fader, meter

    # ------------------------------------------------------------------ theme
    def refresh_theme(self) -> None:
        """Icons and the few colours set in code, from the theme in use."""
        text2, muted = themes.color("text2"), themes.color("text_dim")
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
                nothing = QLabel("Nothing here yet")
                nothing.setObjectName("hint")
                self.sources_layout.addWidget(nothing)
            for device in self.channel.devices:
                text, tip = self._device_text(device)
                self.sources_layout.addWidget(Chip(text, tip + "\nInput device", partial(self._remove_device, device),
                                                   SourcePicture(text, device=True)))
            for app in self.channel.apps:
                label = self.engine.app_label(app)
                self.sources_layout.addWidget(Chip(label, f"{label}\nApp: {app}", partial(self._remove_app, app),
                                                   SourcePicture(label, self.engine.app_icon(app), app)))
        self._update_fx_button()
        self.show_mic_state()

    def _sources_summary(self) -> str:
        names = [self._device_text(d)[0] for d in self.channel.devices] + [self.engine.app_label(a) for a in self.channel.apps]
        return ", ".join(names) if names else "Nothing here yet"

    def show_mic_state(self) -> None:
        has_mic = bool(self.channel.devices)
        self.mic_button.setVisible(has_mic)
        muted = self.engine.mic_muted
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

    def _on_mute(self, mix_id: str, on: bool) -> None:
        self.engine.set_mute(self.channel.id, mix_id, on)

    def toggle_separate(self) -> None:
        on = not self.channel.separate  # from the real state, not from a tick mark that might be stale
        self.engine.set_separate(self.channel.id, on)
        self.window.say(own_device_message(self.channel, on))
        self.title.setToolTip(self._title_tip())

    def _on_link(self, on: bool) -> None:
        self.engine.set_linked(self.channel.id, on)
        self.link.setIcon(icons.icon("link", themes.color("accent_text") if on else themes.color("text_dim"), 18))
        self.sync_from_model()

    def sync_from_model(self) -> None:
        channel = self.channel
        widgets = [self.link, *self.faders.values(), *self.mutes.values()]
        for widget in widgets:
            widget.blockSignals(True)
        self.link.setChecked(channel.linked)
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


# ------------------------------------------------------------------------ mixes
MIX_EYEBROWS = {MONITOR: "FOR YOU", STREAM: "FOR YOUR AUDIENCE", RECORDING: "FOR RECORDING"}


class MixStrip(QFrame):
    """A mix's master card: its device, a fader with a meter, the level, Mute, Limiter and one action. Vertical in the Columns
    layout, with sliders along it in the Rows layout."""

    def __init__(self, mix: Mix, engine: Engine, on_remove=None, on_add_recording=None, rows: bool = False) -> None:
        super().__init__()
        self.setObjectName("mix")
        self.rows = rows
        if not rows:
            self.setFixedWidth(MIX_WIDTH)
        self.mix, self.engine = mix, engine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16 if not rows else 8)

        head = QHBoxLayout()
        head.setSpacing(8)
        names = QVBoxLayout()
        names.setSpacing(4)
        eyebrow = _label(MIX_EYEBROWS.get(mix.id, "MIX"), "tag", center=False)
        eyebrow.setProperty("mix", mix.id)
        names.addWidget(eyebrow)
        self.setProperty("mix", mix.id)
        title = QLabel(mix.label)
        title.setObjectName("title")
        names.addWidget(title)
        head.addLayout(names, 1)
        self.readout = ReadoutEdit(None)
        self.readout.setProperty("big", True)
        self.readout.setAccessibleName(f"{mix.label} level in decibels")
        self.readout.setToolTip("Click and type a level in dB (for example -6), then press Enter")
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

    def refresh_theme(self) -> None:
        self.fader.set_fill(themes.color("accent"))
        if self.menu_button is not None:
            self.menu_button.setIcon(icons.icon("more", themes.color("text_dim"), 20))
        self._show_toggles()

    def _show_toggles(self) -> None:
        muted = self.mute.isChecked()
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


class _UpdateBridge(QObject):
    """Carries the answer of the update check from its worker thread back to the window."""

    done = Signal(object)
    progress = Signal(int, int)  # bytes downloaded so far, total (0 = unknown)
    staged = Signal(object)      # (version, "") when an update was downloaded and verified, ("", message) when it was not
    quiet = Signal(object)       # the same, for the automatic update: no dialogs


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


def _palette_for(colors: dict) -> QPalette:
    """Qt's own palette in the theme's colours, for the widgets the style sheet does not reach (dialogs, tooltips)."""
    palette = QPalette()
    role = QPalette.ColorRole

    def c(name: str) -> QColor:
        return QColor(colors[name])

    for which, name in ((role.Window, "bg"), (role.WindowText, "text"), (role.Base, "input"), (role.AlternateBase, "panel"),
                        (role.Text, "list_text"), (role.Button, "button"), (role.ButtonText, "button_text"),
                        (role.ToolTipBase, "popup"), (role.ToolTipText, "text"), (role.Highlight, "select"),
                        (role.HighlightedText, "select_text"), (role.Link, "link"), (role.PlaceholderText, "text_dim"),
                        (role.BrightText, "strong")):
        palette.setColor(which, c(name))
    for which in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, which, c("text_off"))
    return palette


# ------------------------------------------------------------------ main window
class MainWindow(QMainWindow):
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
        outer.addWidget(self._build_top_bar())

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        outer.addWidget(self.content, 1)
        self.apps_bar = AppsBar(engine, self)
        self.apps_bar.setFixedHeight(40)
        self.apps_button_holder.addWidget(self.apps_bar)
        self.strips: list = []
        self.mix_strips: list = []
        self.add_mix_button: Optional[QPushButton] = None
        self.first_run: Optional[FirstRun] = None
        self.layout_mode = engine.mixer.layout if engine.mixer.layout in LAYOUTS else "columns"
        self._build_content()

        self.status_label = QLabel(notice or "Ready")
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
        self.repopulate_devices()
        self._show_layout_choice()
        self.refresh_theme_widgets()
        root.setFocus(Qt.FocusReason.OtherFocusReason)

        self._update_tray()  # the tray icon is there from the start if Sluice is set to run in the tray
        self.resize(*DEFAULT_SIZE)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._update_meters)
        self.meter_timer.start(33)
        self.engine_timer = QTimer(self)
        self.engine_timer.timeout.connect(self._tick_engine)
        self.engine_timer.start(500)
        # Settings save themselves: every few seconds, if (and only if) something changed since the last save.
        self._saved_snapshot: Optional[str] = self._snapshot() if config_file is not None and config_file.exists() else None
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start(AUTOSAVE_MS)

    # ------------------------------------------------------------------ the top bar and the content
    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        self.menu_button = _icon_button("menu", "Menu: file, mixer, view and help", 40)
        self.menu_button.setMenu(self.main_menu)
        row.addWidget(self.menu_button)
        name = QLabel("Sluice")
        name.setObjectName("appname")
        row.addWidget(name)
        version = QLabel(f"v{__version__}")
        version.setObjectName("version")
        version.setToolTip("The Sluice version you are running. Please include it in bug reports.")
        row.addSpacing(-8)
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
                               ("rows", "Rows", "A line for each channel, sliders lying down")):
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
        self._show_perf()
        row.addWidget(self.status_chip)

        self.settings_button = QPushButton("Settings")
        self.settings_button.setFixedHeight(40)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip("Theme, audio buffer, start at login, controllers and more")
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

    def _build_content(self) -> None:
        """The channels and the two master cards, in the chosen layout. Rebuilt when the layout is switched."""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        rows = self.layout_mode == "rows"
        self.mix_strips = [
            MixStrip(m, self.engine, self.toggle_recording_mix if m.id == RECORDING else None,
                     self.toggle_recording_mix if m.id == STREAM and not self.engine.mixer.has_recording_mix else None, rows=rows)
            for m in self.engine.mixer.mixes]
        self.add_mix_button = next((s.add_button for s in self.mix_strips if s.add_button is not None), None)
        for strip in self.mix_strips:
            if strip.combo:
                strip.combo.about_to_show.connect(self._on_popup)
        self.channels_widget = QWidget()
        self.channels_widget.setObjectName("channels")
        page = QHBoxLayout()
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(24)
        if rows:
            self.channels_row = QVBoxLayout(self.channels_widget)
            self.channels_row.setContentsMargins(0, 0, 8, 0)
            self.channels_row.setSpacing(16)
            scroll = QScrollArea()
        else:
            self.channels_row = QHBoxLayout(self.channels_widget)
            self.channels_row.setContentsMargins(0, 0, 0, 16)  # air between the cards and the scroll bar
            self.channels_row.setSpacing(16)
            scroll = SmoothScrollArea()
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
            masters = QVBoxLayout()
            masters.setSpacing(16)
            for strip in self.mix_strips:
                masters.addWidget(strip, 1)
            holder = QWidget()
            holder.setFixedWidth(304)
            holder.setLayout(masters)
            masters.setContentsMargins(0, 0, 0, 0)
            page.addWidget(holder)
        else:
            page.addWidget(scroll, 1)
            masters = QHBoxLayout()
            masters.setSpacing(16)
            for strip in self.mix_strips:
                masters.addWidget(strip)
            holder = QWidget()
            holder.setLayout(masters)
            masters.setContentsMargins(0, 0, 0, 16)
            page.addWidget(holder)
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
        if mode != self.layout_mode:
            self.layout_mode = mode
            self._build_content()
        self._show_layout_choice()

    def _show_layout_choice(self) -> None:
        for key, button in self.layout_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == self.layout_mode)
            button.blockSignals(False)
        for key, action in self.layout_actions.items():
            action.setChecked(key == self.layout_mode)

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
            strip.set_empty(wanted and not strip.channel.apps and strip.channel.id != "mic" and not strip.rows)
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
    def _action(self, menu: QMenu, text: str, slot, shortcut=None, checkable: bool = False) -> QAction:
        action = menu.addAction(text)
        action.setCheckable(checkable)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
            self.addAction(action)  # the menu bar is out of sight (the menu button holds the menus): shortcuts belong to the window
        action.triggered.connect(lambda _checked=False: slot())
        return action

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._action(file_menu, "&Save settings", self.save_settings, QKeySequence.StandardKey.Save)
        file_menu.addSeparator()
        self._action(file_menu, "&Export settings\u2026", self.export_settings)
        self._action(file_menu, "&Import settings\u2026", self.import_settings)
        self.restore_menu = file_menu.addMenu("&Restore earlier settings")
        self.restore_menu.aboutToShow.connect(self._fill_restore_menu)
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", self.quit_app, QKeySequence.StandardKey.Quit)

        mixer_menu = bar.addMenu("&Mixer")
        self._action(mixer_menu, "&Add channel\u2026", self.add_channel, "Ctrl+N")
        self._action(mixer_menu, "&Refresh devices and apps", self.refresh_now, "F5")
        self._action(mixer_menu, "&Recording devices for OBS\u2026", self.show_own_devices)
        self.recording_action = self._action(mixer_menu, "Third mix: &Recording\u2026", self.toggle_recording_mix, checkable=True)
        mixer_menu.addSeparator()
        self.mic_action = self._action(mixer_menu, "Mute my &microphone", self.toggle_mic_mute, "Ctrl+M", checkable=True)
        self.hear_action = self._action(mixer_menu, "&Hear Broadcast", self.toggle_hear_broadcast, "Ctrl+B", checkable=True)
        self.mute_actions = {}
        for mix in self.engine.mixer.mixes:
            shortcut = {MONITOR: "Ctrl+Shift+L", STREAM: "Ctrl+Shift+B"}.get(mix.id, "")
            self.mute_actions[mix.id] = self._action(mixer_menu, f"&Mute {mix.label}", partial(self.toggle_mix_mute, mix.id),
                                                     shortcut, checkable=True)
        mixer_menu.aboutToShow.connect(self._refresh_mixer_menu)

        # Settings: everything that is chosen once and then left alone.
        self.settings_menu = settings_menu = bar.addMenu("&Settings")
        self.theme_menu = settings_menu.addMenu("&Theme")
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        buffer_menu = settings_menu.addMenu("Audio &buffer")
        self.buffer_actions = {}
        labels = {256: "Smallest (256 frames): lowest delay, most CPU", 512: "Small (512 frames): the default",
                  1024: "Large (1024 frames): less CPU", 2048: "Largest (2048 frames): least CPU, most delay"}
        for frames in BUFFER_CHOICES:
            self.buffer_actions[frames] = self._action(buffer_menu, labels[frames], partial(self.set_buffer, frames), checkable=True)
        buffer_menu.aboutToShow.connect(self._refresh_buffer_menu)
        startup = settings_menu.addMenu("Start when I &log in")
        group = QActionGroup(self)
        self.autostart_actions = {}
        for key, text in (("off", "Do not start automatically"), ("window", "Start with the window open"),
                          ("minimized", "Start minimized (to the system tray if that is switched on)")):
            action = startup.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.triggered.connect(lambda _c=False, key=key: self.set_autostart(key))
            self.autostart_actions[key] = action
        closing = settings_menu.addMenu("When I &close the window")
        close_group = QActionGroup(self)
        self.close_actions = {}
        for key, text in (("quit", "Quit Sluice"), ("minimize", "Keep running, minimized to the taskbar"),
                          ("tray", "Keep running in the system tray")):
            action = closing.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(close_group)
            action.triggered.connect(lambda _c=False, key=key: self.set_close_action(key))
            self.close_actions[key] = action
        self.launcher_action = self._action(settings_menu, "Add Sluice to the &applications menu", self.toggle_launcher, checkable=True)
        self.auto_update_action = self._action(settings_menu, "&Update automatically when a new version is found",
                                               self.toggle_auto_update, checkable=True)
        settings_menu.addSeparator()
        self.controllers_separator = settings_menu.addSeparator()  # "MIDI controllers and Stream Deck" is added here by attach_controls()
        self._action(settings_menu, "&Reset all settings to the defaults\u2026", self.reset_settings)
        settings_menu.aboutToShow.connect(self._refresh_settings_menu)

        view_menu = bar.addMenu("&View")
        self.layout_actions = {}
        layout_group = QActionGroup(self)
        for key, text in (("columns", "Layout: &Columns (a card for each channel)"), ("rows", "Layout: &Rows (a line for each channel)")):
            action = view_menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(layout_group)
            action.triggered.connect(lambda _c=False, key=key: self.set_layout(key))
            self.layout_actions[key] = action
        view_menu.addSeparator()
        self.fullscreen_action = self._action(view_menu, "&Full screen", self.toggle_fullscreen, "F11", checkable=True)
        self._action(view_menu, "&Reset window size", self.reset_window_size)
        view_menu.aboutToShow.connect(lambda: self.fullscreen_action.setChecked(self.isFullScreen()))

        self.help_menu = bar.addMenu("&Help")
        self._action(self.help_menu, "&Keyboard shortcuts", self.show_shortcuts, "F1")
        self.help_menu.addSeparator()
        self.help_menu.addAction("What's new in this version\u2026", self.show_whats_new)
        self.help_menu.addAction("Check for updates\u2026", self.check_for_updates)
        self.rollback_action = self._action(self.help_menu, "Go back to the previous version\u2026", self.rollback_update)
        self.help_menu.aboutToShow.connect(self._refresh_update_menu)
        self.help_menu.addSeparator()
        self.help_menu.addAction("Save bug report\u2026", self.save_report)
        self._action(self.help_menu, "I heard a &glitch (mark this moment)", self.mark_glitch, "Ctrl+Shift+G")
        folders = self.help_menu.addMenu("Open &folder")
        folders.addAction("&Settings", self.open_settings_folder)
        folders.addAction("&Logs", self.open_log_folder)
        folders.addAction("&Themes", self.open_theme_folder)
        self.help_menu.addAction("Report a problem\u2026", partial(self.open_link, ISSUES_URL))
        self.help_menu.addSeparator()
        self.help_menu.addAction("Join the Discord\u2026", partial(self.open_link, DISCORD_URL))
        self.help_menu.addAction("Project page on GitHub\u2026", partial(self.open_link, PROJECT_URL))
        self.help_menu.addAction(f"About Sluice {__version__}", self.show_about)
        self.uninstall_action = self.help_menu.addAction("Uninstall Sluice\u2026", self.uninstall_app)

        # The menus live behind the menu button (and the Settings button) in the top bar; the classic bar stays out of sight.
        self.main_menu = QMenu(self)
        for menu in (file_menu, mixer_menu, view_menu, self.help_menu):
            self.main_menu.addMenu(menu)
        bar.setVisible(False)

    def uninstall_app(self) -> None:
        """Two ways to remove Sluice, each showing exactly what it removes; then Sluice closes and a separate process does it."""
        import subprocess

        from . import uninstall

        if "Demo" in self.engine.io.label:
            QMessageBox.information(self, "Uninstall Sluice", "Demo mode changes nothing, so there is nothing to uninstall here.")
            return
        keep_plan = uninstall.plan(keep_settings=True)
        all_plan = uninstall.plan(keep_settings=False, remove_git=True)

        def listing(result) -> str:
            return uninstall.describe(result).replace("Sluice will remove:", "This will remove:")

        box = QMessageBox(self)
        box.setWindowTitle("Uninstall Sluice")
        box.setText("How much of Sluice should be removed?")
        box.setInformativeText(
            "Uninstall, keep my settings\n" + listing(keep_plan) +
            "\n\nRemove everything\n" + listing(all_plan).replace("\n  (nothing: it is not installed here)", "") +
            "\n\nBoth close Sluice first and remove these a moment later, then check that nothing was missed. "
            + " ".join(uninstall.STAYS))
        caches = QCheckBox("Also clear download caches (pip and cargo; other programs use them too)")
        caches.setToolTip("Clears ~/.cache/pip and ~/.cargo/registry. Programs that use them just download again when they need to.")
        box.setCheckBox(caches)
        keep_button = box.addButton("Uninstall, keep my settings", QMessageBox.ButtonRole.AcceptRole)
        everything_button = box.addButton("Remove everything", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (keep_button, everything_button):
            return
        keep = clicked is keep_button
        remove_git = False
        if not keep and all_plan.git_folder:
            answer = QMessageBox.question(
                self, "Delete the git folder?",
                "The Sluice folder is a git clone. Deleting it also deletes any changes in it that you have not committed "
                "or pushed.\n\nDelete it too?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            remove_git = answer == QMessageBox.StandardButton.Yes
        command = uninstall.command_for_gui(keep, clear_caches=caches.isChecked(), remove_git=remove_git)
        script = ('sleep 4; out=$("$@" 2>&1); '
                  'command -v notify-send >/dev/null 2>&1 && notify-send "Sluice uninstall" "$out"; exit 0')
        try:
            # a few seconds' wait lets this process finish closing (it holds the single-copy lock until then)
            subprocess.Popen(["sh", "-c", script, "sluice-uninstall", *command], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            QMessageBox.warning(self, "Uninstall Sluice", f"Could not start the uninstall: {exc}\nRun this in a terminal instead: sluice --uninstall")
            return
        self.quit_app()

    def open_link(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.information(self, "Open link", f"Sluice could not open your browser. The address is:\n\n{url}")

    def _refresh_mixer_menu(self) -> None:
        self.hear_action.setChecked(self.engine.hear_broadcast)
        self.mic_action.setChecked(self.engine.mic_muted)
        self.recording_action.setChecked(self.engine.mixer.has_recording_mix)
        for mix_id, action in self.mute_actions.items():
            action.setChecked(self.engine.mixer.mix(mix_id).mute)

    def _refresh_settings_menu(self) -> None:
        self._refresh_file_menu()
        self.auto_update_action.setChecked(self.engine.mixer.auto_update)

    # ------------------------------------------------------------------ themes
    def _system_is_dark(self) -> bool:
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", None)  # Qt 6.5 and newer; an older one has no word on it: stay dark
        return scheme is None or scheme() != Qt.ColorScheme.Light

    def _themes_folder(self) -> Optional[Path]:
        return themes.themes_dir(self.config_file)

    def current_theme(self) -> "themes.Theme":
        return themes.resolve(self.engine.mixer.theme, self._system_is_dark(), self._themes_folder())

    def apply_theme(self, theme_id: Optional[str] = None) -> "themes.Theme":
        """Show a theme now (or the one saved in the settings): the style sheet, the palette and the meters."""
        if theme_id is not None:
            self.engine.mixer.theme = theme_id
        theme = self.current_theme()
        themes.set_current(theme.colors)
        self.setStyleSheet(themes.build_style(theme.colors))
        app = QGuiApplication.instance()
        if app is not None:
            app.setPalette(_palette_for(theme.colors))
        self.refresh_theme_widgets()
        return theme

    def _on_system_scheme_changed(self, *_args) -> None:
        if self.engine.mixer.theme == themes.SYSTEM and not self._closed:
            self.apply_theme()

    def _fill_theme_menu(self) -> None:
        menu = self.theme_menu
        menu.clear()
        group = QActionGroup(menu)
        chosen = themes.canonical_id(self.engine.mixer.theme, self._themes_folder())

        def add(theme_id: str, text: str, tip: str = "") -> None:
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.setChecked(chosen == theme_id)
            if tip:
                action.setToolTip(tip)
            action.triggered.connect(lambda _c=False, theme_id=theme_id: self.choose_theme(theme_id))

        for theme in themes.BUILT_IN.values():
            add(theme.id, theme.name)
        add(themes.SYSTEM, themes.SYSTEM_LABEL, "Dark or Light, following your desktop's own setting")
        custom = themes.custom_themes(self._themes_folder())
        if custom:
            menu.addSeparator()
            for theme in custom:
                add(theme.id, theme.name)
        if chosen.startswith(themes.CUSTOM_PREFIX) and not any(t.id == chosen for t in custom):  # not in the folder any more
            menu.addSeparator()
            missing = menu.addAction("An imported theme that is no longer in the themes folder (showing Dark)")
            missing.setCheckable(True)
            missing.setChecked(True)
            missing.setEnabled(False)
        menu.addSeparator()
        menu.addAction("&Import theme\u2026", self.import_theme)
        menu.addAction("&Export current theme\u2026", self.export_theme)
        if custom:
            remove = menu.addMenu("&Remove an imported theme")
            for theme in custom:
                remove.addAction(theme.name, partial(self.remove_theme, theme.id))
        menu.addSeparator()
        more = menu.addAction("&Get more themes\u2026", partial(self.open_link, THEMES_URL))
        more.setToolTip("Opens the theme collection on the project page in your browser: download a file, then Import theme")
        menu.setToolTipsVisible(True)

    def choose_theme(self, theme_id: str) -> None:
        theme = self.apply_theme(theme_id)
        if theme_id == themes.SYSTEM:
            self.say(f"Theme: following your system (right now {theme.name}).")
        else:
            self.say(f"Theme: {theme.name}.")

    def import_theme_from(self, path) -> "themes.Theme":
        """Check a theme file, keep a copy in the themes folder and switch to it. Raises ThemeError."""
        folder = self._themes_folder()
        if folder is None:
            raise themes.ThemeError("Demo mode does not keep imported themes.")
        theme, notes = themes.load_file(path)
        problems = themes.contrast_problems(theme.colors)
        if problems:
            ask = QMessageBox.question(
                self, "Hard to read",
                f"The theme \u201c{theme.name}\u201d may be hard to read:\n\n" + "\n".join("\u2022 " + p for p in problems[:4])
                + "\n\nUse it anyway? You can switch back in Settings > Theme.")
            if ask != QMessageBox.StandardButton.Yes:
                raise themes.ThemeError("The theme was not imported.")
        stored = themes.save_custom(theme, folder)
        self.apply_theme(stored.id)
        self.say(f"Theme \u201c{stored.name}\u201d imported and in use." + (f" ({'; '.join(notes[:3])}.)" if notes else ""))
        return stored

    def import_theme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import theme", str(Path.home()), "Themes (*.json)")
        if not path:
            return
        try:
            self.import_theme_from(path)
        except themes.ThemeError as exc:
            QMessageBox.warning(self, "Could not import the theme", str(exc))

    def export_theme_to(self, path) -> None:
        theme = self.current_theme()
        name = theme.name if theme.id.startswith(themes.CUSTOM_PREFIX) else f"{theme.name} copy"
        data = themes.export_dict(themes.Theme(theme.id, name, theme.base, theme.colors))
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.say(f"Theme saved to {logs.short_path(path)}. Edit the colours, then use Settings > Theme > Import theme.")

    def export_theme(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export current theme", str(Path.home() / "sluice-theme.json"),
                                              "Themes (*.json)")
        if path:
            try:
                self.export_theme_to(path)
            except OSError as exc:
                QMessageBox.warning(self, "Could not save the theme", str(exc))

    def remove_theme(self, theme_id: str) -> None:
        if themes.remove_custom(theme_id, self._themes_folder()):
            if self.engine.mixer.theme == theme_id:
                self.apply_theme(themes.DEFAULT)
            self.say("Theme removed.")
        else:
            self.say("That theme could not be removed.")

    def open_theme_folder(self) -> None:
        folder = self._themes_folder()
        if folder is None:
            self.say("Demo mode does not keep imported themes.")
            return
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def toggle_recording_mix(self) -> None:
        mixer = self.engine.mixer
        turn_on = not mixer.has_recording_mix
        text = ("Add a third mix, \u201cRecording\u201d: a second virtual microphone, \u201cSluice (Recording)\u201d, with its own "
                "faders and mutes, so a recorder can get a different blend from the one your audience hears."
                if turn_on else "Remove the Recording mix and its virtual microphone.")
        ask = QMessageBox(self)
        ask.setWindowTitle("Recording mix")
        ask.setText(text + "\n\nSluice has to restart to do this. Your settings are saved first.")
        restart = ask.addButton("Restart now", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        self.recording_action.setChecked(mixer.has_recording_mix)
        if ask.clickedButton() is not restart:
            return
        mixer.set_recording_mix(turn_on)
        from . import reconnect

        self.shutdown()  # saves the settings
        reconnect.restart_self(show_window=True)

    def toggle_mic_mute(self) -> None:
        self.engine.set_mic_muted(not self.engine.mic_muted)  # from the real state, like the other toggles
        self._show_mic_state()
        if self._tray is not None and self._tray.isVisible():
            self._tray.setToolTip("Sluice" + (" (microphone muted)" if self.engine.mic_muted else ""))
        self.say("Your microphone is muted everywhere, including Sluice (Mic)." if self.engine.mic_muted
                 else "Your microphone is live.")

    def _show_mic_state(self) -> None:
        for strip in self.strips:
            strip.show_mic_state()

    def toggle_hear_broadcast(self) -> None:
        on = not self.engine.hear_broadcast  # from the real state, so a stale tick mark can never invert it
        self.engine.set_hear_broadcast(on)
        self.sync_from_model()
        self.say("Your output now plays the Broadcast mix: this is what your audience hears." if on
                 else "Your output is back on the Listen mix.")

    def toggle_mix_mute(self, mix_id: str) -> None:
        mix = self.engine.mixer.mix(mix_id)
        self.engine.set_master_mute(mix_id, not mix.mute)
        self.sync_from_model()
        self.say(f"{mix.label} is {'muted' if mix.mute else 'on'}.")

    def _refresh_buffer_menu(self) -> None:
        for frames, action in self.buffer_actions.items():
            action.setChecked(frames == self.engine.mixer.buffer_frames)

    def set_buffer(self, frames: int) -> None:
        self.engine.mixer.buffer_frames = frames
        self.say(f"Audio buffer set to {frames} frames. It is used the next time Sluice starts "
                 f"(running now: {self.engine.io.blocksize}).")

    def show_own_devices(self) -> None:
        OwnDevicesDialog(self.engine, self).exec()

    def refresh_now(self) -> None:
        self.engine.refresh_devices()
        self.repopulate_devices()
        self.refresh_sources()
        self.say("Devices and apps refreshed.")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def reset_window_size(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        self.resize(*DEFAULT_SIZE)

    def show_shortcuts(self) -> None:
        rows = [("Ctrl+S", "Save settings"), ("Ctrl+N", "Add a channel"), ("Ctrl+B", "Hear Broadcast on or off"),
                ("Ctrl+Shift+L", "Mute or unmute Listen"), ("Ctrl+Shift+B", "Mute or unmute Broadcast"),
                ("Ctrl+Shift+G", "Mark a glitch you just heard"),
                ("F5", "Refresh devices and apps"), ("F11", "Full screen"), ("F1", "This list"), ("Ctrl+Q", "Quit")]
        table = "".join(f"<tr><td><b>{key}</b>&nbsp;&nbsp;&nbsp;</td><td>{what}</td></tr>" for key, what in rows)
        QMessageBox.information(self, "Keyboard shortcuts", f"<table>{table}</table><br>"
                                "Faders: scroll the mouse wheel over one, or use the arrow keys when it is selected.<br>"
                                "For buttons and knobs outside the app, see <b>Settings > MIDI controllers and Stream Deck</b>.")

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
        state = desktop.autostart_state()
        for key, action in self.autostart_actions.items():
            action.setChecked(key == state)
        for key, action in self.close_actions.items():
            action.setChecked(key == self.engine.mixer.close_action)

    def set_close_action(self, mode: str) -> None:
        self.engine.mixer.close_action = mode
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

    # ------------------------------------------------------------------ system tray
    @property
    def tray_active(self) -> bool:
        """True while the tray icon is on screen: then closing or minimizing the window hides it into the tray."""
        return self._tray is not None and self._tray.isVisible()

    def _update_tray(self) -> None:
        """Show the tray icon exactly while the close setting is 'tray' (and the desktop has a tray)."""
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        want = self.engine.mixer.close_action == "tray" and not self._closed and QSystemTrayIcon.isSystemTrayAvailable()
        if not want:
            if self._tray is not None:
                self._tray.hide()
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(self.windowIcon(), self)
            menu = QMenu(self)
            self._tray_show = menu.addAction("Show Sluice", self.bring_to_front)
            self._tray_mic = menu.addAction("Mute my microphone", self.toggle_mic_mute)
            self._tray_mic.setCheckable(True)
            menu.addSeparator()
            menu.addAction("Quit", self.quit_app)
            menu.aboutToShow.connect(self._refresh_tray_menu)
            self._tray.setContextMenu(menu)
            self._tray_menu = menu  # keep a reference: Qt does not own a tray icon's menu
            self._tray.activated.connect(self._on_tray_activated)
        self._tray.setToolTip("Sluice" + (" (microphone muted)" if self.engine.mic_muted else ""))
        self._tray.show()

    def _refresh_tray_menu(self) -> None:
        self._tray_show.setText("Hide Sluice" if self.isVisible() and not self.isMinimized() else "Show Sluice")
        self._tray_mic.setChecked(self.engine.mic_muted)

    def _on_tray_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # a plain click: show it, or hide it if it is already in front
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.hide()
            else:
                self.bring_to_front()

    def start_minimized(self) -> None:
        """Start without showing the window: into the tray if that is how Sluice is set to run, else to the taskbar."""
        self._update_tray()
        if self.tray_active:
            self.say("Sluice is running in the system tray.")
        else:
            self.showMinimized()

    def quit_app(self) -> None:
        """Really quit (File > Quit, Ctrl+Q), whatever closing the window is set to do."""
        self._quitting = True
        self.close()

    def set_autostart(self, mode: str) -> None:
        from . import desktop

        try:
            desktop.set_autostart(mode)
        except OSError as exc:
            QMessageBox.warning(self, "Could not change start-up", str(exc))
            return
        self.say({"off": "Sluice will not start by itself.",
                  "window": "Sluice will start when you log in, with its window open.",
                  "minimized": "Sluice will start when you log in, minimized to the taskbar."}[mode])

    def toggle_launcher(self) -> None:
        from . import desktop

        try:
            if desktop.is_installed():
                desktop.uninstall()
                self.say("Sluice was removed from the applications menu.")
            else:
                desktop.install()
                self.say("Sluice is now in the applications menu: search for \u201cSluice\u201d in your launcher.")
        except OSError as exc:
            QMessageBox.warning(self, "Could not change the applications menu", str(exc))

    def open_settings_folder(self) -> None:
        folder = (self.config_file or config_path()).parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

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
        self._show_mic_state()  # a controller or `sluice ctl mic-mute` may have changed it
        if self._tray is not None and self._tray.isVisible():
            self._tray.setToolTip("Sluice" + (" (microphone muted)" if self.engine.mic_muted else ""))

    # ---------------------------------------------------------------- channels
    def rebuild_channels(self) -> None:
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
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("Add a channel for another app or group of apps")
        add.clicked.connect(self.add_channel)
        if rows:
            add.setFixedHeight(48)
            self.channels_row.addWidget(add)
            self.channels_row.addStretch(0)
        else:
            add.setFixedWidth(160)
            add.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            self.channels_row.addWidget(add)
            self.channels_row.addStretch(1)
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
        self.apps_bar.refresh()

    def refresh_sources(self) -> None:
        for strip in self.strips:
            strip.refresh_sources()
        self.apps_bar.refresh()
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
        levels = self.engine.levels()
        for strip in self.strips:
            for mix_id, meter in strip.meters.items():
                meter.push(levels.get(f"ch:{strip.channel.id}:{mix_id}", 0.0))
        for strip in self.mix_strips:
            strip.meter.push(levels.get(f"mix:{strip.mix.id}", 0.0))

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

    # ----------------------------------------------------------- updating in place
    def start_update(self, result) -> None:
        """Download and check the new version (nothing changes yet), then offer to restart into it."""
        root = selfupdate.install_root()
        problem = selfupdate.offer_problem(root, result)
        if problem:
            QMessageBox.information(self, "Update", problem)
            return
        dialog = QProgressDialog(f"Downloading Sluice {result.latest}\u2026", "", 0, 100, self)
        dialog.setWindowTitle("Updating Sluice")
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setValue(0)
        self._update_progress_dialog = dialog
        self.say(f"Downloading Sluice {result.latest}\u2026")
        bridge, stage = self._update_bridge, self._stage_update

        def work() -> None:
            try:
                version = stage(result, root, progress=lambda done, total: bridge.progress.emit(done, total))
                bridge.staged.emit((version, ""))
            except selfupdate.UpdateError as exc:
                bridge.staged.emit(("", str(exc)))
            except Exception as exc:  # anything unexpected is still just "could not update"
                log.exception("update failed")
                bridge.staged.emit(("", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, name="sluice-update", daemon=True).start()

    def _update_progress(self, done: int, total: int) -> None:
        dialog = self._update_progress_dialog
        if dialog is not None and total > 0:
            dialog.setValue(min(99, int(done * 100 / total)))

    def _close_progress(self) -> None:
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.close()
            self._update_progress_dialog = None

    def _update_staged(self, outcome) -> None:
        self._close_progress()
        version, message = outcome
        if not version:
            self.say(f"Could not update: {message.splitlines()[0] if message else 'unknown error'}")
            QMessageBox.warning(self, "Could not update", message or "Unknown error.")
            return
        self.say(f"Sluice {version} is downloaded and checked. It is installed when Sluice restarts or closes.")
        if self._ask_restart_for_update(version):
            self.restart_into_update()

    def _ask_restart_for_update(self, version: str) -> bool:
        ask = QMessageBox(self)
        ask.setWindowTitle("Update ready")
        ask.setText(f"Sluice {version} was downloaded and checked.\n\nRestart now to start using it? Your settings are saved "
                    "first. If you choose later, it is installed the next time you close Sluice.")
        restart = ask.addButton("Restart now", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        return ask.clickedButton() is restart

    def restart_into_update(self) -> None:
        from . import reconnect

        self.shutdown()  # saves the settings, stops the audio
        selfupdate.apply_staged_quietly()
        reconnect.restart_self(show_window=True)

    def _refresh_update_menu(self) -> None:
        previous = selfupdate.previous_version(selfupdate.install_root())
        self.rollback_action.setEnabled(bool(previous))
        self.rollback_action.setText(f"Go back to version {previous}\u2026" if previous else "Go back to the previous version\u2026")

    def toggle_auto_update(self) -> None:
        mixer = self.engine.mixer
        turn_on = not mixer.auto_update
        if turn_on:
            reason = selfupdate.unavailable_reason(selfupdate.install_root())
            if reason:
                self.auto_update_action.setChecked(False)
                QMessageBox.information(self, "Update automatically", reason)
                return
            ask = QMessageBox.question(
                self, "Update automatically",
                "Sluice will ask GitHub once, shortly after it starts, whether there is a newer version. If there is, it "
                "downloads it, checks it against its checksum, and installs it the next time you close Sluice. It never "
                "restarts or changes anything while it is running, and you can go back with Help > Go back to the previous "
                "version.\n\nTurn this on?")
            if ask != QMessageBox.StandardButton.Yes:
                self.auto_update_action.setChecked(False)
                return
        mixer.auto_update = turn_on
        self.auto_update_action.setChecked(turn_on)
        self.say("Sluice will download new versions by itself and install them when you close it." if turn_on
                 else "Automatic updates are off. Help > Check for updates still works.")

    def _auto_update_check(self) -> None:
        """Once, a little after start-up, only if the user turned it on: fetch a newer version and leave it waiting."""
        if self._auto_update_started or self._closed or self.config_file is None or not self.engine.mixer.auto_update:
            return
        root = selfupdate.install_root()
        if selfupdate.unavailable_reason(root):
            return
        self._auto_update_started = True
        check, stage, bridge = self._update_check, self._stage_update, self._update_bridge

        def work() -> None:
            try:
                result = check(__version__)
                if result.status != "available" or selfupdate.offer_problem(root, result):
                    return
                bridge.quiet.emit((stage(result, root), ""))
            except selfupdate.UpdateError as exc:
                bridge.quiet.emit(("", str(exc)))
            except Exception:
                log.exception("automatic update failed")

        threading.Thread(target=work, name="sluice-auto-update", daemon=True).start()

    def _auto_update_staged(self, outcome) -> None:
        version, message = outcome
        if version:
            self.say(f"Sluice {version} was downloaded and checked. It is installed when you close Sluice.")
        else:
            log.info("automatic update did not go ahead: %s", message)
            self.say("An automatic update could not be installed. Help > Check for updates shows why.")

    def rollback_update(self) -> None:
        root = selfupdate.install_root()
        previous = selfupdate.previous_version(root)
        if not previous:
            QMessageBox.information(self, "Go back", "There is no earlier version to go back to.")
            return
        ask = QMessageBox(self)
        ask.setWindowTitle("Go back to the previous version")
        ask.setText(f"Go back to Sluice {previous}?\n\nSluice restarts. Your settings are kept, but a newer version may have "
                    "saved things an older one does not understand, so a backup of your settings is a good idea first "
                    "(File > Export settings).")
        go = ask.addButton("Go back and restart", QMessageBox.ButtonRole.AcceptRole)
        ask.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        ask.exec()
        if ask.clickedButton() is not go:
            return
        self.shutdown()
        try:
            selfupdate.rollback(root)
        except selfupdate.UpdateError as exc:
            log.warning("rollback failed: %s", exc)
        from . import reconnect

        reconnect.restart_self(show_window=True)

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
                    "(Help > Open folder).")

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
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            try:
                hints.colorSchemeChanged.disconnect(self._on_system_scheme_changed)
            except (RuntimeError, TypeError):
                pass
        if self._tray is not None:
            self._tray.hide()  # no ghost icon after Sluice is gone
        self.meter_timer.stop()
        self.engine_timer.stop()
        self.autosave_timer.stop()
        if self.controls is not None:
            self.controls.close()
        self.engine.shutdown(save_to=None if self._keep_settings_file else self.config_file)

    def closeEvent(self, event) -> None:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        saving = bool(app is not None and app.isSavingSession())  # True during a logout or shutdown: always let it close
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
            self.meter_timer.start(33)
        elif not on and self.meter_timer.isActive():
            self.meter_timer.stop()

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
        if event.type() == QEvent.Type.WindowStateChange:
            self._set_meters_running(self.isVisible() and not self.isMinimized())
            if self.tray_active and self.isMinimized() and not self._closed:
                QTimer.singleShot(0, self._minimize_to_tray)
        super().changeEvent(event)
