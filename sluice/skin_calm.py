# SPDX-License-Identifier: GPL-3.0-or-later
"""The Calm skin's own colours (0.12.2): warm white cards on a soft paper background for Light, graphite cards for Dark, with Listen in
blue and Broadcast in a warm orange. Shown on the plain Dark and Light themes while Settings > Themes and skins > Skin's own colours is
on (the default); every other theme keeps its own colours in Calm."""
from __future__ import annotations

CALM_LIGHT = {
    "bg": "#f3f2ee", "panel": "#ffffff", "mix": "#ffffff", "border": "#eae8e3", "border_soft": "#eae8e3",
    "text": "#1b1b1f", "text_dim": "#6b6a70", "text_faint": "#6b6a70", "text_off": "#8c8b92", "title": "#1b1b1f",
    "strong": "#1b1b1f", "input": "#faf9f6", "well": "#ecebe6", "chip": "#faf9f6", "button": "#faf9f6",
    "button_text": "#1b1b1f", "button_border": "#e3e1db", "hover": "#b3b1aa", "line": "#e2e0da", "accent": "#2e6bd9",
    "select": "#dbe6fa", "select_soft": "#e8effb", "select_text": "#1b1b1f", "popup": "#ffffff", "dialog": "#faf9f6",
    "fill": "#2e6bd9", "handle": "#ffffff", "handle_edge": "#d2d0ca", "handle_hover": "#faf9f6", "applied": "#e8effb",
    "scroll_track": "#ecebe6", "scroll_hover": "#b3b1aa", "scroll_press": "#8c8b92", "row_hover": "#f3f2ee",
    "list_text": "#1b1b1f", "check_text": "#3a3940", "link": "#2e6bd9", "code": "#b45a17", "ok": "#1f8f62",
    "alarm": "#c62828", "warn": "#8f5a00", "error": "#c62e42", "muted": "#8c8b92", "mute": "#d63c3c",
    "limiter": "#1f8f62", "linked": "#2e6bd9", "on_color": "#ffffff",
    "surface2": "#faf9f6", "border2": "#e3e1db", "text2": "#55545b", "track": "#ecebe6", "meter_bg": "#ecebe6",
    "accent_bg": "#e8effb", "accent_text": "#2459b8", "mute_bg": "#fde9e8", "mute_fg": "#c42b2b", "live_bg": "#e2f3ea",
    "live_fg": "#17734e", "dashed": "#c4c2bb", "focus": "#2e6bd9",
}

CALM_DARK = {
    "bg": "#141518", "panel": "#1e1f23", "mix": "#1e1f23", "border": "#2c2d32", "border_soft": "#2c2d32",
    "text": "#edecea", "text_dim": "#a3a2a9", "text_faint": "#a3a2a9", "text_off": "#77767d", "title": "#f5f4f2",
    "strong": "#f5f4f2", "input": "#25262b", "well": "#17181b", "chip": "#25262b", "button": "#25262b",
    "button_text": "#edecea", "button_border": "#303136", "hover": "#5a5960", "line": "#34353b", "accent": "#6b9bf2",
    "select": "#1b2b47", "select_soft": "#17263f", "select_text": "#ffffff", "popup": "#222327", "dialog": "#1a1b1e",
    "fill": "#6b9bf2", "handle": "#f5f4f2", "handle_edge": "#f5f4f2", "handle_hover": "#ffffff", "applied": "#17263f",
    "scroll_track": "#17181b", "scroll_hover": "#3e3f45", "scroll_press": "#5a5960", "row_hover": "#25262b",
    "list_text": "#edecea", "check_text": "#d5d4d9", "link": "#6b9bf2", "code": "#f0a05a", "ok": "#3ccb93",
    "alarm": "#b3262c", "warn": "#f0c03a", "error": "#ff7b7b", "muted": "#77767d", "mute": "#ff6b6b",
    "limiter": "#3ccb93", "linked": "#6b9bf2", "on_color": "#141518",
    "surface2": "#25262b", "border2": "#303136", "text2": "#c2c1c7", "track": "#2a2b30", "meter_bg": "#17181b",
    "accent_bg": "#17263f", "accent_text": "#8db3f7", "mute_bg": "#3a1d21", "mute_fg": "#ff8a8a", "live_bg": "#12261d",
    "live_fg": "#3ccb93", "dashed": "#3e3f45", "focus": "#6b9bf2",
}

CALM_THEMES = {"dark": CALM_DARK, "light": CALM_LIGHT}
