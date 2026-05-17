"""
TallyAero Maneuver Overlay — callback registration.

Each topical module exports a `register(app)` function. The top-level
`register_all(app)` invokes them in deterministic order. Dash callback
firing order is determined by inputs, not by registration order — the
order here is for readability only.

Module map (filled in as Phase 1 progresses):

    environment     → OAT, altimeter, wind, airport-select, elevation lookup (Phase 1d)
    aircraft        → aircraft cascade, engine/category/flap/gear, weight, fuel, power, CG (Phase 1e)
    map             → click handlers, point stores, marker rendering (Phase 1f)
    edit_aircraft   → /edit-aircraft modal + CRUD (Phase 1g)
    navigation      → URL routing, screen-width, mobile settings toggle (Phase 1d)
    maneuvers       → per-maneuver draw + simulate callbacks (Phase 1c)

Until each module exists, its `register(app)` import here is commented out.
"""

from __future__ import annotations


def register_all(app):
    """Wire every callback module to the given Dash app.

    Sub-phases will uncomment the imports + calls below as each module lands.
    """
    from . import navigation       # Phase 1i
    from . import environment      # Phase 1d
    from . import aircraft         # Phase 1e
    from . import map as map_      # Phase 1f
    from . import edit_aircraft    # Phase 1g
    from . import route            # Phase 5d
    from . import sidebar          # Phase 8d
    from .maneuvers import register_maneuvers   # Phase 1c

    navigation.register(app)
    environment.register(app)
    aircraft.register(app)
    map_.register(app)
    edit_aircraft.register(app)
    route.register(app)
    sidebar.register(app)
    register_maneuvers(app)

    # Phase 1 complete: every callback module is wired. app.py retains
    # only the Dash() instantiation, the layout shell, and the __main__
    # entry point.
