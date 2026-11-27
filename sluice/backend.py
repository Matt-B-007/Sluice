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
from collections import deque
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
    channels: int = 2  # more than 2: a multichannel interface; sluice only uses its first two channels


@dataclass
class Stream:
    """An app's playback stream."""

    index: int
    key: str  # lower-case binary or app name: what channels remember
    name: str  # what to show the user
    sink: str  # name of the sink it currently plays into
    aliases: frozenset = frozenset()  # other lower-case names for the same program (app id, Steam game id...)
    icon: str = ""  # the icon name the program gave its stream (application.icon_name), "" when it gave none

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
    def ensure_null_sink(
        self, name: str, description: str, as_source: bool = False, source_description: Optional[str] = None
    ) -> None:
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

    def ensure_null_sink(
        self, name: str, description: str, as_source: bool = False, source_description: Optional[str] = None
    ) -> None:
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
# The last few calls made to the audio server, newest last: (call name, time.monotonic(), "ok" | "closed"). A native abort inside
# libpulse leaves nothing behind but a stack trace, so this is what a bug report shows about what led up to it.
_BREADCRUMBS: deque = deque(maxlen=8)


def recent_pulse_calls(now: Optional[float] = None) -> list:
    """[(call, seconds ago, outcome)] for the last few audio-server calls, newest last."""
    now = time.monotonic() if now is None else now
    return [(name, round(max(0.0, now - at), 2), outcome) for name, at, outcome in list(_BREADCRUMBS)]


def connect_pulse(client_name: str = "sluice"):
    """A new connection to the audio server, always behind the liveness check (``_LiveCheck``): every connection Sluice keeps goes
    through here, so none can be left without it."""
    import pulsectl

    return _LiveCheck(pulsectl.Pulse(client_name))


class _LiveCheck:
    """Wraps the pulsectl connection so every call first checks the connection is alive.

    When PipeWire restarts, the PulseAudio connection dies. Asking a dead connection for a list can make libpulse
    abort the whole program (seen in crash.log: ``Fatal Python error: Aborted`` inside the sink-input and source
    list calls). Checking first turns that into an ordinary error, which the engine already handles by waiting for the
    server and restarting Sluice (see reconnect.py)."""

    _ALWAYS_OK = ("close", "disconnect", "connected")

    def __init__(self, pulse) -> None:
        object.__setattr__(self, "_inner", pulse)

    def _alive(self) -> bool:
        pulse = self._inner
        if not hasattr(pulse, "_ctx"):  # a test double: nothing to check
            return True
        try:
            from pulsectl import _pulsectl as lib

            return pulse._ctx is not None and lib.pa.context_get_state(pulse._ctx) == lib.PA_CONTEXT_READY
        except Exception as exc:  # cannot even ask: treat the connection as dead (the caller reconnects)
            log.debug("could not read the audio-server connection state: %s", exc)
            return False

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr) or name in self._ALWAYS_OK or name.startswith("_"):
            return attr

        def checked(*args, **kwargs):
            if not self._alive():
                _BREADCRUMBS.append((name, time.monotonic(), "closed"))
                raise ConnectionError("Audio server shut down: the PulseAudio connection is closed")
            _BREADCRUMBS.append((name, time.monotonic(), "ok"))
            return attr(*args, **kwargs)

        return checked

    def __setattr__(self, name, value) -> None:
        setattr(self._inner, name, value)


class PulseSystem(AudioSystem):
    label = "PipeWire (JACK)"

    def __init__(self, purge: bool = True) -> None:
        self._pulse = connect_pulse(
            "sluice"
        )  # raises if the server is unreachable (pulsectl is imported there, so demo mode works without it)
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
            log.warning(
                "%s was named %r instead of %r; trying another way to write the name", name, found.description, description
            )
            try:
                self._pulse.module_unload(index)
            except Exception as exc:
                log.warning("could not unload module %s: %s", index, exc)
            index = None
        if index is None:  # nothing gave the right name: a device with a plain name is better than none
            log.warning("could not give %s the name %r; creating it with a plain name", name, description)
            return self._pulse.module_load(module, base)
        return index

    def ensure_null_sink(
        self, name: str, description: str, as_source: bool = False, source_description: Optional[str] = None
    ) -> None:
        description = _safe_description(description)
        source_description = _safe_description(source_description) if source_description else f"{description} (Mic)"
        existing = {s.name: s for s in self._pulse.sink_list()}
        if name in existing:
            self._remember(name, existing[name].owner_module)  # left over from a crash: take it over
        else:
            self._remember(
                name, self._load_described("module-null-sink", f"sink_name={name}", "sink_properties", description, name, "sink")
            )

        if as_source:
            source_name = f"{name}_mic"
            existing_sources = {s.name: s for s in self._pulse.source_list()}
            if source_name in existing_sources:
                self._remember(name, existing_sources[source_name].owner_module)
            else:
                base = f"master={name}.monitor source_name={source_name}"
                self._remember(
                    name,
                    self._load_described(
                        "module-remap-source", base, "source_properties", source_description, source_name, "source"
                    ),
                )

    def begin_shutdown(self) -> None:
        """0.12.4: Sluice is quitting. A broken connection is not replaced any more (at logout the audio server is shutting
        down too: reconnecting waited two seconds for nothing), and once the server is found gone there is nothing left to
        remove, since its devices went with it."""
        self.__dict__["_quitting"] = True

    def remove_null_sink(self, name: str) -> None:
        if self.__dict__.get("_server_gone"):
            self._modules.pop(name, None)
            return
        for index in reversed(self._modules.pop(name, [])):  # remap-source first, then the sink
            try:
                self._pulse.module_unload(index)
                log.debug("unloaded module %s (%s)", index, name)
            except Exception as exc:
                if self.__dict__.get("_quitting"):
                    self.__dict__["_server_gone"] = True
                    log.info(
                        "the audio server is already gone (logging out?), and Sluice's devices with it: nothing to remove (%s)",
                        exc,
                    )
                    return
                log.warning("could not unload module %s (%s): %s", index, name, exc)

    def _stale_modules(self, legacy: bool) -> list:
        """The loaded modules that are Sluice's own virtual devices (and, with ``legacy``, the old pwmix ones)."""
        prefixes = (PREFIX, LEGACY_PREFIX) if legacy else (PREFIX,)
        found = []
        for module in self._pulse.module_list():
            argument = module.argument or ""
            if module.name == "module-remap-source" and any(f"source_name={p}" in argument for p in prefixes):
                found.append(module)
            elif module.name == "module-null-sink" and any(f"sink_name={p}" in argument for p in prefixes):
                found.append(module)
        return found

    def leftover_devices(self, legacy: bool = True) -> list:
        """Names of Sluice virtual devices that exist right now (used by the uninstall check)."""
        names = []
        for module in self._stale_modules(legacy):
            match = re.search(r"(?:sink|source)_name=(\S+)", module.argument or "")
            names.append(match.group(1) if match else module.name)
        return names

    def purge_stale(self, legacy: bool = False) -> int:
        """Remove virtual devices a crashed earlier run left behind. Returns how many were removed.
        ``legacy`` also removes the ones left by the old name (pwmix); only ``--cleanup`` asks for that."""
        removed = 0
        for module in self._stale_modules(legacy):
            argument = module.argument or ""
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
        old, self._pulse = self._pulse, connect_pulse("sluice")  # behind the same liveness check as the first connection
        self.__dict__.pop("_sink_names", None)
        try:
            old.close()
        except Exception as exc:  # it was already broken: that is why it is being replaced
            log.debug("the old audio-server connection did not close cleanly: %s", exc)
        log.warning("reconnected to the PulseAudio protocol after the connection to the audio server broke")

    def list_streams(self) -> list:
        """Apps playing sound. A broken connection (the audio server restarted, a call failed half way) is replaced by a new
        one and the question asked once more, instead of failing every half second until Sluice is restarted."""
        try:
            return self._list_streams_once()
        except Exception as first:
            if self.__dict__.get("_quitting"):  # 0.12.4: quitting: no new connection to a server that is going away
                raise
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
                for name in (
                    "application.name",
                    "application.process.binary",
                    "application.id",
                    "pipewire.access.portal.app_id",
                    "application.icon_name",
                )
            }
            steam = self._steam_id(props.get("application.process.id"))
            if steam:
                aliases.add(steam)
            aliases.update(name[:-4] for name in {key, *aliases} if name.endswith(".exe") and len(name) > 4)
            aliases.discard("")
            aliases.discard(key)
            streams.append(
                Stream(
                    item.index,
                    key,
                    app_name or binary,
                    sink,
                    frozenset(aliases),
                    (props.get("application.icon_name") or "").strip(),
                )
            )
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
        except Exception as exc:  # shutting down: a connection that is already gone is fine
            log.debug("the audio-server connection did not close cleanly: %s", exc)
