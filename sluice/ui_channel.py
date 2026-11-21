# SPDX-License-Identifier: GPL-3.0-or-later
"""The channel cards (Columns and Rows), their source chips, the own-devices dialog and the apps bars."""
from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from . import themes, ui_icons as icons
from .engine import Engine
from .model import Channel, MAX_DB, MIN_DB, Mix
from .ui_base import (
    _icon_button, _is_nexus, _is_original, _is_tile, _label, _slot, _toggle, channel_width, COLUMN_WIDTH, elide, ElidedLabel,
    EMPTY_HINTS, format_db, MIC_ROW, MIX_NAMES, MIX_TAGS, mute_tip, ORIGINAL_SOURCES_HEIGHT, ReadoutEdit, ROW_CELL_MIN, ROW_NAME_WIDTH,
    ROW_TOOLS_WIDTH, SOURCES_HEIGHT,
)
from .ui_effects import EffectsDialog
from .ui_meters import Fader, LevelMeter, NexusRing, SourcePicture

if TYPE_CHECKING:  # only for type hints: the window imports this module
    from .ui_window import MainWindow

log = logging.getLogger("sluice.ui")


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






class RowCard(QFrame):
    """A channel row of the Rows layout: a card with a bar in the channel's colour along its left edge."""

    def __init__(self, color: str) -> None:
        super().__init__()
        self.setObjectName("row")
        self.bar_color = color
        self.key = None
        if _is_tile():
            from .ui_tile_paint import KeyBackground
            self.key = KeyBackground((4, 1, 4, 8), radius=16)

    def paintEvent(self, event) -> None:
        if self.key is not None:  # the Tile look: a raised key with a short bar in the channel's colour, not a full-height one
            p = QPainter(self)
            self.key.draw(self, p)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.bar_color))
            face = self.key.face_rect(self)
            p.drawRoundedRect(QRectF(face.left() + 10, face.center().y() - 14, 5, 28), 2.5, 2.5)
            p.end()
            return
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)
        p.setClipPath(shape)
        p.fillRect(QRectF(0, 0, 8, self.height()), QColor(self.bar_color))
        p.end()




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
        if getattr(self, "tint", None) is None:  # the channel's identity colour, as drawn on this theme (the Tile look has its own set)
            self.tint = self._theme_tint()
        self.compact = mixes > 2  # three fader columns share the strip
        self.faders: dict = {}
        self.meters: dict = {}
        self.readouts: dict = {}
        self.mutes: dict = {}
        self._empty = False

        self.frame = self._make_frame(rows)
        if self.nexus:  # glass: a top edge in the channel's colour
            from .ui_nexus import glass_edge_sheet
            self.frame.setStyleSheet(glass_edge_sheet("strip", self.tint))
        if not rows:
            self.setFixedWidth(channel_width(mixes))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)
        self.layout_root = QVBoxLayout(self.frame) if not rows else QHBoxLayout(self.frame)
        if rows:
            self.layout_root.setContentsMargins(24, 8, 24, 16 if _is_tile() else 8)  # Tile: room for the key's skirt
            self.layout_root.setSpacing(16)
        elif self.original:
            self.layout_root.setContentsMargins(8, 8, 8, 8)
            self.layout_root.setSpacing(6)
        else:
            self.layout_root.setContentsMargins(16, 16, 16, 16)
            self.layout_root.setSpacing(16)

        self.title = ElidedLabel(channel.label)  # a long name ends in an ellipsis instead of being cut off; the tooltip has it whole
        self.title.setObjectName("title" if self.original else "name")
        if self.original:
            self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setToolTip(self._title_tip())
        self.title.mouseDoubleClickEvent = lambda _e: self.rename()
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.dot.setStyleSheet(f"background: {self.tint}; border-radius: 6px;")

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
    def _make_frame(self, rows: bool) -> QFrame:
        """The card behind the controls (the Tile look paints its own: see ui_tile.TileStrip)."""
        if rows:
            return RowCard(self.tint)
        frame = QFrame()
        frame.setObjectName("strip")
        return frame

    def _title_tip(self) -> str:
        c = self.channel
        return (f"{c.label}\nAlso recordable as “{c.solo_description}”. Double-click to rename" if c.separate
                else f"{c.label}\nDouble-click to rename")

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
            self.ring = NexusRing(self.tint, self._ring_picture)
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
        accent.setStyleSheet(f"background: {self.tint};")
        self.accent_bar = accent
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
        layout.setContentsMargins(24, 8, 24, 16 if _is_tile() else 8)
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
        fader.set_fill(self.tint)
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
    def _theme_tint(self) -> str:
        """The channel's colour on the theme in use: darker shades of it on light themes, so it stands out (0.11.5)."""
        from . import depth, look_tile
        if _is_tile():
            return look_tile.channel_color(self.channel)
        return depth.channel_tint(self.channel.color, themes._current)

    def _retint(self) -> None:
        tint = self._theme_tint()
        if tint == self.tint:
            return
        self.tint = tint
        self.dot.setStyleSheet(f"background: {tint}; border-radius: 6px;")
        if getattr(self, "accent_bar", None) is not None:
            self.accent_bar.setStyleSheet(f"background: {tint};")
        if self.ring is not None:
            self.ring.set_color(tint)
        if self.nexus:
            from .ui_nexus import floor_of, glass_edge_sheet
            self.frame.setStyleSheet(glass_edge_sheet("strip", tint))
            floor = floor_of(self)
            if floor is not None:
                floor.set_color(self, tint)

    def refresh_theme(self) -> None:
        """Icons and the few colours set in code, from the theme in use."""
        self._retint()
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
            self.title.setToolTip(self._title_tip())
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
