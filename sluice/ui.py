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

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFontMetrics, QKeySequence, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
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
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, logs, report, updates, whatsnew
from .engine import Engine
from .model import BUFFER_CHOICES, MAX_DB, MIN_DB, MONITOR, STREAM, Channel, Mix, Mixer, config_path, linear_to_db, list_backups
from .ui_effects import EffectsDialog
from .ui_widgets import ReadoutEdit

log = logging.getLogger("sluice.ui")
AUTOSAVE_MS = 5000  # how often to look for unsaved changes
NONE_DATA = "__none__"  # combo item data for "no device" (Qt dislikes None)
CHANNEL_WIDTH = 180
MIX_WIDTH = 132
MIX_TAGS = {MONITOR: "LISTEN", STREAM: "BROADCAST"}

STYLE = """
QMainWindow, QWidget#root, QScrollArea, QWidget#channels { background: #181b20; }
QWidget { color: #d7dce2; font-size: 12px; }
QFrame#strip, QFrame#mix, QFrame#apps {
    background: #232830; border: 1px solid #373d47; border-radius: 8px;
}
QFrame#mix { background: #20262e; }
QFrame#apps { border-radius: 6px; }
QFrame#chip { background: #2c323c; border: 1px solid #3d4551; border-radius: 4px; }
QFrame#accent { border: none; border-radius: 2px; }
QLabel { background: transparent; }
QLabel#title { font-size: 15px; font-weight: 700; color: #f0f3f6; }
QLabel#tag { font-size: 9px; font-weight: 600; letter-spacing: 1px; color: #7d8795; }
QLabel#hint { font-size: 10px; color: #8a93a0; }
QLabel#chiptext { font-size: 11px; background: transparent; }
QLabel#readout { font-family: monospace; font-size: 11px; color: #e8eef5;
    background: #12151a; border: 1px solid #2e343d; border-radius: 4px; padding: 2px 0; }
QLineEdit#readout { font-family: monospace; font-size: 11px; color: #e8eef5; background: #12151a;
    border: 1px solid #2e343d; border-radius: 4px; padding: 2px 0; }
QLineEdit#readout:focus { border-color: #5b8def; }
QLabel#status { color: #8a93a0; padding: 2px 8px; }
QLabel#demo { color: #1b1300; background: #f5c542; font-weight: 700; padding: 3px 10px; }
QFrame#divider { background: #373d47; max-width: 1px; }

QPushButton {
    background: #303641; color: #aab2bd; border: 1px solid #454c58;
    border-radius: 4px; padding: 4px 8px; font-weight: 600;
}
QPushButton:hover { border-color: #6f7887; }
QPushButton:checked { color: #0e1014; border-color: transparent; }
QPushButton::menu-indicator { image: none; width: 0; }
QPushButton#mute:checked  { background: #ef5258; }
QPushButton#limiter:checked { background: #35d0c0; }
QPushButton#link:checked { background: #8aa0b8; }
QPushButton#add { border-style: dashed; color: #8a93a0; background: transparent; }
QPushButton#addchannel { border: 2px dashed #3d4551; color: #8a93a0; background: transparent;
    border-radius: 8px; font-size: 13px; }
QPushButton#addchannel:hover { border-color: #6f7887; color: #d7dce2; }
QPushButton#app { padding: 3px 10px; border-radius: 11px; }
QPushButton#appassigned { padding: 3px 10px; border-radius: 11px; color: #e8eef5; background: #2f4a6b; }
QToolButton { background: transparent; border: none; color: #8a93a0; font-weight: 700; padding: 0 4px; }
QToolButton:hover { color: #ef5258; }
QToolButton#menu:hover { color: #e8eef5; }
QToolButton::menu-indicator { image: none; width: 0; }

QComboBox {
    background: #12151a; border: 1px solid #373d47; border-radius: 4px; padding: 3px 6px;
}
QComboBox:hover { border-color: #6f7887; }
QComboBox QAbstractItemView {
    background: #1b1f26; border: 1px solid #454c58; selection-background-color: #34507a;
}
QMenu { background: #1b1f26; border: 1px solid #454c58; padding: 4px; }
QMenu::item { padding: 5px 18px; border-radius: 3px; }
QMenu::item:selected { background: #34507a; }
QMenu::item:disabled { color: #5d6672; }
QMenuBar { background: #181b20; color: #aab2bd; }
QMenuBar::item:selected { background: #2c323c; }
QDialog { background: #1d2127; }
QListWidget { background: #12151a; border: 1px solid #373d47; border-radius: 4px; }
QListWidget::item { padding: 5px; }
QListWidget::item:selected { background: #34507a; }
QLineEdit { background: #11141a; border: 1px solid #2c333d; border-radius: 6px; padding: 5px 8px; color: #e6e9ef; selection-background-color: #3b5b8f; }
QLineEdit:focus { border-color: #5b8def; }
QCheckBox { spacing: 8px; color: #c9ced8; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #3d4551; border-radius: 3px; background: #11141a; }
QCheckBox::indicator:checked { background: #5b8def; border-color: #5b8def; }
QListWidget { background: #11141a; border: 1px solid #2c333d; border-radius: 6px; padding: 4px; color: #e6e9ef; outline: 0; }
QListWidget::item { padding: 5px 6px; border-radius: 4px; }
QListWidget::item:selected { background: #2d3a52; color: #ffffff; }
QListWidget::item:hover:!selected { background: #1d222b; }
QScrollBar:horizontal { background: #1f232a; height: 12px; border-radius: 6px; margin: 0 2px; }
QScrollBar::handle:horizontal { background: #3d4551; border-radius: 6px; min-width: 48px; }
QScrollBar::handle:horizontal:hover { background: #56606f; }
QScrollBar::handle:horizontal:pressed { background: #6b7688; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #3d4551; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }

QSlider::groove:vertical { background: #0e1014; position: absolute; left: 12px; right: 12px;
    border-radius: 3px; }
QSlider::add-page:vertical { background: #2c5f48; border-radius: 3px; }
QSlider::handle:vertical { background: #dfe4ea; height: 22px; margin: 0 -9px;
    border-radius: 4px; border: 1px solid #8a93a0; }
QSlider::handle:vertical:hover { background: #ffffff; }
QSlider::groove:horizontal { background: #0e1014; height: 6px; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #2c5f48; border-radius: 3px; }
QSlider::handle:horizontal { background: #dfe4ea; width: 14px; margin: -5px 0; border-radius: 4px; }
"""


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


class LevelMeter(QWidget):
    """Vertical peak meter: the bar jumps up with the sound and falls back slowly (about 20 dB a second), and a
    thin line holds the highest recent peak, so you can see how loud something really was."""

    FALL = 0.011        # bar fall per frame at 30 frames a second, on a 60 dB scale (about 20 dB a second)
    HOLD_FRAMES = 45    # the peak line stays put for 1.5 seconds
    PEAK_FALL = 0.006

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(12)
        self.setMinimumHeight(140)
        self._level = 0.0
        self._peak = 0.0
        self._peak_age = 0
        self._lit: Optional[QPixmap] = None  # the full-height coloured bar with its segment lines, drawn once per size
        self._painted = None  # (bar height, peak line) as last drawn: nothing is repainted unless this changes

    def _shown(self) -> tuple:
        height = self.height()
        return int(height * self._level), (int(height * self._peak) if self._peak > 0.02 else -1)

    def resizeEvent(self, event) -> None:
        self._lit = None
        self._painted = None
        super().resizeEvent(event)

    def _lit_pixmap(self) -> QPixmap:
        if self._lit is None:
            ratio = self.devicePixelRatioF()
            width, height = self.width(), self.height()
            pixmap = QPixmap(int(width * ratio), int(height * ratio))
            pixmap.setDevicePixelRatio(ratio)
            p = QPainter(pixmap)
            gradient = QLinearGradient(0, height, 0, 0)
            gradient.setColorAt(0.00, QColor("#1c9a58"))
            gradient.setColorAt(0.68, QColor("#3ddc84"))
            gradient.setColorAt(0.84, QColor("#f5c542"))
            gradient.setColorAt(1.00, QColor("#ef5258"))
            p.fillRect(QRectF(0, 0, width, height), gradient)
            p.setPen(QColor("#0e1014"))  # thin dark lines give the segmented look
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

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        rect = self.rect()
        p.fillRect(rect, QColor("#0e1014"))
        height = rect.height()
        fill, peak = self._shown()
        if fill > 0:
            top = height - fill + 1
            p.drawPixmap(0, top, self._lit_pixmap(), 0, int(top * self.devicePixelRatioF()),
                         int(rect.width() * self.devicePixelRatioF()), int(fill * self.devicePixelRatioF()))
        if peak >= 0:
            p.setPen(QColor("#e8eef5"))
            p.drawLine(rect.left(), rect.bottom() - peak, rect.right(), rect.bottom() - peak)
        p.end()
        self._painted = (fill, peak)


class Fader(QSlider):
    """Gain fader. Its public value is in tenths of a dB (``gain()``, ``setGain()``, ``gainChanged``); the handle
    follows ``FADER_TAPER``. Double-click resets to 0 dB, the wheel moves 1 dB."""

    gainChanged = Signal(int)

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Vertical)
        self.setRange(0, FADER_STEPS)
        self.setValue(round(db_to_fader_position(0.0) * FADER_STEPS))
        self.setSingleStep(8)
        self.setPageStep(60)
        self.setMinimumHeight(140)
        self.setFixedWidth(34)
        self.setToolTip("Double-click to reset to 0 dB")
        self.valueChanged.connect(lambda _position: self.gainChanged.emit(self.gain()))

    def gain(self) -> int:
        return round(fader_position_to_db(self.value() / FADER_STEPS) * 10)

    def setGain(self, tenths: int) -> None:
        self.setValue(round(db_to_fader_position(tenths / 10.0) * FADER_STEPS))

    def mouseDoubleClickEvent(self, event) -> None:
        self.setGain(0)
        event.accept()

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / 120.0
        self.setGain(max(int(MIN_DB * 10), min(int(MAX_DB * 10), self.gain() + int(round(notches * 10)))))
        event.accept()


class DeviceCombo(QComboBox):
    """Device picker. Item data: '' = system default, NONE_DATA = disabled, else a device name."""

    about_to_show = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)

    def showPopup(self) -> None:
        self.about_to_show.emit()
        super().showPopup()

    def populate(self, devices, current: Optional[str]) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItem("Default", "")
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


class Chip(QFrame):
    """A source on a channel: a device or an app, with a remove button."""

    def __init__(self, text: str, tooltip: str, on_remove) -> None:
        super().__init__()
        self.setObjectName("chip")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 1, 2, 1)
        row.setSpacing(2)
        self.label = QLabel(elide(text, 118, self))
        self.label.setObjectName("chiptext")
        self.label.setToolTip(tooltip or text)
        close = QToolButton()
        close.setText("×")
        close.setToolTip("Remove")
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


class ChannelStrip(QFrame):
    def __init__(self, channel: Channel, engine: Engine, window: "MainWindow") -> None:
        super().__init__()
        self.setObjectName("strip")
        self.setFixedWidth(CHANNEL_WIDTH)
        self.channel, self.engine, self.window = channel, engine, window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        accent = QFrame()
        accent.setObjectName("accent")
        accent.setFixedHeight(4)
        accent.setStyleSheet(f"background: {channel.color};")
        layout.addWidget(accent)

        head = QHBoxLayout()
        self.title = _label(channel.label, "title")
        self.title.setToolTip(f"Also recordable as \u201c{channel.solo_description}\u201d. Double-click to rename"
                              if channel.separate else "Double-click to rename")
        self.title.mouseDoubleClickEvent = lambda _e: self.rename()
        menu_button = QToolButton()
        menu_button.setObjectName("menu")
        menu_button.setText("⋮")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        menu.addAction("Rename…", self.rename)
        self.separate_action = menu.addAction("")
        self.separate_action.setCheckable(True)
        self.separate_action.setToolTip("Offer this channel on its own as a microphone-style input, so OBS, Discord or a game "
                                        "can use just this channel (after its effects). Not needed for the Broadcast mix.")
        self.separate_action.triggered.connect(lambda _checked=False: self.toggle_separate())

        def refresh_menu() -> None:
            self.separate_action.setText(f"Also offer as its own input: \u201c{self.channel.solo_description}\u201d")
            self.separate_action.setChecked(self.channel.separate)

        menu.aboutToShow.connect(refresh_menu)
        refresh_menu()
        menu.addAction("Delete channel", self.delete)
        menu_button.setMenu(menu)
        head.addSpacing(18)
        head.addWidget(self.title, 1)
        head.addWidget(menu_button)
        layout.addLayout(head)

        # Sources: devices and apps feeding this channel.
        layout.addWidget(_label("SOURCES", "tag"))
        self.sources_box = QWidget()
        self.sources_layout = QVBoxLayout(self.sources_box)
        self.sources_layout.setContentsMargins(0, 0, 0, 0)
        self.sources_layout.setSpacing(3)
        self.sources_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(84)
        scroll.setWidget(self.sources_box)
        scroll.setStyleSheet("background: transparent;")
        self.sources_box.setStyleSheet("background: transparent;")
        layout.addWidget(scroll)

        self.add_button = QPushButton("+ Add device or app")
        self.add_button.setObjectName("add")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_menu = QMenu(self.add_button)
        self.add_menu.aboutToShow.connect(self._build_add_menu)
        self.add_button.setMenu(self.add_menu)
        layout.addWidget(self.add_button)

        self.fx_button = QPushButton()
        self.fx_button.clicked.connect(self.open_effects)
        layout.addWidget(self.fx_button)

        self.link = _toggle("LINK", "link", "Move the Monitor and Stream faders together")
        self.link.toggled.connect(self._on_link)
        layout.addWidget(self.link)

        # One fader column per mix.
        self.faders: dict = {}
        self.meters: dict = {}
        self.readouts: dict = {}
        self.mutes: dict = {}
        columns = QHBoxLayout()
        columns.setSpacing(6)
        for mix in engine.mixer.mixes:
            columns.addLayout(self._build_column(mix), 1)
        layout.addLayout(columns, 1)

        self.refresh_sources()
        self.sync_from_model()

    def _build_column(self, mix: Mix) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(4)
        column.addWidget(_label(MIX_TAGS.get(mix.id, mix.label.upper()), "tag"))
        fader, meter = Fader(), LevelMeter()
        fader.gainChanged.connect(partial(self._on_level, mix.id))
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addStretch(1)
        row.addWidget(fader)
        row.addWidget(meter)
        row.addStretch(1)
        column.addLayout(row, 1)
        readout = ReadoutEdit(None)
        readout.setToolTip("Click and type a level in dB (for example -12), then press Enter")
        readout.entered.connect(partial(self._typed_level, mix.id))
        column.addWidget(readout)
        mute = _toggle("M", "mute", f"Mute in the {mix.label} mix")
        mute.toggled.connect(partial(self._on_mute, mix.id))
        column.addWidget(mute)
        self.faders[mix.id], self.meters[mix.id] = fader, meter
        self.readouts[mix.id], self.mutes[mix.id] = readout, mute
        return column

    # ------------------------------------------------------------------ sources
    def refresh_sources(self) -> None:
        while self.sources_layout.count():
            item = self.sources_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for device in self.channel.devices:
            text, tip = self._device_text(device)
            self.sources_layout.addWidget(Chip("\U0001f3a4 " + text, tip, partial(self._remove_device, device)))
        for app in self.channel.apps:
            label = self.engine.app_label(app)
            self.sources_layout.addWidget(Chip("▶ " + label, f"{label}\nApp: {app}", partial(self._remove_app, app)))
        if not self.channel.devices and not self.channel.apps:
            hint = _label("Nothing yet.\nAdd a mic, or an app\nthat should play here.", "hint")
            self.sources_layout.addWidget(hint)
        self._update_fx_button()

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
        self.fx_button.setText("Effects" if count == 0 else f"Effects ({len(active)}/{count} on)")

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
        self.title.setToolTip(f"Also recordable as \u201c{self.channel.solo_description}\u201d. Double-click to rename"
                              if on else "Double-click to rename")

    def _on_link(self, on: bool) -> None:
        self.engine.set_linked(self.channel.id, on)
        self.sync_from_model()

    def sync_from_model(self) -> None:
        channel = self.channel
        widgets = [self.link, *self.faders.values(), *self.mutes.values()]
        for widget in widgets:
            widget.blockSignals(True)
        self.link.setChecked(channel.linked)
        for mix_id, fader in self.faders.items():
            db = channel.levels.get(mix_id, 0.0)
            fader.setGain(round(db * 10))
            self.readouts[mix_id].setText(format_db(db))
            self.mutes[mix_id].setChecked(bool(channel.mutes.get(mix_id)))
        for widget in widgets:
            widget.blockSignals(False)


# ------------------------------------------------------------------------ mixes
class MixStrip(QFrame):
    def __init__(self, mix: Mix, engine: Engine) -> None:
        super().__init__()
        self.setObjectName("mix")
        self.setFixedWidth(MIX_WIDTH)
        self.mix, self.engine = mix, engine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(_label("FOR YOU" if mix.kind == MONITOR else "FOR YOUR AUDIENCE" if mix.id == STREAM else "FOR YOUR RECORDER", "tag"))
        layout.addWidget(_label(mix.label, "title"))

        self.combo: Optional[DeviceCombo] = None
        if mix.kind == MONITOR:
            layout.addWidget(_label("You hear this", "hint"))
            self.combo = DeviceCombo()
            self.combo.activated.connect(self._on_device)
            layout.addWidget(_slot(self.combo))
        else:
            layout.addWidget(_label("Audience hears this" if mix.id == STREAM else "Recorder hears this", "hint"))
            hint = _label(f"Record from\n“{mix.source_description}”", "hint")
            hint.setWordWrap(True)
            layout.addWidget(_slot(hint))

        self.fader, self.meter = Fader(), LevelMeter()
        self.fader.gainChanged.connect(self._on_gain)
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addStretch(1)
        row.addWidget(self.fader)
        row.addWidget(self.meter)
        row.addStretch(1)
        layout.addLayout(row, 1)

        self.hear: Optional[QPushButton] = None
        if mix.kind == MONITOR:
            self.hear = _toggle("Hear Broadcast", "link",
                                "Check what your audience hears: your output plays the Broadcast mix instead of the Listen mix. "
                                "Turn it off to go back. It always starts off.")
            self.hear.toggled.connect(self._on_hear)
            layout.addWidget(self.hear)
        self.readout = ReadoutEdit(None)
        self.readout.setToolTip("Click and type a level in dB (for example -6), then press Enter")
        self.readout.entered.connect(self._typed_gain)
        layout.addWidget(self.readout)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.mute = _toggle("M", "mute", "Mute this whole mix")
        self.limiter = _toggle("LIM", "limiter", "Limiter: stops the mix from clipping")
        self.mute.toggled.connect(lambda on: self.engine.set_master_mute(self.mix.id, on))
        self.limiter.toggled.connect(lambda on: self.engine.set_limiter(self.mix.id, on))
        buttons.addWidget(self.mute)
        buttons.addWidget(self.limiter)
        layout.addLayout(buttons)
        self.sync_from_model()

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

    def populate_devices(self) -> None:
        if self.combo:
            self.combo.populate(self.engine.sinks, self.mix.device)

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


# ------------------------------------------------------------------- apps bar
class AppsBar(QFrame):
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
                item.widget().deleteLater()
        self.row.addWidget(_label("Playing now:", "tag", center=False))
        seen = set()
        for stream in self.engine.streams:
            if stream.key in seen:
                continue
            seen.add(stream.key)
            self.row.addWidget(self._chip(stream))
        if not seen:
            self.row.addWidget(_label("No app is playing sound. Start something and it shows up here.", "hint", center=False))
        self.row.addStretch(1)

    def _chip(self, stream) -> QPushButton:
        owner = self.engine.channel_for_stream(stream)
        button = QPushButton(f"{stream.name}  ›  {owner.label}" if owner else stream.name)
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


class _UpdateBridge(QObject):
    """Carries the answer of the update check from its worker thread back to the window."""

    done = Signal(object)


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
        self.setStyleSheet(STYLE)
        self._keep_settings_file = False  # set after "Import settings": quitting must not overwrite what was imported
        self._build_menus()
        self._update_check = updates.check  # replaced in tests
        self._update_bridge = _UpdateBridge()
        self._update_bridge.done.connect(self._show_update_result)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 6)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.channels_widget = QWidget()
        self.channels_widget.setObjectName("channels")
        self.channels_row = QHBoxLayout(self.channels_widget)
        self.channels_row.setContentsMargins(0, 0, 0, 16)  # air between the strips and the scroll bar
        self.channels_row.setSpacing(8)
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.channels_widget)
        top.addWidget(scroll, 1)

        divider = QFrame()
        divider.setObjectName("divider")
        top.addWidget(divider)
        self.mix_strips = [MixStrip(m, engine) for m in engine.mixer.mixes]
        for strip in self.mix_strips:
            top.addWidget(strip)
        outer.addLayout(top, 1)

        self.apps_bar = AppsBar(engine, self)
        outer.addWidget(self.apps_bar)

        self.strips: list = []
        self.rebuild_channels()

        self.status_label = QLabel(notice or "Ready")
        self.status_label.setObjectName("status")
        self.statusBar().addWidget(self.status_label, 1)
        self.mic_button = QPushButton("Mic live")
        self.mic_button.setCheckable(True)
        self.mic_button.setFlat(True)
        self.mic_button.setToolTip("Mute or unmute every microphone, including the Sluice (Mic) device other apps listen to (Ctrl+M).")
        self.mic_button.clicked.connect(self.toggle_mic_mute)
        self.statusBar().addPermanentWidget(self.mic_button)
        self._show_mic_state()
        self.perf_label = QLabel("")
        self.perf_label.setObjectName("status")
        self.perf_label.setToolTip(
            "A dropout is a moment the audio could not keep up: you may hear a click or a gap.\n"
            "Dropouts while starting or changing effects are not counted. If the number keeps climbing,\n"
            "choose a larger size in View > Audio buffer, or remove heavy effects.")
        self.statusBar().addPermanentWidget(self.perf_label)
        version = QLabel(f"v{__version__}")
        version.setObjectName("status")
        version.setToolTip("The Sluice version you are running. Please include it in bug reports.")
        self.statusBar().addPermanentWidget(version)
        backend = QLabel(engine.io.label)
        backend.setObjectName("demo" if "Demo" in engine.io.label else "status")
        self.statusBar().addPermanentWidget(backend)

        for strip in self.mix_strips:
            if strip.combo:
                strip.combo.about_to_show.connect(self._on_popup)
        self.repopulate_devices()

        self._update_tray()  # the tray icon is there from the start if Sluice is set to run in the tray
        self.resize(1240, 720)
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

    # ------------------------------------------------------------------- menus
    def _action(self, menu: QMenu, text: str, slot, shortcut=None, checkable: bool = False) -> QAction:
        action = menu.addAction(text)
        action.setCheckable(checkable)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
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
        self._action(file_menu, "Open settings &folder", self.open_settings_folder)
        file_menu.addSeparator()
        self.launcher_action = self._action(file_menu, "Add Sluice to the &applications menu", self.toggle_launcher, checkable=True)
        startup = file_menu.addMenu("Start when I &log in")
        group = QActionGroup(self)
        self.autostart_actions = {}
        for key, text in (("off", "Do not start automatically"), ("window", "Start with the window open"),
                          ("minimized", "Start minimized to the taskbar")):
            action = startup.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.triggered.connect(lambda _c=False, key=key: self.set_autostart(key))
            self.autostart_actions[key] = action
        file_menu.aboutToShow.connect(self._refresh_file_menu)
        file_menu.addSeparator()
        closing = file_menu.addMenu("When I &close the window")
        close_group = QActionGroup(self)
        self.close_actions = {}
        for key, text in (("quit", "Quit Sluice"), ("minimize", "Keep running, minimized to the taskbar"),
                          ("tray", "Keep running in the system tray")):
            action = closing.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(close_group)
            action.triggered.connect(lambda _c=False, key=key: self.set_close_action(key))
            self.close_actions[key] = action
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", self.quit_app, QKeySequence.StandardKey.Quit)

        mixer_menu = bar.addMenu("&Mixer")
        self._action(mixer_menu, "&Add channel\u2026", self.add_channel, "Ctrl+N")
        self._action(mixer_menu, "&Recording devices for OBS\u2026", self.show_own_devices)
        mixer_menu.addSeparator()
        self.mic_action = self._action(mixer_menu, "Mute my &microphone", self.toggle_mic_mute, "Ctrl+M", checkable=True)
        self.hear_action = self._action(mixer_menu, "&Hear Broadcast", self.toggle_hear_broadcast, "Ctrl+B", checkable=True)
        self.mute_actions = {}
        for mix in self.engine.mixer.mixes:
            shortcut = {MONITOR: "Ctrl+Shift+L", STREAM: "Ctrl+Shift+B"}.get(mix.id, "")
            self.mute_actions[mix.id] = self._action(mixer_menu, f"&Mute {mix.label}", partial(self.toggle_mix_mute, mix.id),
                                                     shortcut, checkable=True)
        mixer_menu.addSeparator()
        self.recording_action = self._action(mixer_menu, "Third mix: &Recording\u2026", self.toggle_recording_mix, checkable=True)
        self._action(mixer_menu, "&Refresh devices and apps", self.refresh_now, "F5")
        mixer_menu.aboutToShow.connect(self._refresh_mixer_menu)

        view_menu = bar.addMenu("&View")
        self.fullscreen_action = self._action(view_menu, "&Full screen", self.toggle_fullscreen, "F11", checkable=True)
        self._action(view_menu, "&Reset window size", self.reset_window_size)
        view_menu.addSeparator()
        buffer_menu = view_menu.addMenu("Audio &buffer")
        self.buffer_actions = {}
        labels = {256: "Smallest (256 frames): lowest delay, most CPU", 512: "Small (512 frames): the default",
                  1024: "Large (1024 frames): less CPU", 2048: "Largest (2048 frames): least CPU, most delay"}
        for frames in BUFFER_CHOICES:
            self.buffer_actions[frames] = self._action(buffer_menu, labels[frames], partial(self.set_buffer, frames), checkable=True)
        buffer_menu.aboutToShow.connect(self._refresh_buffer_menu)
        view_menu.aboutToShow.connect(lambda: self.fullscreen_action.setChecked(self.isFullScreen()))

        self.help_menu = bar.addMenu("&Help")  # Controllers is inserted before this one by attach_controls()
        self._action(self.help_menu, "&Keyboard shortcuts", self.show_shortcuts, "F1")
        self.help_menu.addSeparator()
        self.help_menu.addAction("What's new in this version\u2026", self.show_whats_new)
        self.help_menu.addAction("Check for updates\u2026", self.check_for_updates)
        self.help_menu.addAction("Save bug report\u2026", self.save_report)
        self.help_menu.addAction("Open log folder", self.open_log_folder)
        self.help_menu.addSeparator()
        self.help_menu.addAction(f"About Sluice {__version__}", self.show_about)

    def _refresh_mixer_menu(self) -> None:
        self.hear_action.setChecked(self.engine.hear_broadcast)
        self.mic_action.setChecked(self.engine.mic_muted)
        self.recording_action.setChecked(self.engine.mixer.has_recording_mix)
        for mix_id, action in self.mute_actions.items():
            action.setChecked(self.engine.mixer.mix(mix_id).mute)

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
        reconnect.restart_self()

    def toggle_mic_mute(self) -> None:
        self.engine.set_mic_muted(not self.engine.mic_muted)  # from the real state, like the other toggles
        self._show_mic_state()
        if self._tray is not None and self._tray.isVisible():
            self._tray.setToolTip("Sluice" + (" (microphone muted)" if self.engine.mic_muted else ""))
        self.say("Your microphone is muted everywhere, including Sluice (Mic)." if self.engine.mic_muted
                 else "Your microphone is live.")

    def _show_mic_state(self) -> None:
        muted = self.engine.mic_muted
        self.mic_button.blockSignals(True)
        self.mic_button.setChecked(muted)
        self.mic_button.blockSignals(False)
        self.mic_button.setText("MIC MUTED" if muted else "Mic live")
        self.mic_button.setStyleSheet("QPushButton { background: #b3262c; color: white; border: none; padding: 1px 8px; }" if muted
                                      else "QPushButton { border: none; padding: 1px 8px; color: #8fd19e; }")

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
        self.resize(1240, 720)

    def show_shortcuts(self) -> None:
        rows = [("Ctrl+S", "Save settings"), ("Ctrl+N", "Add a channel"), ("Ctrl+B", "Hear Broadcast on or off"),
                ("Ctrl+Shift+L", "Mute or unmute Listen"), ("Ctrl+Shift+B", "Mute or unmute Broadcast"),
                ("F5", "Refresh devices and apps"), ("F11", "Full screen"), ("F1", "This list"), ("Ctrl+Q", "Quit")]
        table = "".join(f"<tr><td><b>{key}</b>&nbsp;&nbsp;&nbsp;</td><td>{what}</td></tr>" for key, what in rows)
        QMessageBox.information(self, "Keyboard shortcuts", f"<table>{table}</table><br>"
                                "Faders: scroll the mouse wheel over one, or use the arrow keys when it is selected.<br>"
                                "For buttons and knobs outside the app, see <b>Controllers</b>.")

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
        self.say(f"Settings exported to {path}.")

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
        menu = QMenu("&Controllers", self)
        menu.addAction("MIDI controllers and Stream Deck\u2026", controls.show_dialog)
        self.menuBar().insertMenu(self.help_menu.menuAction(), menu)  # File, Mixer, View, Controllers, Help

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
        while self.channels_row.count():
            item = self.channels_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.strips = [ChannelStrip(c, self.engine, self) for c in self.engine.mixer.channels]
        for strip in self.strips:
            self.channels_row.addWidget(strip)
        add = QPushButton("+\nAdd channel")
        add.setObjectName("addchannel")
        add.setFixedWidth(124)
        add.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self.add_channel)
        self.channels_row.addWidget(add)
        self.channels_row.addStretch(1)

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
        self.perf_label.setText(self.engine.status_text())

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
            f"Log: {logs.log_path()}",
        )

    def check_for_updates(self) -> None:
        self.say("Checking for updates...")
        check = self._update_check

        def work() -> None:
            self._update_bridge.done.emit(check(__version__))

        threading.Thread(target=work, name="sluice-update-check", daemon=True).start()

    # -------------------------------------------------------------- what's new
    def show_notes(self, title: str, heading: str, markdown: str, main_label: str = "", main_url: str = "") -> None:
        from .ui_whatsnew import NotesDialog

        self._notes_dialog = NotesDialog(title, heading, markdown, main_label, main_url, self)
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
            self.show_notes(
                "Update available", f"Sluice {result.latest} is available. You are running {result.current}.",
                result.notes or "No release notes were published for this version.",
                "Open download page" if result.page else "", result.page)
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
        self.status_label.setText(f"Bug report saved to {written}. Look it over before sharing it.")

    def save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save bug report", str(Path.home() / "sluice-report.txt"), "Text files (*.txt)"
        )
        if path:
            try:
                self.save_report_to(path)
            except OSError as exc:
                QMessageBox.warning(self, "Could not save the report", str(exc))

    def open_log_folder(self) -> None:
        folder = logs.state_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ---------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
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
