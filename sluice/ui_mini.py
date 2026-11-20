"""The compact list: every channel on one line (its colour, name, a slider and a mute button) for a window too small for the cards.
It is also the picture the desktop widgets use. It drives the same engine calls as the cards; the cards stay alive, hidden, so
everything else in the window (the tray, the controllers, the bug report) keeps working."""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import themes
from . import ui_icons as icons


def _db_text(db: float) -> str:
    return "off" if db <= -60 else f"{db:.1f} dB"


class MiniStrip(QWidget):
    """A list of channels for one mix at a time (Listen or Broadcast), and that mix's master line at the bottom."""

    def __init__(self, window, tile: bool = False) -> None:
        super().__init__()
        from .ui import Fader  # here: ui imports this module

        self.tile = tile  # the Tile look: each line is a mini tile with one lane (fader and meter in one)
        self.window_ = window
        self.engine = window.engine
        self._fader_class = Fader
        self.setObjectName("ministrip")
        self.mix_id = self.engine.mixer.mixes[0].id if self.engine.mixer.mixes else "monitor"
        self.rows: dict = {}
        self.master: dict = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*((12, 12, 12, 20) if tile else (0, 0, 0, 0)))  # Tile: the mini keys sit in a tray
        outer.setSpacing(8)
        self._tray = None
        self.choice = QFrame()
        self.choice.setObjectName("segmented")
        pick = QHBoxLayout(self.choice)
        pick.setContentsMargins(4, 4, 4, 4)
        pick.setSpacing(4)
        self.choice_buttons: dict = {}
        for mix in self.engine.mixer.mixes:
            button = QPushButton(mix.label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setAccessibleName(f"Show the {mix.label} levels")
            button.setToolTip({"monitor": "Listen: the levels of what you hear", "stream": "Broadcast: the levels of what your audience hears"}
                              .get(mix.id, f"The levels of {mix.label}"))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(partial(self.choose_mix, mix.id))
            pick.addWidget(button)
            self.choice_buttons[mix.id] = button
        outer.addWidget(self.choice)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(0 if tile else 6)
        outer.addLayout(self.list_box)
        outer.addStretch(1)
        rule = QFrame()
        rule.setObjectName("divider")
        rule.setFixedHeight(1)
        outer.addWidget(rule)
        self.master_row = self._make_row("Main", None)
        outer.addWidget(self.master_row)
        self.master_row.fader.gainChanged.connect(self._master_level)
        self.master_row.mute.toggled.connect(self._master_mute)
        self.rebuild()

    # ---------------------------------------------------------------- building
    def _make_row(self, text: str, channel) -> QWidget:
        if self.tile:
            return self._make_tile(text, channel)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        color = channel.color if channel is not None else themes.color("accent")
        dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        from .ui import ElidedLabel  # here: ui imports this module

        name = ElidedLabel(text)
        name.setObjectName("name")
        name.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        name.setFixedWidth(84)
        name.setToolTip(text)
        fader = self._fader_class(horizontal=True)
        fader.set_fill(color)
        fader.setMinimumWidth(64)
        readout = QLabel("0.0 dB")
        readout.setObjectName("ratetext")
        readout.setMinimumWidth(52)
        readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mute = QPushButton("")
        mute.setObjectName("mute")
        mute.setCheckable(True)
        mute.setFixedSize(34, 30)
        mute.setCursor(Qt.CursorShape.PointingHandCursor)
        for widget in (dot, name):
            line.addWidget(widget)
        line.addWidget(fader, 1)
        line.addWidget(readout)
        line.addWidget(mute)
        row.fader, row.readout, row.mute, row.name, row.channel = fader, readout, mute, name, channel
        return row

    def _make_tile(self, text: str, channel) -> QWidget:
        from . import look_tile
        from .ui_tile import MiniTile  # here: ui_tile imports ui, which imports this module

        if channel is not None:
            row = MiniTile(text, look_tile.channel_color(channel), look_tile.channel_icon(channel))
        else:
            row = MiniTile(text, themes.color("accent"), "speaker")
        row.channel = channel
        return row

    def push_levels(self, levels: dict) -> None:
        """The live signal on each mini tile's lane, for the mix chosen at the top (the Tile look only)."""
        for channel_id, row in self.rows.items():
            row.fader.push(levels.get(f"ch:{channel_id}:{self.mix_id}", 0.0))
        self.master_row.fader.push(levels.get(f"mix:{self.mix_id}", 0.0))

    def rebuild(self) -> None:
        """One line for each channel now in the mixer."""
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget():
                item.widget().hide()  # at once: the old line must not show beside the new one until it is deleted
                item.widget().deleteLater()
        self.rows = {}
        for channel in self.engine.mixer.channels:
            row = self._make_row(channel.label, channel)
            row.fader.setAccessibleName(f"{channel.label} level")
            row.mute.setAccessibleName(f"Mute {channel.label}")
            row.fader.gainChanged.connect(partial(self._level, channel.id))
            row.mute.toggled.connect(partial(self._mute, channel.id))
            self.list_box.addWidget(row)
            self.rows[channel.id] = row
        self.master_row.fader.setAccessibleName("Main level")
        self.master_row.mute.setAccessibleName("Mute main")
        self.choose_mix(self.mix_id if any(m.id == self.mix_id for m in self.engine.mixer.mixes)
                        else self.engine.mixer.mixes[0].id)

    # ---------------------------------------------------------------- doing
    def choose_mix(self, mix_id: str, _checked: bool = False) -> None:
        self.mix_id = mix_id
        for key, button in self.choice_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == mix_id)
            button.blockSignals(False)
        mix = next((m for m in self.engine.mixer.mixes if m.id == mix_id), None)
        self.master_row.name.setText(mix.label if mix is not None else "Main")
        self.sync_from_model()

    def _level(self, channel_id: str, value: int) -> None:
        self.engine.set_level(channel_id, self.mix_id, value / 10.0)
        self.window_.sync_from_model()

    def _mute(self, channel_id: str, on: bool) -> None:
        self.engine.set_mute(channel_id, self.mix_id, on)
        self.window_.sync_from_model()

    def _master_level(self, value: int) -> None:
        self.engine.set_master(self.mix_id, value / 10.0)
        self.window_.sync_from_model()

    def _master_mute(self, on: bool) -> None:
        self.engine.set_master_mute(self.mix_id, on)
        self.window_.sync_from_model()

    def sync_from_model(self) -> None:
        """Show the model's values (also after a controller or `sluice ctl` changed them)."""
        for channel in self.engine.mixer.channels:
            row = self.rows.get(channel.id)
            if row is None:
                continue
            db = channel.levels.get(self.mix_id, 0.0)
            muted = bool(channel.mutes.get(self.mix_id))
            self._show(row, db, muted)
        mix = next((m for m in self.engine.mixer.mixes if m.id == self.mix_id), None)
        if mix is not None:
            self._show(self.master_row, mix.gain_db, bool(mix.mute))

    def _show(self, row: QWidget, db: float, muted: bool) -> None:
        for widget in (row.fader, row.mute):
            widget.blockSignals(True)
        row.fader.setGain(round(db * 10))
        row.mute.setChecked(muted)
        for widget in (row.fader, row.mute):
            widget.blockSignals(False)
        if self.tile:
            from . import look_tile

            row.fader.set_muted(muted)
            row.readout.setText("Muted" if muted else _db_text(db))
            if bool(row.readout.property("muted")) != muted:
                row.readout.setProperty("muted", muted)
                row.readout.style().unpolish(row.readout)
                row.readout.style().polish(row.readout)
            name = look_tile.LANE_ICONS.get(self.mix_id, "speaker") if row.channel is not None else ("speaker_off" if muted else "speaker")
            row.mute.setIcon(icons.icon(name, themes.color("mute_fg" if muted else "text2"), 16))
        else:
            row.readout.setText(_db_text(db))
            row.mute.setIcon(icons.icon("speaker_off" if muted else "speaker", themes.color("mute_fg" if muted else "text"), 18))
        label = self.mix_label()
        who = row.channel.label if row.channel is not None else "the main level"
        row.mute.setToolTip(f"{'Unmute' if muted else 'Mute'} {who} in {label}")

    def mix_label(self) -> str:
        mix = next((m for m in self.engine.mixer.mixes if m.id == self.mix_id), None)
        return mix.label if mix is not None else "this mix"

    def paintEvent(self, event) -> None:
        if not self.tile:
            super().paintEvent(event)
            return
        if self._tray is None:
            from .ui_tile import TrayPainter
            self._tray = TrayPainter()  # the same tray as behind the big tiles
        p = QPainter(self)
        self._tray.draw(self, p)
        p.end()

    def refresh_theme(self) -> None:
        if self._tray is not None:
            self._tray.reset()
        if hasattr(self, "rows"):
            self.sync_from_model()
