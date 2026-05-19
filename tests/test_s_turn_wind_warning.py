"""Test for the wind-perpendicular helper used by S-Turns (ACS Gap 3).

The ACS expects the reference line to be near-perpendicular to wind;
S-Turns is fundamentally about flying equal-radius semicircles ACROSS
the wind. A pilot who picks a line parallel to wind defeats the
purpose. Compute the angular offset between the reference line and
true wind-perpendicular; an amber chip flags any offset > 15°.
"""
from __future__ import annotations

import pytest

from callbacks.maneuvers.s_turn import _wind_perp_offset_deg


def test_east_west_line_north_wind_perfect():
    """Line 270° (E-W), wind from 0° (north) → perfect perpendicular."""
    assert _wind_perp_offset_deg(270, 0) == 0


def test_east_line_north_wind_perfect():
    """Line bearing 90° (E) — same line as 270° E-W → perpendicular."""
    assert _wind_perp_offset_deg(90, 0) == 0


def test_north_south_line_north_wind_worst():
    """Line 0° (N-S), wind from 0° (N) → parallel, worst-case 90° offset."""
    assert _wind_perp_offset_deg(0, 0) == 90


def test_small_offset_280_deg():
    assert _wind_perp_offset_deg(280, 0) == 10


def test_small_offset_260_deg():
    assert _wind_perp_offset_deg(260, 0) == 10


def test_offset_always_0_to_90():
    """Sweep a few angles and confirm the result stays in [0, 90]."""
    for line in range(0, 361, 30):
        for wind in range(0, 361, 30):
            r = _wind_perp_offset_deg(line, wind)
            assert 0 <= r <= 90, f"line={line} wind={wind} → {r}"


def test_symmetric_around_perpendicular():
    """260° and 280° should yield equal offsets (10°)."""
    assert _wind_perp_offset_deg(260, 0) == _wind_perp_offset_deg(280, 0)
