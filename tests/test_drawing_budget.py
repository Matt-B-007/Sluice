# SPDX-License-Identifier: GPL-3.0-or-later
"""The drawing budget (0.11.5): with every meter moving, a full window in any look draws a meter update in under 1.5 ms, and no
look costs more than twice what Calm cost in 0.11.4 (0.83 ms). Idle, with no sound, nothing is drawn at all.

Timings depend on the machine, so they are scaled by a small fixed drawing job measured first (about 21 ms on the machine the
budget was set on): a slower machine gets proportionally more time, never less."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402

from sluice import themes  # noqa: E402
from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402

BUDGET_MS = 1.5
CALM_0114_MS = 0.83
REFERENCE_MS = 21.0


def _machine_factor() -> float:
    pixmap = QPixmap(400, 400)
    best = 1e9
    for _ in range(5):
        start = time.perf_counter()
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(2000):
            p.setBrush(QColor(i % 255, 100, 200))
            p.drawRoundedRect(QRectF(i % 300, i % 280, 60, 40), 8, 8)
        p.end()
        best = min(best, (time.perf_counter() - start) * 1000)
    return max(1.0, best / REFERENCE_MS)


def _window(qapp, skin):
    mixer = Mixer.demo()
    mixer.skin, mixer.theme = skin, "dark"
    engine = Engine(mixer, MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, None)
    win.resize(1456, 900)
    win.show()
    win.meter_timer.stop()  # the test drives the meters itself
    for _ in range(5):
        qapp.processEvents()
    return win, engine


def _cost(qapp, win, engine, moving: bool) -> float:
    mixer = engine.mixer
    keys = [f"ch:{c.id}:{m.id}" for c in mixer.channels for m in mixer.mixes] + [f"mix:{m.id}" for m in mixer.mixes]
    frame = [0]
    engine.sample_levels = lambda *_a, **_k: {
        k: (0.2 + 0.6 * ((frame[0] + i) % 7) / 7) if moving else 0.0 for i, k in enumerate(keys)
    }
    best = 1e9
    for _ in range(3):
        start = time.perf_counter()
        for i in range(60):
            frame[0] = i
            win._update_meters()
            qapp.processEvents()
        best = min(best, (time.perf_counter() - start) / 60 * 1000)
    return best


@pytest.mark.parametrize("skin", list(themes.SKINS))
def test_a_meter_update_stays_within_the_budget_in_every_look(qapp, skin):
    factor = _machine_factor()
    win, engine = _window(qapp, skin)
    try:
        _cost(qapp, win, engine, True)  # warm up: pictures are drawn once and kept
        quiet = _cost(qapp, win, engine, False)
        moving = _cost(qapp, win, engine, True) - quiet
        limit = min(BUDGET_MS, 2 * CALM_0114_MS) * factor
        assert moving < limit, f"{skin}: {moving:.2f} ms a meter update (limit {limit:.2f} ms)"
    finally:
        win.shutdown()


def test_nothing_is_drawn_while_it_is_silent(qapp):
    from sluice import ui_meters

    win, engine = _window(qapp, "nexus")
    try:
        _cost(qapp, win, engine, False)
        painted = []
        original = ui_meters.LevelMeter.paintEvent
        ui_meters.LevelMeter.paintEvent = lambda self, event: (painted.append(self), original(self, event))
        try:
            _cost(qapp, win, engine, False)
        finally:
            ui_meters.LevelMeter.paintEvent = original
        assert painted == []
    finally:
        win.shutdown()


def test_switching_looks_themes_and_sizes_with_sound_playing_never_shows_a_blank_window(qapp):
    win, engine = _window(qapp, "calm")
    try:
        mixer = engine.mixer
        keys = [f"ch:{c.id}:{m.id}" for c in mixer.channels for m in mixer.mixes] + [f"mix:{m.id}" for m in mixer.mixes]
        engine.sample_levels = lambda *_a, **_k: {k: 0.6 for k in keys}
        for skin, theme, size in (
            ("nexus", "dark", (1456, 900)),
            ("tile", "light", (1100, 860)),
            ("glass", "paper", (1300, 800)),
            ("calm", "contrast", (900, 760)),
            ("nexus", "light", (1600, 900)),
            ("tile", "dark", (1456, 900)),
        ):
            win.choose_skin(skin)
            win.choose_theme(theme)
            win.resize(*size)
            for _ in range(4):
                win._update_meters()
                qapp.processEvents()
            image = win.grab().toImage()
            colours = {image.pixel(x, y) for x in range(0, image.width(), 37) for y in range(0, image.height(), 41)}
            assert len(colours) > 8, f"{skin}/{theme}: the window looks blank"
            assert win.strips and all(s.isVisible() for s in win.strips) or win.layout_mode == "mini"
    finally:
        win.shutdown()
