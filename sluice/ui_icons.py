# SPDX-License-Identifier: GPL-3.0-or-later
"""The small line icons of the interface, drawn with Qt so they take the colour of the theme.

Every icon is a 24 x 24 drawing made of strokes (round ends), the same way as the icons of the design mock-ups. They are drawn
for the exact pixel size asked for, whatever the screen's scale (100%, 125%, 150%, 200%...): the stroke is a whole number of
pixels wide and straight lines sit on pixel boundaries, so they stay sharp instead of blurred by a fractional scale.
``icon(name, color)`` returns a QIcon; nothing is read from disk.
"""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap

NAMES = ("speaker", "speaker_off", "mic", "mic_off", "link", "sliders", "plus", "menu", "gear", "more", "chevron_down", "headphones",
         "broadcast")


class _Grid:
    """Draws on the 24 x 24 grid scaled to ``k`` pixels per unit, with a pen of whole pixels and edges snapped to the pixel grid."""

    def __init__(self, painter: QPainter, k: float, color: QColor) -> None:
        self.p, self.k = painter, k
        self.w = max(1, round(2 * k))
        self.off = 0.5 if self.w % 2 else 0.0   # an odd pen is centred on a pixel's middle, an even one on its edge
        pen = QPen(color, self.w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self.color = color

    def s(self, v: float) -> float:
        return round(v * self.k - self.off) + self.off

    def pt(self, x: float, y: float) -> QPointF:
        return QPointF(self.s(x), self.s(y))

    def line(self, x1, y1, x2, y2) -> None:
        self.p.drawLine(self.pt(x1, y1), self.pt(x2, y2))

    def poly(self, points: list, closed: bool = False) -> None:
        path = QPainterPath()
        path.moveTo(self.pt(*points[0]))
        for point in points[1:]:
            path.lineTo(self.pt(*point))
        if closed:
            path.closeSubpath()
        self.p.drawPath(path)

    def rrect(self, x, y, w, h, r) -> None:
        x0, y0, x1, y1 = self.s(x), self.s(y), self.s(x + w), self.s(y + h)
        self.p.drawRoundedRect(QRectF(x0, y0, x1 - x0, y1 - y0), r * self.k, r * self.k)

    def arc(self, x, y, w, h, start_deg, span_deg) -> None:
        k = self.k
        self.p.drawArc(QRectF(x * k, y * k, w * k, h * k), int(start_deg * 16), int(span_deg * 16))

    def circle(self, cx, cy, r, filled: bool = False) -> None:
        k = self.k
        if filled:
            self.p.setBrush(self.color)
        self.p.drawEllipse(QPointF(self.s(cx), self.s(cy)), r * k, r * k)
        if filled:
            self.p.setBrush(Qt.BrushStyle.NoBrush)


def _draw(name: str, g: _Grid) -> None:
    if name in ("speaker", "speaker_off"):
        g.poly([(4, 9.5), (8, 9.5), (13, 5.5), (13, 18.5), (8, 14.5), (4, 14.5)], closed=True)
        if name == "speaker_off":
            g.line(17, 9, 22, 15)
            g.line(22, 9, 17, 15)
        else:
            g.arc(10, 7.5, 9, 9, -50, 100)
            g.arc(8, 4.5, 15, 15, -50, 100)
    elif name in ("mic", "mic_off"):
        g.rrect(9, 3, 6, 11, 3)
        g.arc(5.5, 7, 13, 11, 180, 180)
        g.line(12, 18, 12, 21)
        g.line(9, 21, 15, 21)
        if name == "mic_off":
            g.line(4, 4, 20, 20)
    elif name == "link":
        g.rrect(3, 8.5, 11, 7, 3.5)
        g.rrect(10, 8.5, 11, 7, 3.5)
    elif name == "sliders":
        for y, x in ((6, 9), (12, 15), (18, 8)):
            g.line(4, y, 20, y)
            g.circle(x, y, 2.2, filled=True)
    elif name == "plus":
        g.line(12, 5, 12, 19)
        g.line(5, 12, 19, 12)
    elif name == "menu":
        for y in (7, 12, 17):
            g.line(4, y, 20, y)
    elif name == "gear":
        g.circle(12, 12, 3)
        for angle in range(0, 360, 45):
            a = math.radians(angle)
            g.line(12 + 6.5 * math.sin(a), 12 - 6.5 * math.cos(a), 12 + 9 * math.sin(a), 12 - 9 * math.cos(a))
        g.circle(12, 12, 6.5)
    elif name == "more":
        for y in (5.5, 12, 18.5):
            g.circle(12, y, 1.5, filled=True)
    elif name == "chevron_down":
        g.poly([(6, 9), (12, 15), (18, 9)])
    elif name == "headphones":
        g.arc(4, 4, 16, 16, 0, 180)
        g.rrect(3.5, 12, 4, 7, 2)
        g.rrect(16.5, 12, 4, 7, 2)
    elif name == "broadcast":
        g.circle(12, 12, 2, filled=True)
        g.arc(7, 7, 10, 10, 135, 90)
        g.arc(7, 7, 10, 10, -45, 90)
        g.arc(3, 3, 18, 18, 135, 90)
        g.arc(3, 3, 18, 18, -45, 90)
    else:
        raise ValueError(f"no icon called {name}")


def render(name: str, color: str, px: int) -> QPixmap:
    """The icon as a pixmap exactly ``px`` x ``px`` device pixels."""
    px = max(8, int(px))
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw(name, _Grid(p, px / 24.0, QColor(color)))
    p.end()
    return pixmap


class _Engine(QIconEngine):
    """Draws the icon for whatever size and screen scale Qt asks for, so it is never a stretched copy of another size."""

    def __init__(self, name: str, color: str) -> None:
        super().__init__()
        self.name, self.color = name, color

    def clone(self):
        return _Engine(self.name, self.color)

    def actualSize(self, size: QSize, mode, state) -> QSize:
        side = min(size.width(), size.height())
        return QSize(side, side)

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return _cached(self.name, self.color, min(size.width(), size.height()))

    def paint(self, painter: QPainter, rect, mode, state) -> None:
        ratio = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
        side = min(rect.width(), rect.height())
        pixmap = _cached(self.name, self.color, round(side * ratio))  # device pixels: drawn 1:1, never stretched
        painter.drawPixmap(QRectF(rect.x() + (rect.width() - side) / 2.0, rect.y() + (rect.height() - side) / 2.0, side, side),
                           pixmap, QRectF(pixmap.rect()))


@lru_cache(maxsize=512)
def _cached(name: str, color: str, px: int) -> QPixmap:
    return render(name, color, px)


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """A QIcon of the named drawing in ``color`` (a #rrggbb string), sharp at every screen scale."""
    if name not in NAMES:
        raise ValueError(f"no icon called {name}")
    return QIcon(_Engine(name, color))


# ------------------------------------------------------------------------------------------ pictures of apps and games
_AVATAR_COLORS = ("#4da3ff", "#3ddc84", "#ff9f43", "#b78cff", "#ff6b9a", "#f5c542", "#3ddbc0", "#ff7a7a")


def _steam_art(app_id: str) -> str:
    """A small picture Steam keeps for a game (its icon, else its header), or "". Looked up in Steam's own library cache."""
    import re
    from pathlib import Path

    home = Path.home()
    roots = (home / ".local/share/Steam", home / ".steam/steam", home / ".var/app/com.valvesoftware.Steam/.local/share/Steam")
    for root in roots:
        folder = root / "appcache" / "librarycache"
        try:
            for name in (f"{app_id}_icon.jpg", f"{app_id}_icon.png"):
                if (folder / name).is_file():
                    return str(folder / name)
            game = folder / app_id
            if game.is_dir():
                files = sorted(p for p in game.rglob("*") if p.suffix.lower() in (".jpg", ".png"))
                for p in files:
                    if re.fullmatch(r"[0-9a-f]{40}", p.stem):
                        return str(p)  # Steam's own icon for the game
                for wanted in ("library_capsule", "library_header", "header", "logo"):
                    for p in files:
                        if p.stem.startswith(wanted):
                            return str(p)
        except OSError:
            continue
    return ""


@lru_cache(maxsize=512)
def _source_image(spec: str):
    """The QImage for an icon name or file path (or None). Theme icons come from the desktop's icon theme."""
    import os

    from PySide6.QtGui import QImage

    candidates = []
    if spec and os.path.isabs(spec):
        candidates.append(spec)
    if spec.startswith("steam_icon_"):
        art = _steam_art(spec[len("steam_icon_"):])
        if art:
            candidates.append(art)
    for path in candidates:
        image = QImage(path)
        if not image.isNull():
            return image
    if spec and not os.path.isabs(spec):
        themed = QIcon.fromTheme(spec)
        if not themed.isNull():
            pixmap = themed.pixmap(128, 128)
            if not pixmap.isNull():
                return pixmap.toImage()
    return None


def app_pixmap(spec: str, label: str, size: int = 20, ratio: float = 1.0, key: str = "") -> QPixmap:
    """A square picture of an app or game, ``size`` points wide, sharp at ``ratio``. When no picture is known: a rounded square
    with the first letter of the name, in a colour chosen from the name so it is always the same one."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QFont

    px = max(1, round(size * ratio))
    pixmap = QPixmap(px, px)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    p.setClipPath(clip)
    image = _source_image(spec)
    if image is not None:
        side = min(image.width(), image.height())
        square = image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side)
        p.drawImage(QRectF(0, 0, size, size), square)
    else:
        seed = sum(ord(c) for c in (key or label)) if (key or label) else 0
        p.fillRect(QRectF(0, 0, size, size), QColor(_AVATAR_COLORS[seed % len(_AVATAR_COLORS)]))
        font = QFont()
        font.setPixelSize(max(8, round(size * 0.55)))
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor("#0e1116"))
        letter = next((c for c in label if c.isalnum()), "?").upper()
        p.drawText(QRectF(0, 0, size, size), int(_Qt.AlignmentFlag.AlignCenter), letter)
    p.end()
    return pixmap


# ------------------------------------------------------------------------------------------ the system tray icon
TRAY_STATES = ("idle", "talking", "muted")
_TRAY_SIZES = (16, 22, 24, 32, 48, 64)


@lru_cache(maxsize=32)
def tray_pixmap(state: str, px: int) -> QPixmap:
    """The logo for the system tray: plain, lit up while you talk (a teal ring and the gate handle in teal), or with a red badge while
    your microphone is muted. Drawn at the exact pixel size so it stays sharp in the tray."""
    from PySide6.QtSvg import QSvgRenderer

    from .desktop import bundled_icon

    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    k = px / 128.0
    renderer = QSvgRenderer(str(bundled_icon()))
    if renderer.isValid():
        renderer.render(painter, QRectF(0, 0, px, px))
    else:  # the picture is missing: a plain teal tile is better than nothing
        painter.setBrush(QColor("#1c2430"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, px, px), 30 * k, 30 * k)
    if state == "talking":
        # The ring closes and glows: its two gaps fill in, it gets heavier and brighter, and the tile gets a teal edge.
        lit = QColor("#5ff5dc")
        painter.setBrush(Qt.BrushStyle.NoBrush)
        edge = QPen(QColor("#2ee6c5"), max(1.5, 5 * k))
        painter.setPen(edge)
        inset = edge.widthF() / 2
        painter.drawRoundedRect(QRectF(inset, inset, px - 2 * inset, px - 2 * inset), 30 * k - inset, 30 * k - inset)
        ring = QPen(lit, max(1.5, 9 * k))
        painter.setPen(ring)
        painter.drawEllipse(QPointF(64 * k, 64 * k), 38 * k, 38 * k)
    elif state == "muted":
        # The ring turns red where it was teal, and a red badge with a white bar sits in the corner the ring leaves free.
        red = QColor("#ef4444")
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(red, max(1.5, 6 * k)))
        rect = QRectF(26 * k, 26 * k, 76 * k, 76 * k)  # the ring's circle: centre (64, 64), radius 38
        for start in (207, 27):  # the two arcs of the logo's ring, 144 degrees each, clockwise
            arc = QPainterPath()
            arc.arcMoveTo(rect, start)
            arc.arcTo(rect, start, -144)
            painter.drawPath(arc)
        centre, radius = QPointF(100 * k, 100 * k), 24 * k
        painter.setPen(QPen(QColor("#10131a"), max(1.0, 4 * k)))  # a dark rim so the badge stands out on any tray
        painter.setBrush(red)
        painter.drawEllipse(centre, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(centre.x() - 12 * k, centre.y() - 3.5 * k, 24 * k, 7 * k), 3.5 * k, 3.5 * k)
    painter.end()
    return pixmap


def tray_icon(state: str) -> QIcon:
    """The tray icon for ``state`` (idle, talking or muted) at every size a tray might ask for."""
    if state not in TRAY_STATES:
        raise ValueError(f"no tray state called {state}")
    result = QIcon()
    for px in _TRAY_SIZES:
        result.addPixmap(tray_pixmap(state, px))
    return result
