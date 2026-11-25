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
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap

NAMES = ("speaker", "speaker_off", "mic", "mic_off", "link", "sliders", "plus", "menu", "gear", "more", "chevron_down", "headphones",
         "broadcast", "chevron_up", "gamepad", "chat", "globe", "note", "bell",
         # 0.11.7: the ☰ panel and the Settings window
         "refresh", "columns", "rows", "widgets", "eye", "record", "camera", "fullscreen", "tray", "keyboard", "star", "pulse", "bug",
         "palette", "power", "save", "close", "chevron_right", "wave", "folder", "info", "quit",
         # 0.12.0: the setup check
         "checklist",
         # 0.12.2: drawn instead of typed characters (▾ ◀ ▶ ✓ ×)
         "chevron_left", "check", "x")


class _Grid:
    """Draws on the 24 x 24 grid scaled to ``k`` pixels per unit, with a pen of whole pixels and edges snapped to the pixel grid."""

    def __init__(self, painter: QPainter, k: float, color: QColor) -> None:
        self.p, self.k = painter, k
        self.w = max(1, round(2.4 * k))  # 0.12.2: a little bolder: 2 px at 16 px, where it was 1
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
    elif name == "chevron_up":
        g.poly([(6, 15), (12, 9), (18, 15)])
    elif name == "gamepad":  # the Tile look's Game channel
        g.rrect(3, 7, 18, 11, 5.5)
        g.line(7, 12.5, 11, 12.5)
        g.line(9, 10.5, 9, 14.5)
        g.circle(15.5, 11, 1.1, filled=True)
        g.circle(17.5, 14, 1.1, filled=True)
    elif name == "chat":  # Chat
        g.poly([(4, 5), (20, 5), (20, 16), (11, 16), (6, 20), (6, 16), (4, 16)], closed=True)
    elif name == "globe":  # Browser
        g.circle(12, 12, 8.5)
        g.arc(8, 3.5, 8, 17, 0, 360)
        g.line(3.5, 12, 20.5, 12)
    elif name == "note":  # Music
        g.circle(8, 17, 2.8)
        g.circle(17, 15, 2.8)
        g.line(10.8, 17, 10.8, 6)
        g.line(19.8, 15, 19.8, 4)
        g.line(10.8, 6, 19.8, 4)
    elif name == "bell":  # System
        g.poly([(5, 17), (7, 14.5), (7, 10), (8.5, 6.5), (12, 5), (15.5, 6.5), (17, 10), (17, 14.5), (19, 17)], closed=True)
        g.line(10.5, 20, 13.5, 20)
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
    elif name == "refresh":
        g.arc(4, 4, 16, 16, 30, 300)
        g.poly([(20, 4), (20, 9), (15, 9)])
    elif name == "columns":
        for x, w in ((3, 5), (10, 5), (17, 4)):
            g.rrect(x, 4, w, 16, 1.5)
    elif name == "rows":
        for y, h in ((4, 4.5), (10, 4.5), (16, 4)):
            g.rrect(3, y, 18, h, 1.5)
    elif name == "widgets":
        g.rrect(3, 3, 7, 7, 2)
        g.rrect(14, 3, 7, 7, 2)
        g.rrect(3, 14, 7, 7, 2)
        g.line(17.5, 14, 17.5, 21)
        g.line(14, 17.5, 21, 17.5)
    elif name == "eye":
        g.arc(2, 5, 20, 14, 20, 140)
        g.arc(2, 5, 20, 14, 200, 140)
        g.circle(12, 12, 3)
    elif name == "record":
        g.circle(12, 12, 8)
        g.circle(12, 12, 3, filled=True)
    elif name == "camera":
        g.rrect(2, 6, 14, 12, 2)
        g.poly([(16, 10), (22, 7), (22, 17), (16, 14)])
    elif name == "fullscreen":
        g.poly([(3, 8), (3, 3), (8, 3)])
        g.poly([(16, 3), (21, 3), (21, 8)])
        g.poly([(3, 16), (3, 21), (8, 21)])
        g.poly([(16, 21), (21, 21), (21, 16)])
    elif name == "tray":
        g.poly([(3, 13), (8, 13), (10, 16), (14, 16), (16, 13), (21, 13)])
        g.rrect(3, 5, 18, 15, 2)
    elif name == "keyboard":
        g.rrect(2, 6, 20, 12, 2)
        for x in (6, 10, 14, 18):
            g.circle(x, 10, 0.6, filled=True)
        g.line(7, 14, 17, 14)
    elif name == "star":
        points = []
        for i in range(10):
            a = math.radians(-90 + 36 * i)
            r = 9 if i % 2 == 0 else 4
            points.append((12 + r * math.cos(a), 12.5 + r * math.sin(a)))
        g.poly(points, closed=True)
    elif name == "pulse":
        g.poly([(3, 12), (7, 12), (10, 5), (14, 19), (17, 12), (21, 12)])
    elif name == "bug":
        g.rrect(7, 7, 10, 13, 5)
        g.line(12, 11, 12, 20)
        g.line(3, 13, 7, 13)
        g.line(17, 13, 21, 13)
        g.line(9, 7, 7.5, 4)
        g.line(15, 7, 16.5, 4)
    elif name == "palette":
        g.arc(3, 3, 18, 18, 0, 300)
        g.poly([(21, 12), (16, 13), (15, 16), (16.5, 20.5)])
        for x, y in ((8, 10), (12, 7), (16, 9)):
            g.circle(x, y, 1.2, filled=True)
    elif name == "power":
        g.line(12, 3, 12, 11)
        g.arc(4, 5, 16, 16, 120, 300)
    elif name == "save":
        g.poly([(4, 4), (16, 4), (20, 8), (20, 20), (4, 20)], closed=True)
        g.poly([(8, 4), (8, 9), (15, 9), (15, 4)])
        g.rrect(8, 14, 8, 6, 0.5)
    elif name == "close":
        g.line(6, 6, 18, 18)
        g.line(18, 6, 6, 18)
    elif name == "chevron_right":
        g.poly([(9, 6), (15, 12), (9, 18)])
    elif name == "chevron_left":
        g.poly([(15, 6), (9, 12), (15, 18)])
    elif name == "check":
        g.poly([(5, 12.5), (10, 17.5), (19, 7)])
    elif name == "x":  # a small cross, for removing a chip
        g.line(8, 8, 16, 16)
        g.line(16, 8, 8, 16)
    elif name == "wave":
        g.poly([(3, 12), (6, 12), (8, 7), (11, 17), (13, 9), (15, 15), (17, 12), (21, 12)])
    elif name == "folder":
        g.poly([(3, 6), (9, 6), (11, 8), (21, 8), (21, 19), (3, 19)], closed=True)
    elif name == "info":
        g.circle(12, 12, 9)
        g.line(12, 11, 12, 17)
        g.circle(12, 7.5, 0.8, filled=True)
    elif name == "checklist":
        for y in (6, 12, 18):
            g.poly([(3.5, y), (5, y + 2), (8.5, y - 2)])
            g.line(12, y, 21, y)
    elif name == "quit":
        g.poly([(14, 4), (5, 4), (5, 20), (14, 20)])
        g.line(10, 12, 21, 12)
        g.poly([(17, 8), (21, 12), (17, 16)])
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


class _ThemedEngine(_Engine):
    """0.12.2: an icon that takes its colour from the theme in use each time it is drawn (``token``, such as "text2"), so a button
    made once still matches after the theme changes."""

    def __init__(self, name: str, token: str) -> None:
        super().__init__(name, "#000000")
        self.token = token

    def clone(self):
        return _ThemedEngine(self.name, self.token)

    def _now(self) -> None:
        from . import themes
        self.color = themes.color(self.token)

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        self._now()
        return super().pixmap(size, mode, state)

    def paint(self, painter: QPainter, rect, mode, state) -> None:
        self._now()
        super().paint(painter, rect, mode, state)


def themed_icon(name: str, token: str = "text2") -> QIcon:
    """A QIcon of the named drawing in the theme's ``token`` colour, as it is when drawn."""
    if name not in NAMES:
        raise ValueError(f"no icon called {name}")
    return QIcon(_ThemedEngine(name, token))


def dropdown(button, size: int = 14) -> None:
    """0.12.2: a button that opens a menu shows a drawn chevron at its right end, instead of a typed ▾."""
    button.setIcon(themed_icon("chevron_down"))
    button.setIconSize(QSize(size, size))
    button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)


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


APP_DIRS = ("~/.local/share/applications", "/usr/share/applications", "/usr/local/share/applications",
            "/var/lib/flatpak/exports/share/applications", "~/.local/share/flatpak/exports/share/applications",
            "/var/lib/snapd/desktop/applications")


@lru_cache(maxsize=256)
def guess_icon(name: str) -> str:
    """0.12.2: the icon name for an app Sluice only knows by name (``spotify``, ``Discord``, ``firefox``): the name itself if the icon
    theme has it, else the Icon= line of a matching desktop entry (com.spotify.Client.desktop and the like), else ""."""
    import os
    name = (name or "").strip()
    if not name or os.path.isabs(name):
        return ""
    lower = name.lower()
    for candidate in dict.fromkeys((name, lower, lower.replace(" ", "-"), lower.replace(" ", ""))):
        if QIcon.hasThemeIcon(candidate):
            return candidate
    for folder in APP_DIRS:
        folder = os.path.expanduser(folder)
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for entry in entries:
            stem = entry[:-8].lower() if entry.endswith(".desktop") else ""
            if not stem or not (stem == lower or stem.endswith("." + lower) or stem.split(".")[-1] == lower.replace(" ", "")):
                continue
            try:
                with open(os.path.join(folder, entry), encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        if line.startswith("Icon="):
                            return line[5:].strip()
            except OSError:
                continue
    return ""


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
    if image is None:  # 0.12.2: no picture given: look the app up by its name, so a chip shows its real icon, not a letter
        for name in (key.split(":")[-1] if key else "", label):
            guessed = guess_icon(name)
            image = _source_image(guessed) if guessed else None
            if image is not None:
                break
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
def _logo_svg(ring: Optional[str] = None) -> Optional[bytes]:
    """The bundled logo as SVG text, optionally with the ring in another colour (None if the file is missing)."""
    from .launcher import bundled_icon

    try:
        text = Path(bundled_icon()).read_text(encoding="utf-8")
    except OSError:
        return None
    return (text.replace(RING_COLOUR, ring) if ring else text).encode("utf-8")


RING_COLOUR = "#0d9488"   # the teal of the logo's ring
TALKING_RING = "#4fb5aa"  # the ring colour about 35% lighter, for the closed ring while you talk
MUTED_RED = "#ef4444"


TRAY_CROP = (20.5, 87.0)   # the logo file is cropped to the part that has ink: from 20.5, 87 units wide (the same as its viewBox)


def tray_pixmap(state: str, px: int) -> QPixmap:
    """The logo for the system tray, on a transparent background like the logo itself: plain; while you talk the ring closes
    and gets heavier and lighter; while your microphone is muted the whole logo fades, the ring turns red, and a red badge
    sits in the corner. The picture is cropped to the logo so it fills the tray slot like the other icons there, and drawn
    at the exact pixel size so it stays sharp."""
    from PySide6.QtSvg import QSvgRenderer

    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    origin, size = TRAY_CROP
    k = px / size
    painter.scale(k, k)
    painter.translate(-origin, -origin)   # from here on everything is drawn in the logo's own 128-unit picture
    ring = {"muted": MUTED_RED, "talking": TALKING_RING}.get(state)
    renderer = QSvgRenderer(_logo_svg(ring) or b"")
    if state == "talking":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(TALKING_RING), max(1.5 / k, 10.0)))
        painter.drawEllipse(QPointF(64, 64), 38, 38)   # the two gaps fill in: a closed ring
    if state == "muted":
        painter.setOpacity(0.45)
    if renderer.isValid():
        renderer.render(painter, QRectF(origin, origin, size, size))   # the logo (for "talking" with the ring in the lighter colour)
    painter.setOpacity(1.0)
    if state == "muted":
        end = origin + size
        radius = 0.234 * size   # the badge keeps its share of the icon
        centre = QPointF(end - radius - 1.0, end - radius - 1.0)
        painter.setPen(QPen(QColor("#10131a"), max(1.0 / k, 3.0)))   # a dark rim so the badge stands out on any tray
        painter.setBrush(QColor(MUTED_RED))
        painter.drawEllipse(centre, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        bar_w, bar_h = radius * 1.0, radius * 0.3
        painter.drawRoundedRect(QRectF(centre.x() - bar_w / 2, centre.y() - bar_h / 2, bar_w, bar_h), bar_h / 2, bar_h / 2)
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
