"""Glide corridor tests — envelope geometry + route sampling + union."""
from __future__ import annotations

import math

from core.corridor import (
    glide_envelope_polygon,
    sample_route_points,
    compute_route_corridor,
    _offset_latlon,
)


# Reference airports
KDYB = (33.0635, -80.2795)
KSAV = (32.1276, -81.2021)
KJFK = (40.6398, -73.7789)
KLAX = (33.9425, -118.4081)


def test_offset_zero_distance():
    """Offset by zero returns the same point."""
    lat, lon = _offset_latlon(40.0, -80.0, 90.0, 0.0)
    assert abs(lat - 40.0) < 1e-9
    assert abs(lon - (-80.0)) < 1e-9


def test_offset_east_1nm():
    """East offset by 1 NM moves longitude by ~1/(60·cos(lat)) deg."""
    lat, lon = _offset_latlon(40.0, -80.0, 90.0, 1.0)
    expected_dlon = 1.0 / (60.0 * math.cos(math.radians(40.0)))
    assert abs(lat - 40.0) < 0.001
    assert abs((lon + 80.0) - expected_dlon) < 0.001


def test_envelope_still_air_circular():
    """No wind → envelope is ~circular, all radii close to still-air glide."""
    agl = 5000.0
    gr = 10.0
    expected_nm = (agl * gr) / 6076.115   # ~8.23 NM
    poly = glide_envelope_polygon(33.0, -80.0, agl, gr, glide_ias_kt=75.0,
                                   wind_dir_deg=0.0, wind_speed_kt=0.0,
                                   n_points=36)
    # Each vertex should sit ~ expected_nm from the center
    # Convert each vertex back to NM via haversine
    from core.route import haversine_nm
    xs = list(poly.exterior.coords)
    for lon, lat in xs[:-1]:
        d = haversine_nm(33.0, -80.0, lat, lon)
        assert abs(d - expected_nm) < 0.5, f"got {d:.2f}, expected {expected_nm:.2f}"


def test_envelope_zero_agl_empty():
    poly = glide_envelope_polygon(33.0, -80.0, 0.0, 10.0)
    assert poly.is_empty


def test_envelope_wind_elongates_downwind():
    """Wind FROM west (270°) makes the eastern reach larger than western."""
    poly = glide_envelope_polygon(33.0, -80.0, 5000.0, 10.0,
                                   glide_ias_kt=75.0,
                                   wind_dir_deg=270.0, wind_speed_kt=20.0,
                                   n_points=72)
    # East vertex (heading 90°) and west vertex (heading 270°)
    from core.route import haversine_nm
    coords = list(poly.exterior.coords)[:-1]
    # Find points closest to due-east and due-west
    east_dists = []
    west_dists = []
    for lon, lat in coords:
        if lon > -80.0:
            east_dists.append(haversine_nm(33.0, -80.0, lat, lon))
        else:
            west_dists.append(haversine_nm(33.0, -80.0, lat, lon))
    east_max = max(east_dists)
    west_max = max(west_dists)
    assert east_max > west_max, f"east {east_max:.2f} should beat west {west_max:.2f}"


def test_sample_route_short_leg():
    """KDYB → KSAV (~73 NM) sampled at 5 NM should give ~15 points."""
    pts = sample_route_points(*KDYB, *KSAV, spacing_nm=5.0)
    assert 14 <= len(pts) <= 16
    # Endpoints
    assert abs(pts[0][0] - KDYB[0]) < 0.01
    assert abs(pts[0][1] - KDYB[1]) < 0.01
    assert abs(pts[-1][0] - KSAV[0]) < 0.01
    assert abs(pts[-1][1] - KSAV[1]) < 0.01


def test_sample_route_min_two():
    """Even zero-length leg still returns at least 2 points."""
    pts = sample_route_points(*KDYB, *KDYB, spacing_nm=1.0)
    assert len(pts) >= 2


def test_corridor_short_leg_renders_polygon():
    """KDYB → KSAV at 5500 MSL with a 10:1 glide → corridor is a tube
    along the route, single exterior ring."""
    rings, meta = compute_route_corridor(
        *KDYB, *KSAV,
        cruise_alt_msl_ft=5500.0, field_elev_ft=55.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        wind_dir_deg=0.0, wind_speed_kt=0.0,
        spacing_nm=2.0,
    )
    assert len(rings) >= 1
    assert len(rings[0]) > 10
    assert meta["n_samples"] > 10
    assert meta["narrowest_nm"] > 0
    assert meta["agl_ft"] == round(5500.0 - 55.0, 0)


def test_corridor_zero_alt_empty():
    rings, meta = compute_route_corridor(
        *KDYB, *KSAV,
        cruise_alt_msl_ft=0.0, field_elev_ft=55.0,
        glide_ratio=10.0,
    )
    assert rings == []
    assert meta["n_samples"] == 0 or meta["narrowest_nm"] == 0.0


def test_corridor_headwind_narrower_than_no_wind():
    """A 30 kt headwind should reduce the narrowest dimension."""
    _, calm = compute_route_corridor(
        *KDYB, *KSAV,
        cruise_alt_msl_ft=5500.0, field_elev_ft=55.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        wind_dir_deg=0.0, wind_speed_kt=0.0,
        spacing_nm=5.0,
    )
    _, windy = compute_route_corridor(
        *KDYB, *KSAV,
        cruise_alt_msl_ft=5500.0, field_elev_ft=55.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        wind_dir_deg=180.0, wind_speed_kt=30.0,    # tailwind on a southwest leg
        spacing_nm=5.0,
    )
    # With wind, narrowest is smaller than calm
    assert windy["narrowest_nm"] < calm["narrowest_nm"]
