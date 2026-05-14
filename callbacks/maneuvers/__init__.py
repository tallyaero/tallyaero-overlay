"""Per-maneuver draw/simulate callbacks. Each module exports `register(app)`.

The package-level `register_maneuvers(app)` wires every maneuver in
deterministic order. Phase 1c populates this.
"""

from __future__ import annotations


def register_maneuvers(app):
    """Register every maneuver callback. Populated as Phase 1c lands."""
    from . import poweroff180
    from . import steep_turn
    from . import chandelle
    poweroff180.register(app)
    steep_turn.register(app)
    chandelle.register(app)
