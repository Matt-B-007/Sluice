# SPDX-License-Identifier: GPL-3.0-or-later
"""The Nexus look: a deep blue-black window with cyan and coral light, rounded glassy cards, thin glowing outlines and capital-letter
headings. It starts from the Calm style sheet and adds to it, so every part of the window is styled and nothing is left bare.

Part of the Look setting (View > Look). Nexus has its own colours for the built-in Dark theme; every other theme keeps its own colours
and gets Nexus's shapes."""
from __future__ import annotations

from string import Template

NEXUS_DARK = {
    "bg": "#05080f", "panel": "#0b111b", "mix": "#0d1522", "border": "#1b2636", "border_soft": "#1b2636",
    "text": "#e8eef7", "text_dim": "#8a99ae", "text_faint": "#8a99ae", "text_off": "#5d6b80", "title": "#ffffff",
    "strong": "#ffffff", "input": "#070b13", "well": "#070b13", "chip": "#111a28", "button": "#0f1827",
    "button_text": "#e8eef7", "button_border": "#24344a", "hover": "#3a4f6b", "line": "#2a3b52", "accent": "#22e5ff",
    "select": "#0d3a45", "select_soft": "#0a2a33", "select_text": "#ffffff", "popup": "#0b111b", "dialog": "#0a0f18",
    "fill": "#22e5ff", "handle": "#ffffff", "handle_edge": "#ffffff", "handle_hover": "#ffffff", "applied": "#0a2a33",
    "scroll_track": "#0a0f18", "scroll_hover": "#2a3b52", "scroll_press": "#3a4f6b", "row_hover": "#111a28",
    "list_text": "#e8eef7", "check_text": "#b7c3d4", "link": "#22e5ff", "code": "#ffb020", "ok": "#3dff9a",
    "alarm": "#b3262c", "warn": "#ffb020", "error": "#ff6b78", "muted": "#6a7a90", "mute": "#ff5a5f",
    "limiter": "#22e5ff", "linked": "#22e5ff", "on_color": "#05080f",
    "surface2": "#111a28", "border2": "#24344a", "text2": "#b7c3d4", "track": "#182233", "meter_bg": "#070b13",
    "accent_bg": "#0a2f38", "accent_text": "#22e5ff", "mute_bg": "#33121a", "mute_fg": "#ff7b80", "live_bg": "#0b2a1e",
    "live_fg": "#3dff9a", "dashed": "#2a3b52", "focus": "#22e5ff",
}

NEXUS_EXTRA = """
/* Nexus: glass cards with a thin cool outline, capital-letter headings, cyan light on what is on. */
QFrame#strip, QFrame#row, QFrame#mix { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $glass_top, stop:0.4 $panel,
    stop:1 $glass_bottom); border: 1px solid $glass_outline; border-radius: 20px; }
QWidget#topbar { border-bottom: 1px solid $accent_soft; }
QFrame#statuschip, QFrame#segmented { border-color: $accent_soft; }
QFrame#mix[mix="monitor"] { border-color: $listen_edge; }
QFrame#mix[mix="stream"] { border-color: $broadcast_edge; }
QLabel#name, QLabel#title { font-weight: 700; letter-spacing: 0.4px; color: $title; }
QLabel#appname { font-size: 20px; font-weight: 800; letter-spacing: 3px; color: $title; }
QLabel#tag { font-weight: 700; letter-spacing: 1px; }
QLabel#tag[narrow="true"] { letter-spacing: 0.4px; }
QLabel#mixheading { letter-spacing: 1.4px; }
QPushButton { border-radius: 12px; border: 1px solid $border2; }
QPushButton:hover { border-color: $accent; }
QPushButton:checked { border-color: $accent; }
QPushButton#mute:checked { background: $mute_bg; border: 1px solid $mute; }
QPushButton#link:checked { background: $accent_bg; border: 1px solid $accent; }
QPushButton#limiter:checked { background: $accent_bg; border: 1px solid $accent; }
QPushButton#primary { background: $accent; color: $on_color; border-color: transparent; }
QPushButton#addchip, QPushButton#addchannel { border: 1px dashed $accent; color: $accent_text; background: transparent; }
QPushButton#addchip:hover, QPushButton#addchannel:hover { background: $accent_bg; border-color: $accent; color: $accent_text; }
QFrame#segmented { border: 1px solid $border2; border-radius: 14px; background: rgba(255,255,255,0.03); }
QPushButton#segment:checked { background: $accent_bg; color: $accent_text; border: 1px solid $accent; }
QFrame#statuschip { border: 1px solid $accent_soft; border-radius: 14px; background: rgba(255,255,255,0.03); }
QFrame#sourcechip, QFrame#chip { background: $surface2; border: 1px solid $border2; border-radius: 10px; }
QLabel#livechip { background: $live_bg; color: $live_fg; border: 1px solid $live_fg; }
QComboBox { border: 1px solid $border2; }
QComboBox:hover { border-color: $accent; }
QLineEdit#readout:hover { border-color: $accent; }
QMenu { border: 1px solid $border2; }
QMenu::item:selected { background: $accent_bg; color: $accent_text; }
QToolTip { border: 1px solid $accent; }
QWidget#channels, QWidget#masters { background: transparent; }
"""

NEXUS_STYLE_EXTRA = Template(NEXUS_EXTRA)

CORAL_DARK, CORAL_LIGHT = "#ff7a59", "#c4472a"   # Broadcast in Nexus, when the theme has no second colour of its own


def glass_values(values: dict) -> dict:
    """The colours of Nexus's glass for a theme: a lit top, a deeper bottom and an outline from the accent (``depth``)."""
    from . import depth
    d = depth.depth_colors(values)
    light = d["light"]
    return {"glass_top": depth.shade(values["panel"], 0.6 if light else 0.06),
            "glass_bottom": depth.shade(values["panel"], -0.03 if light else -0.3),
            "glass_outline": d["outline"]}


def mix_pair(colors: dict) -> tuple:
    """Listen and Broadcast in Nexus: Listen in the accent (cyan on Nexus's own colours), Broadcast in the theme's second colour
    (its code colour) when that stands apart from the accent, otherwise coral."""
    from . import depth
    listen = colors["accent"]
    second = colors["code"]
    light = depth.luminance(colors["panel"]) >= depth.LIGHT_PANEL
    if depth.contrast(second, listen) < 1.35 or abs(_hue(second) - _hue(listen)) < 0.08:
        second = CORAL_LIGHT if light else CORAL_DARK
    return listen, second


def _hue(color: str) -> float:
    import colorsys
    from . import depth
    return colorsys.rgb_to_hls(*depth._rgb(color))[0]
