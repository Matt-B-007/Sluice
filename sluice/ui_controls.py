# SPDX-License-Identifier: GPL-3.0-or-later
"""Glue for outside control: the control socket, the MIDI hub, and the "Controllers" window."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .control import ControlApi, ControlServer, socket_path
from .engine import Engine
from .midi import Binding, MidiEvent, MidiHub, load_bindings, save_bindings

log = logging.getLogger("sluice.controls")

POLL_MS = 15
RESCAN_MS = 2000

ACTIONS = [
    ("Channel fader", "level"),
    ("Channel mute", "mute"),
    ("Master fader (a whole mix)", "master"),
    ("Master mute (a whole mix)", "master-mute"),
]
CONTROLS = {
    "level": [("Fader or knob (absolute)", "fader"), ("Endless encoder (turns +/-)", "encoder")],
    "master": [("Fader or knob (absolute)", "fader"), ("Endless encoder (turns +/-)", "encoder")],
    "mute": [("Button", "button")],
    "master-mute": [("Button", "button")],
}


class Controls:
    """Owns everything that lets outside devices drive the app. Create after the window, call ``close()`` on exit."""

    def __init__(self, engine: Engine, window, bindings_file: Optional[Path], demo: bool = False) -> None:
        self.engine, self.window = engine, window
        self.bindings_file = bindings_file
        self.api = ControlApi(engine, on_change=self._changed)
        self.server = ControlServer(self.api, socket_path(demo))
        bindings = load_bindings(bindings_file) if bindings_file else []
        self.hub = MidiHub(self.api.handle, bindings)
        self.poll_timer = QTimer(window)
        self.poll_timer.timeout.connect(self.hub.poll)
        self.scan_timer = QTimer(window)
        self.scan_timer.timeout.connect(self.rescan)
        self.rescan()
        self.scan_timer.start(RESCAN_MS)
        self.dialog: Optional["ControllersDialog"] = None

    def rescan(self) -> None:
        """Look for controllers. Reading them is only polled while one is plugged in: with none, nothing wakes up."""
        self.hub.rescan()
        if self.hub.has_inputs():
            if not self.poll_timer.isActive():
                self.poll_timer.start(POLL_MS)
        elif self.poll_timer.isActive():
            self.poll_timer.stop()

    def _changed(self, cmd: str) -> None:
        if cmd == "show":  # a second Sluice was started (menu, autostart): bring this window to the front
            self.window.bring_to_front()
            return
        self.window.sync_from_model()
        if cmd == "assign":
            self.window.refresh_sources()

    def save(self) -> None:
        if self.bindings_file is None:
            return
        try:
            save_bindings(self.bindings_file, self.hub.bindings)
        except OSError as exc:
            log.warning("could not save controller bindings: %s", exc)

    def show_dialog(self) -> None:
        self.dialog = ControllersDialog(self, self.window)
        self.dialog.exec()
        self.dialog = None

    def close(self) -> None:
        self.poll_timer.stop()
        self.scan_timer.stop()
        self.hub.close()
        self.server.close()
        self.save()


class ControllersDialog(QDialog):
    def __init__(self, controls: Controls, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controls = controls
        self.setWindowTitle("Controllers")
        self.resize(640, 520)
        layout = QVBoxLayout(self)

        self.devices = QLabel()
        self.devices.setWordWrap(True)
        layout.addWidget(self.devices)
        hint = QLabel(
            "Stream Deck and other button boxes: have each button run <b>sluice ctl</b> (see the README, "
            "<i>Controllers</i>). MIDI faders, knobs and pads are set up here."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("Your bindings"))
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove)
        layout.addWidget(remove)

        layout.addWidget(QLabel("Add a binding"))
        form = QFormLayout()
        self.action = QComboBox()
        for label, value in ACTIONS:
            self.action.addItem(label, value)
        self.channel = QComboBox()
        for channel in controls.engine.mixer.channels:
            self.channel.addItem(channel.label, channel.id)
        self.mix = QComboBox()
        self.control = QComboBox()
        self.step = QDoubleSpinBox()
        self.step.setRange(0.5, 6.0)
        self.step.setSingleStep(0.5)
        self.step.setValue(1.0)
        self.step.setSuffix(" dB per click")
        form.addRow("Does what", self.action)
        form.addRow("Channel", self.channel)
        form.addRow("Mix", self.mix)
        form.addRow("Control is a", self.control)
        form.addRow("Encoder step", self.step)
        layout.addLayout(form)
        self.learn_button = QPushButton("Learn: then touch the control on your device")
        self.learn_button.clicked.connect(self._learn)
        layout.addWidget(self.learn_button)
        self.message = QLabel("")
        self.message.setObjectName("hint")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.action.currentIndexChanged.connect(self._action_changed)
        self.control.currentIndexChanged.connect(self._control_changed)
        self._action_changed()
        self._refresh()
        self.finished.connect(lambda _code: controls.hub.learn(None))
        self.timer = QTimer(self)  # device list can change while the window is open
        self.timer.timeout.connect(self._refresh_devices)
        self.timer.start(1000)

    # ------------------------------------------------------------------ view
    def _action_changed(self) -> None:
        action = self.action.currentData()
        self.control.clear()
        for label, value in CONTROLS[action]:
            self.control.addItem(label, value)
        is_master = action in ("master", "master-mute")
        self.channel.setEnabled(not is_master)
        self.mix.clear()
        if not is_master:
            self.mix.addItem("Both", "")
        for mix in self.controls.engine.mixer.mixes:
            self.mix.addItem(mix.label, mix.label.lower())
        self._control_changed()

    def _control_changed(self) -> None:
        self.step.setEnabled(self.control.currentData() == "encoder")

    def _refresh_devices(self) -> None:
        hub = self.controls.hub
        paths = hub.device_paths
        if paths:
            text = f"MIDI inputs being listened to: {len(paths)}  ({', '.join(p.rsplit('/', 1)[-1] for p in paths)})"
        else:
            text = "No MIDI controller found. Plug one in: it is picked up within a couple of seconds."
        if hub.denied:
            text += "\nNo permission to read " + ", ".join(hub.denied) + ". Add yourself to the 'audio' group, then log in again."
        self.devices.setText(text)

    def _refresh(self) -> None:
        self._refresh_devices()
        self.list.clear()
        for binding in self.controls.hub.bindings:
            kind, channel, number = binding.source.split(":")
            name = ("CC " if kind == "cc" else "Note ") + f"{number} (MIDI channel {channel})"
            self.list.addItem(f"{name}   →   {binding.describe()}   [{binding.control}]")

    # ----------------------------------------------------------------- actions
    def _learn(self) -> None:
        hub = self.controls.hub
        if hub.learning is not None:
            hub.learn(None)
            self.learn_button.setText("Learn: then touch the control on your device")
            self.message.setText("")
            return
        if not hub.device_paths:
            self.message.setText("No MIDI controller is connected, so there is nothing to learn from.")
            return
        action = self.action.currentData()
        needs_channel = action in ("level", "mute")
        binding = Binding(
            source="",
            control=self.control.currentData(),
            action=action,
            channel=self.channel.currentData() if needs_channel else "",
            mix=self.mix.currentData() or "",
            step_db=self.step.value(),
        )
        if needs_channel and not binding.channel:
            self.message.setText("This mixer has no channels yet.")
            return
        self.learn_button.setText("Waiting for a control...  (click to cancel)")
        self.message.setText("Move the fader, turn the knob or press the button you want to use.")
        hub.learn(lambda event: self._learned(binding, event))

    def _learned(self, binding: Binding, event: MidiEvent) -> None:
        binding.source = event.source
        hub = self.controls.hub
        hub.set_bindings([b for b in hub.bindings if b.source != binding.source] + [binding])
        self.controls.save()
        log.info("controller binding added: %s -> %s", binding.source, binding.describe())
        self.learn_button.setText("Learn: then touch the control on your device")
        self.message.setText(f"Bound {event.source} to {binding.describe()}. Add another, or close this window.")
        self._refresh()

    def _remove(self) -> None:
        row = self.list.currentRow()
        hub = self.controls.hub
        if 0 <= row < len(hub.bindings):
            hub.set_bindings(hub.bindings[:row] + hub.bindings[row + 1:])
            self.controls.save()
            self._refresh()
