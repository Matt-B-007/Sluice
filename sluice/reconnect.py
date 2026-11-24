# SPDX-License-Identifier: GPL-3.0-or-later
"""Coming back after the audio server (PipeWire) was restarted.

When PipeWire restarts, every program connected to it loses the connection, Sluice included: its virtual devices are
gone and the JACK client is dead. Reconnecting in place would mean rebuilding every connection, so Sluice does the safe
thing: it waits until the server answers again, saves its settings, and starts itself afresh with the same arguments.
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("sluice.reconnect")

LOST_PREFIX = "Audio server shut down"
POLL_SECONDS = 2.0
GIVE_UP_SECONDS = 180.0


def is_lost_message(message: str) -> bool:
    return message.startswith(LOST_PREFIX)


def server_is_back() -> bool:
    """True when a new connection to the JACK/PipeWire server can be made right now."""
    try:
        import jack

        client = jack.Client("sluice-probe", no_start_server=True, use_exact_name=False)
    except Exception as exc:  # no server yet: the caller keeps waiting
        log.debug("the audio server is not back yet: %s", exc)
        return False
    try:
        client.close()
    except Exception as exc:  # it answered, which is all this asks
        log.debug("the probe connection did not close cleanly: %s", exc)
    return True


def restart_command(show_window: bool = False) -> list:
    """The command line that started this process (python, then the script or ``-m sluice`` and its arguments).

    ``show_window`` leaves out ``--minimized``: someone who just pressed a button is looking at the screen and expects
    the window back, even when Sluice was first started minimized at login."""
    argv = list(getattr(sys, "orig_argv", [])) or [sys.executable] + sys.argv
    command = [sys.executable] + argv[1:]
    if show_window:
        command = [part for part in command if part != "--minimized"]
    if "--finish-move" in command:  # done once already (0.12.0)
        at = command.index("--finish-move")
        del command[at:at + 2]
    return command


def restart_self(show_window: bool = False) -> None:  # pragma: no cover - replaces the process
    command = restart_command(show_window)
    log.info("restarting: %s", command)
    try:
        from . import logs

        logs.mark_clean_exit()  # the process id stays the same, so the next start must not mistake this for a crash
    except Exception as exc:  # the restart goes ahead; the worst case is a "did not end normally" note next time
        log.warning("could not mark this session as ended cleanly before restarting: %s", exc)
    os.execv(command[0], command)
