# SPDX-License-Identifier: GPL-3.0-or-later
"""The channel cards (Columns and Rows), their source chips, the own-devices dialog and the apps bars."""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import ui_dialog
from . import themes, ui_icons as icons
from .engine import Engine
from .model import Channel, MAX_DB, MIN_DB, Mix
from .ui_base import (
    _icon_button,
    _is_tile,
    _label,
    channel_width,
    COLUMN_WIDTH,
    elide,
    ElidedLabel,
    EMPTY_HINTS,
    LEVEL_HELP,
    MIX_NAMES,
    MIX_TAGS,
    mute_tip,
    ReadoutEdit,
    ROW_CELL_MIN,
    ROW_NAME_WIDTH,
    ROW_TOOLS_WIDTH,
    SOURCES_HEIGHT,
    SOURCES_MIN,
    short_device_name,
)
from .ui_effects import EffectsDialog
from .ui_meters import Fader, LevelMeter, SourcePicture

if TYPE_CHECKING:  # only for type hints: the window imports this module
    from .ui_window import MainWindow

log = logging.getLogger("sluice.ui")
PAIR_GAP = 12  # between a fader and its meter


class Chip(QFrame):
    """A source on a channel: a device or an app (with its picture), and a remove button."""

    def __init__(self, text: str, tooltip: str, on_remove, picture: Optional[SourcePicture] = None) -> None:
        super().__init__()
        self.setObjectName("sourcechip")
        self.setFixedHeight(32)
        row = QHBoxLayout(self)
        row.setContentsMargins(*(8, 0, 4, 0))
        row.setSpacing(8)
        self.picture = picture
        if picture is not None:
            row.addWidget(picture)
        self.label = QLabel(elide(text, (88 if picture is not None else 120), self))
        self.label.setObjectName("chiptext")
        self.label.setToolTip(tooltip or text)
        close = QToolButton()
        close.setObjectName("remove")
        close.setIcon(icons.themed_icon("x", "text_dim"))  # 0.12.2: drawn, not a typed ×
        close.setIconSize(QSize(14, 14))
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
    return (
        f"\u201c{channel.solo_description}\u201d is now available in OBS and other recorders. It carries only "
        f"{channel.label}, after its effects, and does not follow the faders or mute buttons."
    )


class OwnDevicesDialog(QDialog):
    """One list of channels with a tick for each one that should also be its own recording device."""

    def __init__(self, engine: Engine, window: "MainWindow") -> None:
        super().__init__(window)
        self.engine, self.window_ = engine, window
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Each ticked channel can be recorded on its own, so OBS can have one source per channel (your mic on one, the "
            "game on another). Each carries only that channel, after its effects.\n\n"
            "In OBS, choose \u201cSluice (Game) for OBS\u201d (Audio Output Capture) or \u201cSluice (Game)\u201d (Audio "
            "Input Capture)."
            + (
                " Not \u201cPlay to Sluice (Game)\u201d: that is where apps play in, before the faders."
                if engine.mixer.show_play_to_devices
                else ""  # 0.13.1-beta.2: hidden, so it cannot be picked by mistake
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        # 0.12.4: an app channel's device follows its Broadcast fader and mute, so muting Broadcast mutes it in OBS too
        self.follow = QCheckBox("App channels follow their Broadcast fader and mute (and the whole Broadcast's)")
        self.follow.setToolTip(
            "On: what OBS records from \u201cSluice (Game)\u201d is what Broadcast would send. Off: always at "
            "full level, and you set the level in OBS.\nA microphone's device is never muted by Broadcast, "
            "because a voice chat such as Discord often uses it too; \u201cMute my microphone\u201d mutes it."
        )
        self.follow.setChecked(engine.mixer.devices_follow_broadcast)
        self.follow.toggled.connect(window.set_devices_follow_broadcast)
        layout.addWidget(self.follow)
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
        from .ui_dialog import card_panel  # 0.12.2: a panel from the menu, not a separate window

        card_panel(self, "Recording devices for OBS")

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


class CardFrame(QFrame):
    """0.13.1: a card that shows small corner brackets in the accent while it, or a control on it, has the keyboard focus
    (House Standard v1.3; the Tile look draws its own)."""

    def __init__(self) -> None:
        super().__init__()
        self._focused = False
        app = QApplication.instance()
        if app is None:
            return
        import weakref

        card = weakref.ref(self)

        def moved(_old, new) -> None:  # a plain function, not a method: it outlives the card harmlessly
            frame = card()
            if frame is None:
                return
            try:
                inside = new is not None and (new is frame or frame.isAncestorOf(new))
                if inside != frame._focused:
                    frame._focused = inside
                    frame.update()
            except RuntimeError:  # the card is gone
                pass

        app.focusChanged.connect(moved)
        self.destroyed.connect(lambda *_a: CardFrame._forget(app, moved))

    @staticmethod
    def _forget(app, slot) -> None:
        try:
            app.focusChanged.disconnect(slot)
        except (RuntimeError, TypeError, SystemError):
            pass

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._focused:
            from .ui_tile_paint import paint_brackets

            p = QPainter(self)
            paint_brackets(p, QRectF(self.rect()), themes.color("accent"), radius=12)  # (the card's own corner)
            p.end()


class ChannelStrip(QWidget):
    """One channel: a card in the Columns layout (faders side by side) or a row in the Rows layout (sliders along the row)."""

    def __init__(self, channel: Channel, engine: Engine, window: "MainWindow", rows: bool = False) -> None:
        super().__init__()
        self.setObjectName("channelstrip")
        self.rows = rows
        self.ring = None  # (the Nexus look's ring meter, retired in 0.13.1)
        mixes = len(engine.mixer.mixes)
        self.channel, self.engine, self.window = channel, engine, window
        if (
            getattr(self, "tint", None) is None
        ):  # the channel's identity colour, as drawn on this theme (the Tile look has its own set)
            self.tint = self._theme_tint()
        self.compact = mixes > 2  # three fader columns share the strip
        self.faders: dict = {}
        self.meters: dict = {}
        self.readouts: dict = {}
        self.mutes: dict = {}
        self._empty = False

        self.frame = self._make_frame(rows)
        if not rows:
            self.setFixedWidth(channel_width(mixes))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)
        self.layout_root = QVBoxLayout(self.frame) if not rows else QHBoxLayout(self.frame)
        if rows:
            self.layout_root.setContentsMargins(24, 8, 24, 16 if _is_tile() else 8)  # Tile: room for the key's skirt
            self.layout_root.setSpacing(16)
        else:
            self.layout_root.setContentsMargins(16, 16, 16, 16)
            self.layout_root.setSpacing(16)

        self.title = ElidedLabel(
            channel.label
        )  # a long name ends in an ellipsis instead of being cut off; the tooltip has it whole
        self.title.setObjectName("name")
        self.title.setToolTip(self._title_tip())
        self.title.mouseDoubleClickEvent = lambda _e: self.rename()
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.dot.setStyleSheet(f"background: {self.tint}; border-radius: 6px;")
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
    def _make_frame(self, rows: bool) -> QFrame:
        """The card behind the controls (the Tile look paints its own: see ui_tile.TileStrip)."""
        if rows:
            return RowCard(self.tint)
        frame = CardFrame()
        frame.setObjectName("strip")
        return frame

    def _title_tip(self) -> str:
        c = self.channel
        return (
            f"{c.label}\nAlso recordable as “{c.solo_description}”. Double-click to rename"
            if c.separate
            else f"{c.label}\nDouble-click to rename"
        )

    def _build_options_menu(self) -> None:
        menu = self.menu
        self.add_menu.setTitle("Add app or device")
        menu.addMenu(self.add_menu)
        menu.addAction("Rename…", self.rename)
        self.separate_action = menu.addAction("")
        self.separate_action.setCheckable(True)
        self.separate_action.setToolTip(
            "Offer this channel on its own as a microphone-style input, so OBS, Discord or a game "
            "can use just this channel (after its effects). Not needed for the Broadcast mix."
        )
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
        self.link_badge = None
        # 0.12.2: a tinted icon tile with the channel's drawing, instead of a coloured dot
        from . import skin_tile
        from .ui_tile_paint import IconWell

        self.well = IconWell(self.tint, skin_tile.channel_icon(self.channel), self.channel.label, 32)
        self.dot.hide()
        head.addWidget(self.well)
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
        layout.addWidget(
            self.add_button
        )  # always in view, under the list: however many sources there are, adding one is one click

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
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(PAIR_GAP)
            inner.addStretch(1)  # 0.12.0: the fader and its meter as one pair, centred under the mix's name and over its level
            inner.addWidget(fader)
            inner.addWidget(meter)
            inner.addStretch(1)
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
        readout.setAccessibleName(f"{self.channel.label}, {mix.label} level")
        readout.setToolTip(LEVEL_HELP.strip())
        readout.wheel_steps = True
        readout.levels = True
        readout.wheeled.connect(partial(self._wheel_level, mix.id))
        readout.entered.connect(partial(self._typed_level, mix.id))
        mute = QPushButton("")
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
    def _theme_tint(self) -> str:
        """The channel's colour on the theme in use: darker shades of it on light themes, so it stands out (0.11.5)."""
        from . import depth, skin_tile

        if _is_tile():
            return skin_tile.channel_color(self.channel)
        return depth.channel_tint(self.channel.color, themes._current)

    def _retint(self) -> None:
        tint = self._theme_tint()
        if tint == self.tint:
            return
        self.tint = tint
        self.dot.setStyleSheet(f"background: {tint}; border-radius: 6px;")
        if getattr(self, "well", None) is not None and not _is_tile():
            self.well.color = tint
            self.well.update()
        if getattr(self, "accent_bar", None) is not None:
            self.accent_bar.setStyleSheet(f"background: {tint};")

    def refresh_theme(self) -> None:
        """Icons and the few colours set in code, from the theme in use."""
        self._retint()
        own = self.tint if themes.current_skin() == "calm" else None  # 0.12.2: meters in the channel's colour
        for meter in self.meters.values():
            if hasattr(meter, "set_tint"):
                meter.set_tint(own)
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
                    widget.hide()  # hidden at once: the old chips must not show for the moment before they are deleted
                    widget.deleteLater()
            if not self.channel.devices and not self.channel.apps:
                nothing = QLabel("Nothing here yet")
                nothing.setObjectName("hint")
                self.sources_layout.addWidget(nothing)
            for device in self.channel.devices:
                text, tip = self._device_text(device)
                self.sources_layout.addWidget(
                    Chip(text, tip + "\nInput device", partial(self._remove_device, device), SourcePicture(text, device=True))
                )
            for app in self.channel.apps:
                label = self.engine.app_label(app)
                self.sources_layout.addWidget(
                    Chip(
                        label,
                        f"{label}\nApp: {app}",
                        partial(self._remove_app, app),
                        SourcePicture(label, self.engine.app_icon(app), app),
                    )
                )
        self._update_fx_button()
        self.show_mic_state()
        even = getattr(self.window, "even_sources", None)
        if even is not None and not self.rows:
            even()

    def sources_needed(self) -> int:
        """0.12.0: how tall this card's list of sources wants to be: its chips (32 px, 8 apart), from one chip's height up to
        SOURCES_HEIGHT, past which it scrolls."""
        count = len(self.channel.devices) + len(self.channel.apps)
        return max(SOURCES_MIN, min(SOURCES_HEIGHT, count * 32 + max(0, count - 1) * 8))

    def set_sources_height(self, height: int) -> None:
        if not self.rows and getattr(self, "sources_scroll", None) is not None and self.sources_scroll.height() != height:
            self.sources_scroll.setFixedHeight(height)

    def _sources_summary(self) -> str:
        names = [self._device_text(d)[0] for d in self.channel.devices] + [self.engine.app_label(a) for a in self.channel.apps]
        return ", ".join(names) if names else "Nothing here yet"

    def show_mic_state(self) -> None:
        has_mic = bool(self.channel.devices)
        muted = self.engine.mic_muted
        self.mic_button.setVisible(has_mic)
        if getattr(self, "link_badge", None) is not None:
            self.link_badge.setVisible(self.channel.linked and not has_mic)
        self.mic_button.blockSignals(True)
        self.mic_button.setChecked(muted)
        self.mic_button.blockSignals(False)
        self.mic_button.setIcon(icons.icon("mic_off" if muted else "mic", themes.color("mute_fg" if muted else "text2"), 20))
        self.mic_button.setIconSize(QSize(20, 20))
        self.mic_button.setToolTip(
            "Microphones are muted. Click to unmute every microphone (Ctrl+M)."
            if muted
            else "Microphone is live. Click to mute every microphone, including the Sluice (Mic) device "
            "other apps listen to (Ctrl+M)."
        )
        self.mic_button.setAccessibleName("Unmute microphones" if muted else "Mute microphones")

    def _device_text(self, device: str) -> tuple:
        if device == "":
            return "Default mic", "Follows the system default microphone"
        for d in self.engine.sources:
            if d.name == device:
                return short_device_name(
                    d.description
                ), f"{d.description}\n{device}"  # 0.12.0: short on the card, whole in the tip
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
            action = devices.addAction(short_device_name(d.description), partial(self._add_device, d.name))
            action.setToolTip(d.description)
            action.setEnabled(d.name not in self.channel.devices)

        monitors = [d for d in engine.sources if d.monitor]
        if monitors:
            loops = {engine.resolve_mix_sink(m) for m in engine.mixer.mixes}
            heard = menu.addMenu("Sound playing on an output device")
            for d in monitors:
                node = d.name[: -len(".monitor")]
                action = heard.addAction(
                    d.description + ("  (your own output: would loop)" if node in loops else ""),
                    partial(self._add_device, d.name),
                )
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
        dialog = AppPickerDialog(
            self.engine.catalog, self.channel.label, owner_of, self, running=running, anchor=getattr(self, "add_button", None)
        )
        if dialog.exec():
            for key in dialog.selected_keys():
                self.engine.assign_app(key, self.channel.id)
            self.window.refresh_sources()

    # ------------------------------------------------------------------ actions
    def rename(self) -> None:
        text, ok = QInputDialog.getText(self, "Rename channel", "Name:", text=self.channel.label)
        if ok and text.strip():
            name, problem = self.window.channel_name(text, renaming=self.channel.id)
            if problem:
                self.window.say(problem)
                return
            self.engine.rename_channel(self.channel.id, name)
            if len(text.strip()) > len(name):
                self.window.say(f"Renamed to \u201c{name}\u201d (the name was shortened to 24 characters).")
            self.title.setText(self.channel.label)
            self.title.setToolTip(self._title_tip())
            self.window.refresh_sources()

    def delete(self) -> None:
        answer = ui_dialog.question(
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
        self.fx_button.setText(
            "Effects"
            if count == 0
            else (f"{count} effect" if count == 1 else f"{count} effects")
            if len(active) == count
            else f"{len(active)} of {count} on"
        )
        self.fx_button.setToolTip(
            "Open this channel's effects"
            if count == 0
            else f"Open this channel's effects: {len(active)} of {count} {'is' if count == 1 else 'are'} on"
        )

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
        levels = dict(self.channel.levels)
        self.engine.set_linked(self.channel.id, on)
        if on and len(set(round(v, 1) for v in levels.values())) > 1:  # 0.13.1-beta.3: the jump is said, not silent
            from .ui_base import format_db

            self.window.say(
                f"{self.channel.label}: linked. Broadcast now follows Listen, at {format_db(self.channel.levels.get('monitor', 0.0))} "
                "(unlink to set them apart again)."
            )
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
            self.readouts[mix_id].show_level(db, narrow=_is_tile())
            self.mutes[mix_id].setChecked(bool(channel.mutes.get(mix_id)))
        for widget in widgets:
            widget.blockSignals(False)
        for mix in self.engine.mixer.mixes:
            self._show_mute(mix)
        self.show_mic_state()
        if getattr(self, "link_badge", None) is not None:  # (a mic channel has its mic button there; its Link button says it)
            self.link_badge.setPixmap(icons.icon("link", themes.color("accent"), 16).pixmap(16, 16))
            self.link_badge.setVisible(channel.linked and not self.mic_button.isVisibleTo(self))
        node = getattr(self, "node", None)
        if node is not None:
            node.refresh()


# ------------------------------------------------------------------- playing now
class AppsBar(QPushButton):
    """ "Playing now · 3": a button that lists the apps making sound and lets you choose the channel each one plays into."""

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

    def _outside(self) -> list:
        """0.12.4: apps that played outside every channel in the last minutes, newest first (playing or not now)."""
        playing = {s.assign_key for s in self._streams()}
        recent = getattr(self.engine, "recent_unassigned", {})
        return [
            (key, name, key in playing)
            for key, (name, _seen) in sorted(recent.items(), key=lambda item: -item[1][1])
            if self.engine.mixer.channel_for_app(key) is None
        ]

    def refresh(self) -> None:
        count = len(self._streams())
        outside = len(self._outside())
        text = f"Playing now · {count}" if count else "Playing now"
        if outside:
            text += f" · {outside} not on a channel"
        self.setText(text)
        self.setToolTip(
            "Which apps are playing and which channel each one is on"
            + (
                f"\n{outside} app(s) played outside every channel lately, so no fader or mute reaches them: click to put them "
                "on one."
                if outside
                else ""
            )
        )

    def _fill(self) -> None:
        menu = self.menu
        menu.clear()
        streams = self._streams()
        outside = [(key, name) for key, name, playing in self._outside() if not playing]
        if not streams and not outside:
            menu.addAction("No app is playing sound. Start something and it shows up here.").setEnabled(False)
        if outside:  # 0.12.4: ones that played lately outside every channel (alerts, say), to put on a channel after the fact
            heading = menu.addAction("Played lately, not on a channel (no fader reaches them)")
            heading.setEnabled(False)
            for key, name in outside:
                sub = menu.addMenu(f"{name}  ›  not on a channel")
                sub.setIcon(QIcon(icons.app_pixmap(self.engine.app_icon(key), name, 20, self.devicePixelRatioF(), key)))
                for channel in self.engine.mixer.channels:
                    sub.addAction(channel.label, partial(self._assign, key, channel.id))
            menu.addSeparator()
        for stream in streams:
            owner = self.engine.channel_for_stream(stream)
            sub = menu.addMenu(f"{stream.name}  ›  {owner.label}" if owner else f"{stream.name}  ›  not on a channel")
            sub.setIcon(
                QIcon(
                    icons.app_pixmap(
                        self.engine.app_icon(stream.assign_key), stream.name, 20, self.devicePixelRatioF(), stream.assign_key
                    )
                )
            )
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
