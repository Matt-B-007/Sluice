# SPDX-License-Identifier: GPL-3.0-or-later
"""Effects dialog: a channel's effect chain, built-in effects and VST3 plugins."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
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
    QVBoxLayout,
    QWidget,
)

from .effects import BUILTINS, ParamInfo, builtin_names, scan_vst3, vst3_plugin_names, vst3_search_paths
from . import logs, presets, themes
from .model import MIN_DB, VOICE_CHAIN, Effect, new_effect_id
from .ui_room import MeasureEchoDialog, MeasureRoomDialog, MeasureVoiceDialog
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


class EffectsDialog(QDialog):
    def __init__(self, engine, channel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.engine, self.channel = engine, channel
        self._compressor: Optional[Effect] = None  # set while the Compressor's page is shown (it gets a live hint)
        self._user_cache: Optional[dict] = None  # the saved presets, read once (the button is refreshed on every slider move)
        self._rows: dict = {}  # parameter key -> its ParamRow, for the effect being shown
        self.setWindowTitle(f"Effects — {channel.label}")
        self.resize(720, 460)

        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        hint = QLabel("Processed top to bottom. Untick to bypass.\nBuilt-in effects are placed in the best order for you; only VST3 plugins can be moved.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        left.addWidget(hint)
        self.list = QListWidget()
        self.list.setMinimumWidth(220)
        left.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add ▾")
        self.add_button.setMenu(QMenu(self.add_button))
        self.add_button.menu().aboutToShow.connect(self._build_add_menu)
        up, down, remove = QPushButton("▲"), QPushButton("▼"), QPushButton("Remove")
        up.setToolTip("Move up")
        down.setToolTip("Move down")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        remove.clicked.connect(self._remove)
        for button in (self.add_button, up, down, remove):
            buttons.addWidget(button)
        left.addLayout(buttons)
        self.up, self.down = up, down
        preset = QPushButton("Use the recommended voice chain")
        preset.setToolTip("High-pass, noise gate, EQ, compressor and limiter, in that order, with starting values that suit a speaking voice.")
        preset.clicked.connect(self._apply_voice_chain)
        left.addWidget(preset)
        self.presets_button = QPushButton("Presets ▾")
        self.presets_button.setMenu(QMenu(self.presets_button))
        self.presets_button.menu().aboutToShow.connect(self._build_presets_menu)
        left.addWidget(self.presets_button)
        self.preset_feedback = QLabel("")
        self.preset_feedback.setObjectName("feedback")
        self.preset_feedback.setWordWrap(True)
        self.preset_feedback.hide()
        left.addWidget(self.preset_feedback)
        self.new_hint = QLabel("New: Echo Reducer and Noise Reducer. Use Add, or the button above, to put them on this channel.")
        self.new_hint.setWordWrap(True)
        self.new_hint.setObjectName("hint")
        left.addWidget(self.new_hint)
        outer.addLayout(left)

        right = QVBoxLayout()
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
        right.addWidget(self.editor_button)
        right.addWidget(self.params_area, 1)
        outer.addLayout(right, 1)

        self.activity_label: Optional[QLabel] = None
        self._activity_stage = None
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._update_activity)
        self.finished.connect(self._timer.stop)
        self.list.currentRowChanged.connect(self._show_params)
        self.list.itemChanged.connect(self._on_item_changed)
        self._reload(select=0)
        for button in self.findChildren(QPushButton):  # Enter must only finish a typed value, never press a button
            button.setAutoDefault(False)
            button.setDefault(False)

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
            if effect.kind == "vst3":
                item.setToolTip(f"VST3: {effect.path}")
            if effect.bypass:
                item.setForeground(QColor(themes.color("muted")))
            self.list.addItem(item)
        self.list.blockSignals(False)
        types = {e.type for e in self.channel.effects if e.kind == "builtin"}
        self.new_hint.setVisible(bool(types & {"highpass", "noise_gate"}) and not types & {"echo_reducer", "noise_reducer"})
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
        self._update_presets_button()  # a moved slider may mean the settings no longer match the preset

    def _update_presets_button(self) -> None:
        """The button names the preset in use ("Presets: Light touch"), or says "Custom" once something differs."""
        builtin = [e for e in self.channel.effects if e.kind == "builtin"]
        name = presets.active_name(self.channel.effects, self._user_presets()) if builtin else None
        shown = presets.short_name(name) if name else ("Custom" if builtin else "none yet")
        text = QFontMetrics(self.presets_button.font()).elidedText(f"Presets: {shown}", Qt.TextElideMode.ElideRight, 196)
        self.presets_button.setText(text + " ▾")
        self.presets_button.setToolTip(
            (f"In use: {name}.\n" if name else "The settings match none of the presets.\n" if builtin else "")
            + "Ready-made settings for different rooms, and your own. They never change the gate threshold.")

    def _build_presets_menu(self) -> None:
        menu = self.presets_button.menu()
        menu.clear()
        user = self._user_presets(reload=True)
        current = presets.active_name(self.channel.effects, user)
        for name, (description, entries) in presets.BUILT_IN.items():
            action = menu.addAction(name, partial(self._apply_preset, entries, name))
            action.setToolTip(description)
            action.setCheckable(True)
            action.setChecked(name == current)
        if user:
            menu.addSeparator()
            for name, entries in user.items():
                action = menu.addAction(name, partial(self._apply_preset, entries, name))
                action.setCheckable(True)
                action.setChecked(name == current)
        menu.addSeparator()
        save = menu.addAction("Save these settings as a preset…", self._save_preset)
        save.setEnabled(self._presets_file() is not None)
        if user:
            remove = menu.addMenu("Delete a preset of mine")
            for name in user:
                remove.addAction(name, partial(self._delete_preset, name))
        menu.setToolTipsVisible(True)

    def _apply_preset(self, entries: list, name: str = "") -> None:
        changed = presets.apply(self.engine, self.channel.id, entries)
        if changed:
            # Show the result: jump to a reducer page (that is where most presets change something you can see)
            target = next((i for i, e in enumerate(self.channel.effects)
                           if e.kind == "builtin" and e.type in ("echo_reducer", "noise_reducer")
                           and any(x["type"] == e.type for x in entries)), None)
            self._reload(select=target if target is not None else max(0, self.list.currentRow()))
            message = f"Applied \u201c{presets.short_name(name)}\u201d: {presets.summary(entries)}." if name else \
                f"Preset applied: {presets.summary(entries)}."
        else:
            self._reload(select=max(0, self.list.currentRow()))
            message = (f"\u201c{presets.short_name(name)}\u201d changed nothing: this channel has none of the effects it sets "
                       f"({presets.summary(entries)}). Use Add to put them on the channel, or the recommended voice chain, "
                       "then pick the preset again.")
        self.preset_feedback.setText(message)
        self.preset_feedback.show()
        say = getattr(self.parent(), "say", None)
        if say is not None:
            say(message)

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Name for this preset:")
        name = name.strip()
        if not ok or not name:
            return
        path = self._presets_file()
        stored = presets.load_user(path)
        stored[name] = presets.snapshot(self.channel.effects)
        if not presets.save_user(path, stored):
            QMessageBox.warning(self, "Save preset", "The preset could not be saved (is the settings folder writable?).")
        self._user_presets(reload=True)
        self._update_presets_button()

    def _delete_preset(self, name: str) -> None:
        path = self._presets_file()
        stored = presets.load_user(path)
        stored.pop(name, None)
        presets.save_user(path, stored)
        self._user_presets(reload=True)
        self._update_presets_button()

    def _apply_voice_chain(self) -> None:
        if any(e.kind == "builtin" and e.type in VOICE_CHAIN for e in self.channel.effects):
            ask = QMessageBox.question(self, "Recommended voice chain",
                                       "This replaces the built-in effects on this channel (not VST3 plugins) with the "
                                       "recommended chain at its default values. Continue?")
            if ask != QMessageBox.StandardButton.Yes:
                return
        self.engine.apply_voice_chain(self.channel.id)
        self._reload(select=0)

    def _current_effect(self) -> Optional[Effect]:
        row = self.list.currentRow()
        return self.channel.effects[row] if 0 <= row < len(self.channel.effects) else None

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
        dialog.exec()

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
