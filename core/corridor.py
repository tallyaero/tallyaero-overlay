"""Glide corridor — the area along a route reachable in a power-off glide.

Per route sample point, the engine-out reach is a wind-distorted polygon
(circle in still air, teardrop downwind in wind). The corridor is the
union of all those polygons sampled at ~1 NM along the route.

Foundation only — no AGL refinement against terrain yet (Phase 7c).
That step samples Open-Meteo elevation per route point and reduces the
local AGL by `cruise_alt - elevation`.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from core.route import EARTH_RADIUS_NM, haversine_nm, initial_bearing_deg


def _offset_latlon(lat_deg: float, lon_deg: float,
                   bearing_deg: float, distance_nm: float) -> tuple[float, float]:
    """Return a new lat/lon offset from (lat, lon) by `distance_nm` on
    the great-circle bearing `bearing_deg`. Equirectangular at short
    range; we use the spherical formula for accuracy."""
    if distance_nm <= 0:
        return (lat_deg, lon_deg)
    d_rad = distance_nm / EARTH_RADIUS_NM
    brg = math.radians(bearing_deg)
    lat1 = math.radians(lat_deg)
    lon1 = math.radians(lon_deg)
    sin_lat2 = (math.sin(lat1) * math.cos(d_rad)
                + math.cos(lat1) * math.sin(d_rad) * math.cos(brg))
    lat2 = math.asin(sin_lat2)
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d_rad) * math.cos(lat1),
        math.cos(d_rad) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), math.degrees(lon2))


def glide_envelope_polygon(
    lat: float, lon: float,
    agl_ft: float,
    glide_ratio: float,
    glide_ias_kt: float = 75.0,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    n_points: int = 36,
) -> Polygon:
    """Engine-out reach envelope around a single point.

    Args:
        lat, lon: aircraft position (deg).
        agl_ft: height above ground (feet).
        glide_ratio: best-glide L/D (e.g. 8.5 for a Cessna 172).
        glide_ias_kt: best-glide IAS — needed to scale wind effect.
        wind_dir_deg, wind_speed_kt: wind FROM direction + speed.
        n_points: how many directions to sample (36 = 10° spacing).

    Returns:
        Shapely Polygon in (lon, lat) coordinate order.

    Math:
        Still-air glide distance = agl_ft × glide_ratio (feet) / FT_PER_NM.
        With wind, the time-to-ground at the IAS is fixed
        (t = agl / glide_descent_rate). Ground reach in direction θ =
        air_distance + wind_drift_along_θ over that time. We approximate
        this by scaling the still-air reach by (IAS + wind_component) / IAS
        where wind_component = wind_speed × cos(wind_dir - heading_θ).
    """
    if agl_ft <= 0 or glide_ratio <= 0:
        return Polygon()

    still_air_nm = (agl_ft * glide_ratio) / 6076.115

    # Avoid singularities when wind ~ TAS by clamping the scale factor
    points: list[tuple[float, float]] = []
    for i in range(n_points):
        heading = 360.0 * i / n_points
        # wind FROM dir; the wind vector points TOWARD (wind_dir + 180).
        # The component pushing the airplane along its heading is
        # negative when wind opposes (head wind), positive on tail.
        # Δ = wind_dir + 180 - heading  →  along-track component
        # = wind_speed × cos(Δ).
        rel = math.radians(wind_dir_deg + 180.0 - heading)
        along_track = wind_speed_kt * math.cos(rel)
        scale = max(0.05, 1.0 + along_track / max(1.0, glide_ias_kt))
        reach_nm = still_air_nm * scale
        plat, plon = _offset_latlon(lat, lon, heading, reach_nm)
        points.append((plon, plat))

    points.append(points[0])  # close the ring
    return Polygon(points)


def sample_route_points(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
    spacing_nm: float = 1.0,
) -> list[tuple[float, float]]:
    """Sample (lat, lon) tuples along the great-circle from origin to
    destination at ~`spacing_nm` intervals. Returns at minimum the two
    endpoints; longer legs interpolate."""
    total_nm = haversine_nm(origin_lat, origin_lon, dest_lat, dest_lon)
    bearing = initial_bearing_deg(origin_lat, origin_lon, dest_lat, dest_lon)
    n_steps = max(2, int(total_nm / max(0.1, spacing_nm)) + 1)
    points: list[tuple[float, float]] = []
    for i in range(n_steps):
        d_nm = total_nm * (i / (n_steps - 1))
        lat, lon = _offset_latlon(origin_lat, origin_lon, bearing, d_nm)
        points.append((lat, lon))
    return points


def compute_route_corridor(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
    cruise_alt_msl_ft: float,
    field_elev_ft: float,
    glide_ratio: float,
    glide_ias_kt: float = 75.0,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    spacing_nm: float = 2.0,
    n_envelope_points: int = 36,
) -> tuple[list[list[list[float]]], dict]:
    """Compute the union of glide envelopes along a route.

    Returns:
        (polygon_rings, metadata)
        polygon_rings is a list of [lat, lon] vertex lists — one per
        exterior ring of the corridor (one for a simple union, possibly
        more if the corridor splits — rare). Suitable for dl.Polygon.
        metadata: narrowest, widest, total_area_nm2, n_samples.

    AGL is approximated as `cruise_alt_msl_ft - field_elev_ft` and held
    constant along the route. Phase 7c will refine per-sample via
    Open-Meteo elevation.
    """
    agl_ft = max(0.0, cruise_alt_msl_ft - field_elev_ft)
    samples = sample_route_points(origin_lat, origin_lon,
                                  dest_lat, dest_lon, spacing_nm)

    polygons: list[Polygon] = []
    for lat, lon in samples:
        poly = glide_envelope_polygon(
            lat=lat, lon=lon,
            agl_ft=agl_ft,
            glide_ratio=glide_ratio,
            glide_ias_kt=glide_ias_kt,
            wind_dir_deg=wind_dir_deg,
            wind_speed_kt=wind_speed_kt,
            n_points=n_envelope_points,
        )
        if not poly.is_empty:
            polygons.append(poly)

    if not polygons:
        return [], {"narrowest_nm": 0.0, "widest_nm": 0.0,
                    "area_nm2": 0.0, "n_samples": 0}

    union = unary_union(polygons)

    # Extract exterior rings as [lat, lon] lists for dl.Polygon
    rings: list[list[list[float]]] = []
    geoms = [union] if isinstance(union, Polygon) else list(union.geoms)
    for g in geoms:
        if isinstance(g, Polygon) and not g.is_empty:
            rings.append([[lat, lon] for lon, lat in g.exterior.coords])

    # Approximate area (deg²) → NM² with crude conversion at the
    # route midpoint latitude; the user just needs a relative number.
    mid_lat = (origin_lat + dest_lat) / 2.0
    nm_per_deg_lat = 60.0
    nm_per_deg_lon = 60.0 * math.cos(math.radians(mid_lat))
    area_nm2 = union.area * nm_per_deg_lat * nm_per_deg_lon

    # Narrowest / widest perpendicular width — proxy via per-sample
    # envelope mean radius (still-air glide × scale spread).
    still_air_nm = (agl_ft * glide_ratio) / 6076.115
    widest = still_air_nm * (1.0 + wind_speed_kt / max(1.0, glide_ias_kt))
    narrowest = still_air_nm * max(0.05, 1.0 - wind_speed_kt / max(1.0, glide_ias_kt))

    return rings, {
        "narrowest_nm": round(narrowest, 2),
        "widest_nm": round(widest, 2),
        "area_nm2": round(area_nm2, 1),
        "n_samples": len(samples),
        "agl_ft": round(agl_ft, 0),
    }
