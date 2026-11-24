# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window: the top bar, the layouts, the meters' timer, saving, and everything that ties the cards together."""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from . import __version__, efficiency, logs, rawmic, report, update_install, sizing, themes, ui_icons as icons, update_check, whatsnew
from .engine import Engine
from .flow import FlowLayout, OverlapLayout
from .model import Channel, list_backups, Mixer, RECORDING, STREAM
from .ui_base import (
    _icon_button, _is_nexus, _is_tile, _label, AUTO_UPDATE_DELAY_MS, AUTOSAVE_MS, CLOSE_HINT, DEFAULT_SIZE, default_size,
    DISCORD_URL, ElidedLabel, FIRST_RUN_WIDTH, ISSUES_URL, LAYOUTS, MIX_HEADINGS, MIX_TAGS, PROJECT_URL, ROW_CELL_MIN, ROW_NAME_WIDTH,
    ROW_TOOLS_WIDTH, TILE_GAP, TOP_BAR_GAP, TOP_BAR_HEIGHT,
)
from .ui_channel import AppsBar, ChannelStrip
from .ui_widgets import DesktopWidgetManager
from .ui_menus import MenusMixin
from .ui_mini import MiniStrip
from .ui_mix import MixHeading, MixStrip
from .ui_themes import ThemesMixin
from .ui_tray import TrayMixin
from .ui_updating import _UpdateBridge, UpdatingMixin

log = logging.getLogger("sluice.ui")


class FirstRun(QFrame):
    """Shown until the first app is on a channel: three steps and a note about the demo. Nothing is routed until you add something."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.setObjectName("firstrun")
        self.window = window
        self.setFixedWidth(FIRST_RUN_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)
        head = QVBoxLayout()
        head.setSpacing(8)
        title = QLabel("Let's set up your mixer")
        title.setObjectName("title")
        head.addWidget(title)
        intro = QLabel("Three steps. You can change everything later, and nothing is routed until you add something.")
        intro.setWordWrap(True)
        intro.setObjectName("intro")
        head.addWidget(intro)
        layout.addLayout(head)
        self.buttons = []
        steps = (
            ("1", "Choose your microphone", "Pick the one you speak into and it goes on the Mic channel.", "Choose microphone", True,
             window.first_run_microphone),
            ("2", "Add your apps", "Games, Discord, your browser and music players each get a channel, so you can balance them "
             "separately.", "Add apps", False, window.first_run_apps),
            ("3", "Pick Sluice in your streaming app", "In OBS or Discord, choose “Sluice (Broadcast)” as the microphone. "
             "That is the processed sound.", "Show me how", False, window.first_run_streaming),
            ("4", "Make it look like yours", "Five skins and a choice of colours. Compare them side by side now, or change them later "
             "in Settings.", "Compare skins", False, window.compare_skins),
        )
        for number, name, text, button_text, primary, slot in steps:
            row = QHBoxLayout()
            row.setSpacing(16)
            badge = QLabel(number)
            badge.setObjectName("step" if primary else "stepoff")
            badge.setFixedSize(32, 32)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            body = QVBoxLayout()
            body.setSpacing(8)
            heading = QLabel(name)
            heading.setStyleSheet("font-weight: 600;")
            body.addWidget(heading)
            detail = _label(text, "hint", center=False)
            detail.setWordWrap(True)
            body.addWidget(detail)
            button = QPushButton(button_text)
            if primary:
                button.setObjectName("primary")
            button.setFixedHeight(40)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            row.addLayout(body, 1)
            layout.addLayout(row)
            self.buttons.append(button)
        layout.addStretch(1)
        self.demo_link = QLabel("Prefer to look around first? <a href=\"demo\">Try the demo</a>. "
                                "It changes nothing on your computer.")
        self.demo_link.setObjectName("hint")
        self.demo_link.setWordWrap(True)
        self.demo_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.demo_link.linkActivated.connect(lambda _href: window.first_run_demo())
        layout.addWidget(self.demo_link)


class MainWindow(MenusMixin, ThemesMixin, TrayMixin, UpdatingMixin, QMainWindow):
    def __init__(self, engine: Engine, config_file: Optional[Path] = None, notice: str = "") -> None:
        super().__init__()
        self.engine = engine
        self.config_file = config_file
        self._closed = False
        self._quitting = False
        # What's new: a start with no settings and no record is a new install (nothing has changed for them), so that
        # is written down now; an older record, or settings without one, means an update, shown once the window is open.
        self._config_existed = config_file is not None and config_file.exists()
        self._reconnecting = False
        self._tray = None
        self._tray_state = "idle"
        self._voice_until = 0.0
        self._whats_new_done = config_file is None  # demo mode: nothing to remember
        self._notes_dialog = None
        if config_file is not None and not self._config_existed and not whatsnew.read_marker(config_file):
            whatsnew.write_marker(config_file, __version__)
        self.controls = None  # set by attach_controls()
        self.setWindowTitle("Sluice")  # 0.12.0: the version is shown in About and at the foot of Settings only
        from . import fonts
        fonts.load()  # Inter and JetBrains Mono, for the Tile look (added for Sluice alone; nothing is installed)
        from . import ui_glass
        themes.set_see_through(False)
        themes.set_reduce_effects(self.engine.mixer.reduce_effects)
        if ui_glass.wants_see_through(self.engine.mixer):  # 0.11.7: Glass on KDE: decided before the window first appears
            ui_glass.make_see_through(self)
        self.apply_theme()  # before anything is built, so every widget (and the meters) starts in the chosen colours
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):  # "Match my system" follows the desktop while Sluice is running
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        self._keep_settings_file = False  # set after "Import settings": quitting must not overwrite what was imported
        self._build_menus()
        self._update_check = update_check.check  # replaced in tests
        self._update_bridge = _UpdateBridge()
        self._update_bridge.done.connect(self._show_update_result)
        self._update_bridge.progress.connect(self._update_progress)
        self._update_bridge.staged.connect(self._update_staged)
        self._update_bridge.quiet.connect(self._auto_update_staged)
        self._update_bridge.engine_rebuilt.connect(self._engine_rebuilt)
        self._stage_update = update_install.stage  # replaced in tests
        self._update_progress_dialog = None
        self._auto_update_started = False
        QTimer.singleShot(AUTO_UPDATE_DELAY_MS, self._auto_update_check)
        QTimer.singleShot(AUTO_UPDATE_DELAY_MS + 2000, self.offer_move_once)  # 0.12.0: once, for a copy in its download folder

        root = QWidget()
        root.setObjectName("root")
        root.setProperty("seethrough", themes.see_through())
        self.statusBar().setProperty("seethrough", themes.see_through())
        self.glass_backdrop = ui_glass.GlassBackdrop(self, root, self.statusBar())  # Glass: soft shapes behind the panes
        self.setCentralWidget(root)
        self.dress_skin()  # the theme was chosen before the content existed: the skin's sheet goes on it now
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # the window starts with nothing highlighted; Tab moves to the first control
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 24, 24, 8)
        outer.setSpacing(24)
        self._outer = outer
        self.top_bar = self._build_top_bar()
        outer.addWidget(self.top_bar)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        outer.addWidget(self.content, 1)
        self.apps_bar = AppsBar(engine, self)
        self.apps_bar.setFixedHeight(40)
        self.apps_button_holder.addWidget(self.apps_bar)
        self.strips: list = []
        self.mix_strips: list = []
        self.add_mix_button: Optional[QPushButton] = None
        self.first_run: Optional[FirstRun] = None
        self._plan = None
        self._plan_size = QSize(*DEFAULT_SIZE)
        self._relayouts = 0
        self._plan_ready = False
        self._told = set()  # one-time notes already shown this session
        self.layout_mode, self._dock = "columns", "right"
        self._refresh_plan()
        self._build_content()

        self.status_label = ElidedLabel(notice or "Ready", tip_when_cut=True)
        self.status_label.setObjectName("status")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.status_label, 1)
        self.buffer_offer = QPushButton("")
        self.buffer_offer.setFlat(True)
        self.buffer_offer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.buffer_offer.clicked.connect(self.accept_buffer_offer)
        self.buffer_offer.hide()
        self.statusBar().addPermanentWidget(self.buffer_offer)
        self.raw_mic_button = QPushButton("")
        self.raw_mic_button.setFlat(True)
        self.raw_mic_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.raw_mic_button.setStyleSheet(f"color: {themes.color('warn')};")
        self.raw_mic_button.clicked.connect(self.show_raw_mic)
        self.raw_mic_button.hide()
        self.statusBar().addPermanentWidget(self.raw_mic_button)
        self._apply_chrome()
        self.repopulate_devices()
        self._show_layout_choice()
        self.refresh_theme_widgets()
        root.setFocus(Qt.FocusReason.OtherFocusReason)

        self.desktop = DesktopWidgetManager(self)
        self.tracker = efficiency.Tracker()  # how much CPU and memory Sluice itself uses, for the bug report
        self.tracker.engine = engine
        efficiency.activate(self.tracker)
        self.tray_timer = QTimer(self)  # watches the microphone for the tray icon, only while the window is hidden in the tray
        self.tray_timer.timeout.connect(self._tray_tick)
        from .ui_tray import SuspendWatcher, is_wayland
        self.suspend_watcher = SuspendWatcher(self) if is_wayland() else None  # 0.11.7: minimize into the tray on Wayland too
        self._update_tray()  # the tray icon is there from the start if Sluice is set to run in the tray
        self.setMinimumSize(360, 300)  # smaller than the cards need: the compact list takes over below that (see sizing.py)
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(0)
        self._relayout_timer.timeout.connect(self._relayout)
        self.resize(*default_size(self._screen_area()))
        self._apply_step()
        self._plan_ready = True
        report.set_window_source(self._report_info)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._update_meters)
        self.meter_timer.start(33)
        self._meter_slow = 1.0
        self.engine_timer = QTimer(self)
        self.engine_timer.timeout.connect(self._tick_engine)
        self.engine_timer.start(500)
        # Settings save themselves: every few seconds, if (and only if) something changed since the last save.
        self._saved_snapshot: Optional[str] = self._snapshot() if config_file is not None and config_file.exists() else None
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start(AUTOSAVE_MS)
        self.desktop.restore()  # the widgets left on the desktop last time

    # ------------------------------------------------------------------ the top bar and the content
    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedHeight(TOP_BAR_HEIGHT)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, TOP_BAR_GAP)  # room between the buttons and the line under the bar (0.11.5)
        row.setSpacing(16)
        self.menu_button = _icon_button("menu", "Menu: mutes, layout, desktop widgets and help", 40)
        self.menu_button.clicked.connect(self.show_panel)  # 0.11.7: the ☰ panel (ui_panel.py), not the old nested menus
        row.addWidget(self.menu_button)
        self.settings_button = _icon_button("gear", "Settings: themes and skins, audio, startup, controllers and updates", 40)
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.clicked.connect(lambda _c=False: self.open_settings())
        row.addSpacing(-8)  # the two buttons sit together
        row.addWidget(self.settings_button)
        name = QLabel("Sluice")
        name.setObjectName("appname")
        self.app_name = name
        row.addWidget(name)
        demo = "Demo" in self.engine.io.label
        self.live_chip = QLabel("Demo mode" if demo else "\u25cf  Live")
        self.live_chip.setObjectName("demo" if demo else "livechip")
        self.live_chip.setToolTip(self.engine.io.label)
        row.addWidget(self.live_chip)
        row.addStretch(1)

        self.layout_frame = QFrame()
        self.layout_frame.setObjectName("segmented")
        segments = QHBoxLayout(self.layout_frame)
        segments.setContentsMargins(4, 4, 4, 4)
        segments.setSpacing(4)
        self.layout_buttons = {}
        for key, text, tip in (("columns", "Columns", "A card for each channel, faders standing up"),
                               ("rows", "Rows", "A line for each channel, sliders lying down")):
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"{text} layout")
            button.clicked.connect(lambda _c=False, key=key: self.set_layout(key))
            segments.addWidget(button)
            self.layout_buttons[key] = button
        row.addWidget(self.layout_frame)

        self.apps_button_holder = QHBoxLayout()
        self.apps_button_holder.setContentsMargins(0, 0, 0, 0)
        row.addLayout(self.apps_button_holder)

        self.status_chip = QFrame()
        self.status_chip.setObjectName("statuschip")
        self.status_chip.setFixedHeight(40)
        chip = QHBoxLayout(self.status_chip)
        chip.setContentsMargins(16, 0, 16, 0)
        chip.setSpacing(12)
        self.perf_dot = QLabel()
        self.perf_dot.setFixedSize(8, 8)
        self.perf_label = QLabel("")
        self.perf_label.setObjectName("dropouts")
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(16)
        self.rate_label = QLabel("")
        self.rate_label.setObjectName("ratetext")
        dropouts = QHBoxLayout()
        dropouts.setSpacing(8)
        dropouts.addWidget(self.perf_dot)
        dropouts.addWidget(self.perf_label)
        chip.addLayout(dropouts)
        chip.addWidget(divider)
        chip.addWidget(self.rate_label)
        self.status_divider = divider
        self._show_perf()
        row.addWidget(self.status_chip)
        return bar

    def _show_perf(self) -> None:
        """The health chip: dropouts first, the sample rate and the buffer small beside it, the explanation on hover."""
        text = self.engine.dropout_text()
        self.perf_label.setText(text)
        self.rate_label.setText(self.engine.rate_text())
        tip = (self.engine.dropout_tooltip() + "\n\n" + "Sample rate and buffer size: a smaller buffer means less delay, a "
               "larger one means fewer dropouts. Change it in Settings > Audio.")
        for widget in (self.status_chip, self.perf_label, self.rate_label):
            widget.setToolTip(tip)
        total, _ours = self.engine.dropout_counts()
        color = themes.color("live_fg") if total == 0 else themes.color("warn")
        self.perf_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

    def _apply_chrome(self) -> None:
        """The window's frame, the same in every skin (0.12.0: the Original skin and its menu bar are gone): the top bar, with the
        menus behind its ☰ and ⚙ buttons."""
        self.top_bar.setVisible(True)
        self._outer.setContentsMargins(24, 24, 24, 8)
        self._outer.setSpacing(24)

    def _restructure_for_skin(self) -> None:
        """A different look has different parts, not only different colours: rebuild the cards in it."""
        self._apply_chrome()
        self._tune_meter_rate()
        self._refresh_plan()
        self._apply_step()
        self._build_content()
        self._show_layout_choice()
        self._refresh_apps()
        self._show_perf()

    def _refresh_apps(self) -> None:
        self.apps_bar.refresh()

    def _refresh_plan(self) -> bool:
        """Work out how the window should be arranged at its size now; True when the cards have to be rebuilt for it."""
        size = self._plan_size
        plan = sizing.plan_for(size.width(), size.height(), self.engine.mixer.layout, themes.current_skin(), self._plan,
                               mixes=len(self.engine.mixer.mixes))
        changed = self._plan is None or (plan.mode, plan.dock) != (self._plan.mode, self._plan.dock)
        self._plan = plan
        self.layout_mode, self._dock = plan.mode, plan.dock
        return changed

    def _apply_step(self) -> None:
        """Show as much of the top bar as the width allows (the same few controls, in the same places, only fewer of them)."""
        if not hasattr(self, "live_chip") or self._plan is None:
            return
        step = self._plan.step
        compact, mini = step in ("compact", "mini"), step == "mini"
        self.live_chip.setVisible(not compact)
        self.rate_label.setVisible(not compact)
        self.status_divider.setVisible(not compact)
        self.apps_bar.setVisible(step in ("roomy", "standard"))
        self.app_name.setVisible(not mini)
        self.layout_frame.setVisible(not mini)
        self._outer.setContentsMargins(*self._margins_for(step))

    def _margins_for(self, step: str) -> tuple:
        return {"roomy": (24, 24, 24, 8), "standard": (24, 24, 24, 8), "compact": (16, 16, 16, 6), "mini": (10, 10, 10, 6)}[step]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._plan_size = event.size()
        if getattr(self, "_plan_ready", False):
            self._relayout_timer.start()

    def _report_info(self) -> dict:
        """What the bug report says about the window: its size, the screen, the arrangement and where the main parts are."""
        screen = self.screen()
        geometry = screen.geometry() if screen is not None else None
        plan = self._plan
        parts = [f"window            {self.width()}x{self.height()}"]

        def where(name: str, widget) -> None:
            if widget is None or not widget.isVisible():
                return
            top = widget.mapTo(self, widget.rect().topLeft())
            parts.append(f"{name:<18}x={top.x()} y={top.y()} {widget.width()}x{widget.height()}")

        where("top bar", getattr(self, "top_bar", None))
        scroll = getattr(self, "channel_scroll", None)
        where("channel area", scroll)
        if scroll is not None and scroll.isVisible():
            vertical, sideways = scroll.verticalScrollBar(), scroll.horizontalScrollBar()
            parts.append(f"{'':<18}content {scroll.widget().width()}x{scroll.widget().height()}; scrolls "
                         f"{vertical.maximum()} px down, {sideways.maximum()} px across")
        for strip in self.strips[:12]:
            where(f"card {strip.channel.id}", strip)
        for strip in self.mix_strips:
            where(f"mix {strip.mix.id}", strip)
        if getattr(self, "mini", None) is not None:
            where("compact list", self.mini)
        return {
            "width": self.width(), "height": self.height(), "fullscreen": self.isFullScreen(),
            "screen": f"{geometry.width()}x{geometry.height()}" if geometry is not None else "unknown",
            "scale": f"{screen.devicePixelRatio():g}" if screen is not None else "?",
            "step": plan.step if plan else "?", "mode": plan.mode if plan else "?", "dock": plan.dock if plan else "?",
            "chosen": self._chosen_layout(), "relayouts": self._relayouts,
            "skin_colors": bool(self.engine.mixer.skin_colors),
            "widgets": self._widgets_summary(),
            "minimize": self.minimize_detection(),
            "layout": "\n".join(parts),
        }

    def _relayout(self) -> None:
        """After the window changed size: arrange it for the new size (rebuilding the cards only if the arrangement changed)."""
        was_mini = self.layout_mode == "mini"
        changed = self._refresh_plan()
        self._apply_step()
        if changed:
            if self.layout_mode == "mini" and not was_mini and "mini" not in self._told:
                self._told.add("mini")
                self.say("The window is small, so Sluice shows a compact list. Make the window larger for the full cards.")
            self._relayouts += 1
            self._build_content()
            self._show_layout_choice()
            self.sync_from_model()

    def _build_mini(self) -> None:
        """The compact list, for a window too small for the cards. The cards still exist, hidden, so the
        tray, the controllers and the bug report see the same window; the list drives the same engine calls."""
        engine = self.engine
        self.mix_strips = [
            MixStrip(m, engine, self.toggle_recording_mix if m.id == RECORDING else None,
                     self.toggle_recording_mix if m.id == STREAM and not engine.mixer.has_recording_mix else None, rows=False)
            for m in engine.mixer.mixes]
        self.add_mix_button = next((s.add_button for s in self.mix_strips if s.add_button is not None), None)
        for strip in self.mix_strips:
            if strip.combo:
                strip.combo.about_to_show.connect(self._on_popup)
        self.channels_row = None
        self.mini = MiniStrip(self, tile=themes.current_skin() == "tile")
        self.channels_widget = self.mini
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.mini)
        self.channel_scroll = scroll
        self.content_layout.addWidget(scroll)
        self.rebuild_channels()
        self.repopulate_devices()
        self.refresh_theme_widgets()

    def _rebuild_mini(self) -> None:
        for strip in getattr(self, "_mini_hidden", []):
            strip.deleteLater()
        self.first_run = None
        self.strips = [ChannelStrip(c, self.engine, self, rows=False) for c in self.engine.mixer.channels]
        self._mini_hidden = list(self.strips) + list(self.mix_strips)
        for strip in self.strips:
            strip.refresh_sources()
        self.mini.rebuild()
        self.refresh_theme_widgets()

    def _build_content(self) -> None:
        """The channels and the two master cards, in the chosen layout. Rebuilt when the layout is switched."""
        for strip in getattr(self, "_mini_hidden", []):
            strip.deleteLater()  # the hidden cards behind the compact list, from before
        self._mini_hidden = []
        self.mini = None
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if self.layout_mode == "mini":
            self._build_mini()
            return
        rows = self.layout_mode == "rows"
        tray = _is_tile() and not rows
        bottom = self._dock == "bottom"
        tile_keys = _is_tile() and not rows  # Listen and Broadcast as short keys, stacked beside the tiles or side by side below them
        if tile_keys:
            from .ui_tile import MIX_KEY_OVERLAP  # here: ui_tile imports the channel cards, which import this module
        self.mix_strips = [
            MixStrip(m, self.engine, self.toggle_recording_mix if m.id == RECORDING else None,
                     self.toggle_recording_mix if m.id == STREAM and not self.engine.mixer.has_recording_mix else None,
                     rows=rows or (bottom and not tile_keys))
            for m in self.engine.mixer.mixes]
        self.add_mix_button = next((s.add_button for s in self.mix_strips if s.add_button is not None), None)
        for strip in self.mix_strips:
            if strip.combo:
                strip.combo.about_to_show.connect(self._on_popup)
        # Nexus and Calm: the floor paints each card's shadow (soft in Calm), and in Nexus the glow that follows its sound.
        floored = (_is_nexus(rows) or themes.current_skin() == "calm") and not rows  # the cards sit on a CardFloor
        if tray:  # the Tile look's keys sit in a tray
            from .ui_tile_paint import TileTray
            self.channels_widget = TileTray()
        elif floored:
            from .ui_nexus import CardFloor
            self.channels_widget = CardFloor(soft=not _is_nexus(rows))
        else:
            self.channels_widget = QWidget()
            self.channels_widget.setObjectName("channels")
        page = QHBoxLayout()
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing((8 if tray else 24))
        if rows:
            self.channels_row = QVBoxLayout(self.channels_widget)
            self.channels_row.setContentsMargins(0, 0, 8, 0)
            self.channels_row.setSpacing(16)
            scroll = QScrollArea()
        else:
            # The cards wrap onto new lines as the window narrows. A tile keeps room round itself for its shadows, so the tiles
            # overlap by that room: 28 px of tray shows between two keys.
            self.channels_row = FlowLayout(self.channels_widget, (TILE_GAP if tray else 24 if floored else 16))
            self.channels_row.setContentsMargins(*((10, 18, 10, 20) if tray else (14, 14, 14, 26) if floored else (0, 0, 8, 8)))
            scroll = QScrollArea()
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.channels_widget)
        self.channel_scroll = scroll
        if rows:
            left = QVBoxLayout()
            left.setSpacing(16)
            left.addWidget(self._row_headings())
            left.addWidget(scroll, 1)
            page.addLayout(left, 1)
            if bottom:
                masters = QHBoxLayout()
                masters.setSpacing(16)
                for strip in self.mix_strips:
                    masters.addWidget(strip, 1)
                masters.setContentsMargins(0, 0, 0, 0)
            else:
                masters = QVBoxLayout()
                masters.setSpacing(16)
                for strip in self.mix_strips:
                    masters.addWidget(strip, 1)
                holder = QWidget()
                holder.setFixedWidth(304)
                holder.setLayout(masters)
                masters.setContentsMargins(0, 0, 0, 0)
                page.addWidget(holder)
        elif bottom:
            page.addWidget(scroll, 1)
            if tile_keys:  # side by side, their faces 28 px apart (the clear room round them overlaps)
                masters = OverlapLayout(vertical=False, overlap=MIX_KEY_OVERLAP)
            else:
                masters = QHBoxLayout()
                masters.setSpacing(16)
            for strip in self.mix_strips:
                masters.addWidget(strip, 0 if tile_keys else 1)
            masters.setContentsMargins(0, 0, 0, 0)
        elif tile_keys:  # Listen and Broadcast stacked at the right, beside the tray
            page.addWidget(scroll, 1)
            masters = OverlapLayout(vertical=True, overlap=MIX_KEY_OVERLAP)  # faces 28 px apart, as the tiles are
            for strip in self.mix_strips:
                masters.addWidget(strip)
            holder = QWidget()
            holder.setLayout(masters)
            masters.setContentsMargins(0, 8, 0, 0)
            page.addWidget(holder)
        else:
            page.addWidget(scroll, 1)
            masters = QHBoxLayout()
            masters.setSpacing(24 if floored else 16)
            for strip in self.mix_strips:
                masters.addWidget(strip)
            if floored:
                from .ui_nexus import CardFloor
                holder = CardFloor("masters", soft=not _is_nexus(rows))
                masters.setContentsMargins(14, 14, 14, 26)
            else:
                holder = QWidget()
                masters.setContentsMargins(0, 0, 0, 16)
            holder.setLayout(masters)
            page.addWidget(holder)
            self._floor_mixes(holder)
        if bottom:  # narrow: Listen and Broadcast in a bar under the channels, everything still in view
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(12)
            column.addLayout(page, 1)
            bar = QWidget()
            bar.setObjectName("masterbar")
            bar.setLayout(masters)
            column.addWidget(bar)
            page = column
        wrapper = QWidget()
        wrapper.setLayout(page)
        self.content_layout.addWidget(wrapper)
        self.rebuild_channels()
        self.repopulate_devices()
        self.refresh_theme_widgets()

    def _screen_area(self):
        """The free area of the screen the window is on (or the main one), as (width, height), or None."""
        if QApplication.platformName() in ("offscreen", "minimal"):  # a virtual 800x600 screen (tests): not a real one to fit
            return None
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return None
        area = screen.availableGeometry()
        return area.width(), area.height()

    def _widgets_summary(self) -> str:
        """For the bug report: how many desktop widgets are open and how they are shown (KDE layer-shell, or why not)."""
        from . import desktop_place
        desktop = getattr(self, "desktop", None)
        count = len(desktop.open_widgets) if desktop is not None else 0
        if not count:
            return f"none open (they would be {desktop_place.status()})"
        skin, _colors = desktop.dressing()
        each = []
        for (kind, mix, channel), widget in desktop.open_widgets.items():
            name = "/".join(filter(None, [kind, mix, channel]))
            each.append(f"{name} ({'layer-shell' if widget.layered else 'window'}"
                        f"{', blur on' if getattr(widget, '_blurred', False) else ''})")
        own = f"; their own skin: {skin}" if skin else ""
        return f"{count} open, shown as {desktop_place.status()}{own}. Each: {', '.join(each)}"

    def _floor_mixes(self, holder) -> None:
        """The Nexus look: Listen and Broadcast glow on their floor with their sound, as the channel cards do."""
        from .ui_nexus import CardFloor
        if not isinstance(holder, CardFloor):
            return
        for strip in self.mix_strips:
            holder.add(strip, strip.ring.color if strip.ring is not None else themes.color("accent"))
            if strip.ring is not None:
                strip.ring.on_glow = partial(holder.set_glow, strip)

    def _floor_channels(self) -> None:
        from .ui_nexus import CardFloor
        floor = self.channels_widget
        if not isinstance(floor, CardFloor):
            return
        for strip in self.strips:
            floor.add(strip, strip.tint)
            if strip.ring is not None:
                strip.ring.on_glow = partial(floor.set_glow, strip)

    def _row_headings(self) -> QWidget:
        """The Rows layout's column headings: CHANNEL, LISTEN · you hear, BROADCAST · audience hears."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(24, 0, 32, 0)
        row.setSpacing(16)
        first = _label("CHANNEL", "tag", center=False)
        first.setFixedWidth(8 + ROW_NAME_WIDTH + 32 + 32 + 16 + 16 + ROW_TOOLS_WIDTH - 24)
        row.addWidget(first)
        for mix in self.engine.mixer.mixes:
            heading = MixHeading(mix.id, f"{MIX_TAGS.get(mix.id, mix.label.upper())} \u00b7 {MIX_HEADINGS.get(mix.id, mix.label.lower())}")
            heading.setMinimumWidth(ROW_CELL_MIN)
            row.addWidget(heading, 1)
        return box

    def refresh_theme_widgets(self) -> None:
        """Tell every widget that paints itself or sets icons that the colours changed."""
        for widget in self.findChildren(QWidget):
            refresh = getattr(widget, "refresh_theme", None)
            if refresh is not None:
                refresh()
        if hasattr(self, "menu_button"):
            self.menu_button.setIcon(icons.icon("menu", themes.color("text"), 18))
            self.settings_button.setIcon(icons.icon("gear", themes.color("text"), 18))
            self._show_perf()

    def set_layout(self, mode: str) -> None:
        if mode not in LAYOUTS:
            return
        self.engine.mixer.layout = mode
        if self._refresh_plan():
            self._apply_step()
            self._build_content()
        self._show_layout_choice()

    def _chosen_layout(self) -> str:
        """The layout chosen in the settings as it applies to the look in use (the compact list does not change the choice)."""
        mode = self.engine.mixer.layout
        return mode if mode in LAYOUTS else "columns"

    def _show_layout_choice(self) -> None:
        chosen = self._chosen_layout()
        for key, button in self.layout_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == chosen)
            button.blockSignals(False)
        for key, action in self.layout_actions.items():
            action.setChecked(key == chosen)
        if hasattr(self, "skin_colors_action"):
            self._show_skin_items()

    # ------------------------------------------------------------------ first run
    def _needs_first_run(self) -> bool:
        mixer = self.engine.mixer
        return "firstrun" not in mixer.hints_seen and not any(c.apps for c in mixer.channels) and self.config_file is not None

    def _update_first_run(self) -> None:
        wanted = self._needs_first_run()
        if not wanted and self.first_run is not None:
            if any(c.apps for c in self.engine.mixer.channels) and "firstrun" not in self.engine.mixer.hints_seen:
                self.engine.mixer.hints_seen.append("firstrun")  # an app is on a channel: this screen has done its job
            self.first_run.hide()
            self.first_run.deleteLater()
            self.first_run = None
        for strip in self.strips:
            strip.set_empty(wanted and not strip.channel.apps and strip.channel.id != "mic" and not strip.rows)
        if wanted and self.first_run is None and self.layout_mode == "columns":
            self.first_run = FirstRun(self)
            self.channels_row.insertWidget(0, self.first_run)

    def first_run_microphone(self) -> None:
        strip = next((s for s in self.strips if s.channel.id == "mic"), None) or (self.strips[0] if self.strips else None)
        if strip is not None:
            strip.add_menu.popup(strip.menu_button.mapToGlobal(strip.menu_button.rect().bottomLeft()))

    def first_run_apps(self) -> None:
        strip = next((s for s in self.strips if s.channel.id != "mic"), None)
        if strip is not None:
            strip._add_installed()

    def first_run_streaming(self) -> None:
        QMessageBox.information(
            self, "Pick Sluice in your streaming app",
            "In OBS, add an Audio Input Capture and choose \u201cSluice (Broadcast)\u201d. In Discord, open Voice & Video and "
            "choose it as the microphone. That is your mic and your apps together, after the effects you set up.\n\n"
            "To check it yourself, press \u201cHear Broadcast\u201d on the Listen card.")

    def first_run_demo(self) -> None:
        QMessageBox.information(
            self, "Try the demo",
            "The demo shows a full mixer with made-up sound and changes nothing on your computer.\n\n"
            "Close Sluice, then start it again with:  sluice --demo")

    # ------------------------------------------------------------------- menus
    # ------------------------------------------------------------------- settings files
    def _snapshot(self) -> str:
        return json.dumps(self.engine.mixer.to_dict(), sort_keys=True)

    def _autosave(self) -> None:
        if self._closed or self.config_file is None or self._keep_settings_file:
            return
        snapshot = self._snapshot()
        if snapshot == self._saved_snapshot:
            return
        try:
            self.engine.save_config(self.config_file, backups=True)
            self._saved_snapshot = self._snapshot()
            log.debug("settings saved automatically")
        except OSError as exc:  # try again next time; do not interrupt someone who is mixing
            log.warning("automatic save failed: %s", exc)

    def save_settings(self) -> None:
        if self.config_file is None:
            self.say("Demo mode: settings are not saved.")
            return
        try:
            self.engine.save_config(self.config_file, backups=True)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self._keep_settings_file = False
        self._saved_snapshot = self._snapshot()
        self.say(f"Settings saved to {self.config_file}.")

    def export_settings_to(self, path) -> None:
        self.engine.save_config(Path(path))
        self.say(f"Settings exported to {logs.short_path(path)}.")

    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", str(Path.home() / "sluice-settings.json"),
                                              "Settings (*.json)")
        if path:
            try:
                self.export_settings_to(path)
            except OSError as exc:
                QMessageBox.warning(self, "Could not export the settings", str(exc))

    def import_settings_from(self, path) -> None:
        """Check a settings file and make it the saved settings. It takes effect the next time Sluice starts."""
        import json
        import shutil

        if self.config_file is None:
            raise ValueError("Demo mode does not use saved settings.")
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"That file could not be read as settings: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("channels"), list) or not data["channels"] \
                or data.get("version") != Mixer.default().to_dict()["version"]:
            raise ValueError("That file does not look like Sluice settings.")
        if self.config_file.exists():
            shutil.copy2(self.config_file, self.config_file.with_name("config.before-import.json"))
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, self.config_file)
        self._keep_settings_file = True
        self.say("Settings imported. Close Sluice and start it again to use them.")

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", str(Path.home()), "Settings (*.json)")
        if not path:
            return
        try:
            self.import_settings_from(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Could not import the settings", str(exc))
            return
        QMessageBox.information(
            self, "Settings imported",
            "The settings are saved. Close Sluice and start it again to use them.\n\n"
            "Until then Sluice keeps what you have now, and it will not overwrite the imported file when you quit. "
            "Your previous settings were kept as config.before-import.json.")

    def _fill_restore_menu(self) -> None:
        self.restore_menu.clear()
        backups = list_backups(self.config_file) if self.config_file is not None else []
        if not backups:
            self.restore_menu.addAction("No earlier versions yet").setEnabled(False)
            return
        for path in backups:
            try:
                when = time.strftime("%b %d, %I:%M %p", time.strptime(path.stem[len("config-"):][:15], "%Y%m%d-%H%M%S"))
                count = len(json.loads(path.read_text()).get("channels", []))
                label = f"{when}  ({count} channels)"
            except (OSError, ValueError):
                label = path.stem
            self.restore_menu.addAction(label, partial(self.restore_backup, path))

    def restore_backup(self, path, confirm: bool = True) -> None:
        if confirm and QMessageBox.question(
                self, "Restore earlier settings",
                "Go back to these settings? Your current ones are kept as config.before-import.json.\n\n"
                "The change takes effect the next time Sluice starts.") != QMessageBox.StandardButton.Yes:
            return
        self._autosave()  # make sure what you have now is on disk first
        try:
            self.import_settings_from(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not restore", str(exc))
            return
        self.say("Earlier settings restored. Close Sluice and start it again to use them.")

    def reset_settings(self) -> None:
        """Put the settings back to how a fresh Sluice starts. The current ones are kept; it takes effect at the next start."""
        import shutil

        if self.config_file is None:
            self.say("Demo mode: there are no saved settings to reset.")
            return
        ask = QMessageBox.question(
            self, "Reset all settings",
            "Put every setting back to how a fresh Sluice starts?\n\nThat means the default channels, levels, effects, theme "
            "and options. Your effect presets and controller assignments are kept.\n\nYour current settings are kept as "
            "config.before-reset.json, and the change takes effect the next time Sluice starts.")
        if ask != QMessageBox.StandardButton.Yes:
            return
        self._autosave()  # what you have now is on disk first, so the copy below is the latest
        try:
            if self.config_file.exists():
                shutil.copy2(self.config_file, self.config_file.with_name("config.before-reset.json"))
            Mixer.default().save(self.config_file)
        except OSError as exc:
            QMessageBox.warning(self, "Could not reset the settings", str(exc))
            return
        self._keep_settings_file = True  # quitting must not write the old settings back over the fresh ones
        self.say("Settings reset. Close Sluice and start it again to use them. Your old settings are in config.before-reset.json.")

    def bring_to_front(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh_file_menu(self) -> None:
        from . import launcher

        self.launcher_action.setChecked(launcher.is_installed())
        self._refresh_background_menu()

    def set_close_action(self, mode: str) -> None:
        self.engine.mixer.close_action = mode
        if CLOSE_HINT not in self.engine.mixer.hints_seen:
            self.engine.mixer.hints_seen.append(CLOSE_HINT)  # they know the choice exists: no need for the first-close question
        self._update_tray()
        if mode == "quit":
            self.say("Closing the window will quit Sluice.")
        elif mode == "tray" and not self.tray_active:
            self.say("No system tray was found on this desktop, so closing the window will minimize it to the taskbar instead. "
                     "Use File > Quit to exit.")
        elif mode == "tray":
            self.say("Closing or minimizing the window will keep Sluice running in the system tray. Click its icon to bring "
                     "the window back; right-click it for Quit.")
        else:
            self.say("Closing the window will keep Sluice running, minimized to the taskbar. Use File > Quit to exit.")

    # ---------------------------------------------------------------- outside control
    def attach_controls(self, controls) -> None:
        self.controls = controls
        action = QAction("&MIDI controllers and Stream Deck\u2026", self.settings_menu)
        action.triggered.connect(lambda _checked=False: controls.show_dialog())
        self.settings_menu.insertAction(self.controllers_separator, action)
        self.controllers_heading.setVisible(True)

    def sync_from_model(self) -> None:
        """Show the model's current values (after something other than the mouse changed them)."""
        for strip in self.strips:
            strip.sync_from_model()
        for strip in self.mix_strips:
            strip.sync_from_model()
        if getattr(self, "mini", None) is not None:
            self.mini.sync_from_model()
        self._show_mic_state()  # a controller or `sluice ctl mic-mute` may have changed it
        self._refresh_tray_icon()
        self._sync_tray_timer()

    # ---------------------------------------------------------------- channels
    def rebuild_channels(self) -> None:
        if self.layout_mode == "mini":
            self._rebuild_mini()
            return
        rows = self.layout_mode == "rows"
        while self.channels_row.count():
            item = self.channels_row.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.first_run = None
        self.strips = [self._channel_strip(c, rows) for c in self.engine.mixer.channels]
        self.even_sources()
        for strip in self.strips:
            if rows:
                strip.setMaximumHeight(104)
            self.channels_row.addWidget(strip, 1 if rows else 0)
        add = QPushButton("+  Add channel")
        add.setObjectName("addchannel")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("Add a channel for another app or group of apps")
        add.clicked.connect(self.add_channel)
        if rows:
            add.setFixedHeight(48)
            self.channels_row.addWidget(add)
            self.channels_row.addStretch(0)
        else:
            add.setFixedSize(160, 56)
            self.channels_row.addWidget(add)
            self._floor_channels()
        self.refresh_theme_widgets()
        self._update_first_run()

    def _channel_strip(self, channel: Channel, rows: bool) -> "ChannelStrip":
        """A channel's card in the look in use: a tile in the Tile look (Columns), a ChannelStrip everywhere else."""
        if themes.current_skin() == "tile" and not rows:
            from .ui_tile import TileStrip
            return TileStrip(channel, self.engine, self)
        return ChannelStrip(channel, self.engine, self, rows=rows)

    def tile_mover(self):
        """What moves a tile when it is dragged by its header (the Tile look)."""
        if getattr(self, "_tile_mover", None) is None:
            from .ui_tile_move import TileMover
            self._tile_mover = TileMover(self)
        return self._tile_mover

    def commit_tile_order(self, order: list) -> None:
        """Keep the channel order a dragged tile left (it is saved with the settings)."""
        rank = {channel_id: i for i, channel_id in enumerate(order)}
        mixer = self.engine.mixer
        if [c.id for c in mixer.channels] == order:
            return
        mixer.channels.sort(key=lambda c: rank.get(c.id, len(rank)))
        self.strips.sort(key=lambda s: rank.get(s.channel.id, len(rank)))
        self.say("Channel order changed.")

    def move_tile(self, channel_id: str, delta: int) -> None:
        """Move a channel one place earlier or later (the tile's menu: the keyboard way to do what dragging does)."""
        ids = [c.id for c in self.engine.mixer.channels]
        if channel_id not in ids:
            return
        index = ids.index(channel_id)
        target = max(0, min(len(ids) - 1, index + delta))
        if target == index:
            return
        ids.insert(target, ids.pop(index))
        self.commit_tile_order(ids)
        self.rebuild_channels()
        strip = next((s for s in self.strips if s.channel.id == channel_id), None)
        if strip is not None:
            strip.setFocus(Qt.FocusReason.OtherFocusReason)

    def add_channel(self) -> None:
        text, ok = QInputDialog.getText(self, "New channel", "Name (for example Game, Music, Browser):")
        if ok and text.strip():
            self.engine.add_channel(text)
            self.rebuild_channels()

    def remove_channel(self, channel_id: str) -> None:
        self.engine.remove_channel(channel_id)
        self.rebuild_channels()
        self._refresh_apps()

    def even_sources(self) -> None:
        """0.12.0: the lists of sources are as tall as the longest one needs (one chip at least, two before they scroll), the same
        on every card, so the cards in a row stay the same height and short lists leave no empty band."""
        cards = [s for s in self.strips if not s.rows and hasattr(s, "sources_needed")]
        if cards:
            height = max(s.sources_needed() for s in cards)
            for strip in cards:
                strip.set_sources_height(height)

    def refresh_sources(self) -> None:
        for strip in self.strips:
            strip.refresh_sources()
        self._refresh_apps()
        self._update_first_run()

    # ----------------------------------------------------------------- devices
    def repopulate_devices(self) -> None:
        for strip in self.mix_strips:
            strip.populate_devices()

    def _on_popup(self) -> None:
        self.engine.refresh_devices()
        self.repopulate_devices()

    # ------------------------------------------------------------------ timers
    def _update_meters(self) -> None:
        levels = self.engine.sample_levels()
        for strip in self.strips:
            loudest = 0.0
            for mix_id, meter in strip.meters.items():
                level = levels.get(f"ch:{strip.channel.id}:{mix_id}", 0.0)
                meter.push(level)
                loudest = max(loudest, level)
                fader = strip.faders[mix_id]
                if fader._reveal:  # the waveform is only fed while someone is looking at it
                    fader.feed(level)
            if strip.ring is not None:
                strip.ring.push(loudest, self._meter_slow)
            after = getattr(strip, "after_meters", None)
            if after is not None:  # a tile: its clip note and the app meters of a folded-out tile
                after(loudest)
        for strip in self.mix_strips:
            level = levels.get(f"mix:{strip.mix.id}", 0.0)
            strip.meter.push(level)
            if strip.fader._reveal:
                strip.fader.feed(level)
            if strip.ring is not None:
                strip.ring.push(level, self._meter_slow)
        if getattr(self, "mini", None) is not None and self.mini.tile:
            self.mini.push_levels(levels)
        self.tracker.meter_tick()
        self._refresh_tray_icon()

    def _begin_reconnect(self) -> None:
        from . import reconnect

        self._reconnecting = True
        self._reconnect_waited = 0.0
        self.say("The audio server (PipeWire) stopped. Waiting for it to come back: Sluice will then restart itself.")
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(int(reconnect.POLL_SECONDS * 1000))
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._reconnect_timer.start()

    def _try_reconnect(self) -> None:
        from . import reconnect

        self._reconnect_waited += reconnect.POLL_SECONDS
        if reconnect.server_is_back():
            self._reconnect_timer.stop()
            self.shutdown()  # saves the settings first
            reconnect.restart_self()
        elif self._reconnect_waited > reconnect.GIVE_UP_SECONDS:
            self._reconnect_timer.stop()
            self.say("The audio server did not come back. Start the audio server, then restart Sluice.")

    def _tick_engine(self) -> None:
        if self.engine.server_lost and not self._reconnecting and not self._closed:
            self._begin_reconnect()
        logs.heartbeat()
        self.tracker.sample()
        self.tracker.maybe_write()
        changed = self.engine.tick()
        if "devices" in changed:
            self.repopulate_devices()
        if changed:
            self.refresh_sources()
        errors = self.engine.take_errors()
        if errors:
            self.status_label.setText(errors[-1])
        for notice in self.engine.take_notices():
            self.status_label.setText(notice)
        text = self.engine.dropout_text()
        if text != self.perf_label.text():  # the tooltip explains the number, so it only changes when the number does
            self._show_perf()
        self._update_buffer_offer()
        self._update_raw_mic()

    def _update_raw_mic(self) -> None:
        """A warning in the status bar while an app listens to the raw microphone instead of the one with effects."""
        warnings = self.engine.raw_mic
        self.raw_mic_button.setVisible(bool(warnings))
        if warnings:
            app, text = next(iter(warnings.items()))
            more = f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else ""
            self.raw_mic_button.setText(rawmic.short(app) + more)
            self.raw_mic_button.setToolTip(text + "\nClick for details.")

    def show_raw_mic(self) -> None:
        warnings = dict(self.engine.raw_mic)
        if not warnings:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Raw microphone")
        box.setText("\n\n".join(warnings.values()))
        box.setInformativeText("Nothing is wrong with Sluice. If that is what you want, you can stop the reminder.")
        dismiss = box.addButton("Don't remind me about " + ("these apps" if len(warnings) > 1 else next(iter(warnings))),
                                QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is dismiss:
            for app in warnings:
                self.engine.dismiss_raw_mic(app)
            self._update_raw_mic()

    def _update_buffer_offer(self) -> None:
        bigger = self.engine.larger_buffer_offer()
        self.buffer_offer.setVisible(bigger is not None)
        if bigger is not None:
            self.buffer_offer.setText(f"Try a larger buffer ({bigger})")
            self.buffer_offer.setToolTip(f"Dropouts keep coming. This saves {bigger} frames as the audio buffer (now "
                                         f"{self.engine.io.blocksize}); it is used the next time Sluice starts. "
                                         "More room for slow moments, a little more delay.")

    def accept_buffer_offer(self) -> None:
        bigger = self.engine.larger_buffer_offer()
        if bigger is not None:
            self.set_buffer(bigger)
            self._refresh_buffer_menu()
        self._update_buffer_offer()

    # ------------------------------------------------------------------- help
    def say(self, text: str) -> None:
        self.status_label.setText(text)

    def hint_missing_part(self, key: str) -> bool:
        """0.12.0: the moment an optional part would be used (Glass blur, KDE widgets, VST3) and it is missing, say so once, with
        where to find the command that installs it. Returns whether the hint was shown."""
        from . import setup_check
        seen = self.engine.mixer.hints_seen
        tag = f"setup-{key}"
        if tag in seen or key not in setup_check.BY_KEY:
            return False
        result = setup_check.check(setup_check.BY_KEY[key])
        if not result.missing:
            return False
        seen.append(tag)
        self.say(f"{result.part.name} is missing: {result.reason}. Settings > Setup check has the command that installs it.")
        return True

    def show_about(self) -> None:
        import platform

        from PySide6 import __version__ as pyside_version

        QMessageBox.about(
            self, "About Sluice",
            f"<b>Sluice {__version__}</b><br>An open-source virtual audio mixer for PipeWire.<br><br>"
            f"License: GPL-3.0-or-later<br>Python {platform.python_version()}, PySide6 {pyside_version}<br>"
            f"Log: {logs.short_path(logs.log_path())}<br><br>"
            f'<a href="{PROJECT_URL}">Project page</a> &nbsp;·&nbsp; <a href="{DISCORD_URL}">Join the Discord</a> '
            f'&nbsp;·&nbsp; <a href="{ISSUES_URL}">Report a problem</a>',
        )

    def check_for_updates(self) -> None:
        self.say("Checking for updates\u2026")
        check = self._update_check

        def work() -> None:
            self._update_bridge.done.emit(check(__version__))

        threading.Thread(target=work, name="sluice-update-check", daemon=True).start()

    # -------------------------------------------------------------- what's new
    def show_notes(self, title: str, heading: str, markdown: str, main_label: str = "", main_url: str = "",
                   action=None, action_label: str = "") -> None:
        from .ui_whatsnew import NotesDialog

        self._notes_dialog = NotesDialog(title, heading, markdown, main_label, main_url, self,
                                         action=action, action_label=action_label)
        self._notes_dialog.open()  # does not block: a start-up notice must never hold up the window

    def show_whats_new(self) -> None:
        notes = whatsnew.notes_for(__version__) or "No release notes are included with this build. See the releases page for the list of changes."
        self.show_notes(f"What's new in Sluice {__version__}", f"What's new in Sluice {__version__}", notes)

    def _maybe_show_whats_new(self) -> None:
        """Once after an update, when the window is really on screen (a start minimized at login waits until it is opened)."""
        if self._whats_new_done or self._closed or self.config_file is None:
            return
        if not self.isVisible() or self.isMinimized():
            return
        self._whats_new_done = True
        marker = whatsnew.read_marker(self.config_file)
        text = whatsnew.what_to_show(self._config_existed, marker, __version__)
        whatsnew.write_marker(self.config_file, __version__)
        if text:
            from . import spectral
            offer = update_install.engine_rebuild_offer(update_install.install_root(), spectral.RUST_VERSION, spectral.RUST_EXPECTED,
                                                        spectral.rust_is_older())
            if offer:  # 0.11.6: the update shipped a newer Rust engine than the one built here
                self.show_notes(f"What's new in Sluice {__version__}", f"Sluice was updated to {__version__}. What's new:",
                                f"{text}\n\n---\n\n*{offer}*", action=self.rebuild_engine, action_label="Rebuild the engine")
            else:
                self.show_notes(f"What's new in Sluice {__version__}", f"Sluice was updated to {__version__}. What's new:", text)

    def engine_rebuild_state(self) -> tuple:
        """(whether Settings > Updates can offer "Rebuild the audio engine", the line under it)."""
        from . import spectral
        root = update_install.install_root()
        last = update_install.last_rebuild()
        tail = ""
        if last is not None:
            tail = " Last try: " + ("it worked." if last["result"] == "ok" else f"{last['result']}.")
        if root is None or not (root / "rust" / "sluice_dsp").is_dir():
            return False, "This copy of Sluice has no engine source to build (it was not installed from its folder)."
        if not shutil.which("cargo"):
            return False, "Rust is not installed (install it, then rebuild)."
        if spectral.RUST_VERSION and spectral.rust_is_older():
            return True, f"Yours is {spectral.RUST_VERSION}; this Sluice comes with {spectral.RUST_EXPECTED}: rebuild for the fixes since.{tail}"
        if spectral.RUST_VERSION:
            return True, f"Engine {spectral.RUST_VERSION}, up to date. Rebuild if it misbehaves.{tail}"
        return True, f"The Rust engine is not in use: build it for less CPU.{tail}"

    def rebuild_engine(self) -> None:
        """Rebuild the Rust engine in the background (offered after an update that ships a newer one); say how it went."""
        root = update_install.install_root()
        if root is None:
            return
        self.say("Rebuilding the audio engine… (a minute or two; Sluice keeps working)")
        bridge = self._update_bridge

        def work() -> None:
            problem = update_install.rebuild_engine(root)
            bridge.engine_rebuilt.emit(problem)

        threading.Thread(target=work, name="sluice-engine-rebuild", daemon=True).start()

    def _engine_rebuilt(self, problem: str) -> None:
        self.say(f"The audio engine could not be rebuilt: {problem}." if problem
                 else "The audio engine was rebuilt. Restart Sluice to use it (File > Quit, then open it again).")

    def _show_update_result(self, result) -> None:
        if result.status == "available":
            self.say(f"Version {result.latest} is available (you have {result.current}).")
            problem = update_install.offer_problem(update_install.install_root(), result)
            notes = result.notes or "No release notes were published for this version."
            if problem:
                notes += f"\n\n---\n\n*Sluice cannot install this by itself: {problem}*"
            self.show_notes(
                "Update available", f"Sluice {result.latest} is available. You are running {result.current}.", notes,
                "Open download page" if result.page else "", result.page,
                action=None if problem else partial(self.start_update, result), action_label="Update now")
        elif result.status == "up_to_date":
            self.say(f"Sluice {result.current} is the latest version.")
            QMessageBox.information(self, "Up to date", f"You are running the latest version ({result.current}).")
        elif result.status == "not_configured":
            self.say(f"Sluice {result.current}. Update checking is not set up yet.")
            QMessageBox.information(
                self, "Check for updates",
                f"You are running Sluice {result.current}.\n\nThis build has no download address to check yet. "
                "Until there is one, new versions arrive as a new zip file.")
        else:
            self.say(f"Could not check for updates: {result.message}")
            QMessageBox.warning(self, "Could not check for updates", result.message or "Unknown error.")

    def save_report_to(self, path) -> None:
        written = report.write_report(Path(path))
        self.status_label.setText(f"Bug report saved to {logs.short_path(written)}. Your user name and computer name are replaced; look it over before sharing it.")

    def save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save bug report", str(Path.home() / report.default_name()), "Text files (*.txt)"
        )
        if path:
            try:
                self.save_report_to(path)
            except Exception as exc:  # a file problem, or something unexpected while building the report
                log.warning("could not save the bug report: %s", exc, exc_info=True)
                QMessageBox.warning(
                    self, "Could not save the report",
                    f"The report could not be saved to:\n{path}\n\n{type(exc).__name__}: {exc}\n\n"
                    "Try another folder, or run  sluice --report  in a terminal. Details are in the log "
                    "(File > Open folder).")

    def mark_glitch(self) -> None:
        self.say(self.engine.mark_glitch())

    def open_log_folder(self) -> None:
        folder = logs.state_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ---------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if report._window_source == self._report_info:
            report.set_window_source(None)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            try:
                hints.colorSchemeChanged.disconnect(self._on_system_scheme_changed)
            except (RuntimeError, TypeError):
                pass
        if self._tray is not None:
            self._tray.hide()  # no ghost icon after Sluice is gone
        self.meter_timer.stop()
        self.tray_timer.stop()
        self.engine_timer.stop()
        self.autosave_timer.stop()
        self.desktop.close_all()  # they stay in the saved list and come back next time
        self.tracker.write()  # so `sluice --report` can show how this session went
        if efficiency.ACTIVE is self.tracker:
            efficiency.activate(None)
        if self.controls is not None:
            self.controls.close()
        self.engine.shutdown(save_to=None if self._keep_settings_file else self.config_file)

    def _should_ask_close_choice(self, saving: bool) -> bool:
        """The first time the window is closed with the default setting (Quit), on a desktop with a system tray, ask once whether to
        quit or keep running in the tray, so nobody loses the mixer by accident or never learns the tray exists."""
        mixer = self.engine.mixer
        return (mixer.close_action == "quit" and CLOSE_HINT not in mixer.hints_seen and not self._quitting and not self._closed
                and not saving and self.config_file is not None and self.isVisible() and self._tray_possible())

    def _ask_close_choice(self) -> bool:
        """Ask what closing should do. True: carry on closing (the setting is now what they chose, or a quit this once); False: stay."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Close Sluice?")
        box.setText("Quit Sluice, or keep it running in the system tray?")
        box.setInformativeText("In the tray the mixer keeps working while the window is out of the way, and you can mute your microphone "
                               "from the tray icon. You can change this any time in Settings > Running in the background.")
        tray = box.addButton("Keep running in the tray", QMessageBox.ButtonRole.AcceptRole)
        quit_button = box.addButton("Quit Sluice", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        remember = QCheckBox("Do not ask again when I choose Quit")
        box.setCheckBox(remember)
        box.setDefaultButton(tray)
        box.exec()
        clicked = box.clickedButton()
        if clicked is tray:
            self.set_close_action("tray")  # remembered: closing now keeps it running in the tray from here on
            return True
        if clicked is quit_button:
            if remember.isChecked():
                self.set_close_action("quit")  # remembered: the question never comes again
            return True
        return False

    def closeEvent(self, event) -> None:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        saving = bool(app is not None and app.isSavingSession())  # True during a logout or shutdown: always let it close
        if self._should_ask_close_choice(saving) and not self._ask_close_choice():
            event.ignore()  # they cancelled: the window stays
            return
        if self.engine.mixer.close_action in ("minimize", "tray") and not self._quitting and not self._closed and not saving:
            event.ignore()
            if self.tray_active:
                self.hide()
                self.say("Sluice is still running in the system tray.")
            else:
                self.showMinimized()
                self.say("Sluice is still running. Click it in the taskbar to bring it back, or use File > Quit.")
            return
        self.shutdown()
        event.accept()

    # Nobody can see the meters while the window is hidden or minimised, so they stop (and cost nothing).
    def _set_meters_running(self, on: bool) -> None:
        if self._closed:
            return
        if on and not self.meter_timer.isActive():
            self.meter_timer.start(self._meter_interval())
        elif not on and self.meter_timer.isActive():
            self.meter_timer.stop()
        self._window_state_changed()

    def _meter_interval(self) -> int:
        """33 ms normally; 66 ms in Nexus while this window is not the one in use (it is still live, for a second screen beside a game)."""
        slow = themes.current_skin() == "nexus" and self.isVisible() and not self.isActiveWindow()
        self._meter_slow = 2.0 if slow else 1.0
        return 66 if slow else 33

    def _tune_meter_rate(self) -> None:
        if self.meter_timer.isActive():
            wanted = self._meter_interval()
            if self.meter_timer.interval() != wanted:
                self.meter_timer.setInterval(wanted)

    def showEvent(self, event) -> None:
        if themes.see_through() and not getattr(self, "_blur_asked", False) and self.windowHandle() is not None:
            from . import ui_glass
            self._blur_asked = ui_glass.blur_window(self)  # KWin blurs the wallpaper behind the see-through window
        if self.suspend_watcher is not None and not getattr(self, "_suspend_watched", False) and self.windowHandle() is not None:
            self.suspend_watcher.watch(self.windowHandle())
            self._suspend_watched = True
        self._set_meters_running(not self.isMinimized())
        if not self._whats_new_done:
            QTimer.singleShot(700, self._maybe_show_whats_new)
        super().showEvent(event)

    def _minimize_to_tray(self) -> None:
        if self.tray_active and self.isMinimized() and not self._closed:
            self.hide()
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)  # so showing it again is not minimized

    def hideEvent(self, event) -> None:
        self._set_meters_running(False)
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.ActivationChange and not self._closed:
            self._tune_meter_rate()
            if self.suspend_watcher is not None:
                self.suspend_watcher.note_active()  # in use until now (a minimize takes the activation away as it happens)
        if event.type() == QEvent.Type.WindowStateChange:
            self._set_meters_running(self.isVisible() and not self.isMinimized())
            if self.tray_active and self.isMinimized() and not self._closed:
                QTimer.singleShot(0, self._minimize_to_tray)
        super().changeEvent(event)
