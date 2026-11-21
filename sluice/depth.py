# SPDX-License-Identifier: GPL-3.0-or-later
"""Depth: the colours that make things look raised, sunk in or lit, worked out from any theme's own colours.

Every look uses these (0.11.5): Tile's raised keys and their tray, Nexus's glass cards, outlines and glow, Calm's soft card shadows,
and the desktop widgets. A theme file does not have to list any of them: they come from its background, card, text and accent
colours by the rules below. A theme file can still set any of them by hand (``DEPTH_TOKENS``), and what it sets is kept.

The rules, so that every one of the 28 themes looks right:

- Shading keeps the colour's hue and saturation and changes only its lightness, so a strongly coloured theme (Blueprint, Synthwave,
  Streamer Purple) shades into darker and lighter versions of its own colour instead of turning grey.
- Shadows are a deep version of the theme's own background colour, never plain black, so warm and coloured themes keep their warmth.
- Very dark backgrounds (OLED Black, Terminal Green, Neon Tokyo, Aurora) cannot show a shadow: there the depth comes from a lit top
  edge and a slightly lighter key face, and the tray is a touch lighter than the floor instead of darker.
- High contrast stays flat and plain: solid fills and borders, with depth shown only by a thicker lower edge.
- On light themes there is no glow (neon on white looks washed out), and channel colours are darkened until they stand out against
  the grooves they sit in.
"""
from __future__ import annotations

import colorsys
from functools import lru_cache

# Colours a theme file may give by hand. Anything else is worked out (see ``depth_colors``).
DEPTH_TOKENS = (
    "key_top", "key_bottom", "key_skirt", "key_rim", "key_edge", "tray_top", "tray_bottom", "tray_lip", "groove", "shadow",
    "knob_top", "knob_bottom", "knob_ring", "outline",
)
VERY_DARK = 0.006    # a background darker than this (relative luminance) cannot show a shadow
LIGHT_PANEL = 0.4    # a card lighter than this is a light theme (the same line ``themes.complete`` draws)
GRAPHIC_CONTRAST = 3.0   # the usual bar for drawn things (a coloured signal in a groove, a handle on its track)


def _rgb(value: str) -> tuple:
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    r, g, b = _rgb(value)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def shade(value: str, amount: float) -> str:
    """Lighter (``amount`` > 0, toward white) or darker (< 0, toward black) by changing lightness only: hue and saturation stay."""
    h, lightness, s = colorsys.rgb_to_hls(*_rgb(value))
    if amount >= 0:
        lightness = lightness + (1.0 - lightness) * amount
    else:
        lightness = lightness * (1.0 + amount)
    return _hex(colorsys.hls_to_rgb(h, lightness, s))


def with_lightness(value: str, lightness: float, saturation: float = 1.0) -> str:
    """The same hue at a set lightness (0..1), its saturation scaled by ``saturation``."""
    h, _l, s = colorsys.rgb_to_hls(*_rgb(value))
    return _hex(colorsys.hls_to_rgb(h, lightness, s * saturation))


def mix(a: str, b: str, amount: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * amount for x, y in zip(ra, rb)))


def stand_out(color: str, against: str, minimum: float = GRAPHIC_CONTRAST) -> str:
    """``color`` made darker or lighter (whichever moves away from ``against``), keeping its hue, just far enough to stand out by
    ``minimum`` to 1. Used for channel colours in grooves and slider handles on their tracks."""
    if contrast(color, against) >= minimum:
        return color
    darker = luminance(against) >= 0.18
    for step in range(1, 21):
        candidate = shade(color, (-step if darker else step) / 20)
        if contrast(candidate, against) >= minimum:
            return candidate
    return "#000000" if darker else "#ffffff"


def is_light(colors: dict) -> bool:
    return luminance(colors["panel"]) >= LIGHT_PANEL


@lru_cache(maxsize=64)
def _depth(items: tuple, flat: bool) -> tuple:
    c = dict(items)
    panel, bg, raised, text, accent = c["panel"], c["bg"], c.get("surface2", c["panel"]), c["text"], c["accent"]
    light = luminance(panel) >= LIGHT_PANEL
    very_dark = luminance(bg) < VERY_DARK and not light
    if light:
        d = {
            "key_top": shade(panel, 0.75), "key_bottom": shade(panel, -0.05),
            "key_skirt": shade(panel, -0.20), "key_rim": shade(panel, -0.30), "key_edge": shade(panel, -0.15),
            "button_top": shade(raised, 0.8), "button_bottom": shade(raised, -0.05),
            "tray_top": shade(bg, 0.35), "tray_bottom": shade(bg, -0.08), "tray_lip": shade(bg, -0.24),
            "groove": shade(panel, -0.14),
            "shadow": with_lightness(bg, 0.16, 0.5), "shadow_alpha": 0.24, "contact_alpha": 0.22,
            "highlight_alpha": 1.0, "edge_light": False,
            "knob_top": "#ffffff", "knob_bottom": shade(panel, -0.08), "knob_ring": text,
            "outline": mix(panel, accent, 0.36), "glow": False,
        }
    else:
        d = {
            "key_top": shade(panel, 0.16 if very_dark else 0.12), "key_bottom": shade(panel, -0.22),
            "key_skirt": shade(panel, -0.45), "key_rim": shade(panel, -0.68), "key_edge": shade(panel, -0.3),
            "button_top": shade(raised, 0.12), "button_bottom": shade(raised, -0.12),
            "tray_top": shade(bg, 0.10) if very_dark else shade(bg, -0.25),
            "tray_bottom": bg if very_dark else shade(bg, -0.5),
            "tray_lip": shade(bg, 0.16) if very_dark else shade(bg, -0.7),
            "groove": shade(panel, -0.5),
            "shadow": with_lightness(bg, 0.02, 0.6), "shadow_alpha": 0.25 if very_dark else 0.55,
            "contact_alpha": 0.3 if very_dark else 0.5, "highlight_alpha": 0.24 if very_dark else 0.14,
            "edge_light": very_dark,
            "knob_top": "#ffffff", "knob_bottom": shade(c.get("handle", "#e8ecf0"), -0.16), "knob_ring": accent,
            "outline": mix(panel, accent, 0.5 if very_dark else 0.34), "glow": True,
        }
    if flat:  # High contrast: plain fills, solid borders, depth only from a thicker lower edge
        d.update({"key_top": panel, "key_bottom": panel, "button_top": raised, "button_bottom": raised,
                  "key_edge": c["border"], "key_skirt": text, "key_rim": text, "tray_top": bg, "tray_bottom": bg,
                  "tray_lip": c["border"], "shadow_alpha": 0.0, "contact_alpha": 0.0, "highlight_alpha": 0.0, "glow": False,
                  "outline": c["border"], "groove": mix(panel, text, 0.22)})
    d["light"], d["very_dark"], d["flat"] = light, very_dark, flat
    for name in DEPTH_TOKENS:  # a theme that set one by hand keeps it
        if name in c:
            d[name] = c[name]
    if contrast(d["groove"], d["key_bottom"]) < 1.15:  # a groove must show on the key: darker if it can be, lighter on a black key
        darker = shade(d["key_bottom"], -0.45 if not light else -0.2)
        d["groove"] = darker if contrast(darker, d["key_bottom"]) >= 1.15 else mix(d["key_bottom"], text, 0.16)
    return tuple(sorted(d.items()))


def depth_colors(colors: dict, flat: bool = False) -> dict:
    """The depth colours for a complete set of theme colours (cached: painting asks on every frame)."""
    keys = ("panel", "bg", "surface2", "text", "accent", "border", "handle") + DEPTH_TOKENS
    return dict(_depth(tuple((k, colors[k]) for k in keys if k in colors), bool(flat)))


def channel_tint(color: str, colors: dict) -> str:
    """A channel's colour as drawn on this theme: on light themes it is darkened (same hue) until it stands out from the groove
    and the card it sits on, so yellow and green signals are still easy to see on white."""
    return _tint(color, colors["panel"], depth_colors(colors)["groove"])


@lru_cache(maxsize=256)
def _tint(color: str, panel: str, groove: str) -> str:
    if luminance(panel) < LIGHT_PANEL:
        return color
    return stand_out(stand_out(color, groove), panel)
