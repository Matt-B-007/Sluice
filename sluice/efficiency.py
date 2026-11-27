# SPDX-License-Identifier: GPL-3.0-or-later
"""How much of the computer Sluice itself uses, for the bug report.

The report already says who is busy and who drops out; this says how efficient Sluice is on that computer: its own CPU (when the
window is open and when it is not), its memory, how much of each audio block its own work uses, how often it wakes up, and which
features were on. Every bug report then shows where Sluice could use less, and plain notes ("flags") point at anything that looks
wasteful.

Only numbers and counts are kept: no device names, app names or audio. Nothing runs on the audio thread and there is no timer of its
own: ``Tracker.sample`` is called from the window's existing half-second tick and costs two clock reads.

A running Sluice writes a small snapshot file once a minute (and when it quits), so ``sluice --report`` from a terminal can show it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from . import logs

log = logging.getLogger(__name__)

SNAPSHOT_NAME = "efficiency.json"
SNAPSHOT_SECONDS = 60.0
BASELINE_SECONDS = 60.0  # the memory use at this point is what later growth is compared with
MEMORY_EVERY = 15 * 60.0  # 0.12.4: memory is noted this often, so a report shows whether it grows steadily or jumps once
MEMORY_KEEP = 200  # about two days of samples; the oldest are dropped
STATES = ("open", "tray", "background")  # window visible / hidden into the tray / minimized or hidden with no tray

# When a flag is raised (one per line in the report). These are rules of thumb, not alarms.
FLAG_AUDIO_AVERAGE = 0.25  # share of a block's time Sluice's own audio work uses, on average
FLAG_AUDIO_WORST = 0.85
FLAG_CPU_OPEN = 15.0  # percent of one core while the window is open
FLAG_CPU_HIDDEN = 1.5  # percent of one core while the window is hidden or minimized
FLAG_RAM_MB = 500.0
FLAG_RAM_GROWTH_MB = 150.0
FLAG_WAKEUPS_HIDDEN = 12.0  # meter updates a second while nothing shows them
FLAG_HELPERS_PER_MINUTE = 30.0  # helper programs started a minute
FLAG_HELPER_SHARE = 0.25  # share of all CPU used by helper programs, when the total is not tiny
MIN_SECONDS = 30.0  # a flag needs this much time in the state, or the number means little


def snapshot_path() -> Path:
    return logs.state_dir() / SNAPSHOT_NAME


def _cpu_seconds() -> float:
    """CPU time used by this whole process (every thread, the Rust audio thread too) and by the helper programs it has run and
    waited for (``pw-link``), since it started: the cost of Sluice as a whole, not just of its own Python and Rust."""
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


def _helper_cpu_seconds() -> float:
    t = os.times()
    return t.children_user + t.children_system


# Helper programs Sluice starts (today only ``pw-link``, to read and make connections). Starting a program costs far more than a
# call inside the process, so how often it happens is one of the first things to look at.
_helpers = {"launches": 0, "seconds": 0.0}
_helpers_lock = threading.Lock()


def helper_launched(seconds: float) -> None:
    """Called after every helper program run: how long it took (wall time)."""
    with _helpers_lock:
        _helpers["launches"] += 1
        _helpers["seconds"] += max(0.0, seconds)


def _status(field: str) -> Optional[float]:
    """A number from /proc/self/status in kB (VmRSS, VmHWM) or a plain count (Threads); None when it is not there."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith(field + ":"):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


# --------------------------------------------------------------------------------------- threads
_CLOCK_TICKS = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0


def _group_name(name: str) -> str:
    """One name for a family of threads (``Thread-3``, ``OpenBLAS-7`` ...): digits and a trailing counter are dropped."""
    name = re.sub(r"[-_ ]?\d+$", "", name.strip()) or name.strip() or "unnamed"
    return name


def thread_table(audio_thread: Optional[int] = None, main_thread_before: float = 0.0, before: Optional[dict] = None) -> list:
    """[(group name, thread count, cpu seconds, is the window's thread, is the audio thread)] for every thread of this process, biggest
    CPU first. Python threads are named by their ``threading`` name, the rest by the name the system gives them (the libraries that start
    them, such as OpenBLAS or Qt, name their own). The CPU of a thread that has already ended is not in here: see ``cpu_split``.
    ``main_thread_before`` is what the window's thread had used before this run began (it carries over a restart in the same process).
    ``before`` is the same for any thread, by thread id: what each had used when this run began."""
    before = before or {}
    names = {}
    try:
        for t in threading.enumerate():
            if getattr(t, "native_id", None):
                names[t.native_id] = t.name
    except Exception as exc:  # the Python names are a nicety: the system's own thread names still show
        log.debug("could not read the Python thread names: %s", exc)
    pid = os.getpid()
    groups: dict = {}
    try:
        tids = [int(x) for x in os.listdir("/proc/self/task")]
    except (OSError, ValueError):
        return []
    for tid in tids:
        try:
            raw = Path(f"/proc/self/task/{tid}/stat").read_text(encoding="utf-8")
            comm = Path(f"/proc/self/task/{tid}/comm").read_text(encoding="utf-8").strip()
            rest = raw[raw.rindex(")") + 2:].split()
            cpu = (int(rest[11]) + int(rest[12])) / _CLOCK_TICKS  # utime + stime
        except (OSError, ValueError, IndexError):
            continue
        gui, audio = tid == pid, tid == audio_thread
        if gui:
            label = "window (main thread, with the engine's timers)"
        elif audio:
            label = "audio callback"
        else:
            label = _group_name(names.get(tid) or comm)
        entry = groups.setdefault(label, [0, 0.0, gui, audio])
        entry[0] += 1
        entry[1] += max(0.0, cpu - max(main_thread_before if gui else 0.0, before.get(tid, 0.0)))
    return sorted(((n, c, cpu, g, a) for n, (c, cpu, g, a) in groups.items()), key=lambda r: (-r[2], r[0]))


def _main_thread_cpu() -> float:
    """CPU seconds of the window's (main) thread so far; it is the one thread that survives Sluice restarting itself."""
    return _thread_cpu(os.getpid())


def _all_thread_cpu() -> dict:
    """{thread id: CPU seconds so far} for every thread of this process."""
    try:
        return {int(x): _thread_cpu(int(x)) for x in os.listdir("/proc/self/task")}
    except (OSError, ValueError):
        return {}


def _thread_cpu(tid: int) -> float:
    """CPU seconds one thread of this process has used so far (0 when it is gone)."""
    try:
        raw = Path(f"/proc/self/task/{tid}/stat").read_text(encoding="utf-8")
        rest = raw[raw.rindex(")") + 2:].split()
        return (int(rest[11]) + int(rest[12])) / _CLOCK_TICKS
    except (OSError, ValueError, IndexError):
        return 0.0


def cpu_split(table: list, helper_cpu: float, total_cpu: Optional[float] = None) -> dict:
    """Where Sluice's CPU went during this run: the window, the audio callback, every other thread, helper programs, and what
    threads that have already ended used (the difference to the process total)."""
    t = os.times()
    own = (t.user + t.system) if total_cpu is None else total_cpu
    gui = sum(r[2] for r in table if r[3])
    audio = sum(r[2] for r in table if r[4])
    other = sum(r[2] for r in table if not r[3] and not r[4])
    ended = max(0.0, own - gui - audio - other)
    return {"window": round(gui, 2), "audio": round(audio, 2), "other_threads": round(other, 2), "ended_threads": round(ended, 2),
            "helpers": round(helper_cpu, 2)}


class Tracker:
    """Collects the numbers while Sluice runs. One per window."""

    def __init__(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self.started = now
        self.last = now
        self.cpu_last = _cpu_seconds()
        self.helper_cpu_start = _helper_cpu_seconds()
        with _helpers_lock:
            self.helpers_start = (_helpers["launches"], _helpers["seconds"])
        # Sluice restarts itself in the same process after an update (the process id and its start time stay), and the system keeps counting
        # CPU across that. These starting values leave out everything the program before the restart used.
        times = os.times()
        self.base_total_cpu = times.user + times.system
        self.base_helper_cpu = times.children_user + times.children_system
        self.base_main_cpu = _main_thread_cpu()
        self.base_thread_cpu = _all_thread_cpu()   # every thread alive now: whatever it used so far is not this run's
        self.state = "open"
        self.seconds = {s: 0.0 for s in STATES}
        self.cpu = {s: 0.0 for s in STATES}
        self.ticks = {s: 0 for s in STATES}  # meter updates
        self.audio_cpu = {s: 0.0 for s in STATES}  # of the CPU above, what the audio callback thread used (the work being asked for)
        self.audio_cpu_last = 0.0
        self.audio_read_at = 0.0
        self.rss_baseline: Optional[float] = None
        self.rss_samples: list = []  # (seconds since start, MB)
        self.last_written = 0.0
        self.engine = None

    # ------------------------------------------------------------ collecting
    def set_state(self, state: str, now: Optional[float] = None) -> None:
        """The window was shown, hidden or minimized: time and CPU up to now belong to the old state."""
        if state not in STATES or state == self.state:
            return
        self.sample(now, state_changed=True)  # reads the audio thread's CPU too, so it is counted under the state it was used in
        self.state = state

    def sample(self, now: Optional[float] = None, state_changed: bool = False) -> None:
        now = time.monotonic() if now is None else now
        cpu = _cpu_seconds()
        self.seconds[self.state] += max(0.0, now - self.last)
        self.cpu[self.state] += max(0.0, cpu - self.cpu_last)
        self.last, self.cpu_last = now, cpu
        tid = getattr(getattr(self.engine, "graph", None), "audio_thread_id", None)
        if tid and (now - self.audio_read_at >= 1.0 or state_changed):
            self.audio_read_at = now
            used = _thread_cpu(tid)
            self.audio_cpu[self.state] += max(0.0, used - self.audio_cpu_last)
            self.audio_cpu_last = used
        if self.rss_baseline is None and now - self.started >= BASELINE_SECONDS:
            self.rss_baseline = _status("VmRSS")
        if self.rss_baseline is not None and (not self.rss_samples or now - self.started - self.rss_samples[-1][0] >= MEMORY_EVERY):
            mb = _mb(_status("VmRSS"))
            if mb is not None:
                self.rss_samples.append((round(now - self.started, 1), mb))
                del self.rss_samples[:-MEMORY_KEEP]

    def meter_tick(self) -> None:
        self.ticks[self.state] += 1

    # ------------------------------------------------------------ reading
    def snapshot(self, engine=None, now: Optional[float] = None) -> dict:
        """Everything the report needs, as plain numbers (and a few words)."""
        self.sample(now)
        engine = engine or self.engine
        total = sum(self.seconds.values())
        data: dict = {
            "taken": time.time(),
            "seconds": round(total, 1),
            "state": self.state,
            "by_state": {s: {"seconds": round(self.seconds[s], 1), "cpu_seconds": round(self.cpu[s], 2), "meter_updates": self.ticks[s],
                             "audio_cpu_seconds": round(self.audio_cpu[s], 2)}
                         for s in STATES},
            "cpu_seconds": round(sum(self.cpu.values()), 2),
            "rss_mb": _mb(_status("VmRSS")),
            "rss_peak_mb": _mb(_status("VmHWM")),
            "rss_baseline_mb": _mb(self.rss_baseline),
            "rss_over_time": [list(sample) for sample in self.rss_samples],
            "startup": dict(STARTUP),
            "threads": _status("Threads"),
            "helper_cpu_seconds": round(max(0.0, _helper_cpu_seconds() - self.helper_cpu_start), 3),
        }
        table = thread_table(getattr(getattr(engine, "graph", None), "audio_thread_id", None), main_thread_before=self.base_main_cpu,
                             before=self.base_thread_cpu)
        data["thread_groups"] = [{"name": n, "count": c, "cpu_seconds": round(cpu, 2)} for n, c, cpu, _g, _a in table[:25]]
        data["thread_groups_more"] = max(0, len(table) - 25)
        data["math_libraries"] = math_libraries()
        data["processor_threads"] = os.cpu_count()
        t = os.times()
        data["cpu_split"] = cpu_split(table, t.children_user + t.children_system - self.base_helper_cpu,
                                      t.user + t.system - self.base_total_cpu)
        data["process_seconds"] = round(max(0.0, time.monotonic() - self.started), 1)
        try:
            from . import backend

            data["pulse_recent"] = backend.recent_pulse_calls()
        except Exception as exc:  # never let the report fail over this
            log.debug("could not read the audio-server call list: %s", exc)
        with _helpers_lock:
            data["helper_launches"] = _helpers["launches"] - self.helpers_start[0]
            data["helper_seconds"] = round(_helpers["seconds"] - self.helpers_start[1], 2)
        if engine is not None:
            data.update(_engine_facts(engine))
        return data

    def maybe_write(self, now: Optional[float] = None) -> None:
        """Once a minute: keep a snapshot where ``sluice --report`` can find it."""
        now = time.monotonic() if now is None else now
        if now - self.last_written >= SNAPSHOT_SECONDS:
            self.write(now=now)

    def write(self, now: Optional[float] = None) -> None:
        self.last_written = time.monotonic() if now is None else now
        if not logs.running_path().exists():
            return  # not a real session (a test, or the marker is gone): leave the saved snapshot of the real one alone
        data = self.snapshot(now=now)
        data["pid"] = os.getpid()
        try:
            path = snapshot_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass  # never worth bothering anyone about


def _mb(kilobytes: Optional[float]) -> Optional[float]:
    return None if kilobytes is None else round(kilobytes / 1024.0, 1)


def _engine_facts(engine) -> dict:
    """Which features were on: counts only."""
    from . import dsp, spectral

    mixer = engine.mixer
    effects = [e for c in mixer.channels for e in c.effects]
    average, worst, blocks = engine.load_stats()
    return {
        "audio_load_average": round(average, 4),
        "audio_load_worst": round(worst, 4),
        "audio_load_worst_at": getattr(engine, "worst_block", lambda: (None, 0.0))()[0],
        "audio_load_worst_after": round(getattr(engine, "worst_block", lambda: (None, 0.0))()[1], 1),
        "audio_load_samples": blocks,
        "audio_wait": getattr(engine, "wait_stats", lambda: None)(),
        "dropouts": int(getattr(engine.io, "xruns", 0) or 0),
        "channels": len(mixer.channels),
        "mixes": len(mixer.mixes),
        "effects_on": sum(1 for e in effects if not e.bypass),
        "effects_bypassed": sum(1 for e in effects if e.bypass),
        "vst3_plugins": sum(1 for e in effects if e.kind == "vst3" and not e.bypass),
        "mic_channels": sum(1 for c in mixer.channels if c.devices),
        "recording_mix": bool(mixer.has_recording_mix),
        "live_voice_display": bool(getattr(engine, "tap_open", False)),
        "buffer_frames": int(getattr(engine.io, "blocksize", 0) or 0),
        "sample_rate": int(getattr(engine.io, "sample_rate", 0) or 0),
        "dsp": f"{dsp.MIX_BACKEND}" + (f" (Rust engine version {spectral.RUST_VERSION}, numbered apart from Sluice)" if spectral.RUST_VERSION else ""),
        "audio_client": type(engine.io).__name__,
    }


# ------------------------------------------------------------------------------------------ reading it back
def _percent(cpu: float, seconds: float) -> Optional[float]:
    return None if seconds <= 0 else 100.0 * cpu / seconds


def cpu_percent(data: dict) -> dict:
    """Average CPU as a percent of one core: overall and for each window state that lasted long enough to mean something."""
    result = {"all": _percent(data.get("cpu_seconds", 0.0), data.get("seconds", 0.0))}
    for state, values in data.get("by_state", {}).items():
        result[state] = _percent(values.get("cpu_seconds", 0.0), values.get("seconds", 0.0)) if values.get("seconds", 0.0) >= 1 else None
    return result


def flags(data: dict) -> list:
    """Plain notes about anything that looks wasteful. An empty list means nothing stood out."""
    notes: list = []
    cpu = cpu_percent(data)
    by_state = data.get("by_state", {})

    def seconds(state: str) -> float:
        return by_state.get(state, {}).get("seconds", 0.0)

    if data.get("audio_load_samples", 0) >= 20:
        if data.get("audio_load_average", 0.0) > FLAG_AUDIO_AVERAGE:
            notes.append(f"Sluice's audio work uses {data['audio_load_average']:.0%} of each block on average: heavy "
                         "(a bigger audio buffer, fewer effects or the Rust engine would lower it).")
        if data.get("audio_load_worst", 0.0) > FLAG_AUDIO_WORST:
            notes.append(f"A block took {data['audio_load_worst']:.0%} of its time at worst: close to a dropout.")
    if cpu.get("open") is not None and seconds("open") >= MIN_SECONDS and cpu["open"] > FLAG_CPU_OPEN:
        notes.append(f"{cpu['open']:.1f}% of a core while the window was open: more than expected.")
    for state in ("tray", "background"):
        # The audio work (the effects on your microphone, the mixing) is what Sluice is there to do: it runs the same with the window
        # hidden. Only the rest, which is what hiding the window should have removed, is held against the program.
        rest = _percent(max(0.0, by_state.get(state, {}).get("cpu_seconds", 0.0) - by_state.get(state, {}).get("audio_cpu_seconds", 0.0)),
                        by_state.get(state, {}).get("seconds", 0.0))
        if rest is not None and seconds(state) >= MIN_SECONDS and rest > FLAG_CPU_HIDDEN:
            notes.append(f"{rest:.1f}% of a core while the window was hidden ({state}), not counting the audio work: "
                         "it should be close to idle.")
        ticks = by_state.get(state, {}).get("meter_updates", 0)
        if seconds(state) >= MIN_SECONDS and ticks / seconds(state) > FLAG_WAKEUPS_HIDDEN:
            notes.append(f"{ticks / seconds(state):.0f} meter updates a second while the window was hidden: nobody could see them.")
    rss = data.get("rss_mb")
    if rss is not None and rss > FLAG_RAM_MB:
        notes.append(f"{rss:.0f} MB of memory in use: more than expected.")
    base = data.get("rss_baseline_mb")
    if rss is not None and base is not None and rss - base > FLAG_RAM_GROWTH_MB:
        notes.append(f"Memory grew by {rss - base:.0f} MB since the first minute: a possible leak.")
    seconds_all = data.get("seconds", 0.0)
    launches = data.get("helper_launches", 0)
    if seconds_all >= MIN_SECONDS and launches * 60.0 / seconds_all > FLAG_HELPERS_PER_MINUTE:
        notes.append(f"{launches * 60.0 / seconds_all:.0f} helper programs (pw-link) started a minute: polling like this costs more "
                     "than the work itself.")
    if seconds_all >= MIN_SECONDS and data.get("cpu_seconds", 0.0) > 0:
        share = data.get("helper_cpu_seconds", 0.0) / data["cpu_seconds"]
        if share > FLAG_HELPER_SHARE and 100.0 * data["cpu_seconds"] / seconds_all > 0.5:
            notes.append(f"Helper programs used {share:.0%} of all the CPU Sluice caused.")
    dsp_text = data.get("dsp", "")
    if dsp_text.startswith("python"):
        notes.append("The Rust engine is not in use, so Sluice runs its slower Python version of the audio work.")
    return notes


# ------------------------------------------------------------------------------------------------ 0.12.6: start-up
STARTUP: dict = {}  # name -> seconds after the process started, in the order they happened


def process_age() -> Optional[float]:
    """Seconds since this process started (the kernel's own record, so Python's start-up and imports are counted too)."""
    try:
        start_ticks = int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19])
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return max(0.0, uptime - start_ticks / os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError):
        return None


def startup_mark(name: str) -> None:
    """Note that start-up reached ``name`` (only the first time)."""
    if name not in STARTUP:
        age = process_age()
        if age is not None:
            STARTUP[name] = round(age, 3)


def startup_line(marks: Optional[dict]) -> str:
    """ "window shown 1.42 s after start (Python and imports 0.61, audio connected 0.66, ...)" """
    if not marks:
        return ""
    steps, previous = [], 0.0
    for name, at in marks.items():
        steps.append(f"{name} {at:.2f} (+{at - previous:.2f})")
        previous = at
    return " · ".join(steps)


def wait_line(wait) -> str:
    """0.12.6: how much of the audio work was waiting for Python's lock, held by the window: a block that waits long enough
    for the window becomes a dropout, however little work it has."""
    if not wait:
        return "waiting for the window (Python's lock): not measured (only the Rust audio client 0.11.1 and later measures it)"
    average, worst, in_worst = (list(wait) + [None, None, None])[:3]
    text = f"of that, waiting for the window (Python's lock) before the work could start: average {average:.1%}, worst {worst:.1%}"
    if in_worst is not None:
        text += f"; the worst block spent {in_worst:.1%} of a block's time waiting"
    return text


def memory_over_time(samples: list, every: float = 3600.0) -> str:
    """0.12.4: the memory samples, one an hour (the first and the latest always), as "0:01 61 MB · 1:00 63 MB · …"."""
    shown, next_at = [], None
    for i, (seconds, mb) in enumerate(samples):
        if next_at is None or seconds >= next_at or i == len(samples) - 1:
            shown.append(f"{int(seconds // 3600)}:{int(seconds % 3600 // 60):02d} {mb:.0f} MB")
            next_at = (seconds // every + 1) * every
    return " · ".join(shown) if len(shown) > 1 else ""


def summary_line(data: Optional[dict]) -> str:
    """One line for the top of the report."""
    if not data:
        return "Efficiency: no measurements (Sluice was not running in this session)."
    cpu = cpu_percent(data)
    parts = []
    if cpu.get("all") is not None:
        parts.append(f"CPU {cpu['all']:.1f}% of one core on average")
    if data.get("rss_mb") is not None:
        peak = data.get("rss_peak_mb")
        parts.append(f"RAM {data['rss_mb']:.0f} MB" + (f" (peak {peak:.0f})" if peak is not None else ""))
    if data.get("audio_load_samples", 0):
        parts.append(f"audio load {data['audio_load_average']:.0%} average, {data['audio_load_worst']:.0%} worst")
    notes = flags(data)
    parts.append(f"{len(notes)} flag{'s' if len(notes) != 1 else ''}" if notes else "no flags")
    return "Efficiency: " + ", ".join(parts) + "."


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    return f"{seconds / 3600:.1f} h"


_MATH_LIBRARIES = (("OpenBLAS", re.compile(r"libopenblas|libscipy_openblas")), ("Intel MKL", re.compile(r"libmkl_")),
                   ("BLIS", re.compile(r"libblis")), ("ATLAS", re.compile(r"libatlas")),
                   ("OpenMP (GNU)", re.compile(r"libgomp")), ("OpenMP (LLVM)", re.compile(r"libomp|libiomp")),
                   ("FFTW", re.compile(r"libfftw3")))


def math_libraries(maps_text: Optional[str] = None) -> list:
    """The maths libraries loaded into this process, by name. They start worker threads of their own (OpenBLAS starts one
    per processor thread), which explains a crowd of threads named ``python``. Reads /proc/self/maps unless given text."""
    if maps_text is None:
        try:
            maps_text = Path("/proc/self/maps").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    paths = {line.split(None, 5)[5].strip() for line in maps_text.splitlines() if len(line.split(None, 5)) == 6}
    found = []
    for name, pattern in _MATH_LIBRARIES:
        files = sorted({os.path.basename(p) for p in paths if pattern.search(os.path.basename(p))})
        if files:
            found.append(f"{name} ({', '.join(files)})")
    return found


def format_section(data: Optional[dict], source: str = "") -> str:
    """The report's section as text."""
    if not data:
        return "(no measurements: Sluice has not run long enough to write them)"
    cpu = cpu_percent(data)
    lines = [source] if source else []
    lines.append(f"Measured over {_duration(data.get('seconds', 0.0))}. CPU is a percent of ONE core (the audio thread and the helper programs included).")
    lines.append("")
    lines.append("CPU")
    names = {"open": "window open", "tray": "hidden in the tray", "background": "minimized or hidden"}
    for state in STATES:
        values = data.get("by_state", {}).get(state, {})
        if values.get("seconds", 0.0) < 1:
            continue
        value = cpu.get(state)
        rate = values.get("meter_updates", 0) / values["seconds"]
        audio = _percent(values.get("audio_cpu_seconds", 0.0), values["seconds"])
        part = f"   (audio callback {audio:.2f}%, the rest {max(0.0, (value or 0.0) - audio):.2f}%)" if audio is not None and value is not None else ""
        lines.append(f"  {names[state]:<20} {_duration(values['seconds']):>8}   "
                     f"{'-' if value is None else format(value, '.2f') + '%':>8}   {rate:.1f} meter updates/s{part}")
    if cpu.get("all") is not None:
        lines.append(f"  {'all together':<20} {_duration(data.get('seconds', 0.0)):>8}   {cpu['all']:.2f}%")
        if "helper_launches" in data:
            helper = _percent(data.get("helper_cpu_seconds", 0.0), data.get("seconds", 0.0)) or 0.0
            per_minute = data["helper_launches"] * 60.0 / data["seconds"] if data.get("seconds") else 0.0
            lines.append(f"  of which helper programs (pw-link): {helper:.2f}%; started {data['helper_launches']} times "
                         f"({per_minute:.1f} a minute, {data.get('helper_seconds', 0.0):.1f} s waiting for them)")
    lines.append("")
    lines.append("Memory")
    if data.get("rss_mb") is not None:
        text = f"  now {data['rss_mb']:.0f} MB, peak {data.get('rss_peak_mb') or 0:.0f} MB"
        if data.get("rss_baseline_mb") is not None:
            text += f", after the first minute {data['rss_baseline_mb']:.0f} MB"
        lines.append(text + (f"; {int(data['threads'])} threads" if data.get("threads") else ""))
        over = memory_over_time(data.get("rss_over_time") or [])
        if over:
            lines.append("  over time: " + over)
        if data.get("startup"):
            lines.append("")
            lines.append("Start-up (seconds after the process started, and the step's own share)")
            lines.append("  " + startup_line(data["startup"]))
    else:
        lines.append("  (not available on this system)")
    split = data.get("cpu_split")
    if split:
        age = data.get("process_seconds") or data.get("seconds", 0.0)
        total = sum(split.values()) or 0.0
        lines.append("")
        lines.append(f"Where the CPU went (since this run of Sluice started, {_duration(age)}; a percent of ONE core)")
        names = (("window", "window and engine timers (main thread)"), ("audio", "audio callback"),
                 ("other_threads", "all other threads"), ("ended_threads", "threads that have ended"),
                 ("helpers", "helper programs (pw-link)"))
        for key, text in names:
            share = split.get(key, 0.0)
            pct = f"{100.0 * share / age:6.2f}%" if age else "     -"
            part = f"{100.0 * share / total:3.0f}%" if total else "  -"
            lines.append(f"  {text:<40} {share:7.1f} s  {pct}  {part} of the total")
    groups = data.get("thread_groups")
    if groups:
        lines.append("")
        lines.append("Threads by name (a thread's CPU counts from when it started; names come from Python or from the library that made them)")
        for g in groups:
            lines.append(f"  {g['count']:>3} x {g['name']:<46} {g['cpu_seconds']:7.1f} s")
        if data.get("thread_groups_more"):
            lines.append(f"  ... and {data['thread_groups_more']} more groups")
    if "math_libraries" in data:
        libs = data["math_libraries"]
        lines.append("")
        lines.append(f"Maths libraries loaded (they start worker threads of their own; this computer has {data.get('processor_threads') or '?'} processor threads)")
        lines.append("  " + ("; ".join(libs) if libs else "none found") +
                     (f"\n  Their worker threads: OPENBLAS_NUM_THREADS={os.environ.get('OPENBLAS_NUM_THREADS', 'not set')} "
                      "(Sluice sets 1 unless you set it yourself)" if libs else ""))
    recent = data.get("pulse_recent")
    if recent:
        lines.append("")
        lines.append("Last calls to the audio server (newest last; 'closed' means the connection was found dead and the call was not made)")
        lines.append("  " + ", ".join(f"{name} {ago:g}s before this ({outcome})" for name, ago, outcome in recent))
    lines.append("")
    lines.append("Audio work (share of each block's time that Sluice's own processing used)")
    if data.get("audio_load_samples", 0):
        lines.append(f"  average {data['audio_load_average']:.1%}, worst block {data['audio_load_worst']:.1%}, "
                     f"dropouts {data.get('dropouts', 0)}")
        if data.get("audio_load_worst_at"):  # 0.11.7: when it was, so a one-off at start-up is told apart from one mid-session
            after = data.get("audio_load_worst_after", 0.0)
            when = time.strftime("%H:%M:%S", time.localtime(data["audio_load_worst_at"]))
            lines.append(f"  the worst block was at {when}, {after:g} s after Sluice started"
                         + (" (during start-up)" if after < 10 else ""))
        lines.append("  " + wait_line(data.get("audio_wait")))
    else:
        lines.append("  (not measured by this audio backend)")
    if "channels" in data:
        lines.append("")
        lines.append("What was switched on (counts only)")
        lines.append(f"  {data['channels']} channels, {data['mixes']} mixes, {data['mic_channels']} with a microphone; "
                     f"{data['effects_on']} effects on ({data['vst3_plugins']} VST3), {data['effects_bypassed']} bypassed")
        lines.append(f"  recording mix {'on' if data['recording_mix'] else 'off'}, live voice display "
                     f"{'open' if data['live_voice_display'] else 'closed'}")
        lines.append(f"  {data['sample_rate']} Hz, {data['buffer_frames']} frames; audio work in {data['dsp']}; client {data['audio_client']}")
        lines.append("  (the time each effect takes is not measured: that would put a clock on the audio thread)")
    lines.append("")
    notes = flags(data)
    lines.append("Flags")
    lines.extend(f"  - {n}" for n in notes) if notes else lines.append("  none: nothing here looks wasteful")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------ the one running now
ACTIVE: Optional[Tracker] = None


def activate(tracker: Optional[Tracker]) -> None:
    global ACTIVE
    ACTIVE = tracker


def for_report() -> tuple:
    """(data, where it came from) for the bug report: this process if Sluice is running here, else the snapshot file of a running or
    finished Sluice."""
    if ACTIVE is not None:
        return ACTIVE.snapshot(), "This session (live)."
    try:
        data = json.loads(snapshot_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ""
    age = max(0.0, time.time() - float(data.get("taken", 0)))
    alive = False
    try:
        alive = logs._pid_alive(int(data.get("pid", 0))) and logs.running_path().exists()
    except (OSError, ValueError):
        pass
    where = f"The running Sluice, as of {_duration(age)} ago." if alive else f"The last Sluice session, which ended {_duration(age)} ago or earlier."
    return data, where
