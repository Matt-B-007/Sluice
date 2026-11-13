# SPDX-License-Identifier: GPL-3.0-or-later
"""Control plane: devices, virtual devices and app streams.

Audio samples do not flow through here (that is ``audio_io`` + ``dsp``). This module
talks the PulseAudio protocol (served by pipewire-pulse on CachyOS) to

  * list real capture and playback devices,
  * create the virtual devices sluice needs (one null sink per channel, plus the
    "Stream" mix sink and the microphone-style source apps record from),
  * list apps that are playing sound and move them between sinks.

``MockSystem`` is an in-memory fake used by tests and ``--demo`` mode.
"""
from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .apps import steam_id_of_process
from .model import LEGACY_PREFIX, PREFIX

log = logging.getLogger("sluice.pulse")

INVALID_INDEX = 0xFFFFFFFF


@dataclass(frozen=True)
class Device:
    name: str
    description: str
    monitor: bool = False  # "what this output device is playing" rather than a microphone or line input
    channels: int = 2      # more than 2: a multichannel interface; sluice only uses its first two channels


@dataclass
class Stream:
    """An app's playback stream."""

    index: int
    key: str  # lower-case binary or app name: what channels remember
    name: str  # what to show the user
    sink: str  # name of the sink it currently plays into
    aliases: frozenset = frozenset()  # other lower-case names for the same program (app id, Steam game id...)

    @property
    def names(self) -> frozenset:
        return frozenset({self.key}) | self.aliases

    @property
    def assign_key(self) -> str:
        """What a channel should remember for this program: a Steam game id when there is one (it survives restarts)."""
        return next((a for a in sorted(self.aliases) if a.startswith("steam:")), self.key)


def _channels(item) -> int:
    count = getattr(item, "channel_count", 2)
    return count if isinstance(count, int) and count > 0 else 2


NBSP = "\u00a0"


def _same_text(a: str, b: str) -> bool:
    return (a or "").replace(NBSP, " ").strip() == (b or "").replace(NBSP, " ").strip()


def _property_variants(key: str, description: str) -> list:
    """The ways to write ``<key>=device.description=<text>`` in a module's argument string, best first.

    PipeWire splits the argument string at spaces *before* it looks at quotes, so ``device.description="Sluice (Game)"``
    arrives as just ``"Sluice``: every device was called plain "Sluice". The first form therefore uses a no-break space,
    which looks like a space but is not one to the parser. The second is the escaped-quote form, as a fallback."""
    return [
        f"{key}=device.description={description.replace(' ', NBSP)}",
        f'{key}="device.description=\\"{description}\\""',
    ]


def _safe_description(text: str) -> str:
    """Remove characters that could break out of a module argument string."""
    return re.sub(r"[\x00-\x1f\"'\\]", "", text).strip() or "Sluice"


class AudioSystem(ABC):
    label = "abstract"

    @abstractmethod
    def list_sources(self) -> list:
        """Real capture devices (no monitors, nothing created by sluice)."""

    @abstractmethod
    def list_sinks(self) -> list:
        """Real playback devices (nothing created by sluice)."""

    @abstractmethod
    def default_source(self) -> Optional[str]: ...

    @abstractmethod
    def default_sink(self) -> Optional[str]: ...

    @abstractmethod
    def ensure_null_sink(self, name: str, description: str, as_source: bool = False, source_description: Optional[str] = None) -> None:
        """Create (or adopt) a virtual sink. With ``as_source`` also expose its monitor
        as a microphone-style source named ``<name>_mic``."""

    @abstractmethod
    def remove_null_sink(self, name: str) -> None: ...

    @abstractmethod
    def list_streams(self) -> list:
        """Apps currently playing sound, as ``Stream`` objects."""

    @abstractmethod
    def move_stream(self, index: int, sink_name: str) -> None: ...

    @abstractmethod
    def cleanup(self) -> None:
        """Remove everything this process created."""


# ============================================================================ mock
class MockSystem(AudioSystem):
    label = "Demo mode (no audio is touched)"

    def __init__(self) -> None:
        self.sources = [
            Device("alsa_input.usb-Blue_Yeti.analog-stereo", "Blue Yeti Microphone"),
            Device("alsa_input.pci-0000_00_1f.3.analog-stereo", "Built-in Audio Analog Stereo"),
            Device("alsa_input.usb-Webcam.mono-fallback", "USB Webcam Microphone"),
        ]
        self.sinks = [
            Device("alsa_output.usb-Headset.analog-stereo", "Headphones (USB Audio)"),
            Device("alsa_output.pci-0000_01_00.1.hdmi-stereo", "HDMI / DisplayPort"),
            Device("alsa_output.pci-0000_00_1f.3.analog-stereo", "Built-in Speakers"),
        ]
        self.default_src: Optional[str] = self.sources[0].name
        self.default_snk: Optional[str] = self.sinks[0].name
        self.null_sinks: dict = {}  # name -> (description, as_source)
        self.streams: list = []
        self.move_error: Optional[Exception] = None
        self.moves: list = []
        self.cleaned_up = False

    def add_demo_streams(self) -> None:
        sink = self.sinks[0].name
        self.streams = [
            Stream(1, "firefox", "Firefox", sink),
            Stream(2, "spotify", "Spotify", sink),
            Stream(3, "discord", "Discord", sink),
            Stream(4, "vlc", "VLC media player", sink),
            Stream(5, "gamelauncher", "Game (Proton)", sink),
        ]

    def list_sources(self) -> list:
        return list(self.sources)

    def list_sinks(self) -> list:
        return list(self.sinks)

    def default_source(self) -> Optional[str]:
        return self.default_src

    def default_sink(self) -> Optional[str]:
        return self.default_snk

    def ensure_null_sink(self, name: str, description: str, as_source: bool = False, source_description: Optional[str] = None) -> None:
        self.null_sinks[name] = (description, as_source)

    def remove_null_sink(self, name: str) -> None:
        self.null_sinks.pop(name, None)

    def list_streams(self) -> list:
        return [Stream(s.index, s.key, s.name, s.sink) for s in self.streams]

    def move_stream(self, index: int, sink_name: str) -> None:
        if self.move_error is not None:
            raise self.move_error
        for stream in self.streams:
            if stream.index == index:
                stream.sink = sink_name
                self.moves.append((index, sink_name))
                return

    def cleanup(self) -> None:
        self.null_sinks.clear()
        self.cleaned_up = True


# ========================================================================== pulse
class PulseSystem(AudioSystem):
    label = "PipeWire (JACK)"

    def __init__(self, purge: bool = True) -> None:
        import pulsectl  # imported lazily so demo mode works without it

        self._pulse = pulsectl.Pulse("sluice")  # raises if the server is unreachable
        self._modules: dict = {}  # virtual device name -> [module indexes]
        log.info("connected to the PulseAudio protocol")
        if purge:
            self.purge_stale()

    # ---------------------------------------------------------------- devices
    def list_sources(self) -> list:
        return [
            Device(s.name, s.description or s.name, monitor=s.name.endswith(".monitor"), channels=_channels(s))
            for s in self._pulse.source_list()
            if not s.name.startswith((PREFIX, LEGACY_PREFIX))
        ]

    def list_sinks(self) -> list:
        return [
            Device(s.name, s.description or s.name, channels=_channels(s))
            for s in self._pulse.sink_list()
            if not s.name.startswith((PREFIX, LEGACY_PREFIX))
        ]

    def default_source(self) -> Optional[str]:
        return self._pulse.server_info().default_source_name

    def default_sink(self) -> Optional[str]:
        return self._pulse.server_info().default_sink_name

    # ----------------------------------------------------------- virtual sinks
    def _remember(self, name: str, module_index: Optional[int]) -> None:
        if module_index is not None and module_index != INVALID_INDEX:
            indexes = self._modules.setdefault(name, [])
            if module_index not in indexes:
                indexes.append(module_index)

    def _load_described(self, module: str, base: str, key: str, description: str, name: str, kind: str) -> Optional[int]:
        """Load a module, then read the device back and check it got the name we asked for; try the next spelling if not."""
        index = None
        for props in _property_variants(key, description):
            args = f"{base} {props}"
            log.debug("%s %s", module, args)
            try:
                index = self._pulse.module_load(module, args)
            except Exception as exc:
                log.warning("%s refused %r: %s", module, props, exc)
                continue
            listing = self._pulse.sink_list() if kind == "sink" else self._pulse.source_list()
            found = next((d for d in listing if d.name == name), None)
            if found is None or _same_text(found.description, description):
                return index  # right name (or the device is not listed, so it cannot be checked)
            log.warning("%s was named %r instead of %r; trying another way to write the name", name, found.description, description)
            try:
                self._pulse.module_unload(index)
            except Exception as exc:
                log.warning("could not unload module %s: %s", index, exc)
            index = None
        if index is None:  # nothing gave the right name: a device with a plain name is better than none
            log.warning("could not give %s the name %r; creating it with a plain name", name, description)
            return self._pulse.module_load(module, base)
        return index

    def ensure_null_sink(self, name: str, description: str, as_source: bool = False, source_description: Optional[str] = None) -> None:
        description = _safe_description(description)
        source_description = _safe_description(source_description) if source_description else f"{description} (Mic)"
        existing = {s.name: s for s in self._pulse.sink_list()}
        if name in existing:
            self._remember(name, existing[name].owner_module)  # left over from a crash: take it over
        else:
            self._remember(name, self._load_described("module-null-sink", f"sink_name={name}", "sink_properties", description, name, "sink"))

        if as_source:
            source_name = f"{name}_mic"
            existing_sources = {s.name: s for s in self._pulse.source_list()}
            if source_name in existing_sources:
                self._remember(name, existing_sources[source_name].owner_module)
            else:
                base = f"master={name}.monitor source_name={source_name}"
                self._remember(name, self._load_described("module-remap-source", base, "source_properties", source_description, source_name, "source"))

    def remove_null_sink(self, name: str) -> None:
        for index in reversed(self._modules.pop(name, [])):  # remap-source first, then the sink
            try:
                self._pulse.module_unload(index)
                log.debug("unloaded module %s (%s)", index, name)
            except Exception as exc:
                log.warning("could not unload module %s (%s): %s", index, name, exc)

    def purge_stale(self, legacy: bool = False) -> int:
        """Remove virtual devices a crashed earlier run left behind. Returns how many were removed.
        ``legacy`` also removes the ones left by the old name (pwmix); only ``--cleanup`` asks for that."""
        removed = 0
        prefixes = (PREFIX, LEGACY_PREFIX) if legacy else (PREFIX,)
        for module in self._pulse.module_list():
            argument = module.argument or ""
            if module.name == "module-remap-source" and any(f"source_name={p}" in argument for p in prefixes):
                pass
            elif module.name == "module-null-sink" and any(f"sink_name={p}" in argument for p in prefixes):
                pass
            else:
                continue
            try:
                self._pulse.module_unload(module.index)
                removed += 1
                log.info("removed leftover %s (%s)", module.name, argument)
            except Exception as exc:
                log.warning("could not remove leftover module %s: %s", module.index, exc)
        return removed

    # ----------------------------------------------------------------- streams
    def _reconnect(self) -> None:
        """Open a fresh connection to the audio server (the old one is dropped without waiting for it)."""
        import pulsectl

        old, self._pulse = self._pulse, pulsectl.Pulse("sluice")
        self.__dict__.pop("_sink_names", None)
        try:
            old.close()
        except Exception:
            pass
        log.warning("reconnected to the PulseAudio protocol after the connection to the audio server broke")

    def list_streams(self) -> list:
        """Apps playing sound. A broken connection (the audio server restarted, a call failed half way) is replaced by a new
        one and the question asked once more, instead of failing every half second until Sluice is restarted."""
        try:
            return self._list_streams_once()
        except Exception as first:
            log.warning("listing the playing apps failed (%s: %s); reconnecting", type(first).__name__, first)
            self._reconnect()  # if the server really is gone this raises, and the caller's usual handling takes over
            return self._list_streams_once()

    def _list_streams_once(self) -> list:
        items = self._pulse.sink_input_list()
        # Sink names only change when devices come and go, so the list is reused; it is asked for again
        # only when a stream sits on a sink this program has not seen yet (one query instead of two, twice a second).
        # (PipeWire can reuse an id after a device is removed, so the list also expires after a few seconds.)
        sinks = self.__dict__.setdefault("_sink_names", {})
        now = time.monotonic()
        if any(item.sink not in sinks for item in items) or now - self.__dict__.get("_sink_names_at", 0.0) > 4.0:
            sinks.clear()
            sinks.update({s.index: s.name for s in self._pulse.sink_list()})
            self.__dict__["_sink_names_at"] = now
        streams = []
        for item in items:
            if item.owner_module not in (None, INVALID_INDEX):
                continue  # created by a module (a loopback, say), not by an app
            props = item.proplist or {}
            binary = (props.get("application.process.binary") or "").strip()
            app_name = (props.get("application.name") or "").strip()
            key = (binary or app_name).lower()
            sink = sinks.get(item.sink)
            if not key or sink is None:
                continue
            aliases = {
                (props.get(name) or "").strip().lower()
                for name in ("application.name", "application.process.binary", "application.id",
                             "pipewire.access.portal.app_id", "application.icon_name")
            }
            steam = self._steam_id(props.get("application.process.id"))
            if steam:
                aliases.add(steam)
            aliases.update(name[:-4] for name in {key, *aliases} if name.endswith(".exe") and len(name) > 4)
            aliases.discard("")
            aliases.discard(key)
            streams.append(Stream(item.index, key, app_name or binary, sink, frozenset(aliases)))
        return streams

    def _steam_id(self, pid) -> Optional[str]:
        """Steam game id of the program that owns a stream (cached: /proc is not read on every tick)."""
        if not pid or not str(pid).isdigit():
            return None
        cache = self.__dict__.setdefault("_steam_cache", {})
        if pid not in cache:
            if len(cache) > 256:
                cache.clear()
            cache[pid] = steam_id_of_process(int(pid))
        return cache[pid]

    def move_stream(self, index: int, sink_name: str) -> None:
        for sink in self._pulse.sink_list():
            if sink.name == sink_name:
                self._pulse.sink_input_move(index, sink.index)
                return
        raise LookupError(f"sink '{sink_name}' does not exist")

    # ----------------------------------------------------------------- cleanup
    def cleanup(self) -> None:
        for name in list(self._modules):
            self.remove_null_sink(name)
        try:
            self._pulse.close()
        except Exception:
            pass
