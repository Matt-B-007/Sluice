# SPDX-License-Identifier: GPL-3.0-or-later
"""Remote control: lets other programs and devices drive the mixer.

* ``ControlApi``     turns a request (a dict) into engine calls. No Qt, no sockets: easy to test.
* ``ControlServer``  listens on a local Unix socket (inside ``$XDG_RUNTIME_DIR``, so only you can use it)
                     and passes each JSON line to the ``ControlApi``. It runs in the GUI thread.
* ``send``           the client side, used by ``sluice ctl ...`` (a Stream Deck button just runs that command).

Wire format: one JSON object per line in, one JSON object per line out::

    {"cmd": "level", "channel": "music", "mix": "listen", "step": -2}   ->   {"ok": true, ...}
"""
from __future__ import annotations

import json
import logging
import math
import os
import socket
from typing import Callable, Optional

from .engine import Engine
from .model import MAX_DB, MIN_DB, clamp_db

log = logging.getLogger("sluice.control")

MAX_REQUEST = 64 * 1024
STATES = ("on", "off", "toggle")


class ControlError(Exception):
    """A request that cannot be carried out; the message is shown to whoever sent it."""


def socket_path(demo: bool = False) -> str:
    override = os.environ.get("SLUICE_SOCKET")
    if override:
        return override
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/sluice-{os.getuid()}"
    os.makedirs(base, mode=0o700, exist_ok=True)
    return os.path.join(base, "sluice-control-demo.sock" if demo else "sluice-control.sock")


# --------------------------------------------------------------------------------------- the API
class ControlApi:
    """Executes control requests against an engine. ``on_change(cmd)`` is called after anything that changed."""

    def __init__(self, engine: Engine, on_change: Optional[Callable[[str], None]] = None) -> None:
        self.engine = engine
        self.on_change = on_change or (lambda _cmd: None)

    # ------------------------------------------------------------------ entry point
    def handle(self, request: object) -> dict:
        try:
            if not isinstance(request, dict):
                raise ControlError("a request must be a JSON object")
            cmd = request.get("cmd")
            handler = {
                "status": self._status,
                "level": self._level,
                "mute": self._mute,
                "master": self._master,
                "master-mute": self._master_mute,
                "assign": self._assign,
                "hear-broadcast": self._hear_broadcast,
                "mic-mute": self._mic_mute,
                "show": lambda _request: {},  # the window itself is raised by whoever listens (see ui_controls)
            }.get(cmd)
            if handler is None:
                raise ControlError(f"unknown command {cmd!r}; try: status, level, mute, master, master-mute, assign, hear-broadcast, mic-mute, show")
            result = handler(request)
            if cmd != "status":
                self.on_change(cmd)
            return {"ok": True, **result}
        except ControlError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # a bad request must never take the app down
            log.warning("control request failed: %r: %s", request, exc, exc_info=True)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ---------------------------------------------------------------------- lookups
    def _channel(self, request: dict):
        name = request.get("channel")
        if not isinstance(name, str) or not name.strip():
            raise ControlError("which channel? (\"channel\" is missing)")
        wanted = name.strip().lower()
        for channel in self.engine.mixer.channels:
            if wanted in (channel.id, channel.label.lower()):
                return channel
        known = ", ".join(c.id for c in self.engine.mixer.channels)
        raise ControlError(f"no channel called {name!r} (channels: {known})")

    def _mix(self, name: object):
        if not isinstance(name, str) or not name.strip():
            raise ControlError("which mix? (\"mix\" is missing)")
        wanted = name.strip().lower()
        for mix in self.engine.mixer.mixes:
            if wanted in (mix.id, mix.label.lower()):
                return mix
        known = ", ".join(f"{m.label.lower()}" for m in self.engine.mixer.mixes)
        raise ControlError(f"no mix called {name!r} (mixes: {known})")

    def _mixes(self, request: dict) -> list:
        """The mix named in the request, or both when none is named."""
        if request.get("mix") in (None, "", "both"):
            return list(self.engine.mixer.mixes)
        return [self._mix(request["mix"])]

    @staticmethod
    def _number(request: dict, key: str) -> Optional[float]:
        value = request.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ControlError(f"{key!r} must be a number")
        return float(value)

    @staticmethod
    def _state(request: dict, current: bool) -> bool:
        state = request.get("state", "toggle")
        if state is True:
            state = "on"
        elif state is False:
            state = "off"
        if state not in STATES:
            raise ControlError(f"state must be one of {', '.join(STATES)}")
        return (not current) if state == "toggle" else state == "on"

    def _target_db(self, request: dict, current: float) -> float:
        db, step = self._number(request, "db"), self._number(request, "step")
        if (db is None) == (step is None):
            raise ControlError("give exactly one of \"db\" (set) or \"step\" (change by)")
        return clamp_db(db if db is not None else current + step)

    # --------------------------------------------------------------------- commands
    def _status(self, _request: dict) -> dict:
        mixer = self.engine.mixer
        return {
            "channels": [
                {
                    "id": c.id,
                    "label": c.label,
                    "linked": c.linked,
                    "levels": {m.label.lower(): round(c.levels.get(m.id, 0.0), 1) for m in mixer.mixes},
                    "muted": {m.label.lower(): bool(c.mutes.get(m.id)) for m in mixer.mixes},
                    "apps": list(c.apps),
                }
                for c in mixer.channels
            ],
            "hear_broadcast": self.engine.hear_broadcast,
            "mic_muted": self.engine.mic_muted,
            "mixes": [
                {"id": m.id, "label": m.label, "db": round(m.gain_db, 1), "muted": m.mute, "limiter": m.limiter}
                for m in mixer.mixes
            ],
        }

    def _level(self, request: dict) -> dict:
        channel = self._channel(request)
        mixes = self._mixes(request)
        # work out every new value first: a linked channel moves both faders on one call, so a step must not be applied twice
        targets = [(mix, self._target_db(request, channel.levels.get(mix.id, 0.0))) for mix in mixes]
        for mix, new in (targets[:1] if channel.linked else targets):
            self.engine.set_level(channel.id, mix.id, new)
        return {"channel": channel.id, "levels": {m.label.lower(): round(channel.levels.get(m.id, 0.0), 1) for m in self.engine.mixer.mixes}}

    def _mute(self, request: dict) -> dict:
        channel = self._channel(request)
        for mix in self._mixes(request):
            self.engine.set_mute(channel.id, mix.id, self._state(request, bool(channel.mutes.get(mix.id))))
        return {"channel": channel.id, "muted": {m.label.lower(): bool(channel.mutes.get(m.id)) for m in self.engine.mixer.mixes}}

    def _master(self, request: dict) -> dict:
        mix = self._mix(request.get("mix"))
        self.engine.set_master(mix.id, self._target_db(request, mix.gain_db))
        return {"mix": mix.id, "db": round(mix.gain_db, 1)}

    def _master_mute(self, request: dict) -> dict:
        mix = self._mix(request.get("mix"))
        self.engine.set_master_mute(mix.id, self._state(request, mix.mute))
        return {"mix": mix.id, "muted": mix.mute}

    def _hear_broadcast(self, request: dict) -> dict:
        on = self._state(request, self.engine.hear_broadcast)
        self.engine.set_hear_broadcast(on)
        return {"hear_broadcast": self.engine.hear_broadcast}

    def _mic_mute(self, request: dict) -> dict:
        self.engine.set_mic_muted(self._state(request, self.engine.mic_muted))
        return {"mic_muted": self.engine.mic_muted}

    def _assign(self, request: dict) -> dict:
        app = request.get("app")
        if not isinstance(app, str) or not app.strip():
            raise ControlError("which app? (\"app\" is missing)")
        target = request.get("channel")
        if target in (None, "", "none"):
            self.engine.assign_app(app.strip().lower(), None)
            return {"app": app, "channel": None}
        channel = self._channel(request)
        self.engine.assign_app(app.strip().lower(), channel.id)
        return {"app": app, "channel": channel.id}


# ------------------------------------------------------------------------------------ the server
class ControlServer:
    """Accepts connections on a local socket. Needs a running Qt application; works in the GUI thread."""

    def __init__(self, api: ControlApi, path: str) -> None:
        from PySide6.QtNetwork import QLocalServer

        self.api = api
        self.path = path
        self._buffers: dict = {}
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(path)  # a stale socket from a crash; sluice itself is single-instance
        self.listening = self.server.listen(path)
        if self.listening:
            self.server.newConnection.connect(self._accept)
            log.info("control socket: %s", path)
        else:
            log.warning("could not open the control socket %s: %s", path, self.server.errorString())

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            self._buffers[connection] = bytearray()
            connection.readyRead.connect(lambda c=connection: self._read(c))
            connection.disconnected.connect(lambda c=connection: self._drop(c))

    def _drop(self, connection) -> None:
        self._buffers.pop(connection, None)
        connection.deleteLater()

    def _read(self, connection) -> None:
        buffer = self._buffers.get(connection)
        if buffer is None:
            return
        buffer += bytes(connection.readAll())
        if len(buffer) > MAX_REQUEST:
            self._reply(connection, {"ok": False, "error": "request too large"})
            return
        if b"\n" not in buffer:
            return
        line = bytes(buffer).split(b"\n", 1)[0]
        buffer.clear()
        try:
            request = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._reply(connection, {"ok": False, "error": "that is not valid JSON"})
            return
        log.debug("control request: %s", request)
        self._reply(connection, self.api.handle(request))

    @staticmethod
    def _reply(connection, response: dict) -> None:
        connection.write(json.dumps(response).encode("utf-8") + b"\n")
        connection.flush()
        connection.disconnectFromServer()

    def close(self) -> None:
        # Detach every open connection first: a socket that outlives its server and still has our callbacks
        # attached can be touched after Qt has deleted it, which crashes the whole app.
        for connection in list(self._buffers):
            for signal in (connection.readyRead, connection.disconnected):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            connection.abort()
            connection.deleteLater()
        self._buffers.clear()
        try:
            self.server.newConnection.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.server.close()
        self.server.deleteLater()
        try:
            os.unlink(self.path)
        except OSError:
            pass


# ------------------------------------------------------------------------------------ the client
def send(request: dict, path: Optional[str] = None, timeout: float = 3.0) -> dict:
    """Send one request to a running sluice. Raises ``ConnectionError`` if none is running."""
    path = path or socket_path()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(path)
        connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
        data = b""
        while b"\n" not in data:
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise ConnectionError("sluice is not running (or has no control socket)") from exc
    except socket.timeout as exc:
        raise ConnectionError("sluice did not answer in time") from exc
    finally:
        connection.close()
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as exc:
        raise ConnectionError("sluice sent an answer that could not be read") from exc


# ------------------------------------------------------------------------------------ the CLI
def _format_status(response: dict) -> str:
    lines = []
    for mix in response["mixes"]:
        lines.append(f"{mix['label']:<10} master {mix['db']:>6.1f} dB{'  MUTED' if mix['muted'] else ''}")
    lines.append("")
    for ch in response["channels"]:
        parts = [f"{name} {db:>6.1f} dB{' (muted)' if ch['muted'].get(name) else ''}" for name, db in ch["levels"].items()]
        lines.append(f"{ch['id']:<10} " + "   ".join(parts) + (f"   apps: {', '.join(ch['apps'])}" if ch["apps"] else ""))
    return "\n".join(lines)


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="sluice ctl",
        description="Control a running sluice (for Stream Deck buttons, scripts and other devices).",
        epilog="examples:\n  sluice ctl level music --mix listen --step -2\n  sluice ctl mute mic\n  sluice ctl master broadcast --set -6",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="print the raw reply")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def amount(p):
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--set", dest="db", type=float, metavar="DB", help="set to this level in dB (%d to +%d)" % (MIN_DB, MAX_DB))
        group.add_argument("--step", type=float, metavar="DB", help="change by this many dB (negative: quieter), e.g. --step=-2")

    def state(p):
        p.add_argument("state", nargs="?", default="toggle", choices=STATES, help="default: toggle")

    sub.add_parser("status", help="show every level and mute")
    p = sub.add_parser("level", help="channel fader")
    p.add_argument("channel")
    p.add_argument("--mix", help="listen or broadcast (default: both)")
    amount(p)
    p = sub.add_parser("mute", help="channel mute")
    p.add_argument("channel")
    p.add_argument("--mix", help="listen or broadcast (default: both)")
    state(p)
    p = sub.add_parser("master", help="master fader of a mix")
    p.add_argument("mix")
    amount(p)
    p = sub.add_parser("master-mute", help="mute a whole mix")
    p.add_argument("mix")
    state(p)
    p = sub.add_parser("hear-broadcast", help="play the Broadcast mix in your own output, to check what the audience hears")
    state(p)
    p = sub.add_parser("mic-mute", help="silence (or restore) every microphone, in all mixes and in Sluice (Mic) too")
    state(p)
    p = sub.add_parser("assign", help="send an app to a channel (or 'none' to release it)")
    p.add_argument("app")
    p.add_argument("channel")
    return parser


def run_cli(argv: list) -> int:
    import sys

    args = build_parser().parse_args(argv)
    request: dict = {"cmd": args.cmd}
    for key in ("channel", "mix", "app", "state", "db", "step"):
        value = getattr(args, key, None)
        if value is not None:
            request[key] = value
    try:
        response = send(request)
    except ConnectionError as exc:
        print(f"sluice ctl: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(response))
    elif not response.get("ok"):
        print(f"sluice ctl: {response.get('error', 'failed')}", file=sys.stderr)
    elif args.cmd == "status":
        print(_format_status(response))
    return 0 if response.get("ok") else 1
