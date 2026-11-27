# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt interface: the one place the rest of Sluice imports the window and its parts from.

The code lives in five modules (0.11.5 split the old 3,800-line file):

- ``ui_base``: sizes, names, small helpers and small widgets
- ``ui_meters``: the level meter, the fader, the source picture and the Nexus ring
- ``ui_mix``: the Listen, Broadcast and Recording cards
- ``ui_channel``: the channel cards and their parts
- ``ui_window``: the main window

Every name in them is reachable here as ``ui.NAME``, as it always was."""

from __future__ import annotations

from . import ui_base, ui_channel, ui_meters, ui_mix, ui_window

for _module in (ui_base, ui_meters, ui_mix, ui_channel, ui_window):
    globals().update({name: value for name, value in vars(_module).items() if not name.startswith("__")})
del _module
__version__ = ui_window.__version__  # ui.__version__, as before

MainWindow = ui_window.MainWindow  # named here as well, so tools that read the source can find it
