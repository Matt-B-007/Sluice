# SPDX-License-Identifier: GPL-3.0-or-later
"""Effect presets: two small choices (Room, Voice style) and the presets you save yourself.

A preset is a list of ``{"type", "bypass", "params"}`` entries for built-in effects. Applying one adds the effects the
channel lacks, in the usual order, and sets them. The ready-made choices never set the Noise Gate threshold or the Gain:
they depend on your microphone, so they are set by *Measure my room*, *Check my voice level* or by hand. Presets you save
yourself keep those too.

Your own presets live in ``presets.json`` next to the settings file.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

def _entry(kind: str, bypass: bool = False, **params) -> dict:
    return {"type": kind, "bypass": bypass, "params": {k: float(v) for k, v in params.items()}}


# Two small choices. "Room" is about the room around you and only touches the two reducers; "Voice style" is about how you
# want to sound and only touches the high-pass, EQ, compressor and limiter. Each effect belongs to exactly one of them, so
# the two never fight. Neither sets the gate threshold or the Gain: those depend on your microphone (see Measure my room).
ROOMS: dict = {
    "Quiet": ("Treated or very quiet room: both reducers off (no extra delay).",
              [_entry("echo_reducer", True), _entry("noise_reducer", True)]),
    "Normal": ("An ordinary room: some fan or traffic and a little echo. The starting choice.",
               [_entry("echo_reducer", reverb_time=0.6, reduction_db=9), _entry("noise_reducer", reduction_db=12)]),
    "Noisy": ("A loud fan, bare walls: more reduction and a longer echo time.",
              [_entry("echo_reducer", reverb_time=0.8, reduction_db=12), _entry("noise_reducer", reduction_db=18)]),
    "Very noisy": ("As much reduction as is sensible. Some risk of a thin voice: only if Noisy is not enough.",
                   [_entry("echo_reducer", reverb_time=1.0, reduction_db=15), _entry("noise_reducer", reduction_db=22)]),
}

STYLES: dict = {
    "Natural": ("Sounds like you, only tidier. The starting choice.",
                [_entry("highpass", cutoff_frequency_hz=80),
                 _entry("eq", low_hz=120, low_db=-1, mid_hz=250, mid_db=-2, mid_q=1, high_hz=4000, high_db=2),
                 _entry("compressor", threshold_db=-28, ratio=2.5, attack_ms=15, release_ms=120, makeup_db=3),
                 _entry("limiter", threshold_db=-2, release_ms=60)]),
    "Broadcast": ("Warm, full and even, like radio or a podcast.",
                  [_entry("highpass", cutoff_frequency_hz=80),
                   _entry("eq", low_hz=150, low_db=2, mid_hz=300, mid_db=-1.5, mid_q=1, high_hz=3500, high_db=3),
                   _entry("compressor", threshold_db=-30, ratio=3.5, attack_ms=12, release_ms=160, makeup_db=6),
                   _entry("limiter", threshold_db=-1.5, release_ms=60)]),
    "Game chat": ("Clear and punchy so teammates hear every word over the game.",
                  [_entry("highpass", cutoff_frequency_hz=110),
                   _entry("eq", low_hz=200, low_db=-2, mid_hz=300, mid_db=-2, mid_q=1, high_hz=3000, high_db=4),
                   _entry("compressor", threshold_db=-34, ratio=6, attack_ms=6, release_ms=100, makeup_db=8),
                   _entry("limiter", threshold_db=-3, release_ms=50)]),
    "Recording": ("Close to the raw microphone with room left to edit later.",
                  [_entry("highpass", cutoff_frequency_hz=60),
                   _entry("eq", low_hz=120, low_db=0, mid_hz=250, mid_db=0, mid_q=1, high_hz=8000, high_db=0),
                   _entry("compressor", threshold_db=-18, ratio=1.5, attack_ms=30, release_ms=200, makeup_db=0),
                   _entry("limiter", threshold_db=-3, release_ms=80)]),
}
DEFAULT_ROOM, DEFAULT_STYLE = "Normal", "Natural"
AXES = {"room": ROOMS, "style": STYLES}
AXIS_TYPES = {"room": ("echo_reducer", "noise_reducer"), "style": ("highpass", "eq", "compressor", "limiter")}

FILE_NAME = "presets.json"


def path_beside(config_file: Optional[Path]) -> Optional[Path]:
    return None if config_file is None else Path(config_file).parent / FILE_NAME


def load_user(path: Optional[Path]) -> dict:
    """{name: entries}. A missing or damaged file is simply no presets."""
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result: dict = {}
    if isinstance(data, dict):
        for name, entries in data.items():
            if isinstance(name, str) and isinstance(entries, list):
                clean = [e for e in entries if isinstance(e, dict) and isinstance(e.get("type"), str)]
                result[name] = [{"type": e["type"], "bypass": bool(e.get("bypass", False)),
                                 "params": {k: float(v) for k, v in dict(e.get("params") or {}).items()
                                            if isinstance(k, str) and isinstance(v, (int, float))}} for e in clean]
    return result


def save_user(path: Optional[Path], presets: dict) -> bool:
    if path is None:
        return False
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".presets-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(presets, handle, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def snapshot(effects: list) -> list:
    """The current built-in effects of a channel as preset entries. Your own presets keep everything, the gate threshold
    and the Gain included: they describe one microphone in one room."""
    return [{"type": e.type, "bypass": bool(e.bypass), "params": dict(e.params)} for e in effects if e.kind == "builtin"]


def apply(engine, channel_id: str, entries: list, personal: bool = False) -> int:
    """Apply entries to the channel: effects it lacks are added (in the usual order), the others are changed. Ready-made
    choices never touch the gate threshold or the Gain (``personal`` presets do). Returns how many effects were set."""
    from .effects import BUILTINS
    from .model import Effect, new_effect_id

    changed = 0
    done: set = set()
    for entry in entries:
        kind = entry["type"]
        if kind not in BUILTINS:
            continue
        if kind == "gain" and not personal:
            continue
        channel = engine.mixer.channel(channel_id)
        effect = next((e for e in channel.effects if e.kind == "builtin" and e.type == kind and e.id not in done), None)
        if effect is None:
            if bool(entry.get("bypass", False)):
                continue  # nothing to switch off
            effect = Effect(new_effect_id(), "builtin", BUILTINS[kind].name, type=kind)
            engine.add_effect(channel_id, effect)
        done.add(effect.id)
        for key, value in entry.get("params", {}).items():
            if kind == "noise_gate" and key == "threshold_db" and not personal:
                continue
            engine.set_effect_param(effect.id, key, value)
        if bool(entry.get("bypass", False)) != effect.bypass:
            engine.set_effect_bypass(channel_id, effect.id, bool(entry.get("bypass", False)))
        changed += 1
    return changed


def factory_effects(stable_ids: bool = False) -> list:
    """The voice chain a new install starts with: every effect, set to Room Normal and Voice Natural."""
    from .model import voice_chain_effects

    effects = voice_chain_effects(stable_ids)
    for entry in ROOMS[DEFAULT_ROOM][1] + STYLES[DEFAULT_STYLE][1]:
        effect = next((e for e in effects if e.type == entry["type"]), None)
        if effect is not None:
            effect.params.update(entry["params"])
            effect.bypass = bool(entry["bypass"])
    return effects


# ---------------------------------------------------------------- which one is in use, and what it did
EFFECT_LABELS = {"echo_reducer": "Echo Reducer", "noise_reducer": "Noise Reducer", "eq": "EQ", "noise_gate": "Noise Gate",
                 "compressor": "Compressor", "highpass": "High-pass", "limiter": "Limiter", "gain": "Gain"}
TOLERANCE = 1e-3


def current_value(effect, key: str):
    """A saved parameter, or its default when it was never changed."""
    if key in effect.params:
        return effect.params[key]
    from .effects import BUILTINS

    definition = BUILTINS.get(effect.type)
    spec = next((p for p in definition.params if p.key == key), None) if definition else None
    return None if spec is None else spec.default


def _spec(kind: str, key: str):
    from .effects import BUILTINS

    definition = BUILTINS.get(kind)
    return next((p for p in definition.params if p.key == key), None) if definition else None


def distance(effects: list, entries: list, personal: bool = False) -> Optional[float]:
    """How far the channel's effects are from these entries: 0 when identical, each parameter counting by its share of its
    range, a different on/off state counting 1. None when the channel has none of the effects at all. A missing effect counts
    as off (so it costs nothing against an entry that switches it off, and 1 against one that wants it on)."""
    builtin = [e for e in effects if e.kind == "builtin"]
    used: set = set()
    total, seen = 0.0, False
    for entry in entries:
        kind, wants_off = entry["type"], bool(entry.get("bypass", False))
        effect = next((e for e in builtin if e.type == kind and e.id not in used), None)
        if effect is None:
            total += 0.0 if wants_off else 1.0
            continue
        used.add(effect.id)
        seen = True
        if wants_off != bool(effect.bypass):
            total += 1.0
            continue
        if wants_off:
            continue  # both off: the values behind it do not matter
        for key, wanted in entry.get("params", {}).items():
            if kind == "noise_gate" and key == "threshold_db" and not personal:
                continue
            have = current_value(effect, key)
            spec = _spec(kind, key)
            if have is None or spec is None:
                total += 1.0
                continue
            span = (spec.hi - spec.lo) or 1.0
            gap = abs(float(have) - float(wanted)) / span
            total += 0.0 if abs(float(have) - float(wanted)) <= TOLERANCE else max(gap, 1e-6)
    return total if seen else None


def matches(effects: list, entries: list, personal: bool = False) -> bool:
    """True when the channel's built-in effects are exactly what these entries would set."""
    d = distance(effects, entries, personal)
    return d is not None and d == 0.0


def axis_state(effects: list, axis: str) -> tuple:
    """(name, changed) for the "room" or "style" choice: the nearest choice, and whether the settings have moved off it
    (even by a hair). (None, False) when the channel has none of that axis's effects."""
    best, best_d = None, None
    for name, (_description, entries) in AXES[axis].items():
        d = distance(effects, entries)
        if d is not None and (best_d is None or d < best_d):
            best, best_d = name, d
    if best is None:
        return None, False
    return best, best_d > 0.0


def reset_axis(engine, channel_id: str, axis: str) -> None:
    name, _changed = axis_state(engine.mixer.channel(channel_id).effects, axis)
    if name is not None:
        apply(engine, channel_id, AXES[axis][name][1])


def user_name(effects: list, user: Optional[dict] = None) -> Optional[str]:
    """The name of your own preset the channel exactly matches, or None."""
    for name, entries in (user or {}).items():
        if matches(effects, entries, personal=True):
            return name
    return None


def room_for_noise(noise_db: float) -> str:
    """The Room choice that suits a measured background noise (the loud end of the room, in dB below full scale)."""
    if noise_db < -58.0:
        return "Quiet"
    if noise_db < -48.0:
        return "Normal"
    if noise_db < -38.0:
        return "Noisy"
    return "Very noisy"


def summary(entries: list) -> str:
    """'Echo Reducer 5 dB, 0.4 s; Noise Reducer 6 dB': what a preset sets, for the message after applying it."""
    parts = []
    for entry in entries:
        label = EFFECT_LABELS.get(entry["type"], entry["type"])
        if entry.get("bypass", False):
            parts.append(f"{label} off")
            continue
        params = entry.get("params", {})
        bits = []
        if "reduction_db" in params:
            bits.append(f"{params['reduction_db']:g} dB")
        if "reverb_time" in params:
            bits.append(f"{params['reverb_time']:g} s")
        parts.append(f"{label} {', '.join(bits)}".strip() if bits else label)
    return "; ".join(parts)
