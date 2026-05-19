"""Tests for the per-leg WCA helper used by Rectangular Course (ACS Gap 4).

The Rectangular Course simulation produces a hover list with 4 straight
legs (downwind, base, upwind, crosswind) interleaved with 4 turn
segments (turn_to_base etc). The helper groups by segment, drops the
turns, and emits one row per straight leg with avg_gs, avg_crab,
max_crab.
"""
from __future__ import annotations

import pytest

from callbacks.maneuvers.rectangular_course import _per_leg_wca


def _hover_for(legs):
    """legs = list of (segment, gs, drift) tuples, repeated per step."""
    out = []
    for seg, gs, drift in legs:
        out.append({"segment": seg, "gs": gs, "drift": drift})
    return out


def test_groups_four_straight_legs_in_order():
    hover = _hover_for([
        ("entry", 100, 0),
        ("entry_turn", 100, 0),
        ("downwind", 110, -5),
        ("downwind", 110, -5),
        ("turn_to_base", 100, 0),
        ("base", 95, -10),
        ("turn_to_upwind", 95, 0),
        ("upwind", 85, +5),
        ("upwind", 85, +5),
        ("turn_to_crosswind", 90, 0),
        ("crosswind", 95, +10),
        ("turn_to_downwind", 100, 0),
    ])
    rows = _per_leg_wca(hover)
    legs = [r["leg"] for r in rows]
    assert legs == ["downwind", "base", "upwind", "crosswind"]


def test_avg_gs_per_leg():
    hover = _hover_for([
        ("downwind", 110, -5),
        ("downwind", 120, -7),
        ("base", 95, -10),
        ("upwind", 85, +5),
        ("crosswind", 95, +10),
    ])
    rows = _per_leg_wca(hover)
    dw = next(r for r in rows if r["leg"] == "downwind")
    assert dw["avg_gs"] == 115


def test_max_crab_uses_absolute_value():
    hover = _hover_for([
        ("downwind", 100, -8),
        ("downwind", 100, -12),
    ])
    rows = _per_leg_wca(hover)
    dw = next(r for r in rows if r["leg"] == "downwind")
    assert dw["max_crab"] == 12.0


def test_avg_crab_signed():
    """avg_crab averages signed values (preserves left/right direction)."""
    hover = _hover_for([
        ("base", 100, -8),
        ("base", 100, -12),
    ])
    rows = _per_leg_wca(hover)
    base = next(r for r in rows if r["leg"] == "base")
    assert base["avg_crab"] == -10.0


def test_skips_turn_segments():
    hover = _hover_for([
        ("entry_turn", 100, 0),
        ("turn_to_base", 100, 0),
        ("turn_to_upwind", 100, 0),
        ("turn_to_crosswind", 100, 0),
        ("turn_to_downwind", 100, 0),
    ])
    rows = _per_leg_wca(hover)
    assert rows == []


def test_skips_entry_segment():
    hover = _hover_for([
        ("entry", 100, 0),
        ("downwind", 110, -5),
    ])
    rows = _per_leg_wca(hover)
    legs = [r["leg"] for r in rows]
    assert "entry" not in legs
