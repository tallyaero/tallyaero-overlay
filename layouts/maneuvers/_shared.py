"""Shared helpers for the horizontal-native maneuver shelf layouts.

Each per-maneuver layout returns a flex row of `_field()` mini-columns
plus action buttons + hidden helper containers that the existing
callbacks reference.
"""
from __future__ import annotations

from dash import html


def _field(label, control, slider=False):
    """Compact labeled mini-column for the shelf.

    label slug appears as 9.5px uppercase letter-spaced text above
    the control. `slider=True` swaps to the wider `.shelf-field-slider`
    wrapper that clamps the rc-slider to a fixed width."""
    cls = "shelf-field shelf-field-slider" if slider else "shelf-field"
    return html.Div(
        [html.Div(label, className="shelf-field-label"), control],
        className=cls,
    )


def _spacer():
    """Pushes the elements after it to the right of the shelf row."""
    return html.Div(className="shelf-spacer")
