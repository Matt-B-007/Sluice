"""How the window arranges itself at the size it has: the layout shown, where the Listen and Broadcast cards sit, and how much of
the top bar is shown. Pure functions of the window size, so they are easy to test; the window only follows what they say."""
from __future__ import annotations

from typing import NamedTuple, Optional

HYSTERESIS = 24          # pixels: a plan is kept while the width stays this close to the edge it changed at (no flicker while dragging)
BOTTOM_DOCK_HEIGHT = 720  # the Listen and Broadcast bar needs this much height beside the channels
MINI_HEIGHT = 460        # shorter than this, only the compact list fits
STEPS = ("roomy", "standard", "compact", "mini")


class Plan(NamedTuple):
    mode: str            # columns, rows, free or mini (the compact list)
    dock: str            # right: Listen and Broadcast beside the channels; bottom: in a bar under them (columns and rows only)
    step: str            # roomy, standard, compact or mini: how much of the top bar and spacing is shown


def _base(width: int, height: int, layout: str, look: str) -> Plan:
    original = look == "original"
    mode = layout if layout in ("columns", "rows", "free") else "columns"
    if mode == "free" and look not in ("nexus", "tile"):
        mode = "columns"  # Free belongs to the Nexus and Tile looks; the saved choice is kept
    step = "roomy" if width >= 1600 else "standard" if width >= 1180 else "compact" if width >= 820 else "mini"
    narrowest = {"rows": 980, "free": 640}.get(mode, 620 if original else 760)
    if width < narrowest or height < MINI_HEIGHT:
        return Plan("mini", "right", "mini")
    dock = "right"
    if mode == "columns" and not original and width < 1180:
        dock = "bottom"
    if mode == "rows" and width < 1340:
        dock = "bottom"
    if dock == "bottom" and height < BOTTOM_DOCK_HEIGHT:
        return Plan("mini", "right", "mini")  # a bar under the channels would leave them no room: the compact list is clearer
    return Plan(mode, dock, step)


def plan_for(width: int, height: int, layout: str, look: str, previous: Optional[Plan] = None) -> Plan:
    """The plan for a window of this size. ``previous`` (the plan in use) is kept while the width is within ``HYSTERESIS`` of the edge."""
    plan = _base(width, height, layout, look)
    if previous is not None and previous != plan:
        if previous in (_base(width - HYSTERESIS, height, layout, look), _base(width + HYSTERESIS, height, layout, look)):
            return previous
    return plan
