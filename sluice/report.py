# SPDX-License-Identifier: GPL-3.0-or-later
"""``sluice --report``: one text file with everything needed to understand a bug.

Only reads things (sluice's own files and a few read-only audio-system queries).
Personal details are replaced before it is written: the home folder becomes ``~``, and the user name,
computer name, user id, USB serial numbers and Bluetooth addresses become placeholders. Device names,
app names and plugin paths remain, so it is still worth a look before sharing.
"""

from __future__ import annotations

import os
import json
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from . import __version__, efficiency, logs
from .model import config_path

LOG_LINES = 300
PREVIOUS_LINES = 60  # the end of the session before this one (a crash happens at the end of a session)
CRASH_BLOCK_LINES = 40
REPEAT_MIN = 4  # this many identical lines in a row are shown as the first, a count, and the last
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
    kept = lines[starts[-1] :] if starts else lines
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
            slow = [line for line in lines[i + 1 : j] if _SLOW_BLOCK.search(line)][:3]  # a block over 100% is worth keeping
            out.append(
                f"    ... {run - 2 - len(slow)} similar lines, {_log_time(lines[i])} to {_log_time(lines[j])}"
                + (", the slow ones kept ..." if slow else " ...")
            )
            out.extend(slow)
            out.append(lines[j])
        else:
            out.extend(lines[i : j + 1])
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


def archive_note(archive_text: str) -> str:
    """One line about the archived traces: when the last one was and which version wrote it."""
    headings = [line for line in archive_text.splitlines() if line.startswith("--- archived trace:")]
    if not headings:
        return ""
    found = re.match(r"--- archived trace: (?:session|command) started (.+?) \(Sluice (.+?)\) ---", headings[-1])
    if found:
        return f"The last archived trace was written by the session that started {found.group(1)} (Sluice {found.group(2)}); {len(headings)} in all are in {logs.CRASH_ARCHIVE_NAME}."
    return f"{len(headings)} older trace(s) are in {logs.CRASH_ARCHIVE_NAME}."


def crash_summary(text: str, modified: Optional[float] = None, archive_text: str = "") -> str:
    """The native-crash file split into sessions: which session each trace belongs to, and when the file last changed.
    Traces from long-gone sessions live in the archive file and are only mentioned in one line."""
    lines = text.splitlines()
    blocks: list = []  # (header or None, trace lines)
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
        head.append(f"No native crash in the last {sessions} session(s).")
        old = archive_note(archive_text)
        if old:
            head.append(old)
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
    old = archive_note(archive_text)
    if old:
        head.append(f"\n{old}")
    return "\n".join(head)


_PW_TOP_COLUMNS = 9  # S ID QUANT RATE WAIT BUSY W/Q B/Q ERR


_VIDEO_FORMAT = re.compile(
    r"^(?:BGR|RGB|ARGB|ABGR|xRGB|xBGR|NV\d|I4\d\d|YUY|UYVY|YV12|MJPG|JPEG|GRAY|P0\d\d|YUV|H264|VP\d)", re.IGNORECASE
)
_SIZE = re.compile(r"^\d+x\d+$")


def _kind_of(parts: list) -> str:
    """'audio', 'video' (a screen or camera feed: its ERR counts skipped frames, not audio glitches) or 'virtual'
    (one of Sluice's own virtual devices, which report large counts that match nothing you can hear)."""
    if parts[-1].startswith(("sluice_", "input.sluice_", "output.sluice_")):
        return "virtual"
    fmt = parts[_PW_TOP_COLUMNS] if len(parts) > _PW_TOP_COLUMNS else ""
    size = parts[_PW_TOP_COLUMNS + 1] if len(parts) > _PW_TOP_COLUMNS + 1 else ""
    return "video" if _VIDEO_FORMAT.match(fmt) or _SIZE.match(size) else "audio"


def top_errors(text: str, limit: int = 6) -> str:
    """From the ``pw-top`` table: the audio programs and devices with a dropout count above zero, most first. Video feeds
    (screen capture) and Sluice's own virtual devices are named on a separate line, because their counts are not audio
    dropouts."""
    found: dict = {"audio": [], "video": [], "virtual": []}
    for line in text.splitlines():
        parts = line.split()
        if (
            len(parts) <= _PW_TOP_COLUMNS
            or parts[0] not in "RIS"
            or not parts[1].isdigit()
            or not parts[_PW_TOP_COLUMNS - 1].isdigit()
        ):
            continue
        errors = int(parts[_PW_TOP_COLUMNS - 1])
        if errors > 0:
            found[_kind_of(parts)].append((errors, parts[-1]))
    lines = []
    if found["audio"]:
        found["audio"].sort(reverse=True)
        listed = ", ".join(f"{name} ({count})" for count, name in found["audio"][:limit])
        lines.append(
            "Dropouts counted per audio program or device, most first: " + listed + ". The device that drives the audio "
            "is usually the one to look at; programs behind it show errors when it is late."
        )
    else:
        lines.append("No audio program or device shows dropouts in this snapshot.")
    if found["video"]:
        listed = ", ".join(f"{name} ({count})" for count, name in sorted(found["video"], reverse=True)[:limit])
        lines.append("Video feeds with errors (screen or camera capture: skipped frames, not audio): " + listed + ".")
    if found["virtual"]:
        total = sum(count for count, _ in found["virtual"])
        lines.append(
            f"Sluice's own virtual devices ({len(found['virtual'])}) show {total} errors in total. These counters do not "
            'match what you hear; the line "audio dropouts" in the log below is what Sluice itself counts.'
        )
    return "\n".join(lines)


_LOG_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
DROPOUT_MARKERS = (
    "audio dropouts:",
    "what changed just before",
    "nothing changed in the audio system",
    "MARKED BY YOU",
    "a dropout right after",
)


def _stamp(line: str) -> Optional[float]:
    found = _LOG_STAMP.match(line)
    if not found:
        return None
    try:
        return time.mktime(time.strptime(found.group(1), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def dropout_timeline(lines: list, now: Optional[float] = None, limit: int = 40) -> str:
    """The dropouts of one session with what changed just before each, and whether they are still happening."""
    picked = [line for line in lines if any(marker in line for marker in DROPOUT_MARKERS)]
    if not picked:
        return "No dropouts were logged in this session."
    now = time.time() if now is None else now
    times = [t for line, t in ((l, _stamp(l)) for l in picked if "audio dropouts:" in l or "MARKED BY YOU" in l) if t is not None]
    head = []
    if times:
        ago = max(0.0, now - max(times))
        when = f"{ago / 60:.0f} min" if ago >= 90 else f"{ago:.0f} s"
        state = "still happening (the last one was moments ago)" if ago <= 120 else "not happening now"
        gaps = [b - a for a, b in zip(sorted(times), sorted(times)[1:])]
        spread = f"; the gaps between them are {min(gaps) / 60:.0f} to {max(gaps) / 60:.0f} min" if gaps else ""
        head.append(
            f"{len(times)} dropout event(s) or marked glitch(es) in this session; the last was {when} before this report: "
            f"{state}{spread}."
        )
    shown = picked[-limit:]
    if len(picked) > len(shown):
        head.append(f"(first {len(picked) - len(shown)} lines not shown)")
    return "\n".join(head + shown)


USB_LINE = re.compile(
    r"usb \d+-[\d.]+: (?:new .*USB device number|USB disconnect|reset .*USB device|Product:|Manufacturer:|"
    r"over-current|cannot enumerate|unable to enumerate|disabled by hub|device not accepting address|"
    r"device descriptor read|cannot submit urb)",
    re.IGNORECASE,
)


def usb_events(limit: int = 30) -> str:
    """The last hours of USB connect, disconnect and reset lines from the kernel log. Serial numbers are not included."""
    text = _run(["journalctl", "-k", "--no-pager", "-o", "short-iso", "--since", "-4 hours"], timeout=8.0)
    if "No entries" in text and not text.startswith("("):  # 0.12.4: the journal was read and simply had nothing (dmesg,
        return "No USB connect, disconnect or reset lines in the kernel log of the last hours."  # tried next, needs root)
    if text.startswith("("):
        text = _run(["dmesg", "--time-format", "iso"], timeout=8.0)
    if text.startswith("("):
        return (
            f"{text}\nReading the kernel log may need permission: on many systems it works for members of the "
            "'systemd-journal' group."
        )
    found = [line for line in text.splitlines() if USB_LINE.search(line)]
    if not found:
        return "No USB connect, disconnect or reset lines in the kernel log of the last hours."
    shown = found[-limit:]
    note = [f"({len(found) - len(shown)} older lines not shown)"] if len(found) > len(shown) else []
    return "\n".join(note + shown)


def _short_names(text: str) -> dict:
    """``pactl list short sinks`` (or sources) → {index: name}."""
    names = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            names[parts[0].strip()] = parts[1].strip()
    return names


def _stream_blocks(text: str, header: str, target: str) -> list:
    """``pactl list sink-inputs`` (or source-outputs) → [(index, app, binary, target index)]."""
    found, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(header + " #"):
            current = {"index": line.split("#", 1)[1].strip(), "app": "", "binary": "", "target": "", "other": "", "node": ""}
            found.append(current)
        elif re.match(r"^[A-Z][A-Za-z ]+ #\d+$", line):
            current = None  # a block of another kind: its lines are not this stream's
        elif current is None:
            continue
        elif line.startswith(target + ":"):
            current["target"] = line.split(":", 1)[1].strip()
        elif line.startswith("application.name = "):
            current["app"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("application.process.binary = "):
            current["binary"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith(("media.name = ", "node.description = ")) and not current["other"]:
            current["other"] = line.split("=", 1)[1].strip().strip('"')  # 0.12.6: for streams without an app name
        elif line.startswith("node.name = "):
            current["node"] = line.split("=", 1)[1].strip().strip('"')
    rows = []
    for b in found:
        app = b["app"]
        if not app and not b["binary"]:
            if "sluice" in b["node"].lower():  # the copies behind Sluice's own recording devices and Broadcast
                app = f"Sluice's own ({b['node']})"
            else:
                app = b["other"] or b["node"]
        rows.append((b["index"], app, b["binary"], b["target"]))
    return rows


def stream_routes(streams_text: str, devices_text: str, header: str, target: str, verb: str) -> str:
    """0.12.4: every app's stream and the device it is on, e.g. "201  Shred A Billion (shredabillion.exe) → sluice_ch_game".
    This is what shows whether OBS records a channel's "Monitor of" (before the faders) or Sluice's recording device."""
    if streams_text.startswith("("):
        return streams_text
    names = _short_names(devices_text)
    rows = []
    for index, app, binary, where in _stream_blocks(streams_text, header, target):
        who = app or binary or "(no name)"
        if binary and binary.lower() not in who.lower():
            who += f" ({binary})"
        rows.append(f"{index:>5}  {who} → {names.get(where, where or '?')}")
    return "\n".join(rows) if rows else f"No app is {verb} right now."


def busy_programs(limit: int = 6) -> str:
    """How busy the computer is right now: the load average and the programs using the most CPU."""
    lines = []
    load = __import__("sluice.events", fromlist=["load_average"]).load_average()
    if load:
        lines.append(load[0].upper() + load[1:])
    table = _run(["ps", "-eo", "pcpu,comm", "--sort=-pcpu"], timeout=4.0)
    if table.startswith("("):
        lines.append(table)
    else:
        lines.append("Programs using the most CPU at this moment (percent of one thread):")
        lines.extend("  " + row.strip() for row in table.splitlines()[1 : limit + 1])
    return "\n".join(lines)


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
    for label, path in (
        ("CPU frequency setting", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
        ("USB power saving (seconds, -1 is off)", "/sys/module/usbcore/parameters/autosuspend"),
    ):
        try:
            lines.append(f"{label}: {Path(path).read_text(encoding='utf-8').strip()}")
        except OSError:
            lines.append(f"{label}: (not available)")
    lines.append("")
    lines.append("USB devices by controller (lsusb -t):")
    lines.append(_run(["lsusb", "-t"]))
    return "\n".join(lines)


def anonymize(text: str) -> str:
    """Replace details that identify a person or a machine with placeholders."""
    home = str(Path.home()).rstrip("/")
    if home and home != "/":
        text = text.replace(home, "~")
    try:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or Path.home().name
    except Exception:  # no home folder or user name on this system: nothing to hide, so nothing to replace
        user = ""
    host = platform.node()
    # Windows-style home folders first (Proton games show Z:\home\<name>\...), before the user name is replaced inside them
    text = re.sub(r"(?i)\b[A-Z]:\\(?:home|users)\\[^\\\s]+", "~", text)
    # 'User Name: x' / 'Host Name: y' lines from pactl info, then every other mention of the same words
    text = re.sub(r"(?m)^(\s*User Name:\s*).+$", r"\1<user>", text)
    text = re.sub(r"(?m)^(\s*Host Name:\s*).+$", r"\1<host>", text)
    text = re.sub(r"(?m)^(\s*Cookie:\s*).+$", r"\1<cookie>", text)
    text = re.sub(r"(SerialNumber:\s*)\S+", r"\1<serial>", text)
    for word, placeholder in ((user, "<user>"), (host, "<host>"), (host.split(".")[0] if host else "", "<host>")):
        if word and len(word) >= 3 and word.lower() not in ("root", "localhost", "user", "host"):
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", placeholder, text, flags=re.IGNORECASE)
    # the machine name in a kernel-log line, whatever it was when the line was written (it can change between boots)
    text = re.sub(r"(?m)^(\d{4}-\d\d-\d\dT[\d:.+-]+\s+)\S+(\s+kernel:)", r"\1<host>\2", text)
    text = re.sub(r"/run/user/\d+", "/run/user/<uid>", text)
    text = re.sub(r"/(?:home|Users)/[^/\s]+", "~", text)
    # USB serial numbers: alsa_input.usb-Vendor_Product_SERIAL-00.analog-stereo
    text = re.sub(r"(usb-[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*?)_([A-Z0-9]{8,})(-\d+)", r"\1_<serial>\3", text)
    # 0.12.6: the House Standard's placeholders (~ <user> <host> <ip> <mac> <secret> <steamid>), plus Sluice's own
    text = re.sub(r"(?i)\b(?:[0-9a-f]{2}[:_]){5}[0-9a-f]{2}\b", "<mac>", text)  # Bluetooth and network addresses
    text = _IPV4.sub(_ip_or_version, text)
    text = _IPV6.sub(_ipv6_or_not, text)
    text = re.sub(r"\b7656119\d{10}\b", "<steamid>", text)  # Steam ACCOUNT ids only: game ids (steam:1240440) stay
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b", "<secret>", text)
    text = re.sub(
        r"(?i)\b((?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|passwd)\s*[=:]\s*)"
        r"(?!<secret>)[^\s\"',;]{6,}",
        r"\1<secret>",
        text,
    )
    text = re.sub(r"(?i)(Authorization:\s*(?:Bearer|token)\s+)\S+", r"\1<secret>", text)
    return text


_IPV4 = re.compile(r"(?<![\w.=-])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\w.])")
_IPV6 = re.compile(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])")


def _ipv6_or_not(match) -> str:
    """Only what really is an IPv6 address (a time of day such as 19:02:00 is not) becomes <ip>; ::1 stays."""
    import ipaddress

    text = match.group(0)
    if not any(ch.isdigit() for ch in text):  # "a::b" in a program's text is not an address
        return text
    try:
        address = ipaddress.IPv6Address(text)
    except ValueError:
        return text
    return text if address.is_loopback or address.is_unspecified else "<ip>"


def _ip_or_version(match) -> str:
    """An IPv4 address becomes <ip>; a version number that looks like one (0.11.0.1, ==0.10.0) does not, nor does 127.0.0.1."""
    text = match.group(1)
    first = int(text.split(".")[0])
    if first == 0 or text.startswith("127.") or text == "255.255.255.255":
        return text
    return "<ip>"


def _section(title: str, body: str) -> str:
    return f"\n===== {title} =====\n{body.rstrip()}\n"


_UPDATED = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d)(?::\d\d)?\S*\s+INFO\s+sluice\.(?:selfupdate|update_install): updated (\S+) -> (\S+)",
    re.MULTILINE,
)


def update_history(log_text: str) -> str:
    """0.11.7: one line on the last update, from the log ("Updated 0.11.5 -> 0.11.6 on 2026-11-20 19:40"), or ""."""
    found = _UPDATED.findall(log_text or "")
    if not found:
        return ""
    when, old, new = found[-1]
    more = f" ({len(found)} updates in the log)" if len(found) > 1 else ""
    return f"Last update: {old} -> {new} on {when}{more}.\n"


def engine_summary(
    version: Optional[str] = None,
    expected: Optional[str] = None,
    older: Optional[bool] = None,
    error: Optional[str] = None,
    rebuild: Optional[dict] = "unset",
) -> str:
    """0.11.7: one line on the Rust engine: which, whether this Sluice ships a newer one, and the last rebuild and how it went."""
    from . import spectral, update_install

    version = spectral.RUST_VERSION if version is None else version
    expected = spectral.RUST_EXPECTED if expected is None else expected
    older = spectral.rust_is_older() if older is None else older
    error = spectral.RUST_ERROR if error is None else error
    rebuild = update_install.last_rebuild() if rebuild == "unset" else rebuild
    if version:
        line = f"Audio engine: Rust {version}" + (
            f" (this Sluice comes with {expected}: rebuild it for the fixes since)" if older else ""
        )
    elif error:
        line = f"Audio engine: Python (the Rust build could not be used: {error})"
    else:
        line = "Audio engine: Python (the Rust engine is not installed)"
    if rebuild:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(rebuild["at"]))
        line += f". Last rebuild: {when}, {'worked' if rebuild['result'] == 'ok' else rebuild['result']}"
    return line + ".\n"


def skin_summary() -> str:
    """One line on what is on screen: the look, the layout shown (a saved Free, gone in 0.11.5, shows Columns) and whether effects are reduced."""
    from . import themes

    try:
        saved = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    skin = themes.current_skin()
    chosen = saved.get("layout", "columns") if isinstance(saved, dict) else "columns"
    shown = chosen if chosen in ("columns", "rows") else "columns"
    note = f" (saved as {chosen})" if shown != chosen else ""
    return f"Skin: {skin}. Layout shown: {shown}{note}. Effects reduced: {'yes' if themes.reduce_effects() else 'no'}.\n"


_window_source = None  # a function returning what the window knows about its own arrangement (set by the window)


def set_window_source(source) -> None:
    """The window registers itself so the report can say how it was arranged; None when it closes."""
    global _window_source
    _window_source = source


def _window_info() -> dict:
    try:
        return dict(_window_source()) if _window_source is not None else {}
    except Exception as exc:  # the report must still be written
        return {"error": f"{type(exc).__name__}: {exc}"}


def window_summary() -> str:
    """One line on the size and arrangement of the window: what is needed to explain 'things overlap' or 'it is cut off'."""
    info = _window_info()
    if not info:
        return ""
    if info.get("error"):
        return f"Window: (could not read: {info['error']})\n"
    dock = {"right": "Listen and Broadcast beside the channels", "bottom": "Listen and Broadcast in a bar under the channels"}
    automatic = "yes" if info["mode"] != info["chosen"] else "no"
    return (
        f"Window: {info['width']}x{info['height']} px{' (full screen)' if info.get('fullscreen') else ''} on a {info['screen']} screen at scale "
        f"{info['scale']}. Size step: {info['step']}. Arrangement: {info['mode']}"
        f"{'' if info['mode'] == 'mini' else ', ' + dock.get(info['dock'], info['dock'])} (chosen: {info['chosen']}; "
        f"switched by the window's size: {automatic}). Rearranged {info['relayouts']} times this session. "
        f"Skin's own colours: {'on' if info.get('look_colors', True) else 'off'}.\n"
        f"Desktop widgets: {info.get('widgets', 'none open')}.\n"
        + (f"Minimizing: {info['minimize']}.\n" if info.get("minimize") else "")
    )


def window_layout() -> str:
    """The sizes of the main parts of the window, so a layout problem can be seen without a screenshot."""
    info = _window_info()
    return info.get("layout", "") if info else ""


def _safe(make) -> str:
    """A summary line that must never stop the report being written."""
    try:
        return make()
    except Exception as exc:
        return f"({type(exc).__name__} while writing a summary line: {exc})\n"


def header() -> str:
    """0.13.1 (House Standard): app, version, channel, install type, distro, desktop, Wayland/X11, kernel. One line each."""
    from . import update_install
    from .model import Mixer

    try:
        channel = Mixer.load(config_path()).update_channel if config_path().is_file() else "stable"
    except Exception:  # noqa: BLE001 - a damaged settings file still gets a report
        channel = "unknown"
    root = update_install.install_root()
    if root is None:
        install = "not installed (run from a folder or a package)"
    elif update_install.runs_from_download(root):
        install = f"from its download folder ({logs.short_path(root)})"
    else:
        install = f"in its own folder ({logs.short_path(root)})"
    distro = ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                distro = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    session = "Wayland" if os.environ.get("WAYLAND_DISPLAY") else "X11" if os.environ.get("DISPLAY") else "no desktop session"
    return (
        f"App: Sluice {__version__}\nUpdate channel: {channel}\nInstalled: {install}\nDistribution: {distro or 'unknown'}\n"
        f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP') or 'unknown'} ({session})\nKernel: {platform.release()}\n"
    )


def build_report(log_lines: int = LOG_LINES, include_settings: bool = True) -> str:
    """The bug report. ``include_settings`` False (the Report dialog's choice) leaves the settings file out: it names your
    channels, devices and apps."""
    from .diagnose import report as diagnose_report

    try:
        efficiency_data, efficiency_source = efficiency.for_report()
    except Exception as exc:  # the report must still be written
        efficiency_data, efficiency_source = None, f"(could not read: {exc})"
    parts = [
        "sluice bug report\n"
        "Your user name, computer name, home folder, USB serial numbers and Bluetooth addresses are replaced.\n"
        "It still contains device names, app names and plugin file paths. Look it over before sharing it.\n"
        f"Created: {time.strftime('%Y-%m-%d %H:%M:%S %Z')} by Sluice {__version__}\n"
        + _safe(header)
        + skin_summary()
        + window_summary()
        + _safe(engine_summary)
        + _safe(lambda: update_history(logs.log_path().read_text(encoding="utf-8", errors="replace")))
        + efficiency.summary_line(efficiency_data)
    ]
    parts.append(_section("sluice", f"version {__version__}\nPython {platform.python_version()}\n{platform.platform()}"))
    if window_layout():
        parts.append(_section("Window layout (position and size in pixels of the main parts)", window_layout()))

    try:
        parts.append(_section("Self-check (sluice --diagnose)", diagnose_report(engine_line=False)[0]))
    except Exception as exc:
        parts.append(_section("Self-check (sluice --diagnose)", f"(could not run: {exc})"))

    parts.append(_section("PipeWire", _run(["pipewire", "--version"])))
    parts.append(_section("WirePlumber", _run(["wireplumber", "--version"])))
    parts.append(_section("pactl info", _run(["pactl", "info"])))
    parts.append(
        _section(
            "PipeWire clock and buffer size (pw-metadata -n settings)", _grep(_run(["pw-metadata", "-n", "settings"]), "clock")
        )
    )
    top = _run(["pw-top", "-b", "-n", "2"], timeout=10.0)
    if top.startswith("("):
        parts.append(_section("Who is busy or erring right now (pw-top; ERR is dropouts per program)", top))
    else:
        last = last_pw_top_round(top)
        parts.append(
            _section("Who is busy or erring right now (pw-top; ERR is dropouts per program)", top_errors(last) + "\n\n" + last)
        )
    parts.append(_section("Sinks (pactl list short sinks)", _run(["pactl", "list", "short", "sinks"])))
    parts.append(_section("Sources (pactl list short sources)", _run(["pactl", "list", "short", "sources"])))
    parts.append(
        _section(
            "Apps playing and where their sound goes (pactl list sink-inputs)",
            stream_routes(
                _run(["pactl", "list", "sink-inputs"]), _run(["pactl", "list", "short", "sinks"]), "Sink Input", "Sink", "playing"
            ),
        )
    )
    parts.append(
        _section(
            'Apps recording and what they record (pactl list source-outputs; ".monitor" is before the faders)',
            stream_routes(
                _run(["pactl", "list", "source-outputs"]),
                _run(["pactl", "list", "short", "sources"]),
                "Source Output",
                "Source",
                "recording",
            ),
        )
    )
    parts.append(_section("sluice modules loaded", _grep(_run(["pactl", "list", "short", "modules"]), "sluice")))
    parts.append(_section("sluice ports and links (pw-link -l)", sluice_blocks(_run(["pw-link", "-l"]))))

    try:
        config = config_path().read_text(encoding="utf-8")
    except OSError:
        config = "(no saved settings yet)"
    if not include_settings:
        config = "(left out: chosen when the report was made)"
    parts.append(_section(f"Settings ({config_path()})", config))
    parts.append(
        _section(
            "Sluice's own efficiency (its CPU, memory and wake-ups; numbers only)",
            efficiency.format_section(efficiency_data, efficiency_source),
        )
    )
    parts.append(_section("Computer (CPU and USB, which matter for dropouts)", hardware_summary()))
    parts.append(_section("How busy the computer is right now", busy_programs()))
    parts.append(_section("USB connects, disconnects and resets in the kernel log (last hours)", usb_events()))
    try:
        log_text = logs.log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        log_text = ""
    sessions = split_sessions(log_text.splitlines()) if log_text else []
    parts.append(
        _section(
            "Dropouts in this session and what changed just before each",
            dropout_timeline(sessions[-1]) if sessions else "(no log yet)",
        )
    )
    parts.append(
        _section(
            f"Log: this session, then the end of the one before ({logs.log_path()})",
            session_log(log_text, log_lines) if log_text else "(file not found)",
        )
    )
    try:
        crash_text = logs.crash_path().read_text(encoding="utf-8", errors="replace")
        modified = logs.crash_path().stat().st_mtime
    except OSError:
        crash_text, modified = "", None
    try:
        archive_text = logs.crash_archive_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        archive_text = ""
    parts.append(
        _section(
            f"Native crash log ({logs.crash_path()})",
            crash_summary(crash_text, modified, archive_text)
            if crash_text
            else ("(file not found: no crash has been recorded)" + ("\n" + archive_note(archive_text) if archive_text else "")),
        )
    )
    return "\n".join(parts)


KEEP_REPORTS = 10
LATEST_NAME = "sluice-report-latest.txt"
_DATED = re.compile(r"^sluice-report-\d[\w.\-]*\.txt$")


def default_name(now: Optional[float] = None) -> str:
    """``sluice-report-0.9.7-2026-11-14-1002.txt``: sorts by time and shows the version without opening it."""
    return f"sluice-report-{__version__}-{time.strftime('%Y-%m-%d-%H%M', time.localtime(now))}.txt"


def is_dated_name(name: str) -> bool:
    return bool(_DATED.match(name)) and name != LATEST_NAME


def _tidy(folder: Path, keep: int = KEEP_REPORTS) -> None:
    """Keep the newest few dated reports. Only files with the dated name are ever touched, never ones you named."""
    try:
        old = sorted((p for p in folder.iterdir() if is_dated_name(p.name)), key=lambda p: (p.stat().st_mtime, p.name))
    except OSError:
        return
    for p in old[:-keep] if keep > 0 else old:
        try:
            p.unlink()
        except OSError:
            pass


def write_report(path: Optional[Path] = None) -> Path:
    """Writes the report. With no path it goes to the home folder under a dated name. A dated name also updates
    removes the oldest dated reports beyond ten (and the ``sluice-report-latest.txt`` that 0.9.7 left beside them: there
    is one report per save, the one with the date in its name); any other name is written alone."""
    path = Path(path) if path else Path.home() / default_name()
    text = anonymize(build_report())
    path.write_text(text, encoding="utf-8")
    if is_dated_name(path.name):
        try:
            (path.parent / LATEST_NAME).unlink()
        except OSError:
            pass
        _tidy(path.parent)
    return path
