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
from .chandelle import chandelle_layout
from .lazy_eight import lazy8_layout
from .steep_spiral import steep_spiral_layout
from .s_turn import s_turn_layout
from .turns_around_point import turns_point_layout

# Filled in as Phase 1b lands. The re-export here lets app.py write a
# single `from layouts.maneuvers import *` once Task 13 ships.
__all__: list[str] = [
    "impossible_turn_layout",
    "poweroff180_layout",
    "engineout_layout",
    "steep_turn_layout",
    "chandelle_layout",
    "lazy8_layout",
    "steep_spiral_layout",
    "s_turn_layout",
    "turns_point_layout",
]
