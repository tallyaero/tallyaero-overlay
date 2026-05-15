"""Divert-airport reach analysis along a planned route.

For each route sample point, find the airports an engine-out glide
could reach from that altitude. Aggregate to:
  - the unique set of reachable divert airports along the route
  - "unsupported gap" segments where NO airport is reachable
  - per-sample reachability for downstream rendering

Reach math is matched to the corridor (still-air NM × wind scale).
Terrain ridge-clip from core.corridor isn't applied here yet — the
unsupported-gap metric is therefore a slight under-count (terrain may
block some flat-line diverts). Phase 7g+ adds terrain-aware divert
reach by reusing terrain_intercept_nm per (sample, airport) bearing.

Filter rules for "landable":
  - Skip seaplane bases (wheeled aircraft can't land on water).
  - Skip airports with no usable runway data unless they are
    large/medium type (those almost certainly have plenty of runway).
  - Require at least one runway >= min_runway_ft when runway data
    exists.
"""
from __future__ import annotations

import math
from typing import Iterable

from core.route import haversine_nm, EARTH_RADIUS_NM

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
