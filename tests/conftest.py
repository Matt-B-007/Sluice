# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared test setup.

0.13.1: the tests are sealed off from the computer they run on. Before anything is imported, the whole run gets its own home,
settings, data, log, cache and runtime folders, the audio tools (pactl, pw-link, pw-top...) are replaced by stand-ins that
refuse to run, and the audio servers are pointed at addresses that do not exist: the same as GitHub's clean machine. A Sluice
open on the computer, its lock, its socket, its settings and its logs are invisible to the tests. And while the tests run, a
pretend "python -m sluice" is running too, so a test that only passes when no Sluice runs fails everywhere, not only on the
developer's computer (StowLock could not push 0.12.6 while Sluice was open: the uninstall tests saw it)."""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SEALED = Path(tempfile.mkdtemp(prefix="sluice-tests-"))
for _name, _sub in (
    ("HOME", "home"),
    ("XDG_CONFIG_HOME", "home/.config"),
    ("XDG_DATA_HOME", "home/.local/share"),
    ("XDG_STATE_HOME", "home/.local/state"),
    ("XDG_CACHE_HOME", "home/.cache"),
    ("XDG_RUNTIME_DIR", "run"),
):
    (SEALED / _sub).mkdir(parents=True, exist_ok=True)
    os.environ[_name] = str(SEALED / _sub)
os.chmod(SEALED / "run", 0o700)
_STUBS = SEALED / "bin"
_STUBS.mkdir()
AUDIO_TOOLS = (
    "pactl",
    "pw-link",
    "pw-top",
    "pw-metadata",
    "pw-dump",
    "pw-cli",
    "wpctl",
    "pipewire",
    "wireplumber",
    "pacmd",
    "jack_lsp",
)
for _tool in AUDIO_TOOLS:
    _stub = _STUBS / _tool
    _stub.write_text(
        f"#!/bin/sh\necho '{_tool}: blocked in the tests (they must not touch the real audio system)' >&2\nexit 127\n"
    )
    _stub.chmod(_stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
os.environ["PATH"] = f"{_STUBS}{os.pathsep}{os.environ.get('PATH', '')}"
os.environ["PULSE_SERVER"] = f"unix:{SEALED / 'run' / 'no-pulse-server'}"
os.environ["PIPEWIRE_REMOTE"] = str(SEALED / "run" / "no-pipewire")
os.environ["USER"] = os.environ["LOGNAME"] = "sluicetester"  # the same user name on every computer
os.environ.pop("DISPLAY", None)
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 0.13.1: the fonts too. Qt finds fonts through fontconfig, and every computer has different ones, so the same text measured
# 87 pixels on GitHub's machine and 75 on the developer's ("text cut off" on one only). The tests see the fonts Sluice ships
# (sluice/data/fonts) and nothing else, on every computer: a layout that only fits with someone's installed font fails here.
FONTS = Path(__file__).resolve().parent.parent / "sluice" / "data" / "fonts"
_CHOSEN_FONTCONFIG = os.environ.get("FONTCONFIG_FILE")  # set by whoever runs the tests (to try GitHub's fonts): kept
(SEALED / "fontconfig").mkdir()
(SEALED / "fontconfig" / "fonts.conf").write_text(
    '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n<fontconfig>\n'
    f"  <dir>{FONTS}</dir>\n  <cachedir>{SEALED / 'fontconfig' / 'cache'}</cachedir>\n"
    "  <alias><family>sans-serif</family><prefer><family>Inter</family></prefer></alias>\n"
    "  <alias><family>monospace</family><prefer><family>JetBrains Mono</family></prefer></alias>\n"
    "</fontconfig>\n"
)
os.environ["FONTCONFIG_FILE"] = _CHOSEN_FONTCONFIG or str(SEALED / "fontconfig" / "fonts.conf")
os.environ.pop("FONTCONFIG_PATH", None)
os.environ.pop("QT_FONT_DPI", None)  # the same text size everywhere too

import numpy as np  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def a_sluice_is_running():
    """A pretend "python -m sluice" for the whole run (it only sleeps), so tests cannot depend on no Sluice running."""
    package = SEALED / "pretend" / "sluice"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "__main__.py").write_text("import time\ntime.sleep(3600)\n")
    process = subprocess.Popen(
        [sys.executable, "-m", "sluice", "--pretend-for-tests"],
        cwd=package.parent,
        env={**os.environ, "PYTHONPATH": str(package.parent)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    yield process
    process.kill()
    process.wait(timeout=5)


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole run: Qt cannot safely create a second one after the first is gone."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from sluice import fonts

    fonts.install(app)  # 0.12.7: the same start-up step Sluice itself takes, before any window is made
    return app


@pytest.fixture
def clap_room():
    """A function ``clap_room(rt60, noise_db, seed=0)``: four seconds of microphone signal (2, n) with one clap in a
    simulated room whose echo dies away in ``rt60`` seconds, over room noise at ``noise_db`` dB."""
    sr = 48000

    def make(rt60, noise_db, seed=0):
        rng = np.random.default_rng(seed)
        n = int(sr * rt60 * 1.3)
        t = np.arange(n) / sr
        tail = rng.standard_normal(n) * 10 ** (-3 * t / rt60)
        tail[: int(0.004 * sr)] = 0
        tail *= 1.0 / np.sqrt(np.sum(tail**2))
        h = tail.copy()
        h[int(0.002 * sr)] += 1.0
        clap = np.zeros(sr * 4)
        clap[sr : sr + 30] = rng.standard_normal(30) * 0.8
        x = np.convolve(clap, h)[: clap.size]
        x = x / np.max(np.abs(x)) * 0.5
        hum = rng.standard_normal(x.size) * 10 ** (noise_db / 20)
        return np.stack([x + hum, x + hum]).astype(np.float32)

    return make


@pytest.fixture(autouse=True)
def _delete_closed_windows():
    """After each test, delete the main windows it shut down (0.11.6). ``shutdown()`` leaves the window to Qt, and outside an event
    loop Qt never deletes it, so every test's window (some 17 MB each) stayed in memory and the whole run outgrew 8 GB."""
    yield
    import sys

    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    window_type = getattr(sys.modules.get("sluice.ui_window"), "MainWindow", None)
    for widget in app.topLevelWidgets():
        if window_type is not None and isinstance(widget, window_type) and getattr(widget, "_closed", False):
            widget.hide()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    import gc

    gc.collect()
