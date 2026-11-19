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
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Optional

SYSTEM = "system"          # "Match my system": follows the desktop's light or dark setting
CUSTOM_PREFIX = "custom:"  # an imported theme: custom:<file name without .json>
MAX_FILE_BYTES = 64 * 1024
MAX_CUSTOM = 40            # imported themes shown (the rest of a crowded folder is ignored)

TOKEN_NAMES = (
    "bg", "panel", "mix", "border", "border_soft", "text", "text_dim", "text_faint", "text_off", "title", "strong",
    "input", "well", "chip", "button", "button_text", "button_border", "hover", "line", "accent", "select",
    "select_soft", "select_text", "popup", "dialog", "fill", "handle", "handle_edge", "handle_hover", "applied",
    "scroll_track", "scroll_hover", "scroll_press", "row_hover", "list_text", "check_text", "link", "code", "ok",
    "alarm", "warn", "error", "muted", "mute", "limiter", "linked", "on_color",
    # added in 0.10.0. A theme file that does not list them gets them worked out from its own colours (see ``complete``).
    "surface2", "border2", "text2", "track", "meter_bg", "accent_bg", "accent_text", "mute_bg", "mute_fg", "live_bg",
    "live_fg", "dashed", "focus",
)
NEW_TOKENS = TOKEN_NAMES[TOKEN_NAMES.index("surface2"):]

DARK = {
    "bg": "#0e1116", "panel": "#151a22", "mix": "#18202b", "border": "#232b37", "border_soft": "#232b37",
    "text": "#e7ecf3", "text_dim": "#8794a7", "text_faint": "#8794a7", "text_off": "#667386", "title": "#f4f7fb",
    "strong": "#f2f5fa", "input": "#10141b", "well": "#10141b", "chip": "#1b212b", "button": "#1b212b",
    "button_text": "#e7ecf3", "button_border": "#2a3340", "hover": "#4a5668", "line": "#2f3948", "accent": "#3ddbc0",
    "select": "#17423d", "select_soft": "#12342e", "select_text": "#ffffff", "popup": "#151a22", "dialog": "#12161d",
    "fill": "#3ddbc0", "handle": "#f2f5fa", "handle_edge": "#f2f5fa", "handle_hover": "#ffffff", "applied": "#12342e",
    "scroll_track": "#12161d", "scroll_hover": "#3a4556", "scroll_press": "#4a5668", "row_hover": "#1b212b",
    "list_text": "#e7ecf3", "check_text": "#b7c1cf", "link": "#6ab0ff", "code": "#e6c07b", "ok": "#5be3b0",
    "alarm": "#b3262c", "warn": "#f5c542", "error": "#ff7a88", "muted": "#6f7887", "mute": "#ef5258",
    "limiter": "#35d0c0", "linked": "#3ddbc0", "on_color": "#0e1116",
    "surface2": "#1b212b", "border2": "#2a3340", "text2": "#b7c1cf", "track": "#222a36", "meter_bg": "#10141b",
    "accent_bg": "#12342e", "accent_text": "#3ddbc0", "mute_bg": "#3a1b22", "mute_fg": "#ff7a88", "live_bg": "#12261f",
    "live_fg": "#5be3b0", "dashed": "#2f3948", "focus": "#3b82f6",
}

LIGHT = {
    "bg": "#f3f5f9", "panel": "#ffffff", "mix": "#f8fafc", "border": "#dde2eb", "border_soft": "#dde2eb",
    "text": "#121722", "text_dim": "#5b6678", "text_faint": "#5b6678", "text_off": "#8a94a2", "title": "#0b0f17",
    "strong": "#111827", "input": "#eef1f6", "well": "#e3e8f0", "chip": "#eef1f6", "button": "#eef1f6",
    "button_text": "#121722", "button_border": "#d3d9e4", "hover": "#7a8493", "line": "#b9c2d1", "accent": "#0f9d8a",
    "select": "#c9ece6", "select_soft": "#d6f2ec", "select_text": "#0b0f17", "popup": "#ffffff", "dialog": "#f8fafc",
    "fill": "#0f9d8a", "handle": "#ffffff", "handle_edge": "#bfc8d6", "handle_hover": "#f0f4fa", "applied": "#d6f2ec",
    "scroll_track": "#e6eaf2", "scroll_hover": "#98a2b0", "scroll_press": "#7f8b9b", "row_hover": "#eef1f6",
    "list_text": "#121722", "check_text": "#2e3748", "link": "#1f5fcc", "code": "#8a5a00", "ok": "#0a7a55",
    "alarm": "#c62828", "warn": "#8a5a00", "error": "#c62e42", "muted": "#7a8493", "mute": "#e0414a",
    "limiter": "#1fb3a3", "linked": "#0b7f70", "on_color": "#0e1014",
    "surface2": "#eef1f6", "border2": "#d3d9e4", "text2": "#2e3748", "track": "#e3e8f0", "meter_bg": "#e6eaf2",
    "accent_bg": "#d6f2ec", "accent_text": "#0b7f70", "mute_bg": "#fde3e6", "mute_fg": "#c62e42", "live_bg": "#ddf5ec",
    "live_fg": "#0a7a55", "dashed": "#b9c2d1", "focus": "#2563eb",
}

CONTRAST = {
    "bg": "#000000", "panel": "#0a0a0a", "mix": "#0f0f0f", "border": "#9aa0a6", "border_soft": "#9aa0a6",
    "text": "#ffffff", "text_dim": "#d6dade", "text_faint": "#d6dade", "text_off": "#9aa0a6", "title": "#ffffff",
    "strong": "#ffffff", "input": "#000000", "well": "#2b2b2b", "chip": "#1a1a1a", "button": "#161616",
    "button_text": "#ffffff", "button_border": "#c0c5cb", "hover": "#ffd400", "line": "#9aa0a6", "accent": "#ffd400",
    "select": "#1f4fd8", "select_soft": "#1f4fd8", "select_text": "#ffffff", "popup": "#000000", "dialog": "#050505",
    "fill": "#00a86b", "handle": "#ffffff", "handle_edge": "#ffffff", "handle_hover": "#ffd400", "applied": "#1f4fd8",
    "scroll_track": "#161616", "scroll_hover": "#c0c5cb", "scroll_press": "#ffd400", "row_hover": "#1a1a1a",
    "list_text": "#ffffff", "check_text": "#ffffff", "link": "#8fd3ff", "code": "#ffd400", "ok": "#7dff9a",
    "alarm": "#d40000", "warn": "#ffd400", "error": "#ff6b6b", "muted": "#9aa0a6", "mute": "#ff5a5f",
    "limiter": "#35d0c0", "linked": "#c0c5cb", "on_color": "#000000",
}

PURPLE = {
    "bg": "#150c2b", "panel": "#21143f", "mix": "#1d1138", "border": "#4a2f7d", "border_soft": "#4a2f7d",
    "text": "#efe4ff", "text_dim": "#b39ddb", "text_faint": "#a58fd0", "text_off": "#7a68a0", "title": "#ffffff",
    "strong": "#f7efff", "input": "#0e0720", "well": "#0a0518", "chip": "#2d1b57", "button": "#2f1c5a",
    "button_text": "#d9c6ff", "button_border": "#6a45b0", "hover": "#ff4fd8", "line": "#5a3a96", "accent": "#ff4fd8",
    "select": "#6b2a8f", "select_soft": "#5a2480", "select_text": "#ffffff", "popup": "#1a0f35", "dialog": "#1b1033",
    "fill": "#12b5c8", "handle": "#fff1ff", "handle_edge": "#ff4fd8", "handle_hover": "#ffffff", "applied": "#6b2a8f",
    "scroll_track": "#24164a", "scroll_hover": "#7a52b8", "scroll_press": "#ff4fd8", "row_hover": "#2a1a52",
    "list_text": "#f4eaff", "check_text": "#e5d5ff", "link": "#8fd3ff", "code": "#ffd166", "ok": "#6dffb0",
    "alarm": "#c2185b", "warn": "#ffd166", "error": "#ff6b8b", "muted": "#8d78bd", "mute": "#ef5258",
    "limiter": "#2ee6d6", "linked": "#a58fd0", "on_color": "#0a0518",
}

MIDNIGHT = {
    "bg": "#0b1220", "panel": "#121c31", "mix": "#0e1728", "border": "#2a3c60", "border_soft": "#1f2e4b",
    "text": "#d6e0f2", "text_dim": "#8ea0bf", "text_faint": "#8ea0bf", "text_off": "#505e78", "title": "#eff3fa",
    "strong": "#e6ecf7", "input": "#070c15", "well": "#05080e", "chip": "#222c40", "button": "#263044",
    "button_text": "#bdcae0", "button_border": "#495a7a", "hover": "#4aa3ff", "line": "#2a3c60", "accent": "#4aa3ff",
    "select": "#1f4a85", "select_soft": "#17345d", "select_text": "#ffffff", "popup": "#0d1626", "dialog": "#0f182a",
    "fill": "#2c6a8f", "handle": "#eaf0f8", "handle_edge": "#8ea0bf", "handle_hover": "#ffffff", "applied": "#1f4a85",
    "scroll_track": "#0f182a", "scroll_hover": "#515b6f", "scroll_press": "#747e92", "row_hover": "#1c263b",
    "list_text": "#d6e0f2", "check_text": "#c8d3e8", "link": "#6fb3ff", "code": "#e6c07b", "ok": "#8fd19e",
    "alarm": "#b3262c", "warn": "#e0a030", "error": "#ef5258", "muted": "#6f7887", "mute": "#ef5258",
    "limiter": "#35d0c0", "linked": "#8ea0bf", "on_color": "#0e1014",
}

AMBER = {
    "bg": "#14100b", "panel": "#1f1912", "mix": "#1a140e", "border": "#4a3a24", "border_soft": "#372b1c",
    "text": "#f0dcb4", "text_dim": "#b39a6e", "text_faint": "#b39a6e", "text_off": "#695a40", "title": "#f9f1e1",
    "strong": "#f6ead2", "input": "#0d0a07", "well": "#090705", "chip": "#30291f", "button": "#342c22",
    "button_text": "#dbc59c", "button_border": "#68573e", "hover": "#ffb000", "line": "#4a3a24", "accent": "#ffb000",
    "select": "#6a4a10", "select_soft": "#48330e", "select_text": "#fff3d6", "popup": "#18130d", "dialog": "#1b150f",
    "fill": "#2f6b4f", "handle": "#ffe9bd", "handle_edge": "#b39a6e", "handle_hover": "#ffffff", "applied": "#6a4a10",
    "scroll_track": "#1b150f", "scroll_hover": "#625746", "scroll_press": "#887a63", "row_hover": "#29231a",
    "list_text": "#f0dcb4", "check_text": "#e4cfa6", "link": "#ffc94d", "code": "#ffd980", "ok": "#8fd19e",
    "alarm": "#b3262c", "warn": "#e0a030", "error": "#ef5258", "muted": "#6f7887", "mute": "#ef5258",
    "limiter": "#35d0c0", "linked": "#b39a6e", "on_color": "#0e1014",
}

PAPER = {
    "bg": "#f1ece2", "panel": "#fbf8f2", "mix": "#f6f2ea", "border": "#cfc6b4", "border_soft": "#e3dcd0",
    "text": "#2b2620", "text_dim": "#665e50", "text_faint": "#665e50", "text_off": "#b0aba1", "title": "#110f0d",
    "strong": "#1a1713", "input": "#fdfcf9", "well": "#d4d0c7", "chip": "#eae7e1", "button": "#e6e3dd",
    "button_text": "#403a31", "button_border": "#b1a999", "hover": "#857b68", "line": "#cfc6b4", "accent": "#b4532a",
    "select": "#f0d3c2", "select_soft": "#f0ddcf", "select_text": "#101418", "popup": "#fbf8f2", "dialog": "#f7f3ec",
    "fill": "#46a97b", "handle": "#ffffff", "handle_edge": "#665e50", "handle_hover": "#f0f4fa", "applied": "#f0d3c2",
    "scroll_track": "#f7f3ec", "scroll_hover": "#b8b5af", "scroll_press": "#938f89", "row_hover": "#f1eee8",
    "list_text": "#2b2620", "check_text": "#37312a", "link": "#9a3f1a", "code": "#8a5a00", "ok": "#237a43",
    "alarm": "#c62828", "warn": "#8a5a00", "error": "#c62828", "muted": "#7a8493", "mute": "#e0414a",
    "limiter": "#1fb3a3", "linked": "#9a917c", "on_color": "#0e1014",
}


# ----------------------------------------------------------------------------- working out the colours a file leaves out
def _rgb(value: str) -> tuple:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


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
    return c


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    base: str            # "dark" or "light": what a theme file's missing colours come from
    colors: dict


BUILT_IN: dict = {
    "dark": Theme("dark", "Dark", "dark", DARK),
    "light": Theme("light", "Light", "light", LIGHT),
    "contrast": Theme("contrast", "High contrast", "dark", CONTRAST),
    "purple": Theme("purple", "Retro Purple", "dark", PURPLE),
    "midnight": Theme("midnight", "Midnight Blue", "dark", MIDNIGHT),
    "amber": Theme("amber", "Amber Console", "dark", AMBER),
    "paper": Theme("paper", "Paper", "light", PAPER),
}
DEFAULT = "dark"
SYSTEM_LABEL = "Match my system"


class ThemeError(ValueError):
    """A theme file that cannot be used; the message is meant for the person who chose it."""


# ----------------------------------------------------------------------------- style sheet
STYLE_TEMPLATE = Template("""
/* The look of 0.10.0. Spacing in steps of 8, three text sizes (12 caption, 14 body, 20 title), corners 8 / 12 / 24. */
QMainWindow, QWidget#root, QScrollArea, QWidget#channels, QWidget#sources { background: $bg; }
QWidget { color: $text; font-size: 14px; }
QToolTip { background: $popup; color: $text; border: 1px solid $button_border; padding: 8px; border-radius: 8px; }
QFrame#strip, QFrame#row {
    background: $panel; border: 1px solid $border; border-radius: 24px;
}
QFrame#row { border-radius: 20px; }
QFrame#strip[empty="true"] { background: transparent; border: 2px dashed $dashed; }
QFrame#mix { background: $mix; border: 1px solid $border2; border-radius: 24px; }
QFrame#sourcechip { background: $surface2; border: none; border-radius: 8px; }
QFrame#chip { background: $surface2; border: none; border-radius: 8px; }
QFrame#statuschip { background: transparent; border: 1px solid $border; border-radius: 12px; }
QFrame#divider { background: $border2; max-width: 1px; min-width: 1px; }
QFrame#empty { background: transparent; border: 2px dashed $dashed; border-radius: 24px; }
QFrame#firstrun { background: $panel; border: 1px solid $border2; border-radius: 24px; }
QFrame#accent { border: none; border-radius: 2px; }
QLabel { background: transparent; }
QLabel#appname { font-size: 20px; font-weight: 700; color: $title; }
QLabel#version { font-size: 12px; color: $text_dim; }
QLabel#title { font-size: 20px; font-weight: 700; color: $title; }
QLabel#name { font-size: 20px; font-weight: 600; color: $title; }
QLabel#tag { font-size: 12px; font-weight: 600; letter-spacing: 0.5px; color: $text_faint; }
QLabel#tag[narrow="true"] { font-size: 11px; letter-spacing: 0; }
QLabel#tag[mix="monitor"] { color: $listen_text; }
QLabel#tag[mix="stream"] { color: $broadcast_text; }
QFrame#mix[mix="monitor"] { border-color: $listen_edge; }
QFrame#mix[mix="stream"] { border-color: $broadcast_edge; }
QFrame#mixcell { background: transparent; border: 1px solid transparent; border-radius: 12px; }
QFrame#mixcell[mix="monitor"] { background: $listen_tint; border-color: $listen_edge; }
QFrame#mixcell[mix="stream"] { background: $broadcast_tint; border-color: $broadcast_edge; }
QLabel#mixheading { font-size: 12px; font-weight: 700; letter-spacing: 0.5px; background: transparent; }
QLabel#mixheading[mix="monitor"] { color: $listen_text; }
QLabel#mixheading[mix="stream"] { color: $broadcast_text; }
QLabel#hint { font-size: 12px; color: $text_dim; }
QLabel#feedback { font-size: 12px; color: $text_dim; }
QLabel#chiptext { font-size: 12px; color: $text2; background: transparent; }
QFrame#livepanel { background: $panel; border: 1px solid $border; border-radius: 24px; }
QFrame#detail { background: $panel; border: 1px solid $border; border-radius: 24px; }
QLabel#swatch { border-radius: 6px; background: $text_dim; }
QLabel#swatch[who="out"] { background: $accent; }
QLabel#bigvalue { font-size: 20px; font-weight: 700; color: $title; background: transparent; }
QLabel#gatechip { font-size: 12px; font-weight: 600; padding: 4px 16px; border-radius: 12px; background: $surface2; color: $text2; }
QLabel#gatechip[open="true"] { background: $live_bg; color: $live_fg; }
QLabel#livechip { font-size: 12px; font-weight: 600; color: $live_fg; background: $live_bg; border-radius: 16px; padding: 7px 16px; }
QLabel#ratetext { font-size: 12px; color: $text_dim; }
QLabel#dropouts { font-size: 14px; color: $text2; }
QLabel#readout { font-size: 14px; font-weight: 600; color: $strong; background: transparent; border: none; }
QLineEdit#readout { font-size: 14px; font-weight: 600; color: $strong; background: transparent; border: 2px solid transparent;
    border-radius: 8px; padding: 1px 0; }
QLineEdit#readout:hover { border-color: $border2; }
QLineEdit#readout:focus { border-color: $focus; background: $input; }
QLineEdit#readout[big="true"] { font-size: 20px; font-weight: 700; }
QLabel#status { color: $text_dim; font-size: 12px; padding: 0 8px; }
QLabel#demo { color: #1b1300; background: #f5c542; font-weight: 700; font-size: 12px; border-radius: 8px; padding: 4px 12px; }
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
QPushButton[compact="true"] { border-radius: 8px; min-height: 30px; padding: 0 8px; font-size: 12px; font-weight: 500; }
QPushButton[compact="true"]:focus { padding: 0 7px; }
QPushButton#primary { background: $accent; color: $on_color; border-color: transparent; }
QPushButton#primary:hover { border-color: $hover; }
QPushButton#iconbutton { padding: 0; border-radius: 12px; }
QPushButton#iconbutton[compact="true"] { border-radius: 8px; }
QPushButton#mute { background: $track; border: 2px solid transparent; padding: 0; }
QPushButton#mute:checked { background: $mute_bg; border-color: transparent; }
QPushButton#mute:focus { border-color: $focus; }
QPushButton#limiter { border: 2px solid transparent; font-size: 12px; font-weight: 700; background: $track; color: $text2; }
QPushButton#limiter:checked { background: $accent_bg; color: $accent_text; border-color: transparent; }
QPushButton#limiter:focus { border-color: $focus; }
QPushButton#link { padding: 0; border-radius: 8px; background: $surface2; border: 1px solid $border2; }
QPushButton#link:checked { background: $accent_bg; border-color: $accent; }
QPushButton#link:focus { border: 1px solid $focus; }
QPushButton#micmute { padding: 0; border-radius: 8px; background: transparent; border: 2px solid transparent; min-height: 0; min-width: 0; }
QPushButton#micmute:checked { background: $mute_bg; border-color: transparent; }
QPushButton#micmute:focus { border-color: $focus; }
QPushButton#iconbutton:focus { border: 1px solid $focus; }
QPushButton#addchip { border: 2px dashed $dashed; color: $text_dim; background: transparent; border-radius: 8px;
    min-height: 28px; font-size: 12px; font-weight: 500; padding: 0 8px; }
QPushButton#addchip:hover { border-color: $hover; color: $text; }
QPushButton#addchip:focus { border: 2px solid $focus; padding: 0 8px; }
QPushButton#addchip[iconly="true"]:focus { border: 1px solid $focus; padding: 0; }
QPushButton#addchip[iconly="true"] { border-radius: 8px; padding: 0; border-style: solid; border-width: 1px; border-color: $border2; min-height: 0; }
QPushButton#plain { background: transparent; border: 2px solid transparent; padding: 0; border-radius: 8px; min-height: 0; }
QPushButton#plain:hover { background: $surface2; }
QPushButton#plain:focus { border-color: $focus; }
QFrame#segmented { background: transparent; border: 1px solid $border; border-radius: 12px; }
QPushButton#segment { border: 2px solid transparent; background: transparent; min-height: 30px; border-radius: 9px; padding: 0 14px; font-size: 12px; color: $text2; }
QPushButton#segment:checked { background: $accent_bg; color: $accent_text; border-color: transparent; }
QPushButton#segment:focus { border-color: $focus; }
QLabel#intro { color: $text2; }
QPushButton#addchannel { border: 2px dashed $dashed; color: $text_dim; background: transparent; border-radius: 24px;
    font-size: 14px; font-weight: 600; }
QPushButton#addchannel:hover { border-color: $hover; color: $text; }
QPushButton#addchannel:focus { border: 2px solid $focus; }
QPushButton#quiet { background: transparent; border: 1px solid $border2; color: $text2; font-size: 12px; font-weight: 600; }
QPushButton#quiet:checked { background: $accent_bg; color: $accent_text; border-color: transparent; }
QPushButton#quiet:focus { border: 2px solid $focus; padding: 0 15px; }
QPushButton#devicebutton { background: $surface2; border: 1px solid $border2; color: $text2; font-size: 12px; font-weight: 500;
    text-align: left; padding: 0 12px; }
QPushButton#devicebutton:focus { border: 2px solid $focus; padding: 0 11px; }
QPushButton#app { padding: 3px 12px; border-radius: 12px; }
QPushButton#appassigned { padding: 3px 12px; border-radius: 12px; color: $strong; background: $applied; }
QPushButton:flat { background: transparent; border: none; min-height: 0; padding: 2px 8px; font-size: 12px; }
QToolButton { background: transparent; border: 2px solid transparent; color: $text_dim; font-weight: 700; padding: 0 2px; border-radius: 8px; }
QToolButton:hover { color: $strong; background: $surface2; }
QToolButton:focus { border-color: $focus; }
QToolButton#remove:hover { color: $error; }
QToolButton::menu-indicator { image: none; width: 0; }

QComboBox {
    background: $surface2; border: 1px solid $border2; border-radius: 12px; padding: 0 12px; min-height: 38px;
    font-size: 12px; font-weight: 500; color: $text2;
}
QComboBox:hover { border-color: $hover; }
QComboBox:focus { border: 2px solid $focus; padding: 0 11px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: $popup; border: 1px solid $button_border; selection-background-color: $select;
    selection-color: $select_text; font-size: 14px; padding: 8px; outline: 0;
}
QMenu { background: $popup; border: 1px solid $button_border; padding: 8px; border-radius: 12px; font-size: 14px; }
QMenu::item { padding: 8px 24px; border-radius: 8px; }
QMenu::item:selected { background: $select; color: $select_text; }
QMenu::item:disabled { color: $text_off; }
QMenu::separator { height: 1px; background: $border; margin: 8px 8px; }
QMenuBar { background: $bg; color: $button_text; }
QMenuBar::item { padding: 8px 12px; border-radius: 8px; }
QMenuBar::item:selected { background: $chip; }
QDialog { background: $dialog; }
QMessageBox { background: $dialog; }
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
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: $line; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }

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
""")


def mix_colors(colors: dict) -> dict:
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


LOOKS = {"calm": "Calm", "original": "Original", "nexus": "Nexus"}  # the Look setting: shapes, sizes and painting, apart from colour
DEFAULT_LOOK = "calm"


_look = DEFAULT_LOOK


def set_look(look) -> None:
    """Remember the look in use, for the widgets that draw or lay themselves out differently from one look to another."""
    global _look
    _look = valid_look(look)


def current_look() -> str:
    return _look


_reduce = False


def set_reduce_effects(on: bool) -> None:
    """Nexus's "reduce effects": the rings stop shimmering and the faders show no waveform. Remembered here for the widgets that draw."""
    global _reduce
    _reduce = bool(on)


def reduce_effects() -> bool:
    return _reduce


def look_colors(theme: "Theme", look: str) -> dict:
    """The colours to show for a theme in a look. The Original look shows the built-in themes as they were in 0.9.7;
    imported themes, and every other look, show the theme's own colours."""
    if valid_look(look) == "nexus" and theme.id == "dark":  # Nexus has its own Dark; the other themes keep their colours
        from .look_nexus import NEXUS_DARK
        return complete({**theme.colors, **NEXUS_DARK}, given=NEXUS_DARK.keys())
    if valid_look(look) == "original" and theme.id in BUILT_IN:
        from .look_original import ORIGINAL_PALETTES
        old = ORIGINAL_PALETTES.get(theme.id)
        if old is not None:
            return complete({**theme.colors, **old}, given=old.keys())
    return theme.colors


def valid_look(look) -> str:
    """A saved look id that exists, or the default (an id from a newer or older Sluice never breaks the window)."""
    return look if isinstance(look, str) and look in LOOKS else DEFAULT_LOOK


@lru_cache(maxsize=16)
def _style_for(items: tuple, look: str = DEFAULT_LOOK) -> str:
    values = dict(items)
    values.update(mix_colors(values))
    if look == "original":
        from .look_original import ORIGINAL_STYLE
        return ORIGINAL_STYLE.substitute(values)
    if look == "nexus":  # the Calm sheet with Nexus's rules after it: the later rule wins where both name the same thing
        from .look_nexus import NEXUS_STYLE_EXTRA
        return STYLE_TEMPLATE.substitute(values) + NEXUS_STYLE_EXTRA.substitute(values)
    return STYLE_TEMPLATE.substitute(values)


def build_style(colors: dict, look: str = DEFAULT_LOOK) -> str:
    """The window's style sheet for a complete colour set in a look (cached: switching back costs nothing)."""
    return _style_for(tuple(sorted(colors.items())), valid_look(look))


# ----------------------------------------------------------------------------- the theme in use
_current: dict = dict(DARK)


def set_current(colors: dict) -> None:
    """Remember the colours in use, for the few widgets that paint themselves (the meters) or build their own sheet."""
    global _current
    _current = dict(colors)


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
        raise ThemeError("The theme needs a name, for example \"name\": \"Midnight\".")
    name = " ".join(name.split())[:40]
    base = data.get("base", "dark")
    if base not in ("dark", "light"):
        raise ThemeError("\"base\" must be \"dark\" or \"light\": it supplies any colour the file leaves out.")
    given = data.get("colors", {})
    if not isinstance(given, dict):
        raise ThemeError("\"colors\" must be a list of name: colour pairs.")
    colors = dict(DARK if base == "dark" else LIGHT)
    notes = []
    for key, value in given.items():
        if key not in TOKEN_NAMES:
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
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
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
    for name in ("text_dim", "text_faint"):
        for surface in ("bg", "panel", "surface2"):
            c[name] = readable(c[name], c[surface], 4.5)
    for surface in ("surface2", "panel"):
        c["text2"] = readable(c["text2"], c[surface], 4.5)
    c["accent_text"] = readable(c["accent"], c["accent_bg"], 4.5)
    c["mute_fg"] = readable(c["mute"], c["mute_bg"], 4.5)
    c["live_fg"] = readable(c["ok"], c["live_bg"], 4.5)
    return c


for _palette in (CONTRAST, PURPLE, MIDNIGHT, AMBER, PAPER):  # the older sets get the 0.10.0 colours worked out from their own
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
    name = theme_id[len(CUSTOM_PREFIX):]
    if not name or Path(name).name != name or name.startswith("."):  # a file name, never a path
        return False
    try:
        (Path(folder) / f"{name}.json").unlink()
        return True
    except OSError:
        return False


def export_dict(theme: Theme) -> dict:
    return {"name": theme.name, "base": theme.base, "colors": {k: theme.colors[k] for k in TOKEN_NAMES}}


def canonical_id(theme_id: str, folder: Optional[Path] = None) -> str:
    """The id to show as chosen: an imported file with a built-in theme's exact colours counts as that built-in theme."""
    if isinstance(theme_id, str) and theme_id.startswith(CUSTOM_PREFIX):
        for theme in custom_themes(folder, hide_duplicates=False):
            if theme.id == theme_id:
                for built in BUILT_IN.values():
                    if built.name == theme.name and built.colors == theme.colors:
                        return built.id
    return theme_id


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
    return BUILT_IN[DEFAULT]
