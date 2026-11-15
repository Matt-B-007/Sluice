# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from sluice.audio_io import NullIO
from sluice.backend import MockSystem
from sluice.control import ControlApi, ControlServer, build_parser, run_cli, send, socket_path
from sluice.engine import Engine
from sluice.linker import NullLinker
from sluice.model import MONITOR, STREAM, Mixer


@pytest.fixture
def api():
    system = MockSystem()
    system.add_demo_streams()
    engine = Engine(Mixer.demo(), system, NullIO(realtime=False), NullLinker())
    engine.start()
    changes = []
    yield ControlApi(engine, on_change=changes.append), engine, changes
    engine.shutdown()


def test_status_lists_channels_and_mixes(api):
    a, engine, changes = api
    reply = a.handle({"cmd": "status"})
    assert reply["ok"] and [c["id"] for c in reply["channels"]] == ["mic", "browser", "game", "chat", "music", "system"]
    assert {m["label"] for m in reply["mixes"]} == {"Listen", "Broadcast"}
    assert changes == []  # reading changes nothing


def test_level_set_and_step_on_one_mix(api):
    a, engine, changes = api
    music = engine.mixer.channel("music")  # unlinked in the demo
    assert a.handle({"cmd": "level", "channel": "music", "mix": "listen", "db": -20})["ok"]
    assert music.levels[MONITOR] == -20 and music.levels[STREAM] == -18  # the other fader is untouched
    a.handle({"cmd": "level", "channel": "Music", "mix": "Broadcast", "step": -3})
    assert music.levels[STREAM] == -21
    assert changes == ["level", "level"]


def test_a_step_on_a_linked_channel_is_applied_once(api):
    a, engine, _ = api
    game = engine.mixer.channel("game")  # linked, -3 dB
    assert game.linked
    a.handle({"cmd": "level", "channel": "game", "step": -2})
    assert game.levels == {MONITOR: -5.0, STREAM: -5.0}


def test_levels_are_clamped_and_must_be_sane(api):
    a, engine, _ = api
    a.handle({"cmd": "level", "channel": "game", "db": 500})
    assert engine.mixer.channel("game").levels[MONITOR] == 12.0
    for bad in ({"db": float("nan")}, {"db": "loud"}, {"db": True}, {}, {"db": 1, "step": 1}):
        reply = a.handle({"cmd": "level", "channel": "game", **bad})
        assert reply["ok"] is False and reply["error"]


def test_mute_toggle_on_off(api):
    a, engine, _ = api
    chat = engine.mixer.channel("chat")
    a.handle({"cmd": "mute", "channel": "chat", "mix": "listen"})
    assert chat.mutes[MONITOR] is True
    a.handle({"cmd": "mute", "channel": "chat", "mix": "listen"})
    assert chat.mutes[MONITOR] is False
    a.handle({"cmd": "mute", "channel": "chat", "state": "on"})
    assert chat.mutes[MONITOR] and chat.mutes[STREAM]
    assert a.handle({"cmd": "mute", "channel": "chat", "state": "maybe"})["ok"] is False


def test_master_and_master_mute(api):
    a, engine, _ = api
    a.handle({"cmd": "master", "mix": "broadcast", "db": -6})
    assert engine.mixer.mix(STREAM).gain_db == -6
    a.handle({"cmd": "master", "mix": "broadcast", "step": 2})
    assert engine.mixer.mix(STREAM).gain_db == -4
    a.handle({"cmd": "master-mute", "mix": "listen"})
    assert engine.mixer.mix(MONITOR).mute is True


def test_assign_moves_an_app_and_none_releases_it(api):
    a, engine, changes = api
    assert a.handle({"cmd": "assign", "app": "Firefox", "channel": "game"})["ok"]
    assert engine.mixer.channel_for_app("firefox").id == "game"
    a.handle({"cmd": "assign", "app": "firefox", "channel": "none"})
    assert engine.mixer.channel_for_app("firefox") is None
    assert changes[-1] == "assign"


def test_unknown_things_give_helpful_errors_not_crashes(api):
    a, *_ = api
    assert "no channel" in a.handle({"cmd": "level", "channel": "nope", "db": 0})["error"]
    assert "no mix" in a.handle({"cmd": "master", "mix": "nope", "db": 0})["error"]
    assert "unknown command" in a.handle({"cmd": "format-disk"})["error"]
    assert a.handle("hello")["ok"] is False
    assert a.handle(None)["ok"] is False


def test_cli_parser_accepts_negative_steps():
    args = build_parser().parse_args(["level", "music", "--mix", "listen", "--step", "-2"])
    assert args.step == -2.0 and args.db is None
    args = build_parser().parse_args(["master", "listen", "--set", "-6"])
    assert args.db == -6.0


def test_cli_without_a_running_sluice_fails_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SLUICE_SOCKET", str(tmp_path / "none.sock"))
    assert run_cli(["status"]) == 2
    assert "not running" in capsys.readouterr().err


def test_socket_path_is_private_and_demo_is_separate(monkeypatch, tmp_path):
    monkeypatch.delenv("SLUICE_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert socket_path().endswith("sluice-control.sock")
    assert socket_path(demo=True).endswith("sluice-control-demo.sock")


def test_real_socket_round_trip(qapp, api, tmp_path, monkeypatch):
    """A real client talking to the Qt server, as a Stream Deck button would."""
    from PySide6.QtCore import QCoreApplication

    a, engine, _ = api
    path = str(tmp_path / "c.sock")
    monkeypatch.setenv("SLUICE_SOCKET", path)
    server = ControlServer(a, path)
    assert server.listening
    assert oct(os.stat(path).st_mode & 0o777) in ("0o600", "0o700")  # not open to other users

    results = []

    def client():
        try:
            results.append(send({"cmd": "level", "channel": "music", "mix": "listen", "db": -9}))
            results.append(send({"cmd": "nope"}))
            results.append(run_cli(["mute", "chat", "on"]))
        except Exception as exc:  # pragma: no cover
            results.append(exc)

    thread = threading.Thread(target=client)
    thread.start()
    while thread.is_alive():
        QCoreApplication.processEvents()
        thread.join(0.005)
    QCoreApplication.processEvents()
    server.close()
    assert results[0]["ok"] and results[1]["ok"] is False and results[2] == 0
    assert engine.mixer.channel("music").levels[MONITOR] == -9
    assert engine.mixer.channel("chat").mutes[MONITOR] is True


def test_server_survives_garbage(qapp, api, tmp_path):
    import socket

    from PySide6.QtCore import QCoreApplication

    a, *_ = api
    path = str(tmp_path / "g.sock")
    server = ControlServer(a, path)
    out = []

    def client():
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(path)
        s.sendall(b"\xff\xfe not json\n")
        out.append(json.loads(s.recv(4096)))
        s.close()

    thread = threading.Thread(target=client)
    thread.start()
    while thread.is_alive():
        QCoreApplication.processEvents()
        thread.join(0.005)
    server.close()
    assert out[0]["ok"] is False


def test_hear_broadcast_command(api):
    a, engine, changes = api
    assert a.handle({"cmd": "hear-broadcast"})["hear_broadcast"] is True
    assert engine.hear_broadcast and a.handle({"cmd": "status"})["hear_broadcast"] is True
    assert a.handle({"cmd": "hear-broadcast", "state": "off"})["hear_broadcast"] is False
    assert changes == ["hear-broadcast", "hear-broadcast"]
    assert build_parser().parse_args(["hear-broadcast", "on"]).state == "on"
