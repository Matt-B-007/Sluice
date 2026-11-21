# SPDX-License-Identifier: GPL-3.0-or-later
"""The Original look: the style sheet Sluice had up to 0.9.7 (small corners, 12-pixel text, flat buttons), kept as it was and given a
few extra rules for the parts that were added later. It uses the same colour names as every other look, so every theme works in it.

Part of the Look setting (View > Look). The window's own layout code is shared between the looks; this sheet and the painting
choices in ``ui.py`` are what make one look different from another."""
from __future__ import annotations

from string import Template

ORIGINAL_STYLE = Template("""
QMainWindow, QWidget#root, QScrollArea, QWidget#channels { background: $bg; }
QWidget { color: $text; font-size: 14px; }
QToolTip { background: $popup; color: $text; border: 1px solid $button_border; padding: 4px; }
QFrame#strip, QFrame#mix, QFrame#apps {
    background: $panel; border: 1px solid $border; border-radius: 8px;
}
QFrame#mix { background: $mix; }
QFrame#apps { border-radius: 6px; }
QFrame#chip { background: $chip; border: 1px solid $line; border-radius: 4px; }
QFrame#accent { border: none; border-radius: 2px; }
QLabel { background: transparent; }
QLabel#title { font-size: 18px; font-weight: 700; color: $title; }
QLabel#tag { font-size: 11px; font-weight: 600; letter-spacing: 1px; color: $text_faint; }
QLabel#hint { font-size: 12px; color: $text_dim; }
QLabel#feedback { font-size: 13px; color: $text_dim; }
QLabel#chiptext { font-size: 13px; background: transparent; }
QLabel#readout { font-family: monospace; font-size: 13px; color: $strong;
    background: $input; border: 1px solid $border_soft; border-radius: 4px; padding: 2px 0; }
QLineEdit#readout { font-family: monospace; font-size: 13px; color: $strong; background: $input;
    border: 1px solid $border_soft; border-radius: 4px; padding: 2px 0; }
QLineEdit#readout[compact="true"], QLabel#readout[compact="true"] { font-size: 12px; }
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
    border-radius: 8px; font-size: 15px; }
QPushButton#addchannel:hover, QPushButton#addmix:hover { border-color: $hover; color: $text; }
QPushButton#app { padding: 3px 10px; border-radius: 11px; }
QPushButton#appassigned { padding: 3px 10px; border-radius: 11px; color: $strong; background: $applied; }
QToolButton { background: transparent; border: none; color: $text_dim; font-weight: 700; padding: 0 4px; }
QToolButton:hover { color: $error; }
QToolButton#menu:hover { color: $strong; }
QToolButton::menu-indicator { image: none; width: 0; }

QComboBox {
    background: $input; border: 1px solid $border; border-radius: 4px; padding: 3px 6px; min-height: 0; font-weight: 400; color: $text;
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

/* Rules for parts added after 0.9.7, so they sit in the old look instead of being left bare: the old corners (4 to 8), the old
   text sizes (10 to 13) and its flat, thin-bordered buttons. */
QFrame#row { background: $panel; border: 1px solid $border; border-radius: 8px; }
QFrame#strip[empty="true"], QFrame#empty { background: transparent; border: 2px dashed $line; border-radius: 8px; }
QFrame#sourcechip, QFrame#statuschip { background: $chip; border: 1px solid $line; border-radius: 4px; }
QFrame#firstrun, QFrame#livepanel, QFrame#detail { background: $panel; border: 1px solid $border; border-radius: 8px; }
QFrame#segmented { background: transparent; border: 1px solid $border; border-radius: 6px; }
QFrame#mixcell { background: transparent; border: none; }
QLabel#appname, QLabel#name { font-size: 18px; font-weight: 700; color: $title; }
QLabel#version, QLabel#ratetext { font-size: 12px; color: $text_dim; }
QLabel#dropouts, QLabel#intro { font-size: 14px; color: $text_dim; }
QLabel#mixheading { font-size: 11px; font-weight: 600; letter-spacing: 1px; color: $text_faint; background: transparent; }
QLabel#bigvalue { font-size: 18px; font-weight: 700; color: $title; background: transparent; }
QLabel#gatechip, QLabel#livechip { font-size: 13px; font-weight: 600; padding: 2px 8px; border-radius: 4px; background: $chip; color: $text; }
QLabel#gatechip[open="true"], QLabel#livechip { background: $live_bg; color: $live_fg; }
QLabel#step, QLabel#stepoff { font-size: 15px; font-weight: 700; border-radius: 12px; }
QLabel#step { color: $on_color; background: $accent; }
QLabel#stepoff { color: $text_dim; background: $well; }
QPushButton#primary { background: $accent; color: $on_color; border-color: transparent; }
QPushButton#iconbutton, QPushButton#plain { padding: 2px; border-radius: 4px; min-height: 0; }
QPushButton#plain { background: transparent; border: none; }
QPushButton#addchip, QPushButton#devicebutton, QPushButton#quiet { border-radius: 4px; padding: 3px 8px; font-weight: 600; min-height: 0; }
QPushButton#addchip { border: 1px dashed $line; color: $text_dim; background: transparent; }
QPushButton#segment { border: none; background: transparent; border-radius: 4px; padding: 3px 10px; color: $text_dim; min-height: 0; }
QPushButton#segment:checked { background: $accent; color: $on_color; }
QPushButton#limiter { font-size: 13px; }
QPushButton#hintbutton { background: transparent; border: none; color: $text_dim; font-size: 12px; font-weight: 400; padding: 0; min-height: 0; }
QPushButton#hintbutton:hover { color: $text; }
QToolButton#remove:hover { color: $error; }
QStatusBar { background: $bg; border: none; }
QMessageBox { background: $dialog; }
""")


# ---- the colours the built-in themes had in 0.9.7. The Original look shows them (the themes' ids and names are the same), so
# "Dark" in the Original look is the Dark of 0.9.7 and not today's. They hold the colours 0.9.7 knew; ``themes.complete`` works out the rest.
_DARK = {
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

_LIGHT = {
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

_CONTRAST = {
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

_PURPLE = {
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

_MIDNIGHT = {
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

_AMBER = {
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

_PAPER = {
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

ORIGINAL_PALETTES = {"dark": _DARK, "light": _LIGHT, "contrast": _CONTRAST, "purple": _PURPLE, "midnight": _MIDNIGHT,
                     "amber": _AMBER, "paper": _PAPER}
