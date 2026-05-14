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
    from . import lazy_eight
    from . import steep_spiral
    from . import turns_around_point
    from . import eights_on_pylons
    from . import s_turn
    from . import engineout
    from . import impossible_turn
    from . import rectangular_course
    poweroff180.register(app)
    steep_turn.register(app)
    chandelle.register(app)
    lazy_eight.register(app)
    steep_spiral.register(app)
    turns_around_point.register(app)
    eights_on_pylons.register(app)
    s_turn.register(app)
    engineout.register(app)
    impossible_turn.register(app)
    rectangular_course.register(app)
