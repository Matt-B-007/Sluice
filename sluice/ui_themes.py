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

from . import ui_dialog
from . import logs, themes
from .ui_base import THEMES_URL

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
        themes.set_skin(self.engine.mixer.skin)
        themes.set_reduce_effects(self.engine.mixer.reduce_effects)
        themes.set_skin_colors(self.engine.mixer.skin_colors)
        colors = themes.skin_colors(theme, self.engine.mixer.skin)
        themes.set_current(colors)
        # The skin dresses the mixer (the window's content and its status bar); menus, the Settings window and the other windows
        # opened from it keep the shared style in every skin, in the theme's colours (0.11.6).
        # Calm, narrowed to dialogs, menus and tooltips, in the theme's own colours (not a skin's own), so they match in every skin.
        # 0.11.7: on the whole application, not the window: the tray's menu, a desktop widget's menu and a message box with no
        # parent are windows of their own, which a sheet on the main window never reached. Narrowed as it is, none of it reaches
        # the mixer (that has only its skin's sheet).
        shared = themes.shared_style(themes.skin_colors(theme, "calm"))
        app = QGuiApplication.instance()
        if app is not None and hasattr(app, "setStyleSheet"):
            if app.styleSheet() != shared:
                app.setStyleSheet(shared)
            if self.styleSheet():
                self.setStyleSheet("")
        else:
            self.setStyleSheet(shared)
        self.dress_skin()
        if app is not None:
            app.setPalette(_palette_for(colors))
        self.refresh_theme_widgets()
        desktop = getattr(self, "desktop", None)
        if desktop is not None:  # the desktop widgets are windows of their own: they follow the look and colours too
            desktop.restyle()
        settings = getattr(self, "settings_window", None)
        if settings is not None and settings.isVisible():  # its pictures of the looks are drawn in the theme in use
            settings.refresh()
        return theme

    def _fill_skin_menu(self) -> None:
        menu = self.skin_menu
        menu.clear()
        group = QActionGroup(menu)
        for skin_id, text in themes.SKINS.items():
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.setChecked(themes.valid_skin(self.engine.mixer.skin) == skin_id)
            action.triggered.connect(lambda _c=False, skin_id=skin_id: self.choose_skin(skin_id))
        menu.addSeparator()
        menu.addAction("&Compare skins…").triggered.connect(self.compare_skins)
        menu.setToolTipsVisible(True)

    def compare_skins(self) -> None:
        """A picture of each skin in the colours of the theme in use, to pick one: Settings > Themes and skins (0.12.2: one window
        fewer; the pictures there are the same)."""
        self.open_settings("Themes and skins")

    def choose_skin(self, skin_id: str) -> None:
        """Change the shapes and sizes of the window (the colours stay as chosen under View > Theme)."""
        skin_id = themes.valid_skin(skin_id)
        if skin_id == self.engine.mixer.skin:
            return
        self.engine.mixer.skin = skin_id
        self.apply_theme()
        if hasattr(self, "_restructure_for_skin"):
            self._restructure_for_skin()
        from . import ui_glass
        later = skin_id == "glass" and ui_glass.wants_see_through(self.engine.mixer) and not themes.see_through()
        self.say(f"Skin: {themes.SKINS[skin_id]}." + (" The window becomes see-through the next time Sluice starts." if later else ""))
        if skin_id == "glass" and hasattr(self, "hint_missing_part"):
            self.hint_missing_part("kwindowsystem")  # once: on Plasma without KDE's blur, Glass shows no blur behind

    def set_see_through(self, on: bool) -> None:
        """Settings > Themes and skins > See-through window (Glass on KDE). The window's see-through-ness is fixed when it first
        appears, so this takes effect at the next start."""
        self.engine.mixer.see_through = bool(on)
        from . import ui_glass
        now = themes.see_through()
        if ui_glass.wants_see_through(self.engine.mixer) != now:
            self.say("See-through window: " + ("on" if on else "off") + " the next time Sluice starts.")
        else:
            self.say("See-through window: " + ("on." if on else "off."))

    def set_skin_colors(self, on: bool) -> None:
        """Nexus's and Tile's own colours on Dark (and Tile's white keys on Light), or every theme's own colours everywhere."""
        self.engine.mixer.skin_colors = bool(on)
        self.apply_theme()
        self.say("Skins show their own colours on Dark and Light." if on else "Every theme shows its own colours in every skin.")

    def set_reduce_effects(self, on: bool) -> None:
        """Nexus: no shimmer on the rings and no waveform on the faders."""
        self.engine.mixer.reduce_effects = bool(on)
        themes.set_reduce_effects(on)
        root = self.centralWidget()
        if root is not None:
            root.update()  # Glass: the backdrop goes or comes back
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

        nexus = themes.valid_skin(self.engine.mixer.skin) == "nexus"

        def add(theme_id: str, text: str, tip: str = "", theme=None) -> None:
            if nexus and theme is not None and themes.is_light_theme(theme):  # 0.12.2: the picker says Nexus stays dark
                text += " (Nexus stays dark)"
                tip = themes.NEXUS_DARK_ONLY
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(group)
            action.setChecked(chosen == theme_id)
            if tip:
                action.setToolTip(tip)
            action.triggered.connect(lambda _c=False, theme_id=theme_id: self.choose_theme(theme_id))

        from .ui_menus import heading
        heading(menu, "Your themes")
        for theme in themes.BUILT_IN.values():
            add(theme.id, theme.name, theme=theme)
        add(themes.SYSTEM, themes.SYSTEM_LABEL, "Dark or Light, following your desktop's own setting")
        custom = themes.custom_themes(self._themes_folder())
        if custom:
            menu.addSeparator()
            for theme in custom:
                add(theme.id, theme.name, theme=theme)
        if chosen.startswith(themes.CUSTOM_PREFIX) and not any(t.id == chosen for t in custom):  # not in the folder any more
            menu.addSeparator()
            missing = menu.addAction("An imported theme that is no longer in the themes folder (showing Dark)")
            missing.setCheckable(True)
            missing.setChecked(True)
            missing.setEnabled(False)
        heading(menu, "Manage")
        menu.addAction("&Import theme\u2026", self.import_theme)
        menu.addAction("&Export current theme\u2026", self.export_theme)
        if custom:
            remove = menu.addMenu("&Remove an imported theme")
            for theme in custom:
                remove.addAction(theme.name, partial(self.remove_theme, theme.id))
        more = menu.addAction("&Get more themes", partial(self.open_link, THEMES_URL))  # a link: no "…"
        more.setToolTip("Opens the theme collection on the project page in your browser: download a file, then Import theme")
        menu.setToolTipsVisible(True)

    def set_widget_dress(self, skin=None, theme=None) -> None:
        """Settings > Themes and skins > Desktop widgets: their own skin and theme ("" is the same as the window), shown at once."""
        mixer = self.engine.mixer
        if skin is not None:
            mixer.widget_skin = skin if skin in themes.SKINS else ""
        if theme is not None:
            mixer.widget_theme = theme
        desktop = getattr(self, "desktop", None)
        if desktop is not None:
            desktop.restyle()
        skin = themes.SKINS.get(mixer.widget_skin, "the window's skin")
        self.say(f"Desktop widgets: {skin}" + (f", {themes.resolve(mixer.widget_theme, self._system_is_dark(), self._themes_folder()).name}"
                                               if mixer.widget_theme else ", the window's theme") + ".")

    def dress_skin(self) -> None:
        """Put the skin's sheet on the mixer: the window's content and its status bar (again once they exist, at start-up)."""
        skin = themes.build_style(themes._current, themes.valid_skin(self.engine.mixer.skin))
        for part in (self.centralWidget(), self.statusBar()):
            if part is not None and part.styleSheet() != skin:
                part.setStyleSheet(skin)

    def choose_theme(self, theme_id: str) -> None:
        theme = self.apply_theme(theme_id)
        dark_only = " " + themes.NEXUS_DARK_ONLY if themes.valid_skin(self.engine.mixer.skin) == "nexus" and themes.is_light_theme(theme) else ""
        if theme_id == themes.SYSTEM:
            self.say(f"Theme: following your system (right now {theme.name}).{dark_only}")
        else:
            self.say(f"Theme: {theme.name}.{dark_only}")

    def import_theme_from(self, path) -> "themes.Theme":
        """Check a theme file, keep a copy in the themes folder and switch to it. Raises ThemeError."""
        folder = self._themes_folder()
        if folder is None:
            raise themes.ThemeError("Demo mode does not keep imported themes.")
        theme, notes = themes.load_file(path)
        problems = themes.contrast_problems(theme.colors)
        if problems:
            ask = ui_dialog.question(
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
            ui_dialog.warning(self, "Could not import the theme", str(exc))

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
                ui_dialog.warning(self, "Could not save the theme", str(exc))

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
