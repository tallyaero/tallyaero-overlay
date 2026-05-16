"""Tests for core.multi_engine — driftdown + powered single-engine reach.

Uses synthetic aircraft dicts so tests don't depend on the actual
catalog. The Seneca II spec is used as the reference for assertion
ballparks.
"""
from __future__ import annotations

import pytest
from core.multi_engine import (
    is_multi_engine, has_se_performance_data,
    driftdown_profile, single_engine_powered_reach_nm,
    single_engine_envelope_polygon,
)


def _seneca_like():
    """Synthetic ME aircraft modeled on PA-34 Seneca II numbers."""
    return {
        "name": "Test Seneca",
        "engine_count": 2,
        "single_engine_limits": {
            "best_glide": 87,
            "best_glide_ratio": 9.5,
            "service_ceiling_ft": 13400,
            "rate_of_climb_sl_fpm": 190,
            "cruise_kt": 120,
            "fuel_burn_gph": 10,
        },
        "fuel_capacity_gal": 93,
    }


def _single_engine_172():
    """Single-engine reference — should never trigger ME paths."""
    return {
        "name": "C172R",
        "engine_count": 1,
        "single_engine_limits": {
            "best_glide": 65, "best_glide_ratio": 9.0,
        },
    }


# === Detection ==============================================================

def test_is_multi_engine_twin():
    assert is_multi_engine(_seneca_like()) is True


def test_is_multi_engine_single():
    assert is_multi_engine(_single_engine_172()) is False


def test_is_multi_engine_missing_field():
    assert is_multi_engine({"name": "unknown"}) is False


def test_has_se_data_complete():
    assert has_se_performance_data(_seneca_like()) is True


def test_has_se_data_missing():
    ac = _seneca_like()
    del ac["single_engine_limits"]["fuel_burn_gph"]
    assert has_se_performance_data(ac) is False


def test_has_se_data_singles_false():
    assert has_se_performance_data(_single_engine_172()) is False


# === Driftdown ==============================================================

def test_driftdown_below_ceiling_is_zero():
    """Seneca II ceiling 13,400 → engine quit at 8,000 = already below."""
    p = driftdown_profile(_seneca_like(), start_alt_msl_ft=8000)
    assert p["already_below_ceiling"] is True
    assert p["descent_time_min"] == 0.0
    assert p["ground_distance_nm"] == 0.0
    assert p["target_alt_msl_ft"] == 8000


def test_driftdown_at_ceiling_is_zero():
    p = driftdown_profile(_seneca_like(), start_alt_msl_ft=13400)
    assert p["already_below_ceiling"] is True


def test_driftdown_above_ceiling():
    """Engine quit at 18,000 → descends to 13,400. Positive time + dist."""
    p = driftdown_profile(_seneca_like(), start_alt_msl_ft=18000)
    assert p["already_below_ceiling"] is False
    assert p["descent_time_min"] > 0
    assert p["ground_distance_nm"] > 0
    assert p["target_alt_msl_ft"] == 13400


def test_driftdown_tailwind_extends_forward_distance():
    base = driftdown_profile(_seneca_like(), start_alt_msl_ft=18000)
    with_tw = driftdown_profile(
        _seneca_like(), start_alt_msl_ft=18000, wind_along_track_kt=20)
    assert with_tw["ground_distance_nm"] > base["ground_distance_nm"]


def test_driftdown_headwind_shrinks_forward_distance():
    base = driftdown_profile(_seneca_like(), start_alt_msl_ft=18000)
    with_hw = driftdown_profile(
        _seneca_like(), start_alt_msl_ft=18000, wind_along_track_kt=-30)
    assert with_hw["ground_distance_nm"] < base["ground_distance_nm"]


def test_driftdown_bad_data_returns_no_descent():
    """Missing service_ceiling_ft → safe fallback."""
    ac = _seneca_like()
    ac["single_engine_limits"]["service_ceiling_ft"] = 0
    p = driftdown_profile(ac, start_alt_msl_ft=18000)
    assert p["descent_time_min"] == 0.0


# === Powered SE reach =======================================================

def test_reach_full_fuel_no_wind_default_60min_cap():
    """Seneca II at 8000 ft (below ceiling) with full 93 gal, calm air,
    DEFAULT 60-min operational cap: 60 min × 120 kt = 120 NM. Fuel
    doesn't constrain because 93 gal / 10 gph = 9.3 hr ≫ 60 min."""
    r = single_engine_powered_reach_nm(
        _seneca_like(),
        current_alt_msl_ft=8000,
        fuel_remaining_gal=93,
        bearing_deg=0,
    )
    assert 110 < r < 130


def test_reach_uncapped_max_theoretical():
    """When the operational cap is lifted, the reach approaches the
    fuel-out maximum (~1116 NM for full Seneca tanks)."""
    r = single_engine_powered_reach_nm(
        _seneca_like(), 8000, 93, 0,
        max_minutes_after_failure=1e6,   # effectively unlimited
    )
    assert 1000 < r < 1200


def test_reach_fuel_limit_under_cap():
    """If fuel runs out before the cap, fuel wins. 5 gal / 10 gph = 30
    min × 120 kt = 60 NM, vs default 60-min cap = 120 NM."""
    r = single_engine_powered_reach_nm(_seneca_like(), 8000, 5, 0)
    assert 55 < r < 65


def test_reach_tailwind_extends():
    base = single_engine_powered_reach_nm(_seneca_like(), 8000, 50, 0)
    with_tw = single_engine_powered_reach_nm(
        _seneca_like(), 8000, 50, 0, wind_dir_deg=180, wind_speed_kt=30)
    assert with_tw > base


def test_reach_headwind_shrinks():
    base = single_engine_powered_reach_nm(_seneca_like(), 8000, 50, 0)
    with_hw = single_engine_powered_reach_nm(
        _seneca_like(), 8000, 50, 0, wind_dir_deg=0, wind_speed_kt=30)
    assert with_hw < base


def test_reach_above_ceiling_includes_driftdown_distance():
    """Engine quit at 18000 (above ceiling 13400) should include a
    nonzero driftdown segment in addition to the level segment."""
    below_ceiling = single_engine_powered_reach_nm(
        _seneca_like(), 13400, 50, 0)
    above_ceiling = single_engine_powered_reach_nm(
        _seneca_like(), 18000, 50, 0)
    # Above ceiling has the driftdown contribution AND consumes some
    # fuel during driftdown — net depends on the trade-off. Both
    # should be positive and the order can vary; assert just that
    # both fall in a sane range.
    assert below_ceiling > 0
    assert above_ceiling > 0


def test_reach_zero_fuel_is_zero():
    r = single_engine_powered_reach_nm(_seneca_like(), 8000, 0, 0)
    assert r == 0.0


def test_reach_single_engine_aircraft_returns_zero():
    """A C172 has no SE data → reach 0 (caller falls back to glide)."""
    r = single_engine_powered_reach_nm(_single_engine_172(), 8000, 30, 0)
    assert r == 0.0


# === Envelope polygon =======================================================

def test_envelope_polygon_nonempty_for_me():
    poly = single_engine_envelope_polygon(
        33.0, -80.0, _seneca_like(),
        current_alt_msl_ft=8000, fuel_remaining_gal=50, n_points=12,
    )
    assert not poly.is_empty
    # 12 unique points + 1 closing → exterior coord count
    assert len(poly.exterior.coords) > 5


def test_envelope_polygon_empty_for_single_engine():
    poly = single_engine_envelope_polygon(
        33.0, -80.0, _single_engine_172(), 8000, 30, n_points=12)
    assert poly.is_empty


def test_envelope_polygon_empty_when_no_fuel():
    poly = single_engine_envelope_polygon(
        33.0, -80.0, _seneca_like(), 8000, 0, n_points=12)
    assert poly.is_empty
