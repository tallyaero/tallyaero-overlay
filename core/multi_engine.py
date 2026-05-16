"""Multi-engine engine-out reach: driftdown + powered single-engine flight.

For ME aircraft, a single-engine failure is NOT a glider scenario.
The aircraft can sustain altitude up to its SE service ceiling, and
above the ceiling drifts down at a rate proportional to power
deficit. The "corridor" becomes a driftdown footprint + level-flight
fuel range — typically 10-30× larger than the glide-only number.

Public API:
    is_multi_engine(aircraft) -> bool
    driftdown_profile(aircraft, start_alt, weight_lb=None,
                      wind_along_track_kt=0) -> dict
    single_engine_powered_reach_nm(aircraft, current_alt,
        fuel_remaining_gal, bearing_deg, wind_dir_deg,
        wind_speed_kt, dest_elev_ft=0) -> float
    single_engine_envelope_polygon(...) -> Polygon
    has_se_performance_data(aircraft) -> bool

Honest caveats — surfaced in the UI tooltip:
- Performance assumes the CRITICAL engine has failed.
- Assumes the failed engine is SECURED (feathered, mixture off).
- Standard atmosphere / standard temperature.
- Gross weight (worst case).
- Density altitude degrades SE numbers significantly; not yet modeled.
"""
from __future__ import annotations

import math
from typing import Optional

from shapely.geometry import Polygon
from shapely.ops import unary_union

from core.corridor import _offset_latlon, FT_PER_NM
from core.route import haversine_nm


# === Detection ==============================================================

def is_multi_engine(aircraft: dict) -> bool:
    """True if the aircraft has more than one engine."""
    return int(aircraft.get("engine_count") or 1) >= 2


def has_se_performance_data(aircraft: dict) -> bool:
    """True if all four SE performance fields are populated.
    When False, callers should fall back to glider corridor for ME
    aircraft until the data lands."""
    sel = aircraft.get("single_engine_limits") or {}
    return all(
        sel.get(k) is not None
        for k in ("service_ceiling_ft", "rate_of_climb_sl_fpm",
                  "cruise_kt", "fuel_burn_gph")
    )


# === Driftdown ==============================================================

def driftdown_profile(
    aircraft: dict,
    start_alt_msl_ft: float,
    weight_lb: Optional[float] = None,
    wind_along_track_kt: float = 0.0,
) -> dict:
    """Compute the descent profile when an engine fails at
    `start_alt_msl_ft`.

    Returns dict:
        target_alt_msl_ft   the SE service ceiling (where SE RoC = 0).
        descent_time_min    minutes to drift from start_alt to ceiling.
                            Zero if already below ceiling.
        ground_distance_nm  forward distance covered during driftdown,
                            adjusted by along-track wind.
        already_below_ceiling  bool — start_alt <= SE ceiling.
        descent_rate_fpm    average fpm during the driftdown segment.

    Math: SE RoC at altitude h is linearly interpolated between
    `rate_of_climb_sl_fpm` at sea level and 50 fpm at the SE service
    ceiling (FAR 23.65 definition). Above the ceiling, the rate becomes
    NEGATIVE (descent) with magnitude proportional to (h - ceiling)
    extrapolated past the same slope.
    """
    sel = aircraft.get("single_engine_limits") or {}
    ceiling = float(sel.get("service_ceiling_ft") or 0)
    roc_sl = float(sel.get("rate_of_climb_sl_fpm") or 0)
    cruise_kt = float(sel.get("cruise_kt") or 0)

    if start_alt_msl_ft <= ceiling:
        return {
            "target_alt_msl_ft": start_alt_msl_ft,
            "descent_time_min": 0.0,
            "ground_distance_nm": 0.0,
            "already_below_ceiling": True,
            "descent_rate_fpm": 0.0,
        }

    # SE climb rate is roc_sl at sea level, 50 fpm at ceiling.
    # Linear interpolation gives slope (50 - roc_sl) / ceiling per ft.
    # Above ceiling, projecting the same slope, RoC = 50 + slope*(h-ceiling)
    # which becomes negative (= rate of descent).
    if ceiling <= 0 or roc_sl <= 0:
        # Bad data — return as if no driftdown
        return {
            "target_alt_msl_ft": start_alt_msl_ft,
            "descent_time_min": 0.0,
            "ground_distance_nm": 0.0,
            "already_below_ceiling": True,
            "descent_rate_fpm": 0.0,
        }

    slope_fpm_per_ft = (50.0 - roc_sl) / ceiling
    # Average rate over the descent segment is the mean of the rates
    # at the start altitude and at the ceiling (50 fpm). The rate at
    # start_alt is 50 + slope*(start_alt - ceiling) — negative.
    rate_at_start = 50.0 + slope_fpm_per_ft * (start_alt_msl_ft - ceiling)
    # Average descent magnitude (positive number for descent rate)
    avg_descent = -(50.0 + rate_at_start) / 2.0   # both rates negative
    avg_descent = max(50.0, avg_descent)   # floor at 50 fpm for sanity

    descent_height_ft = start_alt_msl_ft - ceiling
    descent_time_min = descent_height_ft / avg_descent

    # Ground speed = SE cruise TAS + along-track wind (positive = tailwind)
    gs_kt = max(1.0, cruise_kt + wind_along_track_kt)
    ground_distance_nm = (descent_time_min / 60.0) * gs_kt

    return {
        "target_alt_msl_ft": ceiling,
        "descent_time_min": descent_time_min,
        "ground_distance_nm": ground_distance_nm,
        "already_below_ceiling": False,
        "descent_rate_fpm": -avg_descent,
    }


# === Powered SE reach =======================================================

def _wind_along_track(
    bearing_deg: float, wind_dir_deg: float, wind_speed_kt: float,
) -> float:
    """Positive = tailwind on this bearing; negative = headwind."""
    rel = math.radians(wind_dir_deg + 180.0 - bearing_deg)
    return wind_speed_kt * math.cos(rel)


def single_engine_powered_reach_nm(
    aircraft: dict,
    current_alt_msl_ft: float,
    fuel_remaining_gal: float,
    bearing_deg: float,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    dest_elev_ft: float = 0.0,
) -> float:
    """Directional powered reach on remaining engine.

    Combines a driftdown segment (if above SE ceiling) + a level-flight
    segment (at the ceiling or current alt, whichever is lower) using
    remaining fuel. Wind component along the bearing is applied to
    ground speed for both segments.

    Returns 0 when SE performance data isn't populated.
    """
    if not has_se_performance_data(aircraft):
        return 0.0
    sel = aircraft.get("single_engine_limits") or {}
    cruise_kt = float(sel["cruise_kt"])
    fuel_gph = float(sel["fuel_burn_gph"])
    ceiling = float(sel["service_ceiling_ft"])

    along = _wind_along_track(bearing_deg, wind_dir_deg, wind_speed_kt)

    # Driftdown segment (if above ceiling)
    dd = driftdown_profile(
        aircraft, current_alt_msl_ft,
        wind_along_track_kt=along,
    )
    dd_dist = dd["ground_distance_nm"]
    dd_minutes = dd["descent_time_min"]
    fuel_used_dd = (dd_minutes / 60.0) * fuel_gph
    fuel_left = max(0.0, fuel_remaining_gal - fuel_used_dd)

    # Level-flight segment: from min(current_alt, ceiling) until fuel
    # runs out OR we reach destination elevation (if dest > ceiling
    # we can't get above it on one engine — corner case).
    gs = max(1.0, cruise_kt + along)
    if fuel_gph <= 0:
        return dd_dist
    level_minutes = fuel_left / fuel_gph * 60.0
    level_dist = (level_minutes / 60.0) * gs

    return dd_dist + level_dist


# === SE envelope polygon ====================================================

def compute_route_se_corridor(
    samples: list[tuple[float, float]],
    sample_alts_msl_ft: list[float],
    aircraft: dict,
    fuel_remaining_gal: float,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    sample_winds: Optional[list[tuple[float, float]]] = None,
    n_envelope_points: int = 24,
) -> tuple[list[list[list[float]]], dict]:
    """Build the powered single-engine corridor along the route.

    Per route sample, computes the SE reach polygon assuming engine
    failure at that point. Unions all per-sample polygons into the
    corridor footprint.

    Returns (polygon_rings, metadata) matching the shape of
    `core.corridor.compute_route_corridor`. metadata fields:
        n_samples, has_se_data, mean_reach_nm, max_reach_nm,
        area_nm2
    """
    if not has_se_performance_data(aircraft):
        return [], {
            "n_samples": 0, "has_se_data": False,
            "mean_reach_nm": 0.0, "max_reach_nm": 0.0,
            "area_nm2": 0.0,
        }
    if not samples or not sample_alts_msl_ft:
        return [], {
            "n_samples": 0, "has_se_data": True,
            "mean_reach_nm": 0.0, "max_reach_nm": 0.0,
            "area_nm2": 0.0,
        }

    if sample_winds is not None and len(sample_winds) == len(samples):
        per_sample_wind = list(sample_winds)
    else:
        per_sample_wind = [(wind_dir_deg, wind_speed_kt)] * len(samples)

    polys: list[Polygon] = []
    reaches: list[float] = []
    for (lat, lon), alt, (wd, ws) in zip(
        samples, sample_alts_msl_ft, per_sample_wind,
    ):
        poly = single_engine_envelope_polygon(
            lat, lon, aircraft,
            current_alt_msl_ft=alt,
            fuel_remaining_gal=fuel_remaining_gal,
            wind_dir_deg=wd, wind_speed_kt=ws,
            n_points=n_envelope_points,
        )
        if poly.is_empty:
            continue
        polys.append(poly)
        # Track centerline reach (average distance from sample center
        # to polygon vertices) for the metadata mean/max.
        coords = list(poly.exterior.coords)[:-1]
        if coords:
            avg = sum(
                haversine_nm(lat, lon, plat, plon)
                for (plon, plat) in coords
            ) / len(coords)
            reaches.append(avg)

    if not polys:
        return [], {
            "n_samples": len(samples), "has_se_data": True,
            "mean_reach_nm": 0.0, "max_reach_nm": 0.0,
            "area_nm2": 0.0,
        }

    union = unary_union(polys)
    rings: list[list[list[float]]] = []
    geoms = [union] if isinstance(union, Polygon) else list(union.geoms)
    for g in geoms:
        if isinstance(g, Polygon) and not g.is_empty:
            rings.append([[lat, lon] for lon, lat in g.exterior.coords])

    mid_lat = sum(s[0] for s in samples) / len(samples)
    nm_per_deg_lat = 60.0
    nm_per_deg_lon = 60.0 * math.cos(math.radians(mid_lat))
    area_nm2 = union.area * nm_per_deg_lat * nm_per_deg_lon

    return rings, {
        "n_samples": len(samples),
        "has_se_data": True,
        "mean_reach_nm": round(sum(reaches) / max(1, len(reaches)), 1),
        "max_reach_nm": round(max(reaches) if reaches else 0.0, 1),
        "area_nm2": round(area_nm2, 1),
    }


def single_engine_envelope_polygon(
    lat: float, lon: float,
    aircraft: dict,
    current_alt_msl_ft: float,
    fuel_remaining_gal: float,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    n_points: int = 36,
) -> Polygon:
    """Build a powered SE reach polygon around a single sample point.

    n_points directions sampled; each direction's reach computed by
    single_engine_powered_reach_nm. Returns an empty Polygon when SE
    performance data is missing for the aircraft."""
    if not has_se_performance_data(aircraft) or fuel_remaining_gal <= 0:
        return Polygon()
    points: list[tuple[float, float]] = []
    for i in range(n_points):
        heading = 360.0 * i / n_points
        reach = single_engine_powered_reach_nm(
            aircraft, current_alt_msl_ft, fuel_remaining_gal,
            heading, wind_dir_deg, wind_speed_kt,
        )
        if reach <= 0:
            reach = 0.01
        plat, plon = _offset_latlon(lat, lon, heading, reach)
        points.append((plon, plat))
    if not points:
        return Polygon()
    points.append(points[0])
    return Polygon(points)
