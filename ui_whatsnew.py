# SPDX-License-Identifier: GPL-3.0-or-later
"""A window that shows release notes (What's new after an update, and the notes of an available update)."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from . import themes

RELEASES_URL = "https://github.com/Matt-B-007/Sluice/releases"


class NotesDialog(QDialog):
    """A heading, the notes (Markdown), and up to two buttons: an optional main one that opens a web page, and Close."""

    def __init__(self, title: str, heading: str, markdown: str, main_label: str = "", main_url: str = "",
                 parent: Optional[QWidget] = None, *, action: Optional[Callable[[], None]] = None,
                 action_label: str = "") -> None:
        """``action`` (with ``action_label``) adds a button that runs it, for example *Update now*; the main button, if
        any, then stays beside it as the way to the download page."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 520)
        self.main_url = main_url
        layout = QVBoxLayout(self)
        self.heading = QLabel(heading)
        self.heading.setObjectName("title")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.document().setDefaultStyleSheet(f"a {{ color: {themes.color('link')}; }} code {{ color: {themes.color('code')}; }}")
        self.view.setMarkdown(markdown)
        layout.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        self.all_releases = QPushButton("All releases")
        self.all_releases.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        buttons.addWidget(self.all_releases)
        buttons.addStretch(1)
        self.action = action
        self.action_button: Optional[QPushButton] = None
        self.main_button: Optional[QPushButton] = None
        if main_label and main_url:
            self.main_button = QPushButton(main_label)
            self.main_button.clicked.connect(self._open_main)
            buttons.addWidget(self.main_button)
        if action is not None and action_label:
            self.action_button = QPushButton(action_label)
            self.action_button.clicked.connect(self._run_action)
            buttons.addWidget(self.action_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def _run_action(self) -> None:
        self.accept()
        if self.action is not None:
            self.action()

    def _open_main(self) -> None:
        QDesktopServices.openUrl(QUrl(self.main_url))
        self.accept()
