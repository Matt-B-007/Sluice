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
    "bg": "#b9bbc0", "panel": "#f6f7f8", "mix": "#f6f7f8", "border": "#d3d8de", "border_soft": "#dde1e6",
    "text": "#1d232a", "text_dim": "#56616c", "text_faint": "#56616c", "text_off": "#7d8791", "title": "#11161c",
    "strong": "#11161c", "input": "#ffffff", "well": "#dde1e6", "chip": "#eef1f4", "button": "#eef1f4",
    "button_text": "#1d232a", "button_border": "#d3d8de", "hover": "#8f98a2", "line": "#c3c9d0", "accent": "#2f6fe0",
    "select": "#cfe0ff", "select_soft": "#e3ecff", "select_text": "#11161c", "popup": "#ffffff", "dialog": "#f3f5f7",
    "fill": "#2f6fe0", "handle": "#ffffff", "handle_edge": "#c3c9d0", "handle_hover": "#f5f7f9", "applied": "#e3ecff",
    "scroll_track": "#b9bbc0", "scroll_hover": "#8f949b", "scroll_press": "#8f98a2", "row_hover": "#eef1f4",
    "list_text": "#1d232a", "check_text": "#2e3748", "link": "#2f6fe0", "code": "#8a5a00", "ok": "#1f9d5c",
    "alarm": "#c62828", "warn": "#8a5a00", "error": "#cc2f2f", "muted": "#7d8791", "mute": "#cc2f2f",
    "limiter": "#1fb3a3", "linked": "#56616c", "on_color": "#ffffff",
    "surface2": "#eef1f4", "border2": "#d3d8de", "text2": "#56616c", "track": "#dde1e6", "meter_bg": "#dde1e6",
    "accent_bg": "#e3ecff", "accent_text": "#2459b8", "mute_bg": "#fbe1e1", "mute_fg": "#c42b2b", "live_bg": "#ddf5e8",
    "live_fg": "#1a7f4b", "dashed": "#767d86", "focus": "#2f6fe0",
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
    """The channel's colour as drawn in the theme in use (darker shades of it on light themes, so it stands out in a groove)."""
    from . import depth, themes
    return depth.channel_tint(CHANNEL_TINTS.get(channel.id, channel.color), themes._current)


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


def is_flat(values: dict) -> bool:
    """High contrast (and any theme like it, with borders that stand out 3 to 1): plain fills, depth only from a thick lower edge."""
    from .depth import contrast
    return contrast(values["border"], values["panel"]) >= 3.0


def key_colors(values: dict, mix=None) -> dict:
    """The colours of a key, made from a theme's own colours by ``depth`` (0.11.5): its face (lit at the top), the skirt and rim
    under it, the small raised keys on it (buttons), how they look pushed in, the groove pressed into it and the tray the keys sit in."""
    from . import depth

    d = depth.depth_colors(values, flat=is_flat(values) if "border" in values else False)
    light = d["light"]
    return {
        "face_top": d["key_top"], "face_bottom": d["key_bottom"], "skirt": d["key_skirt"], "skirt_dark": d["key_rim"],
        "key_top": d["button_top"], "key_bottom": d["button_bottom"], "key_edge": d["key_edge"], "key_skirt": d["key_skirt"],
        "key_pressed": depth.shade(values["panel"], -0.06 if light else -0.3),
        "key_pressed_top": depth.shade(values["panel"], -0.2 if light else -0.6),
        "tray_top": d["tray_top"], "tray_bottom": d["tray_bottom"], "tray_lip": d["tray_lip"], "groove": d["groove"],
        "shadow_color": d["shadow"], "shadow_alpha": d["shadow_alpha"], "contact_alpha": d["contact_alpha"],
        "highlight_alpha": d["highlight_alpha"], "edge_light": d["edge_light"], "flat": d["flat"],
        "knob_top": d["knob_top"], "knob_bottom": d["knob_bottom"], "knob_ring": d["knob_ring"],
    }


def tile_colors(values: dict, mix) -> dict:
    """The extra values the Tile style sheet rules use."""
    out = key_colors(values, mix)
    out.update({"tile_edge": out["key_edge"], "tile_raised": out["key_bottom"], "tile_track": values["track"],
                "tile_value_font": VALUE_FONT, "tile_ui_font": UI_FONT})
    light = is_light(values["panel"])
    out.update(lcd_colors(light))
    # backlit keys (0.12.2): a key that is on glows from inside, red for a mute and green for the limiter
    out.update({"key_lit_red_top": "#ffd9d3" if light else "#5a2422", "key_lit_red_bottom": "#f3bdb4" if light else "#3e1816",
                "key_lit_red_edge": "#d98a7f" if light else "#7a2a24", "key_lit_green_top": "#e2f7e8" if light else "#2b3a2e",
                "key_lit_green_bottom": "#c3e9cf" if light else "#1f2a22", "key_lit_green_edge": "#8fc9a2" if light else "#2f5a3b",
                "key_lit_green_ink": "#17733a" if light else "#5cf08a"})
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
    keys = key_colors(themes._current)
    colors = {
        **keys, "surface": c("panel"), "edge": keys["key_edge"], "raised": c("surface2"),
        "track": keys["groove"], "stripe": themes.mix(keys["groove"], c("text"), 0.12 if not light else 0.16), "text": c("text"),
        "text2": c("text2"), "text_off": c("text_off"), "red": c("mute_fg"), "handle": "#ffffff" if light else c("handle"),
        "handle_bottom": "#e4e8ec" if light else themes.mix(c("handle"), "#000000", 0.16), "handle_edge": c("handle_edge"),
        "handle_muted": c("text_off"), "focus": c("focus"), "dashed": c("dashed"),
        "shadow": keys["shadow_alpha"] * 0.5, "groove_shadow": 0.22 if light else 0.65, "floor": c("bg"), "light": light,
        # 0.12.2: metal fader caps and LED meters
        "cap_stops": CAP_LIGHT if light else CAP_DARK,
        "led_green": "#2fbf5a" if light else "#39d353", "led_amber": "#e0a21b" if light else "#f2c230",
        "led_red": "#d6362b" if light else "#ff4d3d", "led_off_alpha": 60 if light else 38,
    }
    _paint_cache = (generation, colors)
    return colors


# 0.12.2: a fader cap is brushed metal with a crease across its middle (lighter on the graphite keys, darker on the silver ones)
CAP_DARK = ((0.0, "#9ea2aa"), (0.46, "#6c7078"), (0.5, "#4e5158"), (1.0, "#7a7e86"))
CAP_LIGHT = ((0.0, "#6a6d74"), (0.46, "#45484e"), (0.5, "#33353a"), (1.0, "#50535a"))


def lcd_colors(light_tray: bool) -> dict:
    """0.12.2: the name strip at the top of each tile is a little LCD: green-black glass on the graphite keys, pale green on the silver
    ones. The channel's name is lit in its own colour."""
    if light_tray:
        return {"lcd_top": "#e6f3e9", "lcd_bottom": "#c9e3d1", "lcd_edge": "#9fb3a5", "lcd_text": "#22402c", "lcd_dim": "#4f6e59"}
    return {"lcd_top": "#0d1410", "lcd_bottom": "#080c09", "lcd_edge": "#050706", "lcd_text": "#cfe9d6", "lcd_dim": "#6f8f78"}


def lcd_caps(label) -> None:
    """An LCD shows its name in capitals, as hardware does (the text itself is unchanged, for screen readers and renaming)."""
    from PySide6.QtGui import QFont
    font = label.font()
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    label.setFont(font)


def lcd_ink(tint: str, light_tray: bool) -> str:
    """A channel's name colour on its LCD: a lit pastel of its colour on the dark glass, a deep shade of it on the pale one."""
    from . import themes
    return themes.mix(tint, "#000000", 0.45) if light_tray else themes.mix(tint, "#ffffff", 0.3)


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
QLabel#tilename { font-family: $tile_value_font; font-size: 13px; font-weight: 600; letter-spacing: 1px; color: $lcd_text;
    background: transparent; }
QLabel#tilesource { font-family: $tile_value_font; font-size: 12px; color: $lcd_dim; background: transparent; }
/* 0.12.2: the name strip is a small LCD, recessed into the key */
QFrame#tilelcd { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $lcd_top, stop:1 $lcd_bottom);
    border: 1px solid $lcd_edge; border-top: 2px solid $lcd_edge; border-radius: 6px; }
QLabel#tilesource[clipped="true"] { color: $mute_fg; }
QLabel#tilehint { font-size: 13px; color: $text2; background: transparent; }
QLabel#tilesection { font-size: 12px; font-weight: 600; letter-spacing: 1px; color: $text2; background: transparent; }
QLabel#tileappname { font-size: 13px; color: $text; background: transparent; }
QLabel#tilenote { font-size: 13px; color: $text2; background: transparent; }
QLineEdit#tilevalue, QLabel#tilevalue { font-family: $tile_value_font; font-size: 12px; color: $text; background: transparent;
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
QPushButton#tilemute:checked, QPushButton#tilemute:pressed { """ + _PUSHED + """;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $key_lit_red_top, stop:1 $key_lit_red_bottom); border-color: $key_lit_red_edge; }
QPushButton#tileplain { min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; background: transparent;
    border: 1px solid transparent; border-radius: 8px; }
QPushButton#tileplain:hover { background: $key_bottom; border-color: $key_edge; }
QPushButton#tileplain::menu-indicator { image: none; width: 0; }
QPushButton#tilefx { min-width: 0; min-height: 24px; max-height: 24px; padding: 0 10px; border-radius: 9px; font-size: 13px;
    font-weight: 500; color: $text; text-align: left; """ + _KEY + """; }
QPushButton#tilefx[none="true"] { color: $text2; }
QPushButton#tilefx:hover { border-color: $hover; border-bottom-color: $key_skirt; }
QPushButton#tilefx:pressed { """ + _PUSHED + """; }
QPushButton#fxchip { min-width: 0; min-height: 20px; max-height: 20px; padding: 0 10px; border-radius: 12px; font-size: 12px;
    font-weight: 500; color: $text_off; background: $groove; border: 1px solid $key_edge; border-top: 3px solid $key_pressed_top; }
QPushButton#fxchip:checked { color: $text; """ + _KEY + """; }
QPushButton#fxchip:hover { border-color: $hover; }
QPushButton#fxadd { min-width: 0; min-height: 22px; max-height: 22px; padding: 0 10px; border-radius: 12px; font-size: 12px;
    font-weight: 500; background: transparent; border: 1px dashed $dashed; color: $text2; }
QPushButton#tileadd { min-width: 0; min-height: 24px; max-height: 24px; padding: 0 10px; border-radius: 12px; font-size: 12px;
    font-weight: 500; background: transparent; border: 1px dashed $dashed; color: $text2; }
QPushButton#fxadd:hover, QPushButton#tileadd:hover { border-color: $text2; color: $text; }
QPushButton#tileadd::menu-indicator { image: none; width: 0; }
QPushButton#tilelimiter { min-width: 0; min-height: 18px; max-height: 18px; padding: 0 9px; border-radius: 8px; font-size: 12px;
    font-weight: 600; color: $text2; """ + _KEY + """; }
QPushButton#tilelimiter:hover { border-color: $hover; border-bottom-color: $key_skirt; }
QPushButton#tilelimiter:checked { """ + _PUSHED + """; color: $key_lit_green_ink;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $key_lit_green_top, stop:1 $key_lit_green_bottom); border-color: $key_lit_green_edge; }
QPushButton#tilelimiter:focus { border-left-color: $focus; border-right-color: $focus; border-top-color: $focus; }
QPushButton#tilemove { min-width: 0; min-height: 20px; max-height: 20px; padding: 0 9px; border-radius: 8px; font-size: 12px;
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
QFrame#nexusnode { background: $panel; border: 1px solid $key_edge; border-radius: 12px; }
QFrame#nexusnode:focus, QFrame#nexusnode[open="true"] { border-color: $focus; }
QLabel#nodechips { font-family: $tile_value_font; font-size: 11px; color: $text2; background: transparent; }
QPushButton { border-radius: 9px; }
QFrame#sourcechip, QFrame#chip { border-radius: 8px; }
""")
