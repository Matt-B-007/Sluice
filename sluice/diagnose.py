# SPDX-License-Identifier: GPL-3.0-or-later
"""``sluice --diagnose``: check every moving part and say what is missing."""
from __future__ import annotations

import os
import sys


def _pedalboard() -> tuple:
    try:
        import pedalboard

        return True, f"pedalboard {pedalboard.__version__}"
    except Exception as exc:
        return False, f"{exc}. Install with: pip install pedalboard"


def _pulse() -> tuple:
    try:
        import pulsectl

        with pulsectl.Pulse("sluice-diagnose") as pulse:
            info = pulse.server_info()
            return True, f"{info.server_name} {info.server_version}, default output: {info.default_sink_name}"
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
        import pulsectl

        with pulsectl.Pulse("sluice-diagnose") as pulse:
            found = inputs_left_unused(pulse.card_list())
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


def _pw_link() -> tuple:
    from .linker import PwLinker

    if PwLinker().available():
        return True, "pw-link works"
    from .distro import install_hint

    return False, f"pw-link not found or PipeWire not running. To install: {install_hint(['pipewire', 'pwlink', 'session'])}"


def _vst3() -> tuple:
    from .effects import scan_vst3, vst3_search_paths
    from .model import Mixer

    folders = Mixer.load().vst3_folders  # the folders added in the app count too
    found = scan_vst3(vst3_search_paths(folders))
    searched = ", ".join(str(p) for p in vst3_search_paths(folders))
    if found:
        return True, f"{len(found)} plugin(s): " + ", ".join(name for name, _ in found[:8])
    return True, f"none found (searched {searched}); you can still browse to a .vst3 folder"


def _launcher() -> tuple:
    from . import desktop

    if not desktop.is_installed():
        return True, "not in the applications menu (add it with: sluice --install-desktop)"
    problem = desktop.launcher_problem()
    if problem:
        return False, problem
    return True, "in the applications menu; if clicking it does nothing, read ~/.local/state/sluice/launcher.log"


def run_checks() -> list:
    """[(name, ok, detail)]"""
    checks = [
        ("Python", lambda: (sys.version_info >= (3, 10), sys.version.split()[0])),
        ("pedalboard (effects + VST3)", _pedalboard),
        ("PulseAudio protocol (pipewire-pulse)", _pulse),
        ("JACK client (pipewire-jack)", _jack),
        ("pw-link", _pw_link),
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
    return results


def report() -> tuple:
    """(text, all ok)"""
    results = run_checks()
    lines = [f"{'OK  ' if ok else 'FAIL'} {name}: {detail}" for name, ok, detail in results]
    return "\n".join(lines), all(ok for _, ok, _ in results)
