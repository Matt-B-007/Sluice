# SPDX-License-Identifier: GPL-3.0-or-later
import os

import pytest

from sluice import distro, jackfix

RELEASES = {
    "cachyos": {"ID": "cachyos", "ID_LIKE": "arch"},
    "arch": {"ID": "arch"},
    "manjaro": {"ID": "manjaro", "ID_LIKE": "arch"},
    "ubuntu": {"ID": "ubuntu", "ID_LIKE": "debian"},
    "mint": {"ID": "linuxmint", "ID_LIKE": "ubuntu debian"},
    "pop": {"ID": "pop", "ID_LIKE": "ubuntu debian"},
    "debian": {"ID": "debian"},
    "fedora": {"ID": "fedora"},
    "nobara": {"ID": "nobara", "ID_LIKE": "rhel centos fedora"},
    "tumbleweed": {"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"},
    "leap": {"ID": "opensuse-leap", "ID_LIKE": "suse opensuse"},
    "void": {"ID": "void"},
}


@pytest.mark.parametrize("name,expected", [
    ("cachyos", "arch"), ("arch", "arch"), ("manjaro", "arch"), ("ubuntu", "debian"), ("mint", "debian"), ("pop", "debian"),
    ("debian", "debian"), ("fedora", "fedora"), ("nobara", "fedora"), ("tumbleweed", "suse"), ("leap", "suse"), ("void", "void"),
])
def test_families_are_recognised(name, expected):
    assert distro.family(RELEASES[name]) == expected


def test_unknown_systems_get_no_family_and_a_plain_hint():
    for info in ({"ID": "alpine"}, {"ID": "nixos"}, {"ID": "gentoo"}, {}):
        assert distro.family(info) is None
        assert distro.install_hint(["pipewire"], info) == "Install the equivalent packages for your distribution (see the README)."


def test_install_commands_use_each_distributions_own_names():
    assert distro.install_hint(["jack"], RELEASES["cachyos"]) == "sudo pacman -S --needed pipewire-jack"
    assert distro.install_hint(["jack", "pwlink"], RELEASES["ubuntu"]) == "sudo apt install pipewire-jack pipewire-bin"
    assert distro.install_hint(["jack"], RELEASES["fedora"]) == "sudo dnf install pipewire-jack-audio-connection-kit"
    assert distro.install_hint(["jack"], RELEASES["tumbleweed"]) == "sudo zypper install pipewire-libjack-0_3"
    assert distro.install_hint(["pwlink"], RELEASES["fedora"]) == "sudo dnf install pipewire-utils"
    assert distro.packages_for(["xcb", "venv", "gl"], RELEASES["ubuntu"])[:2] == ["libxcb-cursor0", "python3-venv"]
    assert distro.packages_for(["pipewire", "pipewire"], RELEASES["arch"]) == ["pipewire"]  # no duplicates


def test_every_family_has_a_name_for_every_need_and_an_installer():
    needs = set(distro.PACKAGES["arch"])
    for fam in distro.PACKAGES:
        assert set(distro.PACKAGES[fam]) == needs
        assert fam in distro.INSTALLERS and fam in distro.FAMILY_NAMES


def test_os_release_is_parsed(tmp_path):
    path = tmp_path / "os-release"
    path.write_text('# comment\nNAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\nVERSION_ID=\'22\'\n')
    info = distro.read_os_release(str(path))
    assert info["ID"] == "linuxmint" and info["ID_LIKE"] == "ubuntu debian" and info["VERSION_ID"] == "22"
    assert distro.read_os_release(str(tmp_path / "missing")) == {}


# ------------------------------------------------------------------ the JACK library fix
def make_lib_dir(root, *parts, lib="libjack.so.0"):
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True)
    (folder / lib).write_bytes(b"")
    return str(folder)


def test_pipewire_jack_folders_are_found_in_each_layout(tmp_path):
    deb = make_lib_dir(tmp_path, "usr", "lib", "x86_64-linux-gnu", "pipewire-0.3", "jack")
    fed = make_lib_dir(tmp_path, "usr", "lib64", "pipewire-0.3", "jack", lib="libjack.so.0.3.1")
    make_lib_dir(tmp_path, "usr", "lib", "other", "pipewire-0.3", "jack", lib="libnotjack.so")  # not a jack library
    patterns = (f"{tmp_path}/usr/lib/*/pipewire-0.3/jack", f"{tmp_path}/usr/lib64/pipewire-0.3/jack")
    assert jackfix.pipewire_jack_dirs(patterns) == [deb, fed]
    assert jackfix.pipewire_jack_dirs((f"{tmp_path}/nothing/*",)) == []


def test_retry_environment_puts_pipewires_library_first_and_only_once():
    env = jackfix.environment_for_retry({"LD_LIBRARY_PATH": "/a:/b", "HOME": "/h"}, ["/pw/jack"])
    assert env["LD_LIBRARY_PATH"] == "/pw/jack:/a:/b" and env[jackfix.MARKER] == "1" and env["HOME"] == "/h"
    assert jackfix.environment_for_retry({}, ["/pw/jack"])["LD_LIBRARY_PATH"] == "/pw/jack"
    assert jackfix.environment_for_retry(env, ["/pw/jack"]) is None  # already tried: never loops
    assert jackfix.environment_for_retry({"LD_LIBRARY_PATH": "/pw/jack"}, ["/pw/jack"]) is None  # already in the path
    assert jackfix.environment_for_retry({}, []) is None  # nothing to add


def test_retry_starts_sluice_again_with_the_new_environment(monkeypatch, tmp_path):
    make_lib_dir(tmp_path, "pw", "jack")
    monkeypatch.setattr(jackfix, "PATTERNS", (f"{tmp_path}/pw/jack",))
    monkeypatch.delenv(jackfix.MARKER, raising=False)
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    started = []
    monkeypatch.setattr(os, "execve", lambda path, args, env: started.append((path, args, env)))
    jackfix.retry_with_pipewire_jack(["--debug"])
    path, args, env = started[0]
    assert args[1:] == ["-m", "sluice", "--debug"] and env["LD_LIBRARY_PATH"] == f"{tmp_path}/pw/jack"

    started.clear()
    monkeypatch.setenv(jackfix.MARKER, "1")
    assert jackfix.retry_with_pipewire_jack([]) is False and not started


def test_cli_family_and_command(tmp_path, capsys):
    from sluice import distro

    f = tmp_path / "os-release"
    f.write_text('ID=ubuntu\nID_LIKE="debian"\n')
    assert distro.main(["--os-release", str(f), "family"]) == 0
    assert capsys.readouterr().out.strip() == "debian"
    assert distro.main(["--os-release", str(f), "command"]) == 0
    assert "apt install" in capsys.readouterr().out
    assert distro.main(["bogus"]) == 2
