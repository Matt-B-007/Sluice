# SPDX-License-Identifier: GPL-3.0-or-later
"""Effects: built-in processors and VST3 plugins, hosted with Spotify's ``pedalboard``.

``EffectInstance`` wraps the live plugin objects for one ``model.Effect``. The model
holds only the saved description; instances are created by the engine.
"""
from __future__ import annotations

import base64
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .model import Effect


class EffectError(Exception):
    """A plugin could not be created or loaded. The message is meant for the user."""


def _pedalboard():
    try:
        import pedalboard
    except ImportError as exc:
        raise EffectError("The 'pedalboard' package is not installed (pip install pedalboard).") from exc
    return pedalboard


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    lo: float
    hi: float
    default: float
    unit: str = ""


@dataclass
class ParamInfo:
    """A parameter as shown in the UI. For VST3 plugins values are normalised 0..1."""

    key: str
    label: str
    lo: float
    hi: float
    value: float
    unit: str
    normalized: bool = False
    default: Optional[float] = None  # None when the plugin does not say; the slider then cannot be reset


@dataclass(frozen=True)
class BuiltinDef:
    name: str
    params: tuple
    build: Callable  # (pedalboard module, values) -> (plugins list, {param key: (plugin index, attribute)})


def _direct(*plugin_factories):
    """Builder for effects where each parameter key is an attribute of one plugin."""

    def build(pb, values):
        plugin = plugin_factories[0](pb, values)
        return [plugin], {key: (0, key) for key in values}

    return build


def _build_compressor(pb, v):
    comp = pb.Compressor(
        threshold_db=v["threshold_db"], ratio=v["ratio"], attack_ms=v["attack_ms"], release_ms=v["release_ms"]
    )
    makeup = pb.Gain(gain_db=v["makeup_db"])
    targets = {k: (0, k) for k in ("threshold_db", "ratio", "attack_ms", "release_ms")}
    targets["makeup_db"] = (1, "gain_db")
    return [comp, makeup], targets


def _build_eq(pb, v):
    plugins = [
        pb.LowShelfFilter(cutoff_frequency_hz=v["low_hz"], gain_db=v["low_db"]),
        pb.PeakFilter(cutoff_frequency_hz=v["mid_hz"], gain_db=v["mid_db"], q=v["mid_q"]),
        pb.HighShelfFilter(cutoff_frequency_hz=v["high_hz"], gain_db=v["high_db"]),
    ]
    targets = {
        "low_hz": (0, "cutoff_frequency_hz"), "low_db": (0, "gain_db"),
        "mid_hz": (1, "cutoff_frequency_hz"), "mid_db": (1, "gain_db"), "mid_q": (1, "q"),
        "high_hz": (2, "cutoff_frequency_hz"), "high_db": (2, "gain_db"),
    }
    return plugins, targets


def _build_limiter(pb, v):
    return [pb.Limiter(threshold_db=v["threshold_db"], release_ms=v["release_ms"])], {
        "threshold_db": (0, "threshold_db"), "release_ms": (0, "release_ms")}


# Listed in the order they run (see model.BUILTIN_ORDER). The defaults are the common starting points for a
# speaking voice: high-pass at 80 Hz, a gate just above room noise, a gentle cut of the 200-400 Hz "mud" and a
# little air, a 3:1 compressor taking a few dB off the peaks, and a limiter a couple of dB below full scale.
BUILTINS: dict = {
    "gain": BuiltinDef(
        "Gain",
        (ParamSpec("gain_db", "Gain", -24, 24, 0, "dB"),),
        _direct(lambda pb, v: pb.Gain(gain_db=v["gain_db"])),
    ),
    "highpass": BuiltinDef(
        "High-pass",
        (ParamSpec("cutoff_frequency_hz", "Cutoff", 20, 500, 80, "Hz"),),
        _direct(lambda pb, v: pb.HighpassFilter(cutoff_frequency_hz=v["cutoff_frequency_hz"])),
    ),
    "noise_gate": BuiltinDef(
        "Noise Gate",
        (
            ParamSpec("threshold_db", "Threshold", -80, 0, -45, "dB"),
            ParamSpec("ratio", "Ratio", 1, 20, 10, ":1"),
            ParamSpec("attack_ms", "Attack", 0.1, 100, 5, "ms"),
            ParamSpec("release_ms", "Release", 10, 1000, 150, "ms"),
        ),
        _direct(lambda pb, v: pb.NoiseGate(
            threshold_db=v["threshold_db"], ratio=v["ratio"], attack_ms=v["attack_ms"], release_ms=v["release_ms"])),
    ),
    "eq": BuiltinDef(
        "3-Band EQ",
        (
            ParamSpec("low_hz", "Low freq", 40, 500, 120, "Hz"),
            ParamSpec("low_db", "Low gain", -15, 15, 0, "dB"),
            ParamSpec("mid_hz", "Mid freq", 200, 5000, 300, "Hz"),
            ParamSpec("mid_db", "Mid gain", -15, 15, -3, "dB"),
            ParamSpec("mid_q", "Mid Q", 0.3, 5, 1, ""),
            ParamSpec("high_hz", "High freq", 2000, 12000, 10000, "Hz"),
            ParamSpec("high_db", "High gain", -15, 15, 2, "dB"),
        ),
        _build_eq,
    ),
    "compressor": BuiltinDef(
        "Compressor",
        (
            ParamSpec("threshold_db", "Threshold", -60, 0, -18, "dB"),
            ParamSpec("ratio", "Ratio", 1, 20, 3, ":1"),
            ParamSpec("attack_ms", "Attack", 0.1, 100, 10, "ms"),
            ParamSpec("release_ms", "Release", 10, 1000, 100, "ms"),
            ParamSpec("makeup_db", "Makeup gain", 0, 24, 2, "dB"),
        ),
        _build_compressor,
    ),
    "limiter": BuiltinDef(
        "Limiter",
        (
            ParamSpec("threshold_db", "Ceiling", -20, 0, -2, "dB"),
            ParamSpec("release_ms", "Release", 10, 500, 60, "ms"),
        ),
        _build_limiter,
    ),
}


def builtin_names() -> list:
    """[(type key, display name)] in menu order."""
    return [(key, d.name) for key, d in BUILTINS.items()]


class EffectInstance:
    """Live plugin objects for one saved ``Effect``. Never raises: failures set ``error``."""

    def __init__(self, effect: Effect) -> None:
        self.effect = effect
        self.plugins: list = []
        self.error = ""
        self._targets: dict = {}
        self._vst3 = None
        self._editor_thread: Optional[threading.Thread] = None
        try:
            if effect.kind == "builtin":
                self._load_builtin()
            elif effect.kind == "vst3":
                self._load_vst3()
            else:
                raise EffectError(f"Unknown effect kind '{effect.kind}'")
        except EffectError as exc:
            self.error = str(exc)
        except Exception as exc:  # a plugin must never take the app down
            self.error = f"{type(exc).__name__}: {exc}"

    # ----------------------------------------------------------------- loading
    @property
    def usable(self) -> bool:
        return not self.error and bool(self.plugins)

    def _load_builtin(self) -> None:
        definition = BUILTINS.get(self.effect.type)
        if definition is None:
            raise EffectError(f"Unknown built-in effect '{self.effect.type}'")
        values = {}
        for spec in definition.params:
            stored = self.effect.params.get(spec.key, spec.default)
            values[spec.key] = min(spec.hi, max(spec.lo, float(stored)))
        self.plugins, self._targets = definition.build(_pedalboard(), values)
        self.effect.params = dict(values)

    def _load_vst3(self) -> None:
        pb = _pedalboard()
        path = self.effect.path
        if not path or not Path(path).exists():
            raise EffectError(f"VST3 plugin not found: {path or '(no path)'}")
        kwargs = {"plugin_name": self.effect.plugin_name} if self.effect.plugin_name else {}
        try:
            plugin = pb.load_plugin(path, **kwargs)
        except Exception as exc:
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise EffectError(f"Could not load {Path(path).name}: {first_line}") from exc
        if self.effect.state:
            try:
                plugin.raw_state = base64.b64decode(self.effect.state)
            except Exception:
                pass  # a stale or incompatible saved state is not fatal
        self._vst3 = plugin
        self.plugins = [plugin]

    # -------------------------------------------------------------- parameters
    def param_infos(self) -> list:
        if self.effect.kind == "builtin":
            definition = BUILTINS.get(self.effect.type)
            if definition is None:
                return []
            return [
                ParamInfo(s.key, s.label, s.lo, s.hi, float(self.effect.params.get(s.key, s.default)), s.unit,
                          default=float(s.default))
                for s in definition.params
            ]
        if self._vst3 is None:
            return []
        infos = []
        for key, param in self._vst3.parameters.items():
            try:
                default = getattr(param, "default_raw_value", None)
                infos.append(ParamInfo(key, str(getattr(param, "name", key)), 0.0, 1.0, float(param.raw_value), "", True,
                                       float(default) if isinstance(default, (int, float)) else None))
            except Exception:
                continue
        return infos

    def _spec(self, key: str) -> Optional[ParamSpec]:
        definition = BUILTINS.get(self.effect.type) if self.effect.kind == "builtin" else None
        return next((s for s in definition.params if s.key == key), None) if definition else None

    def record_param(self, key: str, value: float) -> None:
        """Remember a built-in parameter in the saved settings. Safe to call from the UI thread."""
        spec = self._spec(key)
        if spec is not None:
            self.effect.params[key] = min(spec.hi, max(spec.lo, float(value)))

    def apply_param(self, key: str, value: float) -> None:
        """Change the live plugin. While audio is running this must happen on the audio thread."""
        if self.effect.kind == "builtin":
            spec = self._spec(key)
            if spec is not None and self.plugins and key in self._targets:
                index, attr = self._targets[key]
                setattr(self.plugins[index], attr, min(spec.hi, max(spec.lo, float(value))))
        elif self._vst3 is not None and key in self._vst3.parameters:
            self._vst3.parameters[key].raw_value = min(1.0, max(0.0, float(value)))

    def set_param(self, key: str, value: float) -> None:
        self.record_param(key, value)
        self.apply_param(key, value)

    def capture_state(self) -> None:
        """Copy live state into the saved ``Effect`` (call before saving the config)."""
        if self._vst3 is not None:
            try:
                self.effect.state = base64.b64encode(bytes(self._vst3.raw_state)).decode("ascii")
            except Exception:
                pass

    # ------------------------------------------------------------ plugin window
    @property
    def has_editor(self) -> bool:
        return self._vst3 is not None and hasattr(self._vst3, "show_editor")

    def open_editor(self) -> None:
        """Show the plugin's own window (runs in a background thread; one window at a time)."""
        if not self.has_editor:
            return
        if self._editor_thread is not None and self._editor_thread.is_alive():
            return

        def run() -> None:
            try:
                self._vst3.show_editor()
            except Exception:
                pass

        self._editor_thread = threading.Thread(target=run, name="vst3-editor", daemon=True)
        self._editor_thread.start()


# ------------------------------------------------------------------------ VST3
def vst3_search_paths(extra: Optional[list] = None) -> list:
    """The usual VST3 folders (the same ones REAPER and other Linux hosts use), the folders in the VST3_PATH
    environment variable, and any folders the user added (``extra``). Duplicates are dropped."""
    paths = [Path.home() / ".vst3", Path("/usr/lib/vst3"), Path("/usr/lib64/vst3"), Path("/usr/local/lib/vst3")]
    paths.extend(Path(p) for p in os.environ.get("VST3_PATH", "").split(os.pathsep) if p)
    paths.extend(Path(p).expanduser() for p in (extra or []))
    seen: set = set()
    unique = []
    for path in paths:
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    return unique


def scan_vst3(search_paths: Optional[list] = None, max_depth: int = 2) -> list:
    """Find installed VST3 plugins. Returns [(display name, path)] sorted by name."""
    found: dict = {}

    def walk(directory: Path, depth: int) -> None:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.suffix.lower() == ".vst3":
                found.setdefault(str(entry), entry.stem)
            elif entry.is_dir() and depth < max_depth:
                walk(entry, depth + 1)

    for root in search_paths if search_paths is not None else vst3_search_paths():
        if Path(root).is_dir():
            walk(Path(root), 0)
    return sorted(((name, path) for path, name in found.items()), key=lambda item: item[0].lower())


def vst3_plugin_names(path: str) -> list:
    """Names of the plugins inside a VST3 file (some bundles hold several)."""
    try:
        return list(_pedalboard().VST3Plugin.get_plugin_names_for_file(path))
    except Exception:
        return []
