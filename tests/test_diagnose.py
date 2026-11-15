# SPDX-License-Identifier: GPL-3.0-or-later
from sluice import diagnose
from sluice.__main__ import main


def test_report_lists_every_check_and_never_raises():
    results = diagnose.run_checks()
    names = [name for name, _, _ in results]
    assert "pedalboard (effects + VST3)" in names
    assert "pw-link" in names
    assert all(isinstance(ok, bool) and isinstance(detail, str) and detail for _, ok, detail in results)
    text, ok = diagnose.report()
    assert text.count("\n") == len(results) - 1
    assert ok == all(ok_ for _, ok_, _ in results)


def test_a_crashing_check_is_reported_as_a_failure(monkeypatch):
    def boom():
        raise RuntimeError("kaput")

    monkeypatch.setattr(diagnose, "_pulse", boom)
    results = {name: (ok, detail) for name, ok, detail in diagnose.run_checks()}
    ok, detail = results["PulseAudio protocol (pipewire-pulse)"]
    assert not ok and "kaput" in detail


def test_diagnose_command_prints_and_returns_a_status_code(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    code = main(["--diagnose"])
    out = capsys.readouterr().out
    assert "pedalboard" in out
    assert code in (0, 1)


def _card(name, active, profiles):
    from types import SimpleNamespace as NS

    make = lambda n, sinks, sources, prio=1, avail=1: NS(name=n, n_sinks=sinks, n_sources=sources, priority=prio, available=avail)  # noqa: E731
    table = {p[0]: make(*p) for p in profiles}
    return NS(name=name, profile_active=table[active], profile_list=list(table.values()))


def test_a_card_stuck_on_an_output_only_profile_is_found():
    from sluice.diagnose import inputs_left_unused

    elgato = _card("alsa_card.elgato", "output:multichannel-output", [
        ("output:multichannel-output+input:multichannel-input", 1, 1, 101),
        ("output:multichannel-output", 1, 0, 100),
        ("input:multichannel-input", 0, 1, 1),
        ("off", 0, 0, 0)])
    fine = _card("alsa_card.motherboard", "duplex", [("duplex", 1, 1), ("off", 0, 0, 0)])
    switched_off = _card("alsa_card.unused", "off", [("off", 0, 0, 0), ("duplex", 1, 1)])
    unplugged = _card("alsa_card.hdmi", "output", [("output", 1, 0), ("duplex", 1, 1, 1, 0)])
    assert inputs_left_unused([elgato, fine, switched_off, unplugged]) == [
        ("alsa_card.elgato", "output:multichannel-output", "output:multichannel-output+input:multichannel-input")]


def test_the_card_check_is_part_of_the_report():
    from sluice.diagnose import run_checks

    assert "Sound card inputs" in [name for name, _, _ in run_checks()]
