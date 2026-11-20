"""Desktop widgets: small borderless windows you can leave on the desktop (a microphone mute button, a volume dial, a compact list of
channels) so the big window can stay closed. They draw themselves and ask the engine for the shared meter reading, a few times a
second, only while they are shown and only repaint when something they show has changed."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from . import themes

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
        self.setAccessibleName(self.title())

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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._press is not None and (event.globalPosition().toPoint() - self._press).manhattanLength() > 6:
            self._press = None
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            self._press = None
            self.act()
            self.tick()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        top = menu.addAction("Keep on top")
        top.setCheckable(True)
        top.setChecked(self.on_top)
        top.triggered.connect(self.set_on_top)
        menu.addAction("Close this widget", lambda: self.manager.close_spec(self.spec))
        menu.exec(event.globalPos())

    def set_on_top(self, on: bool) -> None:
        self.on_top = bool(on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.on_top)
        self.show()

    def closeEvent(self, event) -> None:
        self.timer.stop()
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
        from .ui import db_to_fader_position

        db, muted, level = self._state or (0.0, False, 0)
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


class StripWidget(DesktopWidget):
    """The compact list of channels as a floating panel."""

    def __init__(self, manager, spec) -> None:
        super().__init__(manager, spec)
        from .ui_mini import MiniStrip

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("desktopstrip")
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.strip = MiniStrip(self.window_)
        if spec.get("mix"):
            self.strip.choose_mix(spec["mix"])
        layout.addWidget(self.strip)
        self.setFixedWidth(340)
        self.setMinimumHeight(180)
        self.setToolTip("Drag the empty space to move. Right-click for more.")
        self._ids = self._channel_ids()

    def title(self) -> str:
        return "Channel levels"

    def _channel_ids(self) -> tuple:
        return tuple(c.id for c in self.engine.mixer.channels)

    def state(self) -> tuple:
        if self._channel_ids() != self._ids:
            self._ids = self._channel_ids()
            self.strip.rebuild()
        self.strip.sync_from_model()
        return ()

    def mousePressEvent(self, event) -> None:
        child = self.childAt(event.position().toPoint())
        if child is None or child is self.strip:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = None

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(themes.color("border")), 1))
        p.setBrush(QColor(themes.color("bg")))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        p.end()


CLASSES = {"mic": MicWidget, "dial": DialWidget, "strip": StripWidget}


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
        if spec.get("x") is None or spec.get("y") is None:
            screen = self.window.screen().availableGeometry() if self.window.screen() else None
            n = len(self.open_widgets) - 1
            if screen is not None:
                spec["x"] = max(screen.left(), screen.right() - widget.width() - 24 - 20 * n)
                spec["y"] = screen.top() + 60 + 24 * n
            else:
                spec["x"], spec["y"] = 100 + 20 * n, 100 + 20 * n
        widget.move(spec["x"], spec["y"])
        widget.show()

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
