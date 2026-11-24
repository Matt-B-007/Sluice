"""The "Compare looks" window: a small picture of each look in the colours of the theme in use, drawn once."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QLabel, QPushButton, QVBoxLayout

from . import themes

W, H = 240, 150
BLURBS = {
    "calm": "Soft cards and quiet colours. The easiest on the eyes and on the computer.",
    "nexus": "Glass cards with sound rings and neon edges. Reduce effects keeps it light.",
    "glass": "Frosted panes over a soft wash of colour. On KDE Plasma, desktop widgets blur what is behind them.",
    "tile": "Raised keys in a tray, light or dark: fader and meter in one groove on each key. Fold a key out for effects and apps.",
}


def draw_preview(skin: str, colors: dict, ratio: float = 1.0) -> QPixmap:
    """One look as a picture: top bar, two channel cards and a master strip. Plain shapes, no effects."""
    pm = QPixmap(int(W * ratio), int(H * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(QColor(colors["bg"]))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if skin == "glass":  # the backdrop: the background washed towards the two mix colours at opposite corners
        mixc = themes.mix_colors(colors, "glass")
        wash = QLinearGradient(QPointF(0, 0), QPointF(W, H))
        wash.setColorAt(0.0, QColor(themes.mix(colors["bg"], mixc["listen"], 0.30)))
        wash.setColorAt(0.55, QColor(colors["bg"]))
        wash.setColorAt(1.0, QColor(themes.mix(colors["bg"], mixc["broadcast"], 0.26)))
        p.fillRect(QRectF(0, 0, W, H), wash)
    panel, accent, text = QColor(colors["panel"]), QColor(colors["accent"]), QColor(colors["text"])
    edge = QColor(themes.mix(colors["panel"], colors["accent"], 0.5)) if skin == "nexus" else QColor(colors.get("border", colors["panel"]))
    radius = {"calm": 10, "nexus": 12, "tile": 9, "glass": 12}.get(skin, 8)
    p.setPen(Qt.NoPen)
    bar = QColor(panel)
    if skin == "glass":
        bar.setAlpha(110)
    p.setBrush(bar)
    p.drawRect(0, 0, W, 18)
    p.setBrush(accent)
    p.drawRoundedRect(QRectF(8, 6, 28, 6), 3, 3)
    if skin == "tile":  # flat tiles: an icon well in the channel's colour, two lanes (fader and meter in one track) and a footer
        _draw_tiles(p, colors)
    for i in range(2 if skin != "tile" else 0):
        x = 10 + i * 70
        card = QRectF(x, 28, 62, 112)
        _card(p, card, skin, colors, edge, radius)
        p.setPen(Qt.NoPen)
        p.setBrush(text)
        p.drawRoundedRect(QRectF(x + 8, 36, 30, 4), 2, 2)
        if skin == "nexus":  # a ring
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(colors["bg"]).lighter(160), 4))
            p.drawEllipse(QRectF(x + 15, 50, 32, 32))
            p.setPen(QPen(accent, 4, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(x + 15, 50, 32, 32), 90 * 16, -(200 + i * 60) * 16)
            p.setPen(Qt.NoPen)
        else:  # a meter bar
            p.setBrush(QColor(colors["bg"]).lighter(150))
            p.drawRoundedRect(QRectF(x + 8, 52, 46, 8), 3, 3)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(x + 8, 52, 30 + i * 12, 8), 3, 3)
        p.setBrush(QColor(colors["bg"]).lighter(150))
        p.drawRoundedRect(QRectF(x + 29, 92, 4, 38), 2, 2)
        p.setBrush(accent)
        p.drawEllipse(QRectF(x + 24, 100 + i * 8, 14, 14))
    _card(p, QRectF(156, 28, 74, 112), skin, colors, edge, radius)
    p.setPen(Qt.NoPen)
    p.setBrush(accent)
    p.drawRoundedRect(QRectF(166, 100, 54, 12), 5, 5)
    p.end()
    return pm


def _card(p: QPainter, card: QRectF, skin: str, colors: dict, edge: QColor, radius: float) -> None:
    """One card as the skin draws it: Calm's soft shadow, Nexus's glass (lit at the top, deeper below, a cool outline), Glass's
    frosted pane (see-through, a bright top edge), or a plain card with an edge."""
    from . import depth
    panel = QColor(colors["panel"])
    light = depth.luminance(colors["panel"]) >= depth.LIGHT_PANEL
    if skin == "calm":  # a soft shadow under the card, made the way the window makes it (ui_paint.soft_shape)
        from .ui_paint import soft_shape
        pixmap, pad = soft_shape(card.width() - 4, card.height(), 4, 0.55 if light else 1.1, "#000000", p.device().devicePixelRatioF(),
                                 radius)
        p.drawPixmap(QPointF(card.left() + 2 - pad, card.top() + 3 - pad), pixmap)
    if skin == "nexus":
        gradient = QLinearGradient(card.topLeft(), card.bottomLeft())
        gradient.setColorAt(0.0, QColor(depth.shade(colors["panel"], 0.6 if light else 0.08)))
        gradient.setColorAt(0.4, panel)
        gradient.setColorAt(1.0, QColor(depth.shade(colors["panel"], -0.03 if light else -0.35)))
        p.setBrush(gradient)
    elif skin == "glass":
        panel.setAlphaF(0.66 if light else 0.5)
        p.setBrush(panel)
        edge = QColor(255, 255, 255, 190 if light else 30)
    else:
        p.setBrush(panel)
    p.setPen(QPen(edge, 1))
    p.drawRoundedRect(card, radius, radius)
    if skin == "glass":  # the light catching the top edge
        p.setPen(QPen(QColor(255, 255, 255, 245 if light else 80), 1))
        p.drawLine(QPointF(card.left() + radius, card.top() + 0.5), QPointF(card.right() - radius, card.top() + 0.5))


def _draw_tiles(p: QPainter, colors: dict) -> None:
    from .skin_tile import CHANNEL_TINTS, key_colors
    keys = key_colors(colors)  # the same depth colours the real keys use (0.11.5)
    panel, edge, track = QColor(keys["face_top"]), QColor(keys["key_edge"]), QColor(keys["groove"])
    tints = (CHANNEL_TINTS["mic"], CHANNEL_TINTS["game"], CHANNEL_TINTS["music"], CHANNEL_TINTS["chat"])
    tray_top = QColor(keys["tray_top"])
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(keys["tray_lip"]))
    p.drawRoundedRect(QRectF(4, 26, 148, 122), 10, 10)
    p.setBrush(tray_top)
    p.drawRoundedRect(QRectF(4, 22, 148, 122), 10, 10)
    skirt = QColor(keys["skirt"])
    for i, tint in enumerate(tints):
        x, y = 10 + (i % 2) * 72, 28 + (i // 2) * 58
        card = QRectF(x, y, 66, 48)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(card.translated(0, 5), 6, 6)
        p.setBrush(skirt)
        p.drawRoundedRect(card.translated(0, 3), 6, 6)
        p.setBrush(panel)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(card, 6, 6)
        well = QColor(themes.mix(colors["panel"], tint, 0.22))
        p.setPen(Qt.NoPen)
        p.setBrush(well)
        p.drawRoundedRect(QRectF(x + 5, y + 5, 10, 10), 3, 3)
        p.setBrush(QColor(colors["text"]))
        p.drawRoundedRect(QRectF(x + 19, y + 7, 24, 3), 1.5, 1.5)
        for lane in range(2):
            ly = y + 22 + lane * 10
            p.setBrush(track)
            p.drawRoundedRect(QRectF(x + 7, ly, 52, 4), 2, 2)
            p.setBrush(QColor(tint))
            p.drawRoundedRect(QRectF(x + 7, ly, 20 + 8 * ((i + lane) % 3), 4), 2, 2)
        p.setBrush(QColor(colors.get("surface2", colors["panel"])))
        p.drawRoundedRect(QRectF(x + 5, y + 41, 22, 6), 2, 2)
    p.setPen(Qt.NoPen)


class CompareSkinsDialog(QDialog):
    """Three pictures side by side; the button under each picks that look. Real buttons, so the keyboard works."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle("Compare skins")
        self.window_ref = window
        theme = window.current_theme()
        ratio = self.devicePixelRatioF()
        grid = QGridLayout()
        self.buttons = {}
        for column, (skin_id, name) in enumerate(themes.SKINS.items()):
            colors = themes.skin_colors(theme, skin_id)
            picture = QLabel()
            picture.setPixmap(draw_preview(skin_id, colors, ratio))
            picture.setAccessibleName(f"{name} skin preview")
            blurb = QLabel(BLURBS[skin_id])
            blurb.setWordWrap(True)
            blurb.setMaximumWidth(W)
            button = QPushButton(f"Use {name}")
            button.clicked.connect(lambda _c=False, skin_id=skin_id: self._use(skin_id))
            self.buttons[skin_id] = button
            grid.addWidget(picture, 0, column)
            grid.addWidget(blurb, 1, column)
            grid.addWidget(button, 2, column)
        self._mark_current()
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(box)

    def _mark_current(self) -> None:
        current = themes.valid_skin(self.window_ref.engine.mixer.skin)
        for skin_id, button in self.buttons.items():
            button.setEnabled(skin_id != current)
            button.setText(("In use: " if skin_id == current else "Use ") + themes.SKINS[skin_id])

    def _use(self, skin_id: str) -> None:
        self.window_ref.choose_skin(skin_id)
        self._mark_current()
