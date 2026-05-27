"""
TallyAero EM Diagram — callback registration.

Each topical module in this package exports a `register(app)` function. The
top-level `register_all(app)` invokes them in deterministic order. The
ordering below is for readability only — Dash callback firing order is
determined by inputs, not by registration order.

Module map (Phase 1g complete):

    figure          → the sacred `update_graph` chart callback
    main            → aircraft selection cascade, dropdowns, CG, weight, maneuvers
    environment     → altitude, OAT, altimeter, airport defaulting
    edit_aircraft   → the entire /edit-aircraft CRUD surface (22 callbacks)
    export          → PDF and PNG generation
    modals          → disclaimer, terms, README, help-bubble routing
    overlays        → multi-engine sync and mobile sidebar
    navigation      → URL routing and back/forward/screen-width
    ui_toggles      → segmented controls and edit-page accordion utilities
"""

from __future__ import annotations

from . import edit_aircraft
from . import environment
from . import export
from . import figure
from . import figure_hv
from . import main
from . import modals
from . import navigation
from . import overlays
from . import ui_toggles


def register_all(app):
    """Wire every callback module to the given Dash app."""
    figure.register(app)
    figure_hv.register(app)
    main.register(app)
    environment.register(app)
    edit_aircraft.register(app)
    export.register(app)
    modals.register(app)
    overlays.register(app)
    navigation.register(app)
    ui_toggles.register(app)
