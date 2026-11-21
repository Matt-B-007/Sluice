# SPDX-License-Identifier: GPL-3.0-or-later
"""The master cards: Listen, Broadcast and the optional Recording mix, with their device pickers."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QStyle, QStyleOptionComboBox, QStylePainter, QToolButton, QVBoxLayout,
    QWidget,
)

from . import themes, ui_icons as icons
from .engine import Engine
from .model import MAX_DB, MIN_DB, Mix, MONITOR, RECORDING, STREAM
from .ui_base import (
    _icon_button, _is_nexus, _is_original, _is_tile, _label, _slot, _toggle, ElidedLabel, format_db, MIX_ICONS, MIX_MUTE_TIPS,
    MIX_WIDTH, NONE_DATA, ORIGINAL_MIX_WIDTH, ReadoutEdit,
)
from .ui_meters import Fader, LevelMeter, NexusRing

log = logging.getLogger("sluice.ui")


class DeviceCombo(QComboBox):
    """Device picker. Item data: '' = system default, NONE_DATA = disabled, else a device name. ``prefix`` is drawn before the
    chosen name on the closed box ("Output: ...") and is not part of the list."""

    about_to_show = Signal()

    def __init__(self, prefix: str = "") -> None:
        super().__init__()
        self.prefix = prefix
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.setFixedHeight(40)

    def showPopup(self) -> None:
        self.about_to_show.emit()
        super().showPopup()

    def paintEvent(self, _event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = (self.prefix + option.currentText) if option.currentText or self.prefix else ""
        room = max(16, self.width() - 12 * 2 - 24)
        option.currentText = QFontMetrics(self.font()).elidedText(text, Qt.TextElideMode.ElideRight, room)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

    def populate(self, devices, current: Optional[str], default_description: Optional[str] = None) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItem(f"{default_description} (system default)" if default_description else "Default", "")
        self.setItemData(0, "Follow the system default device", Qt.ItemDataRole.ToolTipRole)
        self.addItem("None", NONE_DATA)
        names = set()
        # stereo devices first; multichannel interfaces after them, labelled, because only their first two channels are used
        for device in sorted(devices, key=lambda d: d.channels > 2):
            multi = device.channels > 2
            self.addItem(f"{device.description}  [{device.channels} channels]" if multi else device.description, device.name)
            tip = device.name
            if multi:
                tip += (f"\n{device.channels}-channel device: Sluice plays into its first two channels, which may not be "
                        "your headphones. If a stereo entry for the same hardware exists, use that.")
            self.setItemData(self.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
            names.add(device.name)
        wanted = NONE_DATA if current is None else current
        if wanted not in ("", NONE_DATA) and wanted not in names:
            self.addItem(f"{wanted} (missing)", wanted)
        self.setCurrentIndex(max(0, self.findData(wanted)))
        self.blockSignals(False)

    def selected_device(self) -> Optional[str]:
        data = self.currentData()
        return None if data == NONE_DATA else data


class MixHeading(QWidget):
    """A column heading of the Rows layout: an icon and "LISTEN · you hear", in the colour of that mix."""

    def __init__(self, mix_id: str, text: str) -> None:
        super().__init__()
        self.mix_id = mix_id
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 0, 0)
        row.setSpacing(8)
        self.picture = QLabel()
        self.picture.setFixedSize(18, 18)
        self.text = QLabel(text)
        self.text.setObjectName("mixheading")
        self.text.setProperty("mix", mix_id)
        row.addWidget(self.picture)
        row.addWidget(self.text, 1)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        color = themes.mix_colors(themes._current).get({MONITOR: "listen", STREAM: "broadcast"}.get(self.mix_id, ""), themes.color("text2"))
        ratio = self.devicePixelRatioF()
        pixmap = icons.render(MIX_ICONS.get(self.mix_id, "speaker"), color, round(18 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        self.picture.setPixmap(pixmap)


# ------------------------------------------------------------------------ mixes
MIX_EYEBROWS = {MONITOR: "FOR YOU", STREAM: "FOR YOUR AUDIENCE", RECORDING: "FOR RECORDING"}


class MixStrip(QFrame):
    """A mix's master card: its device, a fader with a meter, the level, Mute, Limiter and one action. Vertical in the Columns
    layout, with sliders along it in the Rows layout."""

    def __init__(self, mix: Mix, engine: Engine, on_remove=None, on_add_recording=None, rows: bool = False) -> None:
        super().__init__()
        self.setObjectName("mix")
        self.rows = rows
        self.original = _is_original(rows)
        self.ring = None
        self.key = None
        if not rows:
            self.setFixedWidth(ORIGINAL_MIX_WIDTH if self.original else MIX_WIDTH + (12 if _is_tile() else 0))  # Tile: + the key's sides
        self.mix, self.engine = mix, engine
        self.tile_key = False
        if self.original:
            self._build_original(mix, on_remove)
            return
        if _is_tile() and not rows:  # the Tile look: a short key with a sideways slider (0.11.5)
            from .ui_tile import build_mix_key
            build_mix_key(self, mix, on_remove, on_add_recording)
            self.sync_from_model()
            self.refresh_theme()
            return

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16 if not rows else 8)
        self.key = None
        if _is_tile():  # a raised key: room round the face for its skirt and shadow
            from .ui_tile_paint import SKIRT, KeyBackground
            self.key = KeyBackground((6, 2, 6, 10), radius=16)
            layout.setContentsMargins(6 + 16, 2 + 14, 6 + 16, 10 + SKIRT + 14)
        if _is_nexus(rows):  # a ring with the mix's letter in it, in the mix's colour
            mixc = themes.mix_colors(themes._current)
            color = mixc.get({MONITOR: "listen", STREAM: "broadcast"}.get(mix.id, ""), themes.color("accent"))
            if mix.id == RECORDING:
                color = themes.color("mute")
            self.ring = NexusRing(color, lambda ratio, mix=mix: self._ring_icon(ratio))
            layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
            from .ui_nexus import glass_edge_sheet
            self.setStyleSheet(glass_edge_sheet("mix", color))

        head = QHBoxLayout()
        head.setSpacing(8)
        names = QVBoxLayout()
        names.setSpacing(4)
        eyebrow = _label(MIX_EYEBROWS.get(mix.id, "MIX"), "tag", center=False)
        eyebrow.setProperty("mix", mix.id)
        eyebrow.setProperty("narrow", True)  # 11 px, no letter spacing: FOR YOUR AUDIENCE must fit the card even in a wider fallback font
        names.addWidget(eyebrow)
        self.setProperty("mix", mix.id)
        title = QLabel(mix.label)
        title.setObjectName("title")
        names.addWidget(title)
        head.addLayout(names, 1)
        self.readout = ReadoutEdit(None)
        self.readout.setProperty("big", True)
        self.readout.setAccessibleName(f"{mix.label} level in decibels")
        self.readout.setToolTip("Scroll over the number to change the level (hold Shift for fine steps), or click and type a level in dB (for example -6) and press Enter")
        self.readout.wheel_steps = True
        self.readout.wheeled.connect(self._wheel_gain)
        self.readout.entered.connect(self._typed_gain)
        if on_remove is not None:  # the optional third mix can be taken away again from its own card
            menu_button = _icon_button("more", "Options for this mix", 32, compact=True)
            menu_button.setObjectName("plain")
            menu = QMenu(menu_button)
            menu.addAction("Remove the Recording mix…", on_remove)
            menu_button.setMenu(menu)
            self.menu_button = menu_button
            head.addWidget(menu_button, 0, Qt.AlignmentFlag.AlignTop)
        else:
            self.menu_button = None
        if rows:
            self.readout.setFixedWidth(96)
            self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            head.addWidget(self.readout)
        layout.addLayout(head)

        self.combo: Optional[DeviceCombo] = None
        self.device_button: Optional[QPushButton] = None
        if mix.kind == MONITOR:
            self.combo = DeviceCombo("Output: ")
            self.combo.setToolTip("Where you hear the mix")
            self.combo.setAccessibleName("Listen output device")
            self.combo.activated.connect(self._on_device)
            layout.addWidget(self.combo)
        else:
            self.device_button = QPushButton(f"Sends to: {mix.source_description}")
            self.device_button.setObjectName("devicebutton")
            self.device_button.setFixedHeight(40)
            self.device_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.device_button.setToolTip(f"The device your streaming or recording app should pick: “{mix.source_description}”. "
                                          "Click to copy the name.")
            self.device_button.clicked.connect(self._copy_device_name)
            layout.addWidget(self.device_button)

        self.fader = Fader(horizontal=rows, thumb=(32, 24) if rows else (32, 16))
        self.fader.set_fill(themes.color("accent"))
        self.fader.setAccessibleName(f"{mix.label} level")
        self.fader.gainChanged.connect(self._on_gain)
        self.meter = LevelMeter(horizontal=rows, thickness=8 if rows else 16)
        self.meter.setAccessibleName(f"{mix.label} meter")
        if rows:
            layout.addStretch(1)
            if themes.current_look() == "nexus":  # 0.11.6: the ring at 48 px, in the room between the device and the slider
                mixc = themes.mix_colors(themes._current)
                color = mixc.get({MONITOR: "listen", STREAM: "broadcast"}.get(mix.id, ""), themes.color("accent"))
                self.ring = NexusRing(themes.color("mute") if mix.id == RECORDING else color, lambda ratio: self._ring_icon(ratio),
                                      NexusRing.SMALL)
                layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
                layout.addStretch(1)
            layout.addWidget(self.meter)
            layout.addWidget(self.fader)
        else:
            row = QHBoxLayout()
            row.setSpacing(40)
            row.addStretch(1)
            row.addWidget(self.fader)
            row.addWidget(self.meter)
            row.addStretch(1)
            layout.addLayout(row, 1)
            layout.addWidget(self.readout)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.mute = QPushButton()
        self.mute.setObjectName("mute")
        self.mute.setCheckable(True)
        self.mute.setFixedSize(64, 40)
        self.mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute.setAccessibleName(f"Mute {mix.label}")
        self.limiter = QPushButton("Limiter on")
        self.limiter.setObjectName("limiter")
        self.limiter.setCheckable(True)
        self.limiter.setFixedHeight(40)
        self.limiter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.limiter.setToolTip("Limiter: stops peaks from clipping")
        self.mute.toggled.connect(lambda on: self.engine.set_master_mute(self.mix.id, on))
        self.mute.toggled.connect(lambda _on: self._show_toggles())
        self.limiter.toggled.connect(lambda on: self.engine.set_limiter(self.mix.id, on))
        self.limiter.toggled.connect(lambda _on: self._show_toggles())
        buttons.addWidget(self.mute)
        buttons.addWidget(self.limiter, 1)
        layout.addLayout(buttons)

        # one action at the foot of the card: Listen checks the Broadcast, Broadcast offers the optional third mix
        self.hear: Optional[QPushButton] = None
        self.add_button: Optional[QPushButton] = None
        if mix.kind == MONITOR:
            self.hear = QPushButton("Hear Broadcast")
            self.hear.setObjectName("quiet")
            self.hear.setCheckable(True)
            self.hear.setFixedHeight(40)
            self.hear.setCursor(Qt.CursorShape.PointingHandCursor)
            self.hear.setToolTip("Check what your audience hears: your output plays the Broadcast mix instead of the Listen mix. "
                                 "Turn it off to go back. It always starts off.")
            self.hear.toggled.connect(self._on_hear)
            layout.addWidget(self.hear)
        elif mix.id == STREAM and on_add_recording is not None:
            self.add_button = QPushButton("Add a recording mix")
            self.add_button.setObjectName("quiet")
            self.add_button.setFixedHeight(40)
            self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.add_button.setToolTip("Add a third mix, “Recording”: a second virtual microphone with its own faders "
                                       "and mutes, so a recorder can get a different blend from the one your audience hears. "
                                       "Sluice restarts to add it.")
            self.add_button.clicked.connect(on_add_recording)
            layout.addWidget(self.add_button)
        else:
            spacer = QWidget()
            spacer.setFixedHeight(40)
            layout.addWidget(spacer)
        self.sync_from_model()
        self.refresh_theme()

    def _build_original(self, mix: Mix, on_remove) -> None:
        """The master card of 0.9.7: FOR YOU, the name, a hint, the device, the fader and meter, the level, M and LIM. The same parts
        as the Calm card, so everything still works (the optional Recording mix has its own strip beside the cards)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        eyebrow = ElidedLabel(MIX_EYEBROWS.get(mix.id, "MIX"), tip_when_cut=True)  # a wider fallback font ends in "..." instead of being cut
        eyebrow.setObjectName("tag")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eyebrow.setProperty("narrow", True)  # 11 px, no letter spacing
        layout.addWidget(eyebrow)
        title = _label(mix.label, "title")
        self.menu_button = None
        if on_remove is None:
            layout.addWidget(title)
        else:
            head = QHBoxLayout()
            head.setSpacing(0)
            head.addWidget(title, 1)
            self.menu_button = QToolButton()
            self.menu_button.setObjectName("menu")
            self.menu_button.setText("\u22ee")
            self.menu_button.setToolTip("Options for this mix")
            self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(self.menu_button)
            menu.addAction("Remove the Recording mix\u2026", on_remove)
            self.menu_button.setMenu(menu)
            head.addWidget(self.menu_button)
            layout.addLayout(head)
        self.combo = None
        self.device_button = None
        if mix.kind == MONITOR:
            layout.addWidget(_label("You hear this", "hint"))
            self.combo = DeviceCombo("")
            self.combo.setFixedHeight(34)
            self.combo.setToolTip("Where you hear the mix")
            self.combo.setAccessibleName("Listen output device")
            self.combo.activated.connect(self._on_device)
            layout.addWidget(_slot(self.combo, 34))
        else:
            layout.addWidget(_label("Audience hears this" if mix.id == STREAM else "Recorder hears this", "hint"))
            self.device_button = QPushButton(f"Record from\n\u201c{mix.source_description}\u201d")
            self.device_button.setObjectName("hintbutton")
            self.device_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.device_button.setToolTip(f"The device your streaming or recording app should pick: \u201c{mix.source_description}\u201d. "
                                          "Click to copy the name.")
            self.device_button.clicked.connect(self._copy_device_name)
            layout.addWidget(_slot(self.device_button, 30))
        self.fader, self.meter = Fader(), LevelMeter()
        self.fader.setAccessibleName(f"{mix.label} level")
        self.fader.gainChanged.connect(self._on_gain)
        self.meter.setAccessibleName(f"{mix.label} meter")
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addStretch(1)
        row.addWidget(self.fader)
        row.addWidget(self.meter)
        row.addStretch(1)
        layout.addLayout(row, 1)
        self.hear = None
        self.add_button = None
        if mix.kind == MONITOR:
            self.hear = _toggle("Hear Broadcast", "link",
                                "Check what your audience hears: your output plays the Broadcast mix instead of the Listen mix. "
                                "Turn it off to go back. It always starts off.")
            self.hear.toggled.connect(self._on_hear)
            layout.addWidget(self.hear)
        self.readout = ReadoutEdit(None)
        self.readout.setAccessibleName(f"{mix.label} level in decibels")
        self.readout.setToolTip("Scroll over the number to change the level (hold Shift for fine steps), or click and type a level in dB (for example -6) and press Enter")
        self.readout.wheel_steps = True
        self.readout.wheeled.connect(self._wheel_gain)
        self.readout.entered.connect(self._typed_gain)
        layout.addWidget(self.readout)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.mute = _toggle("M", "mute")
        self.limiter = _toggle("LIM", "limiter", "Limiter: stops peaks from clipping")
        self.mute.setAccessibleName(f"Mute {mix.label}")
        self.mute.toggled.connect(lambda on: self.engine.set_master_mute(self.mix.id, on))
        self.mute.toggled.connect(lambda _on: self._show_toggles())
        self.limiter.toggled.connect(lambda on: self.engine.set_limiter(self.mix.id, on))
        buttons.addWidget(self.mute)
        buttons.addWidget(self.limiter)
        layout.addLayout(buttons)
        self.sync_from_model()
        self.refresh_theme()

    def paintEvent(self, event) -> None:
        if self.key is not None:
            p = QPainter(self)
            self.key.draw(self, p)
            p.end()
            return
        super().paintEvent(event)

    def _ring_icon(self, ratio: float):
        """The Nexus ring's picture for a mix: its icon (headphones, broadcast waves) in the mix's colour."""
        pixmap = icons.render(MIX_ICONS.get(self.mix.id, "speaker"), self.ring.color if self.ring is not None else themes.color("accent"),
                              round(30 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        canvas = QPixmap(round(36 * ratio), round(36 * ratio))
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(Qt.GlobalColor.transparent)
        p = QPainter(canvas)
        p.drawPixmap(3, 3, pixmap)
        p.end()
        return canvas

    def refresh_theme(self) -> None:
        if self.ring is not None:  # Nexus: the mix's colour follows the theme (Listen cyan, Broadcast coral or the theme's own)
            mixc = themes.mix_colors(themes._current)
            color = mixc.get({MONITOR: "listen", STREAM: "broadcast"}.get(self.mix.id, ""), themes.color("mute"))
            if color != self.ring.color:
                self.ring.set_color(color)
                self.ring.refresh_source()
                from .ui_nexus import floor_of, glass_edge_sheet
                self.setStyleSheet(glass_edge_sheet("mix", color))
                floor = floor_of(self)
                if floor is not None:
                    floor.set_color(self, color)
        if self.tile_key:
            from .ui_tile import mix_key_color
            self.tint = mix_key_color(self.mix.id)
            self.fader.set_fill(self.tint)
            self.well.color = self.tint
            self.well.update()
            self.fold.setIcon(icons.icon("chevron_up" if self.fold.isChecked() else "chevron_down", themes.color("text2"), 16))
            self._show_toggles()
            return
        self.fader.set_fill(self.ring.color if self.ring is not None else themes.color("accent"))
        if self.menu_button is not None and not self.original:
            self.menu_button.setIcon(icons.icon("more", themes.color("text_dim"), 20))
        self._show_toggles()

    def _show_toggles(self) -> None:
        muted = self.mute.isChecked()
        if self.original:
            self.mute.setToolTip(f"Muted: nobody hears {MIX_MUTE_TIPS.get(self.mix.id, 'this mix')}. Click to unmute." if muted
                                 else "Mute this whole mix")
            return
        size = 16 if self.tile_key else 20
        self.mute.setIcon(icons.icon("speaker_off" if muted else "speaker", themes.color("mute_fg" if muted else "text2" if self.tile_key
                                                                                        else "text"), size))
        self.mute.setIconSize(QSize(size, size))
        what = MIX_MUTE_TIPS.get(self.mix.id, f"the {self.mix.label} mix")
        self.mute.setToolTip(f"Muted: nobody hears {what}. Click to unmute." if muted else f"Mute {what}")
        on = self.limiter.isChecked()
        if self.tile_key:
            self.fader.set_muted(muted)
            self.limiter.setToolTip("Limiter on: peaks cannot clip. Click to switch it off." if on else
                                    "Limiter off. Click to stop peaks from clipping.")
            return
        self.limiter.setText("Limiter on" if on else "Limiter off")

    def sync_from_model(self) -> None:
        for widget in (self.fader, self.mute, self.limiter):
            widget.blockSignals(True)
        self.fader.setGain(round(self.mix.gain_db * 10))
        self.mute.setChecked(self.mix.mute)
        self.limiter.setChecked(self.mix.limiter)
        if self.hear is not None:
            self.hear.blockSignals(True)
            self.hear.setChecked(self.engine.hear_broadcast)
            self.hear.blockSignals(False)
        for widget in (self.fader, self.mute, self.limiter):
            widget.blockSignals(False)
        self.readout.setText(format_db(self.mix.gain_db))
        self._show_toggles()
        node = getattr(self, "node", None)
        if node is not None:
            node.refresh()

    def populate_devices(self) -> None:
        if self.combo:
            default = self.engine.default_sink
            description = next((d.description for d in self.engine.sinks if d.name == default), None) if default else None
            self.combo.populate(self.engine.sinks, self.mix.device, description)
            if self.tile_key:  # the key's device line names where the mix plays
                self.device_line.setText(self.combo.currentText() or "Your headphones or speakers")

    def _copy_device_name(self) -> None:
        QGuiApplication.clipboard().setText(self.mix.source_description)
        window = self.window()
        if hasattr(window, "say"):
            window.say(f"Copied “{self.mix.source_description}”. Choose it as the microphone in your streaming or recording app.")

    def _on_hear(self, on: bool) -> None:
        self.engine.set_hear_broadcast(on)
        self.window().say("Your output now plays the Broadcast mix: this is what your audience hears." if on
                          else "Your output is back on the Listen mix.")

    def _typed_gain(self, number) -> None:
        if number is not None and number == number:
            self.engine.set_master(self.mix.id, max(MIN_DB, min(MAX_DB, number)))
        self.sync_from_model()

    def _wheel_gain(self, notches: float) -> None:
        self.fader.setGain(max(int(MIN_DB * 10), min(int(MAX_DB * 10), self.fader.gain() + int(round(notches * 10)))))

    def _on_gain(self, value: int) -> None:
        db = value / 10.0
        self.readout.setText(format_db(db))
        self.engine.set_master(self.mix.id, db)

    def _on_device(self, _index: int) -> None:
        self.engine.set_mix_device(self.mix.id, self.combo.selected_device())
