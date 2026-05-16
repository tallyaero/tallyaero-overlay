"""Terrain conflict analysis + presentation helpers.

Surfaces three things about the route's altitude profile vs terrain:

  1. Per-sample status: clear / marginal / conflict — used to color
     route-line segments.
  2. Suggested minimum-safe cruise altitude — peak terrain in the
     corridor strip + buffer, rounded up to the next VFR-legal
     cruising altitude per FAR 91.159.
  3. Altitude profile data (sample distance, sample MSL, terrain MSL)
     suitable for a side-view thumbnail chart.

Two distinct signals (kept separate by callers):
  - cruise_alt < terrain → unflyable conflict
  - cruise above terrain but engine-out can't clear → corridor pinch
    (handled separately by core.corridor)
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from core.corridor import _offset_latlon, FT_PER_M
from core.route import haversine_nm

ElevationFn = Callable[[float, float], float]

# Status thresholds in AGL ft
MARGINAL_AGL_FT = 2000.0   # below this → amber
CONFLICT_AGL_FT = 500.0    # below this → red (or terrain pierces flight)


# === Status per sample ======================================================

def classify_sample_terrain_status(
    sample_msl_ft: float,
    terrain_ft: float,
    marginal_agl_ft: float = MARGINAL_AGL_FT,
    conflict_agl_ft: float = CONFLICT_AGL_FT,
) -> str:
    """Return 'clear' / 'marginal' / 'conflict' for one sample.

    'conflict' covers both cruise-pierces-terrain and AGL-below-min.
    """
    agl = sample_msl_ft - terrain_ft
    if agl < conflict_agl_ft:
        return "conflict"
    if agl < marginal_agl_ft:
        return "marginal"
    return "clear"


def classify_route_statuses(
    samples: list[tuple[float, float]],
    sample_alts_msl_ft: list[float],
    elevation_fn: ElevationFn,
) -> list[tuple[str, float]]:
    """Per-sample (status, terrain_ft) for the full route. Terrain
    pulled from `elevation_fn`; NaN treated as 0 (sea level — safe
    fallback when the DEM tile is missing)."""
    out: list[tuple[str, float]] = []
    for (lat, lon), msl in zip(samples, sample_alts_msl_ft):
        elev_m = elevation_fn(lat, lon)
        if elev_m != elev_m:    # NaN
            terrain_ft = 0.0
        else:
            terrain_ft = elev_m * FT_PER_M
        status = classify_sample_terrain_status(msl, terrain_ft)
        out.append((status, terrain_ft))
    return out


# === Polyline segmentation ==================================================

def segment_polyline_by_status(
    samples: list[tuple[float, float]],
    statuses: list[str],
) -> list[dict]:
    """Group consecutive samples with the same status into segments.

    Returns list of {status, positions: [[lat, lon], ...]}. Includes
    boundary samples in BOTH adjacent segments so the rendered
    polylines visually connect without gaps.
    """
    if not samples or not statuses:
        return []
    out: list[dict] = []
    current_status = statuses[0]
    current_positions: list[list[float]] = [list(samples[0])]
    for (lat, lon), status in zip(samples[1:], statuses[1:]):
        if status == current_status:
            current_positions.append([lat, lon])
        else:
            # Close current segment by including this boundary point too
            current_positions.append([lat, lon])
            out.append({"status": current_status,
                        "positions": current_positions})
            current_status = status
            current_positions = [[lat, lon]]
    out.append({"status": current_status, "positions": current_positions})
    return out


# === Corridor-strip terrain peak ============================================

def max_terrain_in_corridor_strip(
    samples: list[tuple[float, float]],
    elevation_fn: ElevationFn,
    half_width_nm: float = 5.0,
    perp_samples: int = 5,
) -> tuple[float, float, float]:
    """Return (max_terrain_ft, peak_lat, peak_lon).

    For each route sample, samples a perpendicular swath of N points
    on each side of the centerline (up to half_width_nm). This
    captures terrain that the centerline alone misses — e.g. a ridge
    parallel to the route. Returns the highest point found.
    """
    if not samples:
        return 0.0, 0.0, 0.0

    peak_ft = -1e9
    peak_lat = samples[0][0]
    peak_lon = samples[0][1]

    # Build perpendicular offsets in NM
    if perp_samples < 1:
        perp_samples = 1
    if perp_samples > 1:
        step_nm = (2 * half_width_nm) / (perp_samples - 1)
        offsets = [-half_width_nm + i * step_nm for i in range(perp_samples)]
    else:
        offsets = [0.0]

    for i, (lat, lon) in enumerate(samples):
        # Approximate track bearing from neighbor sample
        if i + 1 < len(samples):
            nxt_lat, nxt_lon = samples[i + 1]
        elif i > 0:
            nxt_lat, nxt_lon = lat, lon
            lat, lon = samples[i - 1]
        else:
            nxt_lat, nxt_lon = lat, lon
        d_lat = nxt_lat - lat
        d_lon = (nxt_lon - lon) * math.cos(math.radians(lat))
        track_rad = math.atan2(d_lon, d_lat) if (d_lat or d_lon) else 0.0
        track_deg = math.degrees(track_rad) % 360.0
        perp_deg = (track_deg + 90.0) % 360.0

        for off in offsets:
            if off == 0.0:
                plat, plon = lat, lon
            else:
                plat, plon = _offset_latlon(lat, lon, perp_deg, off)
            elev_m = elevation_fn(plat, plon)
            if elev_m != elev_m:
                continue
            elev_ft = elev_m * FT_PER_M
            if elev_ft > peak_ft:
                peak_ft = elev_ft
                peak_lat = plat
                peak_lon = plon

    if peak_ft < -1e8:
        return 0.0, samples[0][0], samples[0][1]
    return peak_ft, peak_lat, peak_lon


# === VFR cruise altitude rounding ===========================================

def vfr_cruise_round_up(
    altitude_ft: float,
    magnetic_course_deg: float,
) -> float:
    """Round altitude up to the next VFR-legal cruise altitude per
    FAR 91.159.

    Above 3000 AGL but below 18000 MSL:
      eastbound (000°-179° magnetic): odd-thousand + 500
        (3500, 5500, 7500, ...)
      westbound (180°-359° magnetic): even-thousand + 500
        (4500, 6500, 8500, ...)

    For simplicity we use the rule across the whole MSL range; the
    >3000 AGL gate is the caller's concern (suggest_min_cruise_alt
    only invokes this when terrain is in play, so altitudes will
    always be substantially above 3000 AGL anyway).

    At or above 18000 MSL: round to next 500 ft (positive control
    altitudes; ATC assignment, not VFR rule).
    """
    if altitude_ft >= 17500:
        return math.ceil(altitude_ft / 500.0) * 500.0

    eastbound = (magnetic_course_deg % 360.0) < 180.0
    if eastbound:
        # Odd-thousands + 500 ft
        valid = [3500, 5500, 7500, 9500, 11500, 13500, 15500, 17500]
    else:
        # Even-thousands + 500 ft
        valid = [4500, 6500, 8500, 10500, 12500, 14500, 16500]
    for v in valid:
        if v >= altitude_ft:
            return float(v)
    return 17500.0


# === Min-safe-altitude suggestion ===========================================

def suggest_min_cruise_alt(
    max_terrain_ft: float,
    leg_magnetic_courses: list[float],
    terrain_variance_ft: float = 0.0,
) -> tuple[float, str]:
    """Return (suggested_alt_ft, reason). Buffers max terrain by 1000
    ft (non-mountainous) or 2000 ft (mountainous, auto-detected by
    terrain variance > 3000 ft), then rounds up to the next VFR-legal
    cruise altitude per the limiting leg's magnetic course.

    `leg_magnetic_courses` should be at least one course; use the
    course of the leg whose terrain peak is limiting (caller decides
    — if unknown, pass the longest leg's course).
    """
    if not leg_magnetic_courses:
        course = 0.0
    else:
        course = leg_magnetic_courses[0]

    mountainous = terrain_variance_ft >= 3000.0
    buffer_ft = 2000.0 if mountainous else 1000.0
    raw_min = max_terrain_ft + buffer_ft
    suggested = vfr_cruise_round_up(raw_min, course)

    eb = (course % 360.0) < 180.0
    direction = "eastbound" if eb else "westbound"
    terrain_class = "mountainous" if mountainous else "non-mountainous"
    reason = (
        f"Peak terrain {max_terrain_ft:.0f} ft + {buffer_ft:.0f} ft "
        f"{terrain_class} buffer → rounded to next VFR {direction} "
        f"cruise altitude ({suggested:.0f} ft)"
    )
    return suggested, reason


# === Profile-chart data =====================================================

def build_profile_series(
    samples: list[tuple[float, float]],
    sample_alts_msl_ft: list[float],
    elevation_fn: ElevationFn,
    leg_offsets_nm: list[float] | None = None,
) -> dict:
    """Build the data series for an altitude-profile side-view chart.

    Returns dict with parallel arrays:
      distance_nm: cumulative distance from departure for each sample
      flight_alt_ft: per-sample MSL altitude (flight profile)
      terrain_ft: per-sample terrain elevation (centerline only)
      statuses: per-sample 'clear' / 'marginal' / 'conflict'
    """
    if not samples or not sample_alts_msl_ft:
        return {
            "distance_nm": [], "flight_alt_ft": [],
            "terrain_ft": [], "statuses": [],
        }

    distance_nm: list[float] = [0.0]
    for i in range(1, len(samples)):
        prev_lat, prev_lon = samples[i - 1]
        lat, lon = samples[i]
        step = haversine_nm(prev_lat, prev_lon, lat, lon)
        distance_nm.append(distance_nm[-1] + step)

    terrain_ft: list[float] = []
    statuses: list[str] = []
    for (lat, lon), msl in zip(samples, sample_alts_msl_ft):
        elev_m = elevation_fn(lat, lon)
        if elev_m != elev_m:
            tf = 0.0
        else:
            tf = elev_m * FT_PER_M
        terrain_ft.append(tf)
        statuses.append(classify_sample_terrain_status(msl, tf))

    return {
        "distance_nm": distance_nm,
        "flight_alt_ft": list(sample_alts_msl_ft),
        "terrain_ft": terrain_ft,
        "statuses": statuses,
    }
