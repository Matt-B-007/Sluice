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
)

DARK = {
    "bg": "#181b20", "panel": "#232830", "mix": "#20262e", "border": "#373d47", "border_soft": "#2e343d",
    "text": "#d7dce2", "text_dim": "#8a93a0", "text_faint": "#8590a0", "text_off": "#5d6672", "title": "#f0f3f6",
    "strong": "#e8eef5", "input": "#12151a", "well": "#0e1014", "chip": "#2c323c", "button": "#303641",
    "button_text": "#aab2bd", "button_border": "#454c58", "hover": "#6f7887", "line": "#3d4551", "accent": "#5b8def",
    "select": "#34507a", "select_soft": "#2d3a52", "select_text": "#ffffff", "popup": "#1b1f26", "dialog": "#1d2127",
    "fill": "#2c5f48", "handle": "#dfe4ea", "handle_edge": "#8a93a0", "handle_hover": "#ffffff", "applied": "#2f4a6b",
    "scroll_track": "#1f232a", "scroll_hover": "#56606f", "scroll_press": "#6b7688", "row_hover": "#1d222b",
    "list_text": "#e6e9ef", "check_text": "#c9ced8", "link": "#6aa9ff", "code": "#e6c07b", "ok": "#8fd19e",
    "alarm": "#b3262c", "warn": "#e0a030", "error": "#ef5258", "muted": "#6f7887", "mute": "#ef5258",
    "limiter": "#35d0c0", "linked": "#8aa0b8", "on_color": "#0e1014",
}

LIGHT = {
    "bg": "#eceff3", "panel": "#ffffff", "mix": "#f5f7fa", "border": "#c8cfd9", "border_soft": "#c8cfd9",
    "text": "#1f2530", "text_dim": "#566070", "text_faint": "#5f6978", "text_off": "#8a94a2", "title": "#0f141b",
    "strong": "#111827", "input": "#f3f5f8", "well": "#c9d0da", "chip": "#e5e9ef", "button": "#e8ecf1",
    "button_text": "#39424f", "button_border": "#b4bcc8", "hover": "#7a8493", "line": "#b7bfca", "accent": "#2f6fe0",
    "select": "#cfe0fb", "select_soft": "#d3e2fb", "select_text": "#0f141b", "popup": "#ffffff", "dialog": "#f5f7fa",
    "fill": "#46a97b", "handle": "#ffffff", "handle_edge": "#7a8493", "handle_hover": "#f0f4fa", "applied": "#cfe0fb",
    "scroll_track": "#e1e6ec", "scroll_hover": "#98a2b0", "scroll_press": "#7f8b9b", "row_hover": "#e9eef4",
    "list_text": "#1f2530", "check_text": "#2a3340", "link": "#1f5fcc", "code": "#8a5a00", "ok": "#237a43",
    "alarm": "#c62828", "warn": "#8a5a00", "error": "#c62828", "muted": "#7a8493", "mute": "#e0414a",
    "limiter": "#1fb3a3", "linked": "#7f93ab", "on_color": "#0e1014",
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
}
DEFAULT = "dark"
SYSTEM_LABEL = "Match my system"


class ThemeError(ValueError):
    """A theme file that cannot be used; the message is meant for the person who chose it."""


# ----------------------------------------------------------------------------- style sheet
STYLE_TEMPLATE = Template("""
QMainWindow, QWidget#root, QScrollArea, QWidget#channels { background: $bg; }
QWidget { color: $text; font-size: 12px; }
QToolTip { background: $popup; color: $text; border: 1px solid $button_border; padding: 4px; }
QFrame#strip, QFrame#mix, QFrame#apps {
    background: $panel; border: 1px solid $border; border-radius: 8px;
}
QFrame#mix { background: $mix; }
QFrame#apps { border-radius: 6px; }
QFrame#chip { background: $chip; border: 1px solid $line; border-radius: 4px; }
QFrame#accent { border: none; border-radius: 2px; }
QLabel { background: transparent; }
QLabel#title { font-size: 15px; font-weight: 700; color: $title; }
QLabel#tag { font-size: 9px; font-weight: 600; letter-spacing: 1px; color: $text_faint; }
QLabel#hint { font-size: 10px; color: $text_dim; }
QLabel#feedback { font-size: 11px; color: $text_dim; }
QLabel#chiptext { font-size: 11px; background: transparent; }
QLabel#readout { font-family: monospace; font-size: 11px; color: $strong;
    background: $input; border: 1px solid $border_soft; border-radius: 4px; padding: 2px 0; }
QLineEdit#readout { font-family: monospace; font-size: 11px; color: $strong; background: $input;
    border: 1px solid $border_soft; border-radius: 4px; padding: 2px 0; }
QLineEdit#readout[compact="true"], QLabel#readout[compact="true"] { font-size: 10px; }
QLineEdit#readout:focus { border-color: $accent; }
QLabel#status { color: $text_dim; padding: 2px 8px; }
QLabel#demo { color: #1b1300; background: #f5c542; font-weight: 700; padding: 3px 10px; }
QFrame#divider { background: $border; max-width: 1px; }

QPushButton {
    background: $button; color: $button_text; border: 1px solid $button_border;
    border-radius: 4px; padding: 4px 8px; font-weight: 600;
}
QPushButton:hover { border-color: $hover; }
QPushButton:disabled { color: $text_off; }
QPushButton:checked { color: $on_color; border-color: transparent; }
QPushButton::menu-indicator { image: none; width: 0; }
QPushButton#mute:checked  { background: $mute; }
QPushButton#limiter:checked { background: $limiter; }
QPushButton#link:checked { background: $linked; }
QPushButton#micmute { background: transparent; color: $ok; border: 1px solid $button_border; padding: 5px 8px; }
QPushButton#micmute:checked { background: $alarm; color: #ffffff; border-color: transparent; }
QPushButton#add { border-style: dashed; color: $text_dim; background: transparent; }
QPushButton#addchannel, QPushButton#addmix { border: 2px dashed $line; color: $text_dim; background: transparent;
    border-radius: 8px; font-size: 13px; }
QPushButton#addchannel:hover, QPushButton#addmix:hover { border-color: $hover; color: $text; }
QPushButton#app { padding: 3px 10px; border-radius: 11px; }
QPushButton#appassigned { padding: 3px 10px; border-radius: 11px; color: $strong; background: $applied; }
QToolButton { background: transparent; border: none; color: $text_dim; font-weight: 700; padding: 0 4px; }
QToolButton:hover { color: $error; }
QToolButton#menu:hover { color: $strong; }
QToolButton::menu-indicator { image: none; width: 0; }

QComboBox {
    background: $input; border: 1px solid $border; border-radius: 4px; padding: 3px 6px;
}
QComboBox:hover { border-color: $hover; }
QComboBox QAbstractItemView {
    background: $popup; border: 1px solid $button_border; selection-background-color: $select;
    selection-color: $select_text;
}
QMenu { background: $popup; border: 1px solid $button_border; padding: 4px; }
QMenu::item { padding: 5px 18px; border-radius: 3px; }
QMenu::item:selected { background: $select; color: $select_text; }
QMenu::item:disabled { color: $text_off; }
QMenu::separator { height: 1px; background: $border; margin: 4px 6px; }
QMenuBar { background: $bg; color: $button_text; }
QMenuBar::item:selected { background: $chip; }
QDialog { background: $dialog; }
QProgressBar { background: $well; border: 1px solid $border_soft; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QTextBrowser { color: $list_text; background: $input; border: 1px solid $border_soft; padding: 6px; }
QLineEdit { background: $input; border: 1px solid $border_soft; border-radius: 6px; padding: 5px 8px; color: $list_text;
    selection-background-color: $select; selection-color: $select_text; }
QLineEdit:focus { border-color: $accent; }
QCheckBox { spacing: 8px; color: $check_text; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid $line; border-radius: 3px; background: $input; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QListWidget { background: $input; border: 1px solid $border_soft; border-radius: 6px; padding: 4px; color: $list_text;
    outline: 0; }
QListWidget::item { padding: 5px 6px; border-radius: 4px; }
QListWidget::item:selected { background: $select_soft; color: $select_text; }
QListWidget::item:hover:!selected { background: $row_hover; }
QScrollBar:horizontal { background: $scroll_track; height: 12px; border-radius: 6px; margin: 0 2px; }
QScrollBar::handle:horizontal { background: $line; border-radius: 6px; min-width: 48px; }
QScrollBar::handle:horizontal:hover { background: $scroll_hover; }
QScrollBar::handle:horizontal:pressed { background: $scroll_press; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: $line; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }

QSlider::groove:vertical { background: $well; position: absolute; left: 12px; right: 12px;
    border-radius: 3px; }
QSlider::add-page:vertical { background: $fill; border-radius: 3px; }
QSlider::handle:vertical { background: $handle; height: 22px; margin: 0 -9px;
    border-radius: 4px; border: 1px solid $handle_edge; }
QSlider::handle:vertical:hover { background: $handle_hover; }
QSlider::groove:horizontal { background: $well; height: 6px; border-radius: 3px; }
QSlider::sub-page:horizontal { background: $fill; border-radius: 3px; }
QSlider::handle:horizontal { background: $handle; width: 14px; margin: -5px 0; border-radius: 4px; }
""")


@lru_cache(maxsize=8)
def _style_for(items: tuple) -> str:
    return STYLE_TEMPLATE.substitute(dict(items))


def build_style(colors: dict) -> str:
    """The window's style sheet for a complete colour set (cached: switching back to a theme costs nothing)."""
    return _style_for(tuple(sorted(colors.items())))


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
)


def contrast_problems(colors: dict, strict: bool = False) -> list:
    """Plain-language list of text that would be hard to read. ``strict`` demands the usual 4.5 everywhere."""
    problems = []
    for fg, bg, minimum, what in CONTRAST_CHECKS:
        need = 4.5 if strict else minimum
        ratio = contrast_ratio(colors[fg], colors[bg])
        if ratio < need:
            problems.append(f"{what} ({fg} on {bg}) is hard to read: contrast {ratio:.1f}, it should be at least {need:g}")
    return problems


# ----------------------------------------------------------------------------- the folder of imported themes
def themes_dir(config_file) -> Optional[Path]:
    return None if config_file is None else Path(config_file).parent / "themes"


def custom_themes(folder: Optional[Path]) -> list:
    """The imported themes in the folder, by name. A file that cannot be used is skipped."""
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


def resolve(theme_id: str, system_dark: bool = True, folder: Optional[Path] = None) -> Theme:
    """The theme to show for a saved choice. Anything unknown or damaged is the default dark theme."""
    if theme_id == SYSTEM:
        return BUILT_IN["dark" if system_dark else "light"]
    if theme_id in BUILT_IN:
        return BUILT_IN[theme_id]
    if isinstance(theme_id, str) and theme_id.startswith(CUSTOM_PREFIX):
        for theme in custom_themes(folder):
            if theme.id == theme_id:
                return theme
    return BUILT_IN[DEFAULT]
