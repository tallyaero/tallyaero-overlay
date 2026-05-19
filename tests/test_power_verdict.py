"""Tests for the Phase D2 _power_verdict helper.

Covers the three-tier grading:
  - |delta| < 0.10  → green badge ("Power: X%")
  - |delta| < 0.20  → amber chip ("Off-design power: ...")
  - |delta| >= 0.20 → red banner ("Maneuver failed — ...")
And clamping / None-fallback behavior.
"""
from dash import html

from layouts.maneuvers._shared import _power_verdict


def _is_badge(v):
    return isinstance(v, html.Div) and getattr(v, "className", "") == "acs-metric"


def _is_amber_chip(v):
    return isinstance(v, html.Div) and "power-chip" in getattr(v, "className", "")


def _is_red_banner(v):
    return isinstance(v, html.Div) and "power-banner" in getattr(v, "className", "")


def test_zero_delta_is_green():
    v = _power_verdict(0.70, 0.70, "c", "f")
    assert _is_badge(v)


def test_small_delta_is_green():
    v = _power_verdict(0.79, 0.70, "c", "f")
    assert _is_badge(v)


def test_11pct_below_is_amber():
    """At 0.11 absolute delta we're clearly in the amber band."""
    v = _power_verdict(0.59, 0.70, "c", "f")
    assert _is_amber_chip(v)
    assert "59%" in v.children
    assert "design 70%" in v.children
    assert "— c" in v.children


def test_11pct_above_is_amber():
    v = _power_verdict(0.81, 0.70, "c", "f")
    assert _is_amber_chip(v)


def test_15pct_off_is_amber():
    v = _power_verdict(0.55, 0.70, "c", "f")
    assert _is_amber_chip(v)


def test_21pct_off_is_red():
    """At 0.21 absolute delta we're past the red threshold."""
    v = _power_verdict(0.49, 0.70, "c", "fail-text")
    assert _is_red_banner(v)
    assert "Maneuver failed — fail-text" in v.children


def test_far_off_is_red():
    v = _power_verdict(1.00, 0.30, "c", "fail-text")
    assert _is_red_banner(v)


def test_negative_clamps_to_zero():
    v = _power_verdict(-0.5, 0.0, "c", "f")
    assert _is_badge(v)  # 0.0 vs 0.0 = green


def test_above_one_clamps_to_one():
    v = _power_verdict(2.0, 1.0, "c", "f")
    assert _is_badge(v)  # 1.0 vs 1.0 = green


def test_none_power_falls_back_to_design():
    v = _power_verdict(None, 0.625, "c", "f")
    assert _is_badge(v)  # treated as design → green


def test_garbage_power_falls_back_to_design():
    v = _power_verdict("not-a-number", 0.625, "c", "f")
    assert _is_badge(v)
