# SPDX-License-Identifier: GPL-3.0-or-later
"""Effects dialog: a channel's effect chain, built-in effects and VST3 plugins."""
from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .effects import BUILTINS, ParamInfo, builtin_names, scan_vst3, vst3_plugin_names, vst3_search_paths
from . import logs, presets, themes
from .model import MIN_DB, Effect, new_effect_id
from .ui_room import MeasureEchoDialog, MeasureRoomDialog, MeasureVoiceDialog
from .ui_live import LivePanel
from .ui_widgets import ReadoutEdit, ResetSlider

MAX_VST3_PARAMS = 64
SLIDER_STEPS = 1000


def format_value(value: float, unit: str, normalized: bool) -> str:
    if normalized:
        return f"{value * 100:.0f}%"
    if unit == ":1":
        return f"{value:.1f}:1"
    text = f"{value:.0f}" if abs(value) >= 100 else f"{value:.1f}"
    return f"{text} {unit}".strip()


class ParamRow(QWidget):
    """A label, a slider and a value readout for one parameter."""

    def __init__(self, info: ParamInfo, on_change) -> None:
        super().__init__()
        self.info = info
        self._on_change = on_change
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        name = QLabel(info.label)
        name.setFixedWidth(120)
        name.setToolTip(info.label)
        self.slider = ResetSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        span = (info.hi - info.lo) or 1.0
        self.slider.setValue(round((info.value - info.lo) / span * SLIDER_STEPS))
        self.value = info.value
        self.readout = ReadoutEdit(84)
        self.readout.setText(format_value(info.value, info.unit, info.normalized))
        row.addWidget(name)
        row.addWidget(self.slider, 1)
        row.addWidget(self.readout)
        self.slider.valueChanged.connect(self._changed)
        self.slider.reset_requested.connect(self._reset)  # double-click: back to the default
        self.readout.entered.connect(self._typed)
        tip = "Double-click to reset" + (f" to {format_value(info.default, info.unit, info.normalized)}" if info.default is not None else "")
        self.slider.setToolTip(tip if info.default is not None else "")

    def _position(self, value: float) -> int:
        span = (self.info.hi - self.info.lo) or 1.0
        return round((value - self.info.lo) / span * SLIDER_STEPS)

    def _set_value(self, value: float) -> None:
        """Apply an exact value: move the slider without re-deriving the value from its position."""
        info = self.info
        value = min(info.hi, max(info.lo, value))
        self.value = value
        self.slider.blockSignals(True)
        self.slider.setValue(self._position(value))
        self.slider.blockSignals(False)
        self.readout.setText(format_value(value, info.unit, info.normalized))
        self._on_change(info.key, value)

    def set_value(self, value: float) -> None:
        """Set an exact value from outside (for example the result of Measure my room)."""
        self._set_value(value)

    def _reset(self) -> None:
        if self.info.default is not None:
            self._set_value(self.info.default)

    def _typed(self, number) -> None:
        info = self.info
        if number is None or number != number or number in (float("inf"), float("-inf")):
            self.readout.setText(format_value(self.value, info.unit, info.normalized))  # not a number: snap back
            return
        self._set_value(number / 100.0 if info.normalized else number)  # plugin values are shown as percentages

    def _changed(self, position: int) -> None:
        info = self.info
        value = info.lo + (info.hi - info.lo) * position / SLIDER_STEPS
        self.value = value
        self.readout.setText(format_value(value, info.unit, info.normalized))
        self._on_change(info.key, value)


LEVEL_WATCH_SECONDS = 6.0  # how long the microphone is watched before it is called quiet
LOW_PEAK_DB = -26.0  # speech whose loudest moments stay below this is quiet (a normal voice peaks near -17 dB)


CARD_W, CARD_H, ARROW_W = 128, 120, 24
LIVE_W = 464
SUMMARY_ROLE = Qt.ItemDataRole.UserRole + 1
SUMMARIES = {
    "gain": "Louder or quieter",
    "highpass": "Cuts rumble",
    "noise_reducer": "Lowers fan hiss",
    "echo_reducer": "Lowers room echo",
    "noise_gate": "Mutes the room",
    "eq": "Shapes the tone",
    "compressor": "Evens out volume",
    "limiter": "Stops loud peaks",
}


class CardDelegate(QStyledItemDelegate):
    """Draws each effect as a card: its number, an on/off switch, its name and a few words on what it does."""

    SWITCH = (36, 20)

    def sizeHint(self, option, index) -> QSize:
        return QSize(CARD_W + ARROW_W, CARD_H + 8)

    def _switch_rect(self, card: QRectF) -> QRectF:
        w, h = self.SWITCH
        return QRectF(card.right() - 12 - w, card.top() + 12, w, h)

    def _card(self, option) -> QRectF:
        return QRectF(option.rect.left(), option.rect.top() + 4, CARD_W, CARD_H)

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = self._card(option)
        on = self._checked(index)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        fill = themes.color("accent_bg") if selected else (themes.color("hover") if hover else themes.color("panel"))
        border = QPen(QColor(themes.color("accent") if selected else themes.color("border2")), 2 if selected else 1)
        painter.setPen(border)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 12, 12)
        text = QColor(themes.color("text") if on else themes.color("text_dim"))
        small = QFont(painter.font())
        small.setPixelSize(12)
        painter.setFont(small)
        painter.setPen(QColor(themes.color("text_dim")))
        painter.drawText(QRectF(card.left() + 12, card.top() + 12, 24, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), str(index.row() + 1))
        sw = self._switch_rect(card)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(themes.color("accent") if on else themes.color("track")))
        painter.drawRoundedRect(sw, sw.height() / 2, sw.height() / 2)
        knob = sw.height() - 6
        x = sw.right() - 3 - knob if on else sw.left() + 3
        painter.setBrush(QColor(themes.color("bg") if on else themes.color("text_dim")))
        painter.drawEllipse(QRectF(x, sw.top() + 3, knob, knob))
        name = QFont(painter.font())
        name.setPixelSize(14)
        name.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name)
        painter.setPen(text)
        metrics = QFontMetrics(name)
        label = metrics.elidedText(str(index.data(Qt.ItemDataRole.DisplayRole)), Qt.TextElideMode.ElideRight, int(card.width() - 24))
        painter.drawText(QRectF(card.left() + 12, card.top() + 48, card.width() - 24, 22), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        painter.setFont(small)
        painter.setPen(QColor(themes.color("text_dim")))
        summary = str(index.data(SUMMARY_ROLE) or "")
        painter.drawText(QRectF(card.left() + 12, card.top() + 72, card.width() - 24, 36), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), summary if on else "Off")
        if index.row() < index.model().rowCount() - 1:
            mid = QRectF(card.right(), card.center().y() - 8, ARROW_W, 16)
            painter.setPen(QPen(QColor(themes.color("text_dim")), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            cx, cy = mid.center().x(), mid.center().y()
            painter.drawLine(int(cx - 5), int(cy), int(cx + 5), int(cy))
            painter.drawLine(int(cx + 1), int(cy - 4), int(cx + 5), int(cy))
            painter.drawLine(int(cx + 1), int(cy + 4), int(cx + 5), int(cy))
        if option.state & QStyle.StateFlag.State_HasFocus and selected:
            painter.setPen(QPen(QColor(themes.color("focus")), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card.adjusted(-1, -1, 1, 1), 13, 13)
        painter.restore()

    @staticmethod
    def _checked(index) -> bool:
        value = index.data(Qt.ItemDataRole.CheckStateRole)
        return value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)

    @classmethod
    def _toggle(cls, model, index) -> None:
        on = cls._checked(index)
        model.setData(index, Qt.CheckState.Unchecked if on else Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)

    def editorEvent(self, event, model, option, index) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._switch_rect(self._card(option)).adjusted(-6, -6, 6, 6).contains(event.position()):
                self._toggle(model, index)
                return True
        if kind == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select):
            self._toggle(model, index)
            return True
        return False

    def helpEvent(self, event, view, option, index) -> bool:
        if event.type() == QEvent.Type.ToolTip and self._switch_rect(self._card(option)).adjusted(-6, -6, 6, 6).contains(event.pos()):
            QToolTip.showText(event.globalPos(), "Switch this effect on or off", view)
            return True
        return super().helpEvent(event, view, option, index)


class EffectsDialog(QDialog):
    def __init__(self, engine, channel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.engine, self.channel = engine, channel
        self._compressor: Optional[Effect] = None  # set while the Compressor's page is shown (it gets a live hint)
        self._user_cache: Optional[dict] = None  # the saved presets, read once (the choices are refreshed on every slider move)
        self._speech_peak = None  # the loudest microphone peak seen while this window is open
        self._speech_started = None
        self._rows: dict = {}  # parameter key -> its ParamRow, for the effect being shown
        self.setWindowTitle(f"Effects — {channel.label}")
        self.resize(1280, 920)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(24)
        head = QVBoxLayout()
        head.setSpacing(4)
        heading = QLabel("Mic effects")
        heading.setObjectName("title")
        caption = QLabel("Sound passes through these from left to right.")
        caption.setObjectName("hint")
        head.addWidget(heading)
        head.addWidget(caption)
        root.addLayout(head)

        # Room and Voice style choices, and (right) My presets and Hear original mic
        self.sound_box = QWidget()
        sound = QHBoxLayout(self.sound_box)
        sound.setContentsMargins(0, 0, 0, 0)
        sound.setSpacing(24)
        axes = QVBoxLayout()
        axes.setSpacing(16)
        self._choice_buttons: dict = {}  # (axis, name) -> its button
        self._axis_status: dict = {}
        self._axis_reset: dict = {}
        for axis, title in (("room", "Room"), ("style", "Voice style")):
            top = QHBoxLayout()
            top.setSpacing(8)
            label = QLabel(title)
            label.setObjectName("tag")
            top.addWidget(label)
            status = QLabel("")
            status.setObjectName("hint")
            top.addWidget(status, 1)
            reset = QPushButton("Reset")
            reset.setFlat(True)
            reset.setToolTip("Put every setting of this choice back to exactly what the name says.")
            reset.clicked.connect(partial(self._reset_axis, axis))
            reset.hide()
            top.addWidget(reset)
            axes.addLayout(top)
            frame = QFrame()
            frame.setObjectName("segmented")
            segments = QHBoxLayout(frame)
            segments.setContentsMargins(4, 4, 4, 4)
            segments.setSpacing(4)
            for name, (description, _entries) in presets.AXES[axis].items():
                button = QPushButton(name)
                button.setObjectName("segment")
                button.setCheckable(True)
                button.setToolTip(description)
                button.clicked.connect(partial(self._choose, axis, name))
                segments.addWidget(button)
                self._choice_buttons[(axis, name)] = button
            axes.addWidget(frame)
            self._axis_status[axis], self._axis_reset[axis] = status, reset
        self.preset_feedback = QLabel("")
        self.preset_feedback.setObjectName("feedback")
        self.preset_feedback.setWordWrap(True)
        self.preset_feedback.hide()
        axes.addWidget(self.preset_feedback)
        self.level_prompt = QLabel("Your microphone sounds quiet. Quiet speech gives the Compressor nothing to do.")
        self.level_prompt.setWordWrap(True)
        self.level_prompt.setStyleSheet(f"color: {themes.color('warn')};")
        self.level_button = QPushButton("Check my voice level…")
        self.level_button.clicked.connect(self._measure_voice)
        self.level_prompt.hide()
        self.level_button.hide()
        axes.addWidget(self.level_prompt)
        axes.addWidget(self.level_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.room_hint = QLabel("Tip: open the Noise Gate and press Measure my room. Sluice listens and picks the Room "
                                "choice that fits.")
        self.room_hint.setWordWrap(True)
        self.room_hint.setObjectName("hint")
        self.room_hint.hide()
        axes.addWidget(self.room_hint)
        sound.addLayout(axes, 1)

        side = QVBoxLayout()
        side.setSpacing(8)
        side_box = QWidget()
        side_box.setFixedWidth(264)
        side_box.setLayout(side)
        side.setContentsMargins(0, 0, 0, 0)
        self.mine_button = QPushButton("My presets ▾")
        self.mine_button.setMenu(QMenu(self.mine_button))
        self.mine_button.menu().aboutToShow.connect(self._build_mine_menu)
        self.mine_button.setToolTip("Your own saved settings (they also keep the gate threshold and gain). "
                                    "Save as my preset works from any state, even after a tiny change.")
        side.addWidget(self.mine_button)
        # After a change to a preset of yours: keep it, save it as a new one, or go back
        self._active_user: Optional[str] = None
        self.mine_changed_row = QWidget()
        changed_layout = QVBoxLayout(self.mine_changed_row)
        changed_layout.setContentsMargins(0, 0, 0, 0)
        changed_layout.setSpacing(4)
        self.mine_changed_label = QLabel("")
        self.mine_changed_label.setWordWrap(True)
        self.mine_changed_label.setObjectName("hint")
        changed_layout.addWidget(self.mine_changed_label)
        changed_buttons = QHBoxLayout()
        changed_buttons.setSpacing(4)
        self.mine_update_button = QPushButton("Update preset…")
        self.mine_update_button.setToolTip("Replace your saved preset with the settings as they are now (it asks first).")
        self.mine_update_button.clicked.connect(self._update_my_preset)
        self.mine_new_button = QPushButton("Save as new…")
        self.mine_new_button.setToolTip("Keep your preset as it was and save these settings under a new name.")
        self.mine_new_button.clicked.connect(self._save_preset)
        self.mine_undo_button = QPushButton("Undo")
        self.mine_undo_button.setToolTip("Put every setting back to what your preset says.")
        self.mine_undo_button.clicked.connect(self._undo_to_my_preset)
        for button in (self.mine_update_button, self.mine_new_button, self.mine_undo_button):
            changed_layout.addWidget(button)
        self.mine_changed_row.hide()
        side.addWidget(self.mine_changed_row)
        self.compare_button = QPushButton("Hear my original microphone")
        self.compare_button.setCheckable(True)
        self.compare_button.setToolTip("Switches the whole effect chain off so you can compare with and without. "
                                       "Not saved: it ends when you untick it or close Sluice.")
        self.compare_button.toggled.connect(self._compare_chain)
        side.addWidget(self.compare_button)
        side.addStretch(1)
        sound.addWidget(side_box)
        root.addWidget(self.sound_box)

        # The chain: cards from left to right
        chain = QVBoxLayout()
        chain.setSpacing(8)
        self.list = QListWidget()
        self.list.setObjectName("chain")
        self.list.setFlow(QListWidget.Flow.LeftToRight)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(0)
        self.list.setGridSize(QSize(CARD_W + ARROW_W, CARD_H + 8))
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setItemDelegate(CardDelegate(self.list))
        self.list.setFixedHeight(CARD_H + 24)
        self.list.setAccessibleName("Effect chain")
        chain.addWidget(self.list)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.add_button = QPushButton("Add ▾")
        self.add_button.setMenu(QMenu(self.add_button))
        self.add_button.menu().aboutToShow.connect(self._build_add_menu)
        up, down, remove = QPushButton("◀"), QPushButton("▶"), QPushButton("Remove")
        up.setToolTip("Move earlier (VST3 plugins only)")
        down.setToolTip("Move later (VST3 plugins only)")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        remove.clicked.connect(self._remove)
        for button in (self.add_button, up, down, remove):
            buttons.addWidget(button)
        buttons.addStretch(1)
        chain.addLayout(buttons)
        self.up, self.down = up, down
        root.addLayout(chain)

        # The detail of the selected effect (left) and the live display (right)
        lower = QHBoxLayout()
        lower.setSpacing(24)
        detail = QFrame()
        detail.setObjectName("detail")
        right = QVBoxLayout(detail)
        right.setContentsMargins(24, 24, 24, 24)
        right.setSpacing(8)
        self.title = QLabel("")
        self.title.setObjectName("title")
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {themes.color('error')};")
        self.error.hide()
        self.editor_button = QPushButton("Open plugin window")
        self.editor_button.clicked.connect(self._open_editor)
        self.editor_button.hide()
        self.params_area = QScrollArea()
        self.params_area.setWidgetResizable(True)
        self.params_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.params_area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        right.addWidget(self.title)
        right.addWidget(self.error)
        right.addWidget(self.editor_button, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.params_area, 1)
        foot = QLabel("Untick an effect to bypass it. Built-in effects start in the best order; VST3 plugins can be moved.")
        foot.setObjectName("hint")
        foot.setWordWrap(True)
        right.addWidget(foot)
        lower.addWidget(detail, 1)
        self.live = LivePanel(self.engine, self.channel)
        self.live.setFixedWidth(LIVE_W)
        lower.addWidget(self.live)
        root.addLayout(lower, 1)

        self.activity_label: Optional[QLabel] = None
        self._activity_stage = None
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._update_activity)
        self.finished.connect(self._timer.stop)
        self.list.currentRowChanged.connect(self._show_params)
        self.list.itemChanged.connect(self._on_item_changed)
        self._reload(select=0)
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(500)
        self._level_timer.timeout.connect(self._check_level)
        self._level_timer.start()
        self.finished.connect(self._level_timer.stop)
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(33)
        self._live_timer.timeout.connect(self.live.tick)
        self._live_timer.start()
        self.finished.connect(self._live_timer.stop)
        self._show_room_hint()
        for button in self.findChildren(QPushButton):  # Enter must only finish a typed value, never press a button
            button.setAutoDefault(False)
            button.setDefault(False)

    def _fit_list(self) -> None:
        """As tall as the rows of cards need: one row, or more when a long chain wraps."""
        per_row = max(1, self.list.viewport().width() // (CARD_W + ARROW_W))
        rows = max(1, -(-self.list.count() // per_row))
        self.list.setFixedHeight(rows * (CARD_H + 8) + 16)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_list()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()  # a QDialog would otherwise "click" its first button: here that opened the Add menu
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------- list
    def _reload(self, select: Optional[int] = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for effect in self.channel.effects:
            instance = self.engine.effect_instance(effect.id)
            failed = instance is not None and bool(instance.error)
            item = QListWidgetItem(("⚠ " if failed else "") + effect.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if effect.bypass else Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, effect.id)
            item.setData(SUMMARY_ROLE, SUMMARIES.get(effect.type, "") if effect.kind == "builtin" else "VST3 plugin")
            item.setSizeHint(QSize(CARD_W + ARROW_W, CARD_H + 8))
            if effect.kind == "vst3":
                item.setToolTip(f"VST3: {effect.path}")
            if effect.bypass:
                item.setForeground(QColor(themes.color("muted")))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._fit_list()
        if self.channel.effects:
            row = 0 if select is None else max(0, min(select, len(self.channel.effects) - 1))
            self.list.setCurrentRow(row)
        self._show_params(self.list.currentRow())
        self._update_presets_button()

    def _presets_file(self):
        return presets.path_beside(getattr(self.parent(), "config_file", None))

    def _user_presets(self, reload: bool = False) -> dict:
        if self._user_cache is None or reload:
            self._user_cache = presets.load_user(self._presets_file())
        return self._user_cache

    def _param_changed(self, effect_id: str, key: str, value: float) -> None:
        self.engine.set_effect_param(effect_id, key, value)
        self.live.parameters_changed()
        self._update_presets_button()  # a moved slider may mean the settings no longer match the preset

    def _update_presets_button(self) -> None:
        """Tick the Room and Voice style choices that match, and say "(changed)" with a Reset once a value was nudged."""
        effects = self.channel.effects
        user = self._user_presets()
        user_match = presets.user_name(effects, user)
        if self._active_user in user and presets.matches(effects, user[self._active_user], personal=True):
            user_match = self._active_user  # two presets that are identical: keep showing the one being edited
        if user_match is not None:
            self._active_user = user_match  # the preset these settings are, so a later change can be kept or undone
        elif self._active_user not in user:
            self._active_user = None  # it was deleted
        edited = self._active_user is not None and user_match != self._active_user
        self.mine_changed_row.setVisible(edited)
        if edited:
            self.mine_changed_label.setText(f"Changed from your preset \u201c{self._active_user}\u201d.")
        for axis in presets.AXES:
            name, changed = presets.axis_state(effects, axis)
            for (a, n), button in self._choice_buttons.items():
                if a != axis:
                    continue
                on = n == name
                button.setChecked(on)
                button.setText(("\u2713 " if on and not changed else "") + n)
            status = self._axis_status[axis]
            if name is None:
                status.setText("not on this channel yet")
            elif changed:
                status.setText(f"{name} (changed)")
            else:
                status.setText("")
            self._axis_reset[axis].setVisible(name is not None and changed)
        self.mine_button.setText(f"\u2713 {user_match} \u25be" if user_match else "My presets \u25be")
        self.compare_button.setChecked(self.engine.chain_compare(self.channel.id))

    def _choose(self, axis: str, name: str) -> None:
        entries = presets.AXES[axis][name][1]
        presets.apply(self.engine, self.channel.id, entries)
        target = next((i for i, e in enumerate(self.channel.effects) if e.kind == "builtin"
                       and any(x["type"] == e.type for x in entries)), None)
        self._reload(select=target if target is not None else max(0, self.list.currentRow()))
        self._tell(f"{'Room' if axis == 'room' else 'Voice style'}: {name}. {presets.summary(entries)}.")

    def _reset_axis(self, axis: str) -> None:
        presets.reset_axis(self.engine, self.channel.id, axis)
        self._reload(select=max(0, self.list.currentRow()))
        name, _changed = presets.axis_state(self.channel.effects, axis)
        self._tell(f"{name} is back to its own settings.")

    def _tell(self, message: str) -> None:
        self.preset_feedback.setText(message)
        self.preset_feedback.show()
        say = getattr(self.parent(), "say", None)
        if say is not None:
            say(message)

    def _compare_chain(self, original: bool) -> None:
        self.engine.set_chain_compare(self.channel.id, original)
        self.compare_button.setText("Back to my effects" if original else "Hear my original microphone")

    def done(self, result) -> None:  # the before/after switch and the live look never outlive the window
        self._stop_tap()
        if self.engine.chain_compare(self.channel.id):
            self.engine.set_chain_compare(self.channel.id, False)
        super().done(result)

    def _build_mine_menu(self) -> None:
        menu = self.mine_button.menu()
        menu.clear()
        user = self._user_presets(reload=True)
        current = presets.user_name(self.channel.effects, user)
        for name, entries in user.items():
            action = menu.addAction(name, partial(self._apply_mine, entries, name))
            action.setCheckable(True)
            action.setChecked(name == current)
        if user:
            menu.addSeparator()
        save = menu.addAction("Save as my preset\u2026", self._save_preset)
        save.setEnabled(self._presets_file() is not None)
        if user:
            remove = menu.addMenu("Delete a preset of mine")
            for name in user:
                remove.addAction(name, partial(self._delete_preset, name))

    def _apply_mine(self, entries: list, name: str) -> None:
        self._active_user = name
        presets.apply(self.engine, self.channel.id, entries, personal=True)
        self._reload(select=max(0, self.list.currentRow()))
        self._tell(f"Applied your preset \u201c{name}\u201d.")

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save as my preset", "Name for this preset:")
        name = name.strip()
        if not ok or not name:
            return
        path = self._presets_file()
        stored = presets.load_user(path)
        stored[name] = presets.snapshot(self.channel.effects)
        if not presets.save_user(path, stored):
            QMessageBox.warning(self, "Save preset", "The preset could not be saved (is the settings folder writable?).")
        self._user_presets(reload=True)
        self._active_user = name
        self._update_presets_button()
        self._tell(f"Saved \u201c{name}\u201d, with the gate threshold and gain too.")

    def _update_my_preset(self) -> None:
        """Replace the preset being edited with the settings as they are now, after asking."""
        name = self._active_user
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Update preset",
            f"Replace your preset \u201c{name}\u201d with the settings on this channel as they are now?\n\n"
            "The old version of the preset will be gone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        path = self._presets_file()
        stored = presets.load_user(path)
        stored[name] = presets.snapshot(self.channel.effects)
        if not presets.save_user(path, stored):
            QMessageBox.warning(self, "Update preset", "The preset could not be saved (is the settings folder writable?).")
            return
        self._user_presets(reload=True)
        self._update_presets_button()
        self._tell(f"Updated your preset \u201c{name}\u201d.")

    def _undo_to_my_preset(self) -> None:
        name = self._active_user
        entries = self._user_presets().get(name) if name else None
        if entries is None:
            return
        presets.apply(self.engine, self.channel.id, entries, personal=True)
        self._reload(select=max(0, self.list.currentRow()))
        self._tell(f"Back to your preset \u201c{name}\u201d.")

    def _delete_preset(self, name: str) -> None:
        path = self._presets_file()
        stored = presets.load_user(path)
        stored.pop(name, None)
        presets.save_user(path, stored)
        self._user_presets(reload=True)
        self._update_presets_button()

    # ---------------------------------------------------------- level and one-time tips
    def _check_level(self) -> None:
        """Offer the voice level check when the microphone itself is quiet (judged from what it sent while this window was open)."""
        if not self.channel.devices:
            return
        peak = self.engine.channel_input_peak_db(self.channel.id)
        if peak is None or peak <= -50.0:
            return
        now = time.monotonic()
        if self._speech_started is None:
            self._speech_started = now
        self._speech_peak = peak if self._speech_peak is None else max(self._speech_peak, peak)
        if now - self._speech_started >= LEVEL_WATCH_SECONDS:
            low = self._speech_peak < LOW_PEAK_DB
            self.level_prompt.setVisible(low)
            self.level_button.setVisible(low)

    def _show_room_hint(self) -> None:
        mixer = self.engine.mixer
        if "measure_room" in mixer.hints_seen or not self.channel.devices:
            return
        if any(e.type == "noise_gate" for e in self.channel.effects):
            self.room_hint.show()
            mixer.hints_seen.append("measure_room")  # shown once

    def _current_effect(self) -> Optional[Effect]:
        row = self.list.currentRow()
        return self.channel.effects[row] if 0 <= row < len(self.channel.effects) else None

    def _start_tap(self, effect: Optional[Effect]) -> None:
        """Look at the sound around the selected effect (only while this window is open), and show it."""
        setter = getattr(self.engine, "set_effect_tap", None)
        if setter is not None:
            try:
                setter(self.channel.id, effect.id if effect is not None else None)
            except Exception as error:  # the live display is an extra: never let it break the window
                import logging; logging.getLogger("sluice").warning("live display unavailable: %s", error)
        self.live.show_effect(effect)

    def _stop_tap(self) -> None:
        setter = getattr(self.engine, "set_effect_tap", None)
        if setter is not None:
            try:
                setter(self.channel.id, None)
            except Exception:
                pass

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        effect_id = item.data(Qt.ItemDataRole.UserRole)
        bypass = item.checkState() != Qt.CheckState.Checked
        self.engine.set_effect_bypass(self.channel.id, effect_id, bypass)
        self._update_presets_button()
        item.setForeground(QColor(themes.color("muted") if bypass else themes.color("text")))

    def _move(self, delta: int) -> None:
        effect = self._current_effect()
        if effect is None:
            return
        self.engine.move_effect(self.channel.id, effect.id, delta)
        self._reload(select=self.channel.effects.index(effect))

    def _remove(self) -> None:
        effect = self._current_effect()
        if effect is None:
            return
        row = self.list.currentRow()
        self.engine.remove_effect(self.channel.id, effect.id)
        self._reload(select=row)

    # ------------------------------------------------------------- parameters
    def _show_params(self, _row: int) -> None:
        self._start_tap(self._current_effect())
        self._build_params()

    def _build_params(self) -> None:
        effect = self._current_effect()
        movable = effect is not None and effect.kind == "vst3"
        self.up.setEnabled(movable)
        self.down.setEnabled(movable)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        instance = self.engine.effect_instance(effect.id) if effect else None

        self.error.hide()
        self.editor_button.hide()
        self.activity_label, self._activity_stage, self._compressor = None, None, None  # the old page's label is about to go
        self._timer.stop()
        if effect is None or instance is None:
            self.title.setText("No effects yet" if effect is None else effect.name)
            if effect is None:
                note = QLabel("Use Add to put a compressor, noise gate, EQ or a VST3 plugin on this channel.")
                note.setWordWrap(True)
                note.setObjectName("hint")
                layout.addWidget(note)
            self.params_area.setWidget(panel)
            return

        self.title.setText(effect.name)
        if instance.error:
            self.error.setText(instance.error)
            self.error.show()
        if instance.has_editor and instance.usable:
            self.editor_button.show()
        infos = instance.param_infos()
        self._rows = {}
        for info in infos[:MAX_VST3_PARAMS]:
            row = ParamRow(info, partial(self._param_changed, effect.id))
            self._rows[info.key] = row
            layout.addWidget(row)
        definition = BUILTINS.get(effect.type) if effect.kind == "builtin" else None
        self.activity_label, self._activity_stage, self._compressor = None, None, None
        self._timer.stop()
        if definition is not None and definition.hint:
            layout.addSpacing(8)
            if not self.channel.devices:
                warn = QLabel("This channel has no microphone. This effect is made for a voice and will make music or "
                              "game sound worse: remove it here.")
                warn.setWordWrap(True)
                warn.setStyleSheet(f"color: {themes.color('warn')};")
                layout.addWidget(warn)
            note = QLabel(definition.hint)
            note.setWordWrap(True)
            note.setObjectName("hint")
            layout.addWidget(note)
        if instance.stage is not None and instance.usable:
            self.activity_label = QLabel("")
            self.activity_label.setObjectName("hint")
            layout.addWidget(self.activity_label)
            self._activity_stage = instance.stage
            self._timer.start()
            self._update_activity()
            if effect.type == "echo_reducer":
                measure_echo = QPushButton("Measure my room's echo…")
                measure_echo.setAutoDefault(False)
                measure_echo.setToolTip("Clap once; Sluice works out how long your room's echo lasts and sets Room echo time.")
                measure_echo.clicked.connect(partial(self._measure_echo, effect))
                layout.addWidget(measure_echo, 0, Qt.AlignmentFlag.AlignLeft)
            compare = QPushButton("Compare: switch both reducers off / on")
            compare.setAutoDefault(False)
            compare.setToolTip("Flips the Echo Reducer and Noise Reducer together, so you can hear the difference while you talk.")
            compare.clicked.connect(self._compare_reducers)
            layout.addWidget(compare, 0, Qt.AlignmentFlag.AlignLeft)
        if effect.kind == "builtin" and effect.type == "compressor" and instance.usable:
            self.activity_label = QLabel("")
            self.activity_label.setObjectName("hint")
            self.activity_label.setWordWrap(True)
            layout.addWidget(self.activity_label)
            self._compressor = effect
            self._timer.start()
            self._update_activity()
            if self.channel.devices:
                layout.addWidget(self._voice_button(), 0, Qt.AlignmentFlag.AlignLeft)
        if effect.kind == "builtin" and effect.type == "noise_gate" and instance.usable:
            note = QLabel("Not sure what threshold suits your room? Sluice can listen to your microphone for a few "
                          "quiet seconds and set it for you.")
            note.setWordWrap(True)
            note.setObjectName("hint")
            measure = QPushButton("Measure my room…")
            measure.setAutoDefault(False)
            measure.setToolTip("Stay quiet for 5 seconds with your usual background noise on; the threshold is set just above it.")
            measure.clicked.connect(partial(self._measure_room, effect))
            layout.addSpacing(12)
            layout.addWidget(note)
            layout.addWidget(measure, 0, Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(self._voice_button(), 0, Qt.AlignmentFlag.AlignLeft)
        if len(infos) > MAX_VST3_PARAMS:
            more = QLabel(f"{len(infos) - MAX_VST3_PARAMS} more parameters: use “Open plugin window”.")
            more.setObjectName("hint")
            layout.addWidget(more)
        self.params_area.setWidget(panel)

    def _voice_button(self) -> QPushButton:
        button = QPushButton("Check my voice level…")
        button.setAutoDefault(False)
        button.setToolTip("Talk for a few seconds; Sluice says how much to raise or lower your microphone's level.")
        button.clicked.connect(self._measure_voice)
        return button

    def _measure_voice(self) -> None:
        MeasureVoiceDialog(self.engine, self.channel, self._apply_voice_gain, self).exec()

    def _apply_voice_gain(self, change_db: float) -> None:
        """Move the channel's Gain effect (added if there is none) by the amount the voice check asked for."""
        gain = next((e for e in self.channel.effects if e.kind == "builtin" and e.type == "gain"), None)
        if gain is None:
            gain = Effect(new_effect_id(), "builtin", "Gain", type="gain")
            self.engine.add_effect(self.channel.id, gain)
        new = max(-24.0, min(24.0, presets.current_value(gain, "gain_db") + change_db))
        self.engine.set_effect_param(gain.id, "gain_db", new)
        self._reload(select=self.channel.effects.index(gain))
        say = getattr(self.parent(), "say", None)
        if say is not None:
            say(f"Gain on {self.channel.label} is now {new:+.1f} dB.")

    def _update_compressor_hint(self) -> None:
        effect = self._compressor
        peak = self.engine.channel_recent_peak_db(self.channel.id)
        if peak is None or peak <= MIN_DB + 1:
            self.activity_label.setText("Waiting for sound on this channel.")
            return
        top = presets.current_value(effect, "threshold_db") + presets.current_value(effect, "makeup_db")
        if peak < top - 0.5:  # the loudest recent sound is below where the compressor starts (plus its makeup gain)
            self.activity_label.setText(
                "Not doing anything right now: the sound stays below the Threshold. Lower the Threshold, or raise the "
                "microphone's level, so it evens out your voice.")
        else:
            self.activity_label.setText("Working: turning down your loudest moments.")

    def _update_activity(self) -> None:
        if self._compressor is not None and self.activity_label is not None:
            self._update_compressor_hint()
            return
        if self.activity_label is None or self._activity_stage is None:
            return
        db = self._activity_stage.activity_db
        self.activity_label.setText("Turning your voice's frequencies down by about %.0f dB right now." % -db if db < -0.5
                                    else "Not doing anything right now (nothing to reduce, or no sound).")

    def _compare_reducers(self) -> None:
        reducers = [e for e in self.channel.effects if e.kind == "builtin" and e.type in ("echo_reducer", "noise_reducer")]
        turn_off = any(not e.bypass for e in reducers)
        for effect in reducers:
            self.engine.set_effect_bypass(self.channel.id, effect.id, turn_off)
        self._reload(select=self.list.currentRow())

    def _measure_echo(self, effect: Effect) -> None:
        row = self._rows.get("reverb_time")
        if row is None:
            return
        MeasureEchoDialog(self.engine, self.channel, row.value, row.set_value, self).exec()

    def _measure_room(self, effect: Effect) -> None:
        row = self._rows.get("threshold_db")
        if row is None:
            return
        dialog = MeasureRoomDialog(self.engine, self.channel, effect.id, row.value, row.set_value, self)
        dialog.on_applied = self._room_measured
        dialog.exec()

    def _room_measured(self, result) -> None:
        """After Measure my room: pick the Room choice that matches how loud the room turned out to be."""
        if "measure_room" not in self.engine.mixer.hints_seen:
            self.engine.mixer.hints_seen.append("measure_room")
        self.room_hint.hide()
        name = presets.room_for_noise(result.noise_db)
        presets.apply(self.engine, self.channel.id, presets.ROOMS[name][1])
        self._reload(select=max(0, self.list.currentRow()))
        if getattr(result, "quiet_fallback", False):
            self._tell(f"Room: {name}. Sluice heard no sound at all, so it used the quietest setting. If your microphone is "
                       "working, that just means the room is very quiet.")
            return
        self._tell(f"Room: {name}, chosen to match what Sluice heard (about {result.noise_db:.0f} dB of background noise).")

    def _open_editor(self) -> None:
        effect = self._current_effect()
        instance = self.engine.effect_instance(effect.id) if effect else None
        if instance is not None:
            instance.open_editor()

    # ----------------------------------------------------------------- adding
    def _build_add_menu(self) -> None:
        menu = self.add_button.menu()
        menu.clear()
        builtin = menu.addMenu("Built-in")
        for key, name in builtin_names():
            builtin.addAction(name, partial(self._add_builtin, key, name))
        vst = menu.addMenu("VST3 plugin")
        found = scan_vst3(vst3_search_paths(self.engine.mixer.vst3_folders))
        for name, path in found:
            vst.addAction(name, partial(self._add_vst3, path))
        if not found:
            vst.addAction("No plugins found in the usual folders").setEnabled(False)
        vst.addSeparator()
        vst.addAction("Browse for a .vst3 folder…", self._browse_vst3)
        vst.addAction("Add a folder of plugins…", self._add_vst3_folder)
        vst.addAction("Where does Sluice look?", self._show_vst3_folders)

    def _add_vst3_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a folder that contains .vst3 plugins", str(Path.home()))
        if path and path not in self.engine.mixer.vst3_folders:
            self.engine.mixer.vst3_folders.append(path)
            found = scan_vst3(vst3_search_paths(self.engine.mixer.vst3_folders))
            QMessageBox.information(self, "Plugin folder added",
                                    f"{logs.short_path(path)} was added. Sluice now finds {len(found)} VST3 plugin(s) in all its folders.\n"
                                    "Open Add > VST3 plugin to see them.")

    def _show_vst3_folders(self) -> None:
        lines = []
        for folder in vst3_search_paths(self.engine.mixer.vst3_folders):
            count = len(scan_vst3([folder])) if folder.is_dir() else None
            lines.append(f"{logs.short_path(folder)}   ({'does not exist' if count is None else f'{count} plugin(s)'})")
        QMessageBox.information(
            self, "Where Sluice looks for VST3 plugins",
            "\n".join(lines) + "\n\nThese are the folders Linux VST3 hosts normally use, so a plugin that REAPER or another "
            "Linux host can see in them is found here too. Add other folders with \u201cAdd a folder of plugins\u201d, or "
            "with the VST3_PATH environment variable.\n\n"
            "Only Linux VST3 plugins can be loaded. Windows plugins do not work directly (a tool such as yabridge "
            "can make Linux copies of them, usually in ~/.vst3/yabridge), and VST2, JSFX and plugins that exist only "
            "inside another program cannot be loaded.")

    def _add_builtin(self, key: str, name: str) -> None:
        effect = Effect(new_effect_id(), "builtin", name, type=key)
        self.engine.add_effect(self.channel.id, effect)
        self._reload(select=self.channel.effects.index(effect))  # built-in effects land in their fixed place

    def _browse_vst3(self) -> None:
        start = Path.home() / ".vst3"
        path = QFileDialog.getExistingDirectory(
            self, "Choose a VST3 plugin (a folder ending in .vst3)", str(start if start.is_dir() else Path.home())
        )
        if path:
            self._add_vst3(path)

    def _add_vst3(self, path: str) -> None:
        if not path.lower().rstrip("/").endswith(".vst3"):
            QMessageBox.warning(self, "Not a VST3 plugin", "Please choose a folder or file whose name ends in .vst3.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            names = vst3_plugin_names(path)
        finally:
            QApplication.restoreOverrideCursor()
        plugin_name = ""
        if len(names) > 1:
            plugin_name, ok = QInputDialog.getItem(self, "Choose a plugin", "This file contains several plugins:", names, 0, False)
            if not ok:
                return
        display = plugin_name or (names[0] if names else Path(path).stem)
        effect = Effect(new_effect_id(), "vst3", display, path=path, plugin_name=plugin_name)

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            instance = self.engine.add_effect(self.channel.id, effect)
        finally:
            QApplication.restoreOverrideCursor()
        if instance.error:
            self.engine.remove_effect(self.channel.id, effect.id)
            QMessageBox.warning(self, "Could not load plugin", instance.error)
            self._reload()
            return
        self._reload(select=len(self.channel.effects) - 1)
