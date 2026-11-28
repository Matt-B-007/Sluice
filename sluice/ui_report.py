# SPDX-License-Identifier: GPL-3.0-or-later
"""Help > Report a problem (0.13.1, House Standard): a short summary, what happened, a preview of exactly what the report holds,
and a choice about the settings file (left out unless ticked: it names channels, devices and apps). The main buttons keep the
report on this computer (Save, Copy, Open the log folder); sending it is a separate, deliberate step: a private ticket on
Sluice's Discord (the preferred place: only you and the maintainer see it) or a public GitHub issue, which says so first.
Nothing is sent until you choose to."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import logs, report
from .ui_base import DISCORD_URL, ISSUES_URL


GITHUB_TITLE_MAX = 120
GITHUB_STORY_MAX = 1500  # characters of the story in the link (GitHub's limit on a link is about 8,000 once encoded)


class ReportDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Report a problem")
        self.resize(720, 640)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        intro = QLabel("Nothing is sent until you choose to. Save or copy the report first; then send it where you like.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(QLabel("Short summary"))
        self.summary = QLineEdit()
        self.summary.setPlaceholderText("For example: the game is silent in OBS after an update")
        self.summary.setAccessibleName("Short summary")
        layout.addWidget(self.summary)
        layout.addWidget(QLabel("What happened, and what did you expect?"))
        self.story = QPlainTextEdit()
        self.story.setAccessibleName("What happened, and what did you expect?")
        self.story.setFixedHeight(96)
        layout.addWidget(self.story)
        self.settings_box = QCheckBox("Include my settings file (it names your channels, devices and apps)")
        self.settings_box.setAccessibleName("Include my settings file")
        self.settings_box.toggled.connect(lambda _on: self.refresh())
        layout.addWidget(self.settings_box)
        layout.addWidget(QLabel("Details that will be included"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Details that will be included")
        layout.addWidget(self.preview, 1)

        main = QHBoxLayout()
        self.save_button = self._button(main, "Save to file…", self.save, primary=True)
        self.copy_button = self._button(main, "Copy report", self.copy)
        self._button(main, "Open log folder", window.open_log_folder)
        main.addStretch(1)
        layout.addLayout(main)
        send = QHBoxLayout()
        send.addWidget(QLabel("Send it:"))
        self._button(send, "Private ticket on Discord", self.discord)
        self._button(send, "Open on GitHub…", self.github)
        send.addStretch(1)
        layout.addLayout(send)
        note = QLabel(
            "A Discord ticket is private: only you and the maintainer see it. A GitHub issue is public: anyone can read it."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")
        layout.addWidget(note)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        self.saved_path: Path | None = None
        self.refresh()

    @staticmethod
    def _button(row: QHBoxLayout, text: str, slot, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setAccessibleName(text.rstrip("…"))
        button.clicked.connect(lambda _c=False: slot())
        button.setAutoDefault(False)  # 0.13.1-beta.3: Enter in the summary box opened the Save dialog
        row.addWidget(button)
        return button

    # ------------------------------------------------------------------ what goes in
    def text(self) -> str:
        """The report as it would be saved or copied: the summary and story first, then the anonymized report."""
        top = []
        if self.summary.text().strip():
            top.append(f"Summary: {self.summary.text().strip()}")
        if self.story.toPlainText().strip():
            top.append("What happened, and what was expected:\n" + self.story.toPlainText().strip())
        body = report.anonymize(report.build_report(include_settings=self.settings_box.isChecked()))
        return ("\n\n".join(top) + "\n\n" if top else "") + body

    def refresh(self) -> None:
        try:
            self.preview.setPlainText(report.anonymize(report.build_report(include_settings=self.settings_box.isChecked())))
        except Exception as exc:  # noqa: BLE001 - the preview must never stop the dialog
            self.preview.setPlainText(f"(The report could not be built: {type(exc).__name__}: {exc})")

    # ------------------------------------------------------------------ keeping it
    def save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the report", str(Path.home() / report.default_name()), "Text files (*.txt)"
        )
        if path:
            self.save_to(Path(path))

    def save_to(self, path: Path) -> None:
        try:
            path.write_text(self.text(), encoding="utf-8")
        except OSError as exc:
            self.status.setText(f"The report could not be saved there: {exc}. Try another folder.")
            return
        self.saved_path = path
        self.status.setText(f"Saved to {logs.short_path(path)}. Attach this file when you send it.")

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text())
        self.status.setText("The report is copied. Paste it where you send it.")

    # ------------------------------------------------------------------ sending it (a separate step)
    def discord(self) -> None:
        QDesktopServices.openUrl(QUrl(DISCORD_URL))
        self.status.setText(
            "Discord is opening: open a ticket in the Sluice support channel and attach the saved report "
            "(or paste the copied one). Please not in the public forum."
        )

    def github_url(self) -> str:
        """A new GitHub issue with the summary and the report's header only (not the whole report): the file is attached."""
        title = (self.summary.text().strip() or "Problem report")[:GITHUB_TITLE_MAX]
        story = self.story.toPlainText().strip() or "(what happened, and what was expected)"
        if len(story) > GITHUB_STORY_MAX:  # 0.13.1-beta.3: GitHub refuses a link that is too long; the rest is in the file
            story = story[:GITHUB_STORY_MAX].rstrip() + "\n(…the rest is in the attached report file)"
        body = report.header() + "\n" + story + "\n\nPlease attach the saved report file here (drag it into this box)."
        return f"{ISSUES_URL}/new?title={quote(title)}&body={quote(report.anonymize(body))}"

    def github(self) -> None:
        from . import ui_dialog

        answer = ui_dialog.question(
            self,
            "Open on GitHub",
            "This creates a PUBLIC issue: anyone can read it. Only the summary "
            "and the short header are filled in; attach the saved file yourself if you are happy for it "
            "to be public. For a private report, use a Discord ticket instead.\n\nOpen GitHub?",
        )
        if answer != ui_dialog.Button.Yes:
            return
        QDesktopServices.openUrl(QUrl(self.github_url()))
        self.status.setText("GitHub is opening with the summary filled in. Attach the saved report file there.")
