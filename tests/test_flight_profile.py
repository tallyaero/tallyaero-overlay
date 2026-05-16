"""Tests for core.flight_profile."""
from __future__ import annotations

import pytest
from core.flight_profile import (
    climb_rate_fpm, class_baseline_climb_rate,
    compute_flight_profile, altitude_at_distance,
)


def test_baseline_piston_single():
    ac = {"type": "small_airport", "engine_count": 1}   # type wrong field but proxy
    # We actually key on aircraft type. Let's pass aircraft-style data.
    ac2 = {"engine_count": 1}
    assert class_baseline_climb_rate(ac2) == 700.0


def test_baseline_piston_twin():
    ac = {"engine_count": 2}
    assert class_baseline_climb_rate(ac) == 1000.0


def test_baseline_turboprop():
    ac = {"type": "turboprop"}
    assert class_baseline_climb_rate(ac) == 1500.0


def test_baseline_jet():
    ac = {"type": "jet"}
    assert class_baseline_climb_rate(ac) == 2000.0


def test_climb_rate_at_vy_is_full_baseline():
    assert climb_rate_fpm(76, vy_kt=76, vno_kt=129, baseline_fpm=700) == 700


def test_climb_rate_at_vno_is_zero():
    assert climb_rate_fpm(129, vy_kt=76, vno_kt=129, baseline_fpm=700) == 0


def test_climb_rate_above_vno_clamps_to_zero():
    assert climb_rate_fpm(200, vy_kt=76, vno_kt=129, baseline_fpm=700) == 0


def test_climb_rate_below_vy_near_baseline():
    """Vx is typically close to Vy in climb rate; we return 95% baseline."""
    r = climb_rate_fpm(60, vy_kt=76, vno_kt=129, baseline_fpm=700)
    assert 600 <= r <= 700


def test_climb_rate_midpoint():
    """At halfway between Vy and Vno, parabolic gives 0.75 × baseline."""
    midpoint = (76 + 129) / 2
    r = climb_rate_fpm(midpoint, vy_kt=76, vno_kt=129, baseline_fpm=700)
    # frac = 0.5 → 1 - 0.25 = 0.75
    assert abs(r - 525) < 5


def test_climb_rate_at_typical_c172_cruise_climb():
    """C172R cruise-climb 100 KIAS realistic — should be 500-600 fpm."""
    r = climb_rate_fpm(100, vy_kt=76, vno_kt=129, baseline_fpm=700)
    assert 500 <= r <= 600


# === Flight profile ==========================================================

def test_profile_normal_cruise_segment():
    """200 NM at 5500 ft / 700 fpm climb / 110 TAS: cruise segment exists."""
    p = compute_flight_profile(
        field_dep_ft=50.0, field_dest_ft=50.0,
        cruise_alt_msl_ft=5500.0,
        total_route_nm=200.0,
        climb_ias_kt=76.0, climb_rate_fpm=700.0,
        cruise_tas_kt=110.0,
    )
    # Climb: 5450 ft / 700 fpm = 7.79 min × 76 kt / 60 = ~9.86 NM
    # Descent at 3°: 5450 ft × 3.14 NM/1000ft = ~17.1 NM
    # cruise = 200 - 9.86 - 17.1 ≈ 173 NM
    assert p.has_cruise is True
    assert 9.0 <= p.d_toc_nm <= 11.0
    assert 180.0 <= p.d_tod_nm <= 185.0
    assert p.actual_cruise_alt_msl_ft == 5500.0


def test_profile_short_route_no_cruise():
    """20 NM route at 5500 ft target — can't reach cruise."""
    p = compute_flight_profile(
        field_dep_ft=50.0, field_dest_ft=50.0,
        cruise_alt_msl_ft=5500.0,
        total_route_nm=20.0,
        climb_ias_kt=76.0, climb_rate_fpm=700.0,
        cruise_tas_kt=110.0,
    )
    assert p.has_cruise is False
    assert p.actual_cruise_alt_msl_ft < 5500.0
    assert p.actual_cruise_alt_msl_ft > 50.0
    # TOC == TOD
    assert abs(p.d_toc_nm - p.d_tod_nm) < 0.1


def test_profile_altitude_at_endpoints():
    p = compute_flight_profile(
        field_dep_ft=100.0, field_dest_ft=80.0,
        cruise_alt_msl_ft=6000.0,
        total_route_nm=300.0,
        climb_ias_kt=80.0, climb_rate_fpm=750.0,
        cruise_tas_kt=120.0,
    )
    assert altitude_at_distance(0.0, p) == 100.0   # at departure field
    assert abs(altitude_at_distance(300.0, p) - 80.0) < 1e-3   # at dest


def test_profile_altitude_at_cruise():
    """Mid-route should be at cruise altitude."""
    p = compute_flight_profile(
        field_dep_ft=50.0, field_dest_ft=50.0,
        cruise_alt_msl_ft=6000.0,
        total_route_nm=200.0,
        climb_ias_kt=76.0, climb_rate_fpm=700.0,
        cruise_tas_kt=110.0,
    )
    mid = altitude_at_distance(100.0, p)
    assert mid == 6000.0


def test_profile_altitude_during_climb_increases():
    p = compute_flight_profile(
        field_dep_ft=50.0, field_dest_ft=50.0,
        cruise_alt_msl_ft=5500.0,
        total_route_nm=200.0,
        climb_ias_kt=76.0, climb_rate_fpm=700.0,
        cruise_tas_kt=110.0,
    )
    a1 = altitude_at_distance(1.0, p)
    a2 = altitude_at_distance(5.0, p)
    assert a2 > a1
    assert a1 >= 50.0


def test_profile_altitude_during_descent_decreases():
    p = compute_flight_profile(
        field_dep_ft=50.0, field_dest_ft=50.0,
        cruise_alt_msl_ft=5500.0,
        total_route_nm=200.0,
        climb_ias_kt=76.0, climb_rate_fpm=700.0,
        cruise_tas_kt=110.0,
    )
    a_late1 = altitude_at_distance(190.0, p)
    a_late2 = altitude_at_distance(199.0, p)
    assert a_late2 < a_late1
    assert a_late2 >= p.field_dest_ft - 1e-3


def test_profile_higher_climb_rate_means_earlier_toc():
    """Faster climber reaches cruise sooner — closer to departure."""
    base = dict(
        field_dep_ft=50.0, field_dest_ft=50.0,
        cruise_alt_msl_ft=5500.0,
        total_route_nm=200.0,
        climb_ias_kt=76.0,
        cruise_tas_kt=110.0,
    )
    slow = compute_flight_profile(**base, climb_rate_fpm=500.0)
    fast = compute_flight_profile(**base, climb_rate_fpm=1500.0)
    assert fast.d_toc_nm < slow.d_toc_nm


def test_profile_to_dict_round_trip():
    """to_dict() output is JSON-safe (no dataclass, just primitives)."""
    p = compute_flight_profile(
        field_dep_ft=50.0, field_dest_ft=50.0,
        cruise_alt_msl_ft=5500.0,
        total_route_nm=200.0,
        climb_ias_kt=76.0, climb_rate_fpm=700.0,
        cruise_tas_kt=110.0,
    )
    d = p.to_dict()
    import json
    s = json.dumps(d)
    assert "d_toc_nm" in s and "actual_cruise_alt_msl_ft" in s
