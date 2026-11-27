# SPDX-License-Identifier: GPL-3.0-or-later
"""Colour themes: a named set of colours, turned into the window's style sheet.

Every colour in the interface comes from one of the names in ``TOKEN_NAMES``. A theme is a complete set of them, so the
style sheet is built from the theme and nothing is coloured twice. Meter colours (green, amber, red), the red of a Mute
button and the teal of a Limiter button are the same in every theme on purpose: they mean the same thing everywhere.

A theme file is plain JSON with colours only, never code::

    {"name": "Midnight", "base": "dark", "colors": {"accent": "#7c5cff", "bg": "#14121f"}}

Colours a file leaves out come from its ``base`` theme (``dark`` or ``light``). Imported themes are copied into a
``themes`` folder next to the settings file. Every colour is checked to be a hex value before it goes anywhere near the
style sheet, so a theme file cannot change anything but colours.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Optional

SYSTEM = "system"  # "Match my system": follows the desktop's light or dark setting
CUSTOM_PREFIX = "custom:"  # an imported theme: custom:<file name without .json>
MAX_FILE_BYTES = 64 * 1024
MAX_CUSTOM = 40  # imported themes shown (the rest of a crowded folder is ignored)

TOKEN_NAMES = (
    "bg",
    "panel",
    "mix",
    "border",
    "border_soft",
    "text",
    "text_dim",
    "text_faint",
    "text_off",
    "title",
    "strong",
    "input",
    "well",
    "chip",
    "button",
    "button_text",
    "button_border",
    "hover",
    "line",
    "accent",
    "select",
    "select_soft",
    "select_text",
    "popup",
    "dialog",
    "fill",
    "handle",
    "handle_edge",
    "handle_hover",
    "applied",
    "scroll_track",
    "scroll_hover",
    "scroll_press",
    "row_hover",
    "list_text",
    "check_text",
    "link",
    "code",
    "ok",
    "alarm",
    "warn",
    "error",
    "muted",
    "mute",
    "limiter",
    "linked",
    "on_color",
    # added in 0.10.0. A theme file that does not list them gets them worked out from its own colours (see ``complete``).
    "surface2",
    "border2",
    "text2",
    "track",
    "meter_bg",
    "accent_bg",
    "accent_text",
    "mute_bg",
    "mute_fg",
    "live_bg",
    "live_fg",
    "dashed",
    "focus",
    # added in 0.13.1 (House Standard v1.3): a card's edge in the accent at about 18%, and the sidebar shade
    "card_edge",
    "sidebar",
)
NEW_TOKENS = TOKEN_NAMES[TOKEN_NAMES.index("surface2") :]

DARK = {  # 0.13.1: the House Standard's navy "hull" (v1.3), with Sluice's blue accent
    "bg": "#0c1016",
    "panel": "#131922",
    "mix": "#161d27",
    "border": "#263040",
    "border_soft": "#263040",
    "text": "#e8edf4",
    "text_dim": "#9aa6b8",
    "text_faint": "#9aa6b8",
    "text_off": "#6b788c",
    "title": "#f3f6fa",
    "strong": "#f3f6fa",
    "input": "#080b10",
    "well": "#080b10",
    "chip": "#1a212c",
    "button": "#1a212c",
    "button_text": "#e8edf4",
    "button_border": "#2f3a4c",
    "hover": "#4a5870",
    "line": "#2f3a4c",
    "accent": "#60a5fa",
    "select": "#1e3a5f",
    "select_soft": "#172b45",
    "select_text": "#ffffff",
    "popup": "#131922",
    "dialog": "#101620",
    "fill": "#60a5fa",
    "handle": "#f3f6fa",
    "handle_edge": "#f3f6fa",
    "handle_hover": "#ffffff",
    "applied": "#172b45",
    "scroll_track": "#0f141c",
    "scroll_hover": "#3a4659",
    "scroll_press": "#4a5870",
    "row_hover": "#212a37",
    "list_text": "#e8edf4",
    "check_text": "#c3ccd8",
    "link": "#93c5fd",
    "code": "#e6c07b",
    "ok": "#6ee7b7",
    "alarm": "#b3262c",
    "warn": "#fbbf24",
    "error": "#f87171",
    "muted": "#7c889b",
    "mute": "#ef5258",
    "limiter": "#35d0c0",
    "linked": "#60a5fa",
    "on_color": "#0c1016",
    "surface2": "#1a212c",
    "border2": "#2f3a4c",
    "text2": "#c3ccd8",
    "track": "#212a37",
    "meter_bg": "#080b10",
    "accent_bg": "#172b45",
    "accent_text": "#60a5fa",
    "mute_bg": "#3a1b22",
    "mute_fg": "#f87171",
    "live_bg": "#0f2a22",
    "live_fg": "#6ee7b7",
    "dashed": "#2f3a4c",
    "focus": "#60a5fa",
    "card_edge": "#22334c",
    "sidebar": "#080b10",
}

LIGHT = {  # 0.13.1: the House Standard's light "hull" (v1.3), with Sluice's blue accent
    "bg": "#f5f7fa",
    "panel": "#ffffff",
    "mix": "#f8fafc",
    "border": "#dce3eb",
    "border_soft": "#dce3eb",
    "text": "#0f1620",
    "text_dim": "#556274",
    "text_faint": "#556274",
    "text_off": "#8a95a5",
    "title": "#0a1018",
    "strong": "#0a1018",
    "input": "#f1f4f8",
    "well": "#e9eef4",
    "chip": "#f1f4f8",
    "button": "#f1f4f8",
    "button_text": "#0f1620",
    "button_border": "#cdd6e1",
    "hover": "#7a8596",
    "line": "#c3cdd9",
    "accent": "#1d4ed8",
    "select": "#dbe6fd",
    "select_soft": "#e8effe",
    "select_text": "#0a1018",
    "popup": "#ffffff",
    "dialog": "#f8fafc",
    "fill": "#1d4ed8",
    "handle": "#ffffff",
    "handle_edge": "#c0cad7",
    "handle_hover": "#f1f4f8",
    "applied": "#e8effe",
    "scroll_track": "#e9eef4",
    "scroll_hover": "#98a3b3",
    "scroll_press": "#7f8b9c",
    "row_hover": "#e9eef4",
    "list_text": "#0f1620",
    "check_text": "#2b3646",
    "link": "#1d4ed8",
    "code": "#8a5a00",
    "ok": "#047857",
    "alarm": "#c62828",
    "warn": "#975a06",
    "error": "#b91c1c",
    "muted": "#7a8596",
    "mute": "#e0414a",
    "limiter": "#1fb3a3",
    "linked": "#1d4ed8",
    "on_color": "#ffffff",
    "surface2": "#f1f4f8",
    "border2": "#cdd6e1",
    "text2": "#2b3646",
    "track": "#e3e9f0",
    "meter_bg": "#e9eef4",
    "accent_bg": "#e8effe",
    "accent_text": "#1d4ed8",
    "mute_bg": "#fde3e6",
    "mute_fg": "#b91c1c",
    "live_bg": "#ddf5ec",
    "live_fg": "#047857",
    "dashed": "#c3cdd9",
    "focus": "#1d4ed8",
    "card_edge": "#cdd9f5",
    "sidebar": "#edf1f5",
}

CONTRAST = {
    "bg": "#000000",
    "panel": "#0a0a0a",
    "mix": "#0f0f0f",
    "border": "#9aa0a6",
    "border_soft": "#9aa0a6",
    "text": "#ffffff",
    "text_dim": "#d6dade",
    "text_faint": "#d6dade",
    "text_off": "#9aa0a6",
    "title": "#ffffff",
    "strong": "#ffffff",
    "input": "#000000",
    "well": "#2b2b2b",
    "chip": "#1a1a1a",
    "button": "#161616",
    "button_text": "#ffffff",
    "button_border": "#c0c5cb",
    "hover": "#ffd400",
    "line": "#9aa0a6",
    "accent": "#ffd400",
    "select": "#1f4fd8",
    "select_soft": "#1f4fd8",
    "select_text": "#ffffff",
    "popup": "#000000",
    "dialog": "#050505",
    "fill": "#00a86b",
    "handle": "#ffffff",
    "handle_edge": "#ffffff",
    "handle_hover": "#ffd400",
    "applied": "#1f4fd8",
    "scroll_track": "#161616",
    "scroll_hover": "#c0c5cb",
    "scroll_press": "#ffd400",
    "row_hover": "#1a1a1a",
    "list_text": "#ffffff",
    "check_text": "#ffffff",
    "link": "#8fd3ff",
    "code": "#ffd400",
    "ok": "#7dff9a",
    "alarm": "#d40000",
    "warn": "#ffd400",
    "error": "#ff6b6b",
    "muted": "#9aa0a6",
    "mute": "#ff5a5f",
    "limiter": "#35d0c0",
    "linked": "#c0c5cb",
    "on_color": "#000000",
}


COLOUR_BLIND = {  # 0.13.1: built in; sky blue accent (Okabe-Ito), not orange, which reads as a warning
    "bg": "#10151c",
    "panel": "#192230",
    "mix": "#141c26",
    "border": "#33445c",
    "border_soft": "#273548",
    "text": "#e3e9f2",
    "text_dim": "#98a6bb",
    "text_faint": "#98a6bb",
    "text_off": "#586476",
    "title": "#f4f6fa",
    "strong": "#eef2f7",
    "input": "#0a0e12",
    "well": "#07090d",
    "chip": "#293240",
    "button": "#2d3643",
    "button_text": "#c9d2df",
    "button_border": "#536277",
    "hover": "#56b4e9",
    "line": "#33445c",
    "accent": "#56b4e9",
    "select": "#0f4f8f",
    "select_soft": "#0f3861",
    "select_text": "#ffffff",
    "popup": "#131a23",
    "dialog": "#151d28",
    "fill": "#2a76c2",
    "handle": "#f1f4f8",
    "handle_edge": "#98a6bb",
    "handle_hover": "#ffffff",
    "applied": "#0f4f8f",
    "scroll_track": "#151d28",
    "scroll_hover": "#5a626e",
    "scroll_press": "#7e8691",
    "row_hover": "#232c3a",
    "list_text": "#e3e9f2",
    "check_text": "#d4dce7",
    "link": "#6fb4ff",
    "code": "#ffd27a",
    "ok": "#7fc3ff",
    "alarm": "#b3262c",
    "warn": "#e0a030",
    "error": "#ef5258",
    "muted": "#6f7887",
    "mute": "#ef5258",
    "limiter": "#35d0c0",
    "linked": "#98a6bb",
    "on_color": "#0e1014",
    "surface2": "#232c3a",
    "border2": "#45546b",
    "text2": "#c9d2df",
    "track": "#2d3643",
    "meter_bg": "#141a24",
    "accent_bg": "#473c2c",
    "accent_text": "#56b4e9",
    "mute_bg": "#482d39",
    "mute_fg": "#f37d82",
    "live_bg": "#223140",
    "live_fg": "#7fc3ff",
    "dashed": "#32373e",
    "focus": "#3b82f6",
}

OLED = {  # 0.13.1: built in (was a download)
    "bg": "#000000",
    "panel": "#0b0b0d",
    "mix": "#060606",
    "border": "#26272c",
    "border_soft": "#1a1a1e",
    "text": "#e4e6ea",
    "text_dim": "#8c9099",
    "text_faint": "#8c9099",
    "text_off": "#4c4e53",
    "title": "#f4f5f7",
    "strong": "#eff0f2",
    "input": "#000000",
    "well": "#17181b",
    "chip": "#1c1d1f",
    "button": "#212123",
    "button_text": "#c5c8ce",
    "button_border": "#48494e",
    "hover": "#6ea8ff",
    "line": "#26272c",
    "accent": "#6ea8ff",
    "select": "#1d3f73",
    "select_soft": "#112645",
    "select_text": "#ffffff",
    "popup": "#040405",
    "dialog": "#070708",
    "fill": "#2b6a55",
    "handle": "#f2f2f4",
    "handle_edge": "#8c9099",
    "handle_hover": "#ffffff",
    "applied": "#1d3f73",
    "scroll_track": "#070708",
    "scroll_hover": "#505154",
    "scroll_press": "#78787c",
    "row_hover": "#161618",
    "list_text": "#e4e6ea",
    "check_text": "#d2d5da",
    "link": "#8ab8ff",
    "code": "#e6c07b",
    "ok": "#8fd19e",
    "alarm": "#b3262c",
    "warn": "#e0a030",
    "error": "#ef5258",
    "muted": "#6f7887",
    "mute": "#ef5258",
    "limiter": "#35d0c0",
    "linked": "#8c9099",
    "on_color": "#0e1014",
    "surface2": "#161618",
    "border2": "#393a3f",
    "text2": "#c5c8ce",
    "track": "#212123",
    "meter_bg": "#040405",
    "accent_bg": "#1f2a3d",
    "accent_text": "#6ea8ff",
    "mute_bg": "#3d1b1e",
    "mute_fg": "#f05b60",
    "live_bg": "#172119",
    "live_fg": "#8fd19e",
    "dashed": "#242525",
    "focus": "#3b82f6",
}

SYNTHWAVE = {  # 0.13.1: built in (was a download)
    "bg": "#0e0b24",
    "panel": "#191340",
    "mix": "#140f32",
    "border": "#3d2f86",
    "border_soft": "#2d2266",
    "text": "#e8e4ff",
    "text_dim": "#9f98d8",
    "text_faint": "#9f98d8",
    "text_off": "#5c568c",
    "title": "#f6f4ff",
    "strong": "#f1efff",
    "input": "#090717",
    "well": "#060510",
    "chip": "#2a244f",
    "button": "#2e2853",
    "button_text": "#cec9f1",
    "button_border": "#5c509c",
    "hover": "#ff2fa6",
    "line": "#3d2f86",
    "accent": "#00e5ff",
    "select": "#0a5a8a",
    "select_soft": "#0c3a61",
    "select_text": "#ffffff",
    "popup": "#120e2e",
    "dialog": "#151035",
    "fill": "#c4208a",
    "handle": "#fff0fb",
    "handle_edge": "#9f98d8",
    "handle_hover": "#ffffff",
    "applied": "#0a5a8a",
    "scroll_track": "#151035",
    "scroll_hover": "#5b567d",
    "scroll_press": "#807ca0",
    "row_hover": "#231d4a",
    "list_text": "#e8e4ff",
    "check_text": "#d9d5f7",
    "link": "#5ff0ff",
    "code": "#ffd166",
    "ok": "#8fd19e",
    "alarm": "#b3262c",
    "warn": "#e0a030",
    "error": "#ef5258",
    "muted": "#6f7887",
    "mute": "#ef5258",
    "limiter": "#35d0c0",
    "linked": "#9f98d8",
    "on_color": "#0e1014",
    "surface2": "#231d4a",
    "border2": "#4e4192",
    "text2": "#cec9f1",
    "track": "#2e2853",
    "meter_bg": "#120e2f",
    "accent_bg": "#143d66",
    "accent_text": "#00e5ff",
    "mute_bg": "#482145",
    "mute_fg": "#f16c71",
    "live_bg": "#232b38",
    "live_fg": "#8fd19e",
    "dashed": "#312e47",
    "focus": "#3b82f6",
}

PAPER = {
    "bg": "#f1ece2",
    "panel": "#fbf8f2",
    "mix": "#f6f2ea",
    "border": "#cfc6b4",
    "border_soft": "#e3dcd0",
    "text": "#2b2620",
    "text_dim": "#665e50",
    "text_faint": "#665e50",
    "text_off": "#b0aba1",
    "title": "#110f0d",
    "strong": "#1a1713",
    "input": "#fdfcf9",
    "well": "#d4d0c7",
    "chip": "#eae7e1",
    "button": "#e6e3dd",
    "button_text": "#403a31",
    "button_border": "#b1a999",
    "hover": "#857b68",
    "line": "#cfc6b4",
    "accent": "#b4532a",
    "select": "#f0d3c2",
    "select_soft": "#f0ddcf",
    "select_text": "#101418",
    "popup": "#fbf8f2",
    "dialog": "#f7f3ec",
    "fill": "#46a97b",
    "handle": "#ffffff",
    "handle_edge": "#665e50",
    "handle_hover": "#f0f4fa",
    "applied": "#f0d3c2",
    "scroll_track": "#f7f3ec",
    "scroll_hover": "#b8b5af",
    "scroll_press": "#938f89",
    "row_hover": "#f1eee8",
    "list_text": "#2b2620",
    "check_text": "#37312a",
    "link": "#9a3f1a",
    "code": "#8a5a00",
    "ok": "#237a43",
    "alarm": "#c62828",
    "warn": "#8a5a00",
    "error": "#c62828",
    "muted": "#7a8493",
    "mute": "#e0414a",
    "limiter": "#1fb3a3",
    "linked": "#9a917c",
    "on_color": "#0e1014",
}


# ----------------------------------------------------------------------------- working out the colours a file leaves out
def _rgb(value: str) -> tuple:
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def mix(a: str, b: str, amount: float) -> str:
    """The colour ``amount`` (0..1) of the way from ``a`` to ``b``."""
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(ra, rb))


def readable(fg: str, bg: str, minimum: float = 4.5, toward: Optional[str] = None) -> str:
    """``fg``, moved toward white or black (whichever is further from ``bg``) just far enough to read on ``bg``."""
    if contrast_ratio(fg, bg) >= minimum:
        return fg
    end = toward or ("#ffffff" if luminance(bg) < 0.4 else "#000000")
    for step in range(1, 21):
        candidate = mix(fg, end, step / 20)
        if contrast_ratio(candidate, bg) >= minimum:
            return candidate
    return end


def complete(colors: dict, given=()) -> dict:
    """A full colour set: the colours that are missing (the 0.10.0 ones) are worked out from the ones that are there.

    ``given`` names the colours that must be kept as they are. The rest of ``NEW_TOKENS`` is rebuilt from the theme's own
    background, card, text and accent, so an older theme file looks right in the new design without being edited."""
    c = dict(colors)
    keep = set(given)

    def put(name: str, value: str) -> None:
        if name not in keep:
            c[name] = value

    light = luminance(c["bg"]) >= 0.4
    put("surface2", mix(c["panel"], c["text"], 0.05))
    put("border2", mix(c["border"], c["text"], 0.1))
    put("text2", readable(mix(c["text"], c["text_dim"], 0.35), c["panel"]))
    put("track", mix(c["panel"], c["text"], 0.1))
    put("meter_bg", mix(c["panel"], c["bg"], 0.6))
    put("accent_bg", mix(c["panel"], c["accent"], 0.2 if not light else 0.16))
    put("accent_text", readable(c["accent"], c["accent_bg"]))
    put("mute_bg", mix(c["panel"], c["mute"], 0.22))
    put("mute_fg", readable(c["mute"], c["mute_bg"]))
    put("live_bg", mix(c["bg"], c["ok"], 0.16))
    put("live_fg", readable(c["ok"], c["live_bg"]))
    put("dashed", mix(c["bg"], c["text"], 0.16))
    focus = "#2563eb" if light else "#3b82f6"
    for surface in (c["bg"], c["panel"]):
        focus = readable(focus, surface, 3.2)
    put("focus", focus)
    put("card_edge", mix(c["panel"], c["accent"], 0.18))
    put("sidebar", mix(c["bg"], "#000000" if not light else c["border"], 0.3))
    return c


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    base: str  # "dark" or "light": what a theme file's missing colours come from
    colors: dict


BUILT_IN: dict = {
    "dark": Theme("dark", "Dark", "dark", DARK),
    "light": Theme("light", "Light", "light", LIGHT),
    "contrast": Theme("contrast", "High contrast", "dark", CONTRAST),
    "colourblind": Theme("colourblind", "Colour-blind friendly", "dark", COLOUR_BLIND),
    "oled": Theme("oled", "OLED Black", "dark", OLED),
    "paper": Theme("paper", "Paper", "light", PAPER),
    "synthwave": Theme("synthwave", "Synthwave", "dark", SYNTHWAVE),
}
DEFAULT = "dark"
SYSTEM_LABEL = "Match my system"


class ThemeError(ValueError):
    """A theme file that cannot be used; the message is meant for the person who chose it."""


# ----------------------------------------------------------------------------- style sheet
STYLE_TEMPLATE = Template("""
/* The look of 0.13.1 (House Standard): spacing in steps of 4/8, text 12 / 14 / 16 / 22, corners 8 controls / 12 cards / 16 panels. */
QMainWindow, QWidget#root, QScrollArea, QWidget#channels, QWidget#sources { background: $bg; }
QWidget { color: $text; font-size: 14px; }
QToolTip { background: $popup; color: $text; border: 1px solid $button_border; padding: 8px; border-radius: 8px; }
QFrame#strip, QFrame#row {
    background: $panel; border: 1px solid $card_edge; border-radius: 12px;
}
QFrame#row { border-radius: 12px; }
QFrame#strip[empty="true"] { background: transparent; border: 2px dashed $dashed; }
QFrame#mix { background: $mix; border: 1px solid $card_edge; border-radius: 12px; }
QFrame#sourcechip { background: $surface2; border: none; border-radius: 8px; }
QFrame#chip { background: $surface2; border: none; border-radius: 8px; }
QFrame#statuschip { background: transparent; border: 1px solid $border; border-radius: 12px; }
QFrame#divider { background: $border2; max-width: 1px; min-width: 1px; }
QFrame#empty { background: transparent; border: 2px dashed $dashed; border-radius: 12px; }
QFrame#firstrun { background: $panel; border: 1px solid $card_edge; border-radius: 16px; }
QFrame#accent { border: none; border-radius: 2px; }
QPushButton#danger { color: #ffffff; background: $alarm; border: 1px solid $alarm; font-weight: 600; }
QPushButton#updatepill { color: $on_color; background: $accent; border: none; border-radius: 16px; padding: 6px 14px;
    font-weight: 600; }
QPushButton#helpbutton { font-size: 16px; font-weight: 700; color: $text; background: transparent; border: 1px solid $border;
    border-radius: 8px; }
QPushButton#helpbutton:hover { background: $row_hover; }
QPushButton#danger:hover { background: $mute; }
QLabel { background: transparent; }
QLabel#appname { font-size: 20px; font-weight: 700; color: $title; }
QLabel#title { font-size: 20px; font-weight: 700; color: $title; }
QLabel#name { font-size: 17px; font-weight: 600; color: $title; }
QLabel#tag { font-size: 12px; font-weight: 600; letter-spacing: 0.5px; color: $text_faint; }
QLabel#tag[narrow="true"] { font-size: 11px; letter-spacing: 0; }  /* the one exception to 13 px: a capitals label squeezed into a narrow card */
QLabel#tag[mix="monitor"] { color: $listen_text; }
QLabel#tag[mix="stream"] { color: $broadcast_text; }
QFrame#mix[mix="monitor"] { border-color: $listen_edge; }
QFrame#mix[mix="stream"] { border-color: $broadcast_edge; }
QFrame#mixcell { background: transparent; border: 1px solid transparent; border-radius: 12px; }
QFrame#mixcell[mix="monitor"] { background: $listen_tint; border-color: $listen_edge; }
QFrame#mixcell[mix="stream"] { background: $broadcast_tint; border-color: $broadcast_edge; }
QLabel#mixheading { font-size: 12px; font-weight: 600; letter-spacing: 0.5px; background: transparent; }
QLabel#mixheading[mix="monitor"] { color: $listen_text; }
QLabel#mixheading[mix="stream"] { color: $broadcast_text; }
QLabel#hint { font-size: 13px; color: $text_dim; }
QLabel#feedback { font-size: 13px; color: $text_dim; }
QLabel#chiptext { font-size: 13px; color: $text2; background: transparent; }
QFrame#livepanel { background: $panel; border: 1px solid $card_edge; border-radius: 16px; }
QFrame#detail { background: $panel; border: 1px solid $card_edge; border-radius: 16px; }
QLabel#swatch { border-radius: 6px; background: $text_dim; }
QLabel#swatch[who="out"] { background: $accent; }
QLabel#bigvalue { font-size: 20px; font-weight: 700; color: $title; background: transparent; }
QLabel#gatechip { font-size: 13px; font-weight: 600; padding: 4px 16px; border-radius: 12px; background: $surface2; color: $text2; }
QLabel#gatechip[open="true"] { background: $live_bg; color: $live_fg; }
QLabel#livechip { font-size: 13px; font-weight: 600; color: $live_fg; background: $live_bg; border-radius: 16px; padding: 7px 16px; }
QLabel#ratetext { font-size: 13px; color: $text_dim; }
QLabel#dropouts { font-size: 14px; color: $text2; }
QLabel#readout { font-size: 14px; font-weight: 600; color: $strong; background: transparent; border: none; }
QLineEdit#readout { font-size: 14px; font-weight: 600; color: $strong; background: transparent; border: 2px solid transparent;
    border-radius: 8px; padding: 1px 0; }
QLineEdit#readout:hover { border-color: $border2; }
QLineEdit#readout:focus { border-color: $focus; background: $input; }
QLineEdit#readout[big="true"] { font-size: 20px; font-weight: 700; }
QLabel#status { color: $text_dim; font-size: 13px; padding: 0 8px; }
QLabel#demo { color: #1b1300; background: #f5c542; font-weight: 700; font-size: 13px; border-radius: 8px; padding: 4px 12px; }
QLabel#step { font-size: 14px; font-weight: 700; color: $on_color; background: $accent; border-radius: 16px; }
QLabel#stepoff { font-size: 14px; font-weight: 700; color: $text2; background: $track; border-radius: 16px; }
QStatusBar { background: $bg; border: none; }
QStatusBar::item { border: none; }

QPushButton {
    background: $button; color: $button_text; border: 1px solid $button_border;
    border-radius: 12px; padding: 0 16px; min-height: 38px; font-size: 14px; font-weight: 600;
}
QPushButton:hover { border-color: $hover; }
QPushButton:pressed { background: $track; }
QPushButton:focus { border: 2px solid $focus; padding: 0 15px; }
QPushButton:disabled { color: $text_off; }
QPushButton:checked { color: $accent_text; background: $accent_bg; border-color: transparent; }
QPushButton::menu-indicator { image: none; width: 0; }
QPushButton[compact="true"] { border-radius: 8px; min-height: 30px; padding: 0 8px; font-size: 13px; font-weight: 500; }
QPushButton[compact="true"]:focus { padding: 0 7px; }
QPushButton#primary { background: $accent; color: $on_color; border-color: transparent; }
QPushButton#primary:hover { border-color: $hover; }
QPushButton#iconbutton { padding: 0; border-radius: 12px; }
QPushButton#iconbutton[compact="true"] { border-radius: 8px; }
QPushButton#mute { background: $track; border: 2px solid transparent; padding: 0; }
QPushButton#mute:checked { background: $mute_bg; border-color: transparent; }
QPushButton#mute:focus { border-color: $focus; }
QPushButton#limiter { border: 2px solid transparent; font-size: 13px; font-weight: 700; background: $track; color: $text2; }
QPushButton#limiter:checked { background: $accent_bg; color: $accent_text; border-color: transparent; }
QPushButton#limiter:focus { border-color: $focus; }
QPushButton#limiter[mix="monitor"]:checked { background: $listen_tint; color: $listen_text; }
QPushButton#limiter[mix="stream"]:checked { background: $broadcast_tint; color: $broadcast_text; }
QPushButton#link { padding: 0; border-radius: 8px; background: $surface2; border: 1px solid $border2; }
QPushButton#link:checked { background: $accent_bg; border-color: $accent; }
QPushButton#link:focus { border: 1px solid $focus; }
QPushButton#micmute { padding: 0; border-radius: 8px; background: transparent; border: 2px solid transparent; min-height: 0; min-width: 0; }
QPushButton#micmute:checked { background: $mute_bg; border-color: transparent; }
QPushButton#micmute:focus { border-color: $focus; }
QPushButton#iconbutton:focus { border: 1px solid $focus; }
QPushButton#addchip { border: 2px dashed $dashed; color: $text_dim; background: transparent; border-radius: 8px;
    min-height: 28px; font-size: 13px; font-weight: 500; padding: 0 8px; }
QPushButton#addchip:hover { border-color: $hover; color: $text; }
QPushButton#addchip:focus { border: 2px solid $focus; padding: 0 8px; }
QPushButton#addchip[iconly="true"]:focus { border: 1px solid $focus; padding: 0; }
QPushButton#addchip[iconly="true"] { border-radius: 8px; padding: 0; border-style: solid; border-width: 1px; border-color: $border2; min-height: 0; }
QPushButton#plain { background: transparent; border: 2px solid transparent; padding: 0; border-radius: 8px; min-height: 0; }
QPushButton#plain:hover { background: $surface2; }
QPushButton#plain:focus { border-color: $focus; }
QFrame#segmented { background: transparent; border: 1px solid $border; border-radius: 12px; }
QPushButton#segment { border: 2px solid transparent; background: transparent; min-height: 30px; border-radius: 9px; padding: 0 14px; font-size: 13px; color: $text2; }
QPushButton#segment:checked { background: $accent_bg; color: $accent_text; border-color: transparent; }
QPushButton#segment:focus { border-color: $focus; }
QLabel#intro { color: $text2; }
QPushButton#addchannel { border: 2px dashed $dashed; color: $text_dim; background: transparent; border-radius: 24px;
    font-size: 14px; font-weight: 600; }
QPushButton#addchannel:hover { border-color: $hover; color: $text; }
QPushButton#addchannel:focus { border: 2px solid $focus; }
QPushButton#quiet { background: transparent; border: 1px solid $border2; color: $text2; font-size: 13px; font-weight: 600; }
QPushButton#quiet:checked { background: $accent_bg; color: $accent_text; border-color: transparent; }
QPushButton#quiet:focus { border: 2px solid $focus; padding: 0 15px; }
QPushButton#devicebutton { background: $surface2; border: 1px solid $border2; color: $text2; font-size: 13px; font-weight: 500;
    text-align: left; padding: 0 12px; }
QPushButton#devicebutton:focus { border: 2px solid $focus; padding: 0 11px; }
QPushButton#app { padding: 3px 12px; border-radius: 12px; }
QPushButton#appassigned { padding: 3px 12px; border-radius: 12px; color: $strong; background: $applied; }
QPushButton:flat { background: transparent; border: none; min-height: 0; padding: 2px 8px; font-size: 13px; }
QToolButton { background: transparent; border: 2px solid transparent; color: $text_dim; font-weight: 700; padding: 0 2px; border-radius: 8px; }
QToolButton:hover { color: $strong; background: $surface2; }
QToolButton:focus { border-color: $focus; }
QToolButton#remove:hover { color: $error; }
QToolButton::menu-indicator { image: none; width: 0; }

QComboBox {
    background: $surface2; border: 1px solid $border2; border-radius: 12px; padding: 0 12px; min-height: 38px;
    font-size: 13px; font-weight: 500; color: $text2;
}
QComboBox:hover { border-color: $hover; }
QComboBox:focus { border: 2px solid $focus; padding: 0 11px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("$chevron_url"); width: 14px; height: 14px; }
QComboBox::down-arrow:on { top: 1px; }
QComboBox QAbstractItemView {
    background: $popup; border: 1px solid $button_border; selection-background-color: $select;
    selection-color: $select_text; font-size: 14px; padding: 8px; outline: 0;
}
QMenu { background: $popup; border: 1px solid $button_border; padding: 8px; border-radius: 12px; font-size: 14px; }
QMenu::item { padding: 8px 24px; border-radius: 8px; }
QMenu::item:selected { background: $select; color: $select_text; }
QMenu::item:disabled { color: $menu_off; }
QLabel#menuheading { font-size: 12px; font-weight: 600; letter-spacing: 0.6px; color: $text_dim; background: transparent;
    padding: 12px 24px 4px 24px; border-top: 1px solid $border; margin-top: 4px; }
QLabel#menuheading[first="true"] { padding-top: 4px; border-top: none; margin-top: 0; }
QMenu::separator { height: 1px; background: $border; margin: 8px 8px; }
QFrame#menupanel { background: $popup; border: 1px solid $button_border; border-radius: 20px; }
QFrame#menupanel QLabel { background: transparent; }
QFrame#menupanel QLabel#panelsection { font-size: 12px; font-weight: 600; letter-spacing: 0.8px; color: $text_dim; padding: 10px 10px 4px 10px; }
QFrame#menupanel QPushButton#panelrow, QFrame#menupanel QPushButton#panelfoot { background: transparent; border: 1px solid transparent;
    border-radius: 10px; text-align: left; padding: 0; }
QFrame#menupanel QPushButton#panelrow:hover, QFrame#menupanel QPushButton#panelrow:focus { background: $chip; border-color: $chip; }
QFrame#menupanel QPushButton#panelrow:focus { border-color: $focus; }
QFrame#menupanel QPushButton#panelfoot { background: $button; border-color: $button_border; border-radius: 12px; }
QFrame#menupanel QPushButton#panelfoot:hover { background: $hover; }
QFrame#menupanel QPushButton#panelfoot:focus { border-color: $focus; }
QFrame#menupanel QLabel#panelname { font-size: 14px; color: $text; }
QFrame#menupanel QPushButton#panelfoot QLabel#panelname { font-weight: 600; }
QFrame#menupanel QLabel#keycap { font-size: 12px; color: $text_dim; background: $chip; border: 1px solid $button_border;
    border-radius: 6px; padding: 1px 6px; }
QFrame#menupanel QPushButton#paneltile { background: $button; border: 1px solid $button_border; border-radius: 14px; text-align: left; }
QFrame#menupanel QPushButton#paneltile:hover { background: $hover; }
QFrame#menupanel QPushButton#paneltile:focus { border-color: $focus; }
QFrame#menupanel QPushButton#paneltile[on="true"] { background: $mute_bg; border-color: $mute; }
QFrame#menupanel QLabel#tilename { font-size: 13px; font-weight: 600; color: $text; }
QFrame#menupanel QLabel#tilekey { font-size: 12px; color: $text_dim; }
QFrame#menupanel QLabel#tilename[on="true"] { color: $mute_fg; }
QFrame#menupanel QLabel#panelname:disabled { color: $menu_off; }
QFrame#menupanel QPushButton#panelchip { background: $button; border: 1px solid $button_border; border-radius: 12px; min-height: 36px;
    font-size: 13px; font-weight: 600; color: $text; padding: 0 8px; }
QFrame#menupanel QPushButton#panelchip:hover { background: $hover; }
QFrame#menupanel QPushButton#panelchip:checked { background: $mute_bg; border-color: $mute; color: $mute_fg; }
QFrame#menupanel QPushButton#panelchip:focus { border-color: $focus; }
QFrame#menupanel QFrame#segmented { background: transparent; border: 1px solid $border; border-radius: 12px; }
QFrame#menupanel QPushButton#segment { border: 1px solid transparent; background: transparent; min-height: 32px; border-radius: 9px;
    font-size: 13px; font-weight: 600; color: $text2; }
QFrame#menupanel QPushButton#segment:checked { background: $accent_bg; color: $accent_text; border-color: $accent; }
QFrame#menupanel QPushButton#segment:focus { border-color: $focus; }
QFrame#menupanel QPushButton#panellink { background: transparent; border: none; color: $link; font-size: 13px; padding: 2px 0; }
QFrame#menupanel QPushButton#panellink:hover { text-decoration: underline; }
QFrame#menupanel QPushButton#panellink:focus { color: $text; text-decoration: underline; }
QFrame#menupanel QFrame#panelline { background: $border; border: none; }
QDialog QFrame#settingsgroup { background: $panel; border: 1px solid $border; border-radius: 16px; }
QDialog QFrame#settingsgroup[danger="true"] { border: 1px solid $alarm; }
QDialog QFrame#settingsrow { background: transparent; border: none; border-top: 1px solid $border_soft; }
QDialog QFrame#settingsrow[first="true"] { border-top: none; }
QDialog QFrame#settingsrow QLabel#rowname { font-size: 14px; font-weight: 500; color: $text; background: transparent; }
QDialog QFrame#settingsrow QLabel#rowhint { font-size: 13px; color: $text_dim; background: transparent; }
QDialog QLabel#settingstitle { font-size: 22px; font-weight: 700; color: $text; }
QDialog QFrame#settingsrow QLabel#setupok { font-size: 13px; font-weight: 600; color: $ok; background: transparent; }
QDialog QFrame#settingsrow QLabel#setupmissing { font-size: 13px; font-weight: 600; color: $warn; background: transparent; }
QDialog QFrame#settingsrow QLabel#setupneeded { font-size: 13px; font-weight: 600; color: $error; background: transparent; }
QDialog QFrame#settingsrow QLabel#setupidle { font-size: 13px; color: $text_dim; background: transparent; }
QDialog QFrame#settingsrow QLabel#setupcommand { font-family: monospace; font-size: 13px; color: $code; background: $well;
    border: 1px solid $border_soft; border-radius: 8px; padding: 6px 10px; }
QDialog QLabel#grouphead { font-size: 12px; font-weight: 600; letter-spacing: 0.8px; color: $text_dim; padding: 4px 4px 0 4px; }
QMenuBar { background: $bg; color: $button_text; }
QMenuBar::item { padding: 8px 12px; border-radius: 8px; }
QMenuBar::item:selected { background: $chip; }
QDialog { background: $dialog; }
QMessageBox { background: $dialog; }
QDialog#cardpanel { background: $popup; border: 1px solid $button_border; }
QDialog#cardpanel QLabel#panelheading { font-size: 17px; font-weight: 600; color: $title; background: transparent; }
QMessageBox#sluicemessage QLabel { font-size: 14px; color: $text; }
QMessageBox#sluicemessage QPushButton { min-width: 96px; }
QMessageBox#sluicemessage QPushButton#primary { background: $accent; color: $on_color; border-color: transparent; }
QProgressBar { background: $well; border: 1px solid $border_soft; border-radius: 8px; text-align: center; min-height: 16px; }
QProgressBar::chunk { background: $accent; border-radius: 7px; }
QTextBrowser { color: $list_text; background: $input; border: 1px solid $border_soft; border-radius: 12px; padding: 8px; }
QLineEdit { background: $input; border: 1px solid $border_soft; border-radius: 8px; padding: 8px; color: $list_text;
    selection-background-color: $select; selection-color: $select_text; }
QLineEdit:focus { border: 2px solid $focus; padding: 7px; }
QCheckBox { spacing: 8px; color: $check_text; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $line; border-radius: 4px; background: $input; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:focus { border-color: $focus; }
QRadioButton { spacing: 8px; color: $check_text; }
QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid $line; border-radius: 9px; background: $input; }
QRadioButton::indicator:checked { background: $accent; border: 4px solid $input; outline: none; }
QRadioButton::indicator:focus { border-color: $focus; }
QListWidget { background: $input; border: 1px solid $border_soft; border-radius: 12px; padding: 8px; color: $list_text;
    outline: 0; }
QListWidget::item { padding: 8px; border-radius: 8px; }
QListWidget::item:selected { background: $select_soft; color: $select_text; }
QListWidget::item:hover:!selected { background: $row_hover; }
QListWidget#chain { background: transparent; border: none; padding: 0; }
QListWidget#chain::item, QListWidget#chain::item:selected, QListWidget#chain::item:hover:!selected { background: transparent; padding: 0; }
QScrollBar:horizontal { background: $scroll_track; height: 12px; border-radius: 6px; margin: 0 2px; }
QScrollBar::handle:horizontal { background: $line; border-radius: 6px; min-width: 48px; }
QScrollBar::handle:horizontal:hover { background: $scroll_hover; }
QScrollBar::handle:horizontal:pressed { background: $scroll_press; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QScrollBar:vertical { background: $scroll_track; width: 8px; border-radius: 4px; margin: 4px 0; }
QScrollBar::handle:vertical { background: $line; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* sliders in dialogs (the faders of the mixer paint themselves) */
QSlider::groove:horizontal { background: $track; height: 8px; border-radius: 4px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 4px; }
QSlider::handle:horizontal { background: $handle; border: 1px solid $handle_edge; width: 16px; height: 16px; margin: -5px 0;
    border-radius: 9px; }
QSlider::handle:horizontal:hover { background: $handle_hover; }
QSlider::handle:horizontal:focus { border-color: $focus; }
QSlider::groove:vertical { background: $track; width: 8px; border-radius: 4px; }
QSlider::add-page:vertical { background: $accent; border-radius: 4px; }
QSlider::handle:vertical { background: $handle; border: 1px solid $handle_edge; height: 16px; width: 16px; margin: 0 -5px;
    border-radius: 9px; }
/* the Settings window (0.11.5) */
QLabel#settingsheading { font-size: 16px; font-weight: 600; color: $title; padding-top: 8px; }
QListWidget#settingssections { background: $panel; border: 1px solid $border; border-radius: 12px; padding: 8px; outline: none; }
QListWidget#settingssections::item { padding: 10px 12px; border-radius: 8px; color: $text; }
QListWidget#settingssections::item:hover { background: $row_hover; }
QListWidget#settingssections::item:selected { background: $accent_bg; color: $accent_text; }
QPushButton#lookcard { background: $panel; border: 1px solid $border; border-radius: 12px; padding: 0; min-width: 254px;
    max-width: 254px; min-height: 192px; max-height: 192px; }
QPushButton#lookcard:hover { border-color: $hover; }
QPushButton#lookcard:checked { border: 2px solid $accent; }
QPushButton#lookcard:focus { border: 2px solid $focus; }
QLabel#lookname { font-weight: 600; color: $text; background: transparent; }
QPushButton#themepicker { padding: 0 16px; min-width: 200px; text-align: left; }
QPushButton#themepicker::menu-indicator { image: none; width: 0; }
""")


def mix_colors(colors: dict, skin: Optional[str] = None) -> dict:
    """The two colours that tell the mixes apart in the Rows layout: Listen (what you hear) and Broadcast (what your audience hears),
    each with a tint for its background, an edge, and a text colour that reads on the panel. They come from the theme's own colours;
    if the theme's link and accent colours are close, Broadcast takes the theme's warm colour instead so the two stay apart."""
    listen, broadcast = colors["link"], colors["accent"]
    if contrast_ratio(listen, broadcast) < 1.35:
        broadcast = colors["code"]
    out = {}
    for name, base in (("listen", listen), ("broadcast", broadcast)):
        out[name] = base
        out[name + "_tint"] = mix(colors["panel"], base, 0.12)
        out[name + "_edge"] = mix(colors["panel"], base, 0.45)
        out[name + "_text"] = readable(base, mix(colors["panel"], base, 0.12))
    return out


SKINS = {"calm": "Calm", "tile": "Tile"}
# 0.13.1: Nexus and Glass were retired (House Standard: two skins to keep up; no blur). A saved choice of one shows the closest.
RETIRED_SKINS = {
    "nexus": "tile",
    "glass": "calm",
    "original": "calm",
}  # the Look setting: shapes, sizes and painting, apart from colour
DEFAULT_SKIN = "calm"


_skin = DEFAULT_SKIN


def set_skin(skin) -> None:
    """Remember the look in use, for the widgets that draw or lay themselves out differently from one look to another."""
    global _skin
    _skin = valid_skin(skin)


def current_skin() -> str:
    return _skin


_dressings: dict = {}


@contextmanager
def dressed_as(skin: Optional[str], colors: Optional[dict]):
    """Draw in another skin and colours for a moment (0.11.6: desktop widgets may have their own). Inside, ``current_look``,
    ``color`` and ``generation`` answer for that skin and those colours; afterwards they are the window's again. Each skin and
    colour set has its own (negative) generation, so caches keyed on it keep one entry for the window and one for the widgets."""
    global _skin, _current, _generation
    if skin is None and colors is None:
        yield
        return
    saved = (_skin, _current, _generation)
    new_skin = valid_skin(skin) if skin else _skin
    new_colors = dict(colors) if colors is not None else _current
    key = (new_skin, tuple(sorted(new_colors.items())))
    _skin, _current, _generation = new_skin, new_colors, _dressings.setdefault(key, -(len(_dressings) + 1))
    try:
        yield
    finally:
        _skin, _current, _generation = saved


_reduce = False
_skin_colors = True
# With "Look's own colours" on (the default), a look may show its own colours on the plain Dark theme, and Tile on Light too (0.11.5,
# option A). Every other theme keeps its own colours in every look, with full depth worked out from them (``depth``).
TILE_DARK_THEMES = ("dark",)  # the Tile look's graphite keys (skin_tile.TILE_DARK)
TILE_LIGHT_THEMES = ("light",)  # ...and its white keys (skin_tile.TILE_LIGHT)


def set_reduce_effects(on: bool) -> None:
    """Nexus's "reduce effects": the rings stop shimmering and the faders show no waveform. Remembered here for the widgets that draw."""
    global _reduce
    _reduce = bool(on)


def reduce_effects() -> bool:
    return _reduce


def set_skin_colors(on: bool) -> None:
    """Whether a look shows its own colours on Dark (and Tile on Light): Settings > Themes and skins > Skin's own colours."""
    global _skin_colors
    _skin_colors = bool(on)


def skin_colors_on() -> bool:
    return _skin_colors


def skin_colors(theme: "Theme", skin: str) -> dict:
    """The colours to show for a theme in a look. Nexus and Tile may show their own colours on Dark (and Tile on Light); every other
    theme shows its own colours. Then ``finish`` makes sure the
    small and drawn things can be seen."""
    skin = valid_skin(skin)
    colors = theme.colors
    if skin == "calm" and _skin_colors and theme.id in ("dark", "light"):  # 0.12.2: Calm's warm white and graphite
        from .skin_calm import CALM_THEMES

        own = CALM_THEMES[theme.id]
        colors = complete({**theme.colors, **own}, given=own.keys())
    elif skin == "tile" and _skin_colors and theme.id in TILE_DARK_THEMES + TILE_LIGHT_THEMES:
        from .skin_tile import TILE_DARK, TILE_LIGHT

        own = TILE_DARK if theme.id in TILE_DARK_THEMES else TILE_LIGHT
        colors = complete({**theme.colors, **own}, given=own.keys())
    return finish(colors)


def is_light_theme(theme: "Theme") -> bool:
    """Whether a theme is a light one (its cards are light): Nexus shows its dark colours instead (0.12.2)."""
    return luminance(theme.colors["panel"]) >= 0.4


TEXT_OFF_MINIMUM = 3.0  # greyed-out text (a switched-off control, an empty hint): still readable


def finish(colors: dict) -> dict:
    """The last pass over any theme's colours before they are shown (0.11.5): greyed-out text is raised to 3 to 1 on every surface it
    sits on, the Live label to 4.5, and a slider handle's edge to 3 against its groove, so nothing disappears on a light theme."""
    c = dict(colors)
    for surface in ("panel", "bg", "surface2"):
        c["text_off"] = readable(c["text_off"], c[surface], TEXT_OFF_MINIMUM)
    c["live_fg"] = readable(c["live_fg"], c["live_bg"], 4.5)
    c["mute_fg"] = readable(c["mute_fg"], c["mute_bg"], 4.5)
    if luminance(c["panel"]) >= 0.4:
        from .depth import stand_out

        c["handle_edge"] = stand_out(c["handle_edge"], c["track"])
        if contrast_ratio(c["handle"], c["track"]) < 1.3 and contrast_ratio(c["handle_edge"], c["handle"]) < 3:
            c["handle_edge"] = stand_out(c["text2"], c["handle"])
    return c


def chevron_file(color: str) -> str:
    """0.12.2: a dropdown's arrow is Sluice's drawn chevron in the theme's colour, saved once as a small picture for the style sheet
    (a style sheet can only show a picture from a file). "" when it cannot be made (no window system yet, or no writable folder)."""
    import os
    from pathlib import Path

    folder = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sluice" / "icons"
    path = folder / f"chevron-{color.lstrip('#')}.png"
    if path.is_file():
        return path.as_posix()
    try:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is None:
            return ""
        from . import ui_icons

        folder.mkdir(parents=True, exist_ok=True)
        if ui_icons.render("chevron_down", color, 32).save(str(path), "PNG"):
            return path.as_posix()
    except Exception:  # noqa: BLE001 - only a nicer arrow is lost
        pass
    return ""


def valid_skin(skin) -> str:
    """A saved look id that exists, or the default (an id from a newer or older Sluice never breaks the window)."""
    if isinstance(skin, str) and skin in RETIRED_SKINS:
        return RETIRED_SKINS[skin]
    return skin if isinstance(skin, str) and skin in SKINS else DEFAULT_SKIN


@lru_cache(maxsize=16)
def _style_for(items: tuple, skin: str = DEFAULT_SKIN) -> str:
    values = dict(items)
    values.update(mix_colors(values, skin.split("+")[0]))
    values["accent_edge"] = mix(values["panel"], values["accent"], 0.5)  # a thin neon outline for Nexus
    values["accent_soft"] = mix(values["panel"], values["accent"], 0.22)
    values["menu_off"] = mix(
        values["text_off"], values["text_dim"], 0.45
    )  # a greyed-out menu item: plainly off, still easy to read
    values["chevron_url"] = chevron_file(values["text_dim"])
    if skin == "tile":  # the Calm sheet with the Tile rules after it: flat surfaces with a hairline edge
        from .skin_tile import TILE_STYLE_EXTRA, tile_colors

        values.update(tile_colors(values, mix))
        return STYLE_TEMPLATE.substitute(values) + TILE_STYLE_EXTRA.substitute(values)
    css = STYLE_TEMPLATE.substitute(values)
    if skin == "calm+grid":
        dots = grid_file(values["text"], luminance(values["bg"]) >= 0.4)
        if dots:  # (the House Standard's optional faint pattern, at about 4%: only behind the channel area)
            css += f"\nQWidget#channels {{ background: {values['bg']} url({dots}) repeat; }}\n"
    return css


def grid_file(color: str, light: bool) -> str:
    """0.13.1: a 16-pixel tile with one faint dot (about 4% of the text colour), saved once for the style sheet. "" if it cannot
    be made."""
    import os

    folder = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sluice" / "icons"
    path = folder / f"grid-{color.lstrip('#')}.png"
    if path.is_file():
        return path.as_posix()
    try:
        from PySide6.QtGui import QColor, QGuiApplication, QImage

        if QGuiApplication.instance() is None:
            return ""
        folder.mkdir(parents=True, exist_ok=True)
        image = QImage(16, 16, QImage.Format.Format_ARGB32)
        image.fill(0)
        dot = QColor(color)
        dot.setAlphaF(0.07 if light else 0.05)
        for x, y in ((7, 7), (8, 7), (7, 8), (8, 8)):
            image.setPixelColor(x, y, dot)
        if image.save(str(path), "PNG"):
            return path.as_posix()
    except Exception:  # noqa: BLE001 - only the pattern is lost
        pass
    return ""


def build_style(colors: dict, skin: str = DEFAULT_SKIN, see: Optional[bool] = None) -> str:  # (``see`` is ignored: Glass is gone)
    """The window's style sheet for a complete colour set in a look (cached: switching back costs nothing). Glass has a second
    form for a see-through window (``see``; the window's own state when not given)."""
    skin = valid_skin(skin)
    if skin == "calm" and not _reduce:
        skin = "calm+grid"  # 0.13.1: the faint dot grid behind the channels (off with "Reduce effects")
    return _style_for(tuple(sorted(colors.items())), skin)


# Menus, tooltips and their headings are windows of their own: these rules reach them wherever they open.
_EVERYWHERE = ("QMenu", "QToolTip", "QLabel#menuheading", "QFrame#menupanel")  # (the ☰ panel is a popup of its own, 0.11.7)
# The dialog itself (the rest of the rules reach only what is inside one).
_DIALOGS = ("QDialog", "QMessageBox")


def scope_to_dialogs(css: str) -> str:
    """``css`` (a whole look's sheet) narrowed to the dialogs, menus and tooltips (0.11.6). The window carries the Calm sheet in
    this form so every skin's dialogs and menus look the same, while the mixer itself sees only its own skin's sheet: an unscoped
    Calm sheet on the window leaked its boxes, paddings and borders into whatever a skin left unset (Tile's readouts were boxed and
    cut off)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for rule in css.split("}"):
        if "{" not in rule:
            continue
        selectors, body = rule.split("{", 1)
        scoped = []
        for selector in (part.strip() for part in selectors.split(",")):
            if not selector:
                continue
            head = re.split(r"[\s:\[]", selector, maxsplit=1)[0]
            if head.startswith(_EVERYWHERE):
                scoped.append(selector)
                continue
            if head.split("#")[0] in _DIALOGS:
                scoped.append(selector)
            scoped.append(f"QDialog {selector}")
        out.append(f"{', '.join(scoped)} {{{body}}}")
    return "\n".join(out)


@lru_cache(maxsize=16)
def _shared_for(items: tuple) -> str:
    return scope_to_dialogs(_style_for(items, "calm"))


def shared_style(colors: dict) -> str:
    """The sheet the main window carries in every skin: Calm, for its dialogs, menus and tooltips only (cached)."""
    return _shared_for(tuple(sorted(colors.items())))


# ----------------------------------------------------------------------------- the theme in use
_current: dict = dict(DARK)


_generation = 0


def set_current(colors: dict) -> None:
    """Remember the colours in use, for the few widgets that paint themselves (the meters) or build their own sheet."""
    global _current, _generation
    _current = dict(colors)
    _generation += 1


def generation() -> int:
    """A number that changes whenever the colours in use change: painters that cache colours compare it."""
    return _generation


def color(name: str) -> str:
    return _current.get(name) or DARK[name]


# ----------------------------------------------------------------------------- reading and checking
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_hex(value) -> str:
    """'#abc' or '#aabbcc' (any case) -> '#aabbcc'. Anything else is an error: nothing else may reach the style sheet."""
    if not isinstance(value, str) or not _HEX.match(value.strip()):
        raise ThemeError(f"{value!r} is not a colour. Use a hex value such as #1a2b3c.")
    text = value.strip().lower()
    if len(text) == 4:
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "theme"
    return text + "-custom" if text in BUILT_IN or text == SYSTEM else text


def parse(data, fallback_name: str = "Imported theme") -> tuple:
    """Check a decoded theme file. Returns (Theme, notes): notes are things that were ignored. Raises ThemeError."""
    if not isinstance(data, dict):
        raise ThemeError("That file does not look like a Sluice theme (it should be a JSON object).")
    name = data.get("name", fallback_name)
    if not isinstance(name, str) or not name.strip():
        raise ThemeError('The theme needs a name, for example "name": "Midnight".')
    name = " ".join(name.split())[:40]
    base = data.get("base", "dark")
    if base not in ("dark", "light"):
        raise ThemeError('"base" must be "dark" or "light": it supplies any colour the file leaves out.')
    given = data.get("colors", {})
    if not isinstance(given, dict):
        raise ThemeError('"colors" must be a list of name: colour pairs.')
    colors = dict(DARK if base == "dark" else LIGHT)
    notes = []
    from .depth import (
        DEPTH_TOKENS,
    )  # the depth colours (0.11.5) are optional: worked out from the others when a file leaves them out

    for key, value in given.items():
        if key not in TOKEN_NAMES and key not in DEPTH_TOKENS:
            notes.append(f"ignored “{str(key)[:40]}”: not a colour Sluice uses")
            continue
        try:
            colors[key] = normalize_hex(value)
        except ThemeError as exc:
            raise ThemeError(f"“{key}”: {exc}") from exc
    colors = complete(colors, given=[k for k in given if k in TOKEN_NAMES])
    return Theme(CUSTOM_PREFIX + slug(name), name, base, colors), notes


def load_file(path) -> tuple:
    path = Path(path)
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ThemeError("That file is too large to be a theme.")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ThemeError(f"That file could not be read as a theme: {exc}") from exc
    return parse(data, fallback_name=path.stem.replace("-", " ").replace("_", " ").title())


# --- contrast: the text must stay readable, whatever colours a file brings
def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# (foreground, background, smallest ratio, what it is). 4.5 is the usual bar for body text; hints and tags are small
# and dim by design, so they get 3.
CONTRAST_CHECKS = (
    ("text", "bg", 4.5, "the main text on the window"),
    ("text", "panel", 4.5, "the main text on the channel strips"),
    ("text", "dialog", 4.5, "the main text in dialogs"),
    ("text", "popup", 4.5, "the text in menus"),
    ("strong", "input", 4.5, "the numbers in the level boxes"),
    ("list_text", "input", 4.5, "the text in lists and text boxes"),
    ("button_text", "button", 3.0, "the text on buttons"),
    ("text_dim", "panel", 3.0, "the small hints"),
    ("text_faint", "panel", 3.0, "the small labels"),
    ("select_text", "select_soft", 4.5, "the selected line in a list"),
    ("text", "select", 3.0, "the highlighted line in a menu"),
    ("strong", "applied", 3.0, "the app buttons at the bottom"),
    ("text2", "panel", 4.5, "the secondary text on the channel strips"),
    ("text2", "surface2", 4.5, "the source names and device buttons"),
    ("text_dim", "bg", 3.0, "the small grey text on the window"),
    ("text_dim", "surface2", 3.0, "the small grey text on buttons and chips"),
    ("text_dim", "panel", 3.0, "the small grey text on a strip"),
    ("accent_text", "accent_bg", 4.5, "the text on a switched-on button"),
    ("mute_fg", "mute_bg", 4.5, "the crossed speaker on a muted button"),
    ("live_fg", "live_bg", 4.5, "the Live label"),
    ("focus", "bg", 3.0, "the keyboard focus ring on the window"),
    ("focus", "panel", 3.0, "the keyboard focus ring on a strip"),
    ("accent", "panel", 3.0, "the accent colour on a strip"),
)


def polish(colors: dict) -> dict:
    """The built-in themes only: small text moved just far enough to read (4.5 to 1) on every surface it sits on."""
    c = dict(colors)
    c.setdefault("sidebar", mix(c["bg"], "#000000", 0.3))
    for name in (
        "text",
        "text_dim",
        "text_faint",
        "text2",
        "list_text",
        "button_text",
        "strong",
        "title",
        "check_text",
        "ok",
        "warn",
        "error",
        "link",
    ):  # 0.13.1: every surface of the House Standard's check, not only three
        for surface in ("bg", "panel", "mix", "surface2", "button", "chip", "row_hover", "dialog", "popup", "sidebar"):
            c[name] = readable(c[name], c[surface], 4.5)
    if contrast_ratio(c["on_color"], c["accent"]) < 4.5:  # the ink on a filled accent button: dark or white, whichever reads
        c["on_color"] = (
            "#0c1016" if contrast_ratio("#0c1016", c["accent"]) >= contrast_ratio("#ffffff", c["accent"]) else "#ffffff"
        )
    for name in ("text_dim", "text_faint"):
        for surface in ("bg", "panel", "surface2"):
            c[name] = readable(c[name], c[surface], 4.5)
    for surface in ("surface2", "panel"):
        c["text2"] = readable(c["text2"], c[surface], 4.5)
    c["accent_text"] = readable(c["accent"], c["accent_bg"], 4.5)
    c["mute_fg"] = readable(c["mute"], c["mute_bg"], 4.5)
    c["live_fg"] = readable(c["ok"], c["live_bg"], 4.5)
    return c


for _palette in (
    CONTRAST,
    PAPER,
    COLOUR_BLIND,
    OLED,
    SYNTHWAVE,
):  # the older sets get the 0.10.0 colours worked out from their own
    _palette.update(polish(complete(_palette)))
for _palette in (DARK, LIGHT):
    _palette.update(polish(_palette))


# Drawn things (the focus ring, the accent on a strip) need 3 to 1, the usual bar for graphics; only text needs 4.5.
GRAPHICS = ("focus", "accent")


def contrast_problems(colors: dict, strict: bool = False) -> list:
    """Plain-language list of text that would be hard to read. ``strict`` demands the usual 4.5 everywhere."""
    problems = []
    for fg, bg, minimum, what in CONTRAST_CHECKS:
        need = minimum if fg in GRAPHICS else (4.5 if strict else minimum)
        ratio = contrast_ratio(colors[fg], colors[bg])
        if ratio < need:
            problems.append(f"{what} ({fg} on {bg}) is hard to read: contrast {ratio:.1f}, it should be at least {need:g}")
    return problems


# 0.13.1 (House Standard v1.3): every text colour on every surface it can sit on, 4.5 to 1, and the ink on a filled accent
HOUSE_TEXT = (
    "text",
    "text_dim",
    "text_faint",
    "text2",
    "list_text",
    "button_text",
    "strong",
    "title",
    "check_text",
    "ok",
    "warn",
    "error",
    "link",
)
HOUSE_SURFACES = ("bg", "panel", "mix", "surface2", "button", "chip", "row_hover", "dialog", "popup", "sidebar")


def house_contrast_problems(colors: dict) -> list:
    """The House Standard's check, for the built-in themes: each text colour on each surface, and on_color on the accent."""
    problems = []
    for fg in HOUSE_TEXT:
        for bg in HOUSE_SURFACES:
            ratio = contrast_ratio(colors[fg], colors[bg])
            if ratio < 4.5:
                problems.append(f"{fg} on {bg}: {ratio:.2f}")
    ratio = contrast_ratio(colors["on_color"], colors["accent"])
    if ratio < 4.5:
        problems.append(f"on_color on accent (a filled button): {ratio:.2f}")
    return problems


# ----------------------------------------------------------------------------- the folder of imported themes
def themes_dir(config_file) -> Optional[Path]:
    return None if config_file is None else Path(config_file).parent / "themes"


def _is_built_in_copy(theme: Theme) -> bool:
    """A file with a built-in theme's name and exactly its colours (a theme renamed or changed by the person is their own)."""
    return any(theme.name == built.name and theme.colors == built.colors for built in BUILT_IN.values())


def custom_themes(folder: Optional[Path], hide_duplicates: bool = True) -> list:
    """The imported themes in the folder, by name. A file that cannot be used is skipped.

    A file that is an exact copy of a built-in theme (for example Midnight Blue from the first theme pack, which is
    built in now) is left out of the menu so the theme is not listed twice; ``resolve`` and ``canonical_id`` still know it."""
    if folder is None or not Path(folder).is_dir():
        return []
    found = []
    try:
        files = sorted(Path(folder).glob("*.json"))[:MAX_CUSTOM]
    except OSError:
        return []
    for path in files:
        try:
            theme, _notes = load_file(path)
        except ThemeError:
            continue
        if hide_duplicates and _is_built_in_copy(theme):
            continue
        found.append(Theme(CUSTOM_PREFIX + path.stem, theme.name, theme.base, theme.colors))
    return sorted(found, key=lambda t: t.name.lower())


def save_custom(theme: Theme, folder: Path) -> Theme:
    """Write a theme into the folder (replacing one of the same name). Returns it with its stored id."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = slug(theme.name)
    (folder / f"{name}.json").write_text(json.dumps(export_dict(theme), indent=2) + "\n", encoding="utf-8")
    return Theme(CUSTOM_PREFIX + name, theme.name, theme.base, theme.colors)


def remove_custom(theme_id: str, folder: Optional[Path]) -> bool:
    if folder is None or not theme_id.startswith(CUSTOM_PREFIX):
        return False
    name = theme_id[len(CUSTOM_PREFIX) :]
    if not name or Path(name).name != name or name.startswith("."):  # a file name, never a path
        return False
    try:
        (Path(folder) / f"{name}.json").unlink()
        return True
    except OSError:
        return False


def export_dict(theme: Theme) -> dict:
    from .depth import DEPTH_TOKENS

    colors = {k: theme.colors[k] for k in TOKEN_NAMES}
    colors.update({k: theme.colors[k] for k in DEPTH_TOKENS if k in theme.colors})  # depth colours the theme set by hand
    return {"name": theme.name, "base": theme.base, "colors": colors}


def canonical_id(theme_id: str, folder: Optional[Path] = None) -> str:
    """The id to show as chosen: an imported file with a built-in theme's exact colours counts as that built-in theme."""
    if isinstance(theme_id, str) and theme_id.startswith(CUSTOM_PREFIX):
        for theme in custom_themes(folder, hide_duplicates=False):
            if theme.id == theme_id:
                for built in BUILT_IN.values():
                    if built.name == theme.name and built.colors == theme.colors:
                        return built.id
    return theme_id


# Themes the pack no longer ships (0.11.5). A file someone imported stays in their themes folder and keeps working; only if the file is
# gone does the saved choice fall back, and then to the closest built-in theme.
RETIRED_THEMES = {
    "amber-console": "dark",
    "halloween": "dark",
    "midnight-blue": "dark",
    "ocean": "dark",
    "paper": "paper",
    "cassette": "paper",
    "sepia-reader": "paper",
    "studio-slate": "dark",
    "vintage-hi-fi": "dark",
    # 0.13.1: retired built-in themes (House Standard v1.3: Midnight Blue became the default's look, Amber Console's amber now
    # means "warning", and seven themes are kept). Settings that chose them show Dark; imported themes are never touched.
    "purple": "dark",
    "midnight": "dark",
    "amber": "dark",
}


def resolve(theme_id: str, system_dark: bool = True, folder: Optional[Path] = None) -> Theme:
    """The theme to show for a saved choice. Anything unknown or damaged is the default dark theme."""
    if theme_id == SYSTEM:
        return BUILT_IN["dark" if system_dark else "light"]
    if theme_id in BUILT_IN:
        return BUILT_IN[theme_id]
    if isinstance(theme_id, str) and theme_id.startswith(CUSTOM_PREFIX):
        for theme in custom_themes(folder, hide_duplicates=False):
            if theme.id == theme_id:
                return theme
        nearest = RETIRED_THEMES.get(theme_id[len(CUSTOM_PREFIX) :])
        if nearest:  # a theme from the old pack whose file has gone: the closest built-in one, not plain Dark
            return BUILT_IN[nearest]
    return BUILT_IN[DEFAULT]
