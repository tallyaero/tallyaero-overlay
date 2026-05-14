"""Edit-Aircraft modal/page callbacks.

Companion to layouts/edit_aircraft.py. The original root-level
edit_aircraft_page.py contained zero @app.callback registrations - the
editor's interactivity is hosted externally at app.flyaeroedge.com - so
register(app) is intentionally a no-op stub. Wiring lands here when the
overlay tool grows its own edit-aircraft callbacks.
"""

from __future__ import annotations


def register(app):
    """Install every edit-aircraft callback against the given Dash app.

    The original edit_aircraft_page.py shipped no @app.callback decorators;
    this stub exists so callbacks/__init__.py can wire it without special-
    casing and so future modal/route callbacks have an obvious home.
    """
    # No callbacks to register yet. Add them inside this function as the
    # edit-aircraft page grows interactivity inside the overlay tool.
    return
