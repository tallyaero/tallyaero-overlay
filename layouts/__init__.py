"""
TallyAero Maneuver Overlay — layouts package.

Builds the desktop + mobile layout trees. The per-maneuver parameter
forms live under `layouts/maneuvers/` and get composed into the maneuver
picker.

Pure functions; no callbacks, no Dash app reference. The `register_all`
inside callbacks/ is what wires interactivity.
"""

from __future__ import annotations

from .desktop import desktop_layout
from .mobile import mobile_layout

__all__ = [
    "desktop_layout",
    "mobile_layout",
]
