"""Divert-airport reach analysis along a planned route.

For each route sample point, find the airports an engine-out glide
could reach from that altitude. Aggregate to:
  - the unique set of reachable divert airports along the route
  - "unsupported gap" segments where NO airport is reachable
  - per-sample reachability for downstream rendering

Two modes:
  - SIMPLE: pass `reach_per_sample_nm` to `divert_coverage_along_route`.
    Flat haversine reach; no wind, no terrain. Useful for tests +
    sanity checks.
  - GLIDE: pass `cruise_alt_msl_ft + glide_ratio + wind + elevation_fn`
    to `divert_coverage_along_route_glide`. Per-bearing wind-scaled
    reach AND ray-march ridge-clip on every (sample, airport) line.
    Matches the corridor math — same prefetch tiles cover both.

Filter rules for "landable":
  - Skip seaplane bases (wheeled aircraft can't land on water).
  - Skip airports with no usable runway data unless they are
    large/medium type (those almost certainly have plenty of runway).
  - Require at least one runway >= min_runway_ft when runway data
    exists.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Optional

from core.route import haversine_nm, initial_bearing_deg, EARTH_RADIUS_NM
from core.corridor import _offset_latlon, FT_PER_NM, FT_PER_M

ElevationFn = Callable[[float, float], float]

# Default minimum runway for a survivable engine-out landing.
# 1500 ft accommodates almost any GA single — pilots can always
# tighten this if they're flying something faster.
DEFAULT_MIN_RUNWAY_FT = 1500


def is_landable(airport: dict, min_runway_ft: int = DEFAULT_MIN_RUNWAY_FT) -> bool:
    """Heuristic: would I take this airport as an engine-out divert?"""
    ap_type = (airport.get("type") or "").lower()
    if ap_type == "seaplane_base":
        return False

    runways = airport.get("runways") or []
    if runways:
        # Has runway data — at least one must be long enough.
        for r in runways:
            length = r.get("length_ft") or r.get("length") or 0
            if length and length >= min_runway_ft:
                return True
        return False

    # No runway data — accept large/medium (will have ample runway),
    # reject small (might be a 600 ft strip).
    return ap_type in ("large_airport", "medium_airport")


def find_diverts_in_reach(
    airport_data: list[dict],
    lat: float, lon: float,
    reach_nm: float,
    min_runway_ft: int = DEFAULT_MIN_RUNWAY_FT,
) -> list[dict]:
    """All landable airports within `reach_nm` of (lat, lon).

    Returns list of {airport, distance_nm}, sorted by distance ascending.
    Uses a cheap lat/lon bbox prefilter so we don't haversine every one
    of the 49k airports per sample.
    """
    if reach_nm <= 0:
        return []
    # Bbox prefilter: convert reach to a generous bbox in degrees.
    pad_lat = reach_nm / 60.0
    pad_lon = pad_lat / max(0.1, math.cos(math.radians(lat)))
    lat_lo, lat_hi = lat - pad_lat, lat + pad_lat
    lon_lo, lon_hi = lon - pad_lon, lon + pad_lon

    out: list[dict] = []
    for ap in airport_data:
        a_lat = ap.get("lat")
        a_lon = ap.get("lon")
        if a_lat is None or a_lon is None:
            continue
        if a_lat < lat_lo or a_lat > lat_hi or a_lon < lon_lo or a_lon > lon_hi:
            continue
        if not is_landable(ap, min_runway_ft):
            continue
        d = haversine_nm(lat, lon, a_lat, a_lon)
        if d <= reach_nm:
            out.append({"airport": ap, "distance_nm": d})
    out.sort(key=lambda r: r["distance_nm"])
    return out


def divert_coverage_along_route(
    samples: list[tuple[float, float]],
    airport_data: list[dict],
    reach_per_sample_nm: list[float] | float,
    min_runway_ft: int = DEFAULT_MIN_RUNWAY_FT,
) -> dict:
    """Build per-sample divert coverage + the unique reachable set.

    Args:
        samples: list of (lat, lon) along the route.
        airport_data: full airport list.
        reach_per_sample_nm: either one float (constant reach) or a list
            of floats aligned with `samples` (per-sample reach — when
            terrain or AGL varies along the route).
        min_runway_ft: filter for "landable".

    Returns dict with keys:
        per_sample: list[ list[airport_id] ] — IDs of reachable airports
            from each sample.
        unique_diverts: list[dict] — one entry per unique reachable
            airport across the whole route. Sorted by min-distance.
            Each entry: {airport, min_distance_nm, n_samples}.
        n_samples_with_coverage: int
        n_samples_with_no_coverage: int
    """
    if isinstance(reach_per_sample_nm, (int, float)):
        reaches = [float(reach_per_sample_nm)] * len(samples)
    else:
        reaches = list(reach_per_sample_nm)
        if len(reaches) < len(samples):
            reaches = reaches + [reaches[-1]] * (len(samples) - len(reaches))

    per_sample: list[list[str]] = []
    uniq_min_dist: dict[str, float] = {}
    uniq_n_samples: dict[str, int] = {}
    uniq_ap: dict[str, dict] = {}
    for (lat, lon), reach in zip(samples, reaches):
        hits = find_diverts_in_reach(airport_data, lat, lon, reach, min_runway_ft)
        ids = []
        for h in hits:
            ap = h["airport"]
            apid = ap.get("id") or ap.get("icao")
            if not apid:
                continue
            ids.append(apid)
            d = h["distance_nm"]
            if apid not in uniq_min_dist or d < uniq_min_dist[apid]:
                uniq_min_dist[apid] = d
                uniq_ap[apid] = ap
            uniq_n_samples[apid] = uniq_n_samples.get(apid, 0) + 1
        per_sample.append(ids)

    unique_diverts = [
        {"airport": uniq_ap[apid],
         "min_distance_nm": round(uniq_min_dist[apid], 1),
         "n_samples": uniq_n_samples[apid]}
        for apid in uniq_min_dist
    ]
    unique_diverts.sort(key=lambda r: r["min_distance_nm"])

    no_cov = sum(1 for s in per_sample if not s)
    return {
        "per_sample": per_sample,
        "unique_diverts": unique_diverts,
        "n_samples_with_coverage": len(per_sample) - no_cov,
        "n_samples_with_no_coverage": no_cov,
    }


def gap_segments(
    samples: list[tuple[float, float]],
    per_sample_coverage: list[list[str]],
) -> list[dict]:
    """Find contiguous stretches where NO airport is reachable.

    Returns list of {start_idx, end_idx, gap_nm, mid_lat, mid_lon} for
    each unsupported run. `gap_nm` is the great-circle distance from
    the first to the last sample in the run.

    A single isolated uncovered sample is still reported as a gap
    spanning zero distance — pilots may want to see it.
    """
    out: list[dict] = []
    in_gap = False
    gap_start = 0
    for i, cov in enumerate(per_sample_coverage):
        if not cov:
            if not in_gap:
                in_gap = True
                gap_start = i
        else:
            if in_gap:
                out.append(_gap_record(samples, gap_start, i - 1))
                in_gap = False
    if in_gap:
        out.append(_gap_record(samples, gap_start, len(per_sample_coverage) - 1))
    return out


def _gap_record(samples, start_idx: int, end_idx: int) -> dict:
    s_lat, s_lon = samples[start_idx]
    e_lat, e_lon = samples[end_idx]
    gap_nm = haversine_nm(s_lat, s_lon, e_lat, e_lon)
    mid_lat = (s_lat + e_lat) / 2.0
    mid_lon = (s_lon + e_lon) / 2.0
    return {
        "start_idx": start_idx,
        "end_idx": end_idx,
        "gap_nm": round(gap_nm, 1),
        "mid_lat": mid_lat,
        "mid_lon": mid_lon,
        "start_lat": s_lat, "start_lon": s_lon,
        "end_lat": e_lat, "end_lon": e_lon,
    }


def longest_gap_nm(gaps: list[dict]) -> float:
    return max((g["gap_nm"] for g in gaps), default=0.0)


# === Terrain-aware reach =====================================================

def _wind_scale(bearing_deg: float,
                wind_dir_deg: float, wind_speed_kt: float,
                ias_kt: float) -> float:
    """Per-bearing reach scale factor. Wind FROM direction; tailwind
    extends ground reach, headwind shrinks it. Floored at 0.05 so a
    pure headwind doesn't fully collapse the glide. Matches the
    corridor envelope math one-for-one."""
    rel = math.radians(wind_dir_deg + 180.0 - bearing_deg)
    along = wind_speed_kt * math.cos(rel)
    return max(0.05, 1.0 + along / max(1.0, ias_kt))


def can_glide_to(
    sample_lat: float, sample_lon: float, sample_msl_ft: float,
    ap_lat: float, ap_lon: float, ap_elev_ft: float,
    glide_ratio: float,
    glide_ias_kt: float = 75.0,
    wind_dir_deg: float = 0.0, wind_speed_kt: float = 0.0,
    elevation_fn: Optional[ElevationFn] = None,
    terrain_step_nm: float = 0.5,
) -> bool:
    """Can an engine-out glide from (sample) actually reach the airport
    given wind and (optionally) terrain in between?

    Two checks must pass:
      1. Arrival altitude (sample_msl - distance × descent_per_nm) is
         above the airport elevation. Wind on the bearing scales the
         effective glide ratio.
      2. (only if elevation_fn is supplied) Terrain at every step along
         the great-circle never rises above the descending glide line.

    `elevation_fn(lat, lon)` returns meters MSL. NaN return is treated
    as "data unknown, do not block" — same fail-safe as the corridor.
    """
    if glide_ratio <= 0:
        return False
    distance_nm = haversine_nm(sample_lat, sample_lon, ap_lat, ap_lon)
    if distance_nm <= 0:
        return sample_msl_ft >= ap_elev_ft
    bearing = initial_bearing_deg(sample_lat, sample_lon, ap_lat, ap_lon)

    effective_gr = glide_ratio * _wind_scale(
        bearing, wind_dir_deg, wind_speed_kt, glide_ias_kt)
    descent_ft_per_nm = FT_PER_NM / effective_gr

    arrival_alt_ft = sample_msl_ft - distance_nm * descent_ft_per_nm
    if arrival_alt_ft < ap_elev_ft:
        return False

    if elevation_fn is None:
        return True

    d = terrain_step_nm
    while d < distance_nm:
        plat, plon = _offset_latlon(sample_lat, sample_lon, bearing, d)
        terrain_m = elevation_fn(plat, plon)
        if terrain_m == terrain_m:    # not NaN
            terrain_ft = terrain_m * FT_PER_M
            glide_alt_ft = sample_msl_ft - d * descent_ft_per_nm
            if glide_alt_ft < terrain_ft:
                return False
        d += terrain_step_nm
    return True


def find_diverts_in_glide(
    airport_data: list[dict],
    sample_lat: float, sample_lon: float, sample_msl_ft: float,
    glide_ratio: float,
    glide_ias_kt: float = 75.0,
    wind_dir_deg: float = 0.0, wind_speed_kt: float = 0.0,
    min_runway_ft: int = DEFAULT_MIN_RUNWAY_FT,
    elevation_fn: Optional[ElevationFn] = None,
    terrain_step_nm: float = 0.5,
) -> list[dict]:
    """Like find_diverts_in_reach, but reach is computed per-airport
    from the engine-out glide line + optional terrain ridge-clip.

    Returns list of {airport, distance_nm} sorted by distance.
    """
    if sample_msl_ft <= 0 or glide_ratio <= 0:
        return []
    # Conservative bbox: max still-air reach at zero airport elevation
    # = sample_msl × gr / FT_PER_NM, scaled by max possible tailwind
    # boost (1 + wind_speed/IAS).
    boost = 1.0 + wind_speed_kt / max(1.0, glide_ias_kt)
    max_reach_nm = sample_msl_ft * glide_ratio / FT_PER_NM * max(1.0, boost)
    pad_lat = max_reach_nm / 60.0
    pad_lon = pad_lat / max(0.1, math.cos(math.radians(sample_lat)))
    lat_lo, lat_hi = sample_lat - pad_lat, sample_lat + pad_lat
    lon_lo, lon_hi = sample_lon - pad_lon, sample_lon + pad_lon

    out: list[dict] = []
    for ap in airport_data:
        a_lat = ap.get("lat")
        a_lon = ap.get("lon")
        if a_lat is None or a_lon is None:
            continue
        if a_lat < lat_lo or a_lat > lat_hi or a_lon < lon_lo or a_lon > lon_hi:
            continue
        if not is_landable(ap, min_runway_ft):
            continue
        if can_glide_to(
            sample_lat, sample_lon, sample_msl_ft,
            a_lat, a_lon, ap.get("elevation_ft") or 0.0,
            glide_ratio=glide_ratio, glide_ias_kt=glide_ias_kt,
            wind_dir_deg=wind_dir_deg, wind_speed_kt=wind_speed_kt,
            elevation_fn=elevation_fn,
            terrain_step_nm=terrain_step_nm,
        ):
            out.append({
                "airport": ap,
                "distance_nm": haversine_nm(sample_lat, sample_lon, a_lat, a_lon),
            })
    out.sort(key=lambda r: r["distance_nm"])
    return out


def divert_coverage_along_route_glide(
    samples: list[tuple[float, float]],
    airport_data: list[dict],
    cruise_alt_msl_ft: float,
    glide_ratio: float,
    glide_ias_kt: float = 75.0,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    min_runway_ft: int = DEFAULT_MIN_RUNWAY_FT,
    elevation_fn: Optional[ElevationFn] = None,
    terrain_step_nm: float = 0.5,
    sample_alts_msl_ft: Optional[list[float]] = None,
    sample_winds: Optional[list[tuple[float, float]]] = None,
) -> dict:
    """Per-sample divert coverage using engine-out glide + (optionally)
    terrain ridge-clipping.

    Same return shape as `divert_coverage_along_route`. Two optional
    per-sample lists when supplied with matching length:
      - `sample_alts_msl_ft`: altitude at each sample (flight profile)
      - `sample_winds`: (dir, speed) at each sample (winds aloft)
    Length mismatch silently falls back to the scalar values.
    """
    if sample_alts_msl_ft is not None and len(sample_alts_msl_ft) == len(samples):
        per_sample_alt = list(sample_alts_msl_ft)
    else:
        per_sample_alt = [cruise_alt_msl_ft] * len(samples)
    if sample_winds is not None and len(sample_winds) == len(samples):
        per_sample_wind = list(sample_winds)
    else:
        per_sample_wind = [(wind_dir_deg, wind_speed_kt)] * len(samples)

    per_sample: list[list[str]] = []
    uniq_min_dist: dict[str, float] = {}
    uniq_n_samples: dict[str, int] = {}
    uniq_ap: dict[str, dict] = {}
    for (lat, lon), sample_msl, (s_wd, s_ws) in zip(
        samples, per_sample_alt, per_sample_wind,
    ):
        hits = find_diverts_in_glide(
            airport_data, lat, lon,
            sample_msl_ft=sample_msl,
            glide_ratio=glide_ratio,
            glide_ias_kt=glide_ias_kt,
            wind_dir_deg=s_wd, wind_speed_kt=s_ws,
            min_runway_ft=min_runway_ft,
            elevation_fn=elevation_fn,
            terrain_step_nm=terrain_step_nm,
        )
        ids = []
        for h in hits:
            ap = h["airport"]
            apid = ap.get("id") or ap.get("icao")
            if not apid:
                continue
            ids.append(apid)
            d = h["distance_nm"]
            if apid not in uniq_min_dist or d < uniq_min_dist[apid]:
                uniq_min_dist[apid] = d
                uniq_ap[apid] = ap
            uniq_n_samples[apid] = uniq_n_samples.get(apid, 0) + 1
        per_sample.append(ids)

    unique_diverts = [
        {"airport": uniq_ap[apid],
         "min_distance_nm": round(uniq_min_dist[apid], 1),
         "n_samples": uniq_n_samples[apid]}
        for apid in uniq_min_dist
    ]
    unique_diverts.sort(key=lambda r: r["min_distance_nm"])

    no_cov = sum(1 for s in per_sample if not s)
    return {
        "per_sample": per_sample,
        "unique_diverts": unique_diverts,
        "n_samples_with_coverage": len(per_sample) - no_cov,
        "n_samples_with_no_coverage": no_cov,
        "terrain_used": elevation_fn is not None,
    }
