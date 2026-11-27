# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rust built-in effects must sound like the pedalboard ones they replace (skipped when the module is not built)."""

import os

import numpy as np
import pytest

rust = pytest.importorskip("sluice_dsp")
pb = pytest.importorskip("pedalboard")

from sluice.effects import EffectInstance, toolbox  # noqa: E402
from sluice.model import Effect, voice_chain_effects  # noqa: E402

SR = 48000


def signal(seconds=3.0, seed=5):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    env = 0.02 + 0.7 * (np.sin(2 * np.pi * 1.1 * t) > 0)
    left = np.sin(2 * np.pi * 180 * t) * env + 0.3 * np.sin(2 * np.pi * 3000 * t) * env + rng.normal(0, 0.01, n)
    right = np.sin(2 * np.pi * 210 * t) * env * 0.7 + rng.normal(0, 0.01, n)
    return np.stack([left, right]).astype(np.float32)


def run_pb(plugin, x, block=512):
    board = pb.Pedalboard([plugin])
    return np.concatenate(
        [np.asarray(board(np.ascontiguousarray(x[:, i : i + block]), SR, reset=False)) for i in range(0, x.shape[1], block)],
        axis=1,
    )


def run_rs(plugin, x, block=777):  # a different block size: the result must not depend on it
    return np.concatenate(
        [np.asarray(plugin.process(np.ascontiguousarray(x[:, i : i + block]), SR)) for i in range(0, x.shape[1], block)], axis=1
    )


Q = 0.7071067690849304
CASES = {
    "gain": (lambda: pb.Gain(gain_db=6.0), lambda: rust.Gain(gain_db=6.0), 1e-5),
    "highpass": (lambda: pb.HighpassFilter(cutoff_frequency_hz=120), lambda: rust.HighpassFilter(120), 1e-4),
    "lowshelf": (
        lambda: pb.LowShelfFilter(cutoff_frequency_hz=120, gain_db=-2),
        lambda: rust.LowShelfFilter(120, -2, Q),
        1e-3,
    ),  # float32 state in JUCE at 120 Hz: about -65 dB at worst
    "peak": (lambda: pb.PeakFilter(cutoff_frequency_hz=250, gain_db=-4, q=1.0), lambda: rust.PeakFilter(250, -4, 1.0), 1e-3),
    "highshelf": (
        lambda: pb.HighShelfFilter(cutoff_frequency_hz=10000, gain_db=1),
        lambda: rust.HighShelfFilter(10000, 1, Q),
        1e-4,
    ),
    "compressor": (
        lambda: pb.Compressor(threshold_db=-18, ratio=3, attack_ms=10, release_ms=100),
        lambda: rust.Compressor(-18, 3, 10, 100),
        1e-4,
    ),
    "compressor hard": (
        lambda: pb.Compressor(threshold_db=-30, ratio=6, attack_ms=2, release_ms=250),
        lambda: rust.Compressor(-30, 6, 2, 250),
        1e-4,
    ),
    "limiter": (lambda: pb.Limiter(threshold_db=-2, release_ms=60), lambda: rust.Limiter(-2, 60), 1e-4),
    "limiter low ceiling": (lambda: pb.Limiter(threshold_db=-6, release_ms=200), lambda: rust.Limiter(-6, 200), 1e-4),
    "gate": (
        lambda: pb.NoiseGate(threshold_db=-30, ratio=4, attack_ms=3, release_ms=100),
        lambda: rust.NoiseGate(-30, 4, 3, 100),
        1e-4,
    ),
    "gate slow": (
        lambda: pb.NoiseGate(threshold_db=-20, ratio=10, attack_ms=20, release_ms=400),
        lambda: rust.NoiseGate(-20, 10, 20, 400),
        1e-3,
    ),
}


@pytest.mark.parametrize("name", list(CASES))
def test_each_effect_matches_pedalboard(name):
    make_pb, make_rs, tolerance = CASES[name]
    x = signal() * (1.8 if name.startswith("limiter") else 1.0)  # loud enough to be limited
    x = x.astype(np.float32)
    a, b = run_pb(make_pb(), x), run_rs(make_rs(), x)
    assert a.shape == b.shape
    assert np.max(np.abs(a - b)) < tolerance


def test_settings_change_while_running_like_they_do_in_pedalboard():
    x = signal(2.0)
    a, b = pb.Compressor(threshold_db=-18, ratio=3, attack_ms=10, release_ms=100), rust.Compressor(-18, 3, 10, 100)
    first = (run_pb(a, x[:, :SR]), run_rs(b, x[:, :SR]))
    a.threshold_db = b.threshold_db = -30.0
    a.ratio = b.ratio = 8.0
    second = (run_pb(a, x[:, SR:]), run_rs(b, x[:, SR:]))
    assert np.max(np.abs(np.concatenate([first[0], second[0]], 1) - np.concatenate([first[1], second[1]], 1))) < 1e-4


@pytest.mark.skipif(bool(os.environ.get("SLUICE_NO_RUST")), reason="Rust switched off")
def test_the_whole_voice_chain_sounds_the_same_with_and_without_rust(monkeypatch):
    """The gate, compressor and limiter are one Python implementation (0.12.0); the EQ and Gain run in Rust or pedalboard alike.
    The high-pass is the one difference by design (a Butterworth needs the Rust engine), so both runs use the older one here."""
    x = signal(4.0)
    from sluice import effects as fx_module

    monkeypatch.setattr(
        fx_module,
        "_build_highpass",
        lambda pb, v: (
            [pb.HighpassFilter(cutoff_frequency_hz=v["cutoff_frequency_hz"]) for _ in range(2)],
            {"cutoff_frequency_hz": [(0, "cutoff_frequency_hz"), (1, "cutoff_frequency_hz")]},
        ),
    )
    monkeypatch.setitem(
        fx_module.BUILTINS,
        "highpass",
        fx_module.BuiltinDef("High-pass", fx_module.BUILTINS["highpass"].params, fx_module._build_highpass),
    )
    effects = voice_chain_effects(stable_ids=True)

    from sluice import effects as fx

    def build(use_rust):
        monkeypatch.delenv("SLUICE_NO_RUST_EFFECTS", raising=False)
        if not use_rust:
            monkeypatch.setenv("SLUICE_NO_RUST_EFFECTS", "1")
        items = []
        for e in effects:
            inst = EffectInstance(Effect(e.id, e.kind, e.name, type=e.type, params=dict(e.params)))
            items.extend(inst.items)
        return fx.Chain(fx.toolbox(pb), items), items

    with_rust, items_rs = build(True)
    without, items_pb = build(False)
    assert any(fx.is_native(i) for i in items_rs) and not any(fx.is_native(i) for i in items_pb)
    outs = []
    for chain in (with_rust, without):
        outs.append(
            np.concatenate([chain(np.ascontiguousarray(x[:, i : i + 512]), SR) for i in range(0, x.shape[1], 512)], axis=1)
        )
    assert outs[0].shape == outs[1].shape
    assert np.max(np.abs(outs[0] - outs[1])) < 5e-3


def test_the_chain_keeps_the_order_between_rust_and_pedalboard_parts():
    from sluice import effects as fx

    items = [rust.Gain(1.0), pb.Limiter(threshold_db=-2), rust.Gain(1.0), rust.PeakFilter(250, 0, 1.0)]
    chain = fx.Chain(fx.toolbox(pb), items)
    assert [type(p).__name__ for p in chain._parts] == ["NativeRun", "Pedalboard", "NativeRun"]


def test_a_run_refuses_anything_it_does_not_know():
    with pytest.raises(ValueError):
        rust.Run([pb.Gain(gain_db=1.0)])


def test_shelves_use_pedalboards_default_q_when_built_through_the_toolbox():
    tb = toolbox(pb)
    shelf = tb.LowShelfFilter(cutoff_frequency_hz=120, gain_db=-2)
    assert abs(shelf.q - 0.7071067690849304) < 1e-9
