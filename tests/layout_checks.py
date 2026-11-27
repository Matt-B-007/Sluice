# SPDX-License-Identifier: GPL-3.0-or-later
"""Looks at a shown window and reports what would look wrong to a person: controls drawn over each other, text cut off, a sideways
scroll bar, a top bar wider than the window, or anything outside it. Used by the size sweep in test_window_sizing.py."""

import itertools

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QLabel, QWidget


def _region(win, widget) -> QRect:
    box = widget.visibleRegion().boundingRect()
    return QRect(widget.mapTo(win, box.topLeft()), box.size())


def problems(win, size, tag: str) -> list:
    found = []
    if (win.width(), win.height()) != tuple(size):
        found.append((tag, "the window is not the size asked for", win.width(), win.height()))
    shown = [
        w
        for w in win.findChildren(QWidget)
        if w.isVisible() and not w.visibleRegion().isEmpty() and not w.isWindow() and w.width() > 2 and w.height() > 2
    ]
    leaves = [w for w in shown if isinstance(w, (QLabel, QAbstractButton, QAbstractSlider))]
    for a, b in itertools.combinations(leaves, 2):
        if a.isAncestorOf(b) or b.isAncestorOf(a):
            continue
        overlap = _region(win, a).intersected(_region(win, b))
        if overlap.width() > 2 and overlap.height() > 2:
            found.append(
                (
                    tag,
                    "overlap",
                    a.objectName() or type(a).__name__,
                    getattr(a, "text", lambda: "")(),
                    b.objectName() or type(b).__name__,
                    getattr(b, "text", lambda: "")(),
                    overlap.getRect(),
                )
            )
    scroll = getattr(win, "channel_scroll", None)
    if scroll is not None and scroll.horizontalScrollBar().maximum() > 0:
        found.append((tag, "sideways scrolling in the channel area", scroll.horizontalScrollBar().maximum()))
    for widget in shown:
        if isinstance(widget, (QLabel, QAbstractButton)) and type(widget).__name__ != "ElidedLabel":
            text = widget.text()
            if not text or "<" in text or (isinstance(widget, QLabel) and widget.wordWrap()):
                continue
            metrics = widget.fontMetrics()
            need = max(metrics.horizontalAdvance(line.replace("&", "")) for line in text.split("\n"))
            if need > widget.contentsRect().width() + 1 and widget.objectName() != "chiptext":
                found.append(
                    (
                        tag,
                        "text cut off",
                        widget.objectName() or type(widget).__name__,
                        text[:24],
                        need,
                        widget.contentsRect().width(),
                    )
                )
        rect = _region(win, widget)
        if rect.right() > win.width() + 1 or rect.bottom() > win.height() + 1:
            found.append((tag, "outside the window", type(widget).__name__, widget.objectName(), rect.getRect()))
    bar = win.top_bar
    if bar.isVisible() and bar.sizeHint().width() > bar.width() + 1:
        found.append((tag, "top bar wider than the window", bar.sizeHint().width(), bar.width()))
    return found


def window_problems(window, tag: str) -> list:
    """The same checks for any other window (Settings, Effects, a dialog): overlaps, text cut off, anything outside it."""
    found = []
    shown = [
        w
        for w in window.findChildren(QWidget)
        if w.isVisible() and not w.visibleRegion().isEmpty() and not w.isWindow() and w.width() > 2 and w.height() > 2
    ]
    leaves = [w for w in shown if isinstance(w, (QLabel, QAbstractButton, QAbstractSlider))]
    for a, b in itertools.combinations(leaves, 2):
        if a.isAncestorOf(b) or b.isAncestorOf(a):
            continue
        overlap = _region(window, a).intersected(_region(window, b))
        if overlap.width() > 2 and overlap.height() > 2:
            found.append(
                (
                    tag,
                    "overlap",
                    a.objectName() or type(a).__name__,
                    getattr(a, "text", lambda: "")()[:30],
                    b.objectName() or type(b).__name__,
                    getattr(b, "text", lambda: "")()[:30],
                )
            )
    for widget in shown:
        if isinstance(widget, (QLabel, QAbstractButton)) and type(widget).__name__ != "ElidedLabel":
            text = widget.text()
            if not text or "<" in text or (isinstance(widget, QLabel) and widget.wordWrap()):
                continue
            metrics = widget.fontMetrics()
            need = max(metrics.horizontalAdvance(line.replace("&", "")) for line in text.split("\n"))
            room = widget.contentsRect().width()
            if isinstance(widget, QAbstractButton) and not isinstance(widget, QLabel):
                room = widget.width() - 8  # a button draws its text inside its own padding
            if need > room + 1:
                found.append((tag, "text cut off", widget.objectName() or type(widget).__name__, text[:30], need, room))
        rect = _region(window, widget)
        if rect.right() > window.width() + 1 or rect.bottom() > window.height() + 1:
            found.append((tag, "outside the window", type(widget).__name__, widget.objectName(), rect.getRect()))
    return found
