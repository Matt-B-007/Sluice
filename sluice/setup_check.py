# SPDX-License-Identifier: GPL-3.0-or-later
"""What Sluice needs from the system, and what it can use if it is there (0.12.0).

One list, used by the Setup check in Settings, by ``sluice --diagnose`` (and so the bug report) and by install.sh. Each part says
what it is for, whether Sluice needs it, whether it is here (and why not), and the command that installs it on this distribution.
Nothing here installs anything: the person runs the command (Settings has a Copy button for it).
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import distro


@dataclass(frozen=True)
class Part:
    key: str
    name: str
    purpose: str  # what it is for, in a line
    required: bool
    needs: tuple = ()  # distro.PACKAGES keys for the install command
    check: Callable = None  # () -> (ok, reason); ok is None when it cannot be told from here (the reason says when it can)
    applies: Callable = None  # () -> bool: False when this desktop has no use for it (KDE parts elsewhere)
    command: Callable = None  # (result) -> str: a fix other than installing packages


@dataclass
class Result:
    part: Part
    ok: Optional[bool]
    reason: str
    command: str = ""
    applies: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def missing(self) -> bool:
        return self.applies and self.ok is False


# ----------------------------------------------------------------------------- the checks
def _pulse() -> tuple:
    from .diagnose import _pulse as check

    ok, detail = check()
    if ok:
        return ok, detail
    return ok, (
        detail.split(". Is pipewire-pulse running?")[0] + ". If it is installed, start it with: "
        "systemctl --user enable --now pipewire pipewire-pulse wireplumber"
    )


def _jack() -> tuple:
    from .diagnose import _jack as check

    ok, detail = check()
    return ok, detail if ok else detail.split(". Install pipewire-jack")[0]


def _pw_link() -> tuple:
    from .linker import PwLinker

    if PwLinker().available():
        return True, "pw-link works"
    return False, "not found, or PipeWire is not running"


def _kde() -> bool:
    from .desktop_place import kde

    return kde()


def _kde_wayland() -> bool:
    from .desktop_place import kde_wayland

    platform = ""
    try:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is not None:
            platform = QGuiApplication.platformName() or ""
    except Exception:  # no Qt here (sluice --diagnose): the environment decides, as in desktop_place
        pass
    return kde_wayland(platform=platform)


def _layer_shell() -> tuple:
    from .desktop_place import layer_shell

    shell = layer_shell()
    return (True, "the desktop widgets place themselves and stay on top") if shell.available else (False, shell.reason)


def _kconfig() -> tuple:
    found = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    return (True, f"{os.path.basename(found)} is installed") if found else (False, "not found")


def _rust() -> tuple:
    from . import spectral

    if os.environ.get("SLUICE_NO_RUST"):
        return True, "switched off (SLUICE_NO_RUST)"
    if spectral.RUST_VERSION:
        if spectral.rust_is_older():
            return False, (
                f"engine {spectral.RUST_VERSION} is older than this Sluice's {spectral.RUST_EXPECTED}: rebuild it under Updates"
            )
        return True, f"engine {spectral.RUST_VERSION} (numbered apart from Sluice)"
    if spectral.RUST_ERROR:
        return False, f"the engine could not be used: {spectral.RUST_ERROR}"
    if shutil.which("cargo"):
        return False, "Rust is installed but the engine is not built yet: build it under Updates"
    return False, "Rust is not installed, so the faster engine cannot be built (Sluice works the same, using more CPU)"


def _rust_command(result: Result) -> str:
    return "" if shutil.which("cargo") else distro.install_hint(["rust"])


def _pedalboard() -> tuple:
    try:
        import pedalboard

        return True, f"pedalboard {pedalboard.__version__}"
    except Exception as exc:
        return False, f"not installed ({type(exc).__name__})"


def _cryptography() -> tuple:
    from . import signing

    if signing.available():
        return True, "installed"
    return False, "not installed: updates cannot be checked, so none is installed"


def _pip() -> str:
    return f"{sys.executable} -m pip"


def _tray() -> tuple:
    try:
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon

        if QApplication.instance() is None:
            return None, "checked while Sluice is running"
        if QSystemTrayIcon.isSystemTrayAvailable():
            return True, "the desktop shows tray icons"
        return False, "this desktop shows no tray icons"
    except Exception as exc:
        return None, f"could not be checked ({type(exc).__name__})"


def _tray_command(result: Result) -> str:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if "GNOME" not in desktop:
        return ""
    install = distro.install_hint(["tray"])
    return f"{install} && gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com" if install.startswith("sudo") else ""


PARTS = (
    Part(
        "pulse",
        "PipeWire's PulseAudio service (pipewire-pulse)",
        "Finds your apps and devices and moves apps onto channels.",
        True,
        ("pipewire", "pulse", "session", "libpulse"),
        _pulse,
    ),
    Part(
        "jack",
        "PipeWire's JACK library (pipewire-jack)",
        "Carries the sound through Sluice's channels and mixes.",
        True,
        ("jack",),
        _jack,
    ),
    Part(
        "pwlink",
        "pw-link",
        "Connects Sluice to your microphones, speakers and headphones.",
        True,
        ("pipewire", "pwlink", "session"),
        _pw_link,
    ),
    Part(
        "layershell",
        "KDE layer-shell (LayerShellQt)",
        "Lets the desktop widgets place themselves and stay on top on Plasma (Wayland).",
        False,
        ("layershell",),
        _layer_shell,
        _kde_wayland,
    ),
    # (0.13.1: KDE's window-system library is no longer listed: it only blurred what was behind the Glass skin, retired)
    Part(
        "kconfig",
        "KDE kwriteconfig6 (KConfig)",
        "Adds the KWin rule that keeps the widgets on top when layer-shell is missing.",
        False,
        ("kconfig",),
        _kconfig,
        _kde,
    ),
    Part(
        "rust",
        "Rust (the faster audio engine)",
        "Builds Sluice's own audio engine: the same sound with less CPU, and the steeper high-pass filter.",
        False,
        ("rust",),
        _rust,
        None,
        _rust_command,
    ),
    Part(
        "pedalboard",
        "pedalboard",
        "Hosts VST3 plugins, and runs the built-in EQ and Gain when the Rust engine is missing.",
        False,
        (),
        _pedalboard,
        None,
        lambda result: f"{_pip()} install pedalboard",
    ),
    Part(  # 0.13.1-beta.3: listed (since beta.2 an update is refused without it)
        "cryptography",
        "cryptography",
        "Checks the signature on a new version before it is installed. Without it Sluice installs no updates.",
        False,
        (),
        _cryptography,
        None,
        lambda result: f"{_pip()} install cryptography",
    ),
    Part(
        "tray",
        "System tray",
        "Keeps Sluice running in the tray when its window is closed.",
        False,
        ("tray",),
        _tray,
        None,
        _tray_command,
    ),
)

BY_KEY = {part.key: part for part in PARTS}


def check(part: Part) -> Result:
    try:
        applies = part.applies() if part.applies is not None else True
    except Exception:  # when unsure, check it anyway: the check itself then says what went wrong
        applies = True
    if not applies:
        return Result(part, None, "not used on this desktop", applies=False)
    try:
        ok, reason = part.check()
    except Exception as exc:
        ok, reason = False, f"{type(exc).__name__}: {exc}"
    result = Result(part, ok, reason)
    if ok is False:
        try:
            command = part.command(result) if part.command is not None else ""
        except Exception:  # no special command: the package command below is offered instead
            command = ""
        if not command and part.needs and distro.family() is not None:
            command = distro.install_hint(list(part.needs))
        result.command = command
    return result


def check_all(keys: Optional[list] = None) -> list:
    return [check(part) for part in PARTS if keys is None or part.key in keys]


def summary(results: list) -> tuple:
    """(required parts missing, optional parts missing)"""
    return ([r for r in results if r.missing and r.part.required], [r for r in results if r.missing and not r.part.required])


def lines(results: list) -> list:
    """One text line per part, for --diagnose and the bug report."""
    out = []
    for r in results:
        mark = "OK  " if r.ok else ("--  " if not r.applies or r.ok is None else ("FAIL" if r.part.required else "MISS"))
        kind = "needed" if r.part.required else "optional"
        text = f"{mark} {r.part.name} ({kind}): {r.reason}"
        if r.missing and r.command:
            text += f". To install: {r.command}"
        out.append(text)
    return out


def main(argv: Optional[list] = None) -> int:
    """``python3 -m sluice.setup_check [optional|all]``: print the parts missing here (install.sh prints the optional ones)."""
    args = list(sys.argv[1:] if argv is None else argv)
    results = check_all()
    if args[:1] == ["optional"]:
        for r in summary(results)[1]:
            print(f"  - {r.part.name}: {r.part.purpose}" + (f"\n      {r.command}" if r.command else ""))
        return 0
    print("\n".join(lines(results)))
    return 1 if summary(results)[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
