# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl+K command search (0.13.1, House Standard): type a few letters of anything Sluice can do and press Enter. It lists every
menu item (so it can never disagree with the menus), each channel's effects and mutes, and every Settings section."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu, QVBoxLayout

from .ui_base import plain


def commands(window) -> list:
    """[(label, run)] for everything the search offers."""
    found, seen = [], set()

    def walk(menu: QMenu, path: str) -> None:
        for action in menu.actions():
            if action.isSeparator() or not action.text():
                continue
            if action.menu() is not None:
                walk(action.menu(), f"{path} › {plain(action.text())}" if path else plain(action.text()))
                continue
            if not action.isEnabled() or action.property("heading"):
                continue
            label = f"{path} › {plain(action.text())}" if path else plain(action.text())
            keys = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if keys:
                label += f"   ({keys})"
            if label not in seen:
                seen.add(label)
                found.append((label, action.trigger))

    # 0.13.1-beta.3: the skins and themes are found too (their lists are only filled when opened), and so is the "Play to" switch
    for fill in ("_fill_skin_menu", "_fill_theme_menu"):
        if hasattr(window, fill):
            getattr(window, fill)()
    # ...and a command is named for what it does, not for a File, Mixer or Window menu that has not been on screen since 0.12.0
    for menu in getattr(window, "action_groups", []):
        walk(menu, "")
    extra = getattr(window, "play_to_action", None)
    if extra is not None:
        found.append((plain(extra.text()), extra.trigger))
    engine = window.engine
    for channel in engine.mixer.channels:
        found.append((f"Effects on {channel.label}", partial(_effects, window, channel.id)))
        for mix in engine.mixer.mixes:
            muted = channel.mutes.get(mix.id, False)
            found.append(
                (
                    f"{'Unmute' if muted else 'Mute'} {channel.label} in {mix.label}",
                    partial(_toggle_mute, window, channel.id, mix.id),
                )
            )
    from .ui_settings import SECTIONS

    for section in SECTIONS:
        found.append((f"Settings › {section}", partial(window.open_settings, section)))
    return found


def _strip(window, channel_id: str):
    return next((strip for strip in getattr(window, "strips", []) if strip.channel.id == channel_id), None)


def _effects(window, channel_id: str) -> None:
    strip = _strip(window, channel_id)
    if strip is not None and hasattr(strip, "open_effects"):
        strip.open_effects()


def _toggle_mute(window, channel_id: str, mix_id: str) -> None:
    channel = window.engine.mixer.channel(channel_id)
    on = not channel.mutes.get(mix_id, False)
    window.engine.set_mute(channel_id, mix_id, on)
    strip = _strip(window, channel_id)
    if strip is not None and hasattr(strip, "sync_from_model"):
        strip.sync_from_model()
    window.say(f"{channel.label} {'muted' if on else 'unmuted'} in {window.engine.mixer.mix(mix_id).label}.")


def _parts(label: str) -> list:
    low = label.lower()
    for mark in "\u203a()\u201c\u201d:,/-\u00b7":
        low = low.replace(mark, " ")
    parts = low.split()
    return parts + [part[2:] for part in parts if part.startswith("un") and len(part) > 4]  # "mute" finds "Unmute" too


def matches(label: str, text: str) -> bool:
    """Every word typed starts a word of the label. 0.13.1-beta.3: it was "is anywhere inside", so "rows" found "Browser"."""
    parts = _parts(label)
    return all(any(part.startswith(word) for part in parts) for word in _parts(text))


def score(label: str, text: str) -> int:
    """Lower is better: a label that starts with the first word, then words that start with what was typed."""
    words, low = text.lower().split(), label.lower()
    if not words:
        return 0
    starts = sum(1 for word in words if any(part.startswith(word) for part in low.replace("\u203a", " ").split()))
    return (0 if low.startswith(words[0]) else 1) * 100 - starts


class CommandSearch(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Search commands")
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type what you want to do: mute mic, hear broadcast, effects, theme...")
        self.search.setAccessibleName("Search commands")
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.run_selected)
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.setAccessibleName("Commands")
        self.results.itemActivated.connect(lambda item: self.run(item))
        layout.addWidget(self.results, 1)
        self.all = commands(window)
        self.refresh("")

    def refresh(self, text: str) -> None:
        self.results.clear()
        for label, run in sorted((c for c in self.all if matches(c[0], text)), key=lambda c: score(c[0], text)):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, run)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        else:  # 0.13.1-beta.3: an empty box said nothing
            item = QListWidgetItem(f"Nothing matches \u201c{text.strip()}\u201d. Try one word, such as mute, theme or effects.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.results.count():
            row = self.results.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
            self.results.setCurrentRow(max(0, min(self.results.count() - 1, row)))
            return
        super().keyPressEvent(event)

    def run_selected(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self.run(item)

    def run(self, item: QListWidgetItem) -> None:
        run = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if callable(run):
            run()


def install(window) -> None:
    """Ctrl+K opens the search, and ? the shortcuts page (only when nothing takes typing: Qt gives a text box the key first)."""
    search = QAction("Search commands", window)
    search.setShortcut(QKeySequence("Ctrl+K"))
    search.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    search.triggered.connect(lambda: _open(window))
    window.addAction(search)
    window.command_action = search
    question = QAction("Keyboard shortcuts", window)
    question.setShortcut(QKeySequence("?"))
    question.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    question.triggered.connect(window.show_shortcuts)
    window.addAction(question)


def _open(window) -> None:
    window.command_search = CommandSearch(window)
    window.command_search.show()
    window.command_search.search.setFocus()
