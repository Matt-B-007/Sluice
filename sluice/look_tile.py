# SPDX-License-Identifier: GPL-3.0-or-later
"""The Tile look: every card is a raised tile with a lit top edge and a dark lip under it, sitting on the window like tiles on a floor.
It is all style sheet (no effects, nothing painted by Sluice), so it costs the same as the Calm look. It starts from the Calm sheet
and adds to it, and it takes its colours from the theme in use: dark tiles on a dark theme, pale tiles on a light one.

Part of the Look setting (View > Look). Free works in this look as it does in Nexus: each channel is a tile you can drag, and
clicking it folds its card out beside it."""
from __future__ import annotations

from string import Template


def is_light(color: str) -> bool:
    """Whether a #rrggbb colour is a light one (decides how the lit edge and the lip are made from the theme's own panel colour)."""
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    red, green, blue = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255 > 0.6


def tile_colors(values: dict, mix) -> dict:
    """The few extra colours the Tile rules use, made from the theme's panel colour: the lit top edge, the lip and the top of the face."""
    panel = values["panel"]
    if is_light(panel):
        return {"tile_hi": mix(panel, "#ffffff", 0.9), "tile_lip": mix(panel, "#000000", 0.24), "tile_top": mix(panel, "#ffffff", 0.55),
                "tile_edge": mix(panel, "#000000", 0.10)}
    return {"tile_hi": mix(panel, "#ffffff", 0.16), "tile_lip": mix(panel, "#000000", 0.6), "tile_top": mix(panel, "#ffffff", 0.06),
            "tile_edge": mix(panel, "#000000", 0.25)}


TILE_STYLE_EXTRA = Template("""
/* Tile: raised tiles. A lit top edge, a dark lip underneath, a face that is a little lighter at the top. */
QFrame#strip, QFrame#row, QFrame#mix {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $tile_top, stop:1 $panel);
    border: 1px solid $tile_edge; border-top: 2px solid $tile_hi; border-bottom: 6px solid $tile_lip; border-radius: 14px; }
QFrame#nexusnode {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $tile_top, stop:1 $panel);
    border: 1px solid $tile_edge; border-top: 2px solid $tile_hi; border-bottom: 6px solid $tile_lip; border-radius: 14px; }
QFrame#nexusnode:hover { border-top-color: $accent; }
QFrame#nexusnode:focus { border-top-color: $accent; }
QLabel#nodechips { font-family: monospace; font-size: 10px; color: $text2; background: transparent; }
QFrame#nexusnode[open="true"] { border-top-color: $accent; border-bottom-color: $accent; }
QWidget#topbar { border-bottom: 2px solid $tile_lip; }
QWidget#freecanvas { background: transparent; }
QFrame#segmented, QFrame#statuschip { border: 1px solid $tile_edge; border-bottom: 3px solid $tile_lip; border-radius: 12px; }
QPushButton { border-radius: 9px; }
QPushButton#segment:checked { border: 1px solid $accent; }
QFrame#sourcechip, QFrame#chip { border-radius: 8px; }
""")
