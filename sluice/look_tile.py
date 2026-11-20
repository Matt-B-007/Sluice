# SPDX-License-Identifier: GPL-3.0-or-later
"""The Tile look: every channel is a raised key, like the keys of a keyboard sitting in a tray: a face lit from above, a thick lower
edge (its skirt) and a soft shadow under it. Sliders run in grooves pressed into the face, with raised white handles; a button that is
on (muted, linked) looks pushed in. Colour marks two things only: the channel's identity (the tint of its icon well) and the live
signal in its grooves.

The tiles themselves are in ``ui_tile``; this module holds the colours and the style sheet rules that go after the Calm sheet.

Part of the Look setting (View > Look). With View > Tile colours on (the default), the built-in themes show the look's own keys:
white keys on a silver tray for Light and Paper, graphite keys on a black tray for the dark ones. Off, or with High contrast or an
imported theme, the keys take the theme's own colours."""
from __future__ import annotations

from string import Template

# White keys on a silver tray (Light and Paper, with Tile colours on).
TILE_LIGHT = {
    "bg": "#e6e9ed", "panel": "#f8f9fa", "mix": "#f8f9fa", "border": "#d3d8de", "border_soft": "#dde1e6",
    "text": "#1d232a", "text_dim": "#56616c", "text_faint": "#56616c", "text_off": "#7d8791", "title": "#11161c",
    "strong": "#11161c", "input": "#ffffff", "well": "#dde1e6", "chip": "#eef1f4", "button": "#eef1f4",
    "button_text": "#1d232a", "button_border": "#d3d8de", "hover": "#8f98a2", "line": "#c3c9d0", "accent": "#2f6fe0",
    "select": "#cfe0ff", "select_soft": "#e3ecff", "select_text": "#11161c", "popup": "#ffffff", "dialog": "#f3f5f7",
    "fill": "#2f6fe0", "handle": "#ffffff", "handle_edge": "#c3c9d0", "handle_hover": "#f5f7f9", "applied": "#e3ecff",
    "scroll_track": "#e6e9ed", "scroll_hover": "#aeb6bf", "scroll_press": "#8f98a2", "row_hover": "#eef1f4",
    "list_text": "#1d232a", "check_text": "#2e3748", "link": "#2f6fe0", "code": "#8a5a00", "ok": "#1f9d5c",
    "alarm": "#c62828", "warn": "#8a5a00", "error": "#cc2f2f", "muted": "#7d8791", "mute": "#cc2f2f",
    "limiter": "#1fb3a3", "linked": "#56616c", "on_color": "#ffffff",
    "surface2": "#eef1f4", "border2": "#d3d8de", "text2": "#56616c", "track": "#dde1e6", "meter_bg": "#dde1e6",
    "accent_bg": "#e3ecff", "accent_text": "#2459b8", "mute_bg": "#fbe1e1", "mute_fg": "#c42b2b", "live_bg": "#ddf5e8",
    "live_fg": "#1a7f4b", "dashed": "#aeb6bf", "focus": "#2f6fe0",
}
# Graphite keys on a black tray (Dark, Retro Purple, Midnight Blue and Amber Console, with Tile colours on).
TILE_DARK = {
    "bg": "#0a0d10", "panel": "#2a2f35", "mix": "#2a2f35", "border": "#20252a", "border_soft": "#1c2125",
    "text": "#eef2f5", "text_dim": "#a3aeb8", "text_faint": "#a3aeb8", "text_off": "#76818b", "title": "#ffffff",
    "strong": "#ffffff", "input": "#14171b", "well": "#14171b", "chip": "#353c43", "button": "#353c43",
    "button_text": "#eef2f5", "button_border": "#20252a", "hover": "#55606a", "line": "#3a424a", "accent": "#4c8dff",
    "select": "#1d3359", "select_soft": "#172540", "select_text": "#ffffff", "popup": "#22272c", "dialog": "#1b1f23",
    "fill": "#4c8dff", "handle": "#f5f7f9", "handle_edge": "#f5f7f9", "handle_hover": "#ffffff", "applied": "#172540",
    "scroll_track": "#15181b", "scroll_hover": "#4a535c", "scroll_press": "#5a646e", "row_hover": "#353c43",
    "list_text": "#eef2f5", "check_text": "#c5ced6", "link": "#7fb0ff", "code": "#f0c03a", "ok": "#2fcf7a",
    "alarm": "#b3262c", "warn": "#f0c03a", "error": "#ff7b7b", "muted": "#76818b", "mute": "#ff7b7b",
    "limiter": "#35d0c0", "linked": "#a3aeb8", "on_color": "#0a0d10",
    "surface2": "#353c43", "border2": "#20252a", "text2": "#a3aeb8", "track": "#14171b", "meter_bg": "#14171b",
    "accent_bg": "#172540", "accent_text": "#7fb0ff", "mute_bg": "#3a1d21", "mute_fg": "#ff7b7b", "live_bg": "#10261b",
    "live_fg": "#2fcf7a", "dashed": "#4a535c", "focus": "#4c8dff",
}

# A channel's identity colour: the tint of its icon well and the colour of its live signal. Channels Sluice does not know keep
# the colour they were given when they were added.
CHANNEL_TINTS = {"mic": "#4c8dff", "game": "#ff8a3d", "chat": "#a77bff", "browser": "#2fcf7a", "music": "#ff5c8a",
                 "system": "#f0c03a"}
CHANNEL_ICONS = {"mic": "mic", "game": "gamepad", "chat": "chat", "browser": "globe", "music": "note", "system": "bell"}
LANE_ICONS = {"monitor": "headphones", "stream": "broadcast", "recording": "mic"}  # Listen, Broadcast, Recording

UI_FONT = '"Inter", "Inter Variable", "Noto Sans", "DejaVu Sans", sans-serif'
VALUE_FONT = '"JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", monospace'
VALUE_FAMILIES = ["JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", "monospace"]


def channel_color(channel) -> str:
    return CHANNEL_TINTS.get(channel.id, channel.color)


def channel_icon(channel) -> str:
    """The drawing in the channel's icon well ("" for a channel Sluice does not know: the well shows its first letter)."""
    if channel.id in CHANNEL_ICONS:
        return CHANNEL_ICONS[channel.id]
    return "mic" if channel.devices and not channel.apps else ""


def is_light(color: str) -> bool:
    """Whether a #rrggbb colour is a light one (decides how strong the shadows under the keys are)."""
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    red, green, blue = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255 > 0.6


def key_colors(values: dict, mix) -> dict:
    """The colours of a key, made from a theme's own colours: its face (lighter at the top), the skirt under it, the small raised
    keys on it (buttons), how they look pushed in, the groove pressed into it and the tray the keys sit in."""
    panel, bg, raised = values["panel"], values["bg"], values["surface2"]
    light = is_light(panel)
    if light:
        return {"face_top": mix(panel, "#ffffff", 0.7), "face_bottom": mix(panel, "#000000", 0.03),
                "skirt": mix(panel, "#000000", 0.15), "skirt_dark": mix(panel, "#000000", 0.23),
                "key_top": mix(raised, "#ffffff", 0.8), "key_bottom": mix(raised, "#000000", 0.02),
                "key_edge": mix(panel, "#000000", 0.13), "key_skirt": mix(panel, "#000000", 0.2),
                "key_pressed": mix(raised, "#000000", 0.06), "key_pressed_top": mix(panel, "#000000", 0.18),
                "tray_top": mix(bg, "#ffffff", 0.6), "tray_bottom": mix(bg, "#000000", 0.04), "tray_lip": mix(bg, "#000000", 0.15),
                "groove": values["track"]}
    return {"face_top": mix(panel, "#ffffff", 0.05), "face_bottom": mix(panel, "#000000", 0.1),
            "skirt": mix(panel, "#000000", 0.45), "skirt_dark": mix(panel, "#000000", 0.62),
            "key_top": mix(raised, "#ffffff", 0.05), "key_bottom": mix(raised, "#000000", 0.1),
            "key_edge": mix(panel, "#000000", 0.25), "key_skirt": mix(panel, "#000000", 0.5),
            "key_pressed": mix(panel, "#000000", 0.18), "key_pressed_top": mix(panel, "#000000", 0.55),
            "tray_top": mix(bg, "#ffffff", 0.11), "tray_bottom": mix(bg, "#ffffff", 0.035), "tray_lip": mix(bg, "#000000", 0.5),
            "groove": values["track"]}


def tile_colors(values: dict, mix) -> dict:
    """The extra values the Tile style sheet rules use."""
    out = key_colors(values, mix)
    out.update({"tile_edge": out["key_edge"], "tile_raised": out["key_bottom"], "tile_track": values["track"],
                "tile_value_font": VALUE_FONT, "tile_ui_font": UI_FONT})
    return out


_paint_cache: tuple = (None, None)


def paint_colors() -> dict:
    """The colours the tiles paint with, from the theme in use. Worked out once per theme change (painting asks for them on every
    meter frame, so this must cost nothing)."""
    global _paint_cache
    from . import themes

    generation = themes.generation()
    if _paint_cache[0] == generation:
        return _paint_cache[1]
    c = themes.color
    light = is_light(c("panel"))
    keys = key_colors({"panel": c("panel"), "bg": c("bg"), "surface2": c("surface2"), "track": c("track")}, themes.mix)
    colors = {
        **keys, "surface": c("panel"), "edge": keys["key_edge"], "raised": c("surface2"),
        "track": c("track"), "stripe": themes.mix(c("track"), c("text"), 0.12 if not light else 0.16), "text": c("text"),
        "text2": c("text2"), "text_off": c("text_off"), "red": c("mute_fg"), "handle": "#ffffff" if light else c("handle"),
        "handle_bottom": "#e4e8ec" if light else themes.mix(c("handle"), "#000000", 0.16), "handle_edge": c("handle_edge"),
        "handle_muted": c("text_off"), "focus": c("focus"), "dashed": c("dashed"),
        "shadow": 0.13 if light else 0.5, "groove_shadow": 0.2 if light else 0.6, "floor": c("bg"), "light": light,
    }
    _paint_cache = (generation, colors)
    return colors


_KEY = """background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $key_top, stop:1 $key_bottom);
    border: 1px solid $key_edge; border-bottom: 3px solid $key_skirt"""
_PUSHED = """background: $key_pressed; border: 1px solid $key_edge; border-top: 3px solid $key_pressed_top"""

TILE_STYLE_EXTRA = Template("""
/* Tile: raised keys. The keys paint their own face, skirt and shadow; small buttons on them are raised keys too (a thick lower
   border is their skirt) and look pushed in while on (the thick border moves to the top). */
QWidget { font-family: $tile_ui_font; }
QFrame#strip, QFrame#row, QFrame#mix { background: transparent; border: none; }
QFrame#tileframe, QWidget#tiletray, QWidget#minitile { background: transparent; border: none; }
QWidget#tilegrip, QWidget#tilelanes, QWidget#tiledetails, QWidget#tilefoot, QWidget#tilerow { background: transparent; }
QLabel#tilename { font-size: 13px; font-weight: 600; color: $text; background: transparent; }
QLabel#tilesource { font-size: 11px; color: $text2; background: transparent; }
QLabel#tilesource[clipped="true"] { color: $mute_fg; }
QLabel#tilehint { font-size: 11px; color: $text2; background: transparent; }
QLabel#tilesection { font-size: 10px; font-weight: 600; letter-spacing: 1px; color: $text2; background: transparent; }
QLabel#tileappname { font-size: 12px; color: $text; background: transparent; }
QLabel#tilenote { font-size: 11px; color: $text2; background: transparent; }
QLineEdit#tilevalue, QLabel#tilevalue { font-family: $tile_value_font; font-size: 11px; color: $text; background: transparent;
    border: 1px solid transparent; border-radius: 6px; padding: 0 2px; }
QLineEdit#tilevalue:hover { border-color: $key_edge; }
QLineEdit#tilevalue:focus { border-color: $focus; background: $groove; }
QLineEdit#tilevalue[muted="true"], QLabel#tilevalue[muted="true"] { color: $mute_fg; }
/* sizes here, not in code: a style sheet's min-height wins over a fixed size, and the Calm sheet asks for 38 px buttons.
   A raised key's borders are 1 + 3 px tall, so a 28 px key has 24 px inside. */
QPushButton#tileicon, QPushButton#tilemute { min-width: 26px; max-width: 26px; min-height: 24px; max-height: 24px; padding: 0;
    border-radius: 9px; """ + _KEY + """; }
QPushButton#tileicon:hover, QPushButton#tilemute:hover { border-color: $hover; border-bottom-color: $key_skirt; }
QPushButton#tileicon:checked, QPushButton#tileicon:pressed { """ + _PUSHED + """; background: $accent_bg; }
QPushButton#tilemute:checked, QPushButton#tilemute:pressed { """ + _PUSHED + """; background: $mute_bg; }
QPushButton#tileplain { min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; background: transparent;
    border: 1px solid transparent; border-radius: 8px; }
QPushButton#tileplain:hover { background: $key_bottom; border-color: $key_edge; }
QPushButton#tileplain::menu-indicator { image: none; width: 0; }
QPushButton#tilefx { min-width: 0; min-height: 24px; max-height: 24px; padding: 0 10px; border-radius: 9px; font-size: 12px;
    font-weight: 500; color: $text; text-align: left; """ + _KEY + """; }
QPushButton#tilefx[none="true"] { color: $text2; }
QPushButton#tilefx:hover { border-color: $hover; border-bottom-color: $key_skirt; }
QPushButton#tilefx:pressed { """ + _PUSHED + """; }
QPushButton#fxchip { min-width: 0; min-height: 20px; max-height: 20px; padding: 0 10px; border-radius: 12px; font-size: 11px;
    font-weight: 500; color: $text_off; background: $groove; border: 1px solid $key_edge; border-top: 3px solid $key_pressed_top; }
QPushButton#fxchip:checked { color: $text; """ + _KEY + """; }
QPushButton#fxchip:hover { border-color: $hover; }
QPushButton#fxadd { min-width: 0; min-height: 22px; max-height: 22px; padding: 0 10px; border-radius: 12px; font-size: 11px;
    font-weight: 500; background: transparent; border: 1px dashed $dashed; color: $text2; }
QPushButton#tileadd { min-width: 0; min-height: 24px; max-height: 24px; padding: 0 10px; border-radius: 12px; font-size: 11px;
    font-weight: 500; background: transparent; border: 1px dashed $dashed; color: $text2; }
QPushButton#fxadd:hover, QPushButton#tileadd:hover { border-color: $text2; color: $text; }
QPushButton#tileadd::menu-indicator { image: none; width: 0; }
QPushButton#tilemove { min-width: 0; min-height: 20px; max-height: 20px; padding: 0 9px; border-radius: 8px; font-size: 11px;
    font-weight: 500; color: $text; """ + _KEY + """; }
QPushButton#tilemove:hover { border-color: $hover; border-bottom-color: $key_skirt; }
QPushButton#tilemove:pressed { """ + _PUSHED + """; }
QPushButton#tilemove::menu-indicator { image: none; width: 0; }
QPushButton#tileicon:focus, QPushButton#tilemute:focus, QPushButton#tilefx:focus, QPushButton#tilemove:focus,
QPushButton#fxchip:focus { border-left-color: $focus; border-right-color: $focus; border-top-color: $focus; }
QPushButton#tileplain:focus, QPushButton#fxadd:focus, QPushButton#tileadd:focus { border: 1px solid $focus; }
QPushButton#addchannel { background: transparent; border: 1px dashed $dashed; border-radius: 12px; color: $text2; }
QPushButton#addchannel:hover { border-color: $text2; color: $text; }
QWidget#topbar { border-bottom: 1px solid $key_edge; }
QFrame#segmented { background: $groove; border: 1px solid $key_edge; border-radius: 10px; }
QPushButton#segment:checked { color: $text; border-radius: 8px; """ + _KEY + """; }
QFrame#statuschip { border: 1px solid $key_edge; border-radius: 10px; }
QWidget#freecanvas { background: transparent; }
QFrame#nexusnode { background: $panel; border: 1px solid $key_edge; border-radius: 12px; }
QFrame#nexusnode:focus, QFrame#nexusnode[open="true"] { border-color: $focus; }
QLabel#nodechips { font-family: $tile_value_font; font-size: 10px; color: $text2; background: transparent; }
QPushButton { border-radius: 9px; }
QFrame#sourcechip, QFrame#chip { border-radius: 8px; }
""")
