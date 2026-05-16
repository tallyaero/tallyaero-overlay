"""Glide corridor — the area along a route reachable in a power-off glide.

Per route sample point, the engine-out reach is a wind-distorted polygon
(circle in still air, teardrop downwind in wind). The corridor is the
union of all those polygons sampled at ~1-2 NM along the route.

Phase 7d adds terrain awareness. When an `elevation_fn(lat, lon) -> m`
is supplied:
- Per-sample AGL = cruise_alt_msl - terrain_at_sample. Samples below
  ridges contribute nothing.
- Per-direction reach is ray-marched: walk outward at the descending
  glide slope, stop where terrain rises above the glide line. The
  polygon pinches away from rising terrain.
- Tracks how many sample directions were terrain-clipped vs wind-clipped
  so the UI can call out "ridges are biting your glide footprint."
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from shapely.geometry import Polygon
from shapely.ops import unary_union

from core.route import EARTH_RADIUS_NM, haversine_nm, initial_bearing_deg

FT_PER_NM = 6076.115
FT_PER_M = 3.28084
M_PER_FT = 1.0 / FT_PER_M

ElevationFn = Callable[[float, float], float]


def _offset_latlon(lat_deg: float, lon_deg: float,
                   bearing_deg: float, distance_nm: float) -> tuple[float, float]:
    """Spherical-Earth offset by bearing + distance, in degrees."""
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


def terrain_intercept_nm(
    lat: float, lon: float,
    bearing_deg: float,
    cruise_alt_msl_ft: float,
    effective_glide_ratio: float,
    elevation_fn: ElevationFn,
    max_nm: float,
    step_nm: float = 0.25,
) -> float:
    """Ray-march outward along `bearing_deg` from (lat, lon). Returns
    the distance (NM) at which the descending engine-out glide line
    first drops below terrain. Returns `max_nm` if the route never
    intercepts terrain within that distance.

    The glide slope used is the *effective* glide ratio for this
    bearing — i.e. wind-adjusted by the calling envelope code, since
    a tailwind extends ground-track reach per unit altitude lost.

    `elevation_fn` must return meters MSL. We work in feet internally.
    """
    if effective_glide_ratio <= 0 or max_nm <= 0:
        return 0.0

    # Descending glide line: per NM of forward ground track, the
    # airplane sinks ground_descent_ft_per_nm feet.
    # glide_ratio = forward_ft / down_ft → down_ft = forward_ft / GR
    descent_ft_per_nm = FT_PER_NM / effective_glide_ratio

    d = step_nm
    last_clear = 0.0
    while d <= max_nm:
        plat, plon = _offset_latlon(lat, lon, bearing_deg, d)
        terrain_m = elevation_fn(plat, plon)
        # If the lookup failed (NaN), treat as missing data: do not
        # clip — fall back to wind-limited reach for this bearing.
        if terrain_m != terrain_m:   # NaN check
            return max_nm
        terrain_ft = terrain_m * FT_PER_M
        glide_alt_ft = cruise_alt_msl_ft - d * descent_ft_per_nm
        if glide_alt_ft < terrain_ft:
            return last_clear
        last_clear = d
        d += step_nm
    return max_nm


def glide_envelope_polygon(
    lat: float, lon: float,
    agl_ft: float,
    glide_ratio: float,
    glide_ias_kt: float = 75.0,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    n_points: int = 36,
    *,
    cruise_alt_msl_ft: Optional[float] = None,
    elevation_fn: Optional[ElevationFn] = None,
    terrain_step_nm: float = 0.25,
) -> tuple[Polygon, int]:
    """Engine-out reach envelope around a single point.

    Returns:
        (polygon, n_terrain_clipped_directions)
        - polygon: shapely Polygon in (lon, lat) order.
        - n_terrain_clipped_directions: count of the `n_points` headings
          where the terrain intercept came in shorter than the
          wind-scaled still-air reach. 0 means no ridge bites; n_points
          means the airplane is fully terrain-bounded.

    Math:
        Still-air reach per direction = agl_ft × glide_ratio / FT_PER_NM.
        Wind scale per direction = (1 + along_track_wind / IAS), floored
        at 0.05 so a strong headwind narrows but doesn't fully collapse.
        With terrain (elevation_fn + cruise_alt_msl_ft supplied), the
        effective per-direction reach is the lesser of the wind-scaled
        still-air reach and the ray-marched terrain intercept.
    """
    if agl_ft <= 0 or glide_ratio <= 0:
        return Polygon(), 0

    still_air_nm = (agl_ft * glide_ratio) / FT_PER_NM
    have_terrain = elevation_fn is not None and cruise_alt_msl_ft is not None

    n_clipped = 0
    points: list[tuple[float, float]] = []
    for i in range(n_points):
        heading = 360.0 * i / n_points
        rel = math.radians(wind_dir_deg + 180.0 - heading)
        along_track = wind_speed_kt * math.cos(rel)
        scale = max(0.05, 1.0 + along_track / max(1.0, glide_ias_kt))
        wind_reach_nm = still_air_nm * scale

        reach_nm = wind_reach_nm
        if have_terrain:
            # Effective glide ratio along this bearing accounts for
            # along-track wind: tailwind = more ground per ft lost.
            effective_gr = glide_ratio * scale
            terrain_max = terrain_intercept_nm(
                lat=lat, lon=lon, bearing_deg=heading,
                cruise_alt_msl_ft=cruise_alt_msl_ft,
                effective_glide_ratio=effective_gr,
                elevation_fn=elevation_fn,
                max_nm=wind_reach_nm,
                step_nm=terrain_step_nm,
            )
            if terrain_max < wind_reach_nm - 1e-6:
                n_clipped += 1
                reach_nm = terrain_max

        plat, plon = _offset_latlon(lat, lon, heading, max(0.0, reach_nm))
        points.append((plon, plat))

    if not points:
        return Polygon(), 0
    points.append(points[0])
    return Polygon(points), n_clipped


def sample_route_points(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
    spacing_nm: float = 1.0,
) -> list[tuple[float, float]]:
    """Sample (lat, lon) along the great-circle at ~`spacing_nm`.
    At minimum returns the two endpoints."""
    total_nm = haversine_nm(origin_lat, origin_lon, dest_lat, dest_lon)
    bearing = initial_bearing_deg(origin_lat, origin_lon, dest_lat, dest_lon)
    n_steps = max(2, int(total_nm / max(0.1, spacing_nm)) + 1)
    out: list[tuple[float, float]] = []
    for i in range(n_steps):
        d_nm = total_nm * (i / (n_steps - 1))
        lat, lon = _offset_latlon(origin_lat, origin_lon, bearing, d_nm)
        out.append((lat, lon))
    return out


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
    *,
    elevation_fn: Optional[ElevationFn] = None,
    terrain_step_nm: float = 0.25,
    sample_alts_msl_ft: Optional[list[float]] = None,
) -> tuple[list[list[list[float]]], dict]:
    """Compute the union of glide envelopes along a route.

    Returns:
        (polygon_rings, metadata)
        polygon_rings: list of [lat, lon] vertex lists, one per exterior
        ring of the unioned corridor. Suitable for dl.Polygon.
        metadata: {narrowest_nm, widest_nm, area_nm2, n_samples,
                   agl_ft (route mean), min_agl_ft, max_agl_ft,
                   terrain_limited_samples, below_terrain_samples,
                   terrain_used (bool)}

    When `elevation_fn` is None, behavior matches pre-7d: AGL is held
    constant at `cruise_alt - field_elev` along the route and no
    ridge clipping happens. When `elevation_fn` IS supplied, AGL is
    derived per-sample from the DEM and the per-direction reach is
    ridge-clipped by ray-march.
    """
    samples = sample_route_points(origin_lat, origin_lon,
                                  dest_lat, dest_lon, spacing_nm)
    have_terrain = elevation_fn is not None

    # Per-sample altitude: either explicit from caller (flight profile)
    # or the constant cruise_alt for backward compatibility. If the
    # caller-supplied list is the wrong length we silently fall back.
    if sample_alts_msl_ft is not None and len(sample_alts_msl_ft) == len(samples):
        per_sample_alt = list(sample_alts_msl_ft)
    else:
        per_sample_alt = [cruise_alt_msl_ft] * len(samples)

    polygons: list[Polygon] = []
    terrain_limited_samples = 0
    below_terrain_samples = 0
    agl_values: list[float] = []

    for (lat, lon), sample_msl in zip(samples, per_sample_alt):
        if have_terrain:
            elev_m = elevation_fn(lat, lon)
            if elev_m != elev_m:    # NaN — missing tile
                # Fall back to field elev so we don't silently drop the
                # corridor over an offline gap
                sample_terrain_ft = field_elev_ft
            else:
                sample_terrain_ft = elev_m * FT_PER_M
        else:
            sample_terrain_ft = field_elev_ft

        agl_ft = sample_msl - sample_terrain_ft
        if agl_ft <= 0:
            below_terrain_samples += 1
            continue
        agl_values.append(agl_ft)

        poly, n_clipped = glide_envelope_polygon(
            lat=lat, lon=lon,
            agl_ft=agl_ft,
            glide_ratio=glide_ratio,
            glide_ias_kt=glide_ias_kt,
            wind_dir_deg=wind_dir_deg,
            wind_speed_kt=wind_speed_kt,
            n_points=n_envelope_points,
            cruise_alt_msl_ft=sample_msl if have_terrain else None,
            elevation_fn=elevation_fn,
            terrain_step_nm=terrain_step_nm,
        )
        if not poly.is_empty:
            polygons.append(poly)
            if n_clipped > 0:
                terrain_limited_samples += 1

    if not polygons:
        return [], {
            "narrowest_nm": 0.0, "widest_nm": 0.0, "area_nm2": 0.0,
            "n_samples": 0, "agl_ft": 0.0,
            "min_agl_ft": 0.0, "max_agl_ft": 0.0,
            "terrain_limited_samples": 0,
            "below_terrain_samples": below_terrain_samples,
            "terrain_used": have_terrain,
        }

    union = unary_union(polygons)
    rings: list[list[list[float]]] = []
    geoms = [union] if isinstance(union, Polygon) else list(union.geoms)
    for g in geoms:
        if isinstance(g, Polygon) and not g.is_empty:
            rings.append([[lat, lon] for lon, lat in g.exterior.coords])

    mid_lat = (origin_lat + dest_lat) / 2.0
    nm_per_deg_lat = 60.0
    nm_per_deg_lon = 60.0 * math.cos(math.radians(mid_lat))
    area_nm2 = union.area * nm_per_deg_lat * nm_per_deg_lon

    # Narrowest / widest: bracket the per-sample wind-scaled reach. With
    # terrain clipping in play these are upper bounds, since ridges only
    # tighten the envelope further.
    mean_agl_ft = sum(agl_values) / max(1, len(agl_values))
    still_air_nm = (mean_agl_ft * glide_ratio) / FT_PER_NM
    widest = still_air_nm * (1.0 + wind_speed_kt / max(1.0, glide_ias_kt))
    narrowest = still_air_nm * max(0.05, 1.0 - wind_speed_kt / max(1.0, glide_ias_kt))

    return rings, {
        "narrowest_nm": round(narrowest, 2),
        "widest_nm": round(widest, 2),
        "area_nm2": round(area_nm2, 1),
        "n_samples": len(samples),
        "agl_ft": round(mean_agl_ft, 0),
        "min_agl_ft": round(min(agl_values), 0),
        "max_agl_ft": round(max(agl_values), 0),
        "terrain_limited_samples": terrain_limited_samples,
        "below_terrain_samples": below_terrain_samples,
        "terrain_used": have_terrain,
    }
