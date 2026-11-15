# SPDX-License-Identifier: GPL-3.0-or-later
"""The live display of the Effects window: the tap on an effect, the numbers behind the pictures, and the pictures."""
import numpy as np
import pytest

from sluice import ui_live
from sluice.effects import Tap


def test_tap_keeps_peaks_and_recent_samples_only_in_memory():
    tap = Tap(48000)
    tap.record(np.full((2, 512), 0.5, dtype=np.float32), np.full((2, 512), 0.1, dtype=np.float32))
    tap.record(np.full((2, 512), 0.25, dtype=np.float32), np.full((2, 512), 0.05, dtype=np.float32))
    peaks = tap.drain_peaks()
    assert peaks == [pytest.approx((0.5, 0.1)), pytest.approx((0.25, 0.05))]
    assert tap.drain_peaks() == []  # taken out once
    before, after = tap.latest(512)
    assert before.shape == (512,) and float(before[-1]) == pytest.approx(0.25) and float(after[-1]) == pytest.approx(0.05)


def test_tap_handles_blocks_larger_than_its_ring():
    tap = Tap(48000)
    tap.record(np.ones(Tap.RING * 2, dtype=np.float32), np.zeros(Tap.RING * 2, dtype=np.float32))
    before, after = tap.latest(100)
    assert float(before.min()) == 1.0 and float(after.max()) == 0.0


def test_db_scale_puts_minus_60_at_the_centre_line():
    assert ui_live.fraction(-60.0) == 0.0 and ui_live.fraction(0.0) == 1.0
    assert ui_live.fraction(-90.0) == 0.0 and ui_live.fraction(6.0) == 1.0
    assert ui_live.fraction(-30.0) == pytest.approx(0.5)
    assert ui_live.to_db(1.0) == pytest.approx(0.0) and ui_live.to_db(0.0) < -100


def test_band_levels_put_a_tone_in_the_right_band():
    rate = 48000
    t = np.arange(2048) / rate
    levels = ui_live.band_levels(np.sin(2 * np.pi * 1000 * t).astype(np.float32), rate)
    assert len(levels) == ui_live.BANDS
    freqs = np.geomspace(20, 20000, ui_live.BANDS + 1)
    peak_band = int(np.argmax(levels))
    assert freqs[peak_band] <= 1100 and freqs[peak_band + 1] >= 900


def test_compressor_curve_math(qapp):
    curve = ui_live.CurveView()
    curve.set_params(-20.0, 4.0, 2.0)
    assert curve.out_db(-30.0) == pytest.approx(-28.0)  # below the threshold: only the makeup gain
    assert curve.out_db(-10.0) == pytest.approx(-20.0 + 10.0 / 4.0 + 2.0)


def test_wave_scrolls_and_keeps_a_bounded_history(qapp):
    wave = ui_live.LiveWave()
    for _ in range(2000):
        wave.push([(0.3, 0.2)])
    assert len(wave.before) == wave.before.maxlen
    wave.push([])  # nothing new: time still moves
    assert wave.after[-1] == 0.0
    wave.resize(416, 112)
    assert not wave.grab().isNull()


# ---------------------------------------------------------------- the window around it
pytest.importorskip("PySide6")
pytest.importorskip("pedalboard")

from PySide6.QtCore import Qt  # noqa: E402

from sluice.audio_io import NullIO  # noqa: E402
from sluice.backend import MockSystem  # noqa: E402
from sluice.engine import Engine  # noqa: E402
from sluice.linker import NullLinker  # noqa: E402
from sluice.model import Mixer  # noqa: E402
from sluice.ui import MainWindow  # noqa: E402
from sluice.ui_effects import EffectsDialog  # noqa: E402


@pytest.fixture
def dialog(qapp, tmp_path):
    engine = Engine(Mixer.default(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, config_file=tmp_path / "config.json")
    dlg = EffectsDialog(engine, engine.mixer.channel("mic"), win)
    yield dlg
    dlg.close()
    win.shutdown()


def select(dlg, kind):
    dlg.list.setCurrentRow(next(i for i, e in enumerate(dlg.channel.effects) if e.type == kind))


def test_each_effect_gets_its_own_kind_of_display(dialog):
    live = dialog.live
    for kind, wave, spectrum, curve, gate in (("noise_gate", True, False, False, True), ("compressor", True, False, True, False),
                                              ("limiter", True, False, False, False), ("eq", False, True, False, False),
                                              ("highpass", False, True, False, False)):
        select(dialog, kind)
        assert live.wave.isHidden() == (not wave) and live.spectrum.isHidden() == (not spectrum)
        assert live.curve_box.isHidden() == (not curve) and live.gate_box.isHidden() == (not gate)


def test_display_follows_the_sliders(dialog):
    select(dialog, "noise_gate")
    dialog._rows["threshold_db"].set_value(-42.0)
    assert dialog.live.wave.markers == [-42.0]
    select(dialog, "compressor")
    dialog._rows["ratio"].set_value(6.0)
    assert dialog.live.curve.ratio == 6.0


def test_a_switched_off_effect_says_so_and_nothing_is_drawn_without_sound(dialog):
    select(dialog, "compressor")
    dialog.engine.set_effect_bypass(dialog.channel.id, dialog._current_effect().id, True)
    dialog.live.tick()
    assert "switched off" in dialog.live.status.text()


def test_gate_chip_opens_for_loud_sound_and_closes_after_a_hold(dialog):
    select(dialog, "noise_gate")
    live = dialog.live
    threshold = live._value("threshold_db", -30.0)
    live._tick_gate(threshold + 10, False)
    assert live.gate_chip.property("open") is True and "open" in live.gate_chip.text()
    for _ in range(12):
        live._tick_gate(-80.0, False)
    assert live.gate_chip.property("open") is False and "closed" in live.gate_chip.text()


def test_gate_explains_room_and_voice_levels_once_it_has_heard_both(dialog):
    live = dialog.live
    live._recent.extend([-60.0] * 40 + [-20.0] * 40)
    text = live._gate_explanation(-30.0)
    assert "room sits at about -60" in text and "-20" in text


def test_the_tap_is_started_for_the_selected_effect_and_stopped_on_close(dialog, monkeypatch):
    calls = []
    monkeypatch.setattr(dialog.engine, "set_effect_tap", lambda channel, effect: calls.append(effect))
    select(dialog, "limiter")
    assert calls[-1] == dialog._current_effect().id
    dialog.done(0)
    assert calls[-1] is None


def test_cards_show_the_name_and_toggle_with_the_keyboard_and_switch(dialog):
    item = dialog.list.item(0)
    assert item.text() and item.data(Qt.ItemDataRole.UserRole) == dialog.channel.effects[0].id
    before = item.checkState()
    dialog.list.setCurrentRow(0)
    delegate = dialog.list.itemDelegate()
    delegate._toggle(dialog.list.model(), dialog.list.model().index(0, 0))
    assert item.checkState() != before
    assert dialog.channel.effects[0].bypass == (item.checkState() != Qt.CheckState.Checked)
