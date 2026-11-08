# SPDX-License-Identifier: GPL-3.0-or-later
"""``sluice --report``: one text file with everything needed to understand a bug.

Only reads things (sluice's own files and a few read-only audio-system queries).
The report contains device names, app names and plugin paths: look it over before sharing.
"""
from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path
from typing import Optional

from . import __version__, logs
from .model import config_path

LOG_LINES = 300


def _run(command: list, timeout: float = 6.0) -> str:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return f"(not available: {command[0]} is not installed)"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(could not run: {exc})"
    text = (done.stdout or "").strip()
    if done.returncode != 0 and not text:
        return f"(failed with exit code {done.returncode}: {(done.stderr or '').strip()[:200]})"
    return text or "(no output)"


def sluice_blocks(text: str) -> str:
    """From ``pw-link -l`` output keep only the port blocks that mention sluice."""
    blocks: list = []
    for line in text.splitlines():
        if line and line[0] not in " \t":
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    kept = ["\n".join(b) for b in blocks if any("sluice" in part for part in b)]
    return "\n".join(kept) if kept else "(no sluice ports or links found)"


def _grep(text: str, needle: str) -> str:
    lines = [line for line in text.splitlines() if needle in line]
    return "\n".join(lines) if lines else f"(nothing mentioning {needle})"


def _tail(path: Path, lines: int) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(file not found)"
    return "\n".join(content[-lines:]) or "(empty)"


def _section(title: str, body: str) -> str:
    return f"\n===== {title} =====\n{body.rstrip()}\n"


def build_report(log_lines: int = LOG_LINES) -> str:
    from .diagnose import report as diagnose_report

    parts = [
        "sluice bug report\n"
        "This file contains device names, app names and plugin file paths. Look it over before sharing it.\n"
        f"Created: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    ]
    parts.append(_section("sluice", f"version {__version__}\nPython {platform.python_version()}\n{platform.platform()}"))

    try:
        parts.append(_section("Self-check (sluice --diagnose)", diagnose_report()[0]))
    except Exception as exc:
        parts.append(_section("Self-check (sluice --diagnose)", f"(could not run: {exc})"))

    parts.append(_section("PipeWire", _run(["pipewire", "--version"])))
    parts.append(_section("WirePlumber", _run(["wireplumber", "--version"])))
    parts.append(_section("pactl info", _run(["pactl", "info"])))
    parts.append(_section("Sinks (pactl list short sinks)", _run(["pactl", "list", "short", "sinks"])))
    parts.append(_section("Sources (pactl list short sources)", _run(["pactl", "list", "short", "sources"])))
    parts.append(_section("sluice modules loaded", _grep(_run(["pactl", "list", "short", "modules"]), "sluice")))
    parts.append(_section("sluice ports and links (pw-link -l)", sluice_blocks(_run(["pw-link", "-l"]))))

    try:
        config = config_path().read_text(encoding="utf-8")
    except OSError:
        config = "(no saved settings yet)"
    parts.append(_section(f"Settings ({config_path()})", config))
    parts.append(_section(f"Log, last {log_lines} lines ({logs.log_path()})", _tail(logs.log_path(), log_lines)))
    parts.append(_section(f"Native crash log ({logs.crash_path()})", _tail(logs.crash_path(), 60)))
    return "\n".join(parts)


def write_report(path: Optional[Path] = None) -> Path:
    path = Path(path) if path else Path.home() / "sluice-report.txt"
    path.write_text(build_report(), encoding="utf-8")
    return path
