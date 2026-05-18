"""Shared helpers for the horizontal-native maneuver shelf layouts.

Each per-maneuver layout returns a flex row of `_field()` mini-columns
plus action buttons + hidden helper containers that the existing
callbacks reference.
"""
from __future__ import annotations

from dash import html


def _field(label, control, slider=False, tooltip=None):
    """Compact labeled mini-column for the shelf.

    label slug appears as 9.5px uppercase letter-spaced text above
    the control. `slider=True` swaps to the wider `.shelf-field-slider`
    wrapper that clamps the rc-slider to a fixed width. `tooltip`
    surfaces as a native-OS hover tooltip on both the label and the
    control wrapper so pilots can pause-hover any field to learn what
    a non-default value will do."""
    cls = "shelf-field shelf-field-slider" if slider else "shelf-field"
    div_attrs = {"className": cls}
    if tooltip:
        div_attrs["title"] = tooltip
    return html.Div(
        [html.Div(label, className="shelf-field-label"), control],
        **div_attrs,
    )


def _spacer():
    """Pushes the elements after it to the right of the shelf row."""
    return html.Div(className="shelf-spacer")


def _grade(value, target, tol):
    delta = abs(value - target)
    if delta <= tol:
        return "pass"
    if delta <= tol * 1.5:
        return "marginal"
    return "fail"


def _acs_metric(label, value, units, target, tol, cert_level="private"):
    """Render an ACS-tolerance pass/fail/marginal badge.

    pass     when abs(value - target) <= tol
    marginal when abs(value - target) <= tol * 1.5
    fail     otherwise

    Returns an inline-flex html.Div with className="acs-metric" and a
    data-cert-level attribute carrying the supplied cert_level verbatim
    (e.g. "private", "commercial"). Used by per-maneuver info panels."""
    grade = _grade(value, target, tol)
    value_text = f"{value:.1f}" if isinstance(value, float) else str(value)
    children = [
        html.Span(label, className="acs-metric-label"),
        html.Span(value_text, className=f"acs-metric-value acs-{grade}"),
    ]
    if units:
        children.append(html.Span(units, className="acs-metric-units"))
    return html.Div(
        children,
        className="acs-metric",
        **{"data-cert-level": cert_level},
    )
