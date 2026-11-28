# SPDX-License-Identifier: GPL-3.0-or-later
"""The uninstall dialog (0.13.1, House Standard): one red Uninstall button; settings and logs are kept unless the person ticks
"Also delete my settings and logs"; the list underneath always shows exactly what will go."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import uninstall


class UninstallDialog(QDialog):
    def __init__(self, keep_plan, everything_plan, parent=None, plan=None) -> None:
        super().__init__(parent)
        self.keep, self.everything = keep_plan, everything_plan
        self._plan = plan  # 0.13.1-beta.3: (delete settings, clear caches) -> Plan, so the list follows both boxes
        self.setWindowTitle("Uninstall Sluice")
        self.resize(560, 440)
        layout = QVBoxLayout(self)
        title = QLabel("Uninstall Sluice?")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Sluice closes, then removes itself a moment later and checks that nothing was missed. "
            "Your audio goes back to how it was before Sluice."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.delete_settings = QCheckBox("Also delete my settings and logs")
        self.delete_settings.setChecked(False)
        self.delete_settings.toggled.connect(self._refresh)
        layout.addWidget(self.delete_settings)
        self.caches = QCheckBox("Also clear download caches (pip and cargo; other programs use them too)")
        self.caches.toggled.connect(self._refresh)
        self.caches.setToolTip(
            "Clears ~/.cache/pip and ~/.cargo/registry. Programs that use them just download again when they need to."
        )
        layout.addWidget(self.caches)
        self.listing = QLabel()
        self.listing.setWordWrap(True)
        self.listing.setObjectName("hint")
        layout.addWidget(self.listing, 1)
        stays = QLabel(" ".join(uninstall.STAYS))
        stays.setWordWrap(True)
        stays.setObjectName("hint")
        layout.addWidget(stays)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.uninstall_button = QPushButton("Uninstall")
        self.uninstall_button.setObjectName("danger")
        self.uninstall_button.clicked.connect(self.accept)
        buttons.addWidget(self.uninstall_button)
        layout.addLayout(buttons)
        self.cancel_button.setDefault(True)  # Enter never uninstalls by accident
        self._refresh()

    def _refresh(self) -> None:
        plan = self.everything if self.delete_settings.isChecked() else self.keep
        if self._plan is not None:
            plan = self._plan(self.delete_settings.isChecked(), self.caches.isChecked())
        text = uninstall.describe(plan).replace("Sluice will remove:", "This removes:").replace("Left alone:", "Kept:")
        self.listing.setText(text.replace("\n  (nothing: it is not installed here)", ""))
