"""Desktop widgets: small borderless windows you can leave on the desktop (a microphone mute button, a volume dial, a compact list of
channels, and since 0.11.5 one channel or one mix with its sliders) so the big window can stay closed. They draw themselves in the look
in use and ask the engine for the shared meter reading, a few times a second, only while they are shown and only repaint when something
they show has changed.

Where they go is ``desktop_place``: they snap to the screen's edges and to each other, remember a place on each screen, and on KDE
Plasma under Wayland they are real desktop-widget windows (layer-shell), so they can place themselves and stay on top."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from . import ui_dialog
from . import desktop_place, themes

from .model import MAX_DESKTOP_WIDGETS as MAX_WIDGETS, clean_widget_spec as clean_spec  # noqa: E402  (the model keeps them: it has no Qt)

TICK_MS = 100


def _short(db: float) -> str:
    from .ui_base import short_level

    return short_level(db)


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
        self._grab_at = QPointF()
        self._dragging = False
        self._drag_pending = None
        self._drag_waiting = False
        self.layered = False
        self.setMouseTracking(True)  # to show where it can be taken (an open hand) and where its controls are
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
    def event(self, event) -> bool:
        """Every event (painting, the mouse, showing) in the widgets' own skin and theme, when they have one (0.11.6)."""
        if event.type() == QEvent.Type.UpdateRequest and self._drag_waiting:
            self._drag_frame()  # the last step is on screen: take the next
        skin, colors = self.manager.dressing()
        with themes.dressed_as(skin, colors):
            return super().event(event)

    def tick(self) -> None:
        skin, colors = self.manager.dressing()
        with themes.dressed_as(skin, colors):
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
            desktop_place.layer_shell().place(self.windowHandle(), x, y, origin, screen)
            self.spec["x"], self.spec["y"] = int(x), int(y)
            if not self._dragging:
                self.settle_timer.start()
        else:
            self.move(x, y)

    def _screen_at(self, point: QPoint):
        app = QApplication.instance()
        screen = app.screenAt(point) if app is not None else None
        return screen or self.screen() or (app.primaryScreen() if app is not None else None)

    def settle(self) -> None:
        """It has stopped moving: snap to the screen's edges and to the other widgets, and remember the place on this screen. Not
        while it is still held (a pause mid-drag used to snap it away under the pointer): then it waits for the release."""
        if self._dragging or QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.settle_timer.start()
            return
        here = self.position()
        screen = self._screen_at(here + QPoint(self.width() // 2, self.height() // 2))
        if screen is None:
            return
        area = screen.availableGeometry()
        others = [
            (w.position().x(), w.position().y(), w.width(), w.height())
            for w in self.manager.open_widgets.values()
            if w is not self and w.isVisible()
        ]
        x, y = desktop_place.snap(
            (here.x(), here.y(), self.width(), self.height()), (area.x(), area.y(), area.width(), area.height()), others
        )
        if (x, y) != (here.x(), here.y()):
            self.settle_timer.blockSignals(True)
            self.place(x, y)
            self.settle_timer.blockSignals(False)
            self.settle_timer.stop()
        desktop_place.remember(self.spec, screen.name() or "screen", x, y)

    # -- pressing, dragging and clicking
    # 0.11.7: a layer-shell widget (KDE Plasma on Wayland) is moved by Sluice, and Qt's screen position for the pointer is out of
    # date for such a window (it does not know where the surface is), so moving by it lagged and jumped. Now the widget moves by
    # how far the pointer is from where it was pressed, measured inside the widget, one step per frame the compositor shows: after
    # a step lands, the pointer's place in the widget already counts it, so nothing is added twice.
    DRAG_START = 4  # pixels the pointer moves before a press becomes a drag (a smaller press is a click)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._drag_from = (self._press, self.position())
            self._grab_at = event.position()  # where in the widget it was taken
            self._dragging = False
            self._drag_pending = None
            self._drag_waiting = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_from is None:
            self.hover(event.position())
            return
        local = event.position()
        offset = local - self._grab_at
        if not self._dragging:
            if abs(offset.x()) + abs(offset.y()) <= self.DRAG_START:
                return
            self._dragging = True
            self._press = None
            if not self.layered:
                handle = self.windowHandle()
                if (
                    handle is not None and handle.startSystemMove()
                ):  # the desktop moves it (the only way on Wayland, smooth on X11)
                    self._drag_from = None
                    return
        if self._drag_waiting:
            return  # measured before the last step was shown: it would count that step twice. The next event after it has it all
        self._drag_pending = local
        self._drag_step()

    def _drag_step(self) -> None:
        """Move by the pointer's distance from where the widget was taken; then wait for that frame before the next step."""
        if self._drag_waiting or self._drag_pending is None:
            return
        offset = self._drag_pending - self._grab_at
        self._drag_pending = None
        dx, dy = round(offset.x()), round(offset.y())
        if not dx and not dy:
            return
        here = self.position()
        self.place(here.x() + dx, here.y() + dy)
        self._drag_waiting = True
        handle = self.windowHandle()
        if handle is not None:
            handle.requestUpdate()  # an UpdateRequest comes back once the compositor has shown the moved surface
        QTimer.singleShot(48, self._drag_frame)  # in case no frame comes (a hidden or blocked surface)

    def _drag_frame(self) -> None:
        if self._drag_waiting:
            self._drag_waiting = False
            self._drag_step()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            dragged = self._dragging and self._drag_from is not None
            if dragged and self.layered:  # the last bit of the way, from where it was let go
                self._drag_waiting = False
                self._drag_pending = event.position()
                self._drag_step()
            self._drag_from = None
            self._dragging = False
            self._drag_pending = None
            self._drag_waiting = False
            self.unsetCursor()
            if self._press is not None:
                self._press = None
                self.act()
                self.tick()
            elif dragged:
                self.settle()  # snap only now, when it is let go

    def hover(self, point: QPointF) -> None:
        """The pointer over the widget with no button held: an open hand where dragging moves it (subclasses mark their controls)."""
        if self.cursor().shape() != Qt.CursorShape.OpenHandCursor:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

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
        spot = QPoint(self.spec.get("x") or 0, self.spec.get("y") or 0)
        self.layered = handle is not None and shell.attach(handle, screen=self._screen_at(spot))
        return self.layered

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.settle_timer.stop()
        if self.layered and self.windowHandle() is not None:
            desktop_place.layer_shell().forget(self.windowHandle())
        super().closeEvent(event)

    def _colors(self) -> tuple:
        panel = QColor(themes.color("panel"))
        return panel, QColor(themes.color("text")), QColor(themes.color("accent"))


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
        if themes.current_skin() == "tile":
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
        from . import skin_tile, ui_tile_paint as ui_tile

        muted, glow = self._state or (False, 0)
        pc = skin_tile.paint_colors()
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
            self.engine.mixer.mixes[0] if self.engine.mixer.mixes else None
        )

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
        if themes.current_skin() == "tile":
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
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "off" if muted else _short(db))
        p.end()

    def _paint_key(self, db: float, muted: bool, level: int, position: float) -> None:
        """The Tile look: a raised round knob in a groove, the level as an arc in the groove, the pointer on the knob."""
        from . import skin_tile

        pc = skin_tile.paint_colors()
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
        p.drawLine(
            QPointF(cx + math.sin(angle) * r * 0.55, cy - math.cos(angle) * r * 0.55),
            QPointF(cx + math.sin(angle) * r * 0.82, cy - math.cos(angle) * r * 0.82),
        )
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(pc["red"] if muted else pc["text"]))
        p.drawText(knob.adjusted(0, 8, 0, 8), Qt.AlignmentFlag.AlignCenter, "off" if muted else _short(db))
        p.end()


class StripWidget(DesktopWidget):
    """The compact list of channels as a floating panel."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)  # see-through like the others (0.11.7): it paints its own panel, solid but in Glass
        self.setObjectName("desktopstrip")
        layout = QVBoxLayout(self)
        self._layout = layout
        self.strip = None
        with themes.dressed_as(*manager.dressing()):
            self.restyle()
        self.setFixedWidth(340)
        self.setMinimumHeight(180)
        self.setToolTip("Drag the empty space to move. Right-click for more.")
        self._ids = self._channel_ids()

    def restyle(self) -> None:
        """Follow the widgets' skin and colours (the window's, unless they have their own): the Tile look's mini keys in a tray, or
        the plain list. The window's style sheet does not reach a window of its own, so the skin's sheet is given here."""
        from .ui_mini import MiniStrip

        tile = themes.current_skin() == "tile"
        self.setStyleSheet(themes.build_style(themes._current, themes.current_skin(), see=False))
        if self.strip is None or self.strip.tile != tile:
            mix = self.strip.mix_id if self.strip is not None else self.spec.get("mix")
            if self.strip is not None:
                self._layout.removeWidget(self.strip)
                self.strip.hide()
                self.strip.deleteLater()
            self._layout.setContentsMargins(
                *((0, 0, 0, 0) if tile else (12, 12, 12, 12))
            )  # Tile: the list's own tray is the panel
            self.strip = MiniStrip(self.window_, tile=tile)
            if mix:
                self.strip.choose_mix(mix)
            self._layout.addWidget(self.strip)
            self._ids = self._channel_ids() if hasattr(self, "engine") else ()
        self.strip.refresh_theme()
        self._watch_children()
        self.update()

    def _watch_children(self) -> None:
        """The list's own widgets paint outside this window's events: they are watched, so they paint in the widgets' skin too."""
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.Paint or getattr(self, "_painting_child", False):
            return False
        skin, colors = self.manager.dressing()
        if skin is None:
            return False
        self._painting_child = True
        try:
            with themes.dressed_as(skin, colors):
                obj.event(event)  # painted here, in the widgets' skin and colours...
        finally:
            self._painting_child = False
        return True  # ...so Qt does not paint it again

    def title(self) -> str:
        return "Channel levels"

    def _channel_ids(self) -> tuple:
        return tuple(c.id for c in self.engine.mixer.channels)

    def state(self) -> tuple:
        if self._channel_ids() != self._ids:
            self._ids = self._channel_ids()
            self.strip.rebuild()
            self._watch_children()
        self.strip.sync_from_model()
        if self.strip.tile:  # the mini keys show the live signal too (they repaint only when it changes)
            self.strip.push_levels(self.engine.sample_levels(0.05))
        return ()

    def mousePressEvent(self, event) -> None:
        child = self.childAt(event.position().toPoint())
        if child is None or child is self.strip:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = None  # a click on the panel itself does nothing; a drag still ends (and snaps) in the shared code
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        if self.strip.tile:  # the list paints its own tray; the corners round it show the window's floor
            p = QPainter(self)
            p.setRenderHints(
                QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
            )  # 0.12.2: smooth edges everywhere
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
    """The widget's card in the look in use, and the area inside it: a raised key (Tile) or a soft card (Calm). Every colour
    comes from the theme, with its depth worked out (``depth``)."""
    from . import depth

    skin = themes.current_skin()
    colors = themes._current
    d = depth.depth_colors(colors)
    rect = QRectF(widget.rect())
    if skin == "tile":
        from . import ui_tile_paint

        key = rect.adjusted(8, 4, -8, -16)
        ui_tile_paint.paint_surface(p, key, widget.devicePixelRatioF(), radius=14, skirt=6)
        return key.adjusted(12, 10, -12, -16)
    card = rect.adjusted(6, 4, -6, -10)
    if d["shadow_alpha"] > 0:
        from .ui_tile_paint import soft_shape

        pixmap, pad = soft_shape(
            card.width() - 8, card.height() - 4, 6, d["shadow_alpha"] * 1.2, d["shadow"], widget.devicePixelRatioF(), 16
        )
        p.drawPixmap(QPointF(card.x() + 4 - pad, card.y() + 2 - pad + 5), pixmap)
    p.setBrush(QColor(colors["panel"]))
    p.setPen(QPen(QColor(colors["border"]), 1))
    radius = 16
    p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    return card.adjusted(12, 10, -12, -10)


def paint_lane(p: QPainter, rect: QRectF, position: float, live: float, muted: bool, tint: str) -> None:
    """A groove with the fader's position as a soft fill and the live sound as a brighter one; striped and grey while muted."""
    from . import depth
    from .ui_tile_paint import stripe_brush

    colors = themes._current
    d = depth.depth_colors(colors)
    from . import ui_paint

    groove = QRectF(rect.left(), rect.center().y() - 4, rect.width(), 8)
    p.setPen(Qt.PenStyle.NoPen)
    ui_paint.groove(
        p, groove, stripe_brush(d["groove"], themes.mix(d["groove"], colors["text"], 0.14)) if muted else QColor(d["groove"])
    )
    if not muted:
        p.setBrush(QColor(depth.position_fill(tint, d["groove"], 0.35)))  # solid: yellow stays yellow (0.11.6)
        p.drawRoundedRect(QRectF(groove.left(), groove.top(), max(8.0, groove.width() * position), groove.height()), 4, 4)
        if live > 0.01:
            p.setBrush(QColor(tint))
            p.drawRoundedRect(
                QRectF(groove.left(), groove.top(), max(6.0, groove.width() * position * live), groove.height()), 4, 4
            )
    handle = QRectF(groove.left() + groove.width() * position - 6, rect.center().y() - 9, 12, 18)
    ui_paint.handle(p, handle, colors["text_off"] if muted else "#ffffff", colors["handle_edge"] if d["light"] else None, 80)


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
        skin = themes.current_skin()
        rect = QRectF(self.rect())
        top, bottom = self.insets()
        if skin == "tile":
            return rect.adjusted(8 + 12, top, -8 - 12, -bottom)
        return rect.adjusted(6 + 12, top, -6 - 12, -bottom)

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

    def insets(self) -> tuple:
        """(top, bottom): the card's edge, shadow and padding above the header and below the last lane."""
        return (4 + 10, 16 + 16) if themes.current_skin() == "tile" else (4 + 10, 10 + 10)

    def fit(self) -> None:
        """As tall as the header and the lanes need, and no taller (0.11.6: a fixed extra left an empty band at the bottom)."""
        rows = len(self.lanes())
        top, bottom = self.insets()
        lanes = rows * (LANE_H + 6) - 6 if rows else 0
        self.setFixedSize(self.WIDTH, top + self.header_height() + lanes + bottom)

    def state(self) -> tuple:
        return (
            themes.current_skin(),
            themes.generation(),
            tuple((m, round(db, 1), muted, round(live * 16)) for m, _l, _i, db, muted, live in self.lanes()),
        )

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

    def hover(self, point: QPointF) -> None:
        _mix, part, _groove = self._lane_at(point)
        wanted = Qt.CursorShape.PointingHandCursor if part else Qt.CursorShape.OpenHandCursor
        if self.cursor().shape() != wanted:
            self.setCursor(wanted)

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
        from .ui_base import db_to_fader_position, format_level

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tint = self.tint()
        paint_card(self, p, tint)
        inner = self._inner()
        self.paint_header(p, inner)
        font = QFont(self.font())
        font.setPixelSize(12)
        for (mix_id, label, icon, db, muted, live), row, mute, groove in self._rows():
            paint_icon_button(p, mute, icon, themes.color("text2"), muted, muted)
            paint_lane(p, groove, db_to_fader_position(db), live, muted, tint)
            p.setFont(font)
            p.setPen(QColor(themes.color("mute_fg") if muted else themes.color("text")))
            p.drawText(
                QRectF(groove.right() + 6, row.top(), 58, row.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "Muted" if muted else format_level(db, narrow=True),
            )
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
        from . import depth, skin_tile

        channel = self.channel()
        if channel is None:
            return themes.color("accent")
        base = skin_tile.channel_color(channel) if themes.current_skin() == "tile" else channel.color
        return depth.channel_tint(base, themes._current)

    def lanes(self) -> list:
        from .ui_base import MIX_ICONS

        channel = self.channel()
        if channel is None:
            return []
        levels = self.engine.sample_levels(0.05)
        from .ui_base import level_fraction

        return [
            (
                m.id,
                m.label,
                MIX_ICONS.get(m.id, "speaker"),
                channel.levels.get(m.id, 0.0),
                bool(channel.mutes.get(m.id)),
                level_fraction(levels.get(f"ch:{channel.id}:{m.id}", 0.0)),
            )
            for m in self.engine.mixer.mixes
        ]

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
        if channel is not None:  # 0.12.2: the channel's drawing in its tinted tile, as on the cards and in the compact list
            from . import skin_tile, ui_icons as icons

            ratio = p.device().devicePixelRatioF() if p.device() is not None else 1.0
            drawing = icons.render(skin_tile.channel_icon(channel), tint.name(), round(16 * ratio))
            drawing.setDevicePixelRatio(ratio)
            p.drawPixmap(QPointF(well.center().x() - 8, well.center().y() - 8), drawing)
        else:
            p.setPen(tint)
            p.drawText(well, Qt.AlignmentFlag.AlignCenter, "?")
        p.setPen(QColor(themes.color("text")))
        name = channel.label if channel is not None else "This channel was removed"
        p.drawText(QRectF(well.right() + 10, inner.top(), inner.width() - 34, 24), Qt.AlignmentFlag.AlignVCenter, name)


class MixWidget(LaneWidget):
    """One mix on the desktop: Listen or Broadcast (or Recording), its level, Mute and the Limiter."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        self.setToolTip(
            "Drag or scroll the slider to change the level; click the speaker to mute, the Limiter to switch it. "
            "Drag the card to move it."
        )

    def mix(self):
        return next((m for m in self.engine.mixer.mixes if m.id == self.spec.get("mix")), None) or (
            self.engine.mixer.mixes[0] if self.engine.mixer.mixes else None
        )

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
        label = mix.label if mix else "Mix"
        p.drawText(
            QRectF(inner.left() + 30, inner.top(), inner.width() - 100, 24),
            Qt.AlignmentFlag.AlignVCenter,
            label,
        )
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
        self._dressing = None  # (what it was worked out for, (skin, colours))

    def dressing(self) -> tuple:
        """(skin, colours) the widgets draw in, or (None, None) when they look like the window (the default). Settings > Themes and
        skins > Desktop widgets (0.11.6). Worked out once per change: it is asked on every event and meter frame."""
        mixer = self.window.engine.mixer
        skin, theme_id = getattr(mixer, "widget_skin", ""), getattr(mixer, "widget_theme", "")
        if not skin and not theme_id:
            return None, None
        key = (skin, theme_id, mixer.skin, mixer.theme, themes.skin_colors_on())
        if self._dressing is None or self._dressing[0] != key:
            skin = themes.valid_skin(skin or mixer.skin)
            window = self.window
            theme = (
                themes.resolve(theme_id, window._system_is_dark(), window._themes_folder())
                if theme_id
                else window.current_theme()
            )
            self._dressing = (key, (skin, themes.skin_colors(theme, skin)))
        return self._dressing[1]

    @property
    def specs(self) -> list:
        return self.window.engine.mixer.desktop_widgets

    def is_open(self, kind: str, mix=None, channel=None) -> bool:
        return (kind, mix, channel) in self.open_widgets

    def reopen(self, spec: dict) -> bool:
        """Open a widget again from its saved description, places on each screen included (Ctrl+Shift+W)."""
        spec = clean_spec(spec)
        if spec is None or _key(spec) in self.open_widgets or len(self.specs) >= MAX_WIDGETS:
            return spec is not None and _key(spec) in self.open_widgets
        self._show(spec)
        self.specs.append(spec)
        return True

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
            with themes.dressed_as(*self.dressing()):
                fit()
        app = QApplication.instance()
        screens = {}
        for screen in app.screens() if app is not None else []:
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
        if not widget.layered and hasattr(self.window, "hint_missing_part"):
            self.window.hint_missing_part("layershell")  # once, and only on Plasma (Wayland) without LayerShellQt
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
        ask = ui_dialog.question(
            self.window,
            "Keep widgets on top",
            "On KDE Plasma under Wayland, a window cannot keep itself on top. Sluice can add a KWin window rule "
            "(System Settings > Window Management > Window Rules) that keeps its desktop widgets above other "
            "windows. You can remove it there at any time.\n\nAdd the rule?",
        )
        if ask != QMessageBox.StandardButton.Yes:
            return
        problem = desktop_place.add_kwin_rule()
        self.window.say(problem or "Added a KWin rule: Sluice's desktop widgets stay above other windows.")

    def restyle(self) -> None:
        """The look or the colours changed (the window's, or the widgets' own): every open widget follows."""
        self._dressing = None
        skin, colors = self.dressing()
        for widget in self.open_widgets.values():
            restyle = getattr(widget, "restyle", None)
            with themes.dressed_as(skin, colors):
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
