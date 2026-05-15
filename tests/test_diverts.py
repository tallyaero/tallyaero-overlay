"""Tests for core.diverts — landability filter, per-sample reach,
unique aggregation, and gap-segment detection."""
from __future__ import annotations

import pytest
from core.diverts import (
    is_landable, find_diverts_in_reach,
    divert_coverage_along_route, gap_segments, longest_gap_nm,
)


# Synthetic mini-airport DB for fast deterministic tests.
@pytest.fixture
def airports():
    return [
        # Large/medium without runways data — accepted by fallback
        {"id": "KCHS", "lat": 32.8986, "lon": -80.0405,
         "name": "Charleston Intl", "type": "large_airport"},
        {"id": "KSAV", "lat": 32.1276, "lon": -81.2021,
         "name": "Savannah", "type": "medium_airport"},
        # Small with long runway — accepted
        {"id": "KDYB", "lat": 33.0635, "lon": -80.2795,
         "name": "Summerville", "type": "small_airport",
         "runways": [{"length_ft": 5400, "surface": "asphalt"}]},
        # Small with short runway — rejected (<1500 ft)
        {"id": "Q01", "lat": 33.05, "lon": -80.30,
         "name": "Tiny strip", "type": "small_airport",
         "runways": [{"length_ft": 1200, "surface": "turf"}]},
        # Small without runway data — rejected by fallback
        {"id": "Q02", "lat": 33.20, "lon": -80.40,
         "name": "Unknown strip", "type": "small_airport"},
        # Seaplane base — never landable
        {"id": "S99", "lat": 33.10, "lon": -80.20,
         "name": "Seaplane", "type": "seaplane_base"},
        # Far away — should be filtered by reach
        {"id": "KJFK", "lat": 40.6398, "lon": -73.7789,
         "name": "JFK", "type": "large_airport"},
    ]


def test_is_landable_seaplane_rejected(airports):
    assert is_landable(airports[5]) is False


def test_is_landable_large_no_runway_accepted(airports):
    assert is_landable(airports[0]) is True


def test_is_landable_small_with_long_runway(airports):
    assert is_landable(airports[2]) is True


def test_is_landable_small_short_runway_rejected(airports):
    assert is_landable(airports[3]) is False


def test_is_landable_small_no_runway_rejected(airports):
    assert is_landable(airports[4]) is False


def test_is_landable_custom_minimum(airports):
    """Q01 has 1200 ft — accepted if user sets a lower threshold."""
    assert is_landable(airports[3], min_runway_ft=1000) is True


def test_find_diverts_in_reach_short(airports):
    """At KDYB with 10 NM reach, should pick up KDYB itself + KCHS."""
    hits = find_diverts_in_reach(airports, 33.0635, -80.2795, 25.0)
    ids = [h["airport"]["id"] for h in hits]
    assert "KDYB" in ids
    assert "KCHS" in ids
    # KSAV is ~70 NM south — not in 25 NM reach
    assert "KSAV" not in ids
    # KJFK is hundreds of NM away
    assert "KJFK" not in ids


def test_find_diverts_sorted_by_distance(airports):
    hits = find_diverts_in_reach(airports, 33.0635, -80.2795, 100.0)
    dists = [h["distance_nm"] for h in hits]
    assert dists == sorted(dists)


def test_find_diverts_zero_reach(airports):
    assert find_diverts_in_reach(airports, 33.0, -80.0, 0.0) == []


def test_divert_coverage_constant_reach(airports):
    samples = [(33.0635, -80.2795), (32.8986, -80.0405), (32.1276, -81.2021)]
    out = divert_coverage_along_route(samples, airports, 30.0)
    assert len(out["per_sample"]) == 3
    # Each sample is at an airport, so each should have at least 1 reach
    for cov in out["per_sample"]:
        assert len(cov) >= 1
    assert out["n_samples_with_no_coverage"] == 0
    # Unique set should include all three nearby airports
    ids = [d["airport"]["id"] for d in out["unique_diverts"]]
    assert "KDYB" in ids
    assert "KCHS" in ids
    assert "KSAV" in ids


def test_divert_coverage_per_sample_reach(airports):
    """Per-sample reach list — some samples have a smaller reach so
    they should see fewer airports."""
    samples = [(33.0635, -80.2795), (32.8986, -80.0405)]
    reaches = [5.0, 30.0]   # first sample very tight
    out = divert_coverage_along_route(samples, airports, reaches)
    assert len(out["per_sample"][0]) <= len(out["per_sample"][1])


def test_divert_coverage_no_airports_in_reach(airports):
    """Middle of the Atlantic at 1 NM reach should have zero coverage."""
    samples = [(30.0, -50.0), (30.5, -50.5)]
    out = divert_coverage_along_route(samples, airports, 1.0)
    assert out["unique_diverts"] == []
    assert out["n_samples_with_no_coverage"] == 2


def test_gap_segments_simple():
    samples = [(33.0, -80.0), (33.5, -80.0), (34.0, -80.0), (34.5, -80.0)]
    coverage = [["A"], [], [], ["B"]]
    gaps = gap_segments(samples, coverage)
    assert len(gaps) == 1
    assert gaps[0]["start_idx"] == 1
    assert gaps[0]["end_idx"] == 2
    assert gaps[0]["gap_nm"] > 0


def test_gap_segments_multiple():
    samples = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
    coverage = [[], ["A"], [], [], ["B"]]
    gaps = gap_segments(samples, coverage)
    assert len(gaps) == 2


def test_gap_segments_trailing_gap():
    samples = [(0, 0), (1, 0), (2, 0)]
    coverage = [["A"], [], []]
    gaps = gap_segments(samples, coverage)
    assert len(gaps) == 1
    assert gaps[0]["start_idx"] == 1
    assert gaps[0]["end_idx"] == 2


def test_gap_segments_no_gaps():
    samples = [(0, 0), (1, 0)]
    coverage = [["A"], ["B"]]
    assert gap_segments(samples, coverage) == []


def test_longest_gap_nm_empty():
    assert longest_gap_nm([]) == 0.0


def test_longest_gap_nm_max():
    gaps = [{"gap_nm": 5}, {"gap_nm": 22}, {"gap_nm": 10}]
    assert longest_gap_nm(gaps) == 22


# === Terrain-aware reach (Phase 7h) ==========================================

from core.diverts import (
    can_glide_to, find_diverts_in_glide,
    divert_coverage_along_route_glide,
)


def test_can_glide_to_short_no_terrain():
    """No terrain, plenty of altitude — should reach."""
    assert can_glide_to(
        33.0, -80.0, sample_msl_ft=5500.0,
        ap_lat=33.05, ap_lon=-80.05, ap_elev_ft=50.0,
        glide_ratio=10.0,
    ) is True


def test_can_glide_to_too_far_no_terrain():
    """100 NM target with only 5500 ft × 10:1 = ~9 NM still-air reach."""
    assert can_glide_to(
        33.0, -80.0, sample_msl_ft=5500.0,
        ap_lat=34.5, ap_lon=-80.0, ap_elev_ft=50.0,
        glide_ratio=10.0,
    ) is False


def test_can_glide_to_high_airport():
    """Airport elevation eats the AGL — can't reach even nearby."""
    assert can_glide_to(
        33.0, -80.0, sample_msl_ft=5500.0,
        ap_lat=33.05, ap_lon=-80.05, ap_elev_ft=5200.0,
        glide_ratio=10.0,
    ) is False


def test_can_glide_to_with_ridge_blocks():
    """Synthetic 10000 ft wall halfway → glide is blocked."""
    def elev_fn(lat, lon):
        # Wall between sample and airport (the eastern half)
        if lon > -80.05:
            return 10000.0 / 3.28084   # 10000 ft expressed in meters
        return 0.0
    blocked = can_glide_to(
        33.0, -80.1, sample_msl_ft=5500.0,
        ap_lat=33.0, ap_lon=-80.0, ap_elev_ft=50.0,
        glide_ratio=10.0,
        elevation_fn=elev_fn,
    )
    assert blocked is False


def test_can_glide_to_terrain_below_glide_clear():
    """Terrain at 500 ft, glide line is well above → reaches."""
    def elev_fn(lat, lon):
        return 500.0 / 3.28084
    ok = can_glide_to(
        33.0, -80.1, sample_msl_ft=5500.0,
        ap_lat=33.0, ap_lon=-80.05, ap_elev_ft=50.0,
        glide_ratio=10.0,
        elevation_fn=elev_fn,
    )
    assert ok is True


def test_can_glide_to_nan_terrain_does_not_block():
    """NaN elevation = unknown — fail-safe, treat as clear."""
    elev_fn = lambda lat, lon: float("nan")
    assert can_glide_to(
        33.0, -80.1, sample_msl_ft=5500.0,
        ap_lat=33.0, ap_lon=-80.05, ap_elev_ft=50.0,
        glide_ratio=10.0,
        elevation_fn=elev_fn,
    ) is True


def test_can_glide_to_tailwind_extends_reach():
    """A 20 kt tailwind toward the airport should make a marginal
    target reachable that fails in still air."""
    sample = (33.0, -80.0)
    # 11.5 NM north — slightly beyond still-air 9 NM (5500/10/6076 NM × FT)
    ap_lat, ap_lon = 33.19, -80.0
    no_wind = can_glide_to(
        *sample, sample_msl_ft=5500.0,
        ap_lat=ap_lat, ap_lon=ap_lon, ap_elev_ft=50.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        wind_dir_deg=0.0, wind_speed_kt=0.0,
    )
    with_tailwind = can_glide_to(
        *sample, sample_msl_ft=5500.0,
        ap_lat=ap_lat, ap_lon=ap_lon, ap_elev_ft=50.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        wind_dir_deg=180.0, wind_speed_kt=30.0,    # wind FROM south → tailwind north
    )
    assert no_wind is False
    assert with_tailwind is True


def test_find_diverts_in_glide_no_terrain(airports):
    """At 12000 ft with GR 10 the still-air reach is ~19.7 NM, so KCHS
    (~15.6 NM east of KDYB) is in glide; KSAV (~70 NM south) is not."""
    hits = find_diverts_in_glide(
        airports,
        sample_lat=33.0635, sample_lon=-80.2795,
        sample_msl_ft=12000.0,
        glide_ratio=10.0,
    )
    ids = [h["airport"]["id"] for h in hits]
    assert "KDYB" in ids
    assert "KCHS" in ids
    assert "KSAV" not in ids


def test_find_diverts_in_glide_too_low_misses_neighbors(airports):
    """At 5500 ft KCHS is past the still-air glide (~9 NM)."""
    hits = find_diverts_in_glide(
        airports,
        sample_lat=33.0635, sample_lon=-80.2795,
        sample_msl_ft=5500.0,
        glide_ratio=10.0,
    )
    ids = [h["airport"]["id"] for h in hits]
    assert "KDYB" in ids
    assert "KCHS" not in ids


def test_find_diverts_in_glide_ridge_blocks(airports):
    """A synthetic ridge between sample and KCHS blocks it; KDYB still
    reachable because it's at the sample point itself."""
    def ridge_fn(lat, lon):
        # Wall just east of sample
        if lon > -80.20:
            return 9000.0 / 3.28084
        return 0.0
    hits = find_diverts_in_glide(
        airports,
        sample_lat=33.0635, sample_lon=-80.2795,
        sample_msl_ft=5500.0,
        glide_ratio=10.0,
        elevation_fn=ridge_fn,
    )
    ids = [h["airport"]["id"] for h in hits]
    assert "KDYB" in ids        # at sample, no ray-march distance
    assert "KCHS" not in ids    # blocked by wall


def test_coverage_along_route_glide_terrain_used_flag(airports):
    samples = [(33.0635, -80.2795), (32.8986, -80.0405)]
    out = divert_coverage_along_route_glide(
        samples, airports,
        cruise_alt_msl_ft=5500.0, glide_ratio=10.0,
    )
    assert out["terrain_used"] is False
    out2 = divert_coverage_along_route_glide(
        samples, airports,
        cruise_alt_msl_ft=5500.0, glide_ratio=10.0,
        elevation_fn=lambda lat, lon: 0.0,
    )
    assert out2["terrain_used"] is True
    # With zero terrain, results should match the no-terrain path
    assert (sorted(d["airport"]["id"] for d in out["unique_diverts"])
            == sorted(d["airport"]["id"] for d in out2["unique_diverts"]))


def test_coverage_along_route_glide_zero_alt_empty(airports):
    samples = [(33.0635, -80.2795)]
    out = divert_coverage_along_route_glide(
        samples, airports,
        cruise_alt_msl_ft=0.0, glide_ratio=10.0,
    )
    assert out["unique_diverts"] == []
