# SPDX-License-Identifier: GPL-3.0-or-later
"""Effect presets: ready-made settings for the voice chain, and the ones you save yourself.

A preset is a list of ``{"type", "bypass", "params"}`` entries for built-in effects. Applying one changes the effects of
that type that are already on the channel and leaves everything else alone. The Noise Gate's threshold is deliberately
never in a preset: it depends on your microphone's gain, so it is set by *Measure my room* or by hand.

Your own presets live in ``presets.json`` next to the settings file.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

BUILT_IN: dict = {
    "Noisy, echoing room (the default)": (
        "The starting values: both reducers on, Room echo time 0.6 s.",
        [{"type": "echo_reducer", "bypass": False, "params": {"reverb_time": 0.6, "reduction_db": 9}},
         {"type": "noise_reducer", "bypass": False, "params": {"reduction_db": 12}}],
    ),
    "Very noisy or echoing room": (
        "A little more reduction and a longer echo time, for bare walls and a loud fan. Slightly more risk of a thin voice.",
        [{"type": "echo_reducer", "bypass": False, "params": {"reverb_time": 0.9, "reduction_db": 12}},
         {"type": "noise_reducer", "bypass": False, "params": {"reduction_db": 18}}],
    ),
    "Light touch": (
        "Gentle reduction with the least chance of changing your voice.",
        [{"type": "echo_reducer", "bypass": False, "params": {"reverb_time": 0.4, "reduction_db": 5}},
         {"type": "noise_reducer", "bypass": False, "params": {"reduction_db": 6}}],
    ),
    "Quiet room": (
        "Both reducers off (no extra delay), and a smaller cut around 250 Hz.",
        [{"type": "echo_reducer", "bypass": True, "params": {}},
         {"type": "noise_reducer", "bypass": True, "params": {}},
         {"type": "eq", "bypass": False, "params": {"mid_db": -2}}],
    ),
}

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
    """The current built-in effects of a channel as preset entries (the gate threshold is left out)."""
    entries = []
    for effect in effects:
        if effect.kind != "builtin":
            continue
        params = {k: v for k, v in effect.params.items() if not (effect.type == "noise_gate" and k == "threshold_db")}
        entries.append({"type": effect.type, "bypass": bool(effect.bypass), "params": dict(params)})
    return entries


def apply(engine, channel_id: str, entries: list) -> int:
    """Apply entries to the matching built-in effects of the channel. Returns how many effects were changed."""
    changed = 0
    done: set = set()
    for entry in entries:
        kind = entry["type"]
        effect = next((e for e in engine.mixer.channel(channel_id).effects
                       if e.kind == "builtin" and e.type == kind and e.id not in done), None)
        if effect is None:
            continue
        done.add(effect.id)
        for key, value in entry.get("params", {}).items():
            if kind == "noise_gate" and key == "threshold_db":
                continue
            engine.set_effect_param(effect.id, key, value)
        if bool(entry.get("bypass", False)) != effect.bypass:
            engine.set_effect_bypass(channel_id, effect.id, bool(entry.get("bypass", False)))
        changed += 1
    return changed


# ---------------------------------------------------------------- which one is in use, and what it did
EFFECT_LABELS = {"echo_reducer": "Echo Reducer", "noise_reducer": "Noise Reducer", "eq": "EQ", "noise_gate": "Noise Gate",
                 "compressor": "Compressor", "highpass": "High-pass", "limiter": "Limiter", "gain": "Gain"}
TOLERANCE = 1e-3


def short_name(name: str) -> str:
    """The name as shown on a button: without the '(the default)' note."""
    return name.replace(" (the default)", "")


def current_value(effect, key: str):
    """A saved parameter, or its default when it was never changed."""
    if key in effect.params:
        return effect.params[key]
    from .effects import BUILTINS

    definition = BUILTINS.get(effect.type)
    spec = next((p for p in definition.params if p.key == key), None) if definition else None
    return None if spec is None else spec.default


def matches(effects: list, entries: list) -> bool:
    """True when the channel's built-in effects are exactly what these entries would set (a missing effect counts as off)."""
    builtin = [e for e in effects if e.kind == "builtin"]
    used: set = set()
    found = False
    for entry in entries:
        effect = next((e for e in builtin if e.type == entry["type"] and e.id not in used), None)
        if effect is None:
            if entry.get("bypass", False):
                continue
            return False
        used.add(effect.id)
        found = True
        if bool(entry.get("bypass", False)) != bool(effect.bypass):
            return False
        for key, wanted in entry.get("params", {}).items():
            if entry["type"] == "noise_gate" and key == "threshold_db":
                continue
            have = current_value(effect, key)
            if have is None or abs(float(have) - float(wanted)) > TOLERANCE:
                return False
    return found


def active_name(effects: list, user: Optional[dict] = None) -> Optional[str]:
    """The name of the preset the channel's effects currently match, or None. Your own presets are looked at first: you
    saved those on purpose, and they say more about the channel than the built-in ones do."""
    candidates = dict(user or {})
    for name, (_description, entries) in BUILT_IN.items():
        candidates.setdefault(name, entries)
    for name, entries in candidates.items():
        if matches(effects, entries):
            return name
    return None


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
