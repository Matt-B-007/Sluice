# SPDX-License-Identifier: GPL-3.0-or-later
"""The Tile look's channel tiles (chosen direction, 2026-11-19).

A folded tile is 264 x 192: a header (tinted icon well, name, source line, link toggle, overflow menu), one lane for each mix
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

Everything here paints with the theme's colours (``skin_tile.paint_colors``) and caches what it can: a tile's surface, shadow and
focus halo are one pixmap, redrawn only when its size, focus or theme changes."""
from __future__ import annotations

import time
from functools import partial
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import skin_tile, themes, ui_icons as icons
from .flow import FlowLayout
from .model import MIN_DB
from .ui_base import db_to_fader_position, ElidedLabel, EMPTY_HINTS, LEVEL_HELP, level_fraction, mute_tip, ReadoutEdit
from .ui_channel import ChannelStrip
from .ui_meters import Fader, SourcePicture
from .ui_tile_paint import (
    _HANDLES, CLIP_HOLD, CLIP_NOTE, face_gradient, frame_of, IconWell, LANE_EXTRA_H, OPEN_W, PAD, paint_groove, paint_handle, paint_leds,
    SCALE_MARKS, SHADOW, SKIRT, stripe_brush, TileFrame,
)


TILE_W, TILE_H = 264, 192      # a folded tile (0.11.7: 40 px shorter, no empty band above the footer)


# ----------------------------------------------------------------------------- the track: fader and meter in one
class TileLane(Fader):
    """One lane's track: the fader and the meter in one. A soft fill up to the handle is the fader position; a brighter fill is the
    live signal (on the fader's own scale, so a full-scale signal through a fader at 0 dB reaches the handle); a thin tick holds
    the peak. Muted: striped, with a grey handle. Clipping: a red tick and a red outline. Keyboard, wheel and double-click work as
    on every Sluice fader. Repaints only when what it shows changes."""

    # (0.12.3: the bar's fall is ui_meters.fall, in seconds, as LevelMeter's)

    def __init__(self, color: str, on_clip=None) -> None:
        super().__init__(horizontal=True, thumb=(14, 20))
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
        self.thumb = (16, 24) if on else (14, 20)
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
        from .ui_meters import fall
        fall(self, frac)
        if self._shown() != self._painted:  # a silent, settled track costs nothing
            self.update()

    def _led_marks(self) -> tuple:
        """Where the segments turn amber (-12 dB) and red (-3 dB), on the live signal's scale."""
        return self._x_for(-12.0), self._x_for(-3.0)

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
            q.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
            background = face_gradient(self, frame)
            if background is not None:
                q.fillRect(QRectF(0, 0, self.width(), self.height()), background)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(stripe_brush(pc["track"], pc["stripe"]) if self.muted else QColor(pc["track"]))
            q.drawPath(shape)
            if not self.muted:  # 0.12.2: the unlit LED segments, all along the groove
                paint_leds(q, track, track.right(), pc, False, *self._led_marks())
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
        key = (tw, th, ratio, themes.generation(), self.muted, self.fill_color)
        cached = _HANDLES.get(key)
        if cached is None:
            room = 3
            pixmap = QPixmap(int((tw + 2 * room) * ratio), int((th + 2 * room) * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_handle(q, QRectF(room, room, tw, th), pc, self.muted, line=self.fill_color)
            q.end()
            cached = (pixmap, room)
            if len(_HANDLES) > 32:
                _HANDLES.clear()
            _HANDLES[key] = cached
        return cached

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
        pc = skin_tile.paint_colors()
        track = self._track_rect()
        radius = track.height() / 2.0
        shape = QPainterPath()
        shape.addRoundedRect(track, radius, radius)
        base, overlay = self._base_and_overlay(pc, track, shape)
        p.drawPixmap(0, 0, base)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = float(round(self._centre()))
        live, peak, clipping = self._shown()
        if not self.muted:  # 0.12.2: the fader's position as a thin line in the channel's colour, the live signal as lit LEDs
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.fill_color))
            p.drawRoundedRect(QRectF(track.left() + 2, track.bottom() - 2.5, max(0.0, centre - track.left() - 2), 1.6), 0.8, 0.8)
            if live >= 0:
                paint_leds(p, track, live, pc, True, *self._led_marks())
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
            p.drawRoundedRect(thumb.adjusted(-2.5, -2.5, 2.5, 2.5), 5.5, 5.5)
        p.end()
        self._painted = (live, peak, clipping)

    _scale_font = None

    def _paint_scale(self, p: QPainter, track: QRectF, pc: dict) -> None:
        if TileLane._scale_font is None:
            font = QFont(skin_tile.VALUE_FAMILIES[0])
            font.setFamilies(skin_tile.VALUE_FAMILIES)
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
        p.setPen(QPen(QColor(skin_tile.paint_colors()["text2"]), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap,
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
        from .ui_meters import FALL_PER_S, elapsed
        frac = level_fraction(linear)
        self._level = max(frac, self._level - FALL_PER_S * elapsed(self))
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
        pc = skin_tile.paint_colors()
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

    def __init__(self, channel, engine, window) -> None:
        self.tint = skin_tile.channel_color(channel)
        self.expanded = channel.id in getattr(window, "tile_open", set())  # the tiles you folded out stay so across rebuilds
        self._clip_at: Optional[float] = None
        self._ticks = 0
        self._playing: set = set()
        self.app_meters: list = []
        self.lane_rows: dict = {}
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
        self.well = IconWell(self.tint, skin_tile.channel_icon(channel), channel.label)
        grip.addWidget(self.well)
        self.lcd = QFrame()  # 0.12.2: the name and source sit on a small LCD
        self.lcd.setObjectName("tilelcd")
        self.lcd.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts = QVBoxLayout(self.lcd)
        texts.setContentsMargins(8, 2, 8, 3)
        texts.setSpacing(0)
        self.title.setObjectName("tilename")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.source_line = ElidedLabel("")
        self.source_line.setObjectName("tilesource")
        self.source_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts.addWidget(self.title)
        texts.addWidget(self.source_line)
        grip.addWidget(self.lcd, 1)
        self._ink_lcd()
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
        self.head.setFixedHeight(42)
        self.head.setLayout(head)
        root.addWidget(self.head)
        root.addSpacing(8)  # (0.12.2: the LCD header is 6 px taller, so the tile keeps its size)

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
        readout.setAccessibleName(f"{self.channel.label}, {mix.label} level")
        readout.setToolTip(LEVEL_HELP.strip())
        readout.wheel_steps = True
        readout.levels = True
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
        self.earlier_action = QAction_(menu, "Move earlier", lambda: self.window.move_tile(self.channel.id, -1))
        self.later_action = QAction_(menu, "Move later", lambda: self.window.move_tile(self.channel.id, 1))
        menu.insertAction(first, self.earlier_action)
        menu.insertAction(first, self.later_action)
        menu.insertSeparator(first)

        def refresh() -> None:
            self.fold_action.setText("Fold in" if self.expanded else "Fold out")
            ids = [c.id for c in self.engine.mixer.channels]
            index = ids.index(self.channel.id) if self.channel.id in ids else 0
            self.earlier_action.setEnabled(index > 0)
            self.later_action.setEnabled(index < len(ids) - 1)

        menu.aboutToShow.connect(refresh)

    # ------------------------------------------------------------------ folding out
    def toggle_open(self) -> None:
        self.set_open(not self.expanded)

    def set_open(self, on: bool) -> None:
        """Fold out or in."""
        if on == self.expanded:
            return
        self.expanded = on
        self.is_open = on
        opened = getattr(self.window, "tile_open", None)
        if opened is None:
            opened = self.window.tile_open = set()
        (opened.add if on else opened.discard)(self.channel.id)
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
        if not big:  # 0.12.4: measured again once the folded-out parts are really gone (they are deleted a moment later, and
            QTimer.singleShot(0, self._apply_size)  # until then they still count: the tile came back 24 px taller)

    def _apply_size(self) -> None:
        left, top, right, bottom = SHADOW
        width = (OPEN_W if self.expanded else TILE_W) + left + right
        if self.expanded and not self._empty:
            self.layout_root.activate()
            height = self.layout_root.totalHeightForWidth(width) if self.layout_root.hasHeightForWidth() \
                else self.layout_root.totalSizeHint().height()
            height = max(height, TILE_H + top + bottom)
        else:  # 0.11.7: as tall as the header, the lanes and the footer need (TILE_H kept 40 px of empty band above the footer)
            self.layout_root.invalidate()
            self.layout_root.activate()
            height = self.layout_root.totalMinimumSize().height()
            if height <= top + bottom:  # not laid out yet
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
        self.retint(skin_tile.channel_color(self.channel))  # 0.11.6: a channel's colour is shaded for the theme in use
        self._ink_lcd()
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

    def _ink_lcd(self) -> None:
        """The channel's name lit in its own colour on the LCD (0.12.2)."""
        light = skin_tile.is_light(themes.color("panel"))
        self.title.setStyleSheet(f"color: {skin_tile.lcd_ink(self.tint, light)};")
        skin_tile.lcd_caps(self.title)

    def retint(self, color: str) -> None:
        """Give the well, every lane and every app meter this colour (a new theme shades the channel's colour differently)."""
        if color == self.tint:
            return
        self.tint = color
        self.well.color = color
        self.well.update()
        for lane in self.faders.values():
            lane.set_fill(color)
            lane.refresh_theme()
        for _kind, _key, meter in self.app_meters:
            meter.color = color
            meter.update()

    def _show_mute(self, mix) -> None:
        button = self.mutes.get(mix.id)
        if button is None:
            return
        muted = button.isChecked()
        button.setIcon(icons.icon(skin_tile.LANE_ICONS.get(mix.id, "speaker"), themes.color("mute_fg" if muted else "text2"), 16))
        button.setToolTip(mute_tip(mix, muted))
        lane = self.faders.get(mix.id)
        if lane is not None:
            lane.set_muted(muted)
        readout = self.readouts.get(mix.id)
        if readout is not None and not readout.hasFocus():
            db = self.channel.levels.get(mix.id, 0.0)
            if muted:
                readout.setText("Muted")
                readout._level_shown = None
            else:
                readout.show_level(db, narrow=True)
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
        channel = getattr(self, "channel", None)
        color = skin_tile.channel_color(channel) if channel is not None else themes.color("accent")
        self.well.color = color  # 0.11.6: the colour follows the theme, as on the big tiles
        self.well.update()
        self.fader.set_fill(color)
        self.fader.refresh_theme()
        self.frame.refresh_theme()


# ----------------------------------------------------------------------------- Listen and Broadcast as keys (0.11.5)
MIX_KEY_W = 300                # the face of a Listen or Broadcast key; it stacks beside the channel tiles
MIX_KEY_MARGINS = (22, 8, 22, 36)  # room round the face for its skirt and shadows
MIX_KEY_GAP = 28               # 0.11.6: between two keys' faces (skirt included), stacked or side by side
MIX_KEY_OVERLAP = MIX_KEY_MARGINS[1] + MIX_KEY_MARGINS[3] - MIX_KEY_GAP  # how far their clear room overlaps (16, either way)
assert MIX_KEY_MARGINS[0] + MIX_KEY_MARGINS[2] - MIX_KEY_GAP == MIX_KEY_OVERLAP


def mix_key_color(mix_id: str) -> str:
    colors = themes.mix_colors(themes._current)
    return {"monitor": colors["listen"], "stream": colors["broadcast"]}.get(mix_id, themes.color("mute"))


def build_mix_key(strip, mix, on_remove=None, on_add_recording=None) -> None:
    """Build ``strip`` (a MixStrip) as a short key with a sideways slider: the mix's icon, name and device on top with a Limiter
    switch and a chevron, then one lane (mute, fader and meter in one groove, the level). The chevron folds out what is used less:
    the device picker (or the name to pick in OBS), Hear Broadcast or Add a recording mix, and Remove for the Recording mix. The parts
    keep MixStrip's names (fader, meter, readout, mute, limiter, combo, hear...), so everything that drives a mix card drives this."""
    from .ui_base import MIX_ICONS
    from .ui_mix import DeviceCombo
    from .ui_tile_paint import KeyBackground

    left, top, right, bottom = MIX_KEY_MARGINS
    strip.tile_key = True
    strip.key = KeyBackground(MIX_KEY_MARGINS, radius=16)
    strip.setFixedWidth(MIX_KEY_W + left + right)
    strip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
    color = mix_key_color(mix.id)
    strip.tint = color
    root = QVBoxLayout(strip)
    root.setContentsMargins(left + 14, top + 12, right + 14, bottom + SKIRT + 12)
    root.setSpacing(10)

    head = QHBoxLayout()
    head.setSpacing(10)
    strip.well = IconWell(color, MIX_ICONS.get(mix.id, "speaker"), mix.label, 30)
    head.addWidget(strip.well, 0, Qt.AlignmentFlag.AlignTop)
    strip.lcd = QFrame()  # 0.12.2: the name and device on a small LCD, as on the channel tiles
    strip.lcd.setObjectName("tilelcd")
    names = QVBoxLayout(strip.lcd)
    names.setContentsMargins(8, 2, 8, 3)
    names.setSpacing(0)
    title = QLabel(mix.label)
    title.setObjectName("tilename")
    title.setStyleSheet(f"color: {skin_tile.lcd_ink(color, skin_tile.is_light(themes.color('panel')))};")
    strip.lcd_title = title
    skin_tile.lcd_caps(title)
    names.addWidget(title)
    device_text = mix.source_description if mix.kind != "monitor" else "Your headphones or speakers"
    strip.device_line = ElidedLabel(device_text)
    strip.device_line.setObjectName("tilesource")
    names.addWidget(strip.device_line)
    head.addWidget(strip.lcd, 1)
    strip.limiter = QPushButton("Limiter")
    strip.limiter.setObjectName("tilelimiter")
    strip.limiter.setCheckable(True)
    strip.limiter.setCursor(Qt.CursorShape.PointingHandCursor)
    strip.limiter.setToolTip("Limiter: stops peaks from clipping")
    head.addWidget(strip.limiter, 0, Qt.AlignmentFlag.AlignVCenter)
    strip.fold = _small_button("chevron_down", "Open the full mix settings: device and more", "tileplain", checkable=True, size=28)
    head.addWidget(strip.fold, 0, Qt.AlignmentFlag.AlignVCenter)
    root.addLayout(head)

    lane_row = QHBoxLayout()
    lane_row.setSpacing(8)
    strip.mute = QPushButton("")
    strip.mute.setObjectName("tilemute")
    strip.mute.setCheckable(True)
    strip.mute.setFixedSize(28, 28)
    strip.mute.setIconSize(QSize(16, 16))
    strip.mute.setCursor(Qt.CursorShape.PointingHandCursor)
    strip.mute.setAccessibleName(f"Mute {mix.label}")
    lane = TileLane(color)
    lane.setAccessibleName(f"{mix.label} level and meter")
    strip.fader = strip.meter = lane   # the window's meter timer pushes the level into the same groove
    strip.readout = ReadoutEdit(None)
    strip.readout.setObjectName("tilevalue")
    strip.readout.setFixedSize(58, 28)
    strip.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    strip.readout.setAccessibleName(f"{mix.label} level")
    strip.readout.setToolTip(LEVEL_HELP.strip())
    strip.readout.wheel_steps = True
    lane_row.addWidget(strip.mute)
    lane_row.addWidget(lane, 1)
    lane_row.addWidget(strip.readout)
    root.addLayout(lane_row)

    strip.details = QWidget()
    strip.details.setObjectName("tiledetails")
    details = QVBoxLayout(strip.details)
    details.setContentsMargins(0, 4, 0, 0)
    details.setSpacing(8)
    strip.combo = None
    strip.device_button = None
    if mix.kind == "monitor":
        strip.combo = DeviceCombo("Output: ")
        strip.combo.setToolTip("Where you hear the mix")
        strip.combo.setAccessibleName("Listen output device")
        strip.combo.activated.connect(strip._on_device)
        details.addWidget(strip.combo)
    else:
        strip.device_button = QPushButton(f"Pick “{mix.source_description}” in OBS: copy the name")
        strip.device_button.setObjectName("tilemove")
        strip.device_button.setCursor(Qt.CursorShape.PointingHandCursor)
        strip.device_button.setToolTip(f"The device your streaming or recording app should pick: “{mix.source_description}”. "
                                       "Click to copy the name.")
        strip.device_button.clicked.connect(strip._copy_device_name)
        details.addWidget(strip.device_button)
    strip.hear = None
    strip.add_button = None
    if mix.kind == "monitor":
        strip.hear = QPushButton("Hear Broadcast")
        strip.hear.setObjectName("tilemove")
        strip.hear.setCheckable(True)
        strip.hear.setCursor(Qt.CursorShape.PointingHandCursor)
        strip.hear.setToolTip("Check what your audience hears: your output plays the Broadcast mix instead of the Listen mix. "
                              "Turn it off to go back. It always starts off.")
        strip.hear.toggled.connect(strip._on_hear)
        details.addWidget(strip.hear, 0, Qt.AlignmentFlag.AlignLeft)
    elif mix.id == "stream" and on_add_recording is not None:
        strip.add_button = QPushButton("Add a recording mix")
        strip.add_button.setObjectName("tileadd")
        strip.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        strip.add_button.setToolTip("Add a third mix, “Recording”: a second virtual microphone with its own faders and mutes. "
                                    "Sluice restarts to add it.")
        strip.add_button.clicked.connect(on_add_recording)
        details.addWidget(strip.add_button, 0, Qt.AlignmentFlag.AlignLeft)
    strip.menu_button = None
    if on_remove is not None:
        remove = QPushButton("Remove the Recording mix…")
        remove.setObjectName("tileadd")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(on_remove)
        details.addWidget(remove, 0, Qt.AlignmentFlag.AlignLeft)
    strip.details.setVisible(False)
    root.addWidget(strip.details)

    def fold(on: bool) -> None:
        strip.details.setVisible(on)
        strip.fold.setIcon(icons.icon("chevron_up" if on else "chevron_down", themes.color("text2"), 16))
        strip.fold.setToolTip("Fold in" if on else "Open the full mix settings: device and more")
        strip.updateGeometry()

    strip.fold.toggled.connect(fold)
    lane.gainChanged.connect(strip._on_gain)
    strip.readout.wheeled.connect(strip._wheel_gain)
    strip.readout.entered.connect(strip._typed_gain)
    strip.mute.toggled.connect(lambda on: strip.engine.set_master_mute(strip.mix.id, on))
    strip.mute.toggled.connect(lambda _on: strip._show_toggles())
    strip.limiter.toggled.connect(lambda on: strip.engine.set_limiter(strip.mix.id, on))
    strip.limiter.toggled.connect(lambda _on: strip._show_toggles())

