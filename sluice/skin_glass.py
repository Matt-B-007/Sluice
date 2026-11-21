# SPDX-License-Identifier: GPL-3.0-or-later
"""The Glass skin (0.11.6): frosted panes over a softly tinted backdrop. Cards, buttons and chips are see-through, with a bright hairline
along their top edge and a fainter one round the rest, so they read as panes of frosted glass lying on the colour behind them.

It starts from the Calm sheet and adds to it (the later rule wins where both name the same thing), so every part of the window is
styled and the layout is Calm's. On the desktop, Glass widgets are see-through too, and on KDE Plasma KWin blurs what is behind them
(see ``desktop_place.blur_behind``); elsewhere they are see-through without the blur. Every colour comes from the theme in use."""
from __future__ import annotations

from string import Template


def rgba(color: str, alpha: float) -> str:
    """A ``#rrggbb`` colour as a style-sheet ``rgba()`` at ``alpha`` (0..1)."""
    color = color.lstrip("#")
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {round(alpha * 255)})"


def glass_values(values: dict) -> dict:
    """The see-through colours of the panes and the tints of the backdrop, for a theme (light or dark)."""
    from . import depth
    light = depth.luminance(values["panel"]) >= depth.LIGHT_PANEL
    listen, broadcast = values.get("listen", values["accent"]), values.get("broadcast", values["code"])
    bg = values["bg"]
    return {
        # the backdrop: the theme's background, tinted towards the two mix colours at opposite corners
        "glass_wash_a": depth.mix(bg, listen, 0.16 if light else 0.20),
        "glass_wash_b": depth.mix(bg, broadcast, 0.12 if light else 0.16),
        "glass_wash_mid": bg,
        # the panes: the panel colour, see-through, and white hairlines (brighter along the top, where the light catches)
        "glass_pane": rgba(values["panel"], 0.62 if light else 0.50),
        "glass_pane_strong": rgba(values["panel"], 0.80 if light else 0.70),
        "glass_edge": rgba("#ffffff", 0.75 if light else 0.09),
        "glass_edge_top": rgba("#ffffff", 0.95 if light else 0.22),
        "glass_button": rgba("#ffffff", 0.55 if light else 0.06),
        "glass_button_hover": rgba("#ffffff", 0.80 if light else 0.11),
        "glass_button_edge": rgba("#000000", 0.08) if light else rgba("#ffffff", 0.10),
        "glass_well": rgba("#000000", 0.05 if light else 0.28),
        "glass_listen": rgba(listen, 0.14 if light else 0.12),
        "glass_listen_edge": rgba(listen, 0.45),
        "glass_broadcast": rgba(broadcast, 0.14 if light else 0.12),
        "glass_broadcast_edge": rgba(broadcast, 0.45),
        "glass_accent": rgba(values["accent"], 0.22 if light else 0.20),
    }


GLASS_EXTRA = """
/* Glass: frosted panes on a tinted backdrop. */
QWidget#root { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $glass_wash_a, stop:0.55 $glass_wash_mid,
    stop:1 $glass_wash_b); }
QScrollArea, QScrollArea > QWidget > QWidget, QWidget#channels, QWidget#masters, QWidget#sources { background: transparent; }
QStatusBar { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $glass_wash_mid, stop:1 $glass_wash_b); }
QFrame#strip, QFrame#row, QFrame#mix { background: $glass_pane; border: 1px solid $glass_edge; border-top: 1px solid $glass_edge_top;
    border-radius: 22px; }
QFrame#strip[empty="true"], QFrame#empty { background: transparent; border: 2px dashed $glass_button_edge; }
QFrame#mix[mix="monitor"] { border-color: $glass_listen_edge; border-top-color: $glass_edge_top; }
QFrame#mix[mix="stream"] { border-color: $glass_broadcast_edge; border-top-color: $glass_edge_top; }
QFrame#mixcell[mix="monitor"] { background: $glass_listen; border-color: $glass_listen_edge; }
QFrame#mixcell[mix="stream"] { background: $glass_broadcast; border-color: $glass_broadcast_edge; }
QFrame#statuschip, QFrame#segmented { background: $glass_pane; border: 1px solid $glass_edge; border-top-color: $glass_edge_top;
    border-radius: 14px; }
QFrame#sourcechip, QFrame#chip { background: $glass_button; border: 1px solid $glass_button_edge; border-radius: 10px; }
QFrame#livepanel, QFrame#firstrun, QFrame#detail { background: $glass_pane_strong; border: 1px solid $glass_edge;
    border-top-color: $glass_edge_top; border-radius: 16px; }
QPushButton { background: $glass_button; border: 1px solid $glass_button_edge; border-radius: 12px; }
QPushButton:hover { background: $glass_button_hover; border-color: $glass_edge_top; }
QPushButton:checked { background: $glass_accent; border-color: $accent; }
QPushButton#segment { background: transparent; border: 2px solid transparent; }
QPushButton#segment:checked { background: $glass_accent; color: $accent_text; border: 1px solid $accent; }
QPushButton#plain, QPushButton#quiet { background: transparent; border-color: transparent; }
QPushButton#plain:hover, QPushButton#quiet:hover { background: $glass_button; border-color: $glass_button_edge; }
QPushButton#mute:checked { background: $mute_bg; border: 1px solid $mute; }
QPushButton#addchip, QPushButton#addchannel { background: transparent; border: 1px dashed $glass_edge_top; }
QPushButton#addchip:hover, QPushButton#addchannel:hover { background: $glass_button; border-color: $accent; }
QComboBox { background: $glass_button; border: 1px solid $glass_button_edge; border-radius: 12px; }
QComboBox:hover { border-color: $glass_edge_top; }
QLineEdit#readout { background: $glass_well; border: 1px solid transparent; border-radius: 10px; }
QLineEdit#readout:hover { border-color: $glass_edge_top; }
QLabel#name, QLabel#title { font-weight: 700; }
QWidget#topbar { background: transparent; border-bottom: 1px solid $glass_edge; }
"""

GLASS_STYLE_EXTRA = Template(GLASS_EXTRA)
