# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Sluice find PipeWire's JACK library on distributions that do not make it the default.

Debian, Ubuntu and their relatives install ``pipewire-jack`` but keep it out of the library path, so a JACK client
either finds no libjack at all or finds the one for the real JACK server, and then cannot connect. PipeWire's own
``pw-jack`` command solves that by putting its library folder first in ``LD_LIBRARY_PATH``. The path is read when
a program starts, so the only way to do the same is to start Sluice again with it set. This is only tried after
connecting normally has failed, and only once.
"""
from __future__ import annotations

import glob
import os
import sys
from typing import Optional

MARKER = "SLUICE_JACK_RETRIED"
PATTERNS = (
    "/usr/lib/*/pipewire-0.3/jack",   # Debian, Ubuntu (multiarch)
    "/usr/lib/pipewire-0.3/jack",     # Arch
    "/usr/lib64/pipewire-0.3/jack",   # Fedora, openSUSE
    "/usr/lib32/pipewire-0.3/jack",
    "/usr/local/lib/pipewire-0.3/jack",
    "/usr/local/lib/*/pipewire-0.3/jack",
)


def pipewire_jack_dirs(patterns: Optional[tuple] = None) -> list:
    found: list = []
    for pattern in (PATTERNS if patterns is None else patterns):
        for path in sorted(glob.glob(pattern)):
            if os.path.isdir(path) and any(name.startswith("libjack.so") for name in os.listdir(path)) and path not in found:
                found.append(path)
    return found


def environment_for_retry(env: dict, dirs: list) -> Optional[dict]:
    """The environment to start Sluice again with, or None if a retry would not help (nothing to add, or already tried)."""
    if not dirs or env.get(MARKER):
        return None
    current = [p for p in env.get("LD_LIBRARY_PATH", "").split(":") if p]
    if all(d in current for d in dirs):
        return None
    new = dict(env)
    new["LD_LIBRARY_PATH"] = ":".join([*dirs, *[p for p in current if p not in dirs]])
    new[MARKER] = "1"
    return new


def retry_with_pipewire_jack(argv: Optional[list] = None) -> bool:
    """Start Sluice again with PipeWire's JACK library first. Does not return if it starts; returns False if a retry
    makes no sense here."""
    env = environment_for_retry(dict(os.environ), pipewire_jack_dirs())
    if env is None:
        return False
    args = [sys.executable, "-m", "sluice", *(sys.argv[1:] if argv is None else argv)]
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os.execve(sys.executable, args, env)
    return True  # not reached
