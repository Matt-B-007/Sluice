"""The "Compare looks" window: a small picture of each look in the colours of the theme in use, drawn once."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QLabel, QPushButton, QVBoxLayout

from . import themes

W, H = 240, 150
BLURBS = {
    "calm": "Soft cards and quiet colours. The easiest on the eyes and on the computer.",
    "original": "The look of Sluice 0.9.7: flat, compact and familiar.",
    "nexus": "Glass cards with sound rings and neon edges. Reduce effects keeps it light.",
    "tile": "Raised keys in a tray, light or dark: fader and meter in one groove on each key. Fold a key out for effects and apps.",
}


def draw_preview(look: str, colors: dict, ratio: float = 1.0) -> QPixmap:
    """One look as a picture: top bar, two channel cards and a master strip. Plain shapes, no effects."""
    pm = QPixmap(int(W * ratio), int(H * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(QColor(colors["bg"]))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    panel, accent, text = QColor(colors["panel"]), QColor(colors["accent"]), QColor(colors["text"])
    edge = QColor(themes.mix(colors["panel"], colors["accent"], 0.5)) if look == "nexus" else QColor(colors.get("border", colors["panel"]))
    radius = {"calm": 10, "original": 3, "nexus": 12, "tile": 9}.get(look, 8)
    p.setPen(Qt.NoPen)
    p.setBrush(panel)
    p.drawRect(0, 0, W, 18)
    p.setBrush(accent)
    p.drawRoundedRect(QRectF(8, 6, 28, 6), 3, 3)
    if look == "tile":  # flat tiles: an icon well in the channel's colour, two lanes (fader and meter in one track) and a footer
        _draw_tiles(p, colors)
    for i in range(2 if look != "tile" else 0):
        x = 10 + i * 70
        card = QRectF(x, 28, 62, 112)
        p.setBrush(panel)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(card, radius, radius)
        p.setPen(Qt.NoPen)
        p.setBrush(text)
        p.drawRoundedRect(QRectF(x + 8, 36, 30, 4), 2, 2)
        if look == "nexus":  # a ring
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
    p.setBrush(panel)
    p.setPen(QPen(edge, 1))
    p.drawRoundedRect(QRectF(156, 28, 74, 112), radius, radius)
    p.setPen(Qt.NoPen)
    p.setBrush(accent)
    p.drawRoundedRect(QRectF(166, 100, 54, 12), 5, 5)
    p.end()
    return pm


def _draw_tiles(p: QPainter, colors: dict) -> None:
    from .look_tile import CHANNEL_TINTS, key_colors
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


class CompareLooksDialog(QDialog):
    """Three pictures side by side; the button under each picks that look. Real buttons, so the keyboard works."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle("Compare looks")
        self.window_ref = window
        theme = window.current_theme()
        ratio = self.devicePixelRatioF()
        grid = QGridLayout()
        self.buttons = {}
        for column, (look_id, name) in enumerate(themes.LOOKS.items()):
            colors = themes.look_colors(theme, look_id)
            picture = QLabel()
            picture.setPixmap(draw_preview(look_id, colors, ratio))
            picture.setAccessibleName(f"{name} look preview")
            blurb = QLabel(BLURBS[look_id])
            blurb.setWordWrap(True)
            blurb.setMaximumWidth(W)
            button = QPushButton(f"Use {name}")
            button.clicked.connect(lambda _c=False, look_id=look_id: self._use(look_id))
            self.buttons[look_id] = button
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
        current = themes.valid_look(self.window_ref.engine.mixer.look)
        for look_id, button in self.buttons.items():
            button.setEnabled(look_id != current)
            button.setText(("In use: " if look_id == current else "Use ") + themes.LOOKS[look_id])

    def _use(self, look_id: str) -> None:
        self.window_ref.choose_look(look_id)
        self._mark_current()
