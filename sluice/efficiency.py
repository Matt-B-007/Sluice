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
import os
import threading
import time
from pathlib import Path
from typing import Optional

from . import logs

SNAPSHOT_NAME = "efficiency.json"
SNAPSHOT_SECONDS = 60.0
BASELINE_SECONDS = 60.0  # the memory use at this point is what later growth is compared with
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
        self.state = "open"
        self.seconds = {s: 0.0 for s in STATES}
        self.cpu = {s: 0.0 for s in STATES}
        self.ticks = {s: 0 for s in STATES}  # meter updates
        self.rss_baseline: Optional[float] = None
        self.last_written = 0.0
        self.engine = None

    # ------------------------------------------------------------ collecting
    def set_state(self, state: str, now: Optional[float] = None) -> None:
        """The window was shown, hidden or minimized: time and CPU up to now belong to the old state."""
        if state not in STATES or state == self.state:
            return
        self.sample(now)
        self.state = state

    def sample(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        cpu = _cpu_seconds()
        self.seconds[self.state] += max(0.0, now - self.last)
        self.cpu[self.state] += max(0.0, cpu - self.cpu_last)
        self.last, self.cpu_last = now, cpu
        if self.rss_baseline is None and now - self.started >= BASELINE_SECONDS:
            self.rss_baseline = _status("VmRSS")

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
            "by_state": {s: {"seconds": round(self.seconds[s], 1), "cpu_seconds": round(self.cpu[s], 2), "meter_updates": self.ticks[s]}
                         for s in STATES},
            "cpu_seconds": round(sum(self.cpu.values()), 2),
            "rss_mb": _mb(_status("VmRSS")),
            "rss_peak_mb": _mb(_status("VmHWM")),
            "rss_baseline_mb": _mb(self.rss_baseline),
            "threads": _status("Threads"),
            "helper_cpu_seconds": round(max(0.0, _helper_cpu_seconds() - self.helper_cpu_start), 3),
        }
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
        "audio_load_samples": blocks,
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
        "dsp": f"{dsp.MIX_BACKEND}" + (f" (sluice_dsp {spectral.RUST_VERSION})" if spectral.RUST_VERSION else ""),
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
        if cpu.get(state) is not None and seconds(state) >= MIN_SECONDS and cpu[state] > FLAG_CPU_HIDDEN:
            notes.append(f"{cpu[state]:.1f}% of a core while the window was hidden ({state}): it should be close to idle.")
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
        lines.append(f"  {names[state]:<20} {_duration(values['seconds']):>8}   "
                     f"{'-' if value is None else format(value, '.2f') + '%':>8}   {rate:.1f} meter updates/s")
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
    else:
        lines.append("  (not available on this system)")
    lines.append("")
    lines.append("Audio work (share of each block's time that Sluice's own processing used)")
    if data.get("audio_load_samples", 0):
        lines.append(f"  average {data['audio_load_average']:.1%}, worst block {data['audio_load_worst']:.1%}, "
                     f"dropouts {data.get('dropouts', 0)}")
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
