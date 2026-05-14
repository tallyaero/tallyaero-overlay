"""Per-maneuver parameter forms. Each module exports a `<name>_layout()`
function returning a list of Dash components used inside the maneuver
picker accordion.

Phase 1b populates this package one maneuver at a time.
"""

from __future__ import annotations

# Filled in as Phase 1b lands. The re-export here lets app.py write a
# single `from layouts.maneuvers import *` once Task 13 ships.
__all__: list[str] = []
