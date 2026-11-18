# SPDX-License-Identifier: GPL-3.0-or-later
"""The live display of the Effects window: your voice going in and coming out of the effect you are tuning.

Waveforms (grey = going in, accent = coming out) for the Noise Gate, Compressor and Limiter, with their own extras: the gate's
threshold and whether it is open, the compressor's curve with a dot for where your voice is now and a bar for how much it is
turned down, the limiter's ceiling. Frequency displays for the EQ, High-pass, Noise Reducer and Echo Reducer.

All of it is drawn from numbers Sluice already has in memory while this window is open and the effect is selected (see
``effects.Tap``). Nothing is recorded or stored. The displays are drawn about 30 times a second.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import presets, themes

log = logging.getLogger(__name__)

FLOOR_DB = -60.0       # the centre line of the waveform, the edge of the compressor curve
SPECTRUM_TOP = -30.0   # the spectrum shows band levels from here down to SPECTRUM_FLOOR
SPECTRUM_FLOOR = -100.0
BANDS = 96             # frequency bands between 20 Hz and 20 kHz, spaced evenly on a log scale
SPECTRUM_TYPES = ("eq", "highpass", "noise_reducer", "echo_reducer")
WAVE_TYPES = ("noise_gate", "compressor", "limiter")


def to_db(linear: float) -> float:
    return 20.0 * math.log10(max(float(linear), 1e-6))


def fraction(db: float, floor: float = FLOOR_DB) -> float:
    """0 at ``floor`` dB (and below) and 1 at 0 dB."""
    return max(0.0, min(1.0, (db - floor) / (0.0 - floor)))


def going_in_color() -> QColor:
    """The grey of 'going in': quieter than the text, clearly different from the accent."""
    return QColor(themes.mix(themes.color("text_dim"), themes.color("meter_bg"), 0.4))


def band_levels(samples: np.ndarray, rate: int, bands: int = BANDS) -> np.ndarray:
    """Level of each of ``bands`` log-spaced frequency bands (20 Hz to 20 kHz) in dB, for a block of samples."""
    n = len(samples)
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64) * np.hanning(n))) / (n / 4.0)  # a full-scale sine reads 1.0
    power = spectrum ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    edges = np.geomspace(20.0, min(20000.0, rate / 2.0 - 1.0), bands + 1)
    out = np.empty(bands)
    for i in range(bands):
        low, high = np.searchsorted(freqs, edges[i]), np.searchsorted(freqs, edges[i + 1])
        if high > low:
            value = float(power[low:high].mean())
        else:  # narrower than one bin: take the bin it falls in
            value = float(power[min(len(power) - 1, low)])
        out[i] = 10.0 * math.log10(value + 1e-12)
    return out


def _frame_path(rect: QRectF, radius: float = 12.0) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class LiveWave(QWidget):
    """Your voice as a waveform: loudness on a dB scale (the centre line is -60 dB, the edges 0 dB), the last few seconds
    scrolling to the left. Grey is the sound going into the effect, the accent colour what comes out."""

    COLUMN = 2  # pixels per column

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(112)
        self.setFixedHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.before: deque = deque(maxlen=512)
        self.after: deque = deque(maxlen=512)
        self.markers: list = []  # dB values drawn as dashed lines above and below the centre line
        self.setAccessibleName("Live waveform of your voice before and after this effect")

    def clear(self) -> None:
        self.before.clear()
        self.after.clear()
        self.update()

    def set_markers(self, db_values: list) -> None:
        if db_values != self.markers:
            self.markers = list(db_values)
            self.update()

    def push(self, peaks: list) -> None:
        """One new column from the block peaks since the last call (nothing new: a flat column, so time still moves)."""
        if peaks:
            self.before.append(max(p[0] for p in peaks))
            self.after.append(max(p[1] for p in peaks))
        else:
            self.before.append(0.0)
            self.after.append(0.0)
        self.update()

    def _shape(self, values, width: float, mid: float, half: float) -> QPolygonF:
        n = len(values)
        top, bottom = [], []
        for i, value in enumerate(values):
            x = width - (n - 1 - i) * self.COLUMN
            h = fraction(to_db(value)) * half
            top.append(QPointF(x, mid - h))
            bottom.append(QPointF(x, mid + h))
        return QPolygonF(top + bottom[::-1])

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setClipPath(_frame_path(rect))
        p.fillRect(rect, QColor(themes.color("meter_bg")))
        mid, half = rect.height() / 2.0, rect.height() / 2.0 - 4
        p.setPen(QPen(QColor(themes.color("border")), 1))
        p.drawLine(QPointF(0, mid), QPointF(rect.width(), mid))
        p.setPen(Qt.PenStyle.NoPen)
        grey = going_in_color()
        grey.setAlpha(200)
        p.setBrush(grey)
        p.drawPolygon(self._shape(self.before, rect.width(), mid, half))
        accent = QColor(themes.color("accent"))
        accent.setAlpha(220)
        p.setBrush(accent)
        p.drawPolygon(self._shape(self.after, rect.width(), mid, half))
        pen = QPen(QColor(themes.color("link")), 1.5, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        for db in self.markers:
            offset = fraction(db) * half
            p.drawLine(QPointF(0, mid - offset), QPointF(rect.width(), mid - offset))
            p.drawLine(QPointF(0, mid + offset), QPointF(rect.width(), mid + offset))
        p.end()


class LiveSpectrum(QWidget):
    """Your voice by pitch: low sounds on the left, high on the right. Grey going in, the accent colour coming out."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.before: Optional[np.ndarray] = None
        self.after: Optional[np.ndarray] = None
        self.markers: list = []  # Hz, drawn as dashed vertical lines
        self.rate = 48000
        self.setAccessibleName("Live frequency display of your voice before and after this effect")

    def clear(self) -> None:
        self.before = self.after = None
        self.update()

    def set_markers(self, hz_values: list) -> None:
        if hz_values != self.markers:
            self.markers = list(hz_values)
            self.update()

    def set_levels(self, before: np.ndarray, after: np.ndarray) -> None:
        # a little smoothing so the picture glides instead of flickering
        self.before = before if self.before is None else 0.6 * self.before + 0.4 * before
        self.after = after if self.after is None else 0.6 * self.after + 0.4 * after
        self.update()

    def _x(self, hz: float, width: float) -> float:
        top = min(20000.0, self.rate / 2.0 - 1.0)
        return width * (math.log10(max(hz, 20.0)) - math.log10(20.0)) / (math.log10(top) - math.log10(20.0))

    def _polygon(self, levels: np.ndarray, width: float, height: float) -> QPolygonF:
        points = [QPointF(0, height)]
        for i, db in enumerate(levels):
            y = height - 4 - max(0.0, min(1.0, (db - SPECTRUM_FLOOR) / (SPECTRUM_TOP - SPECTRUM_FLOOR))) * (height - 24)
            points.append(QPointF(width * (i + 0.5) / len(levels), y))
        points.append(QPointF(width, height))
        return QPolygonF(points)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setClipPath(_frame_path(rect))
        p.fillRect(rect, QColor(themes.color("meter_bg")))
        width, height = rect.width(), rect.height() - 16  # the strip under the picture holds the pitch labels
        font = QFont(self.font())
        font.setPixelSize(12)
        p.setFont(font)
        grid = QPen(QColor(themes.color("border")), 1)
        for hz, label in ((100, "100 Hz"), (1000, "1 kHz"), (10000, "10 kHz")):
            x = self._x(hz, width)
            p.setPen(grid)
            p.drawLine(QPointF(x, 0), QPointF(x, height))
            p.setPen(QColor(themes.color("text_dim")))
            metrics = QFontMetrics(font)
            p.drawText(QPointF(min(width - metrics.horizontalAdvance(label) - 4, x + 4), rect.height() - 4), label)
        if self.before is not None:
            grey = going_in_color()
            grey.setAlpha(190)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grey)
            p.drawPolygon(self._polygon(self.before, width, height))
        if self.after is not None:
            fill = QColor(themes.color("accent"))
            fill.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            polygon = self._polygon(self.after, width, height)
            p.drawPolygon(polygon)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(themes.color("accent")), 2))
            p.drawPolyline(polygon.mid(1, polygon.size() - 2) if hasattr(polygon, "mid") else polygon)
        pen = QPen(QColor(themes.color("link")), 1.5, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        for hz in self.markers:
            x = self._x(hz, width)
            p.drawLine(QPointF(x, 0), QPointF(x, height))
        p.end()


class CurveView(QWidget):
    """The compressor's curve: the level coming in (across) against the level going out (up), -60 to 0 dB. The dashed diagonal
    is 'no change', the blue line the threshold, the white dot where your voice is right now."""

    SIZE = 160

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self.threshold, self.ratio, self.makeup = -18.0, 3.0, 0.0
        self.dot: Optional[tuple] = None  # (in dB, out dB)
        self.setAccessibleName("Compressor curve")

    def set_params(self, threshold: float, ratio: float, makeup: float) -> None:
        self.threshold, self.ratio, self.makeup = threshold, max(1.0, ratio), makeup
        self.setAccessibleDescription(f"Sound above {threshold:.0f} dB is turned down at a {ratio:.1f} to 1 ratio")
        self.update()

    def set_dot(self, dot: Optional[tuple]) -> None:
        self.dot = dot
        self.update()

    def out_db(self, in_db: float) -> float:
        over = max(0.0, in_db - self.threshold)
        return in_db - over + over / self.ratio + self.makeup

    def _pos(self, in_db: float, out_db: float) -> QPointF:
        s = float(self.SIZE)
        return QPointF(fraction(in_db) * s, s - fraction(out_db) * s)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setClipPath(_frame_path(rect))
        p.fillRect(rect, QColor(themes.color("meter_bg")))
        s = float(self.SIZE)
        p.setPen(QPen(QColor(themes.color("border")), 1))
        for i in (1, 2, 3):
            p.drawLine(QPointF(s * i / 4, 0), QPointF(s * i / 4, s))
            p.drawLine(QPointF(0, s * i / 4), QPointF(s, s * i / 4))
        diagonal = QPen(QColor(themes.color("line")), 1.5, Qt.PenStyle.CustomDashLine)
        diagonal.setDashPattern([5, 5])
        p.setPen(diagonal)
        p.drawLine(QPointF(0, s), QPointF(s, 0))
        marker = QPen(QColor(themes.color("link")), 1.5, Qt.PenStyle.CustomDashLine)
        marker.setDashPattern([3, 4])
        p.setPen(marker)
        x = fraction(self.threshold) * s
        p.drawLine(QPointF(x, 0), QPointF(x, s))
        curve = QPolygonF([self._pos(db, self.out_db(db)) for db in (FLOOR_DB, self.threshold, 0.0)])
        p.setPen(QPen(QColor(themes.color("accent")), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(curve)
        if self.dot is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(themes.color("handle")))
            p.drawEllipse(self._pos(*self.dot), 6, 6)
        p.end()


class ReductionBar(QWidget):
    """A thin bar for 'how much your voice is being turned down right now' (0 to 24 dB)."""

    FULL_DB = 24.0

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(8)
        self.value = 0.0
        self.setAccessibleName("Gain reduction")

    def set_value(self, db: float) -> None:
        self.value = max(0.0, min(self.FULL_DB, db))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(themes.color("meter_bg")))
        p.drawRoundedRect(rect, 4, 4)
        p.setBrush(QColor(themes.color("accent")))
        p.drawRoundedRect(QRectF(0, 0, rect.width() * self.value / self.FULL_DB, rect.height()), 4, 4)
        p.end()


def _caption(text: str = "", name: str = "hint") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class LivePanel(QFrame):
    """"YOUR VOICE, LIVE": the display that goes with the effect selected in the Effects window."""

    def __init__(self, engine, channel) -> None:
        super().__init__()
        self.setObjectName("livepanel")
        self.engine, self.channel = engine, channel
        self.effect = None
        self.kind = ""
        self._ticks = 0
        self._recent = deque(maxlen=240)       # about 8 seconds of "how loud is it going in", for the room and voice levels
        self._smooth_in = FLOOR_DB
        self._smooth_out = FLOOR_DB
        self._reduction = 0.0
        self._gate_hold = 0
        self._last_sound = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        head = QHBoxLayout()
        head.setSpacing(16)
        heading = QLabel("YOUR VOICE, LIVE")
        heading.setObjectName("tag")
        head.addWidget(heading, 1)
        for text, who in (("Going in", "in"), ("Coming out", "out")):
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setProperty("who", who)
            swatch.setObjectName("swatch")
            head.addWidget(swatch)
            head.addWidget(_caption(text, "chiptext"))
        layout.addLayout(head)

        self.wave = LiveWave()
        self.spectrum = LiveSpectrum()
        layout.addWidget(self.wave)
        layout.addWidget(self.spectrum)

        self.curve_box = QWidget()
        curve = QHBoxLayout(self.curve_box)
        curve.setContentsMargins(0, 0, 0, 0)
        curve.setSpacing(24)
        self.curve = CurveView()
        curve.addWidget(self.curve, 0, Qt.AlignmentFlag.AlignTop)
        side = QVBoxLayout()
        side.setSpacing(8)
        side.addWidget(_caption("Turning you down right now", "chiptext"))
        self.reduction_label = QLabel("0.0 dB")
        self.reduction_label.setObjectName("bigvalue")
        side.addWidget(self.reduction_label)
        self.reduction_bar = ReductionBar()
        side.addWidget(self.reduction_bar)
        side.addWidget(_caption("The white dot shows where your voice is on the curve."))
        side.addStretch(1)
        curve.addLayout(side, 1)
        layout.addWidget(self.curve_box)

        self.gate_box = QWidget()
        gate = QVBoxLayout(self.gate_box)
        gate.setContentsMargins(0, 0, 0, 0)
        gate.setSpacing(16)
        self.gate_chip = QLabel("")
        self.gate_chip.setObjectName("gatechip")
        gate.addWidget(self.gate_chip, 0, Qt.AlignmentFlag.AlignLeft)
        self.gate_text = _caption("", "feedback")
        gate.addWidget(self.gate_text)
        layout.addWidget(self.gate_box)

        self.note = _caption("", "feedback")
        layout.addWidget(self.note)
        self.status = _caption("", "hint")
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.show_effect(None)

    # ---------------------------------------------------------------- which effect
    def show_effect(self, effect) -> None:
        self.effect = effect
        self.kind = effect.type if effect is not None and effect.kind == "builtin" else ""
        spectrum = self.kind in SPECTRUM_TYPES
        self.wave.setVisible(not spectrum)
        self.spectrum.setVisible(spectrum)
        self.curve_box.setVisible(self.kind == "compressor")
        self.gate_box.setVisible(self.kind == "noise_gate")
        self.wave.clear()
        self.spectrum.clear()
        self._recent.clear()
        self._reduction = 0.0
        self._gate_hold = 0
        self.wave.set_markers([])
        self.spectrum.set_markers([])
        notes = {
            "limiter": "The dashed lines are the ceiling. Nothing coming out goes above them.",
            "highpass": "Low sounds are on the left, high ones on the right. Everything left of the dashed line is turned down: "
                        "that is rumble from fans and desks.",
            "eq": "Low sounds are on the left, high ones on the right. The dashed lines mark the three bands you are shaping.",
            "noise_reducer": "Steady noise such as a fan or hiss sits as a flat grey layer. Watch it drop while you talk.",
            "echo_reducer": "The tail of your room's echo shows as grey that lingers after you stop. It should be lower coming out.",
            "gain": "Louder or quieter, before the other effects.",
        }
        self.note.setText(notes.get(self.kind, "Your voice before and after this effect." if effect is not None else ""))
        self.note.setVisible(self.kind not in ("noise_gate", "compressor"))
        self._update_params()
        self.tick()

    def _value(self, key: str, default: float) -> float:
        try:
            return float(presets.current_value(self.effect, key))
        except Exception as exc:  # an effect without that setting: draw with the default
            log.debug("no value for %s: %s", key, exc)
            return default

    def _update_params(self) -> None:
        if self.effect is None:
            return
        if self.kind == "noise_gate":
            self.wave.set_markers([self._value("threshold_db", -30.0)])
        elif self.kind == "limiter":
            self.wave.set_markers([self._value("threshold_db", -2.0)])
        elif self.kind == "compressor":
            self.curve.set_params(self._value("threshold_db", -18.0), self._value("ratio", 3.0), self._value("makeup_db", 0.0))
        elif self.kind == "highpass":
            self.spectrum.set_markers([self._value("cutoff_frequency_hz", 100.0)])
        elif self.kind == "eq":
            self.spectrum.set_markers([self._value("low_hz", 120.0), self._value("mid_hz", 250.0), self._value("high_hz", 10000.0)])

    def parameters_changed(self) -> None:
        """A slider moved: redraw the lines that depend on it."""
        self._update_params()

    # ---------------------------------------------------------------- the picture, about 30 times a second
    def tick(self) -> None:
        self._ticks += 1
        self._update_params()
        tap = self.engine.effect_tap(self.channel.id) if self.effect is not None else None
        peaks = tap.drain_peaks() if tap is not None else []
        if self.wave.isVisible():
            self.wave.push(peaks)
        in_db = max((to_db(p[0]) for p in peaks), default=FLOOR_DB)
        out_db = max((to_db(p[1]) for p in peaks), default=FLOOR_DB)
        self._recent.append(in_db)
        if in_db > FLOOR_DB + 5:
            self._last_sound = self._ticks
        quiet = self._ticks - self._last_sound > 60  # two seconds without sound going in
        if self.effect is None:
            self.status.setText("")
        elif self.effect.bypass:
            self.status.setText("This effect is switched off, so nothing changes. Switch it on to see it work.")
        elif tap is None:
            self.status.setText("The live display needs Sluice to be running with sound. Speak into your microphone.")
        elif quiet:
            self.status.setText("Waiting for sound. Speak into your microphone.")
        else:
            self.status.setText("")
        if self.spectrum.isVisible() and tap is not None and self._ticks % 2 == 0 and not quiet:
            before, after = tap.latest(2048)
            self.spectrum.rate = tap.rate
            self.spectrum.set_levels(band_levels(before, tap.rate), band_levels(after, tap.rate))
        if self.kind == "compressor":
            self._tick_compressor(in_db, out_db, quiet)
        elif self.kind == "noise_gate":
            self._tick_gate(in_db, quiet)

    def _tick_compressor(self, in_db: float, out_db: float, quiet: bool) -> None:
        if quiet:
            self._reduction *= 0.9
            self.curve.set_dot(None)
        else:
            if in_db > FLOOR_DB + 5:
                makeup = self._value("makeup_db", 0.0)
                self._reduction = 0.7 * self._reduction + 0.3 * max(0.0, in_db - out_db + makeup)
                self._smooth_in = 0.6 * self._smooth_in + 0.4 * in_db
                self._smooth_out = 0.6 * self._smooth_out + 0.4 * out_db
                self.curve.set_dot((self._smooth_in, self._smooth_out))
            else:
                self._reduction *= 0.9
        self.reduction_label.setText(f"{self._reduction:.1f} dB")
        self.reduction_bar.set_value(self._reduction)

    def _tick_gate(self, in_db: float, quiet: bool) -> None:
        threshold = self._value("threshold_db", -30.0)
        if in_db >= threshold:
            self._gate_hold = 10                      # stays "open" for a third of a second after the last loud block
        elif self._gate_hold:
            self._gate_hold -= 1
        opened = self._gate_hold > 0
        if quiet and not opened:
            self.gate_chip.setText("Gate closed: waiting for sound")
        else:
            self.gate_chip.setText("●  Gate open: hearing your voice" if opened else "Gate closed: keeping the room quiet")
        if self.gate_chip.property("open") != opened:
            self.gate_chip.setProperty("open", opened)
            self.gate_chip.style().unpolish(self.gate_chip)
            self.gate_chip.style().polish(self.gate_chip)
        self.gate_text.setText(self._gate_explanation(threshold))

    def _gate_explanation(self, threshold: float) -> str:
        values = [v for v in self._recent if v > -75]
        if len(values) < 45 or max(values) - min(values) < 12:
            return ("Talk, then stay quiet for a moment. The dashed lines are the threshold: keep them above your room's "
                    "background noise and below your quietest words.")
        ordered = sorted(values)
        room = ordered[int(len(ordered) * 0.1)]
        voice = ordered[int(len(ordered) * 0.95) - 1]
        return (f"Your room sits at about {room:.0f} dB and your voice peaks near {voice:.0f} dB. The dashed lines are the "
                "threshold. Keep it between the two: above the room, below your quietest words.")
