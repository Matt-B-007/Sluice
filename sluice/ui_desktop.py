"""Desktop widgets: small borderless windows you can leave on the desktop (a microphone mute button, a volume dial, a compact list of
channels, and since 0.11.5 one channel or one mix with its sliders) so the big window can stay closed. They draw themselves in the look
in use and ask the engine for the shared meter reading, a few times a second, only while they are shown and only repaint when something
they show has changed.

Where they go is ``desktop_place``: they snap to the screen's edges and to each other, remember a place on each screen, and on KDE
Plasma under Wayland they are real desktop-widget windows (layer-shell), so they can place themselves and stay on top."""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from . import desktop_place, themes

from .model import MAX_DESKTOP_WIDGETS as MAX_WIDGETS, clean_widget_spec as clean_spec  # noqa: E402  (the model keeps them: it has no Qt)

TICK_MS = 100
DIAL_SIZE = 104
MIC_SIZE = 84


def _key(spec: dict) -> tuple:
    return (spec["kind"], spec.get("mix"), spec.get("channel"))


class DesktopWidget(QWidget):
    """The common part: no frame, drag it anywhere, click does the one thing it is for, right-click for Keep on top and Close."""

    def __init__(self, manager, spec: dict) -> None:
        super().__init__()
        self.manager = manager
        self.window_ = manager.window
        self.engine = manager.window.engine
        self.spec = spec
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.on_top = True
        self._state = None
        self._press = None
        self._ready = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.settle_timer = QTimer(self)  # a moment after it stops moving, it snaps into place and its place is remembered
        self.settle_timer.setSingleShot(True)
        self.settle_timer.setInterval(220)
        self.settle_timer.timeout.connect(self.settle)
        self._drag_from = None
        self.layered = False
        self.setAccessibleName(self.title())
        self.setWindowTitle(f"{desktop_place.RULE_TITLE}: {self.title()}")  # a KWin rule finds the widgets by this

    # -- what the subclasses give
    def title(self) -> str:
        return "Sluice widget"

    def state(self) -> tuple:
        return ()

    def act(self) -> None:
        pass

    # -- the shared behaviour
    def tick(self) -> None:
        state = self.state()
        if state != self._state:
            self._state = state
            self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ready = True
        self.tick()
        if not self.timer.isActive():
            self.timer.start(TICK_MS)

    def hideEvent(self, event) -> None:
        self.timer.stop()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._ready:
            self.spec["x"], self.spec["y"] = self.x(), self.y()
            self.settle_timer.start()

    # -- where it is
    def position(self) -> QPoint:
        return QPoint(self.spec.get("x") or 0, self.spec.get("y") or 0) if self.layered else self.pos()

    def place(self, x: int, y: int) -> None:
        """Put the widget at (x, y) on the desktop: through layer-shell margins on KDE Wayland, else an ordinary move (which Wayland
        may ignore for an ordinary window: then it stays where the desktop put it)."""
        if self.layered:
            screen = self._screen_at(QPoint(x, y))
            origin = (screen.geometry().x(), screen.geometry().y()) if screen is not None else (0, 0)
            desktop_place.layer_shell().place(self.windowHandle(), x, y, origin)
            self.spec["x"], self.spec["y"] = int(x), int(y)
            self.settle_timer.start()
        else:
            self.move(x, y)

    def _screen_at(self, point: QPoint):
        app = QApplication.instance()
        screen = app.screenAt(point) if app is not None else None
        return screen or self.screen() or (app.primaryScreen() if app is not None else None)

    def settle(self) -> None:
        """It has stopped moving: snap to the screen's edges and to the other widgets, and remember the place on this screen."""
        here = self.position()
        screen = self._screen_at(here + QPoint(self.width() // 2, self.height() // 2))
        if screen is None:
            return
        area = screen.availableGeometry()
        others = [(w.position().x(), w.position().y(), w.width(), w.height()) for w in self.manager.open_widgets.values()
                  if w is not self and w.isVisible()]
        x, y = desktop_place.snap((here.x(), here.y(), self.width(), self.height()), (area.x(), area.y(), area.width(), area.height()),
                                  others)
        if (x, y) != (here.x(), here.y()):
            self.settle_timer.blockSignals(True)
            self.place(x, y)
            self.settle_timer.blockSignals(False)
            self.settle_timer.stop()
        desktop_place.remember(self.spec, screen.name() or "screen", x, y)

    # -- pressing, dragging and clicking
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._drag_from = (self._press, self.position())

    def mouseMoveEvent(self, event) -> None:
        point = event.globalPosition().toPoint()
        if self._press is not None and (point - self._press).manhattanLength() > 6:
            self._press = None
            if not self.layered:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemMove()  # the desktop moves it (the only way on Wayland for an ordinary window)
                    return
        if self._press is None and self._drag_from is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            start, origin = self._drag_from  # a layer-shell widget (or a desktop with no system move) is moved by Sluice
            moved = origin + (point - start)
            self.place(moved.x(), moved.y())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            dragged = self._press is None and self._drag_from is not None
            self._drag_from = None
            if self._press is not None:
                self._press = None
                self.act()
                self.tick()
            elif dragged:
                self.settle()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        top = menu.addAction("Keep on top")
        top.setCheckable(True)
        top.setChecked(self.on_top)
        top.triggered.connect(self.set_on_top)
        if desktop_place.kde_wayland(platform=QApplication.platformName() or "") and not self.layered:
            menu.addAction("Keep widgets on top on KDE…", self.manager.offer_kwin_rule)
        menu.addAction("Close this widget", lambda: self.manager.close_spec(self.spec))
        menu.exec(event.globalPos())

    def set_on_top(self, on: bool) -> None:
        self.on_top = bool(on)
        if self.layered:  # a layer-shell widget is always on the top layer
            return
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.on_top)
        self.show()

    def attach_layer_shell(self) -> bool:
        """KDE Plasma on Wayland: make this window a desktop widget on the top layer before it is first shown."""
        shell = desktop_place.layer_shell()
        if not shell.available or self.layered:
            return self.layered
        self.winId()  # the native window, not yet shown
        handle = self.windowHandle()
        self.layered = handle is not None and shell.attach(handle)
        return self.layered

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.settle_timer.stop()
        if self.layered and self.windowHandle() is not None:
            desktop_place.layer_shell().forget(self.windowHandle())
        super().closeEvent(event)

    def _colors(self) -> tuple:
        return QColor(themes.color("panel")), QColor(themes.color("text")), QColor(themes.color("accent"))


def _mix_label(engine, mix_id) -> str:
    mix = next((m for m in engine.mixer.mixes if m.id == mix_id), None)
    return mix.label if mix is not None else "Listen"


class MicWidget(DesktopWidget):
    """A round mute button for the microphone, glowing with the level while it is live."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        self.setFixedSize(MIC_SIZE, MIC_SIZE)
        self.setToolTip("Click to mute or unmute your microphone. Drag to move. Right-click for more.")

    def title(self) -> str:
        return "Microphone mute"

    def _level(self) -> float:
        levels = self.engine.sample_levels(0.05)
        mix = self.engine.mixer.mixes[0].id if self.engine.mixer.mixes else "monitor"
        return max((levels.get(f"ch:{c.id}:{mix}", 0.0) for c in self.engine.mixer.channels if c.devices), default=0.0)

    def state(self) -> tuple:
        muted = self.engine.mic_muted
        return (muted, 0 if muted else round(self._level() * 12))

    def act(self) -> None:
        self.window_.toggle_mic_mute()

    def paintEvent(self, _event) -> None:
        if themes.current_look() == "tile":
            self._paint_key()
            return
        muted, glow = self._state or (False, 0)
        panel, text, accent = self._colors()
        red = QColor(themes.color("mute_fg") if muted else "#2bd48a")
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(panel)
        p.drawEllipse(rect)
        ring = QColor(red)
        ring.setAlpha(110 + min(145, glow * 12))
        p.setPen(QPen(ring, 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect.adjusted(2, 2, -2, -2))
        p.setPen(QPen(text if not muted else red, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx, cy = self.width() / 2, self.height() / 2
        p.drawRoundedRect(QRectF(cx - 6, cy - 17, 12, 22), 6, 6)
        p.drawArc(QRectF(cx - 12, cy - 9, 24, 22), 200 * 16, 140 * 16)
        p.drawLine(QPointF(cx, cy + 13), QPointF(cx, cy + 19))
        if muted:
            p.setPen(QPen(red, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx - 16, cy + 17), QPointF(cx + 16, cy - 19))
        p.end()


    def _paint_key(self) -> None:
        """The Tile look: a square raised key with the microphone in a tinted well; pushed in, red, while muted."""
        from . import look_tile, ui_tile_paint as ui_tile

        muted, glow = self._state or (False, 0)
        pc = look_tile.paint_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        skirt = 2 if muted else ui_tile.SKIRT  # a muted key is pushed in: it sits lower, with less of its edge showing
        rect = QRectF(4, 2 + ui_tile.SKIRT - skirt, self.width() - 8, self.height() - 10 - (ui_tile.SKIRT - skirt))
        ui_tile.paint_surface(p, rect, self.devicePixelRatioF(), radius=18, skirt=skirt)
        face = rect.adjusted(0, 0, 0, -skirt)
        tint = QColor(pc["red"] if muted else "#4c8dff")
        well = QRectF(face.center().x() - 22, face.center().y() - 22, 44, 44)
        fill = QColor(tint)
        fill.setAlphaF(0.16)
        p.setPen(QPen(QColor(tint.red(), tint.green(), tint.blue(), 90), 1))
        p.setBrush(fill)
        p.drawRoundedRect(well, 12, 12)
        if not muted and glow:  # the level, as a ring that brightens round the well
            ring = QColor("#2fcf7a")
            ring.setAlpha(min(255, 60 + glow * 16))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ring, 2))
            p.drawRoundedRect(well.adjusted(-3, -3, 3, 3), 14, 14)
        p.setPen(QPen(tint, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = well.center().x(), well.center().y()
        p.drawRoundedRect(QRectF(cx - 4.5, cy - 12, 9, 15), 4.5, 4.5)
        p.drawArc(QRectF(cx - 9, cy - 6, 18, 15), 200 * 16, 140 * 16)
        p.drawLine(QPointF(cx, cy + 9), QPointF(cx, cy + 13))
        if muted:
            p.drawLine(QPointF(cx - 12, cy - 12), QPointF(cx + 12, cy + 12))
        p.end()


class DialWidget(DesktopWidget):
    """A volume dial for a mix's main level (or one channel in that mix): the wheel turns it, a click mutes it."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        self.setFixedSize(DIAL_SIZE, DIAL_SIZE)
        self.setToolTip("Scroll to change the level (hold Shift for small steps). Click to mute or unmute. Drag to move.")

    def _target(self):
        channel_id = self.spec.get("channel")
        if channel_id:
            return next((c for c in self.engine.mixer.channels if c.id == channel_id), None)
        return next((m for m in self.engine.mixer.mixes if m.id == self.spec.get("mix")), None) or (
            self.engine.mixer.mixes[0] if self.engine.mixer.mixes else None)

    def _mix_id(self) -> str:
        return self.spec.get("mix") or (self.engine.mixer.mixes[0].id if self.engine.mixer.mixes else "monitor")

    def title(self) -> str:
        return f"{self.label()} level"

    def label(self) -> str:
        target = self._target() if hasattr(self, "engine") else None
        mix = _mix_label(self.engine, self._mix_id())
        return f"{target.label} in {mix}" if self.spec.get("channel") and target is not None else mix

    def _values(self) -> tuple:
        target = self._target()
        if target is None:
            return 0.0, False
        if self.spec.get("channel"):
            return target.levels.get(self._mix_id(), 0.0), bool(target.mutes.get(self._mix_id()))
        return target.gain_db, bool(target.mute)

    def state(self) -> tuple:
        db, muted = self._values()
        levels = self.engine.sample_levels(0.05)
        key = f"ch:{self.spec['channel']}:{self._mix_id()}" if self.spec.get("channel") else f"mix:{self._mix_id()}"
        return (round(db, 1), muted, round(levels.get(key, 0.0) * 20))

    def act(self) -> None:
        _db, muted = self._values()
        if self.spec.get("channel"):
            self.engine.set_mute(self.spec["channel"], self._mix_id(), not muted)
        else:
            self.engine.set_master_mute(self._mix_id(), not muted)
        self.window_.sync_from_model()

    def wheelEvent(self, event) -> None:
        step = 0.2 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        direction = 1 if event.angleDelta().y() > 0 else -1 if event.angleDelta().y() < 0 else 0
        if not direction:
            return
        db, _muted = self._values()
        new = max(-60.0, min(12.0, round((db + direction * step) * 10) / 10))
        if self.spec.get("channel"):
            self.engine.set_level(self.spec["channel"], self._mix_id(), new)
        else:
            self.engine.set_master(self._mix_id(), new)
        self.window_.sync_from_model()
        self.tick()
        event.accept()

    def paintEvent(self, _event) -> None:
        from .ui_base import db_to_fader_position

        db, muted, level = self._state or (0.0, False, 0)
        if themes.current_look() == "tile":
            self._paint_key(db, muted, level, db_to_fader_position(db))
            return
        panel, text, accent = self._colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(panel)
        p.drawEllipse(QRectF(2, 2, self.width() - 4, self.height() - 4))
        arc = QRectF(12, 12, self.width() - 24, self.height() - 24)
        track = QColor(text)
        track.setAlpha(50)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(track, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc, -45 * 16, 270 * 16)  # from lower left, clockwise, to lower right
        position = db_to_fader_position(db)
        p.setPen(QPen(QColor(themes.color("mute_fg")) if muted else accent, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if position > 0:
            p.drawArc(arc, 225 * 16, int(-270 * position * 16))
        inner = arc.adjusted(11, 11, -11, -11)
        meter = QColor("#2bd48a")
        meter.setAlpha(60 + min(190, level * 10))
        p.setPen(QPen(meter, 3))
        p.drawArc(inner, 225 * 16, int(-270 * min(1.0, level / 20.0) * 16))
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(text)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "off" if (muted or db <= -60) else f"{db:+.0f}" if abs(db) >= 10 else f"{db:+.1f}")
        p.end()


    def _paint_key(self, db: float, muted: bool, level: int, position: float) -> None:
        """The Tile look: a raised round knob in a groove, the level as an arc in the groove, the pointer on the knob."""
        from . import look_tile

        pc = look_tile.paint_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        groove = QRectF(6, 4, side - 12, side - 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pc["track"]))
        p.drawEllipse(groove)
        arc = groove.adjusted(5, 5, -5, -5)
        accent = QColor(pc["red"] if muted else "#4c8dff")
        p.setBrush(Qt.BrushStyle.NoBrush)
        if position > 0:
            p.setPen(QPen(accent, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc, 225 * 16, int(-270 * position * 16))
        knob = groove.adjusted(16, 16, -16, -16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pc["skirt_dark"]))
        p.drawEllipse(knob.translated(0, 5))
        p.setBrush(QColor(pc["skirt"]))
        p.drawEllipse(knob.translated(0, 4))
        gradient = QRadialGradient(knob.left() + knob.width() * 0.38, knob.top() + knob.height() * 0.3, knob.width() * 0.75)
        gradient.setColorAt(0.0, QColor(pc["face_top"]))
        gradient.setColorAt(1.0, QColor(pc["face_bottom"]))
        p.setBrush(gradient)
        p.drawEllipse(knob)
        angle = math.radians(-135 + 270 * position)
        cx, cy, r = knob.center().x(), knob.center().y(), knob.width() / 2
        p.setPen(QPen(accent, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx + math.sin(angle) * r * 0.55, cy - math.cos(angle) * r * 0.55),
                   QPointF(cx + math.sin(angle) * r * 0.82, cy - math.cos(angle) * r * 0.82))
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(pc["red"] if muted else pc["text"]))
        p.drawText(knob.adjusted(0, 8, 0, 8), Qt.AlignmentFlag.AlignCenter,
                   "off" if (muted or db <= -60) else f"{db:+.0f}" if abs(db) >= 10 else f"{db:+.1f}")
        p.end()


class StripWidget(DesktopWidget):
    """The compact list of channels as a floating panel."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("desktopstrip")
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        self._layout = layout
        self.strip = None
        self.restyle()
        self.setFixedWidth(340)
        self.setMinimumHeight(180)
        self.setToolTip("Drag the empty space to move. Right-click for more.")
        self._ids = self._channel_ids()

    def restyle(self) -> None:
        """Follow the look and colours of the main window: the Tile look's mini keys in a tray, or the plain list. The window's style
        sheet does not reach a window of its own, so it is given here."""
        from .ui_mini import MiniStrip

        tile = themes.current_look() == "tile"
        self.setStyleSheet(self.window_.styleSheet())
        if self.strip is None or self.strip.tile != tile:
            mix = self.strip.mix_id if self.strip is not None else self.spec.get("mix")
            if self.strip is not None:
                self._layout.removeWidget(self.strip)
                self.strip.hide()
                self.strip.deleteLater()
            self._layout.setContentsMargins(*((0, 0, 0, 0) if tile else (12, 12, 12, 12)))  # Tile: the list's own tray is the panel
            self.strip = MiniStrip(self.window_, tile=tile)
            if mix:
                self.strip.choose_mix(mix)
            self._layout.addWidget(self.strip)
            self._ids = self._channel_ids() if hasattr(self, "engine") else ()
        self.strip.refresh_theme()
        self.update()

    def title(self) -> str:
        return "Channel levels"

    def _channel_ids(self) -> tuple:
        return tuple(c.id for c in self.engine.mixer.channels)

    def state(self) -> tuple:
        if self._channel_ids() != self._ids:
            self._ids = self._channel_ids()
            self.strip.rebuild()
        self.strip.sync_from_model()
        if self.strip.tile:  # the mini keys show the live signal too (they repaint only when it changes)
            self.strip.push_levels(self.engine.sample_levels(0.05))
        return ()

    def mousePressEvent(self, event) -> None:
        child = self.childAt(event.position().toPoint())
        if child is None or child is self.strip:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = None

    def paintEvent(self, _event) -> None:
        if self.strip.tile:  # the list paints its own tray; the corners round it show the window's floor
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(themes.color("bg")))
            p.end()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(themes.color("border")), 1))
        p.setBrush(QColor(themes.color("bg")))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        p.end()


# ----------------------------------------------------------------------------- one channel, one mix (0.11.5)
LANE_H = 30


def paint_card(widget: QWidget, p: QPainter, tint: str) -> QRectF:
    """The widget's card in the look in use, and the area inside it: a raised key (Tile), glass with an edge in the card's colour
    (Nexus) or a soft card (Calm, Original). Every colour comes from the theme, with its depth worked out (``depth``)."""
    from . import depth

    look = themes.current_look()
    colors = themes._current
    d = depth.depth_colors(colors)
    rect = QRectF(widget.rect())
    if look == "tile":
        from . import ui_tile_paint
        key = rect.adjusted(8, 4, -8, -16)
        ui_tile_paint.paint_surface(p, key, widget.devicePixelRatioF(), radius=14, skirt=6)
        return key.adjusted(12, 10, -12, -16)
    card = rect.adjusted(6, 4, -6, -10)
    if d["shadow_alpha"] > 0:
        from .ui_tile_paint import soft_shape
        pixmap, pad = soft_shape(card.width() - 8, card.height() - 4, 6, d["shadow_alpha"] * 1.2, d["shadow"],
                                 widget.devicePixelRatioF(), 16)
        p.drawPixmap(QPointF(card.x() + 4 - pad, card.y() + 2 - pad + 5), pixmap)
    if look == "nexus":
        gradient = QLinearGradient(card.topLeft(), card.bottomLeft())
        gradient.setColorAt(0.0, QColor(depth.shade(colors["panel"], 0.6 if d["light"] else 0.06)))
        gradient.setColorAt(0.4, QColor(colors["panel"]))
        gradient.setColorAt(1.0, QColor(depth.shade(colors["panel"], -0.03 if d["light"] else -0.3)))
        p.setBrush(gradient)
        p.setPen(QPen(QColor(d["outline"]), 1))
    else:
        p.setBrush(QColor(colors["panel"]))
        p.setPen(QPen(QColor(colors["border"]), 1))
    radius = 6 if look == "original" else 16
    p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    if look == "nexus":  # the top edge in the card's colour: a lit line on dark themes, a 3 px band on light ones
        p.setPen(QPen(QColor(tint), 3 if d["light"] else 1))
        p.drawLine(QPointF(card.left() + radius, card.top() + (1.5 if d["light"] else 0.5)),
                   QPointF(card.right() - radius, card.top() + (1.5 if d["light"] else 0.5)))
    return card.adjusted(12, 10, -12, -10)


def paint_lane(p: QPainter, rect: QRectF, position: float, live: float, muted: bool, tint: str) -> None:
    """A groove with the fader's position as a soft fill and the live sound as a brighter one; striped and grey while muted."""
    from . import depth
    from .ui_tile_paint import stripe_brush

    colors = themes._current
    d = depth.depth_colors(colors)
    groove = QRectF(rect.left(), rect.center().y() - 4, rect.width(), 8)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(stripe_brush(d["groove"], themes.mix(d["groove"], colors["text"], 0.14)) if muted else QColor(d["groove"]))
    p.drawRoundedRect(groove, 4, 4)
    if not muted:
        soft = QColor(tint)
        soft.setAlphaF(0.35)
        p.setBrush(soft)
        p.drawRoundedRect(QRectF(groove.left(), groove.top(), max(8.0, groove.width() * position), groove.height()), 4, 4)
        if live > 0.01:
            p.setBrush(QColor(tint))
            p.drawRoundedRect(QRectF(groove.left(), groove.top(), max(6.0, groove.width() * position * live), groove.height()), 4, 4)
    handle = QRectF(groove.left() + groove.width() * position - 6, rect.center().y() - 9, 12, 18)
    p.setBrush(QColor(0, 0, 0, 80))
    p.drawRoundedRect(handle.translated(0, 1.5), 6, 6)
    p.setBrush(QColor(colors["text_off"] if muted else "#ffffff"))
    p.setPen(QPen(QColor(colors["handle_edge"]), 1) if d["light"] else Qt.PenStyle.NoPen)
    p.drawRoundedRect(handle, 6, 6)


def paint_icon_button(p: QPainter, rect: QRectF, name: str, color: str, pushed: bool, red: bool) -> None:
    from . import ui_icons as icons

    colors = themes._current
    p.setPen(QPen(QColor(colors["mute"] if red else colors["border2"]), 1))
    p.setBrush(QColor(colors["mute_bg"] if red else colors["surface2"]))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
    ratio = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    pixmap = icons.render(name, colors["mute_fg"] if red else color, round(16 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    p.drawPixmap(QPointF(rect.center().x() - 8, rect.center().y() - 8), pixmap)


class LaneWidget(DesktopWidget):
    """The common part of the channel and mix widgets: lanes you can drag or scroll, mute buttons you can click, and the rest of the
    card to move it by."""

    WIDTH = 280

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        self._grab = None  # the lane being dragged, by its mix id
        self.setMouseTracking(False)

    # what each kind gives
    def lanes(self) -> list:
        """[(mix id, label, icon, db, muted, live 0..1)] in order."""
        return []

    def set_db(self, mix_id: str, db: float) -> None:
        pass

    def toggle_mute(self, mix_id: str) -> None:
        pass

    def tint(self) -> str:
        return themes.color("accent")

    def header_height(self) -> int:
        return 34

    def _inner(self) -> QRectF:
        look = themes.current_look()
        rect = QRectF(self.rect())
        if look == "tile":
            return rect.adjusted(8 + 12, 4 + 10, -8 - 12, -16 - 16)
        return rect.adjusted(6 + 12, 4 + 10, -6 - 12, -10 - 10)

    def _rows(self) -> list:
        inner = self._inner()
        top = inner.top() + self.header_height()
        out = []
        for index, lane in enumerate(self.lanes()):
            row = QRectF(inner.left(), top + index * (LANE_H + 6), inner.width(), LANE_H)
            mute = QRectF(row.left(), row.top() + 2, 26, 26)
            groove = QRectF(mute.right() + 10, row.top(), row.width() - 26 - 10 - 64, LANE_H)
            out.append((lane, row, mute, groove))
        return out

    def fit(self) -> None:
        rows = len(self.lanes())
        extra = (26 if themes.current_look() == "tile" else 20) + 24
        self.setFixedSize(self.WIDTH, self.header_height() + rows * (LANE_H + 6) + extra)

    def state(self) -> tuple:
        return (themes.current_look(), themes.generation(), tuple((m, round(db, 1), muted, round(live * 16))
                                                               for m, _l, _i, db, muted, live in self.lanes()))

    def restyle(self) -> None:
        self.fit()
        self.update()

    def showEvent(self, event) -> None:
        self.fit()
        super().showEvent(event)

    def _lane_at(self, point: QPointF):
        for lane, row, mute, groove in self._rows():
            if mute.contains(point):
                return lane[0], "mute", groove
            if groove.adjusted(-6, 0, 6, 0).contains(point):
                return lane[0], "lane", groove
        return None, None, None

    def _db_at(self, groove: QRectF, x: float) -> float:
        from .ui_base import fader_position_to_db
        return fader_position_to_db(max(0.0, min(1.0, (x - groove.left()) / max(1.0, groove.width()))))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            mix_id, part, groove = self._lane_at(event.position())
            if part == "mute":
                self.toggle_mute(mix_id)
                self.tick()
                return
            if part == "lane":
                self._grab = (mix_id, groove)
                self.set_db(mix_id, self._db_at(groove, event.position().x()))
                self.tick()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._grab is not None:
            mix_id, groove = self._grab
            self.set_db(mix_id, self._db_at(groove, event.position().x()))
            self.tick()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._grab is not None:
            self._grab = None
            return
        self._press = None if event.button() == Qt.MouseButton.LeftButton and self._press is not None else self._press
        super().mouseReleaseEvent(event)

    def act(self) -> None:
        pass  # a click on the card itself does nothing: the lanes and buttons do the work

    def wheelEvent(self, event) -> None:
        mix_id, _part, _groove = self._lane_at(event.position())
        if mix_id is None:
            lanes = self.lanes()
            mix_id = lanes[0][0] if lanes else None
        if mix_id is None:
            return
        step = 0.2 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        direction = 1 if event.angleDelta().y() > 0 else -1 if event.angleDelta().y() < 0 else 0
        db = next(db for m, _l, _i, db, _mu, _lv in self.lanes() if m == mix_id)
        self.set_db(mix_id, round((db + direction * step) * 10) / 10)
        self.tick()
        event.accept()

    def paint_header(self, p: QPainter, inner: QRectF) -> None:
        pass

    def paintEvent(self, _event) -> None:
        from .ui_base import db_to_fader_position, format_db

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tint = self.tint()
        paint_card(self, p, tint)
        inner = self._inner()
        self.paint_header(p, inner)
        font = QFont(self.font())
        font.setPixelSize(11)
        for (mix_id, label, icon, db, muted, live), row, mute, groove in self._rows():
            paint_icon_button(p, mute, icon, themes.color("text2"), muted, muted)
            paint_lane(p, groove, db_to_fader_position(db), live, muted, tint)
            p.setFont(font)
            p.setPen(QColor(themes.color("mute_fg") if muted else themes.color("text")))
            p.drawText(QRectF(groove.right() + 6, row.top(), 58, row.height()), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       "Muted" if muted else format_db(db))
        p.end()


class ChannelWidget(LaneWidget):
    """One channel on the desktop: its name and colour, and a lane for each mix (mute, level, live sound)."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        self.setToolTip("Drag or scroll a slider to change that mix's level; click a speaker to mute. Drag the card to move it.")

    def channel(self):
        return next((c for c in self.engine.mixer.channels if c.id == self.spec.get("channel")), None)

    def title(self) -> str:
        channel = self.channel() if hasattr(self, "engine") else None
        return f"{channel.label} channel" if channel is not None else "Channel"

    def tint(self) -> str:
        from . import depth, look_tile
        channel = self.channel()
        if channel is None:
            return themes.color("accent")
        base = look_tile.channel_color(channel) if themes.current_look() == "tile" else channel.color
        return depth.channel_tint(base, themes._current)

    def lanes(self) -> list:
        from .ui_base import MIX_ICONS
        channel = self.channel()
        if channel is None:
            return []
        levels = self.engine.sample_levels(0.05)
        from .ui_base import level_fraction
        return [(m.id, m.label, MIX_ICONS.get(m.id, "speaker"), channel.levels.get(m.id, 0.0), bool(channel.mutes.get(m.id)),
                 level_fraction(levels.get(f"ch:{channel.id}:{m.id}", 0.0))) for m in self.engine.mixer.mixes]

    def set_db(self, mix_id: str, db: float) -> None:
        self.engine.set_level(self.spec["channel"], mix_id, max(-60.0, min(12.0, db)))
        self.window_.sync_from_model()

    def toggle_mute(self, mix_id: str) -> None:
        channel = self.channel()
        if channel is not None:
            self.engine.set_mute(channel.id, mix_id, not channel.mutes.get(mix_id))
            self.window_.sync_from_model()

    def paint_header(self, p: QPainter, inner: QRectF) -> None:
        channel = self.channel()
        tint = QColor(self.tint())
        well = QRectF(inner.left(), inner.top(), 24, 24)
        fill = QColor(tint)
        fill.setAlphaF(0.18)
        p.setPen(QPen(tint, 1))
        p.setBrush(fill)
        p.drawRoundedRect(well, 7, 7)
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(tint)
        p.drawText(well, Qt.AlignmentFlag.AlignCenter, (channel.label[:1] if channel is not None else "?").upper())
        p.setPen(QColor(themes.color("text")))
        name = channel.label if channel is not None else "This channel was removed"
        if themes.current_look() == "nexus":
            name = name.upper()
        p.drawText(QRectF(well.right() + 10, inner.top(), inner.width() - 34, 24), Qt.AlignmentFlag.AlignVCenter, name)


class MixWidget(LaneWidget):
    """One mix on the desktop: Listen or Broadcast (or Recording), its level, Mute and the Limiter."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        self.setToolTip("Drag or scroll the slider to change the level; click the speaker to mute, the Limiter to switch it. "
                        "Drag the card to move it.")

    def mix(self):
        return next((m for m in self.engine.mixer.mixes if m.id == self.spec.get("mix")), None) or (
            self.engine.mixer.mixes[0] if self.engine.mixer.mixes else None)

    def title(self) -> str:
        mix = self.mix() if hasattr(self, "engine") else None
        return f"{mix.label} mix" if mix is not None else "Mix"

    def tint(self) -> str:
        mix = self.mix()
        colors = themes.mix_colors(themes._current)
        return {"monitor": colors["listen"], "stream": colors["broadcast"]}.get(mix.id if mix else "", themes.color("mute"))

    def lanes(self) -> list:
        from .ui_base import MIX_ICONS, level_fraction
        mix = self.mix()
        if mix is None:
            return []
        level = self.engine.sample_levels(0.05).get(f"mix:{mix.id}", 0.0)
        return [(mix.id, mix.label, MIX_ICONS.get(mix.id, "speaker"), mix.gain_db, bool(mix.mute), level_fraction(level))]

    def state(self) -> tuple:
        mix = self.mix()
        return super().state() + ((bool(mix.limiter) if mix else False),)

    def set_db(self, mix_id: str, db: float) -> None:
        self.engine.set_master(mix_id, max(-60.0, min(12.0, db)))
        self.window_.sync_from_model()

    def toggle_mute(self, mix_id: str) -> None:
        mix = self.mix()
        if mix is not None:
            self.engine.set_master_mute(mix.id, not mix.mute)
            self.window_.sync_from_model()

    def _limiter_rect(self) -> QRectF:
        inner = self._inner()
        return QRectF(inner.right() - 64, inner.top() + 2, 64, 20)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._limiter_rect().contains(event.position()):
            mix = self.mix()
            if mix is not None:
                self.engine.set_limiter(mix.id, not mix.limiter)
                self.window_.sync_from_model()
                self.tick()
            return
        super().mousePressEvent(event)

    def paint_header(self, p: QPainter, inner: QRectF) -> None:
        from . import ui_icons as icons
        from .ui_base import MIX_ICONS

        mix = self.mix()
        tint = QColor(self.tint())
        ratio = self.devicePixelRatioF()
        pixmap = icons.render(MIX_ICONS.get(mix.id if mix else "", "speaker"), tint.name(), round(18 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        p.drawPixmap(QPointF(inner.left() + 3, inner.top() + 3), pixmap)
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(themes.color("text")))
        label = (mix.label if mix else "Mix")
        p.drawText(QRectF(inner.left() + 30, inner.top(), inner.width() - 100, 24), Qt.AlignmentFlag.AlignVCenter,
                   label.upper() if themes.current_look() == "nexus" else label)
        on = bool(mix.limiter) if mix else False
        rect = self._limiter_rect()
        p.setPen(QPen(QColor(themes.color("accent") if on else themes.color("border2")), 1))
        p.setBrush(QColor(themes.color("accent_bg") if on else themes.color("surface2")))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        font.setPixelSize(11)
        p.setFont(font)
        p.setPen(QColor(themes.color("accent_text") if on else themes.color("text2")))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Limiter")


CLASSES = {"mic": MicWidget, "dial": DialWidget, "strip": StripWidget, "channel": ChannelWidget, "mix": MixWidget}


class DesktopWidgetManager:
    """Opens, closes and remembers the widgets of a main window (the list is saved in its settings)."""

    def __init__(self, window) -> None:
        self.window = window
        self.open_widgets: dict = {}  # (kind, mix, channel) -> widget

    @property
    def specs(self) -> list:
        return self.window.engine.mixer.desktop_widgets

    def is_open(self, kind: str, mix=None, channel=None) -> bool:
        return (kind, mix, channel) in self.open_widgets

    def open(self, kind: str, mix=None, channel=None, x=None, y=None) -> bool:
        spec = clean_spec({"kind": kind, "mix": mix, "channel": channel, "x": x, "y": y})
        if spec is None:
            return False
        key = _key(spec)
        if key in self.open_widgets:
            return True
        if len(self.specs) >= MAX_WIDGETS:
            return False
        self._show(spec)
        self.specs.append(spec)
        return True

    def _show(self, spec: dict) -> None:
        widget = CLASSES[spec["kind"]](self, spec)
        self.open_widgets[_key(spec)] = widget
        fit = getattr(widget, "fit", None)
        if fit is not None:
            fit()
        app = QApplication.instance()
        screens = {}
        for screen in (app.screens() if app is not None else []):
            area = screen.availableGeometry()
            screens[screen.name() or "screen"] = (area.x(), area.y(), area.width(), area.height())
        primary = app.primaryScreen().name() if app is not None and app.primaryScreen() is not None else ""
        spot = desktop_place.place_for(spec, screens, primary, (widget.width(), widget.height()))
        if spot is None:  # a new widget: near the top right of the main window's screen, each a little lower than the last
            screen = self.window.screen().availableGeometry() if self.window.screen() else None
            n = len(self.open_widgets) - 1
            if screen is not None:
                spot = (max(screen.left(), screen.right() - widget.width() - 24 - 20 * n), screen.top() + 60 + 24 * n)
            else:
                spot = (100 + 20 * n, 100 + 20 * n)
        spec["x"], spec["y"] = int(spot[0]), int(spot[1])
        widget.attach_layer_shell()  # KDE Plasma on Wayland: a real desktop widget, before it is first shown
        widget.move(spec["x"], spec["y"])
        widget.show()
        if widget.layered:
            widget.place(spec["x"], spec["y"])

    def offer_kwin_rule(self) -> None:
        """KDE without layer-shell: offer a KWin rule that keeps the widgets on top (Wayland may ignore a window's own request)."""
        from PySide6.QtWidgets import QMessageBox

        if desktop_place.kwin_rule_present():
            self.window.say("The KWin rule for Sluice's widgets is already there.")
            return
        ask = QMessageBox.question(self.window, "Keep widgets on top",
                                   "On KDE Plasma under Wayland, a window cannot keep itself on top. Sluice can add a KWin window rule "
                                   "(System Settings > Window Management > Window Rules) that keeps its desktop widgets above other "
                                   "windows. You can remove it there at any time.\n\nAdd the rule?")
        if ask != QMessageBox.StandardButton.Yes:
            return
        problem = desktop_place.add_kwin_rule()
        self.window.say(problem or "Added a KWin rule: Sluice's desktop widgets stay above other windows.")

    def restyle(self) -> None:
        """The look or the colours changed: every open widget follows."""
        for widget in self.open_widgets.values():
            restyle = getattr(widget, "restyle", None)
            if restyle is not None:
                restyle()
            widget.update()

    def close_spec(self, spec: dict) -> None:
        widget = self.open_widgets.pop(_key(spec), None)
        if widget is not None:
            widget.close()
            widget.deleteLater()
        if spec in self.specs:
            self.specs.remove(spec)

    def toggle(self, kind: str, mix=None, channel=None) -> bool:
        """Open it if it is closed, close it if it is open. Returns whether it is open now."""
        widget = self.open_widgets.get((kind, mix, channel))
        if widget is not None:
            self.close_spec(widget.spec)
            return False
        return self.open(kind, mix, channel)

    def restore(self) -> None:
        """Show the widgets saved from last time (run once, after the window is built)."""
        for spec in list(self.specs)[:MAX_WIDGETS]:
            if _key(spec) not in self.open_widgets:
                self._show(spec)

    def close_all(self, forget: bool = False) -> None:
        """Close every widget. With ``forget`` they are also removed from the saved list; without it they come back next time."""
        for widget in list(self.open_widgets.values()):
            widget.close()
            widget.deleteLater()
        self.open_widgets.clear()
        if forget:
            self.specs.clear()
