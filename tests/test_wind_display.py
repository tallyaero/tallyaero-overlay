"""Tests for core.wind_display — barb SVG, component math, density."""
from __future__ import annotations

import math
from core.wind_display import (
    wind_barb_svg, wind_components, format_wind_components,
    pick_barb_indices, route_average_wind,
)


# === SVG barb ===============================================================

def test_barb_svg_calm_is_open_circle():
    svg = wind_barb_svg(0.0, 0.5)
    assert "<circle" in svg
    assert "<line" not in svg


def test_barb_svg_5kt_has_one_half_feather():
    svg = wind_barb_svg(180.0, 5.0)
    # Stem line + one half feather line = 2 lines, zero polygons
    assert svg.count("<line") == 2
    assert "<polygon" not in svg


def test_barb_svg_10kt_has_one_full_feather():
    svg = wind_barb_svg(180.0, 10.0)
    assert svg.count("<line") == 2   # stem + 1 full feather
    assert "<polygon" not in svg


def test_barb_svg_25kt():
    """25 kt = 2 full feathers + 1 half feather = 4 lines (stem + 3)."""
    svg = wind_barb_svg(180.0, 25.0)
    assert svg.count("<line") == 4
    assert "<polygon" not in svg


def test_barb_svg_50kt_pennant():
    svg = wind_barb_svg(180.0, 50.0)
    assert svg.count("<polygon") == 1
    assert svg.count("<line") == 1   # only stem


def test_barb_svg_65kt():
    """65 kt = 1 pennant (50) + 1 full feather (10) + 1 half (5)."""
    svg = wind_barb_svg(180.0, 65.0)
    assert svg.count("<polygon") == 1
    assert svg.count("<line") == 3   # stem + full + half


def test_barb_svg_rotation_present():
    """SVG must apply transform: rotate(<dir>deg)."""
    svg = wind_barb_svg(270.0, 15.0)
    assert "rotate(270" in svg


# === Components =============================================================

def test_components_pure_tailwind_eastbound():
    """Track 090, wind FROM 270 (west wind blowing east) → pure tailwind."""
    hw_tw, cross = wind_components(90.0, 270.0, 20.0)
    assert abs(hw_tw - 20.0) < 0.01
    assert abs(cross) < 0.01


def test_components_pure_headwind_eastbound():
    """Track 090, wind FROM 090 (east wind blowing west) → pure headwind."""
    hw_tw, cross = wind_components(90.0, 90.0, 20.0)
    assert abs(hw_tw + 20.0) < 0.01
    assert abs(cross) < 0.01


def test_components_pure_right_crosswind_eastbound():
    """Track 090, wind FROM 180 (south wind blowing north) → pure
    crosswind from the right side of an eastbound airplane."""
    hw_tw, cross = wind_components(90.0, 180.0, 15.0)
    assert abs(hw_tw) < 0.01
    assert cross > 14.9   # +cross = from RIGHT


def test_components_pure_left_crosswind_eastbound():
    """Track 090, wind FROM 360 → from north → left side."""
    hw_tw, cross = wind_components(90.0, 360.0, 15.0)
    assert abs(hw_tw) < 0.01
    assert cross < -14.9   # -cross = from LEFT


def test_components_45_quarter_tailwind():
    """Wind FROM 225 (SW) on a 090 (eastbound) track → tailwind + right XW."""
    hw_tw, cross = wind_components(90.0, 225.0, 14.0)
    # cos(135°-...) actually let's just check both signs and magnitude
    assert hw_tw > 0     # tailwind component
    assert cross > 0     # right crosswind (south side)
    # Resultant magnitude is the wind speed
    assert abs(math.hypot(hw_tw, cross) - 14.0) < 0.01


# === format_wind_components =================================================

def test_format_calm():
    assert format_wind_components(0.5, 0.3) == "calm"


def test_format_headwind_right_xw():
    s = format_wind_components(-12.0, 4.0)
    assert "HW 12" in s
    assert "XW 4R" in s


def test_format_tailwind_left_xw():
    s = format_wind_components(18.0, -3.0)
    assert "TW 18" in s
    assert "XW 3L" in s


# === Adaptive density =======================================================

def test_pick_barbs_short_route():
    idxs = pick_barb_indices(20, 30)
    assert len(idxs) <= 3
    assert idxs[0] == 0   # endpoints included
    assert idxs[-1] == 19


def test_pick_barbs_medium_route():
    idxs = pick_barb_indices(100, 250)
    assert 6 <= len(idxs) <= 8


def test_pick_barbs_long_route():
    idxs = pick_barb_indices(500, 1500)
    assert len(idxs) <= 12


def test_pick_barbs_evenly_spaced():
    """Returned indices are sorted and roughly evenly spaced."""
    idxs = pick_barb_indices(100, 250)
    diffs = [idxs[i + 1] - idxs[i] for i in range(len(idxs) - 1)]
    assert min(diffs) > 0
    # Spacing differences across the route shouldn't vary by more
    # than a factor of 2
    assert max(diffs) <= 2 * min(diffs) + 1


# === Vector mean wind =======================================================

def test_average_wind_uniform():
    """Constant wind input → same wind output."""
    winds = [(270.0, 20.0)] * 5
    d, s = route_average_wind(winds)
    assert abs(d - 270.0) < 0.5
    assert abs(s - 20.0) < 0.01


def test_average_wind_opposite_cancels():
    """350° and 170° (180° apart) of equal magnitude average to ~0 speed."""
    winds = [(350.0, 10.0), (170.0, 10.0)]
    _, s = route_average_wind(winds)
    assert s < 0.5


def test_average_wind_empty():
    d, s = route_average_wind([])
    assert d == 0.0 and s == 0.0


def test_average_wind_wraparound():
    """350° and 010° average to ~0° (or 360°), not 180°."""
    winds = [(350.0, 10.0), (10.0, 10.0)]
    d, _ = route_average_wind(winds)
    diff = min(abs(d - 0.0), abs(d - 360.0))
    assert diff < 5.0
