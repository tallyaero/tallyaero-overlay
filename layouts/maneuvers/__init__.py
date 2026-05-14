"""Per-maneuver parameter forms. Each module exports a `<name>_layout()`
function returning a list of Dash components used inside the maneuver
picker accordion.

Phase 1b populates this package one maneuver at a time.
"""

from __future__ import annotations

from .impossible_turn import impossible_turn_layout
from .poweroff180 import poweroff180_layout
from .engineout import engineout_layout
from .steep_turn import steep_turn_layout

# Filled in as Phase 1b lands. The re-export here lets app.py write a
# single `from layouts.maneuvers import *` once Task 13 ships.
__all__: list[str] = [
    "impossible_turn_layout",
    "poweroff180_layout",
    "engineout_layout",
    "steep_turn_layout",
]
