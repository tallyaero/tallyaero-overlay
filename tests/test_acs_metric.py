"""Tests for the _acs_metric shared helper.

_acs_metric(label, value, units, target, tol, cert_level="private") returns
an html.Div badge that grades a measured value against an ACS tolerance:
- pass     when abs(value - target) <= tol
- marginal when abs(value - target) <= tol * 1.5
- fail     otherwise

Used by per-maneuver info panels (Steep Turn alt loss, Lazy 8 alt
consistency, Rect leg-length match, S-Turns radius match, Pylons heading
±10, Steep Spiral heading ±10, etc.). Single source of truth so the
pass/fail badge styling stays consistent across all 12 maneuvers.
"""
from __future__ import annotations

from dash import html

from layouts.maneuvers._shared import _acs_metric


def _value_span(div):
    """Return the value Span (second child, after label)."""
    children = [c for c in div.children if c is not None]
    return children[1]


def _units_span_or_none(div):
    children = [c for c in div.children if c is not None]
    return children[2] if len(children) >= 3 else None


def test_pass_within_tolerance():
    div = _acs_metric("Alt loss", 50.0, "ft", target=0.0, tol=100.0)
    assert isinstance(div, html.Div)
    assert div.className == "acs-metric"
    assert "acs-pass" in _value_span(div).className


def test_pass_at_exact_target():
    div = _acs_metric("Heading", 360.0, "deg", target=360.0, tol=10.0)
    assert "acs-pass" in _value_span(div).className


def test_pass_at_edge_of_tolerance():
    div = _acs_metric("Alt loss", 100.0, "ft", target=0.0, tol=100.0)
    assert "acs-pass" in _value_span(div).className


def test_marginal_above_tolerance():
    div = _acs_metric("Alt loss", 120.0, "ft", target=0.0, tol=100.0)
    assert "acs-marginal" in _value_span(div).className


def test_marginal_at_edge():
    div = _acs_metric("Alt loss", 150.0, "ft", target=0.0, tol=100.0)
    assert "acs-marginal" in _value_span(div).className


def test_fail_well_beyond_tolerance():
    div = _acs_metric("Alt loss", 250.0, "ft", target=0.0, tol=100.0)
    assert "acs-fail" in _value_span(div).className


def test_zero_tolerance_pass_only_on_match():
    div = _acs_metric("Bank", 60.0, "deg", target=60.0, tol=0.0)
    assert "acs-pass" in _value_span(div).className


def test_zero_tolerance_fail_off_by_any_amount():
    div = _acs_metric("Bank", 60.1, "deg", target=60.0, tol=0.0)
    assert "acs-fail" in _value_span(div).className


def test_negative_value_positive_target_distance_is_absolute():
    div = _acs_metric("Alt delta", -50.0, "ft", target=0.0, tol=100.0)
    assert "acs-pass" in _value_span(div).className


def test_negative_value_positive_target_fail():
    div = _acs_metric("Alt delta", -250.0, "ft", target=0.0, tol=100.0)
    assert "acs-fail" in _value_span(div).className


def test_label_span_present():
    div = _acs_metric("Heading", 360.0, "deg", target=360.0, tol=10.0)
    label_span = [c for c in div.children if c is not None][0]
    assert label_span.children == "Heading"


def test_units_span_present_when_units_nonempty():
    div = _acs_metric("Heading", 360.0, "deg", target=360.0, tol=10.0)
    units = _units_span_or_none(div)
    assert units is not None
    assert units.children == "deg"


def test_empty_units_produces_no_units_span():
    div = _acs_metric("Score", 95.0, "", target=100.0, tol=10.0)
    units = _units_span_or_none(div)
    assert units is None


def test_default_cert_level_is_private():
    div = _acs_metric("Alt", 50.0, "ft", target=0.0, tol=100.0)
    assert div.__getattribute__("data-cert-level") == "private"


def test_commercial_cert_level_propagates():
    div = _acs_metric(
        "Alt", 50.0, "ft", target=0.0, tol=100.0, cert_level="commercial"
    )
    assert div.__getattribute__("data-cert-level") == "commercial"
