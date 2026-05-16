"""Tests for core.waypoints — GPS parser, resolve_any, nearest snap."""
from __future__ import annotations

import pytest
from core.waypoints import (
    parse_gps_coordinate, format_gps_ident, format_gps_display,
    gps_to_waypoint, resolve_any, nearest_airport_within,
    Waypoint,
)


# === GPS parser =============================================================

def test_parse_plain_decimal():
    r = parse_gps_coordinate("33.0635,-80.2795")
    assert r is not None
    lat, lon = r
    assert abs(lat - 33.0635) < 1e-4 and abs(lon + 80.2795) < 1e-4


def test_parse_plain_decimal_with_space():
    r = parse_gps_coordinate("33.0635, -80.2795")
    assert r is not None
    assert abs(r[0] - 33.0635) < 1e-4


def test_parse_hemisphere_decimal():
    r = parse_gps_coordinate("N33.0635 W80.2795")
    assert r is not None
    lat, lon = r
    assert abs(lat - 33.0635) < 1e-4 and abs(lon + 80.2795) < 1e-4


def test_parse_hemisphere_south_east():
    r = parse_gps_coordinate("S33.5 E120.5")
    assert r == (-33.5, 120.5)


def test_parse_dms():
    """N33°03'48.6\" W80°16'46.2\" → ~33.0635, -80.2795"""
    r = parse_gps_coordinate("N33°03'48.6\" W80°16'46.2\"")
    assert r is not None
    lat, lon = r
    assert abs(lat - 33.0635) < 0.001
    assert abs(lon + 80.2795) < 0.001


def test_parse_ddm():
    """N33°03.81' W80°16.77' → ~33.0635, -80.2795 (decimal min)"""
    r = parse_gps_coordinate("N33°03.81' W80°16.77'")
    assert r is not None
    lat, lon = r
    assert abs(lat - 33.0635) < 0.001
    assert abs(lon + 80.2795) < 0.001


def test_parse_arinc_shorthand():
    """N3303.81/W08016.77 (ARINC 424 / GPS-shorthand) → ~33.0635, -80.2795"""
    r = parse_gps_coordinate("N3303.81/W08016.77")
    assert r is not None
    lat, lon = r
    assert abs(lat - 33.0635) < 0.001
    assert abs(lon + 80.2795) < 0.001


def test_parse_canonical_internal():
    """GPS:33.0635,-80.2795 round-trips through the internal format."""
    r = parse_gps_coordinate("GPS:33.0635,-80.2795")
    assert r == (33.0635, -80.2795)


def test_parse_invalid_returns_none():
    assert parse_gps_coordinate("KJFK") is None
    assert parse_gps_coordinate("") is None
    assert parse_gps_coordinate("not a coord") is None
    assert parse_gps_coordinate(None) is None


def test_parse_out_of_range_rejected():
    """Lat > 90 or lon > 180 → reject."""
    assert parse_gps_coordinate("91.0,-80.0") is None
    assert parse_gps_coordinate("33.0,-181.0") is None


def test_parse_zero_zero_rejected():
    """Plain '0.0,0.0' could be a confused airport code — reject."""
    assert parse_gps_coordinate("0.0,0.0") is None


# === Format round-trip ======================================================

def test_format_ident_parses_back():
    ident = format_gps_ident(33.0635, -80.2795)
    assert ident == "GPS:33.0635,-80.2795"
    parsed = parse_gps_coordinate(ident)
    assert parsed == (33.0635, -80.2795)


def test_format_display_human_readable():
    s = format_gps_display(33.0635, -80.2795)
    assert "33" in s and "80" in s and "N" in s and "W" in s


def test_format_display_south_east():
    s = format_gps_display(-33.5, 120.5)
    assert "S" in s and "E" in s


# === resolve_any ============================================================

@pytest.fixture
def sample_airports():
    return [
        {"id": "KDYB", "icao": "KDYB", "local": "DYB",
         "name": "Summerville Airport", "lat": 33.0635, "lon": -80.2795,
         "type": "small_airport"},
        {"id": "KSAV", "icao": "KSAV", "iata": "SAV",
         "name": "Savannah Hilton Head Intl",
         "lat": 32.1276, "lon": -81.2021,
         "type": "medium_airport"},
    ]


def test_resolve_any_airport_exact(sample_airports):
    wp = resolve_any("KDYB", airport_data=sample_airports)
    assert wp is not None
    assert wp.kind == "airport"
    assert wp.ident == "KDYB"


def test_resolve_any_gps_coord(sample_airports):
    wp = resolve_any("33.0,-80.0", airport_data=sample_airports)
    assert wp is not None
    assert wp.kind == "gps"
    assert abs(wp.lat - 33.0) < 1e-4


def test_resolve_any_internal_gps_format(sample_airports):
    wp = resolve_any("GPS:33.5,-80.5", airport_data=sample_airports)
    assert wp is not None
    assert wp.kind == "gps"
    assert wp.lat == 33.5 and wp.lon == -80.5


def test_resolve_any_unknown_returns_none(sample_airports):
    wp = resolve_any("XXXXX", airport_data=sample_airports)
    assert wp is None


def test_resolve_any_navaid_when_data_supplied():
    """Future-compatibility check — resolve_any accepts navaid_data and
    falls through to it when airport doesn't match."""
    navaids = [{"ident": "SAV", "lat": 32.1, "lon": -81.2,
                "name": "Savannah VOR", "freq_mhz": 115.95}]
    wp = resolve_any("SAV", airport_data=[], navaid_data=navaids)
    assert wp is not None
    assert wp.kind == "vor"
    assert wp.ident == "SAV"


# === nearest_airport_within (click snap) ====================================

def test_snap_finds_exact(sample_airports):
    """Click directly on KDYB → snap to KDYB."""
    snapped = nearest_airport_within(
        sample_airports, 33.0635, -80.2795, max_nm=3)
    assert snapped is not None
    assert snapped["id"] == "KDYB"


def test_snap_finds_nearest_within_radius(sample_airports):
    """Click 1 NM north of KDYB → still snaps to KDYB."""
    snapped = nearest_airport_within(
        sample_airports, 33.08, -80.2795, max_nm=3)
    assert snapped is not None
    assert snapped["id"] == "KDYB"


def test_snap_misses_outside_radius(sample_airports):
    """Click 100 NM out from any airport → no snap."""
    snapped = nearest_airport_within(
        sample_airports, 35.0, -75.0, max_nm=3)
    assert snapped is None


def test_snap_picks_nearer_of_two(sample_airports):
    """Click between KDYB and KSAV, closer to KSAV → picks KSAV."""
    snapped = nearest_airport_within(
        sample_airports, 32.2, -81.0, max_nm=20)
    assert snapped is not None
    assert snapped["id"] == "KSAV"


def test_snap_zero_radius_no_match(sample_airports):
    snapped = nearest_airport_within(
        sample_airports, 33.0635, -80.2795, max_nm=0)
    assert snapped is None


def test_waypoint_to_dict_min_shape():
    """to_dict_min produces the legacy airport-dict shape."""
    wp = Waypoint(kind="gps", ident="GPS:33.5,-80.5",
                  lat=33.5, lon=-80.5)
    d = wp.to_dict_min()
    assert d["id"] == "GPS:33.5,-80.5"
    assert d["lat"] == 33.5 and d["lon"] == -80.5
    assert d["kind"] == "gps"
