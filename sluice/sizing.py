"""How the window arranges itself at the size it has: the layout shown, where the Listen and Broadcast cards sit, and how much of
the top bar is shown. Pure functions of the window size, so they are easy to test; the window only follows what they say."""

from __future__ import annotations

from typing import NamedTuple, Optional

HYSTERESIS = 24  # pixels: a plan is kept while the width stays this close to the edge it changed at (no flicker while dragging)
BOTTOM_DOCK_HEIGHT = 720  # the Listen and Broadcast bar needs this much height beside the channels
MINI_HEIGHT = 460  # shorter than this, only the compact list fits
STEPS = ("roomy", "standard", "compact", "mini")
# The Rows layout: one row is its name, buttons and tools (ROW_FIXED) plus a cell per mix (slider, level, mute: ROW_CELL_MIN, with
# 16 px between). A cell narrower than that puts the level over the slider, so the window never offers Rows narrower than this.
ROW_FIXED = 458
ROW_CELL_MIN = 260
ROW_RING = 64  # Nexus (0.11.6): the 48 px ring at the start of each row, and the 16 px gap after it
ROW_SLACK = 72  # the window's side margins, the list's right margin and room for its scroll bar
MASTERS_SIDE = 328  # Listen and Broadcast docked at the right: their column and the gap before it
THREE_MASTERS_HEIGHT = 1000  # three mix cards stacked at the right need this much height; shorter, they go in the bar below


def rows_min_width(mixes: int, skin: str = "") -> int:
    """The narrowest window that shows the Rows layout with this many mixes, Listen and Broadcast in the bar below."""
    return ROW_FIXED + (ROW_RING if skin == "nexus" else 0) + max(2, mixes) * (ROW_CELL_MIN + 16) + ROW_SLACK


class Plan(NamedTuple):
    mode: str  # columns, rows or mini (the compact list)
    dock: str  # right: Listen and Broadcast beside the channels; bottom: in a bar under them (columns and rows only)
    step: str  # roomy, standard, compact or mini: how much of the top bar and spacing is shown


def _base(width: int, height: int, layout: str, skin: str, mixes: int = 2) -> Plan:
    if layout == "list":  # 0.13.1: the compact list chosen on purpose, at any size: a second screen beside a game (from Nexus)
        return Plan("mini", "right", "mini")
    mode = layout if layout in ("columns", "rows") else "columns"  # anything else (Free, gone in 0.11.5) shows Columns
    step = "roomy" if width >= 1600 else "standard" if width >= 1180 else "compact" if width >= 820 else "mini"
    narrowest = {"rows": rows_min_width(mixes, skin)}.get(mode, 760)
    if width < narrowest or height < MINI_HEIGHT:
        return Plan("mini", "right", "mini")
    dock = "right"
    if mode == "columns" and width < 1180:
        dock = "bottom"
    if mode == "rows" and (width < rows_min_width(mixes, skin) + MASTERS_SIDE or (mixes > 2 and height < THREE_MASTERS_HEIGHT)):
        dock = "bottom"
    if dock == "bottom" and height < BOTTOM_DOCK_HEIGHT:
        return Plan("mini", "right", "mini")  # a bar under the channels would leave them no room: the compact list is clearer
    return Plan(mode, dock, step)


def plan_for(width: int, height: int, layout: str, skin: str, previous: Optional[Plan] = None, mixes: int = 2) -> Plan:
    """The plan for a window of this size. ``previous`` (the plan in use) is kept while the width is within ``HYSTERESIS`` of the edge.
    ``mixes`` is how many mixes there are (2, or 3 with Recording): a third needs a wider window for Rows."""
    plan = _base(width, height, layout, skin, mixes)
    if previous is not None and previous != plan:
        if previous in (
            _base(width - HYSTERESIS, height, layout, skin, mixes),
            _base(width + HYSTERESIS, height, layout, skin, mixes),
        ):
            return previous
    return plan
