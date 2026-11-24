# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup check (0.12.0): one list of what Sluice needs and can use, shown in Settings, by --diagnose and by install.sh."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from sluice import distro, setup_check  # noqa: E402
from sluice.setup_check import BY_KEY, PARTS, Part, Result  # noqa: E402

FAMILIES = ("arch", "debian", "fedora", "suse", "void")


def test_every_part_says_what_it_is_for_and_the_needed_ones_are_the_audio_ones():
    assert [p.key for p in PARTS if p.required] == ["pulse", "jack", "pwlink"]
    assert {"layershell", "kwindowsystem", "kconfig", "rust", "pedalboard", "tray"} <= {p.key for p in PARTS if not p.required}
    for part in PARTS:
        assert part.purpose.endswith(".") and part.check is not None


def test_every_package_a_part_needs_is_named_on_every_family():
    for part in PARTS:
        for need in part.needs:
            for fam in FAMILIES:
                assert need in distro.PACKAGES[fam], (part.key, need, fam)
                if part.required:
                    assert distro.PACKAGES[fam][need] or need == "pulse", (part.key, need, fam)


@pytest.mark.parametrize("fam,line", [
    ("arch", "sudo pacman -S --needed layer-shell-qt"),
    ("debian", "sudo apt install liblayershellqtinterface6"),
    ("fedora", "sudo dnf install layer-shell-qt"),
    ("suse", "sudo zypper install libLayerShellQtInterface6"),
])
def test_the_command_is_the_one_for_this_distribution(fam, line):
    ids = {"arch": "arch", "debian": "ubuntu", "fedora": "fedora", "suse": "opensuse-tumbleweed"}
    assert distro.install_hint(["layershell"], {"ID": ids[fam]}) == line


def fake(key="x", required=False, ok=False, reason="gone", applies=True, needs=("kconfig",), command=None, crash=False):
    def check():
        if crash:
            raise RuntimeError("kaput")
        return ok, reason
    return Part(key, "Thing", "Does a thing.", required, needs, check, (lambda: applies), command)


def test_a_missing_part_gets_its_install_command_and_a_present_one_none(monkeypatch):
    monkeypatch.setattr(distro, "family", lambda info=None: "fedora")
    missing = setup_check.check(fake())
    assert missing.missing and missing.command == "sudo dnf install kf6-kconfig"
    here = setup_check.check(fake(ok=True, reason="fine"))
    assert not here.missing and here.command == ""
    elsewhere = setup_check.check(fake(applies=False))
    assert not elsewhere.missing and not elsewhere.applies and elsewhere.reason == "not used on this desktop"
    special = setup_check.check(fake(command=lambda r: "pip install it"))
    assert special.command == "pip install it"


def test_a_crashing_check_is_a_missing_part_that_says_why():
    result = setup_check.check(fake(crash=True))
    assert result.missing and "kaput" in result.reason


def test_the_summary_and_the_text_lines_separate_needed_from_optional():
    results = [Result(fake("a", required=True), False, "no server", "sudo x"), Result(fake("b"), False, "absent", "sudo y"),
               Result(fake("c"), True, "fine"), Result(fake("d"), None, "not used on this desktop", applies=False)]
    needed, optional = setup_check.summary(results)
    assert [r.part.key for r in needed] == ["a"] and [r.part.key for r in optional] == ["b"]
    lines = setup_check.lines(results)
    assert lines[0].startswith("FAIL") and "(needed)" in lines[0] and lines[0].endswith("To install: sudo x")
    assert lines[1].startswith("MISS") and lines[2].startswith("OK") and lines[3].startswith("--")


def test_diagnose_lists_the_same_parts_and_a_missing_optional_part_is_not_a_failure(monkeypatch):
    from sluice import diagnose
    monkeypatch.setattr(setup_check, "PARTS", (fake("opt"), fake("need", required=True, ok=True, reason="here")))
    results = {name: (ok, detail) for name, ok, detail in diagnose.run_checks()}
    assert results["Thing"][0] is True  # (the last of the two "Thing"s: the needed one, present)
    text, _ok = diagnose.report()
    assert "MISS Thing: optional, missing: gone" in text


def test_install_sh_prints_the_optional_parts(capsys, monkeypatch):
    monkeypatch.setattr(setup_check, "PARTS", (fake("opt", reason="absent"), fake("ok", ok=True)))
    monkeypatch.setattr(distro, "family", lambda info=None: "arch")
    assert setup_check.main(["optional"]) == 0
    out = capsys.readouterr().out
    assert "Thing: Does a thing." in out and "sudo pacman -S --needed kconfig" in out
    install = open(os.path.join(os.path.dirname(__file__), "..", "install.sh")).read()
    assert "sluice.setup_check optional" in install


def test_the_rust_part_says_how_to_get_the_faster_engine(monkeypatch):
    from sluice import spectral
    monkeypatch.delenv("SLUICE_NO_RUST", raising=False)
    monkeypatch.setattr(spectral, "RUST_VERSION", "0.9.6")
    assert setup_check.check(BY_KEY["rust"]).missing and "rebuild" in setup_check.check(BY_KEY["rust"]).reason
    monkeypatch.setattr(spectral, "RUST_VERSION", spectral.RUST_EXPECTED)
    assert setup_check.check(BY_KEY["rust"]).ok


# ----------------------------------------------------------------------------- the Settings section
def window(qapp, tmp_path):
    from sluice.audio_io import NullIO
    from sluice.backend import MockSystem
    from sluice.engine import Engine
    from sluice.linker import NullLinker
    from sluice.model import Mixer
    from sluice.ui import MainWindow
    engine = Engine(Mixer.demo(), MockSystem(), NullIO(realtime=False), NullLinker())
    engine.start()
    win = MainWindow(engine, tmp_path / "config.json")
    win.show()
    qapp.processEvents()
    return win


def test_settings_shows_each_part_with_its_state_and_a_copy_button_for_the_command(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(setup_check, "PARTS", (
        fake("need", required=True, reason="no server", needs=("jack",)), fake("opt", ok=True, reason="fine"),
        fake("kde", applies=False)))
    monkeypatch.setattr(distro, "family", lambda info=None: "debian")
    win = window(qapp, tmp_path)
    try:
        win.open_settings("Setup check")
        qapp.processEvents()
        settings = win.settings_window
        assert settings.setup_results  # checked as the section opened
        assert "needs 1 more part" in settings.setup_summary.text()
        command, copy = settings.setup_commands["need"]
        assert command.text() == "sudo apt install pipewire-jack" and list(settings.setup_commands) == ["need"]
        copy.click()
        from PySide6.QtGui import QGuiApplication
        assert QGuiApplication.clipboard().text() == "sudo apt install pipewire-jack" and copy.text() == "Copied"
        states = {label.objectName() for label in settings.pages.currentWidget().findChildren(type(command))}
        assert {"setupneeded", "setupok", "setupidle"} <= states
        monkeypatch.setattr(setup_check, "PARTS", (fake("need", required=True, ok=True, reason="here"),))
        settings.setup_again.click()
        qapp.processEvents()
        assert settings.setup_summary.text() == "Everything is here." and settings.setup_commands == {}
    finally:
        win.shutdown()


def test_an_optional_part_is_mentioned_once_when_it_would_be_used(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(setup_check, "BY_KEY", {"kwindowsystem": fake("kwindowsystem", reason="not installed")})
    win = window(qapp, tmp_path)
    try:
        assert win.hint_missing_part("kwindowsystem")
        assert "Setup check" in win.status_label.text()
        assert not win.hint_missing_part("kwindowsystem")  # only once
        assert "setup-kwindowsystem" in win.engine.mixer.hints_seen
    finally:
        win.shutdown()
