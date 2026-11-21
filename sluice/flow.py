"""A layout that puts its widgets side by side and starts a new line when the width runs out (so a window that gets narrower
wraps its cards instead of scrolling sideways)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 16) -> None:
        super().__init__(parent)
        self._items: list = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # the parts of a box layout the window uses
    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def addWidget(self, widget, stretch: int = 0) -> None:  # noqa: ARG002  (stretch is meaningless in a flow)
        self.addChildWidget(widget)
        self.addItem(_item(widget))
        self.invalidate()

    def insertWidget(self, index: int, widget, stretch: int = 0) -> None:  # noqa: ARG002
        self.addChildWidget(widget)
        self._items.insert(max(0, index), _item(widget))
        self.invalidate()

    def addStretch(self, _stretch: int = 0) -> None:
        pass

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            self.invalidate()
            return self._items.pop(index)
        return None

    def spacing(self) -> int:
        return self._gap

    def setSpacing(self, value: int) -> None:
        self._gap = value
        self.invalidate()

    # the flow itself
    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            if x + size.width() > area.right() + 1 and line > 0:
                x, y, line = area.x(), y + line + self._gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self._gap
            line = max(line, size.height())
        return y + line - rect.y() + margins.bottom()


def _item(widget):
    from PySide6.QtWidgets import QWidgetItem
    return QWidgetItem(widget)


class OverlapLayout(QLayout):
    """A row or column of widgets that may overlap by ``overlap`` pixels (0.11.6). The Tile look's Listen and Broadcast keys keep
    clear room round their faces for their shadows; laid out edge to edge, the faces were 44 px apart. Overlapping the clear room
    puts the faces 28 px apart, and the later key (drawn on top) hides the part of the earlier key's shadow its face covers."""

    def __init__(self, vertical: bool, overlap: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._items: list = []
        self.vertical, self.overlap = vertical, overlap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def addWidget(self, widget, stretch: int = 0) -> None:  # noqa: ARG002
        self.addChildWidget(widget)
        self.addItem(_item(widget))
        self.invalidate()

    def addStretch(self, _stretch: int = 0) -> None:
        pass  # the widgets start at the top (or the left) and the rest is left empty

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            self.invalidate()
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def _shown(self) -> list:
        return [item for item in self._items if not item.isEmpty()]

    def sizeHint(self) -> QSize:
        sizes = [item.sizeHint() for item in self._shown()]
        margins = self.contentsMargins()
        extra = QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        if not sizes:
            return extra
        if self.vertical:
            size = QSize(max(s.width() for s in sizes), sum(s.height() for s in sizes) - self.overlap * (len(sizes) - 1))
        else:
            size = QSize(sum(s.width() for s in sizes) - self.overlap * (len(sizes) - 1), max(s.height() for s in sizes))
        return size + extra

    def minimumSize(self) -> QSize:
        return self.sizeHint()

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        margins = self.contentsMargins()
        x, y = rect.x() + margins.left(), rect.y() + margins.top()
        for item in self._shown():
            size = item.sizeHint()
            item.setGeometry(QRect(QPoint(x, y), size))
            if self.vertical:
                y += size.height() - self.overlap
            else:
                x += size.width() - self.overlap
