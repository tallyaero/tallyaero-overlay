"""Route math tests.

Distances + initial bearings checked against published great-circle
references; wind triangle checked against analytic round-numbers
(pure headwind, pure tailwind, pure 90° crosswind).
"""
from __future__ import annotations

import math

import pytest

from core.route import (
    haversine_nm,
    initial_bearing_deg,
    wind_triangle,
    true_to_magnetic,
    compute_route_segment,
)
from core.schema import RouteInput, RouteResult


# ── Reference airports (lat, lon) from the shared airports.json ───────
KJFK = (40.6398, -73.7789)
KLAX = (33.9425, -118.4081)
KSFO = (37.6189, -122.3750)
KORD = (41.9786, -87.9048)
KDYB = (33.0635, -80.2795)   # Summerville, SC (in-state test)
KSAV = (32.1276, -81.2021)   # Savannah, GA — ~80 NM from KDYB


# ── haversine_nm ───────────────────────────────────────────────────────


def test_haversine_jfk_to_lax():
    """KJFK → KLAX is ~2145 NM (FAA AIM / great-circle calculator)."""
    nm = haversine_nm(*KJFK, *KLAX)
    assert 2140 < nm < 2150, f"expected ~2145 NM, got {nm:.1f}"


def test_haversine_sfo_to_ord():
    """KSFO → KORD is ~1600 NM."""
    nm = haversine_nm(*KSFO, *KORD)
    assert 1590 < nm < 1610, f"expected ~1600 NM, got {nm:.1f}"


def test_haversine_short_leg():
    """KDYB → KSAV (in-state, ~73 NM)."""
    nm = haversine_nm(*KDYB, *KSAV)
    assert 70 < nm < 80, f"expected ~73 NM, got {nm:.1f}"


def test_haversine_zero_when_same():
    assert haversine_nm(*KJFK, *KJFK) == 0.0


# ── initial_bearing_deg ────────────────────────────────────────────────


def test_bearing_jfk_to_lax_westerly():
    """JFK → LAX is roughly westbound. Initial bearing ~273°."""
    brg = initial_bearing_deg(*KJFK, *KLAX)
    assert 270 < brg < 280, f"expected ~273°, got {brg:.1f}"


def test_bearing_north():
    """Due north — destination at +5° lat, same lon."""
    brg = initial_bearing_deg(40.0, -100.0, 45.0, -100.0)
    assert abs(brg) < 0.5 or abs(brg - 360) < 0.5


def test_bearing_east():
    """Due east near the equator — within ~0.5°."""
    brg = initial_bearing_deg(0.0, 0.0, 0.0, 5.0)
    assert abs(brg - 90.0) < 0.5


def test_bearing_wrap_0_to_360():
    """Bearing is always in [0, 360)."""
    brg = initial_bearing_deg(0.0, 0.0, 0.0, -5.0)
    assert 0 <= brg < 360


# ── wind_triangle ──────────────────────────────────────────────────────


def test_wind_triangle_no_wind():
    th, gs = wind_triangle(120.0, 90.0, 0.0, 0.0)
    assert abs(th - 90.0) < 1e-6
    assert abs(gs - 120.0) < 1e-6


def test_wind_triangle_pure_headwind():
    """Wind FROM 090 at 30 kt, flying 090 TC at 120 KTAS → GS 90, TH 090."""
    th, gs = wind_triangle(120.0, 90.0, 90.0, 30.0)
    assert abs(th - 90.0) < 0.5
    assert abs(gs - 90.0) < 0.5


def test_wind_triangle_pure_tailwind():
    """Wind FROM 270 at 30 kt, flying 090 TC at 120 KTAS → GS 150, TH 090."""
    th, gs = wind_triangle(120.0, 90.0, 270.0, 30.0)
    assert abs(th - 90.0) < 0.5
    assert abs(gs - 150.0) < 0.5


def test_wind_triangle_crosswind():
    """Wind FROM 180 at 30 kt, flying 090 TC at 120 KTAS → crab left,
    GS slightly less than TAS due to wind-cor component."""
    th, gs = wind_triangle(120.0, 90.0, 180.0, 30.0)
    # WCA = asin(30/120) = ~14.48° → TH = 090 - 14.48 = 75.5° (crab into wind)
    # Wait: wind FROM 180 (south) blows toward 360 — pushes plane north.
    # Flying TC 090 with northbound push means we crab south (TH > 090).
    assert th > 90.0, f"expected TH > 90 (crab into wind), got {th:.2f}"
    assert th < 110.0
    assert 110 < gs < 120


# ── true_to_magnetic ───────────────────────────────────────────────────


def test_magnetic_west_variation_positive():
    """East-coast US: ~13°W variation. TC 360 → MC 013."""
    mc = true_to_magnetic(360.0, 13.0)
    assert abs(mc - 13.0) < 1e-6


def test_magnetic_east_variation_negative():
    """West-coast US: ~14°E variation (negative under W-positive convention).
    TC 360 → MC 346."""
    mc = true_to_magnetic(360.0, -14.0)
    assert abs(mc - 346.0) < 1e-6


def test_magnetic_wraps():
    mc = true_to_magnetic(355.0, 10.0)
    assert abs(mc - 5.0) < 1e-6


# ── compute_route_segment integration ──────────────────────────────────


def test_compute_route_segment_short_leg():
    """KDYB → KSAV with 120 KTAS, 5 kt headwind at 220°, ~13°W var."""
    r = compute_route_segment(
        *KDYB, *KSAV,
        tas_kt=120.0,
        wind_dir_deg=220.0,
        wind_speed_kt=5.0,
        magvar_deg=13.0,
        fuel_burn_gph=8.5,
    )
    assert 70 < r.distance_nm < 80
    assert 200 < r.true_course_deg < 250          # generally SW
    assert r.magnetic_course_deg != r.true_course_deg  # var applied
    assert 100 < r.ground_speed_kt < 125          # slight tailwind component
    assert r.ete_min > 0
    assert r.fuel_burn_gal is not None
    assert r.fuel_burn_gal > 0


def test_compute_route_segment_no_fuel():
    r = compute_route_segment(*KDYB, *KSAV, tas_kt=120.0)
    assert r.fuel_burn_gal is None


# ── Pydantic schemas ──────────────────────────────────────────────────


def test_route_input_validates():
    inp = RouteInput(
        origin_airport_id="KJFK",
        dest_airport_id="KLAX",
        cruise_alt_ft=8000,
        tas_kt=120,
        wind_dir_deg=270,
        wind_speed_kt=15,
        fuel_burn_gph=8.5,
    )
    assert inp.origin_airport_id == "KJFK"


def test_route_input_rejects_bad_tas():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RouteInput(
            origin_airport_id="KJFK", dest_airport_id="KLAX",
            cruise_alt_ft=8000, tas_kt=0,
        )


def test_route_result_roundtrip():
    r = RouteResult(
        origin_airport_id="KJFK", dest_airport_id="KLAX",
        origin_lat=KJFK[0], origin_lon=KJFK[1],
        dest_lat=KLAX[0], dest_lon=KLAX[1],
        distance_nm=2145.0,
        true_course_deg=273.0, magnetic_course_deg=286.0,
        true_heading_deg=273.0, magnetic_heading_deg=286.0,
        ground_speed_kt=120.0, ete_min=1072.5,
        fuel_burn_gal=151.8,
        magvar_deg=13.0,
    )
    assert r.distance_nm == 2145.0
    # JSON round-trip
    data = r.model_dump()
    r2 = RouteResult(**data)
    assert r == r2
