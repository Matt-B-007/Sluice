"""Small pictures of each skin in the colours of a theme, drawn from its real design (Settings > Themes and skins)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap

from . import themes

W, H = 240, 150
BLURBS = {
    "calm": "Soft cards and quiet colours. The easiest on the eyes and on the computer.",
    "nexus": "Glass cards with sound rings and neon edges. Reduce effects keeps it light.",
    "glass": "Frosted panes over a soft wash of colour. On KDE Plasma, desktop widgets blur what is behind them.",
    "tile": "Raised keys in a tray, light or dark: fader and meter in one groove on each key. Fold a key out for effects and apps.",
}


CHANNELS = (("mic", 0.62), ("game", 0.48), ("chat", 0.7))  # what the pictures show: three channels and how loud each is


def draw_preview(skin: str, colors: dict, ratio: float = 1.0) -> QPixmap:
    """0.12.2: one skin as a small picture drawn from its real design (the shapes the window draws, in these colours): a top bar,
    three channel cards and the Listen card. Calm: white cards with tinted icon tiles; Tile: raised keys with LCD names and LED
    meters on a tray; Glass: frosted panes on a mix of light with pearl knobs; Nexus: glowing level rings and beams on a grid."""
    from .skin_tile import CHANNEL_TINTS
    pm = QPixmap(int(W * ratio), int(H * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(QColor(colors["bg"]))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    mixc = themes.mix_colors(colors, skin)
    if skin == "glass":
        _glass_backdrop(p, colors)
    elif skin == "nexus":
        grid = QColor(colors["accent"])
        grid.setAlphaF(0.07)
        p.setPen(QPen(grid, 1))
        for x in range(0, W, 16):
            p.drawLine(x, 18, x, H)
        for y in range(18, H, 16):
            p.drawLine(0, y, W, y)
    _top_bar(p, skin, colors)
    if skin == "tile":
        _draw_tiles(p, colors)
    else:
        for i, (channel, level) in enumerate(CHANNELS):
            _channel_card(p, QRectF(8 + i * 52, 26, 46, 116), skin, colors, CHANNEL_TINTS[channel], level)
        _listen_card(p, QRectF(168, 26, 64, 116), skin, colors, mixc["listen"])
    p.end()
    return pm


def _top_bar(p: QPainter, skin: str, colors: dict) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(2):  # the menu and Settings buttons
        button = QColor(colors["surface2"] if skin != "glass" else "#ffffff")
        if skin == "glass":
            button.setAlpha(50)
        p.setBrush(button)
        p.drawRoundedRect(QRectF(8 + i * 14, 5, 11, 10), 3, 3)
    p.setBrush(QColor(colors["title"]))
    p.drawRoundedRect(QRectF(38, 8, 26, 4), 2, 2)
    live = QColor(colors["live_fg"])
    p.setBrush(live)
    p.drawEllipse(QRectF(W - 40, 8, 4, 4))
    p.setBrush(QColor(colors["text_dim"]))
    p.drawRoundedRect(QRectF(W - 33, 8, 24, 4), 2, 2)


def _pane(p: QPainter, card: QRectF, skin: str, colors: dict, tint: str = "", radius: float = 9) -> None:
    """A card as the skin draws it."""
    from . import depth
    light = depth.luminance(colors["panel"]) >= depth.LIGHT_PANEL
    if skin == "calm":
        from .ui_paint import soft_shape
        pixmap, pad = soft_shape(card.width() - 4, card.height(), 5, 0.5 if light else 1.0, "#000000", p.device().devicePixelRatioF(), radius)
        p.drawPixmap(QPointF(card.left() + 2 - pad, card.top() + 3 - pad), pixmap)
        p.setBrush(QColor(colors["panel"]))
        p.setPen(QPen(QColor(colors["border"]), 1))
        p.drawRoundedRect(card, radius, radius)
    elif skin == "glass":
        pane = QColor(themes.mix(colors["panel"], tint, 0.25) if tint else colors["panel"])
        pane.setAlphaF(0.62 if light else 0.42)
        p.setBrush(pane)
        p.setPen(QPen(QColor(255, 255, 255, 170 if light else 40), 1))
        p.drawRoundedRect(card, radius + 3, radius + 3)
        p.setPen(QPen(QColor(255, 255, 255, 240 if light else 95), 1))
        p.drawLine(QPointF(card.left() + radius, card.top() + 0.5), QPointF(card.right() - radius, card.top() + 0.5))
    else:  # nexus: a lit card with an outline in the channel's colour, glowing on dark
        if tint:
            halo = QColor(tint)
            for grow, alpha in ((4, 0.06), (2, 0.12)):
                halo.setAlphaF(alpha)
                p.setPen(QPen(halo, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(card.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)
        gradient = QLinearGradient(card.topLeft(), card.bottomLeft())
        gradient.setColorAt(0.0, QColor(depth.shade(colors["panel"], 0.08)))
        gradient.setColorAt(1.0, QColor(depth.shade(colors["panel"], -0.35)))
        p.setBrush(gradient)
        p.setPen(QPen(QColor(themes.mix(colors["panel"], tint or colors["accent"], 0.7)), 1))
        p.drawRoundedRect(card, radius, radius)


def _fader(p: QPainter, x: float, top: float, bottom: float, at: float, skin: str, colors: dict, tint: str) -> None:
    """An upright fader: Calm's pill, Glass's pearl or Nexus's beam with a ring of light."""
    from . import ui_paint
    y = bottom - (bottom - top) * at
    p.setPen(Qt.PenStyle.NoPen)
    if skin == "nexus":
        p.setBrush(QColor(colors["border2"]))
        p.drawRoundedRect(QRectF(x - 1, top, 2, bottom - top), 1, 1)
        glow = QColor(tint)
        glow.setAlphaF(0.25)
        p.setBrush(glow)
        p.drawRoundedRect(QRectF(x - 2.5, y, 5, bottom - y), 2.5, 2.5)
        p.setBrush(QColor(tint))
        p.drawRoundedRect(QRectF(x - 1, y, 2, bottom - y), 1, 1)
        p.setBrush(QColor(colors["bg"]))
        p.setPen(QPen(QColor(tint), 1.6))
        p.drawEllipse(QPointF(x, y), 3.6, 3.6)
        return
    p.setBrush(QColor(colors["track"]) if skin != "glass" else QColor(0, 0, 0, 60))
    p.drawRoundedRect(QRectF(x - 1.5, top, 3, bottom - top), 1.5, 1.5)
    p.setBrush(QColor(tint))
    p.drawRoundedRect(QRectF(x - 1.5, y, 3, bottom - y), 1.5, 1.5)
    if skin == "glass":
        ui_paint.pearl(p, QRectF(x - 4.5, y - 4.5, 9, 9))
    else:
        ui_paint.handle(p, QRectF(x - 6, y - 3, 12, 6), colors["handle"], colors["handle_edge"], 50)


def _meter(p: QPainter, x: float, top: float, bottom: float, level: float, colors: dict, tint: str) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(colors["meter_bg"]))
    p.drawRoundedRect(QRectF(x - 1.5, top, 3, bottom - top), 1.5, 1.5)
    lit = QLinearGradient(QPointF(0, bottom), QPointF(0, top))
    lit.setColorAt(0.0, QColor(tint))
    lit.setColorAt(0.76, QColor(tint))
    lit.setColorAt(0.9, QColor("#f2b722"))
    lit.setColorAt(1.0, QColor("#ee4b5e"))
    p.setBrush(lit)
    y = bottom - (bottom - top) * level
    p.drawRoundedRect(QRectF(x - 1.5, y, 3, bottom - y), 1.5, 1.5)


def _ring(p: QPainter, centre: QPointF, radius: float, level: float, colors: dict, tint: str) -> None:
    """Nexus's level ring: a dim track and a glowing arc."""
    box = QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(colors["border2"]), 2.6))
    p.drawEllipse(box)
    glow = QColor(tint)
    glow.setAlphaF(0.3)
    p.setPen(QPen(glow, 5.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(box, 90 * 16, -round(360 * 16 * level))
    p.setPen(QPen(QColor(tint), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(box, 90 * 16, -round(360 * 16 * level))


def _channel_card(p: QPainter, card: QRectF, skin: str, colors: dict, color: str, level: float) -> None:
    from . import depth
    tint = depth.channel_tint(color, colors)
    _pane(p, card, skin, colors, tint if skin == "nexus" else "")
    p.setPen(Qt.PenStyle.NoPen)
    x = card.left()
    if skin == "nexus":
        _ring(p, QPointF(card.center().x(), card.top() + 20), 11, level, colors, tint)
        p.setBrush(QColor(colors["title"]))
        p.drawRoundedRect(QRectF(card.center().x() - 10, card.top() + 38, 20, 3.5), 1.5, 1.5)
        top = card.top() + 50
    else:
        p.setBrush(QColor(themes.mix(colors["panel"], tint, 0.18)))  # the tinted icon tile
        p.drawRoundedRect(QRectF(x + 6, card.top() + 7, 11, 11), 3, 3)
        p.setBrush(QColor(tint))
        p.drawEllipse(QRectF(x + 9.5, card.top() + 10.5, 4, 4))
        p.setBrush(QColor(colors["title"]))
        p.drawRoundedRect(QRectF(x + 20, card.top() + 9, 18, 3.5), 1.5, 1.5)
        p.setBrush(QColor(colors["text_dim"]))
        p.drawRoundedRect(QRectF(x + 20, card.top() + 15, 12, 2.5), 1.2, 1.2)
        top = card.top() + 30
    bottom = card.bottom() - 22
    for lane, (fx, at) in enumerate(((x + 12, 0.7), (x + 30, 0.62))):
        _fader(p, fx, top, bottom, at, skin, colors, tint)
        _meter(p, fx + 7, top, bottom, level * (1.0 if lane == 0 else 0.85), colors, tint)
    p.setPen(Qt.PenStyle.NoPen)
    for lane in range(2):  # the mute keys
        key = QColor(colors["surface2"] if skin != "glass" else "#ffffff")
        if skin == "glass":
            key.setAlpha(50)
        p.setBrush(key)
        p.drawRoundedRect(QRectF(x + 5 + lane * 19, card.bottom() - 14, 16, 8), 3, 3)


def _listen_card(p: QPainter, card: QRectF, skin: str, colors: dict, tint: str) -> None:
    _pane(p, card, skin, colors, tint)
    p.setPen(Qt.PenStyle.NoPen)
    x = card.left()
    p.setBrush(QColor(tint))
    p.drawRoundedRect(QRectF(x + 7, card.top() + 7, 16, 2.5), 1.2, 1.2)
    p.setBrush(QColor(colors["title"]))
    p.drawRoundedRect(QRectF(x + 7, card.top() + 13, 26, 4), 2, 2)
    top, bottom = card.top() + 28, card.bottom() - 26
    if skin == "nexus":
        _ring(p, QPointF(card.center().x(), card.top() + 46), 13, 0.66, colors, tint)
        top = card.top() + 66
    else:  # the level scale beside the fader (0.12.2)
        p.setBrush(QColor(colors["text_off"]))
        for i in range(5):
            p.drawRect(QRectF(x + 12, top + i * (bottom - top) / 4.0, 4, 1))
    _fader(p, x + 28, top, bottom, 0.72, skin, colors, tint)
    _meter(p, x + 40, top, bottom, 0.66, colors, tint)
    _meter(p, x + 46, top, bottom, 0.6, colors, tint)
    lim = QColor(themes.mix(colors["panel"], tint, 0.2))
    p.setBrush(lim)
    p.drawRoundedRect(QRectF(x + 24, card.bottom() - 16, 34, 9), 3, 3)
    p.setBrush(QColor(colors["surface2"]))
    p.drawRoundedRect(QRectF(x + 7, card.bottom() - 16, 13, 9), 3, 3)


def _glass_backdrop(p: QPainter, colors: dict) -> None:
    from PySide6.QtGui import QRadialGradient
    from .skin_glass import backdrop_colours
    from .ui_glass import SHAPES
    values = dict(colors, **themes.mix_colors(colors, "glass"))
    for (fx, fy, size), colour in zip(SHAPES, backdrop_colours(values)):
        centre = QPointF(fx * W, fy * H)
        radius = size * W
        gradient = QRadialGradient(centre, radius)
        inner = QColor(colour)
        inner.setAlphaF(0.5)
        outer = QColor(colour)
        outer.setAlphaF(0.0)
        gradient.setColorAt(0.0, inner)
        gradient.setColorAt(1.0, outer)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawEllipse(centre, radius, radius)


def _draw_tiles(p: QPainter, colors: dict) -> None:
    """Tile (0.12.2): raised keys on a tray that ends below them, each with an LCD name strip and two sideways LED lanes with metal
    caps, and the Listen key beside them."""
    from .skin_tile import CHANNEL_TINTS, is_light, key_colors, lcd_colors, lcd_ink
    keys = key_colors(colors)
    light = is_light(colors["panel"])
    lcd = lcd_colors(light)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(keys["tray_lip"]))
    p.drawRoundedRect(QRectF(4, 28, 158, 104), 10, 10)
    p.setBrush(QColor(keys["tray_top"]))
    p.drawRoundedRect(QRectF(4, 24, 158, 104), 10, 10)
    tints = (CHANNEL_TINTS["mic"], CHANNEL_TINTS["game"], CHANNEL_TINTS["chat"], CHANNEL_TINTS["music"])
    for i, tint in enumerate(tints):
        _key(p, QRectF(10 + (i % 2) * 76, 30 + (i // 2) * 48, 70, 40), keys, lcd, lcd_ink(tint, light), tint, i, light)
    _key(p, QRectF(170, 30, 64, 40), keys, lcd, lcd_ink(themes.mix_colors(colors, "tile")["listen"], light),
         themes.mix_colors(colors, "tile")["listen"], 1, light)


def _key(p: QPainter, card: QRectF, keys: dict, lcd: dict, ink: str, tint: str, index: int, light: bool) -> None:
    from .skin_tile import CAP_DARK, CAP_LIGHT
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawRoundedRect(card.translated(0, 5), 6, 6)
    p.setBrush(QColor(keys["skirt"]))
    p.drawRoundedRect(card.translated(0, 3), 6, 6)
    face = QLinearGradient(card.topLeft(), card.bottomLeft())
    face.setColorAt(0.0, QColor(keys["face_top"]))
    face.setColorAt(1.0, QColor(keys["face_bottom"]))
    p.setBrush(face)
    p.setPen(QPen(QColor(keys["key_edge"]), 1))
    p.drawRoundedRect(card, 6, 6)
    strip = QRectF(card.left() + 5, card.top() + 4, card.width() - 10, 11)
    p.setPen(QPen(QColor(lcd["lcd_edge"]), 1))
    p.setBrush(QColor(lcd["lcd_bottom"]))
    p.drawRoundedRect(strip, 2.5, 2.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ink))
    p.drawRect(QRectF(strip.left() + 3, strip.top() + 3.5, 18, 3.5))
    for lane in range(2):
        y = card.top() + 21 + lane * 9
        groove = QRectF(card.left() + 6, y, card.width() - 12, 5)
        p.setBrush(QColor(keys["groove"]))
        p.drawRoundedRect(groove, 2.5, 2.5)
        lit = 0.45 + 0.12 * ((index + lane) % 3)
        x = groove.left() + 1.5
        while x < groove.right() - 3:
            on = x < groove.left() + groove.width() * lit
            spot = (x - groove.left()) / groove.width()
            color = QColor("#ff4d3d" if spot > 0.86 else "#f2c230" if spot > 0.7 else "#39d353")
            color.setAlpha(255 if on else 45)
            p.setBrush(color)
            p.drawRect(QRectF(x, y + 1.2, 1.6, 2.6))
            x += 2.6
        cap_x = groove.left() + groove.width() * (lit + 0.08)
        metal = QLinearGradient(QPointF(0, y - 2), QPointF(0, y + 7))
        for at, color in (CAP_LIGHT if light else CAP_DARK):
            metal.setColorAt(at, QColor(color))
        p.setBrush(metal)
        p.drawRoundedRect(QRectF(cap_x - 3, y - 2, 6, 9), 1.5, 1.5)
        p.setBrush(QColor(tint))
        p.drawRect(QRectF(cap_x - 0.5, y, 1, 5))
