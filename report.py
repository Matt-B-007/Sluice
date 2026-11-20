# SPDX-License-Identifier: GPL-3.0-or-later
"""``sluice --report``: one text file with everything needed to understand a bug.

Only reads things (sluice's own files and a few read-only audio-system queries).
Personal details are replaced before it is written: the home folder becomes ``~``, and the user name,
computer name, user id, USB serial numbers and Bluetooth addresses become placeholders. Device names,
app names and plugin paths remain, so it is still worth a look before sharing.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from . import __version__, logs
from .model import config_path

LOG_LINES = 300
PREVIOUS_LINES = 60        # the end of the session before this one (a crash happens at the end of a session)
CRASH_BLOCK_LINES = 40
REPEAT_MIN = 4             # this many identical lines in a row are shown as the first, a count, and the last
SESSION_START = "=== sluice "
CRASH_HEADERS = ("--- sluice session started", "--- sluice command started")


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


def last_pw_top_round(text: str, limit: int = 40) -> str:
    """From ``pw-top -b -n 2`` keep the last round: the first has no timings yet, the second shows who is busy or erring."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.split()[:2] == ["S", "ID"]]
    kept = lines[starts[-1]:] if starts else lines
    return "\n".join(kept[:limit]) or "(no output)"


def _grep(text: str, needle: str) -> str:
    lines = [line for line in text.splitlines() if needle in line]
    return "\n".join(lines) if lines else f"(nothing mentioning {needle})"


_SLOW_BLOCK = re.compile(r"\b(?:[1-9]\d{2,})%")
_NUMBERS = re.compile(r"\d+(?:\.\d+)?")


def _log_key(line: str) -> str:
    """A log line without its time and numbers: lines that differ only in those count as repeats."""
    return _NUMBERS.sub("#", line[24:] if len(line) > 24 else line)


def _log_time(line: str) -> str:
    return line[11:19] if len(line) >= 19 else "?"


def collapse_repeats(lines: list) -> list:
    """Runs of ``REPEAT_MIN`` or more near-identical log lines become: the first, a note with the count, the last."""
    out: list = []
    i = 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and _log_key(lines[j + 1]) == _log_key(lines[i]):
            j += 1
        run = j - i + 1
        if run >= REPEAT_MIN:
            out.append(lines[i])
            slow = [line for line in lines[i + 1:j] if _SLOW_BLOCK.search(line)][:3]  # a block over 100% is worth keeping
            out.append(f"    ... {run - 2 - len(slow)} similar lines, {_log_time(lines[i])} to {_log_time(lines[j])}"
                       + (", the slow ones kept ..." if slow else " ..."))
            out.extend(slow)
            out.append(lines[j])
        else:
            out.extend(lines[i:j + 1])
        i = j + 1
    return out


def split_sessions(lines: list) -> list:
    """The log as a list of sessions, each starting at its ``=== sluice ... starting`` line (text before the first is its own)."""
    sessions: list = [[]]
    for line in lines:
        if SESSION_START in line and "starting" in line and sessions[-1]:
            sessions.append([])
        sessions[-1].append(line)
    return [s for s in sessions if s]


def session_log(text: str, limit: int = LOG_LINES, previous: int = PREVIOUS_LINES) -> str:
    """The current session's log (repeats collapsed), then the end of the session before it. Older sessions are left out:
    they used to fill the report and push today's lines out of sight."""
    sessions = split_sessions(text.splitlines())
    if not sessions:
        return "(empty)"
    current = collapse_repeats(sessions[-1])
    shown = current[-limit:]
    parts = []
    if len(current) > len(shown):
        parts.append(f"(first {len(current) - len(shown)} lines of this session not shown)")
    parts.extend(shown)
    if len(sessions) > 1:
        before = collapse_repeats(sessions[-2])[-previous:]
        parts.append(f"\n--- the end of the session before this one ({len(sessions) - 1} earlier session(s) in the file) ---")
        parts.extend(before)
    return "\n".join(parts)


def crash_summary(text: str, modified: Optional[float] = None) -> str:
    """The native-crash file split into sessions: which session each trace belongs to, and when the file last changed."""
    lines = text.splitlines()
    blocks: list = []   # (header or None, trace lines)
    header: Optional[str] = None
    trace: list = []
    for line in lines:
        if line.startswith(CRASH_HEADERS):
            if trace:
                blocks.append((header, trace))
            header, trace = line, []
        elif line.strip():
            trace.append(line)
    if trace:
        blocks.append((header, trace))
    sessions = sum(1 for line in lines if line.startswith(CRASH_HEADERS))
    head = []
    if modified:
        head.append(f"File last written: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(modified))}")
    if not blocks:
        head.append(f"No native crash recorded ({sessions} session(s) logged in this file).")
        return "\n".join(head)
    for header, trace in blocks[-2:]:
        if header is None:
            label = "a trace from a session that began before the first session line in this file (time unknown)"
        else:
            kind = "command" if header.startswith(CRASH_HEADERS[1]) else "session"
            started = header.replace(f"--- sluice {kind} started", "").split("(pid")[0].strip()
            label = f"a trace written during the {kind} that started {started or 'at an unknown time'}"
        head.append(f"\n--- {label} ---")
        head.extend(trace[:CRASH_BLOCK_LINES])
        if len(trace) > CRASH_BLOCK_LINES:
            head.append(f"... ({len(trace) - CRASH_BLOCK_LINES} more lines)")
    return "\n".join(head)


_PW_TOP_COLUMNS = 9   # S ID QUANT RATE WAIT BUSY W/Q B/Q ERR


def top_errors(text: str, limit: int = 6) -> str:
    """From the ``pw-top`` table: the programs with a dropout count above zero, most first."""
    found = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) <= _PW_TOP_COLUMNS or parts[0] not in "RIS" or not parts[1].isdigit() or not parts[_PW_TOP_COLUMNS - 1].isdigit():
            continue
        errors = int(parts[_PW_TOP_COLUMNS - 1])
        if errors > 0:
            found.append((errors, parts[-1]))
    if not found:
        return "No program shows dropouts in this snapshot."
    found.sort(reverse=True)
    listed = ", ".join(f"{name} ({count})" for count, name in found[:limit])
    return ("Dropouts counted per program, most first: " + listed + ". The device that drives the audio is usually the one "
            "to look at; programs behind it show errors when it is late.")


def hardware_summary() -> str:
    """CPU and USB facts that matter for dropouts. Names of devices are not included."""
    lines = []
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                lines.append("CPU: " + line.split(":", 1)[1].strip())
                break
    except OSError:
        pass
    lines.append(f"CPU threads: {os.cpu_count() or '?'}")
    for label, path in (("CPU frequency setting", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
                        ("USB power saving (seconds, -1 is off)", "/sys/module/usbcore/parameters/autosuspend")):
        try:
            lines.append(f"{label}: {Path(path).read_text(encoding='utf-8').strip()}")
        except OSError:
            lines.append(f"{label}: (not available)")
    lines.append("")
    lines.append("USB devices by controller (lsusb -t):")
    lines.append(_run(["lsusb", "-t"]))
    return "\n".join(lines)


def _tail(path: Path, lines: int) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(file not found)"
    return "\n".join(content[-lines:]) or "(empty)"


def anonymize(text: str) -> str:
    """Replace details that identify a person or a machine with placeholders."""
    home = str(Path.home()).rstrip("/")
    if home and home != "/":
        text = text.replace(home, "~")
    try:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or Path.home().name
    except Exception:
        user = ""
    host = platform.node()
    # 'User Name: x' / 'Host Name: y' lines from pactl info, then every other mention of the same words
    text = re.sub(r"(?m)^(\s*User Name:\s*).+$", r"\1<user>", text)
    text = re.sub(r"(?m)^(\s*Host Name:\s*).+$", r"\1<host>", text)
    for word, placeholder in ((user, "<user>"), (host, "<host>"), (host.split(".")[0] if host else "", "<host>")):
        if word and len(word) >= 3 and word.lower() not in ("root", "localhost", "user", "host"):
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", placeholder, text, flags=re.IGNORECASE)
    text = re.sub(r"/run/user/\d+", "/run/user/<uid>", text)
    text = re.sub(r"/(?:home|Users)/[^/\s]+", "~", text)
    # USB serial numbers: alsa_input.usb-Vendor_Product_SERIAL-00.analog-stereo
    text = re.sub(r"(usb-[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*?)_([A-Z0-9]{8,})(-\d+)", r"\1_<serial>\3", text)
    text = re.sub(r"(?i)\b(?:[0-9a-f]{2}[:_]){5}[0-9a-f]{2}\b", "<address>", text)
    return text


def _section(title: str, body: str) -> str:
    return f"\n===== {title} =====\n{body.rstrip()}\n"


def build_report(log_lines: int = LOG_LINES) -> str:
    from .diagnose import report as diagnose_report

    parts = [
        "sluice bug report\n"
        "Your user name, computer name, home folder, USB serial numbers and Bluetooth addresses are replaced.\n"
        "It still contains device names, app names and plugin file paths. Look it over before sharing it.\n"
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
    parts.append(_section("PipeWire clock and buffer size (pw-metadata -n settings)",
                          _grep(_run(["pw-metadata", "-n", "settings"]), "clock")))
    top = _run(["pw-top", "-b", "-n", "2"], timeout=10.0)
    if top.startswith("("):
        parts.append(_section("Who is busy or erring right now (pw-top; ERR is dropouts per program)", top))
    else:
        last = last_pw_top_round(top)
        parts.append(_section("Who is busy or erring right now (pw-top; ERR is dropouts per program)",
                              top_errors(last) + "\n\n" + last))
    parts.append(_section("Sinks (pactl list short sinks)", _run(["pactl", "list", "short", "sinks"])))
    parts.append(_section("Sources (pactl list short sources)", _run(["pactl", "list", "short", "sources"])))
    parts.append(_section("sluice modules loaded", _grep(_run(["pactl", "list", "short", "modules"]), "sluice")))
    parts.append(_section("sluice ports and links (pw-link -l)", sluice_blocks(_run(["pw-link", "-l"]))))

    try:
        config = config_path().read_text(encoding="utf-8")
    except OSError:
        config = "(no saved settings yet)"
    parts.append(_section(f"Settings ({config_path()})", config))
    parts.append(_section("Computer (CPU and USB, which matter for dropouts)", hardware_summary()))
    try:
        log_text = logs.log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        log_text = ""
    parts.append(_section(f"Log: this session, then the end of the one before ({logs.log_path()})",
                          session_log(log_text, log_lines) if log_text else "(file not found)"))
    try:
        crash_text = logs.crash_path().read_text(encoding="utf-8", errors="replace")
        modified = logs.crash_path().stat().st_mtime
    except OSError:
        crash_text, modified = "", None
    parts.append(_section(f"Native crash log ({logs.crash_path()})",
                          crash_summary(crash_text, modified) if crash_text else "(file not found: no crash has been recorded)"))
    return "\n".join(parts)


def write_report(path: Optional[Path] = None) -> Path:
    path = Path(path) if path else Path.home() / "sluice-report.txt"
    path.write_text(anonymize(build_report()), encoding="utf-8")
    return path
