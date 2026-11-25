# SPDX-License-Identifier: GPL-3.0-or-later
"""How the Tile look paints: raised keys (face, skirt, rim, highlight and shadows), grooves, handles, the tray, the tile frame and
the icon well. Everything paints with the depth colours of the theme in use (``skin_tile.paint_colors``) and caches what it can."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QWidget

from . import skin_tile, themes, ui_icons as icons
from .model import MIN_DB


OPEN_W = 360                   # a folded-out tile (its height follows what it holds)
LANE_EXTRA_H = 44              # each lane past the second (the Recording mix) makes a folded tile this much taller (a 30 px lane and 14 px gap)
SHADOW = (22, 10, 22, 40)      # left, top, right, bottom: the room around a tile for its shadows and halo (0.11.5: none is cut off)
PAD = 14                       # inside the tile's edge
SKIRT = 8                      # the key's thick lower edge, inside the tile's footprint
RADIUS = 12.0
CLIP_HOLD = 2.0                # seconds the track stays outlined in red after a clip
CLIP_NOTE = 60.0               # seconds the source line says when it clipped
SCALE_MARKS = ((MIN_DB, "-∞"), (-40.0, "-40"), (-20.0, "-20"), (-10.0, "-10"), (0.0, "0"), (6.0, "+6"), (12.0, "+12"))


# ----------------------------------------------------------------------------- painting helpers
def soft_shape(width: float, height: float, blur: int, alpha: float, color: str, ratio: float, radius: float = RADIUS) -> tuple:
    """The one way Sluice makes a shadow or a halo (0.12.0: it lives in ui_paint); here with Tile's corner radius by default."""
    from .ui_paint import soft_shape as make
    return make(width, height, blur, alpha, color, ratio, radius)


def paint_surface(p: QPainter, rect: QRectF, ratio: float, focus: Optional[str] = None, lifted: bool = False,
                  shadow: bool = True, radius: float = RADIUS, skirt: int = SKIRT) -> None:
    """One key, in ``rect`` (its whole footprint), as in the 0.11.5 design: a wide soft shadow and a tight contact shadow under it (in
    a deep shade of the theme's own background, never plain black), its skirt (the thick lower edge) with a dark rim, the face lit
    from above with a lit top edge and a shaded bottom edge, and the halo and ring when it has the focus. On a very dark floor the
    shadows would not show, so the face gets a faint lit outline instead; High contrast is flat, with a solid border and edge.
    Painted once into a cached pixmap by whoever owns the key."""
    pc = skin_tile.paint_colors()
    face = rect.adjusted(0, 0, 0, -skirt)
    flat = pc["flat"]
    if shadow and not flat:
        soft_alpha, contact_alpha = pc["shadow_alpha"], pc["contact_alpha"]
        if lifted:
            soft_alpha, contact_alpha = min(1.0, soft_alpha * 1.4), contact_alpha * 0.6
        drop = (skirt + 18, skirt + 4) if not lifted else (skirt + 26, skirt + 8)
        pixmap, pad = soft_shape(face.width() - 8, face.height(), 14, soft_alpha * 1.6, pc["shadow_color"], ratio, radius)
        p.drawPixmap(QPointF(face.x() + 4 - pad, face.y() - pad + drop[0]), pixmap)
        pixmap, pad = soft_shape(face.width() - 2, face.height(), 4, contact_alpha * 1.8, pc["shadow_color"], ratio, radius)
        p.drawPixmap(QPointF(face.x() + 1 - pad, face.y() - pad + drop[1]), pixmap)
    if focus:
        pixmap, pad = soft_shape(face.width(), face.height() + skirt, 6, 0.55, focus, ratio, radius)
        p.drawPixmap(QPointF(face.x() - pad, face.y() - pad), pixmap)
    p.setPen(Qt.PenStyle.NoPen)
    if flat:  # High contrast: a plain face, a solid border, and a thick lower edge in the text colour
        p.setBrush(QColor(pc["skirt"]))
        p.drawRoundedRect(face.translated(0, min(skirt, 3)), radius, radius)
        p.setBrush(QColor(pc["face_top"]))
        p.setPen(QPen(QColor(pc["key_edge"]), 1.5))
        p.drawRoundedRect(face.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)
    else:
        p.setBrush(QColor(pc["skirt_dark"]))  # the rim: one dark line under the skirt
        p.drawRoundedRect(face.translated(0, skirt + 1), radius, radius)
        skirt_fill = QLinearGradient(QPointF(0, face.bottom() - radius), QPointF(0, face.bottom() + skirt))
        skirt_fill.setColorAt(0.0, QColor(pc["skirt"]))
        skirt_fill.setColorAt(1.0, QColor(themes.mix(pc["skirt"], pc["skirt_dark"], 0.45)))
        p.setBrush(skirt_fill)
        p.drawRoundedRect(face.translated(0, skirt), radius, radius)
        gradient = QLinearGradient(face.topLeft(), face.bottomLeft())
        gradient.setColorAt(0.0, QColor(pc["face_top"]))
        gradient.setColorAt(1.0, QColor(pc["face_bottom"]))
        p.setBrush(gradient)
        edge = QColor(0, 0, 0, 18 if pc["light"] else 70)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(face.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        shade = QColor(0, 0, 0, 30 if pc["light"] else 46)  # the inner bottom edge, turning away from the light
        p.setPen(QPen(shade, 2))
        p.drawLine(QPointF(face.left() + radius, face.bottom() - 1.5), QPointF(face.right() - radius, face.bottom() - 1.5))
        highlight = QColor(255, 255, 255, round(255 * pc["highlight_alpha"]))  # the lit top edge
        p.setPen(QPen(highlight, 1))
        p.drawLine(QPointF(face.left() + radius * 0.7, face.top() + 1.5), QPointF(face.right() - radius * 0.7, face.top() + 1.5))
        if pc["edge_light"]:  # a black floor shows no shadow: a faint lit outline lifts the key instead
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 34), 1))
            p.drawRoundedRect(face.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    if focus:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(focus), 1.5))
        p.drawRoundedRect(face.adjusted(0.75, 0.75, -0.75, -0.75), radius - 0.5, radius - 0.5)


def face_gradient(widget: QWidget, frame) -> Optional[QLinearGradient]:
    """The key face's gradient in ``widget``'s own coordinates, so a widget on the face can paint the face behind itself (and be
    opaque: Qt then repaints only that widget, not the key under it, when it changes)."""
    if frame is None:
        return None
    face = frame.face_rect()
    top = widget.mapFrom(frame, QPoint(0, round(face.top()))).y()
    bottom = widget.mapFrom(frame, QPoint(0, round(face.bottom()))).y()
    pc = skin_tile.paint_colors()
    gradient = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
    gradient.setColorAt(0.0, QColor(pc["face_top"]))
    gradient.setColorAt(1.0, QColor(pc["face_bottom"]))
    return gradient


def frame_of(widget: QWidget):
    """The TileFrame a widget sits on, or None."""
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, TileFrame):
        parent = parent.parentWidget()
    return parent


_STRIPES: dict = {}
_HANDLES: dict = {}


def stripe_brush(base: str, stripe: str) -> QBrush:
    """The diagonal stripes of a muted track, as one small tile Qt repeats (not forty lines a frame)."""
    key = (base, stripe)
    brush = _STRIPES.get(key)
    if brush is None:
        tile = QPixmap(8, 8)
        tile.fill(QColor(base))
        q = QPainter(tile)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setPen(QPen(QColor(stripe), 2.5))
        for offset in (-8, 0, 8):
            q.drawLine(QPointF(offset, 8), QPointF(offset + 8, 0))
        q.end()
        brush = QBrush(tile)
        _STRIPES[key] = brush
    return brush


def paint_groove(p: QPainter, shape: QPainterPath, track: QRectF, pc: dict) -> None:
    """A groove pressed into the face: dark at its top edge (in shadow), a faint light line at its bottom edge. (``shape`` is
    the groove's outline as the caller made it; ui_paint.groove makes the same one.)"""
    from . import ui_paint
    ui_paint.groove(p, track, None, round(255 * pc["groove_shadow"] * 0.55), 5.0,
                    light_line=QColor(255, 255, 255, 230 if pc["light"] else 14))


def paint_handle(p: QPainter, thumb: QRectF, pc: dict, muted: bool, focus: Optional[QColor] = None, line: Optional[str] = None) -> None:
    """0.12.2: a metal fader cap, like a hardware desk's: brushed metal lit from above with a crease across its middle, on a soft
    shadow, and a lit line in the channel's colour (``line``) down its centre. Muted: the cap is dull and has no line."""
    radius = min(3.0, thumb.width() / 3.0)
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 70 if pc["light"] else 140))
    p.drawRoundedRect(thumb.translated(0, 1.5), radius + 0.5, radius + 0.5)
    metal = QLinearGradient(thumb.topLeft(), thumb.bottomLeft())
    if muted:
        dull = QColor(pc["handle_muted"])
        metal.setColorAt(0.0, dull.lighter(112))
        metal.setColorAt(1.0, dull.darker(112))
    else:
        for at, color in pc["cap_stops"]:
            metal.setColorAt(at, QColor(color))
    p.setBrush(metal)
    p.setPen(QPen(QColor(0, 0, 0, 120 if not pc["light"] else 90), 1))
    p.drawRoundedRect(thumb.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.setPen(QPen(QColor(255, 255, 255, 70), 1))  # the lit top edge
    p.drawLine(QPointF(thumb.left() + radius, thumb.top() + 1.5), QPointF(thumb.right() - radius, thumb.top() + 1.5))
    centre = thumb.center().x()
    if line and not muted:
        glow = QColor(line)
        glow.setAlpha(90)
        p.setPen(QPen(glow, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(centre, thumb.top() + 4), QPointF(centre, thumb.bottom() - 4))
        p.setPen(QPen(QColor(line), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(centre, thumb.top() + 4), QPointF(centre, thumb.bottom() - 4))
    else:
        p.setPen(QPen(QColor(0, 0, 0, 80), 1.2))
        p.drawLine(QPointF(centre, thumb.top() + 5), QPointF(centre, thumb.bottom() - 5))
    if focus is not None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(focus, 2))
        p.drawRoundedRect(thumb.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
    p.restore()


LED = (3.0, 1.5)  # a segment's width and the gap after it (0.12.2's sideways LED meters)


def paint_leds(p: QPainter, track: QRectF, upto: float, pc: dict, lit: bool, amber_x: float, red_x: float) -> None:
    """The segments of a sideways LED meter from the left of ``track`` to x = ``upto``: green, amber from ``amber_x`` (-12 dB) and
    red from ``red_x`` (-3 dB). Lit, or dim (the unlit ones, drawn once into the lane's cached base)."""
    width, gap = LED
    inset = 2.0 if track.height() >= 8 else 1.5
    top, height = track.top() + inset, track.height() - 2 * inset
    x = track.left() + 3.0
    end = min(upto, track.right() - 3.0)
    colors = {name: QColor(pc[name]) for name in ("led_green", "led_amber", "led_red")}
    if not lit:
        for color in colors.values():
            color.setAlpha(pc["led_off_alpha"])
    p.setPen(Qt.PenStyle.NoPen)
    while x + width <= end + 0.01:
        p.setBrush(colors["led_red"] if x >= red_x else colors["led_amber"] if x >= amber_x else colors["led_green"])
        p.drawRect(QRectF(x, top, width, height))
        x += width + gap


def paint_slot(p: QPainter, rect: QRectF) -> None:
    """Where a dragged tile will land: a dashed outline and "Drop here"."""
    pc = skin_tile.paint_colors()
    floor = QColor(pc["track"])
    floor.setAlpha(110)
    pen = QPen(QColor(pc["dashed"]), 1.5, Qt.PenStyle.CustomDashLine)
    pen.setDashPattern([5, 4])
    p.setPen(pen)
    p.setBrush(floor)
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), RADIUS, RADIUS)
    p.setPen(QColor(pc["text2"]))
    font = QFont(p.font())
    font.setPixelSize(12)
    p.setFont(font)
    band = QRectF(rect.left(), rect.bottom() - 40, rect.width(), 30)  # the lifted tile hangs over the middle: the label is below it
    p.drawText(band, Qt.AlignmentFlag.AlignCenter, "Drop here")


class TileFrame(QFrame):
    """The painted part of a tile: everything under its controls. ``margins`` is the room left round the tile for its shadow."""

    def __init__(self, margins: tuple = SHADOW, radius: float = RADIUS) -> None:
        super().__init__()
        self.setObjectName("tileframe")
        self.margins = margins
        self.radius = radius
        self.focus_color: Optional[str] = None
        self.slot = False
        self.shadow = True
        self.lifted = False
        self._cache = None
        self._cache_key = None

    def tile_rect(self) -> QRectF:
        left, top, right, bottom = self.margins
        return QRectF(self.rect()).adjusted(left, top, -right, -bottom)

    def face_rect(self) -> QRectF:
        """The key's top face (its footprint without the skirt)."""
        return self.tile_rect().adjusted(0, 0, 0, -SKIRT)

    def set_focus_color(self, color: Optional[str]) -> None:
        if color != self.focus_color:
            self.focus_color = color
            self.update()

    def set_slot(self, on: bool) -> None:
        self.slot = on
        self.update()

    def set_lifted(self, on: bool) -> None:
        if on != self.lifted:
            self.lifted = on
            self.update()

    def refresh_theme(self) -> None:
        self._cache = None
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        if self.slot:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_slot(p, self.tile_rect())
            p.end()
            return
        ratio = self.devicePixelRatioF()
        key = (self.size(), self.focus_color, ratio, themes.generation(), self.shadow, self.lifted, self.radius)
        if self._cache is None or key != self._cache_key:
            pixmap = QPixmap(max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_surface(q, self.tile_rect(), ratio, self.focus_color, lifted=self.lifted, shadow=self.shadow, radius=self.radius)
            q.end()
            self._cache, self._cache_key = pixmap, key
        p.drawPixmap(0, 0, self._cache)
        p.end()


class IconWell(QWidget):
    """The channel's tinted icon well: its identity colour, faint behind and full on the drawing (or its first letter)."""

    def __init__(self, color: str, icon: str, letter: str, size: int = 32) -> None:
        super().__init__()
        self.color, self.icon_name, self.letter, self.size_ = color, icon, (letter[:1] or "?").upper(), size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pc = skin_tile.paint_colors()
        well = QColor(themes.mix(pc["surface"], self.color, 0.16 if not pc["light"] else 0.14))
        edge = QColor(themes.mix(pc["surface"], self.color, 0.30))
        p.setPen(QPen(edge, 1))
        p.setBrush(well)
        r = self.size_ * 0.28
        p.drawRoundedRect(QRectF(0.5, 0.5, self.size_ - 1, self.size_ - 1), r, r)
        if self.icon_name:
            ratio = self.devicePixelRatioF()
            px = round(self.size_ * 0.56)
            pixmap = icons.render(self.icon_name, self.color, round(px * ratio))
            pixmap.setDevicePixelRatio(ratio)
            offset = (self.size_ - px) / 2.0
            p.drawPixmap(QPointF(offset, offset), pixmap)
        else:
            font = QFont(p.font())
            font.setPixelSize(round(self.size_ * 0.44))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(self.color))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.letter)
        p.end()


# ----------------------------------------------------------------------------- the tray, and keys for the other cards
class KeyBackground:
    """A raised key behind any widget (the Listen and Broadcast cards, a row of the Rows layout): drawn once per size and theme."""

    def __init__(self, margins: tuple, radius: float = RADIUS) -> None:
        self.margins, self.radius = margins, radius
        self._cache = None
        self._key = None

    def face_rect(self, widget: QWidget) -> QRectF:
        left, top, right, bottom = self.margins
        return QRectF(widget.rect()).adjusted(left, top, -right, -bottom - SKIRT)

    def draw(self, widget: QWidget, p: QPainter, focus: Optional[str] = None) -> None:
        ratio = widget.devicePixelRatioF()
        key = (widget.size(), ratio, themes.generation(), focus)
        if self._cache is None or key != self._key:
            pixmap = QPixmap(max(1, int(widget.width() * ratio)), max(1, int(widget.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            left, top, right, bottom = self.margins
            paint_surface(q, QRectF(widget.rect()).adjusted(left, top, -right, -bottom), ratio, focus, radius=self.radius)
            q.end()
            self._cache, self._key = pixmap, key
        p.drawPixmap(0, 0, self._cache)


class TrayPainter:
    """The tray the keys sit in (0.11.5): a plate sunk below the floor, darker than the keys (lighter than a black floor), with a
    shadow along its inside top edge and a 12 px front lip. Drawn once per size and theme."""

    LIP = 12
    RADIUS = 28

    def __init__(self) -> None:
        self._cache = None
        self._key = None

    def reset(self) -> None:
        self._cache = None

    def draw(self, widget: QWidget, p: QPainter, size=None) -> None:
        """The tray over all of ``widget``, or (0.12.0) only its top-left ``size``: the part the tiles are in."""
        ratio = widget.devicePixelRatioF()
        size = widget.size() if size is None else size
        key = (size, ratio, themes.generation())
        if self._cache is None or key != self._key:
            pc = skin_tile.paint_colors()
            pixmap = QPixmap(max(1, int(size.width() * ratio)), max(1, int(size.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            q = QPainter(pixmap)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self.RADIUS
            plate = QRectF(0, 0, size.width(), size.height()).adjusted(1, 1, -1, -1 - self.LIP)
            q.setPen(Qt.PenStyle.NoPen)
            if not pc["flat"]:
                pixmap_shadow, pad = soft_shape(plate.width() - 24, plate.height(), 16, pc["shadow_alpha"] * 0.9, pc["shadow_color"],
                                                ratio, r)
                q.drawPixmap(QPointF(plate.x() + 12 - pad, plate.y() - pad + self.LIP + 10), pixmap_shadow)
            q.setBrush(QColor(pc["tray_lip"]))
            q.drawRoundedRect(plate.translated(0, self.LIP), r, r)
            gradient = QLinearGradient(plate.topLeft(), plate.bottomLeft())
            gradient.setColorAt(0.0, QColor(pc["tray_top"]))
            gradient.setColorAt(1.0, QColor(pc["tray_bottom"]))
            q.setBrush(gradient)
            if pc["flat"]:
                q.setPen(QPen(QColor(pc["key_edge"]), 1.5))
            q.drawRoundedRect(plate, r, r)
            if not pc["flat"]:
                q.save()  # the inside top edge is in shadow: the plate is sunk below the floor
                clip = QPainterPath()
                clip.addRoundedRect(plate, r, r)
                q.setClipPath(clip)
                inner = QLinearGradient(plate.topLeft(), QPointF(plate.left(), plate.top() + 14))
                inner.setColorAt(0.0, QColor(0, 0, 0, 70 if pc["light"] else 150))
                inner.setColorAt(1.0, QColor(0, 0, 0, 0))
                q.fillRect(QRectF(plate.left(), plate.top(), plate.width(), 14), inner)
                q.restore()
                q.setPen(QPen(QColor(255, 255, 255, 255 if pc["light"] else 12), 1))  # light catching the front edge
                q.drawLine(QPointF(plate.left() + r, plate.bottom() - 0.5), QPointF(plate.right() - r, plate.bottom() - 0.5))
            q.end()
            self._cache, self._key = pixmap, key
        p.drawPixmap(0, 0, self._cache)


class TileTray(QWidget):
    """The tray behind the Columns layout's tiles."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tiletray")
        self.tray = TrayPainter()

    def refresh_theme(self) -> None:
        self.tray.reset()
        self.update()

    def content_size(self):
        """0.12.0: the tray ends with the tiles: the area round the tiles (and the Add channel button) with the layout's margins,
        not the whole of the scroll area. Empty, or before layout: all of it."""
        from PySide6.QtCore import QRect, QSize
        layout = self.layout()
        shown = [w.geometry() for w in self.findChildren(QWidget) if w.parentWidget() is self and w.isVisible()]
        if layout is None or not shown:
            return self.size()
        union = QRect(shown[0])
        for rect in shown[1:]:
            union = union.united(rect)
        margins = layout.contentsMargins()
        width = min(self.width(), union.right() + 1 + margins.right())
        height = min(self.height(), union.bottom() + 1 + margins.bottom() + TrayPainter.LIP)
        return QSize(max(width, 2 * TrayPainter.RADIUS), max(height, 2 * TrayPainter.RADIUS + TrayPainter.LIP))

    def event(self, event) -> bool:
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.ChildRemoved):  # a tile came, went or moved: the tray's end too
            self.update()
        return super().event(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)  # 0.12.2: smooth edges everywhere
        self.tray.draw(self, p, self.content_size())
        p.end()
