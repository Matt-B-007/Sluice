# SPDX-License-Identifier: GPL-3.0-or-later
"""The tour (0.13.1, House Standard): five short steps, skippable, replayable from Help > Show the tour. It starts by itself
only on a new install (never after an update: there it is offered in What's new and Help), and it takes the place of the
first-run hint of earlier versions, with the same two set-up buttons on the steps they belong to."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

STEPS = (
    (
        "Channels",
        "Each card is a channel: a group of apps (Game, Browser, Music...) or your microphone. Sluice puts each app on "
        "its channel by itself, and remembers it.",
        "apps",
    ),
    (
        "Listen and Broadcast",
        "Every channel has two faders. Listen is what you hear in your headphones. Broadcast is what your "
        "stream gets. Hear Broadcast lets you listen to exactly what your audience hears.",
        None,
    ),
    (
        "Sluice in OBS",
        "In OBS, record “Sluice (Broadcast) for OBS” for the whole mix, or one channel at a time "
        "(“Sluice (Game) for OBS”); use “Sluice (Mic)” as your microphone. The devices apps play into are "
        "hidden there, so they cannot be picked by mistake.",
        None,
    ),
    (
        "Effects",
        "Your microphone's effects (noise and echo reducers, EQ, compressor, limiter) are on its card under Effects. "
        "Each can be switched off or removed.",
        "microphone",
    ),
    (
        "Playing now",
        "The Playing now button at the top shows every app making sound, including any that is not on a channel "
        "yet: click one to put it on a channel.",
        None,
    ),
)
SEEN = "tour"


class Tour(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Welcome to Sluice")
        self.setMinimumWidth(460)
        self.index = 0
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.counter = QLabel("")
        self.counter.setObjectName("hint")
        self.title = QLabel("")
        self.title.setObjectName("settingstitle")
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.action = QPushButton("")
        self.action.clicked.connect(self._do_action)
        for widget in (self.counter, self.title, self.body, self.action):
            layout.addWidget(widget)
        buttons = QHBoxLayout()
        self.skip = QPushButton("Skip the tour")
        self.skip.clicked.connect(self.finish)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self.go(self.index - 1))
        self.next = QPushButton("Next")
        self.next.setDefault(True)
        self.next.clicked.connect(lambda: self.finish() if self.index == len(STEPS) - 1 else self.go(self.index + 1))
        buttons.addWidget(self.skip)
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        layout.addLayout(buttons)
        self.go(0)

    def go(self, index: int) -> None:
        self.index = max(0, min(len(STEPS) - 1, index))
        title, text, action = STEPS[self.index]
        self.counter.setText(f"Step {self.index + 1} of {len(STEPS)}")
        self.title.setText(title)
        self.body.setText(text)
        self.action.setVisible(action is not None)
        self.action.setText({"apps": "Add apps to channels", "microphone": "Choose my microphone"}.get(action or "", ""))
        self.back.setEnabled(self.index > 0)
        self.next.setText("Done" if self.index == len(STEPS) - 1 else "Next")

    def _do_action(self) -> None:
        action = STEPS[self.index][2]
        handler = {"apps": "first_run_apps", "microphone": "first_run_microphone"}.get(action or "")
        if handler and hasattr(self.window_, handler):
            getattr(self.window_, handler)()

    def finish(self) -> None:
        remember(self.window_)
        self.accept()


def remember(window) -> None:
    """The tour (and so the first-run hint it replaces) has been seen: it does not start by itself again."""
    mixer = window.engine.mixer
    for hint in (SEEN, "firstrun"):
        if hint not in mixer.hints_seen:
            mixer.hints_seen.append(hint)
    if hasattr(window, "save_settings"):
        window.save_settings()
    if hasattr(window, "_update_first_run"):
        window._update_first_run()


def should_start(window) -> bool:
    """Only on a new install: no settings file before this start, not the demo, not seen."""
    return (
        getattr(window, "config_file", None) is not None
        and not getattr(window, "_config_existed", True)
        and SEEN not in window.engine.mixer.hints_seen
    )
