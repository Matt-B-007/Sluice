# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving a tile: the lifted picture under the pointer and the "Drop here" slot that moves through the other tiles."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import skin_tile
from .ui_tile_paint import soft_shape


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
        pc = skin_tile.paint_colors()
        pixmap, pad = soft_shape(
            self.tile_rect.width(), self.tile_rect.height(), 20, pc["shadow"] * 2.6, "#000000", self.devicePixelRatioF()
        )
        p.drawPixmap(QPointF(self.tile_rect.x() - pad, self.tile_rect.y() - pad + 14), pixmap)
        p.drawPixmap(QPointF(0, 0), self.picture)
        p.end()


class TileMover(QObject):
    """Moves a tile. In Columns the tile's place becomes the "Drop here" slot, which moves through the other tiles as the pointer
    does; dropping keeps that order (and saves it). Escape puts it back."""

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
        self._reorder(point)

    def drop(self, point: QPoint) -> None:
        tile = self.tile
        if tile is None:
            return
        self.window.commit_tile_order([s.channel.id for s in self._strips_in_flow()])
        self._end()

    def cancel(self) -> None:
        tile = self.tile
        if tile is None:
            return
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
