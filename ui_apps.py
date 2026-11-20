# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Installed app or game" picker."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .apps import Catalog


class AppPickerDialog(QDialog):
    """One searchable list for everything that can go on a channel: programs playing sound now, installed
    programs and games, and (by typing a name that is not in the list) any other program."""

    def __init__(self, catalog: Catalog, channel_label: str, owner_of: Callable[[str], Optional[str]],
                 parent: Optional[QWidget] = None, running: Optional[list] = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.owner_of = owner_of  # key -> label of the channel that has it now, or None
        self.running = list(running or [])  # [(label, key)] of programs playing sound right now
        self.setWindowTitle(f"Add an app or game to {channel_label}")
        self.resize(460, 520)
        layout = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search, or type a program name...")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.games_only = QCheckBox("Games only")
        layout.addWidget(self.games_only)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.list, 1)
        self.note = QLabel("")
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_button = buttons.addButton("Add selected", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self._fill)
        self.search.returnPressed.connect(self._enter)
        self.games_only.toggled.connect(self._fill)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self._fill()
        self.search.setFocus()

    def _fill(self) -> None:
        text = self.search.text().strip()
        needle = text.lower()
        self.list.clear()
        listed: set = set()

        def add(label: str, key: str, note: str = "") -> None:
            owner = self.owner_of(key)
            line = label + (f"   {note}" if note else "") + (f"   now in {owner}" if owner else "")
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(item)
            listed.add(key)

        games = {e.key for e in self.catalog.entries if e.kind == "game"}
        for label, key in self.running:  # what is making sound now comes first
            if self.games_only.isChecked() and key not in games:
                continue
            if needle and needle not in label.lower() and needle not in key:
                continue
            add(label, key, "(playing now)")
        for entry in self.catalog.entries:
            if entry.key in listed or (self.games_only.isChecked() and entry.kind != "game"):
                continue
            if needle and needle not in entry.name.lower() and needle not in entry.key:
                continue
            add(entry.name, entry.key, "(game)" if entry.kind == "game" else "")
        if needle and needle not in listed and not self.games_only.isChecked():
            typed = QListWidgetItem(f"Add \u201c{text}\u201d by name")
            typed.setData(Qt.ItemDataRole.UserRole, needle)
            self.list.addItem(typed)  # always offered, so a program that is not listed can still be added
        if len(self.catalog) == 0 and not self.running:
            self.note.setText("No installed programs were found. Type a program name and add it by name.")
        else:
            self.note.setText("Hold Ctrl or Shift to select several. Typing a name that is not listed adds it by name.")
        self._selection_changed()

    def _enter(self) -> None:
        if not self.list.selectedItems() and self.list.count():
            self.list.item(0).setSelected(True)
        if self.list.selectedItems():
            self.accept()

    def _selection_changed(self) -> None:
        self.add_button.setEnabled(bool(self.list.selectedItems()))

    def selected_keys(self) -> list:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
