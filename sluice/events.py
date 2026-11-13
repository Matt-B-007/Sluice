# SPDX-License-Identifier: GPL-3.0-or-later
"""A short memory of what changed in the audio system, so a dropout can say what happened just before it.

Plugging in a USB device, an app starting to play, or Sluice rebuilding its links all make PipeWire rearrange itself, and that
can cause one brief dropout. Seeing the two together in the log tells a person (and a bug report) that nothing is wrong,
instead of suggesting a bigger buffer.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

MAX_EVENTS = 200
WINDOW_SECONDS = 10.0       # how far back a dropout looks
CAUSE_SECONDS = 3.0         # a change this close before a dropout is called its likely cause

_events: deque = deque(maxlen=MAX_EVENTS)    # (monotonic time, text)
_lock = threading.Lock()


def record(text: str, now: Optional[float] = None) -> None:
    with _lock:
        _events.append((time.monotonic() if now is None else now, text))


def clear() -> None:
    with _lock:
        _events.clear()


def before(moment: float, within: float = WINDOW_SECONDS) -> list:
    """[(seconds before ``moment``, text)] for the events up to ``within`` seconds earlier, oldest first. Events a little
    after ``moment`` (up to one second) count as well: the log is written a moment after the dropout itself."""
    with _lock:
        items = list(_events)
    found = [(moment - t, text) for t, text in items if -1.0 <= moment - t <= within]
    return sorted(found, key=lambda pair: -pair[0])


def describe(found: list) -> str:
    """'0.4 s before: input added: Cam Link 4K; 2.1 s before: links changed (+2, -2)' (nearest first)."""
    parts = []
    for seconds, text in sorted(found, key=lambda pair: pair[0]):
        when = "at the same moment" if seconds < 0.05 else f"{seconds:.1f} s before"
        parts.append(f"{when}: {text}")
    return "; ".join(parts)


def likely_cause(found: list) -> Optional[str]:
    """The text of the nearest change within CAUSE_SECONDS before the dropout, or None."""
    near = [(s, t) for s, t in found if s <= CAUSE_SECONDS]
    if not near:
        return None
    # Sluice relinks after a device or stream change, so a "links changed" entry is usually a consequence: name the real cause
    real = [(s, t) for s, t in near if not t.startswith("links changed")]
    return min(real or near)[1]


def load_average() -> str:
    """'load 3.2 on 32 threads' from /proc/loadavg (cheap), or ''."""
    try:
        with open("/proc/loadavg", encoding="ascii") as handle:
            one = float(handle.read().split()[0])
        import os

        return f"load average {one:.1f} on {os.cpu_count() or '?'} threads"
    except (OSError, ValueError, IndexError):
        return ""
