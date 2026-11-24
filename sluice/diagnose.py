# SPDX-License-Identifier: GPL-3.0-or-later
"""``sluice --diagnose``: check every moving part and say what is missing."""
from __future__ import annotations

import os
import sys


def _pulse() -> tuple:
    try:
        from .backend import connect_pulse

        pulse = connect_pulse("sluice-diagnose")  # behind the same liveness check as the program's own connection
        try:
            info = pulse.server_info()
            return True, f"{info.server_name} {info.server_version}, default output: {info.default_sink_name}"
        finally:
            pulse.close()
    except Exception as exc:
        from .distro import install_hint

        return False, (f"{type(exc).__name__}: {exc}. Is pipewire-pulse running? "
                       f"(systemctl --user enable --now pipewire pipewire-pulse wireplumber; "
                       f"to install: {install_hint(['pipewire', 'pulse', 'session', 'libpulse'])})")


def inputs_left_unused(cards) -> list:
    """[(card name, active profile, better profile)] for cards that only play sound although a profile that also
    records is available. Pure function over pulsectl-like objects, so it can be tested without a sound server."""
    found = []
    for card in cards:
        active = getattr(card, "profile_active", None)
        if active is None or active.name == "off" or active.n_sources > 0:
            continue
        better = [p for p in card.profile_list
                  if p.n_sources > 0 and p.n_sinks >= active.n_sinks and getattr(p, "available", 1) != 0 and p.name != "off"]
        if better:
            best = max(better, key=lambda p: (p.n_sinks, p.priority))
            found.append((card.name, active.name, best.name))
    return found


def _cards() -> tuple:
    try:
        from .backend import connect_pulse

        pulse = connect_pulse("sluice-diagnose")
        try:
            found = inputs_left_unused(pulse.card_list())
        finally:
            pulse.close()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if not found:
        return True, "no sound card has an unused input"
    lines = [f"{name} is set to '{active}', which has no microphone input, but '{best}' is available. "
             f"To turn the input on: pactl set-card-profile {name} {best}   (undo: pactl set-card-profile {name} {active})"
             for name, active, best in found]
    return True, "\n     ".join(lines)


def _jack() -> tuple:
    try:
        os.environ.setdefault("PIPEWIRE_PROPS", "{ node.autoconnect=false }")
        import jack

        client = jack.Client("sluice-diagnose", no_start_server=True)
        detail = f"{client.samplerate} Hz, {client.blocksize} frames per block"
        client.close()
        return True, detail
    except Exception as exc:
        from .distro import install_hint
        from .jackfix import pipewire_jack_dirs

        extra = ("" if not pipewire_jack_dirs() else " PipeWire's JACK library is installed; Sluice retries with it "
                 "automatically when it starts (or run it as: pw-jack sluice).")
        return False, (f"{type(exc).__name__}: {exc}. Install pipewire-jack ({install_hint(['jack'])}) and "
                       f"'pip install JACK-Client'.{extra}")


def _vst3() -> tuple:
    from .effects import scan_vst3, vst3_search_paths
    from .model import Mixer

    folders = Mixer.load().vst3_folders  # the folders added in the app count too
    found = scan_vst3(vst3_search_paths(folders))
    searched = ", ".join(str(p) for p in vst3_search_paths(folders))
    if found:
        return True, f"{len(found)} plugin(s): " + ", ".join(name for name, _ in found[:8])
    return True, f"none found (searched {searched}); you can still browse to a .vst3 folder"


def _engine() -> tuple:
    from . import dsp, room, spectral

    parts = {"reducers": spectral.BACKEND, "mixing": dsp.MIX_BACKEND, "room measuring": room.ROOM_BACKEND}
    try:
        from .effects import native_backend

        parts["effects"] = native_backend()
    except Exception as exc:
        parts["effects"] = f"unknown ({type(exc).__name__}: {exc})"  # say so in the check itself
    try:
        import sluice_dsp

        off = os.environ.get("SLUICE_NO_RUST") or os.environ.get("SLUICE_NO_RUST_IO")
        parts["audio client"] = "rust" if hasattr(sluice_dsp, "JackEngine") and not off else "python"
    except Exception as exc:
        parts["audio client"] = f"python ({type(exc).__name__}: {exc})"  # the Rust module is missing or broken: say why
    # 0.12.0: which parts run where, only. Whether the Rust engine is here, its version and whether it is older than this Sluice's
    # are said once: by the setup check's Rust line (and, in the bug report, its "Audio engine" line at the top).
    return True, ", ".join(f"{k}: {v}" for k, v in parts.items())


def _launcher() -> tuple:
    from . import launcher

    if not launcher.is_installed():
        return True, "not in the applications menu (add it with: sluice --install-desktop)"
    problem = launcher.launcher_problem()
    if problem:
        return False, problem
    return True, "in the applications menu; if clicking it does nothing, read ~/.local/state/sluice/launcher.log"


def run_checks() -> list:
    """[(name, ok, detail)]: Sluice's own checks, then the parts of the setup check (setup_check.py, the same list as Settings).
    A missing optional part is not a failure: its detail starts with "optional, missing"."""
    checks = [
        ("Python", lambda: (sys.version_info >= (3, 10), sys.version.split()[0])),
        ("Audio parts (Rust or Python)", _engine),
        ("Sound card inputs", _cards),
        ("VST3 plugins", _vst3),
        ("Applications-menu launcher", _launcher),
    ]
    results = []
    for name, check in checks:
        try:
            ok, detail = check()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((name, ok, detail))
    from . import setup_check

    for r in setup_check.check_all():
        kind = "needed" if r.part.required else "optional"
        if not r.applies or r.ok is None:
            results.append((r.part.name, True, f"{kind}, {r.reason}"))
        elif r.ok:
            results.append((r.part.name, True, r.reason))
        else:
            detail = f"{r.reason}" + (f". To install: {r.command}" if r.command else "")
            results.append((r.part.name, not r.part.required, detail if r.part.required else f"optional, missing: {detail}"))
    return results


def report(engine_line: bool = True) -> tuple:
    """(text, all ok). The bug report says the engine once, in its own summary line, so it leaves out the setup check's Rust line
    (``engine_line=False``)."""
    results = [r for r in run_checks() if engine_line or r[0] != "Rust (the faster audio engine)"]
    def mark(ok, detail):
        if not ok:
            return "FAIL"
        if detail.startswith("optional, missing"):
            return "MISS"
        return "--  " if detail.startswith(("optional, not used", "optional, checked", "needed, checked")) else "OK  "

    lines = [f"{mark(ok, detail)} {name}: {detail}" for name, ok, detail in results]
    return "\n".join(lines), all(ok for _, ok, _ in results)
