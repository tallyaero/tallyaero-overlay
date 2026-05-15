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
