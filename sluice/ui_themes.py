# SPDX-License-Identifier: GPL-3.0-or-later
"""Choosing, applying, importing and exporting themes for the main window.

Part of the main window, split out of ``ui.py``: ``MainWindow`` inherits this class, so every method here is still a method of the window."""
from __future__ import annotations

import logging
import json
from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QGuiApplication, QPalette
from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import logs, themes
from .ui_constants import THEMES_URL

log = logging.getLogger("sluice.ui")


def _palette_for(colors: dict) -> QPalette:
    """Qt's own palette in the theme's colours, for the widgets the style sheet does not reach (dialogs, tooltips)."""
    palette = QPalette()
    role = QPalette.ColorRole

    def c(name: str) -> QColor:
        return QColor(colors[name])

    for which, name in ((role.Window, "bg"), (role.WindowText, "text"), (role.Base, "input"), (role.AlternateBase, "panel"),
                        (role.Text, "list_text"), (role.Button, "button"), (role.ButtonText, "button_text"),
                        (role.ToolTipBase, "popup"), (role.ToolTipText, "text"), (role.Highlight, "select"),
                        (role.HighlightedText, "select_text"), (role.Link, "link"), (role.PlaceholderText, "text_dim"),
                        (role.BrightText, "strong")):
        palette.setColor(which, c(name))
    for which in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, which, c("text_off"))
    return palette


# ------------------------------------------------------------------ main window


class ThemesMixin:
    # ------------------------------------------------------------------ themes
    def _system_is_dark(self) -> bool:
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", None)  # Qt 6.5 and newer; an older one has no word on it: stay dark
        return scheme is None or scheme() != Qt.ColorScheme.Light

    def _themes_folder(self) -> Optional[Path]:
        return themes.themes_dir(self.config_file)

    def current_theme(self) -> "themes.Theme":
        return themes.resolve(self.engine.mixer.theme, self._system_is_dark(), self._themes_folder())

    def apply_theme(self, theme_id: Optional[str] = None) -> "themes.Theme":
        """Show a theme now (or the one saved in the settings): the style sheet, the palette and the meters."""
        if theme_id is not None:
            self.engine.mixer.theme = theme_id
        theme = self.current_theme()
        themes.set_look(self.engine.mixer.look)
        themes.set_reduce_effects(self.engine.mixer.reduce_effects)
        themes.set_nexus_colors(self.engine.mixer.nexus_colors)
        colors = themes.look_colors(theme, self.engine.mixer.look)
        themes.set_current(colors)
        self.setStyleSheet(themes.build_style(colors, self.engine.mixer.look))
        app = QGuiApplication.instance()
        if app is not None:
            app.setPalette(_palette_for(colors))
        self.refresh_theme_widgets()
        return theme

    def _fill_look_menu(self) -> None:
        menu = self.look_menu
        menu.clear()
        group = QActionGroup(menu)
        for look_id, text in themes.LOOKS.items():
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.setChecked(themes.valid_look(self.engine.mixer.look) == look_id)
            action.triggered.connect(lambda _c=False, look_id=look_id: self.choose_look(look_id))
        menu.addSeparator()
        menu.addAction("&Compare looks…").triggered.connect(self.compare_looks)
        menu.setToolTipsVisible(True)

    def compare_looks(self) -> None:
        """Show a picture of each look in the colours of the theme in use, with a button to pick one."""
        from .ui_looks import CompareLooksDialog
        CompareLooksDialog(self).exec()

    def choose_look(self, look_id: str) -> None:
        """Change the shapes and sizes of the window (the colours stay as chosen under View > Theme)."""
        look_id = themes.valid_look(look_id)
        if look_id == self.engine.mixer.look:
            return
        self.engine.mixer.look = look_id
        self.apply_theme()
        if hasattr(self, "_restructure_for_look"):
            self._restructure_for_look()
        self.say(f"Look: {themes.LOOKS[look_id]}.")

    def set_nexus_colors(self, on: bool) -> None:
        """Nexus: its neon colours on the dark themes, or each theme's own colours."""
        self.engine.mixer.nexus_colors = bool(on)
        self.apply_theme()
        self.say("Nexus colours on." if on else "Each theme shows its own colours in Nexus.")

    def set_reduce_effects(self, on: bool) -> None:
        """Nexus: no shimmer on the rings and no waveform on the faders."""
        self.engine.mixer.reduce_effects = bool(on)
        themes.set_reduce_effects(on)
        for strip in self.strips:
            for fader in strip.faders.values():
                fader._update_reveal()
        self.say("Effects reduced: the rings stop shimmering and the faders show no waveform." if on else "Effects back on.")

    def _on_system_scheme_changed(self, *_args) -> None:
        if self.engine.mixer.theme == themes.SYSTEM and not self._closed:
            self.apply_theme()

    def _fill_theme_menu(self) -> None:
        menu = self.theme_menu
        menu.clear()
        group = QActionGroup(menu)
        chosen = themes.canonical_id(self.engine.mixer.theme, self._themes_folder())

        def add(theme_id: str, text: str, tip: str = "") -> None:
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.setChecked(chosen == theme_id)
            if tip:
                action.setToolTip(tip)
            action.triggered.connect(lambda _c=False, theme_id=theme_id: self.choose_theme(theme_id))

        for theme in themes.BUILT_IN.values():
            add(theme.id, theme.name)
        add(themes.SYSTEM, themes.SYSTEM_LABEL, "Dark or Light, following your desktop's own setting")
        custom = themes.custom_themes(self._themes_folder())
        if custom:
            menu.addSeparator()
            for theme in custom:
                add(theme.id, theme.name)
        if chosen.startswith(themes.CUSTOM_PREFIX) and not any(t.id == chosen for t in custom):  # not in the folder any more
            menu.addSeparator()
            missing = menu.addAction("An imported theme that is no longer in the themes folder (showing Dark)")
            missing.setCheckable(True)
            missing.setChecked(True)
            missing.setEnabled(False)
        menu.addSeparator()
        menu.addAction("&Import theme\u2026", self.import_theme)
        menu.addAction("&Export current theme\u2026", self.export_theme)
        if custom:
            remove = menu.addMenu("&Remove an imported theme")
            for theme in custom:
                remove.addAction(theme.name, partial(self.remove_theme, theme.id))
        menu.addSeparator()
        neon = menu.addAction("&Nexus colours on dark themes")
        neon.setCheckable(True)
        neon.setChecked(self.engine.mixer.nexus_colors)
        neon.setEnabled(themes.valid_look(self.engine.mixer.look) == "nexus")
        neon.setToolTip("Only in the Nexus look: its deep blue and cyan on Dark, Retro Purple, Midnight Blue and Amber Console. "
                        "Off: each theme keeps its own colours. High contrast and imported themes are never changed.")
        neon.triggered.connect(lambda checked=False: self.set_nexus_colors(neon.isChecked()))
        menu.addSeparator()
        more = menu.addAction("&Get more themes\u2026", partial(self.open_link, THEMES_URL))
        more.setToolTip("Opens the theme collection on the project page in your browser: download a file, then Import theme")
        menu.setToolTipsVisible(True)

    def choose_theme(self, theme_id: str) -> None:
        theme = self.apply_theme(theme_id)
        if theme_id == themes.SYSTEM:
            self.say(f"Theme: following your system (right now {theme.name}).")
        else:
            self.say(f"Theme: {theme.name}.")

    def import_theme_from(self, path) -> "themes.Theme":
        """Check a theme file, keep a copy in the themes folder and switch to it. Raises ThemeError."""
        folder = self._themes_folder()
        if folder is None:
            raise themes.ThemeError("Demo mode does not keep imported themes.")
        theme, notes = themes.load_file(path)
        problems = themes.contrast_problems(theme.colors)
        if problems:
            ask = QMessageBox.question(
                self, "Hard to read",
                f"The theme \u201c{theme.name}\u201d may be hard to read:\n\n" + "\n".join("\u2022 " + p for p in problems[:4])
                + "\n\nUse it anyway? You can switch back in View > Theme.")
            if ask != QMessageBox.StandardButton.Yes:
                raise themes.ThemeError("The theme was not imported.")
        stored = themes.save_custom(theme, folder)
        self.apply_theme(stored.id)
        self.say(f"Theme \u201c{stored.name}\u201d imported and in use." + (f" ({'; '.join(notes[:3])}.)" if notes else ""))
        return stored

    def import_theme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import theme", str(Path.home()), "Themes (*.json)")
        if not path:
            return
        try:
            self.import_theme_from(path)
        except themes.ThemeError as exc:
            QMessageBox.warning(self, "Could not import the theme", str(exc))

    def export_theme_to(self, path) -> None:
        theme = self.current_theme()
        name = theme.name if theme.id.startswith(themes.CUSTOM_PREFIX) else f"{theme.name} copy"
        data = themes.export_dict(themes.Theme(theme.id, name, theme.base, theme.colors))
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.say(f"Theme saved to {logs.short_path(path)}. Edit the colours, then use View > Theme > Import theme.")

    def export_theme(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export current theme", str(Path.home() / "sluice-theme.json"),
                                              "Themes (*.json)")
        if path:
            try:
                self.export_theme_to(path)
            except OSError as exc:
                QMessageBox.warning(self, "Could not save the theme", str(exc))

    def remove_theme(self, theme_id: str) -> None:
        if themes.remove_custom(theme_id, self._themes_folder()):
            if self.engine.mixer.theme == theme_id:
                self.apply_theme(themes.DEFAULT)
            self.say("Theme removed.")
        else:
            self.say("That theme could not be removed.")

    def open_theme_folder(self) -> None:
        folder = self._themes_folder()
        if folder is None:
            self.say("Demo mode does not keep imported themes.")
            return
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
