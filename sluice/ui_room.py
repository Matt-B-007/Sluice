# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Measure my room" window: listen to the microphone for a few quiet seconds and set the noise gate from it."""
from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from . import room

NO_AUDIO_SECONDS = 2.0   # if nothing has been recorded after this long, audio is not running


class MeasureRoomDialog(QDialog):
    """Steps: explain, listen, show what was found (and offer it). ``on_use(threshold_db)`` applies the result."""

    TITLE = "Measure my room — {channel}"
    SECONDS = room.LISTEN_SECONDS

    def __init__(self, engine, channel, gate_effect_id: str, old_threshold: float, on_use: Callable[[float], None],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.engine, self.channel, self.gate_effect_id = engine, channel, gate_effect_id
        self.old_threshold, self._on_use = old_threshold, on_use
        self.result: Optional[room.RoomResult] = None
        self.on_applied: Optional[Callable] = None  # called with the result after it was used (Measure my room picks a Room choice)
        self.listening = False
        self._started = 0.0
        self.setWindowTitle(self.TITLE.format(channel=channel.label))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.text)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        layout.addWidget(self.bar)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.primary = QPushButton("")
        self.close_button = QPushButton("Cancel")
        buttons.addWidget(self.primary)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        for button in (self.primary, self.close_button):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.primary.clicked.connect(self._primary_clicked)
        self.close_button.clicked.connect(self.reject)

        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)
        self._show_intro()

    # ------------------------------------------------------------------ steps
    def _show_intro(self) -> None:
        self.listening = False
        self.result = None
        self.timer.stop()
        self.bar.setValue(0)
        self.bar.hide()
        self.text.setText(self._intro_text())
        self.primary.setText("Start listening")
        self.primary.setEnabled(True)
        self.close_button.setText("Cancel")
        self._fit()

    def _start(self) -> None:
        try:
            self.engine.measure_room_start(self.channel.id, self.SECONDS)
        except (RuntimeError, KeyError) as exc:
            self._show_message(f"I cannot listen right now: {exc}.", retry=False)
            return
        self.listening = True
        self._started = time.monotonic()
        self.bar.setValue(0)
        self.bar.show()
        self.text.setText(self._listening_text())
        self.primary.setText("Listening\u2026")
        self.primary.setEnabled(False)
        self.close_button.setText("Stop")
        self.timer.start()
        self._fit()

    def tick(self) -> None:
        """Called every 50 ms while listening (and by the tests)."""
        if not self.listening:
            return
        progress = self.engine.measure_room_progress(self.channel.id)
        self.bar.setValue(round(progress * 100))
        result = self._finish()
        if result is not None:
            self.listening = False
            self.timer.stop()
            self._show_result(result)
        elif progress == 0.0 and time.monotonic() - self._started > NO_AUDIO_SECONDS:
            self.engine.measure_room_cancel(self.channel.id)
            self.listening = False
            self.timer.stop()
            self._show_message("Nothing is being recorded, so audio does not seem to be running. "
                               "Check that Sluice has started its audio (see the status bar).", retry=True)

    # The pieces that differ between measuring the noise and measuring the echo.
    def _intro_text(self) -> str:
        return ("Leave your usual background noise on (the fan, the air conditioner, the TV) and stay quiet, with no "
                f"talking, while Sluice listens to this microphone for {room.LISTEN_SECONDS:.0f} seconds.\n\n"
                "It then sets the Noise Gate threshold just above that noise, so the room is quieted between your words. "
                "The Noise Reducer also starts from this noise, if it is on this channel.")

    def _listening_text(self) -> str:
        return "Listening... please stay quiet."

    def _finish(self):
        return self.engine.measure_room_finish(self.channel.id, self.gate_effect_id)

    def _question(self, result) -> str:
        return f"\nThe threshold is now {self.old_threshold:.1f} dB. Set it to {result.threshold_db:.1f} dB?"

    def _use_label(self, result) -> str:
        return f"Use {result.threshold_db:.1f} dB"

    def _apply(self, result) -> None:
        self._on_use(result.threshold_db)
        if getattr(result, "profile", None) is not None:
            self.engine.apply_noise_profile(self.channel.id, result.profile)
        if self.on_applied is not None:
            self.on_applied(result)

    def _fit(self) -> None:
        """The text changes length from step to step: make the window as tall as the words need."""
        self.layout().activate()
        self.resize(self.width(), self.layout().totalHeightForWidth(self.width()) + 2)

    def _show_result(self, result: room.RoomResult) -> None:
        self.result = result
        self.bar.hide()
        if result.usable:
            self.text.setText("\n".join([result.message, self._question(result)]))
            self.primary.setText(self._use_label(result))
            self.primary.setEnabled(True)
            self.close_button.setText("Not now")
            self._fit()
        else:
            self._show_message(result.message, retry=True)

    def _show_message(self, message: str, retry: bool) -> None:
        self.timer.stop()
        self.bar.hide()
        self.text.setText(message)
        self.result = None
        self.primary.setText("Try again")
        self.primary.setEnabled(retry)
        self.close_button.setText("Close")
        self._fit()

    # ---------------------------------------------------------------- buttons
    def _primary_clicked(self) -> None:
        if self.result is not None and self.result.usable:
            self._apply(self.result)
            self.accept()
        else:
            self._start()

    def reject(self) -> None:
        if self.listening:
            self.engine.measure_room_cancel(self.channel.id)
            self.listening = False
        self.timer.stop()
        super().reject()


class MeasureEchoDialog(MeasureRoomDialog):
    """Clap once, stay quiet: how long the room's echo lasts, for the Echo Reducer's "Room echo time"."""

    TITLE = "Measure my room's echo — {channel}"
    SECONDS = room.ECHO_SECONDS

    def __init__(self, engine, channel, old_time: float, on_use: Callable[[float], None],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(engine, channel, "", old_time, on_use, parent)

    def _intro_text(self) -> str:
        return ("Press Start, wait a moment, then clap your hands once, sharply, close to the microphone, and stay quiet "
                f"until the bar is full ({room.ECHO_SECONDS:.0f} seconds). Sluice measures how long the echo takes to die away.\n\n"
                "Turn the fan or air conditioner off if you can: the quieter the room, the better the measurement. In a "
                "loud room it will tell you if the clap was not clear enough.")

    def _listening_text(self) -> str:
        return "Listening... clap once, then stay quiet."

    def _finish(self):
        return self.engine.measure_echo_finish(self.channel.id)

    def _question(self, result) -> str:
        return f"\nRoom echo time is now {self.old_threshold:.1f} s. Set it to {result.reverb_time:.1f} s?"

    def _use_label(self, result) -> str:
        return f"Use {result.reverb_time:.1f} s"

    def _apply(self, result) -> None:
        self._on_use(result.reverb_time)


class MeasureVoiceDialog(MeasureRoomDialog):
    """Talk normally: how loud the voice is, and how far to move the microphone's level (for the Compressor to have work)."""

    TITLE = "Check my voice level — {channel}"
    SECONDS = room.VOICE_SECONDS

    def __init__(self, engine, channel, on_use: Callable[[float], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(engine, channel, "", 0.0, on_use, parent)

    def _intro_text(self) -> str:
        return (f"Press Start, then talk in your normal voice, as if you were on a call, for {room.VOICE_SECONDS:.0f} seconds. "
                "Read something out loud if you like.\n\nSluice measures how loud your voice is at the microphone, before any "
                "effect, and tells you how much to raise or lower the level. Too quiet a voice leaves the Compressor and "
                "Limiter with nothing to do, and the noise is relatively louder.")

    def _listening_text(self) -> str:
        return "Listening... please keep talking."

    def _finish(self):
        return self.engine.measure_voice_finish(self.channel.id)

    def _question(self, result) -> str:
        verb = "Add" if result.change_db > 0 else "Take off"
        return f"\n{verb} {abs(result.change_db):.0f} dB now, using the Gain effect on this channel?"

    def _use_label(self, result) -> str:
        return f"{'Add' if result.change_db > 0 else 'Take off'} {abs(result.change_db):.0f} dB"

    def _apply(self, result) -> None:
        self._on_use(result.change_db)
