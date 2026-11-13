# SPDX-License-Identifier: GPL-3.0-or-later
"""Mixer data model: channels and mixes.

Pure Python: no Qt, no audio server, no DSP, so everything here is unit-testable.

Concepts
--------
* A **channel** is one thing you want to control: "Mic", "Game", "Music", "Chat"...
  Audio gets into a channel from *sources*: capture **devices** you add to it, and
  **apps** you assign to it (each channel owns a virtual output device that
  assigned apps play into). A channel has an **effect chain** (built-in effects
  and VST3 plugins) and its own level + mute **per mix**.
* A **mix** is a finished output. ``monitor`` goes to your headphones/speakers;
  ``stream`` goes to a virtual microphone that OBS, Discord, etc. record from.

Device convention (the ``device`` / ``devices`` entries):
  * ``None`` - disabled (mixes only)
  * ``""``   - follow the system default device
  * ``"name"`` - a specific PulseAudio/PipeWire device name
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MIN_DB = -60.0
MAX_DB = 12.0
CONFIG_VERSION = 2
BUFFER_CHOICES = (256, 512, 1024, 2048)  # audio block sizes (frames) the user can pick; bigger = less CPU, more delay
DEFAULT_BUFFER = 512
CLOSE_CHOICES = ("quit", "minimize", "tray")  # what closing the window does
DEFAULT_CLOSE = "quit"

MONITOR = "monitor"
STREAM = "stream"
RECORDING = "recording"  # the optional third mix (its kind is STREAM)

# Every object sluice creates in the audio server starts with this prefix.
PREFIX = "sluice_"
# The working name was "pwmix"; devices it left behind (after a crash) can be removed with ``sluice --cleanup``.
LEGACY_PREFIX = "pwmix_"

CHANNEL_COLORS = ["#4da3ff", "#3ddc84", "#ff9f43", "#b78cff", "#ff6b9a", "#f5c542", "#35d0c0", "#8aa0b8"]


def db_to_linear(db: float) -> float:
    """Convert decibels to a linear gain. At or below MIN_DB the result is 0 (silence)."""
    if db <= MIN_DB:
        return 0.0
    return 10.0 ** (db / 20.0)


def linear_to_db(linear: float) -> float:
    """Convert a linear amplitude to decibels, floored at MIN_DB."""
    if linear <= 0.0:
        return MIN_DB
    return max(MIN_DB, 20.0 * math.log10(linear))


def clamp_db(db: float) -> float:
    return max(MIN_DB, min(MAX_DB, float(db)))


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "sluice" / "config.json"


def migrate_legacy_settings(target: Path) -> bool:
    """Sluice was called pwmix at first. If there are no Sluice settings yet but pwmix ones exist, copy them
    over (copies only: the old folder is left alone). Returns True when something was copied."""
    import shutil

    target = Path(target)
    old_dir = target.parent.parent / "pwmix"
    if target.exists() or not (old_dir / "config.json").is_file():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        for name in ("config.json", "controls.json"):
            if (old_dir / name).is_file():
                shutil.copy2(old_dir / name, target.parent / name)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------- effects
@dataclass
class Effect:
    """One entry in a channel's effect chain (the saved description, not the live plugin)."""

    id: str
    kind: str  # "builtin" or "vst3"
    name: str
    type: str = ""  # builtin effect type, e.g. "compressor"
    path: str = ""  # VST3 bundle path
    plugin_name: str = ""  # which plugin inside a multi-plugin VST3 bundle
    bypass: bool = False
    params: dict = field(default_factory=dict)  # builtin parameter values
    state: str = ""  # base64 VST3 state


def new_effect_id() -> str:
    return uuid.uuid4().hex[:8]


# Built-in effects always run in this order, which is the usual order for a voice (trim the level, remove
# rumble, gate the room noise, shape the tone, even out the level, catch the peaks). VST3 plugins are not
# part of it: they stay wherever you put them.
BUILTIN_ORDER = ("gain", "highpass", "echo_reducer", "noise_reducer", "noise_gate", "eq", "compressor", "limiter")
BUILTIN_NAMES = {
    "gain": "Gain", "highpass": "High-pass", "echo_reducer": "Echo Reducer", "noise_reducer": "Noise Reducer", "noise_gate": "Noise Gate", "eq": "3-Band EQ",
    "compressor": "Compressor", "limiter": "Limiter",
}
VOICE_CHAIN = ("highpass", "echo_reducer", "noise_reducer", "noise_gate", "eq", "compressor", "limiter")


def canonical_order(effects: list) -> list:
    """The same effects with the built-in ones in the fixed order above. They keep the slots they occupied and
    VST3 plugins do not move."""
    rank = {key: i for i, key in enumerate(BUILTIN_ORDER)}
    slots = [i for i, e in enumerate(effects) if e.kind == "builtin"]
    ordered = sorted((effects[i] for i in slots), key=lambda e: rank.get(e.type, len(rank)))  # stable
    result = list(effects)
    for slot, effect in zip(slots, ordered):
        result[slot] = effect
    return result


def voice_chain_effects(stable_ids: bool = False) -> list:
    """A fresh recommended voice chain; every setting starts at the effect's default.
    ``stable_ids`` gives the same ids every time (used for the factory layout, so two defaults compare equal)."""
    return [Effect(f"voice-{key}" if stable_ids else new_effect_id(), "builtin", BUILTIN_NAMES[key], type=key)
            for key in VOICE_CHAIN]


# ---------------------------------------------------------------------- channels
@dataclass
class Channel:
    id: str
    label: str
    color: str = CHANNEL_COLORS[0]
    devices: list = field(default_factory=list)  # capture devices ("" = system default mic)
    apps: list = field(default_factory=list)  # app keys (lower-case binary or app name)
    effects: list = field(default_factory=list)  # list[Effect]
    levels: dict = field(default_factory=dict)  # mix id -> dB
    mutes: dict = field(default_factory=dict)  # mix id -> bool
    linked: bool = True  # moving one fader moves the other mix's fader too
    separate: bool = False  # also offered as its own recording device ("Sluice Mic only") for OBS and other recorders

    @property
    def sink_name(self) -> str:
        """The virtual output device apps assigned to this channel play into."""
        return f"{PREFIX}ch_{self.id}"

    @property
    def description(self) -> str:
        """What apps (Discord, a browser, a game) show as an output device to play into: "Sluice (Game) output".
        The plain "Sluice (Game)" is kept for the recording device (see ``solo_description``), so the two never share a name."""
        return f"Sluice ({self.label}) output"

    @property
    def solo_sink_name(self) -> str:
        """The virtual device behind this channel's own recording source (only used while ``separate`` is on)."""
        return f"{PREFIX}solo_{self.id}"

    @property
    def solo_description(self) -> str:
        """What OBS and other recorders show as an input device for this channel alone: "Sluice (Game)"."""
        return f"Sluice ({self.label})"

    @property
    def solo_sink_description(self) -> str:
        return f"Sluice ({self.label}) recording feed"


@dataclass
class Mix:
    id: str
    label: str
    kind: str  # MONITOR (a real output device) or STREAM (virtual mic)
    device: Optional[str] = None
    gain_db: float = 0.0
    mute: bool = False
    limiter: bool = True

    @property
    def sink_name(self) -> Optional[str]:
        return f"{PREFIX}{self.id}" if self.kind == STREAM else None

    @property
    def description(self) -> str:
        return f"Sluice ({self.label}) feed"

    @property
    def source_description(self) -> str:
        """The microphone-style device apps record the mix from: "Sluice (Broadcast)"."""
        return f"Sluice ({self.label})"


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:16]
    return slug or "channel"


_ID_RE = re.compile(r"^[a-z0-9_]{1,24}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Mixer:
    def __init__(self, channels: list, mixes: list):
        self.channels = channels
        self.mixes = mixes
        self.vst3_folders: list = []  # extra places to look for VST3 plugins, added by the user
        self.hints_seen: list = []  # one-time tips already shown (they are only ever shown once)
        self.buffer_frames = DEFAULT_BUFFER  # used the next time Sluice starts
        self.auto_update = False  # download new releases in the background and install them when Sluice closes (off by default)
        self.theme = "dark"  # a theme id: dark, light, contrast, purple, system, or custom:<name> (an imported file)
        self.close_action = DEFAULT_CLOSE  # "quit", "minimize" (keep running in the taskbar) or "tray" (keep running in the system tray)

    # ------------------------------------------------------------------ the optional third mix
    @property
    def has_recording_mix(self) -> bool:
        return any(m.id == RECORDING for m in self.mixes)

    def set_recording_mix(self, on: bool) -> None:
        """Add or remove the third mix, "Recording": a second virtual microphone for a recorder, apart from Broadcast.
        It is used the next time Sluice starts, because every device and port is made at start-up."""
        if on and not self.has_recording_mix:
            self.mixes.append(Mix(RECORDING, "Recording", STREAM))
            for c in self.channels:
                c.levels.setdefault(RECORDING, 0.0)
                c.mutes.setdefault(RECORDING, False)
        elif not on and self.has_recording_mix:
            self.mixes = [m for m in self.mixes if m.id != RECORDING]
            for c in self.channels:
                c.levels.pop(RECORDING, None)
                c.mutes.pop(RECORDING, None)

    # ------------------------------------------------------------------ defaults
    @classmethod
    def default(cls) -> "Mixer":
        mixes = [
            Mix(MONITOR, "Listen", MONITOR, device=""),
            Mix(STREAM, "Broadcast", STREAM),
        ]
        mixer = cls([], mixes)
        mic = mixer.add_channel("Mic", devices=[""], linked=False)
        mic.mutes[MONITOR] = True  # you don't want to hear yourself by default
        mic.separate = True  # "Sluice (Mic)": the mic after its effects, as an input for OBS, Discord and games
        mixer.add_channel("Browser")
        mixer.add_channel("Game")
        chat = mixer.add_channel("Chat")
        chat.mutes[STREAM] = True  # voice chat is not sent to the audience, and cannot hear itself back
        mixer.add_channel("Music")
        mixer.add_channel("System")  # notification and other desktop sounds
        from .presets import factory_effects

        mic.effects = factory_effects(stable_ids=True)  # Room Normal + Voice Natural; every effect can be bypassed or removed
        return mixer

    @classmethod
    def demo(cls) -> "Mixer":
        """A filled-in example layout for --demo and screenshots."""
        mixer = cls.default()
        mic = mixer.channel("mic")
        from .presets import factory_effects

        mic.effects = factory_effects()
        mixer.channel("game").effects = [Effect(new_effect_id(), "builtin", "Compressor", type="compressor")]
        mixer.assign_app("gamelauncher", "game")
        mixer.assign_app("spotify", "music")
        mixer.assign_app("vlc", "music")
        mixer.assign_app("discord", "chat")
        mixer.channel("music").levels = {MONITOR: -8.0, STREAM: -18.0}
        mixer.channel("music").linked = False
        mixer.channel("game").levels = {MONITOR: -3.0, STREAM: -3.0}
        return mixer

    # ------------------------------------------------------------------- lookups
    def channel(self, channel_id: str) -> Channel:
        for c in self.channels:
            if c.id == channel_id:
                return c
        raise KeyError(channel_id)

    def mix(self, mix_id: str) -> Mix:
        for m in self.mixes:
            if m.id == mix_id:
                return m
        raise KeyError(mix_id)

    def channel_for_app(self, app_key: str) -> Optional[Channel]:
        for c in self.channels:
            if app_key in c.apps:
                return c
        return None

    def channel_for_stream(self, stream, expand=None) -> Optional[Channel]:
        """The channel a playing program belongs to. ``stream.names`` are all the names it is known by;
        ``expand`` (optional) turns a remembered name into every name that means the same program."""
        names = stream.names
        for c in self.channels:
            for app in c.apps:
                if app in names or (expand is not None and not names.isdisjoint(expand(app))):
                    return c
        return None

    # -------------------------------------------------------------- channel edits
    def _unique_id(self, label: str) -> str:
        base = slugify(label)
        taken = {c.id for c in self.channels}
        if base not in taken:
            return base
        n = 2
        while f"{base}_{n}" in taken:
            n += 1
        return f"{base}_{n}"

    def add_channel(self, label: str, devices: Optional[list] = None, linked: bool = True) -> Channel:
        label = (label or "").strip()[:24] or "Channel"
        channel = Channel(
            id=self._unique_id(label),
            label=label,
            color=CHANNEL_COLORS[len(self.channels) % len(CHANNEL_COLORS)],
            devices=list(devices or []),
            levels={m.id: 0.0 for m in self.mixes},
            mutes={m.id: False for m in self.mixes},
            linked=linked,
        )
        self.channels.append(channel)
        return channel

    def remove_channel(self, channel_id: str) -> None:
        self.channels.remove(self.channel(channel_id))

    def assign_app(self, app_key: str, channel_id: Optional[str]) -> None:
        """Make ``app_key`` belong to exactly one channel (or to none)."""
        for c in self.channels:
            if app_key in c.apps:
                c.apps.remove(app_key)
        if channel_id is not None:
            self.channel(channel_id).apps.append(app_key)

    # ------------------------------------------------------------------ gain math
    def set_level(self, channel_id: str, mix_id: str, db: float) -> None:
        channel = self.channel(channel_id)
        db = clamp_db(db)
        if channel.linked:
            for m in self.mixes:
                channel.levels[m.id] = db
        else:
            channel.levels[mix_id] = db

    def route_gain(self, channel: Channel, mix: Mix) -> float:
        """Linear gain from a channel into a mix (0.0 = silent). Master gain is applied separately."""
        if channel.mutes.get(mix.id):
            return 0.0
        return db_to_linear(channel.levels.get(mix.id, 0.0))

    def master_gain(self, mix: Mix) -> float:
        return 0.0 if mix.mute else db_to_linear(mix.gain_db)

    # ---------------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        return {
            "version": CONFIG_VERSION,
            "vst3_folders": list(self.vst3_folders),
            "hints_seen": list(self.hints_seen),
            "buffer_frames": self.buffer_frames,
            "close_action": self.close_action,
            "auto_update": self.auto_update,
            "theme": self.theme,
            "channels": [
                {
                    "id": c.id,
                    "label": c.label,
                    "color": c.color,
                    "devices": list(c.devices),
                    "apps": list(c.apps),
                    "levels": dict(c.levels),
                    "mutes": dict(c.mutes),
                    "linked": c.linked,
                    "separate_output": c.separate,
                    "effects": [
                        {
                            "id": e.id,
                            "kind": e.kind,
                            "name": e.name,
                            "type": e.type,
                            "path": e.path,
                            "plugin_name": e.plugin_name,
                            "bypass": e.bypass,
                            "params": dict(e.params),
                            "state": e.state,
                        }
                        for e in c.effects
                    ],
                }
                for c in self.channels
            ],
            "recording_mix": self.has_recording_mix,
            "mixes": [
                {"id": m.id, "device": m.device, "gain_db": m.gain_db, "mute": m.mute, "limiter": m.limiter}
                for m in self.mixes
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> "Mixer":
        """Build a mixer from saved data. Anything malformed falls back to defaults."""
        mixer = cls.default()
        if not isinstance(data, dict) or data.get("version") != CONFIG_VERSION:
            return mixer
        frames = data.get("buffer_frames")
        if isinstance(frames, int) and not isinstance(frames, bool) and frames in BUFFER_CHOICES:
            mixer.buffer_frames = frames
        if data.get("close_action") in CLOSE_CHOICES:
            mixer.close_action = data["close_action"]
        mixer.auto_update = data.get("auto_update") is True
        theme = data.get("theme")
        if isinstance(theme, str) and 0 < len(theme) <= 80:
            mixer.theme = theme  # an id that no longer exists simply shows the default theme
        seen_hints = data.get("hints_seen")
        if isinstance(seen_hints, list):
            mixer.hints_seen = [h for h in seen_hints if isinstance(h, str)][:50]
        folders = data.get("vst3_folders")
        if isinstance(folders, list):
            mixer.vst3_folders = [f for f in folders if isinstance(f, str) and f][:50]

        if data.get("recording_mix") is True:
            mixer.set_recording_mix(True)
        for item in data.get("mixes", []):
            if not isinstance(item, dict):
                continue
            try:
                mix = mixer.mix(item.get("id"))
            except KeyError:
                continue
            if mix.kind == MONITOR and "device" in item:
                device = item["device"]
                if device is None or isinstance(device, str):
                    mix.device = device
            if isinstance(item.get("gain_db"), (int, float)):
                mix.gain_db = clamp_db(item["gain_db"])
            if isinstance(item.get("mute"), bool):
                mix.mute = item["mute"]
            if isinstance(item.get("limiter"), bool):
                mix.limiter = item["limiter"]

        raw_channels = data.get("channels")
        if not isinstance(raw_channels, list):
            return mixer
        channels: list[Channel] = []
        seen: set[str] = set()
        for item in raw_channels:
            if not isinstance(item, dict):
                continue
            cid = item.get("id")
            if not isinstance(cid, str) or not _ID_RE.match(cid) or cid in seen:
                continue
            seen.add(cid)
            label = item.get("label")
            channel = Channel(
                id=cid,
                label=label.strip()[:24] if isinstance(label, str) and label.strip() else cid,
                color=item["color"] if isinstance(item.get("color"), str) and _COLOR_RE.match(item["color"]) else CHANNEL_COLORS[len(channels) % len(CHANNEL_COLORS)],
                linked=item["linked"] if isinstance(item.get("linked"), bool) else True,
                separate=item["separate_output"] if isinstance(item.get("separate_output"), bool) else False,
            )
            channel.devices = [d for d in item.get("devices", []) if isinstance(d, str)] if isinstance(item.get("devices"), list) else []
            channel.apps = [a for a in item.get("apps", []) if isinstance(a, str)] if isinstance(item.get("apps"), list) else []
            levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
            mutes = item.get("mutes") if isinstance(item.get("mutes"), dict) else {}
            for m in mixer.mixes:
                level = levels.get(m.id)
                channel.levels[m.id] = clamp_db(level) if isinstance(level, (int, float)) and not isinstance(level, bool) else 0.0
                channel.mutes[m.id] = mutes.get(m.id) if isinstance(mutes.get(m.id), bool) else False
            for e in item.get("effects", []) if isinstance(item.get("effects"), list) else []:
                effect = _effect_from_dict(e)
                if effect is not None:
                    channel.effects.append(effect)
            channel.effects = canonical_order(channel.effects)
            channels.append(channel)
        if channels or raw_channels == []:
            mixer.channels = channels
        return mixer

    def save(self, path: Optional[Path] = None, backups: bool = False) -> None:
        """Write the settings. ``backups=True`` (only for the real settings file, never for an export) first keeps the
        file being replaced as one of the last few versions, so a change can be undone (see ``list_backups``)."""
        path = Path(path) if path else config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(), indent=2)
        if backups:
            try:
                make_backup(path, text)
            except OSError as exc:  # never lose a save because a backup could not be made
                import logging

                logging.getLogger("sluice").warning("could not back up the old settings: %s", exc)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Mixer":
        path = Path(path) if path else config_path()
        try:
            return cls.from_dict(json.loads(path.read_text()))
        except (OSError, ValueError):
            return cls.default()


BACKUPS_KEPT = 5
BACKUP_EVERY_SECONDS = 15 * 60  # a new version at most this often, or autosaving would fill the list in a minute


def backup_dir(config: Path) -> Path:
    return Path(config).parent / "backups"


def list_backups(config: Path) -> list:
    """The saved earlier versions, newest first: [Path]. File names are timestamps, so sorting the names sorts the time."""
    try:
        return sorted(backup_dir(config).glob("config-*.json"), reverse=True)
    except OSError:
        return []


def make_backup(config: Path, new_text: str, now: Optional[float] = None, keep: int = BACKUPS_KEPT) -> Optional[Path]:
    """Before ``config`` is replaced by ``new_text``: keep the old file as a backup, unless nothing changed or a
    backup was made recently. Then delete the oldest ones beyond ``keep``. Returns the new backup, if one was made."""
    config = Path(config)
    now = time.time() if now is None else now
    if not config.is_file():
        return None
    old = config.read_text(encoding="utf-8")
    existing = list_backups(config)
    if old == new_text or (existing and old == existing[0].read_text(encoding="utf-8")):
        return None  # nothing new to keep
    if existing and now - existing[0].stat().st_mtime < BACKUP_EVERY_SECONDS:
        return None
    folder = backup_dir(config)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    target = folder / f"config-{stamp}.json"
    counter = 1
    while target.exists():
        counter += 1
        target = folder / f"config-{stamp}-{counter}.json"
    shutil.copy2(config, target)
    for stale in list_backups(config)[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass
    return target


def _effect_from_dict(item: object) -> Optional[Effect]:
    if not isinstance(item, dict) or item.get("kind") not in ("builtin", "vst3"):
        return None

    def text(key: str) -> str:
        value = item.get(key)
        return value if isinstance(value, str) else ""

    params = item.get("params")
    clean_params = (
        {k: float(v) for k, v in params.items() if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)}
        if isinstance(params, dict)
        else {}
    )
    effect_id = text("id")
    return Effect(
        id=effect_id if re.match(r"^[a-z0-9]{1,16}$", effect_id) else new_effect_id(),
        kind=item["kind"],
        name=text("name") or text("type") or "Effect",
        type=text("type"),
        path=text("path"),
        plugin_name=text("plugin_name"),
        bypass=item["bypass"] if isinstance(item.get("bypass"), bool) else False,
        params=clean_params,
        state=text("state"),
    )
