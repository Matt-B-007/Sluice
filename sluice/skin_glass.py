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


def readable_alpha(text: str, panel: str, behind: list, start: float, need: float = 4.5) -> float:
    """The least opacity (from ``start`` up) at which ``text`` on ``panel`` laid over every colour in ``behind`` reads at ``need``:1
    (0.11.7: the readability guard; a pane gets more solid where a see-through one would not read)."""
    from . import depth
    alpha = start
    while alpha < 0.96:
        if all(depth.contrast(text, depth.mix(colour, panel, alpha)) >= need for colour in behind):
            return round(alpha, 2)
        alpha += 0.04
    return 0.96


def backdrop_colours(values: dict) -> list:
    """The soft shapes Sluice paints behind Glass panes (when the wallpaper does not show through): the theme's own colours."""
    return [values.get("listen", values["accent"]), values["accent"], values.get("broadcast", values["code"]), values["code"],
            values.get("mute", values["accent"])]


def glass_values(values: dict, see_through: bool = False) -> dict:
    """The see-through colours of the panes and the tints of the backdrop, for a theme (light or dark). ``see_through``: the window
    itself is see-through (KDE, blurred by KWin), so what is behind can be any wallpaper, white or black."""
    from . import depth
    light = depth.luminance(values["panel"]) >= depth.LIGHT_PANEL
    listen, broadcast = values.get("listen", values["accent"]), values.get("broadcast", values["code"])
    bg, panel = values["bg"], values["panel"]
    if see_through:
        tint = 0.45 if light else 0.40  # the window's own tint over the blurred wallpaper
        behind = [depth.mix(wall, bg, tint) for wall in ("#ffffff", "#000000", "#808080")]
    else:
        behind = [depth.mix(bg, depth.mix(bg, colour, 0.55 if not light else 0.35), 1.0) for colour in backdrop_colours(values)] + [bg]
    pane = readable_alpha(values["text"], panel, behind, 0.52 if light else 0.38)
    glow = depth.mix(panel, "#ffffff", 0.10 if not light else 0.30)
    return {
        "glass_see_through": rgba(bg, 0.45 if light else 0.40),
        # the backdrop (a fallback: Sluice paints soft shapes over it, see ui_glass.GlassBackdrop)
        "glass_wash_a": depth.mix(bg, listen, 0.16 if light else 0.20),
        "glass_wash_b": depth.mix(bg, broadcast, 0.12 if light else 0.16),
        "glass_wash_mid": bg,
        # the panes: see-through panel colour, a faint glow from the top, white hairlines (brighter along the top edge)
        "glass_pane": rgba(panel, pane),
        "glass_pane_top": rgba(glow, min(0.96, pane + 0.08)),
        "glass_pane_strong": rgba(panel, min(0.96, pane + 0.25)),
        "glass_edge": rgba("#ffffff", 0.60 if light else 0.10),
        "glass_edge_top": rgba("#ffffff", 0.95 if light else 0.30),
        "glass_button": rgba("#ffffff", 0.45 if light else 0.07),
        "glass_button_hover": rgba("#ffffff", 0.70 if light else 0.13),
        "glass_button_edge": rgba("#ffffff", 0.70) if light else rgba("#ffffff", 0.12),
        "glass_well": rgba("#000000", 0.06 if light else 0.26),
        "glass_listen": rgba(listen, 0.16 if light else 0.14),
        "glass_listen_edge": rgba(listen, 0.50),
        "glass_broadcast": rgba(broadcast, 0.16 if light else 0.14),
        "glass_broadcast_edge": rgba(broadcast, 0.50),
        "glass_accent": rgba(values["accent"], 0.24 if light else 0.22),
        "glass_pane_alpha": pane,
    }


GLASS_EXTRA = """
/* Glass: frosted panes on a tinted backdrop. */
QWidget#root { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $glass_wash_a, stop:0.55 $glass_wash_mid,
    stop:1 $glass_wash_b); }
QWidget#root[seethrough="true"] { background: $glass_see_through; }
QStatusBar[seethrough="true"] { background: $glass_see_through; }
QScrollArea, QScrollArea > QWidget > QWidget, QWidget#channels, QWidget#masters, QWidget#sources { background: transparent; }
QStatusBar { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $glass_wash_mid, stop:1 $glass_wash_b); }
QFrame#strip, QFrame#row, QFrame#mix { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $glass_pane_top, stop:0.35 $glass_pane,
    stop:1 $glass_pane); border: 1px solid $glass_edge; border-top: 1px solid $glass_edge_top; border-radius: 24px; }
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
