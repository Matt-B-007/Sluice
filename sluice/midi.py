# SPDX-License-Identifier: GPL-3.0-or-later
"""MIDI controllers: faders, knobs and buttons that drive the mixer.

No extra packages: sluice reads the raw ALSA MIDI device files (``/dev/snd/midiC*D*``) that every USB
MIDI device creates. Nothing is ever sent to the device, so it cannot change a controller's own settings.

* ``parse``      turns raw MIDI bytes into events (handles running status)
* ``Binding``    "this control does that": saved in ``controls.json`` next to the settings
* ``MidiHub``    finds devices (and notices plug/unplug), reads them, applies the bindings
"""
from __future__ import annotations

import glob
import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .model import MIN_DB

log = logging.getLogger("sluice.midi")

DEVICE_GLOB = "/dev/snd/midiC*D*"
MAX_BINDINGS = 256


# ---------------------------------------------------------------------------------------- events
@dataclass(frozen=True)
class MidiEvent:
    kind: str      # "cc", "on" or "off"
    channel: int   # MIDI channel 1-16
    number: int    # controller or note number, 0-127
    value: int     # 0-127

    @property
    def source(self) -> str:
        """Identifies the physical control, e.g. ``cc:1:7`` (CC 7 on MIDI channel 1) or ``note:1:36``."""
        return f"{'cc' if self.kind == 'cc' else 'note'}:{self.channel}:{self.number}"


class Parser:
    """Incremental MIDI byte-stream parser. Only control changes and notes matter; everything else is skipped."""

    def __init__(self) -> None:
        self._status = 0
        self._data: list = []

    def feed(self, data: bytes) -> list:
        events = []
        for byte in data:
            if byte >= 0xF8:          # real-time (clock, active sensing): may appear anywhere, ignore
                continue
            if byte >= 0x80:
                self._status = byte if byte < 0xF0 else 0  # system messages cancel running status
                self._data = []
                continue
            if not self._status:
                continue
            self._data.append(byte)
            kind = self._status & 0xF0
            need = 1 if kind in (0xC0, 0xD0) else 2
            if len(self._data) < need:
                continue
            a, b = (self._data + [0])[:2]
            self._data = []
            channel = (self._status & 0x0F) + 1
            if kind == 0xB0:
                events.append(MidiEvent("cc", channel, a, b))
            elif kind == 0x90:
                events.append(MidiEvent("on" if b else "off", channel, a, b))
            elif kind == 0x80:
                events.append(MidiEvent("off", channel, a, b))
        return events


def parse(data: bytes) -> list:
    return Parser().feed(data)


# ------------------------------------------------------------------------------------- bindings
KINDS = ("fader", "encoder", "button")


@dataclass
class Binding:
    """One control doing one thing.

    ``control``: ``fader`` is an absolute 0-127 value, ``encoder`` turns send +/- steps, ``button`` fires on press.
    ``action``:  ``level`` / ``mute`` (need ``channel``), ``master`` / ``master-mute`` (need ``mix``).
    """

    source: str
    control: str
    action: str
    channel: str = ""
    mix: str = ""        # listen / broadcast; empty = both (channel actions only)
    step_db: float = 1.0  # size of one encoder click

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "Binding":
        if not isinstance(data, dict):
            raise ValueError("a binding must be an object")
        source, control, action = data.get("source"), data.get("control"), data.get("action")
        if not (isinstance(source, str) and source.split(":")[0] in ("cc", "note") and source.count(":") == 2):
            raise ValueError(f"bad source {source!r}")
        if control not in KINDS:
            raise ValueError(f"bad control {control!r}")
        if action not in ("level", "mute", "master", "master-mute"):
            raise ValueError(f"bad action {action!r}")
        step = data.get("step_db", 1.0)
        if isinstance(step, bool) or not isinstance(step, (int, float)) or not math.isfinite(step) or not 0 < step <= 12:
            raise ValueError(f"bad step {step!r}")
        text = lambda key: str(data.get(key) or "")[:64]  # noqa: E731
        return cls(source, control, action, text("channel"), text("mix"), float(step))

    def describe(self) -> str:
        target = self.channel or ""
        if self.mix:
            target = f"{target} / {self.mix}" if target else self.mix
        return f"{self.action} {target}".strip()


def fader_to_db(value: int) -> float:
    """Audio taper for a 0-127 fader: top = 0 dB, about -12 dB at the middle, bottom = silence."""
    if value <= 0:
        return MIN_DB
    return max(MIN_DB, 40.0 * math.log10(min(value, 127) / 127.0))


def encoder_delta(value: int) -> int:
    """Relative-encoder value to a signed click count. 1-63 are clockwise, 65-127 counter-clockwise (two's complement)."""
    if value == 0 or value == 64:
        return 0
    return value if value < 64 else value - 128


def request_for(binding: Binding, event: MidiEvent) -> Optional[dict]:
    """The control request an event triggers, or None if it triggers nothing."""
    request: dict = {"cmd": binding.action}
    if binding.channel:
        request["channel"] = binding.channel
    if binding.mix:
        request["mix"] = binding.mix
    if binding.action in ("level", "master"):
        if binding.control == "fader" and event.kind == "cc":
            request["db"] = fader_to_db(event.value)
        elif binding.control == "encoder" and event.kind == "cc":
            clicks = encoder_delta(event.value)
            if clicks == 0:
                return None
            request["step"] = clicks * binding.step_db
        else:
            return None
        return request
    # mute buttons: act on press only (a CC counts as pressed when its value is above zero)
    pressed = event.kind == "on" or (event.kind == "cc" and event.value > 0)
    if binding.control != "button" or not pressed:
        return None
    request["state"] = "toggle"
    return request


def load_bindings(path: Path) -> list:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        items = raw.get("bindings", []) if isinstance(raw, dict) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("could not read %s (%s); starting with no controller bindings", path, exc)
        return []
    bindings = []
    for item in items[:MAX_BINDINGS]:
        try:
            bindings.append(Binding.from_dict(item))
        except ValueError as exc:
            log.warning("ignoring a controller binding: %s", exc)
    return bindings


def save_bindings(path: Path, bindings: list) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"version": 1, "bindings": [b.to_dict() for b in bindings]}, indent=2), encoding="utf-8")
    os.replace(temp, path)


# ------------------------------------------------------------------------------------------ hub
@dataclass
class _Port:
    path: str
    fd: int
    parser: Parser = field(default_factory=Parser)


class MidiHub:
    """Reads every MIDI input and applies the bindings. Call ``poll()`` often (every 10 ms or so) from one thread."""

    def __init__(self, apply: Callable[[dict], dict], bindings: Optional[list] = None,
                 pattern: str = DEVICE_GLOB, opener: Optional[Callable[[str], int]] = None) -> None:
        self.apply = apply
        self.bindings: list = list(bindings or [])
        self.pattern = pattern
        self._open = opener or (lambda path: os.open(path, os.O_RDONLY | os.O_NONBLOCK))
        self._ports: dict = {}
        self._denied: set = set()
        self.learning: Optional[Callable[[MidiEvent], None]] = None
        self.last_event: Optional[MidiEvent] = None
        self._lookup: dict = {}
        self.set_bindings(self.bindings)

    # ---------------------------------------------------------------- bindings
    def set_bindings(self, bindings: list) -> None:
        self.bindings = list(bindings)
        self._lookup = {}
        for binding in self.bindings:
            self._lookup.setdefault(binding.source, []).append(binding)

    def learn(self, callback: Optional[Callable[[MidiEvent], None]]) -> None:
        """The next control the user touches is passed to ``callback`` instead of being applied (None cancels)."""
        self.learning = callback

    # ----------------------------------------------------------------- devices
    @property
    def device_paths(self) -> list:
        return sorted(self._ports)

    @property
    def denied(self) -> list:
        return sorted(self._denied)

    def rescan(self) -> None:
        found = set(glob.glob(self.pattern))
        for path in sorted(found - set(self._ports)):
            try:
                self._ports[path] = _Port(path, self._open(path))
                self._denied.discard(path)
                log.info("MIDI input opened: %s", path)
            except PermissionError:
                if path not in self._denied:
                    self._denied.add(path)
                    log.warning("no permission to read %s (are you in the 'audio' group?)", path)
            except OSError as exc:
                log.debug("could not open %s: %s", path, exc)
        for path in sorted(set(self._ports) - found):
            self._close(path)
            log.info("MIDI input removed: %s", path)
        self._denied &= found

    def has_inputs(self) -> bool:
        return bool(self._ports)

    def _close(self, path: str) -> None:
        port = self._ports.pop(path, None)
        if port is not None:
            try:
                os.close(port.fd)
            except OSError:
                pass

    def close(self) -> None:
        for path in list(self._ports):
            self._close(path)

    # ----------------------------------------------------------------- reading
    def poll(self) -> int:
        """Read what is waiting, apply it. Returns how many events were handled."""
        handled = 0
        for path in list(self._ports):
            port = self._ports[path]
            while True:
                try:
                    data = os.read(port.fd, 4096)
                except BlockingIOError:
                    break
                except OSError:      # unplugged
                    self._close(path)
                    log.info("MIDI input lost: %s", path)
                    break
                if not data:
                    break
                for event in port.parser.feed(data):
                    self.dispatch(event)
                    handled += 1
        return handled

    def dispatch(self, event: MidiEvent) -> None:
        self.last_event = event
        if self.learning is not None:
            if event.kind == "off":
                return  # a button release is not "the control to learn"
            callback, self.learning = self.learning, None
            callback(event)
            return
        for binding in self._lookup.get(event.source, ()):
            request = request_for(binding, event)
            if request is not None:
                response = self.apply(request)
                if not response.get("ok"):
                    log.debug("binding %s: %s", binding.source, response.get("error"))
