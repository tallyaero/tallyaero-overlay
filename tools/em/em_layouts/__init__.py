"""
TallyAero EM Diagram — layout package.

Each module exports a layout-builder function. All are pure: no callbacks,
no side effects. The dispatcher `em_diagram_layout(is_mobile=False)` picks
the right tree at render time based on detected viewport width.

Phase 5 will collapse desktop + mobile into a single responsive layout
driven by CSS grid + the design tokens. For now they remain sibling trees.
"""

from __future__ import annotations

from .desktop import desktop_layout
from .edit_aircraft import edit_aircraft_layout
from .mobile import mobile_layout


def em_diagram_layout(is_mobile: bool = False):
    """Dispatch to mobile vs desktop based on caller-detected viewport size."""
    if is_mobile:
        return mobile_layout()
    return desktop_layout()


__all__ = [
    "em_diagram_layout",
    "desktop_layout",
    "mobile_layout",
    "edit_aircraft_layout",
]
