# SPDX-License-Identifier: GPL-3.0-or-later
"""The gate, compressor, limiter and high-pass of 0.12.0 (voicefx.py; the high-pass in the Rust engine)."""
import math

import numpy as np
import pytest

from sluice.voicefx import CeilingLimiter, LinkedCompressor, VoiceGate

SR = 48000


def tone(hz, seconds, level_db, right_db=None):
    t = np.arange(int(SR * seconds)) / SR
    left = 10 ** (level_db / 20) * np.sin(2 * np.pi * hz * t)
    right = left if right_db is None else 10 ** (right_db / 20) * np.sin(2 * np.pi * hz * t)
    return np.vstack([left, right]).astype(np.float32)


def run(processor, audio, block=1024):
    return np.hstack([processor.process(audio[:, i:i + block]) for i in range(0, audio.shape[1], block)])


def peak_db(audio):
    return 20 * math.log10(float(np.max(np.abs(audio))) + 1e-12)


def test_the_limiter_holds_its_ceiling_and_adds_nothing_below_it():
    """0.11 copied pedalboard's limiter: make-up gain after limiting pushed peaks to full scale (and clipped)."""
    limiter = CeilingLimiter(SR)
    limiter.threshold_db = -2.0
    loud = run(limiter, tone(200, 0.5, 6.0))
    assert peak_db(loud) <= -2.0 + 0.01  # never past the ceiling, even 8 dB over it
    quiet_in = tone(200, 0.5, -12.0)
    limiter2 = CeilingLimiter(SR)
    limiter2.threshold_db = -2.0
    assert np.allclose(run(limiter2, quiet_in), quiet_in, atol=1e-6)  # under it: untouched (no hidden make-up, no compressor)


def test_the_compressor_keeps_a_stereo_sound_where_it_is():
    """Left and right are followed together: a sound louder on the left is turned down on both sides alike."""
    comp = LinkedCompressor(SR)
    comp.threshold_db, comp.ratio, comp.makeup_db = -20.0, 4.0, 0.0
    out = run(comp, tone(300, 1.0, -4.0, right_db=-16.0))
    tail = out[:, SR // 2:]
    left, right = peak_db(tail[:1]), peak_db(tail[1:])
    assert left < -4.0 - 6  # turned down a lot...
    assert abs((left - right) - 12.0) < 0.2  # ...and the 12 dB between the sides is kept


def test_the_compressor_has_a_soft_knee_and_the_right_slope():
    comp = LinkedCompressor(SR)
    comp.threshold_db, comp.ratio = -20.0, 4.0
    assert comp.reduction(-30.0) == 0.0
    assert -0.6 < comp.reduction(-20.0) < 0.0  # at the threshold: already easing in
    assert comp.reduction(-8.0) == pytest.approx(-9.0)  # 12 dB over at 4:1: 3 dB over, 9 dB off


def test_the_gate_holds_open_between_words_and_does_not_flutter():
    gate = VoiceGate(SR)
    gate.threshold_db, gate.depth_db, gate.hold_ms = -40.0, 24.0, 120.0
    voice = tone(200, 0.4, -20.0)
    pause = tone(200, 0.08, -60.0)  # a short gap between words: shorter than the hold
    room = tone(200, 0.6, -60.0)
    out = run(gate, np.hstack([voice, pause, voice, room]))
    gap = out[:, voice.shape[1]:voice.shape[1] + pause.shape[1]]
    assert peak_db(gap) > -61.0  # held open over the short gap: the word endings are not cut
    end = out[:, -SR // 5:]
    assert peak_db(end) < -60.0 - 20  # the room after the voice is turned down by about the depth
    hover = VoiceGate(SR)
    hover.threshold_db, hover.hold_ms = -40.0, 0.0
    run(hover, tone(200, 0.3, -20.0))
    t = np.arange(int(SR * 0.5)) / SR  # then a level hovering 1-3 dB under the threshold: stays open (hysteresis)
    wobble = (10 ** ((-42 + np.sin(2 * np.pi * 7 * t)) / 20) * np.sin(2 * np.pi * 200 * t) * math.sqrt(2))
    out = run(hover, np.vstack([wobble, wobble]).astype(np.float32))
    assert hover.activity_db == 0.0 and peak_db(out[:, -2000:]) > -45


def test_the_effects_run_in_a_chain_with_their_saved_settings():
    from sluice.effects import BUILTINS, EffectInstance, PlainStage
    from sluice.model import Effect
    for kind in ("noise_gate", "compressor", "limiter"):
        instance = EffectInstance(Effect("x", "builtin", BUILTINS[kind].name, type=kind, params={}))
        assert instance.usable and isinstance(instance.stage, PlainStage), (kind, instance.error)
    old_gate = EffectInstance(Effect("g", "builtin", "Noise Gate", type="noise_gate", params={"threshold_db": -60, "ratio": 4}))
    assert old_gate.usable and old_gate.effect.params["threshold_db"] == -60 and "depth_db" in old_gate.effect.params


def test_the_high_pass_is_a_butterworth_when_the_engine_has_one():
    sluice_dsp = pytest.importorskip("sluice_dsp")
    if not hasattr(sluice_dsp, "ButterworthHighPass"):
        pytest.skip("the Rust engine here is older than 0.11.0")
    hp = sluice_dsp.ButterworthHighPass(100.0)
    for hz, want in ((100, -3.01), (50, -12.3), (1000, 0.0)):
        out = hp.process(tone(hz, 1.0, 0.0), SR)
        assert peak_db(out[:, SR // 2:]) == pytest.approx(want, abs=0.15)


def test_a_limited_voice_is_not_limited_a_second_time_by_the_mix():
    """Item 5 of 0.12.0: the voice limiter's ceiling (-2) sits under the mix limiter's, so the mix limiter stays idle for a voice."""
    from sluice.dsp import LIMITER_CEILING_DB, PeakLimiter
    assert LIMITER_CEILING_DB > -2.0
    voice = CeilingLimiter(SR)
    limited = run(voice, tone(200, 0.5, 6.0))
    assert np.allclose(run(PeakLimiter(SR), limited), limited, atol=1e-6)
