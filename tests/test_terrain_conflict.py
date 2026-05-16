"""Tests for core.terrain_conflict — classification, segmentation,
VFR rounding, suggested altitude, profile data."""
from __future__ import annotations

import pytest
from core.terrain_conflict import (
    classify_sample_terrain_status,
    segment_polyline_by_status,
    max_terrain_in_corridor_strip,
    vfr_cruise_round_up,
    suggest_min_cruise_alt,
    build_profile_series,
    MARGINAL_AGL_FT, CONFLICT_AGL_FT,
)


# === Status classification ==================================================

def test_clear_above_2000_agl():
    assert classify_sample_terrain_status(5500, 100) == "clear"


def test_marginal_500_to_2000_agl():
    # 5500 - 4500 = 1000 ft AGL → marginal
    assert classify_sample_terrain_status(5500, 4500) == "marginal"


def test_conflict_under_500_agl():
    assert classify_sample_terrain_status(5500, 5100) == "conflict"


def test_conflict_terrain_pierces_cruise():
    """Cruise below terrain (negative AGL)."""
    assert classify_sample_terrain_status(5500, 6000) == "conflict"


def test_threshold_boundaries():
    """Exact boundary values."""
    assert classify_sample_terrain_status(2000, 0) == "clear"     # exactly 2000 AGL
    assert classify_sample_terrain_status(1999, 0) == "marginal"  # just below
    assert classify_sample_terrain_status(500, 0) == "marginal"   # exactly 500
    assert classify_sample_terrain_status(499, 0) == "conflict"   # just below


# === Polyline segmentation ==================================================

def test_segment_all_clear():
    samples = [(0, 0), (1, 0), (2, 0)]
    statuses = ["clear", "clear", "clear"]
    out = segment_polyline_by_status(samples, statuses)
    assert len(out) == 1
    assert out[0]["status"] == "clear"
    assert len(out[0]["positions"]) == 3


def test_segment_alternating():
    samples = [(0, 0), (1, 0), (2, 0), (3, 0)]
    statuses = ["clear", "conflict", "conflict", "clear"]
    out = segment_polyline_by_status(samples, statuses)
    assert len(out) == 3
    assert [s["status"] for s in out] == ["clear", "conflict", "clear"]


def test_segment_includes_boundary_in_both():
    """Adjacent segments share the boundary sample so they visually connect."""
    samples = [(0, 0), (1, 0), (2, 0)]
    statuses = ["clear", "clear", "conflict"]
    out = segment_polyline_by_status(samples, statuses)
    assert len(out) == 2
    # First segment has [0, 1] PLUS the boundary at 2
    assert len(out[0]["positions"]) == 3
    # Second segment starts at the boundary 2
    assert len(out[1]["positions"]) == 1


def test_segment_single_sample():
    out = segment_polyline_by_status([(0, 0)], ["clear"])
    assert len(out) == 1
    assert out[0]["positions"] == [[0, 0]]


def test_segment_empty():
    assert segment_polyline_by_status([], []) == []


# === Corridor-strip max terrain =============================================

def test_strip_finds_centerline_peak():
    """No perpendicular variation → centerline determines peak."""
    def elev_fn(lat, lon):
        # Peak at lat=0.5
        return 1000.0 if abs(lat - 0.5) < 0.05 else 0.0
    samples = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
    peak_ft, plat, plon = max_terrain_in_corridor_strip(samples, elev_fn,
                                                        half_width_nm=0.0,
                                                        perp_samples=1)
    # 1000 m = 3281 ft
    assert abs(peak_ft - 3281) < 5


def test_strip_finds_off_centerline_peak():
    """A ridge parallel to but offset from the route."""
    def elev_fn(lat, lon):
        if abs(lon - 0.05) < 0.01:   # ridge slightly east of route
            return 2000.0
        return 0.0
    samples = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
    peak_ft, _, _ = max_terrain_in_corridor_strip(
        samples, elev_fn, half_width_nm=5.0, perp_samples=5)
    # 2000 m = 6562 ft
    assert peak_ft > 6000


def test_strip_zero_samples():
    peak_ft, _, _ = max_terrain_in_corridor_strip([], lambda l, o: 0.0)
    assert peak_ft == 0.0


# === VFR cruise rounding (FAR 91.159) ======================================

def test_eastbound_rounds_to_odd_thousand_500():
    # Eastbound: 3500, 5500, 7500, ...
    assert vfr_cruise_round_up(5000, magnetic_course_deg=90) == 5500
    assert vfr_cruise_round_up(5499, magnetic_course_deg=90) == 5500
    assert vfr_cruise_round_up(5500, magnetic_course_deg=90) == 5500  # exact
    assert vfr_cruise_round_up(5501, magnetic_course_deg=90) == 7500


def test_westbound_rounds_to_even_thousand_500():
    # Westbound: 4500, 6500, 8500, ...
    assert vfr_cruise_round_up(5000, magnetic_course_deg=270) == 6500
    assert vfr_cruise_round_up(6499, magnetic_course_deg=270) == 6500
    assert vfr_cruise_round_up(6500, magnetic_course_deg=270) == 6500
    assert vfr_cruise_round_up(6501, magnetic_course_deg=270) == 8500


def test_eastbound_boundary_at_179():
    """179° magnetic = eastbound."""
    assert vfr_cruise_round_up(5000, magnetic_course_deg=179) == 5500


def test_westbound_boundary_at_180():
    """180° magnetic = westbound."""
    assert vfr_cruise_round_up(5000, magnetic_course_deg=180) == 6500


def test_high_altitude_rounds_to_500_increments():
    """At/above 17500 ft we drop the odd/even rule."""
    assert vfr_cruise_round_up(17600, magnetic_course_deg=90) == 18000
    assert vfr_cruise_round_up(17500, magnetic_course_deg=270) == 17500


# === Suggested altitude =====================================================

def test_suggest_non_mountainous_buffer():
    """4000 ft peak + 1000 buffer = 5000, rounded eastbound = 5500."""
    alt, reason = suggest_min_cruise_alt(4000, [90], terrain_variance_ft=500)
    assert alt == 5500
    assert "non-mountainous" in reason


def test_suggest_mountainous_buffer():
    """7000 ft peak + 2000 buffer (variance >3000) = 9000, rounded
    eastbound = 9500."""
    alt, _reason = suggest_min_cruise_alt(7000, [90], terrain_variance_ft=4000)
    assert alt == 9500


def test_suggest_uses_first_course_eastbound():
    alt, _ = suggest_min_cruise_alt(4000, [45], terrain_variance_ft=500)
    assert alt == 5500


def test_suggest_uses_first_course_westbound():
    alt, _ = suggest_min_cruise_alt(4000, [270], terrain_variance_ft=500)
    assert alt == 6500


# === Profile series =========================================================

def test_profile_series_distance_cumulative():
    """Distances grow monotonically from departure."""
    elev_fn = lambda l, o: 100.0
    samples = [(33.0, -80.0), (33.5, -80.0), (34.0, -80.0)]
    alts = [50, 5500, 50]
    p = build_profile_series(samples, alts, elev_fn)
    assert p["distance_nm"][0] == 0.0
    assert p["distance_nm"][1] > 0
    assert p["distance_nm"][2] > p["distance_nm"][1]


def test_profile_series_terrain_converted_to_ft():
    """100 m terrain returns ~328 ft."""
    elev_fn = lambda l, o: 100.0
    samples = [(33.0, -80.0), (33.1, -80.0)]
    alts = [5500, 5500]
    p = build_profile_series(samples, alts, elev_fn)
    assert all(abs(t - 328) < 1 for t in p["terrain_ft"])


def test_profile_series_status_consistent_with_classifier():
    """Status array matches what classify_sample_terrain_status would say."""
    elev_fn = lambda l, o: 1500.0   # ~4920 ft terrain
    samples = [(33.0, -80.0)]
    alts = [5500]   # ~580 ft AGL → marginal
    p = build_profile_series(samples, alts, elev_fn)
    assert p["statuses"][0] == "marginal"


def test_profile_series_empty():
    p = build_profile_series([], [], lambda l, o: 0.0)
    assert p["distance_nm"] == [] and p["terrain_ft"] == []
