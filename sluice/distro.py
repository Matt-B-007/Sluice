# SPDX-License-Identifier: GPL-3.0-or-later
"""Which Linux family this is, and what to install on it. Only used to print helpful instructions."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# What Sluice needs from the system, by purpose. The names differ between distributions.
PACKAGES = {
    "arch": {
        "pipewire": "pipewire", "pulse": "pipewire-pulse", "session": "wireplumber", "jack": "pipewire-jack",
        "pwlink": "pipewire", "pactl": "libpulse", "libpulse": "libpulse", "xcb": "xcb-util-cursor",
        "python": "python", "gl": "", "venv": "",
    },
    "debian": {
        "pipewire": "pipewire", "pulse": "pipewire-pulse", "session": "wireplumber", "jack": "pipewire-jack",
        "pwlink": "pipewire-bin", "pactl": "pulseaudio-utils", "libpulse": "libpulse0", "xcb": "libxcb-cursor0",
        "python": "python3 python3-pip", "gl": "libgl1 libegl1 libxkbcommon-x11-0 libfontconfig1", "venv": "python3-venv",
    },
    "fedora": {
        "pipewire": "pipewire", "pulse": "pipewire-pulseaudio", "session": "wireplumber",
        "jack": "pipewire-jack-audio-connection-kit", "pwlink": "pipewire-utils", "pactl": "pulseaudio-utils",
        "libpulse": "pulseaudio-libs", "xcb": "xcb-util-cursor", "python": "python3 python3-pip",
        "gl": "mesa-libGL mesa-libEGL libxkbcommon-x11 fontconfig", "venv": "",
    },
    "suse": {
        "pipewire": "pipewire", "pulse": "pipewire-pulseaudio", "session": "wireplumber",
        "jack": "pipewire-libjack-0_3", "pwlink": "pipewire-tools", "pactl": "pulseaudio-utils",
        "libpulse": "libpulse0", "xcb": "libxcb-cursor0", "python": "python3 python3-pip",
        "gl": "libGL1 libEGL1 libxkbcommon-x11-0 fontconfig", "venv": "",
    },
    "void": {
        "pipewire": "pipewire", "pulse": "", "session": "wireplumber", "jack": "libjack-pipewire",
        "pwlink": "pipewire", "pactl": "pulseaudio-utils", "libpulse": "libpulseaudio", "xcb": "xcb-util-cursor",
        "python": "python3 python3-pip", "gl": "libGL libEGL libxkbcommon-x11 fontconfig", "venv": "",
    },
}

INSTALLERS = {
    "arch": "sudo pacman -S --needed {packages}",
    "debian": "sudo apt install {packages}",
    "fedora": "sudo dnf install {packages}",
    "suse": "sudo zypper install {packages}",
    "void": "sudo xbps-install -S {packages}",
}

FAMILY_NAMES = {"arch": "Arch / CachyOS / Manjaro / EndeavourOS", "debian": "Debian / Ubuntu / Linux Mint / Pop!_OS",
                "fedora": "Fedora / Nobara", "suse": "openSUSE", "void": "Void Linux"}

_FAMILY_IDS = {
    "arch": {"arch", "cachyos", "manjaro", "endeavouros", "garuda", "artix", "arcolinux"},
    "debian": {"debian", "ubuntu", "linuxmint", "pop", "zorin", "elementary", "kali", "raspbian", "neon", "mx", "devuan"},
    "fedora": {"fedora", "nobara", "rhel", "centos", "rocky", "almalinux", "bazzite", "ultramarine"},
    "suse": {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "suse", "sles"},
    "void": {"void"},
}


def read_os_release(path: str = "/etc/os-release") -> dict:
    values: dict = {}
    try:
        for line in Path(path).read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def family(os_release: Optional[dict] = None) -> Optional[str]:
    """'arch', 'debian', 'fedora', 'suse' or 'void'; None when this is something else (Gentoo, NixOS, Alpine ...)."""
    info = read_os_release() if os_release is None else os_release
    ids = [info.get("ID", "").lower(), *info.get("ID_LIKE", "").lower().split()]
    for ident in ids:
        for name, members in _FAMILY_IDS.items():
            if ident in members or ident.startswith(f"{name}-"):
                return name
    return None


def packages_for(purposes: list, os_release: Optional[dict] = None) -> list:
    fam = family(os_release)
    if fam is None:
        return []
    names: list = []
    for purpose in purposes:
        for name in PACKAGES[fam].get(purpose, "").split():
            if name not in names:
                names.append(name)
    return names


def install_hint(purposes: list, os_release: Optional[dict] = None) -> str:
    """The command that installs the named things, or a plain sentence when the family is not known."""
    fam = family(os_release)
    names = packages_for(purposes, os_release)
    if fam is None or not names:
        return "Install the equivalent packages for your distribution (see the README)."
    return INSTALLERS[fam].format(packages=" ".join(names))


ALL_NEEDS = ["python", "venv", "pipewire", "pulse", "session", "jack", "pwlink", "pactl", "libpulse", "xcb", "gl"]


def main(argv: Optional[list] = None) -> int:
    """``python3 -m sluice.distro [--os-release FILE] family|command|packages [needs...]``: used by install.sh."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    info = None
    if args[:1] == ["--os-release"] and len(args) >= 2:
        info = read_os_release(args[1])
        args = args[2:]
    what, needs = (args[0] if args else "family"), (args[1:] or ALL_NEEDS)
    if what == "family":
        print(family(info) or "unknown")
    elif what == "name":
        print(FAMILY_NAMES.get(family(info) or "", "an unrecognised distribution"))
    elif what == "packages":
        print(" ".join(packages_for(needs, info)))
    elif what == "command":
        print(install_hint(needs, info))
    else:
        print("usage: python3 -m sluice.distro [--os-release FILE] family|name|packages|command [needs...]", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
