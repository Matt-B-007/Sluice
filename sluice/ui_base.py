# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window's shared pieces: sizes, names, small helpers and the small widgets every card uses (no cards here)."""
from __future__ import annotations

import logging
import math
import re
from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QSizePolicy, QSlider, QWidget

from . import sizing, themes
from .model import MAX_DB, MIN_DB, MONITOR, RECORDING, STREAM, linear_to_db

log = logging.getLogger("sluice.ui")

PROJECT_URL = "https://github.com/Matt-B-007/Sluice"
ISSUES_URL = PROJECT_URL + "/issues"
THEMES_URL = PROJECT_URL + "/tree/main/themes"
DISCORD_URL = "https://discord.gg/awDvJ5Vj2S"
AUTOSAVE_MS = 5000  # how often to look for unsaved changes
TALKING_LEVEL = 0.03  # the microphone peak (0 to 1, about -30 dB) above which the tray icon lights up
TALKING_HOLD = 0.35  # seconds it stays lit after the last sound, so it does not flicker between words
TRAY_WATCH_MS = 200  # how often the hidden window's tray watcher looks at the microphone
CLOSE_HINT = "closechoice"  # in hints_seen once the close choice has been made or the first-close question answered
AUTO_UPDATE_DELAY_MS = 20000  # the automatic update (if switched on) looks once, this long after start-up
TILE_GAP = -16  # Tile: keys overlap by the room they keep for their shadows (22 px a side), so 28 px of tray shows between them
TOP_BAR_GAP = 12  # between the top bar's buttons and the line under it (0.11.5)
TOP_BAR_HEIGHT = 40 + TOP_BAR_GAP
DEFAULT_SIZE = (1680, 860)  # 0.11.7: five channel cards beside Listen and Broadcast (1456 fitted only four since 0.11.5)


def default_size(available=None) -> tuple:
    """DEFAULT_SIZE, made smaller to fit ``available`` (the screen's free area as (width, height)) with a little room round it."""
    width, height = DEFAULT_SIZE
    if available:
        width, height = min(width, max(360, available[0] - 40)), min(height, max(300, available[1] - 40))
    return width, height

NONE_DATA = "__none__"  # combo item data for "no device" (Qt dislikes None)
SOURCES_HEIGHT = 80  # the list of a channel's devices and apps: at most this tall (then it scrolls)...
SOURCES_MIN = 32     # ...and at least one chip tall (0.12.0). Every card in the window takes the tallest list any of them needs.
COLUMN_WIDTH = 80            # one mix's column on a channel card: the fader, its meter, the level and the mute button
CHANNEL_WIDTH = 2 * COLUMN_WIDTH + 32     # a channel card with two mixes (Listen and Broadcast)
CHANNEL_WIDTH_THREE = 3 * COLUMN_WIDTH + 32   # ...and with the optional third one
MIX_WIDTH = 224              # a master card in the Columns layout
FIRST_RUN_WIDTH = 560
ROW_NAME_WIDTH = 148         # the Rows layout: the name and what is on the channel
ROW_TOOLS_WIDTH = 148        # ...the Effects and Link buttons
ROW_CELL_MIN = sizing.ROW_CELL_MIN  # ...and the least width of one mix's slider, level and mute button (the window plans with it)
LAYOUTS = ("columns", "rows")
EMPTY_HINTS = {"mic": "Your microphone goes here.", "browser": "Chrome, Firefox and other browsers.",
               "game": "Games and anything loud.", "chat": "Discord and voice chat.", "music": "Spotify, VLC and players.",
               "system": "Notification sounds and everything else."}
MIX_TAGS = {MONITOR: "LISTEN", STREAM: "BROADCAST", RECORDING: "RECORDING"}
MIX_HEADINGS = {MONITOR: "you hear", STREAM: "audience hears", RECORDING: "recorder hears"}
MIX_NAMES = {MONITOR: "Listen: what you hear", STREAM: "Broadcast: what your audience hears",
             RECORDING: "Recording: what your recorder hears"}


def plain(text: str, keep_dots: bool = False) -> str:
    """A menu item's name as plain text (0.12.0: the one helper for this): no Alt-key mark, no shortcut after a tab, and no
    trailing "…" unless ``keep_dots`` (a row that opens a window keeps them)."""
    text = text.split("\t")[0].replace("&&", "\0").replace("&", "").replace("\0", "&")
    return text if keep_dots else text.rstrip("\u2026")


_PROFILE = re.compile(r"\s+(?:(?:Analog|Digital|Pro|Multichannel)(?:\s+(?:Stereo|Mono|Surround\s+[\d.]+|Input|Output))?|Mono)"
                      r"(?:\s+\(([^)]*)\))?$")


def short_device_name(description: str) -> str:
    """A device's name short enough for a card (0.12.0; the full one goes in its tooltip): PipeWire's profile words go
    ("Analog Stereo", "Digital Stereo (IEC958)"), a chipset's model numbers go, and a sound chip built into the computer is called
    what it is. "Navi 21/23 HDMI/DP Audio Controller Digital Stereo (HDMI 3)" becomes "HDMI 3"; "Family 17h (Models 00h-0fh) HD
    Audio Controller Analog Stereo" becomes "Built-in audio"; "Blue Yeti Analog Stereo" becomes "Blue Yeti"."""
    text = (description or "").strip()
    match = _PROFILE.search(text)
    detail = ""
    if match:
        detail = match.group(1) or ""
        text = text[:match.start()].strip()
    text = re.sub(r"\s*\((?:Models?|Rev)[^)]*\)", "", text).strip()
    hdmi = re.match(r"HDMI\s*\d*", detail)
    if re.search(r"HDMI|DisplayPort|\bDP\b", text) and "Controller" in text:
        return hdmi.group(0) if hdmi else "HDMI"
    if re.search(r"\bHD Audio Controller\b|\bHigh Definition Audio\b|^Built-in Audio$", text):
        return "Built-in audio" + (" (digital)" if detail == "IEC958" else f" ({detail})" if detail and not hdmi else "")
    return text or description


def channel_width(mix_count: int) -> int:
    return CHANNEL_WIDTH if mix_count <= 2 else CHANNEL_WIDTH_THREE


def _is_nexus(rows: bool = False) -> bool:
    """True in the Nexus look (the Columns layout; the Rows layout keeps its own shape until Nexus has one)."""
    return themes.current_skin() == "nexus" and not rows


def _is_tile() -> bool:
    """True in the Tile look (raised keys)."""
    return themes.current_skin() == "tile"


STYLE = themes.build_style(themes.DARK)  # the default look; MainWindow.apply_theme() sets the chosen one


def level_fraction(linear: float) -> float:
    """Map a linear amplitude to 0..1 along a -60 dB .. 0 dB meter scale."""
    return max(0.0, min(1.0, (linear_to_db(linear) - MIN_DB) / -MIN_DB))


def format_db(db: float) -> str:
    if db <= MIN_DB:
        return "-inf dB"
    return "0.0 dB" if abs(db) < 0.05 else f"{db:+.1f} dB"


# ----------------------------------------------------------------------------- 0.12.3: levels as percentages too
UNITS = "both"  # "both", "db" or "percent" (Settings > Mixer > Show levels as); the window sets it from the settings


def db_to_percent(db: float) -> float:
    """A level in dB as the percent KDE's volume slider and PulseAudio show: 0 dB is 100%, -18 dB is about 50%, -60 dB (the
    bottom of a fader) about 10% and off is 0%. Above 0 dB it goes past 100%, as KDE's slider does (+12 dB is about 158%).
    (PulseAudio's percent is the cube root of the amplitude, so percent = 100 x 10^(dB/60).)"""
    if db <= MIN_DB:
        return 0.0
    return 100.0 * 10.0 ** (db / 60.0)


def percent_to_db(percent: float) -> float:
    """The other way: 50% is about -18 dB; 0% or less is off."""
    if percent <= 0:
        return float("-inf")
    return max(MIN_DB, min(MAX_DB, 60.0 * math.log10(percent / 100.0)))


def format_percent(db: float) -> str:
    return f"{db_to_percent(db):.0f}%"


def format_level(db: float, narrow: bool = False) -> str:
    """A level as the settings say: "-18.0 dB · 50%", "-18.0 dB" or "50%". ``narrow`` (Tile's small number boxes): one of the
    two only, dB when both are wanted (the box's tooltip gives the other)."""
    if UNITS == "percent":
        return format_percent(db)
    if UNITS == "db" or narrow:
        return format_db(db)
    if db <= MIN_DB:
        return "-inf dB · 0%"
    number = "0.0" if abs(db) < 0.05 else f"{db:+.1f}"
    return f"{number} dB · {format_percent(db)}"


LEVEL_HELP = ("\nScroll over the number to change the level (hold Shift for fine steps), or click and type a level, in dB "
              "(for example -12) or in percent (for example 50%), and press Enter.")


def short_level(db: float) -> str:
    """A level in the fewest characters, for the desktop widgets' small dials and rows: "-12", "+3.5" or "50%"."""
    if db <= MIN_DB:
        return "off"
    if UNITS == "percent":
        return format_percent(db)
    return f"{db:+.0f}" if abs(db) >= 10 else f"{db:+.1f}"


def level_forms(db: float, narrow: bool = False) -> list:
    """The ways to show a level, longest first, for a box to take the first that fits: "-18.0 dB · 50%", "-18 dB · 50%",
    "-18 · 50%" (whole dB, the unit in the tooltip), then the dB alone (or the percent alone when levels are shown in percent
    only)."""
    full = format_level(db, narrow)
    if UNITS != "both" or narrow:
        return [full]
    if db <= MIN_DB:
        return [full, "off · 0%", format_db(db)]
    number = f"{db:+.0f}" if round(db) else "0"
    pct = format_percent(db)
    return [full, f"{number} dB · {pct}", f"{number} · {pct}", f"{number}\u2009·\u2009{pct}", format_db(db)]


def level_tip(db: float) -> str:
    """Both ways of saying a level, for a tooltip."""
    return f"{format_db(db)} = {format_percent(db)}"


def parse_level(text: str) -> Optional[float]:
    """A level typed into a number box, in dB: "-18", "-18 dB" and "50%" (or "50 %") all work. A bare number counts as dB, or as
    a percent when levels are shown in percent only."""
    number = parse_number(text)
    if number is None or number != number or number == float("-inf"):
        return number
    if "%" in text or UNITS == "percent" and "db" not in text.lower():
        return percent_to_db(number)
    return number


class ElidedLabel(QLabel):
    """A one-line label that ends in an ellipsis when its text does not fit, instead of being cut off (and that never makes its
    layout wider than the room there is)."""

    def __init__(self, text: str = "", tip_when_cut: bool = False) -> None:
        super().__init__(text)
        self._full = text
        self._tip_when_cut = tip_when_cut  # the whole text as a tooltip while it is cut
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._show_fitting()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._show_fitting()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:  # a style sheet's font arrives after the first fit: fit again with it
            self._show_fitting()

    def _show_fitting(self) -> None:
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, max(8, self.width()))
        QLabel.setText(self, shown)
        if self._tip_when_cut:
            self.setToolTip(self._full if shown != self._full else "")

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().minimumSizeHint().height())


def elide(text: str, width: int, widget: QWidget) -> str:
    return QFontMetrics(widget.font()).elidedText(text, Qt.TextElideMode.ElideRight, width)


# ----------------------------------------------------------------------- basics
# Fader taper: (position 0..1 along the fader, dB). Most of the travel is spent between -30 dB and +12 dB, where
# you actually mix, and the quiet end is squeezed together. A straight dB scale spends most of the fader on levels
# nobody uses, so a small move near the top changes the sound far less than a small move near the bottom.
FADER_TAPER = ((0.0, MIN_DB), (0.14, -40.0), (0.25, -30.0), (0.38, -20.0), (0.55, -10.0), (0.75, 0.0), (1.0, MAX_DB))
FADER_STEPS = 1000


def fader_position_to_db(position: float) -> float:
    position = max(0.0, min(1.0, position))
    for (p0, d0), (p1, d1) in zip(FADER_TAPER, FADER_TAPER[1:]):
        if position <= p1:
            return d0 + (d1 - d0) * (position - p0) / (p1 - p0)
    return MAX_DB


def db_to_fader_position(db: float) -> float:
    db = max(MIN_DB, min(MAX_DB, db))
    for (p0, d0), (p1, d1) in zip(FADER_TAPER, FADER_TAPER[1:]):
        if db <= d1:
            return p0 + (p1 - p0) * (db - d0) / (d1 - d0)
    return 1.0


def _label(text: str, name: str = "", center: bool = True) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    if center:
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


MIX_ICONS = {MONITOR: "headphones", STREAM: "broadcast", RECORDING: "mic"}



_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")


def parse_number(text: str) -> Optional[float]:
    """The first number in what someone typed: '-18', '-18 dB', '3.5:1', '50%', '1,5' (comma as decimal point).
    Returns None when there is no number. A bare '-inf' or 'off' counts as minus infinity."""
    cleaned = text.strip().lower().replace(",", ".")
    if re.match(r"^[-+]?\s*(inf|infinity)\b", cleaned) and cleaned.startswith("-") or cleaned in ("off", "-inf", "-inf db"):
        return float("-inf")
    match = _NUMBER.search(cleaned)
    return float(match.group()) if match else None


class ResetSlider(QSlider):
    """A slider that says so when it is double-clicked (the owner puts the value back to its default)."""

    reset_requested = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.reset_requested.emit()
        event.accept()


class ReadoutEdit(QLineEdit):
    """A value display that can also be typed into. Press Enter (or click away) to apply what was typed.

    ``entered`` carries the number typed, or None if there was no number; whoever owns the widget then sets the
    text again from the real value, so a bad entry just snaps back."""

    entered = Signal(object)
    levels = False  # 0.12.3: a level box: "50%" is understood as well as "-18" (dB)
    wheeled = Signal(float)  # notches turned over the box (up is positive); emitted only when ``wheel_steps`` is on
    wheel_steps = False

    def __init__(self, width: Optional[int] = 78) -> None:
        super().__init__()
        self.setObjectName("readout")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if width:
            self.setFixedWidth(width)
        self.setToolTip("Click and type a value, then press Enter")
        self.editingFinished.connect(self._finished)
        self.returnPressed.connect(self.clearFocus)

    def wheelEvent(self, event) -> None:
        """Hovering over a level and turning the wheel nudges it, like the fader beside it. Shift makes the steps fine."""
        if not self.wheel_steps or not self.isEnabled():
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y() or event.angleDelta().x()  # some systems turn Shift+wheel into a sideways scroll
        if delta:
            notches = delta / 120.0
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                notches /= 10.0
            self.wheeled.emit(notches)
        event.accept()

    def show_level(self, db: float, narrow: bool = False) -> None:
        """0.12.3: show a level in the longest form that fits the box (see ``level_forms``), and say it both ways in the
        tooltip. Shown again in the right form when the box changes size."""
        self._level_shown = (db, narrow)
        forms = level_forms(db, narrow)
        room = self.width() - 8  # (the 2 px border and the line edit's own 2 px margin each side)
        metrics = self.fontMetrics()
        text = next((f for f in forms if metrics.horizontalAdvance(f) <= room), forms[-1]) if self.width() > 30 else forms[0]
        if not self.hasFocus() and text != self.text():
            self.setText(text)
        self.setToolTip(level_tip(db) + LEVEL_HELP)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        shown = getattr(self, "_level_shown", None)
        if shown is not None and not self.hasFocus():
            self.show_level(*shown)

    def _finished(self) -> None:
        if self.isModified() or self.hasFocus():
            self.entered.emit(parse_level(self.text()) if self.levels else parse_number(self.text()))
        self.setModified(False)


MIX_MUTE_TIPS = {MONITOR: "what you hear", STREAM: "what your audience hears", RECORDING: "what your recorder hears"}


def mute_tip(mix, muted: bool) -> str:
    what = MIX_MUTE_TIPS.get(mix.id, f"the {mix.label} mix")
    return f"Muted: {what} has none of this channel. Click to unmute." if muted else f"Mute this channel in {what}"


def _icon_button(name: str, tip: str, size: int, checkable: bool = False, compact: bool = False) -> QPushButton:
    button = QPushButton()
    button.setObjectName("iconbutton")
    button.setFixedSize(size, size)
    button.setToolTip(tip)
    button.setAccessibleName(tip.split(":")[0])
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setCheckable(checkable)
    if compact:
        button.setProperty("compact", True)
    return button
