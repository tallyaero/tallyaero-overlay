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
    poly, n_clipped = glide_envelope_polygon(
        33.0, -80.0, agl, gr, glide_ias_kt=75.0,
        wind_dir_deg=0.0, wind_speed_kt=0.0, n_points=36)
    assert n_clipped == 0
    # Each vertex should sit ~ expected_nm from the center
    # Convert each vertex back to NM via haversine
    from core.route import haversine_nm
    xs = list(poly.exterior.coords)
    for lon, lat in xs[:-1]:
        d = haversine_nm(33.0, -80.0, lat, lon)
        assert abs(d - expected_nm) < 0.5, f"got {d:.2f}, expected {expected_nm:.2f}"


def test_envelope_zero_agl_empty():
    poly, n_clipped = glide_envelope_polygon(33.0, -80.0, 0.0, 10.0)
    assert poly.is_empty
    assert n_clipped == 0


def test_envelope_wind_elongates_downwind():
    """Wind FROM west (270°) makes the eastern reach larger than western."""
    poly, _ = glide_envelope_polygon(33.0, -80.0, 5000.0, 10.0,
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


# === Phase 7d terrain-aware tests ============================================

from core.corridor import terrain_intercept_nm, M_PER_FT


def flat_elev_m(level_m: float):
    """Build an elevation_fn that returns a constant — synthetic flat ground."""
    return lambda lat, lon: level_m


def east_wall_elev_m(lat_center: float, lon_center: float,
                    wall_lon_offset: float, wall_height_m: float):
    """Synthetic terrain: zero everywhere except east of the route point,
    where it's a wall at wall_height_m. Used to verify ridge clipping
    pinches the eastern reach."""
    def fn(lat, lon):
        return wall_height_m if lon > (lon_center + wall_lon_offset) else 0.0
    return fn


def test_terrain_intercept_flat_ground_no_clip():
    """Over flat sea-level terrain with 5500 ft altitude, the glide
    line never hits the ground within 50 NM — returns max_nm."""
    elev = flat_elev_m(0.0)
    d = terrain_intercept_nm(
        lat=33.0, lon=-80.0, bearing_deg=90.0,
        cruise_alt_msl_ft=5500.0,
        effective_glide_ratio=10.0,
        elevation_fn=elev,
        max_nm=8.0,
        step_nm=0.25,
    )
    # 5500 ft × GR 10 = 55000 ft glide ≈ 9.05 NM. 8 NM cap → returns 8.
    assert d == 8.0


def test_terrain_intercept_immediate_wall():
    """If terrain at the very first step exceeds the glide line,
    the ray-march clips immediately (returns 0 or last_clear=0)."""
    # 100m-tall wall starting immediately east of origin
    elev = east_wall_elev_m(33.0, -80.0, wall_lon_offset=0.0, wall_height_m=3000.0)
    # 100 ft altitude → glide line drops fast; wall at 3000m=9842ft beats it
    d = terrain_intercept_nm(
        lat=33.0, lon=-80.0, bearing_deg=90.0,
        cruise_alt_msl_ft=100.0,
        effective_glide_ratio=10.0,
        elevation_fn=elev,
        max_nm=5.0,
    )
    assert d <= 0.5


def test_envelope_east_wall_clips_east_only():
    """Wall east of the aircraft → east clip count > 0; west reaches
    its still-air maximum."""
    elev = east_wall_elev_m(33.0, -80.0,
                            wall_lon_offset=0.02,    # ~1 NM east at this lat
                            wall_height_m=4000.0)    # 13123 ft wall
    poly, n_clipped = glide_envelope_polygon(
        33.0, -80.0,
        agl_ft=5500.0, glide_ratio=10.0, glide_ias_kt=75.0,
        wind_dir_deg=0.0, wind_speed_kt=0.0, n_points=36,
        cruise_alt_msl_ft=5500.0,
        elevation_fn=elev,
    )
    # Of the 36 directions, the ~9 pointing east-ish should be clipped
    assert 4 <= n_clipped <= 20
    # Polygon should still exist
    assert not poly.is_empty


def test_corridor_terrain_used_flag_and_agl_metrics():
    """When elevation_fn supplied, terrain_used=True and the per-sample
    AGL drives min/max AGL metadata."""
    elev = flat_elev_m(100.0)   # 100 m = 328 ft AMSL flat ground
    rings, meta = compute_route_corridor(
        *KDYB, *KSAV,
        cruise_alt_msl_ft=5500.0, field_elev_ft=55.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        elevation_fn=elev,
        spacing_nm=5.0,
    )
    assert meta["terrain_used"] is True
    assert meta["below_terrain_samples"] == 0
    # AGL = 5500 - 328 ≈ 5172 ft, uniform
    assert abs(meta["agl_ft"] - 5172) < 5
    assert abs(meta["max_agl_ft"] - meta["min_agl_ft"]) < 5
    assert len(rings) >= 1


def test_corridor_below_terrain_drops_samples():
    """If cruise altitude is below the (synthetic) terrain, every
    sample is dropped and the corridor is empty."""
    elev = flat_elev_m(3000.0)   # 3000 m = 9842 ft
    rings, meta = compute_route_corridor(
        *KDYB, *KSAV,
        cruise_alt_msl_ft=5500.0, field_elev_ft=55.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        elevation_fn=elev,
        spacing_nm=5.0,
    )
    assert rings == []
    assert meta["below_terrain_samples"] > 0
    assert meta["terrain_used"] is True


def test_corridor_terrain_nan_falls_back_to_field_elev():
    """A NaN-returning elevation_fn (offline + uncached) falls back to
    field_elev_ft for that sample — corridor doesn't silently vanish."""
    elev = lambda lat, lon: float("nan")
    rings, meta = compute_route_corridor(
        *KDYB, *KSAV,
        cruise_alt_msl_ft=5500.0, field_elev_ft=55.0,
        glide_ratio=10.0, glide_ias_kt=75.0,
        elevation_fn=elev,
        spacing_nm=5.0,
    )
    # Should match the no-terrain path (field elev fallback)
    assert len(rings) >= 1
    assert meta["below_terrain_samples"] == 0
