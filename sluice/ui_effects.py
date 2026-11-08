# SPDX-License-Identifier: GPL-3.0-or-later
"""Effects dialog: a channel's effect chain, built-in effects and VST3 plugins."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

from .effects import ParamInfo, builtin_names, scan_vst3, vst3_plugin_names, vst3_search_paths
from .model import VOICE_CHAIN, Effect, new_effect_id
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
        outer.addLayout(left)

        right = QVBoxLayout()
        self.title = QLabel("")
        self.title.setObjectName("title")
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #ef5258;")
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
                item.setForeground(QColor("#6f7887"))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.channel.effects:
            row = 0 if select is None else max(0, min(select, len(self.channel.effects) - 1))
            self.list.setCurrentRow(row)
        self._show_params(self.list.currentRow())

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
        item.setForeground(QColor("#6f7887") if bypass else QColor("#d7dce2"))

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
        for info in infos[:MAX_VST3_PARAMS]:
            layout.addWidget(ParamRow(info, partial(self.engine.set_effect_param, effect.id)))
        if len(infos) > MAX_VST3_PARAMS:
            more = QLabel(f"{len(infos) - MAX_VST3_PARAMS} more parameters: use “Open plugin window”.")
            more.setObjectName("hint")
            layout.addWidget(more)
        self.params_area.setWidget(panel)

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
                                    f"{path} was added. Sluice now finds {len(found)} VST3 plugin(s) in all its folders.\n"
                                    "Open Add > VST3 plugin to see them.")

    def _show_vst3_folders(self) -> None:
        lines = []
        for folder in vst3_search_paths(self.engine.mixer.vst3_folders):
            count = len(scan_vst3([folder])) if folder.is_dir() else None
            lines.append(f"{folder}   ({'does not exist' if count is None else f'{count} plugin(s)'})")
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
