"""VFR XC checkpoint generator — glide-biased landmark selection.

Given a route, walks the great-circle in ~6-minute intervals (scaled
by cruise TAS so a 90 kt 172 gets denser checkpoints than a 200 kt
King Air) and picks the best landmark inside a perpendicular wedge
around each interval. Candidates come from airports + VORs + IFR
fixes. Scoring penalizes checkpoints with no airport-in-glide and
bonuses checkpoints that ARE airports themselves — so the resulting
nav log naturally leans the route toward "always have somewhere to
land" coverage. That's the moat.

Anchored to:
    FAA-H-8083-25B Ch. 16 — pilotage + dead-reckoning checkpoint
                            selection criteria (visible-from-air,
                            positive identification, 10-15 NM typical
                            spacing for training)
    AC 91-92                — checkpoint spacing rules of thumb
    FAA-S-ACS-6B Area V.A   — Private Pilot ACS nav log requirements
    AFH Ch. 16-17           — landmark hierarchy
    AC 91-79 (peripheral)   — divert proximity as a safety lever

Output Checkpoint dict shape:
    {
        "lat": float, "lon": float,
        "name": str, "ident": str, "kind": "airport|vor|ndb|fix",
        "frequency_mhz": float | None,
        "cumulative_nm": float,
        "leg_dist_nm": float,
        "true_bearing": float,
        "magnetic_bearing": float,
        "ete_min": float,
        "glide_margin_ft": float,   # alt available − alt needed
        "nearest_divert_id": str,
        "nearest_divert_nm": float,
        "score": int,                # for debugging / sorting
        "notes": str,
        "synthetic": bool,           # True for auto-inserted gap-fillers
    }
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal

from core.route import (
    haversine_nm,
    initial_bearing_deg,
    magvar_west_positive,
    true_to_magnetic,
)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

DEFAULT_CHECKPOINT_MINUTES = 6.0       # AC 91-92 / training rule of thumb
MIN_SPACING_NM = 4.0                   # don't bunch checkpoints too close
MAX_SPACING_NM = 25.0                  # don't go too long even at jet speeds
DEFAULT_WEDGE_HALF_WIDTH_NM = 5.0
# How far an airport can be from a checkpoint and still count as an
# "in-glide divert" for the moat bonus.
GLIDE_REACH_MARGIN_FT = 500.0          # extra safety on top of bare-glide

# Score weights — easy to tune without changing the algorithm shape.
W_IS_AIRPORT = 50
W_NAMED_AIRPORT_BONUS = 30
W_IS_VOR = 20
W_IS_FIX = 10
W_IS_CITY = 28                         # cities ≥ 5k — strong visual landmark
W_IS_BIG_CITY_BONUS = 12               # cities ≥ 50k (e.g. county seat)
W_IS_RIVER_XING = 22                   # named river crossing
W_IS_ROAD_JCT = 18                     # primary road junction
W_DUAL_USE = 10                        # airport + co-located VOR
W_PROX_MAX = 25
W_GLIDE_SAFE = 30
W_OUT_OF_GLIDE_PENALTY = -40
W_DUPLICATE_PENALTY = -20
W_TOO_CLOSE_PENALTY = -15


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _gc_step(lat1: float, lon1: float,
              lat2: float, lon2: float, f: float) -> tuple[float, float]:
    """Linear interpolation along the great-circle from (lat1,lon1) to
    (lat2,lon2). For short legs (< ~500 NM) this is indistinguishable
    from full GC interpolation and 10x cheaper. We use straight-line
    in lat/lon for clarity."""
    return (lat1 + f * (lat2 - lat1), lon1 + f * (lon2 - lon1))


def _perpendicular_offset_nm(point: tuple[float, float],
                              leg_a: tuple[float, float],
                              leg_b: tuple[float, float]) -> float:
    """Perpendicular distance (in NM) from `point` to the great-circle
    segment a→b. Approximation: project onto the rhumb-line, fine for
    short legs."""
    ax, ay = leg_a[1], leg_a[0]
    bx, by = leg_b[1], leg_b[0]
    px, py = point[1], point[0]
    # Convert to NM by scaling lon by cos(midlat).
    midlat = (leg_a[0] + leg_b[0]) / 2.0
    coslat = math.cos(math.radians(midlat))
    ax, bx, px = ax * coslat, bx * coslat, px * coslat
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    seg_len_sq = abx * abx + aby * aby
    if seg_len_sq < 1e-12:
        return math.hypot(apx, apy) * 60.0  # degrees → NM
    t = (apx * abx + apy * aby) / seg_len_sq
    t = max(0.0, min(1.0, t))
    proj_x, proj_y = ax + t * abx, ay + t * aby
    return math.hypot(px - proj_x, py - proj_y) * 60.0


# ---------------------------------------------------------------------------
# Glide-divert lookup
# ---------------------------------------------------------------------------

def _nearest_divert(point: tuple[float, float], airports: list[dict],
                     cruise_alt_msl_ft: float, glide_ratio: float
                     ) -> tuple[Optional[dict], float, float]:
    """Find the closest airport whose distance from `point` is within
    glide reach at cruise altitude. Returns (airport, dist_nm, margin_ft).

    A NEGATIVE margin means the airport is OUT of glide (alt needed
    exceeds altitude available).
    """
    best_within = None
    best_within_dist = 1e9
    best_within_margin = -1e9
    # Fallback: closest airport regardless of glide reach — surfaced when
    # nothing is in glide, so the pilot at least sees the nearest field.
    best_any = None
    best_any_dist = 1e9
    best_any_margin = -1e9

    for ap in airports:
        try:
            ap_lat = float(ap.get("lat"))
            ap_lon = float(ap.get("lon"))
        except (TypeError, ValueError):
            continue
        d = haversine_nm(point[0], point[1], ap_lat, ap_lon)
        if d > 50.0:  # cheap bbox-ish filter; 50 NM covers any sensible glide
            continue
        elev = float(ap.get("elevation_ft") or 0.0)
        alt_avail = cruise_alt_msl_ft - elev
        alt_needed = d * 6076.115 / max(0.1, glide_ratio)
        margin = alt_avail - alt_needed - GLIDE_REACH_MARGIN_FT

        if d < best_any_dist:
            best_any_dist = d
            best_any = ap
            best_any_margin = margin
        if margin > 0 and d < best_within_dist:
            best_within_dist = d
            best_within = ap
            best_within_margin = margin

    if best_within is not None:
        return best_within, best_within_dist, best_within_margin
    return best_any, best_any_dist, best_any_margin


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    lat: float
    lon: float
    ident: str
    name: str
    kind: Literal["airport", "vor", "ndb", "fix", "city", "river", "road_jct"]
    frequency_mhz: Optional[float] = None
    elevation_ft: Optional[float] = None
    population: int = 0                  # cities only
    # Computed during scoring:
    offset_nm: float = 0.0
    glide_margin_ft: float = 0.0
    nearest_divert_id: str = ""
    nearest_divert_nm: float = 0.0
    score: int = 0
    notes: str = ""


def _score_candidate(c: _Candidate,
                      target_point: tuple[float, float],
                      cruise_alt_msl_ft: float, glide_ratio: float,
                      airports: list[dict],
                      already_used_idents: set[str],
                      already_used_positions: list[tuple[float, float]],
                      ) -> None:
    """In-place: write c.score + c.notes + c.glide_* fields."""
    s = 0
    parts: list[str] = []

    # 1. Landmark type
    if c.kind == "airport":
        s += W_IS_AIRPORT
        # Bonus for "named" airports (have an IATA, not just LID code)
        if c.ident and not c.ident.startswith("US-") and len(c.ident) <= 4:
            s += W_NAMED_AIRPORT_BONUS
            parts.append("named airport")
        else:
            parts.append("airport")
    elif c.kind == "vor":
        s += W_IS_VOR
        parts.append("VOR")
    elif c.kind == "ndb":
        s += W_IS_VOR // 2
        parts.append("NDB")
    elif c.kind == "fix":
        s += W_IS_FIX
        parts.append("fix")
    elif c.kind == "city":
        s += W_IS_CITY
        if c.population >= 50000:
            s += W_IS_BIG_CITY_BONUS
            parts.append(f"city ({c.population:,})")
        else:
            parts.append(f"town ({c.population:,})")
    elif c.kind == "river":
        s += W_IS_RIVER_XING
        parts.append(f"{c.name} crossing")
    elif c.kind == "road_jct":
        s += W_IS_ROAD_JCT
        parts.append(f"jct {c.name}")

    # 2. Proximity to course — closer is better, linear up to W_PROX_MAX.
    prox_score = max(0, W_PROX_MAX - int(c.offset_nm * (W_PROX_MAX / 5.0)))
    s += prox_score
    if c.offset_nm < 0.5:
        parts.append("on course")
    elif c.offset_nm < 2.0:
        parts.append(f"{c.offset_nm:.1f} NM off course")
    else:
        parts.append(f"{c.offset_nm:.0f} NM off course")

    # 3. Glide-divert proximity (the moat).
    near_ap, near_dist, near_margin = _nearest_divert(
        (c.lat, c.lon), airports, cruise_alt_msl_ft, glide_ratio,
    )
    c.glide_margin_ft = near_margin
    if near_ap is not None:
        c.nearest_divert_id = near_ap.get("id") or ""
        c.nearest_divert_nm = near_dist
        if near_margin > 0:
            s += W_GLIDE_SAFE
            if c.kind == "airport" and near_dist < 0.1:
                # Self-reference: it IS the divert.
                parts.append("IS the divert")
            else:
                parts.append(f"in glide of {c.nearest_divert_id} ({near_dist:.0f} NM)")
        else:
            s += W_OUT_OF_GLIDE_PENALTY
            parts.append(
                f"OUT OF GLIDE (nearest {c.nearest_divert_id} {near_dist:.0f} NM, "
                f"need {-near_margin:.0f} ft more)"
            )

    # 4. Dual-use bonus: an airport that also has a VOR colocated
    #    (within 1 NM) is the gold-standard checkpoint.
    if c.kind == "airport":
        # The caller passes a flat airports list; we don't have navaids
        # here directly. The dual-use check is done by the caller before
        # invoking this function, which can set notes.
        pass

    # 5. Penalties
    if c.ident in already_used_idents:
        s += W_DUPLICATE_PENALTY
        parts.append("DUPE penalty")
    for prev in already_used_positions:
        d_prev = haversine_nm(c.lat, c.lon, prev[0], prev[1])
        if d_prev < MIN_SPACING_NM:
            s += W_TOO_CLOSE_PENALTY
            parts.append(f"too close to prior cp ({d_prev:.1f} NM)")
            break

    c.score = s
    c.notes = " · ".join(parts)


def _collect_candidates(target_point: tuple[float, float],
                         leg_a: tuple[float, float],
                         leg_b: tuple[float, float],
                         wedge_half_width_nm: float,
                         airports: list[dict],
                         navaids: list[dict],
                         fixes: list[dict],
                         landmarks: Optional[list[dict]] = None,
                         ) -> list[_Candidate]:
    """Enumerate every airport / navaid / fix inside the perpendicular
    wedge around `target_point` along the leg."""
    out: list[_Candidate] = []
    tp_lat, tp_lon = target_point

    # Cheap pre-filter bbox around the wedge to avoid scanning all 50k
    # airports per checkpoint.
    bbox_pad = wedge_half_width_nm / 60.0 + 0.05
    lat_min = tp_lat - bbox_pad
    lat_max = tp_lat + bbox_pad
    coslat = math.cos(math.radians(tp_lat)) or 0.5
    lon_min = tp_lon - bbox_pad / coslat
    lon_max = tp_lon + bbox_pad / coslat

    def _in_bbox(lat: float, lon: float) -> bool:
        return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max

    for ap in airports:
        try:
            lat = float(ap.get("lat")); lon = float(ap.get("lon"))
        except (TypeError, ValueError):
            continue
        if not _in_bbox(lat, lon):
            continue
        # Skip categorically-bad checkpoints — closed airports, the
        # very smallest fields are usually private/grass and not great
        # references; keep medium/large/small for now.
        if ap.get("type") not in ("large_airport", "medium_airport", "small_airport"):
            continue
        off = _perpendicular_offset_nm((lat, lon), leg_a, leg_b)
        if off > wedge_half_width_nm:
            continue
        out.append(_Candidate(
            lat=lat, lon=lon,
            ident=ap.get("id") or ap.get("icao") or "?",
            name=ap.get("name") or "?",
            kind="airport",
            elevation_ft=float(ap.get("elevation_ft") or 0.0),
            offset_nm=off,
        ))

    for nv in navaids:
        try:
            lat = float(nv.get("lat")); lon = float(nv.get("lon"))
        except (TypeError, ValueError):
            continue
        if not _in_bbox(lat, lon):
            continue
        nv_type = (nv.get("type") or "").upper()
        if nv_type in ("VOR", "VOR-DME", "VORTAC", "DME", "TACAN"):
            kind = "vor"
        elif nv_type in ("NDB",):
            kind = "ndb"
        else:
            continue
        off = _perpendicular_offset_nm((lat, lon), leg_a, leg_b)
        if off > wedge_half_width_nm:
            continue
        freq = nv.get("freq_mhz")
        try:
            freq = float(freq) if freq is not None else None
        except (TypeError, ValueError):
            freq = None
        out.append(_Candidate(
            lat=lat, lon=lon,
            ident=nv.get("ident") or "?",
            name=nv.get("name") or "?",
            kind=kind,
            frequency_mhz=freq,
            offset_nm=off,
        ))

    # Fixes are only good fillers if nothing better is around — they
    # don't have visible-from-air landmarks. Cap at half-width / 2 so
    # we only pick them when really close to course.
    fix_half = wedge_half_width_nm / 2.0
    # Note: visual landmarks (cities / rivers / road junctions) are
    # added by the caller as a separate `extra_candidates` argument.
    # Keeping the OSM dependency out of the inner loop lets us cache
    # the fetch by route bbox without re-running per-interval.
    for fx in fixes:
        try:
            lat = float(fx.get("lat")); lon = float(fx.get("lon"))
        except (TypeError, ValueError):
            continue
        if not _in_bbox(lat, lon):
            continue
        off = _perpendicular_offset_nm((lat, lon), leg_a, leg_b)
        if off > fix_half:
            continue
        out.append(_Candidate(
            lat=lat, lon=lon,
            ident=fx.get("ident") or "?",
            name=fx.get("ident") or "?",
            kind="fix",
            offset_nm=off,
        ))

    # Visual landmarks (cities, rivers, road junctions) from OSM.
    # Already pre-fetched for the whole route bbox by the caller; we
    # just filter to the wedge here.
    for lm in (landmarks or []):
        try:
            lat = float(lm.get("lat")); lon = float(lm.get("lon"))
        except (TypeError, ValueError):
            continue
        if not _in_bbox(lat, lon):
            continue
        off = _perpendicular_offset_nm((lat, lon), leg_a, leg_b)
        if off > wedge_half_width_nm:
            continue
        kind = lm.get("kind")
        if kind not in ("city", "river", "road_jct"):
            continue
        out.append(_Candidate(
            lat=lat, lon=lon,
            ident=lm.get("ident") or "?",
            name=lm.get("name") or "?",
            kind=kind,
            population=int(lm.get("population", 0) or 0),
            offset_nm=off,
        ))

    return out


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------

def suggest_checkpoints(
    waypoints: list[dict],
    cruise_alt_msl_ft: float,
    tas_kt: float,
    glide_ratio: float,
    airports: list[dict],
    navaids: list[dict],
    fixes: list[dict],
    landmarks: Optional[list[dict]] = None,
    spacing_minutes: float = DEFAULT_CHECKPOINT_MINUTES,
    spacing_nm_override: Optional[float] = None,
    wedge_half_width_nm: float = DEFAULT_WEDGE_HALF_WIDTH_NM,
    ground_speed_kt: Optional[float] = None,
) -> list[dict]:
    """Generate FAA-style VFR checkpoints along a multi-leg route.

    Spacing scales with `tas_kt` (or `ground_speed_kt` if provided):
    target = `spacing_minutes` × GS / 60, clamped to [MIN, MAX] NM.

    A 172 at 100 KIAS gets a checkpoint every ~10 NM; a King Air at
    200 KIAS gets one every ~20 NM. Pilot can hard-override via
    `spacing_nm_override`.

    The result is the ORDERED checkpoint list (does NOT include the
    origin / destination waypoints themselves).
    """
    if len(waypoints) < 2:
        return []

    gs = float(ground_speed_kt or tas_kt or 100.0)
    if spacing_nm_override is not None and spacing_nm_override > 0:
        target_nm = float(spacing_nm_override)
    else:
        target_nm = max(MIN_SPACING_NM,
                         min(MAX_SPACING_NM, spacing_minutes * gs / 60.0))

    out: list[dict] = []
    used_idents: set[str] = set()
    used_positions: list[tuple[float, float]] = []
    cumulative_nm = 0.0
    prev_point = (float(waypoints[0]["lat"]), float(waypoints[0]["lon"]))

    for i in range(len(waypoints) - 1):
        a = waypoints[i]
        b = waypoints[i + 1]
        a_pos = (float(a["lat"]), float(a["lon"]))
        b_pos = (float(b["lat"]), float(b["lon"]))
        leg_nm = haversine_nm(a_pos[0], a_pos[1], b_pos[0], b_pos[1])
        if leg_nm < target_nm * 0.6:
            # Leg is too short to need an intermediate — skip.
            cumulative_nm += leg_nm
            prev_point = b_pos
            continue

        # Walk the leg in target_nm steps.
        n_steps = max(1, int(round(leg_nm / target_nm)) - 1)
        step_nm = leg_nm / (n_steps + 1)

        for k in range(1, n_steps + 1):
            f = k * step_nm / leg_nm
            tp = _gc_step(a_pos[0], a_pos[1], b_pos[0], b_pos[1], f)

            candidates = _collect_candidates(
                tp, a_pos, b_pos, wedge_half_width_nm,
                airports, navaids, fixes,
                landmarks=landmarks,
            )
            if not candidates:
                continue

            # Strict dedup: any candidate already chosen is OUT for
            # this interval (the soft-penalty wasn't enough — a high-
            # scoring airport would still beat fresh alternatives by
            # the time the penalty applied).
            candidates = [c for c in candidates if c.ident not in used_idents]
            if not candidates:
                continue

            for c in candidates:
                _score_candidate(
                    c, tp, cruise_alt_msl_ft, glide_ratio,
                    airports, used_idents, used_positions,
                )

            best = max(candidates, key=lambda c: c.score)

            # Also reject if the BEST candidate ends up within
            # MIN_SPACING_NM of the previous chosen checkpoint — the
            # too-close penalty alone isn't enough when the only
            # alternative scores much lower.
            if used_positions:
                prev_pos = used_positions[-1]
                if haversine_nm(best.lat, best.lon,
                                  prev_pos[0], prev_pos[1]) < MIN_SPACING_NM:
                    continue

            # Compute cumulative distance + bearings at the chosen pt.
            chosen_pos = (best.lat, best.lon)
            seg_nm = haversine_nm(prev_point[0], prev_point[1],
                                    chosen_pos[0], chosen_pos[1])
            cumulative_nm += seg_nm
            true_bearing = initial_bearing_deg(
                prev_point[0], prev_point[1],
                chosen_pos[0], chosen_pos[1],
            )
            magvar = magvar_west_positive(chosen_pos[0], chosen_pos[1])
            mag_bearing = true_to_magnetic(true_bearing, magvar)
            ete_min = (seg_nm / max(1.0, gs)) * 60.0

            out.append({
                "lat": float(best.lat),
                "lon": float(best.lon),
                "name": best.name,
                "ident": best.ident,
                "kind": best.kind,
                "frequency_mhz": best.frequency_mhz,
                "cumulative_nm": round(cumulative_nm, 1),
                "leg_dist_nm": round(seg_nm, 1),
                "true_bearing": round(true_bearing, 0),
                "magnetic_bearing": round(mag_bearing, 0),
                "ete_min": round(ete_min, 1),
                "glide_margin_ft": round(best.glide_margin_ft, 0),
                "nearest_divert_id": best.nearest_divert_id,
                "nearest_divert_nm": round(best.nearest_divert_nm, 1),
                "score": best.score,
                "notes": best.notes,
                "synthetic": False,
                # Which USER leg this checkpoint belongs to (0-indexed
                # from origin). Lets the caller interleave checkpoints
                # cleanly with intermediate user waypoints when
                # building a bent polyline.
                "leg_idx": i,
            })
            used_idents.add(best.ident)
            used_positions.append(chosen_pos)
            prev_point = chosen_pos

        # Tally the final segment from the last cp (or leg start) to the
        # leg's endpoint so the next leg's cumulative_nm is right.
        cumulative_nm += haversine_nm(prev_point[0], prev_point[1],
                                       b_pos[0], b_pos[1])
        prev_point = b_pos

    return out


def coverage_summary(samples: list[tuple[float, float]],
                      sample_alts_msl_ft: list[float],
                      airports: list[dict],
                      glide_ratio: float) -> dict:
    """Per-sample glide-divert coverage along the route.

    Returns:
        {
            "n_samples": int,
            "n_in_glide": int,
            "pct_in_glide": float,
            "longest_gap_nm": float,
            "worst_exposure_idx": int | None,   # sample index of the start of the worst gap
        }
    """
    if not samples or not sample_alts_msl_ft or len(samples) != len(sample_alts_msl_ft):
        return {"n_samples": 0, "n_in_glide": 0, "pct_in_glide": 0.0,
                "longest_gap_nm": 0.0, "worst_exposure_idx": None}

    in_glide_flags: list[bool] = []
    for (lat, lon), alt_msl in zip(samples, sample_alts_msl_ft):
        _, _, margin = _nearest_divert(
            (lat, lon), airports, alt_msl, glide_ratio,
        )
        in_glide_flags.append(margin > 0)

    n = len(in_glide_flags)
    n_in = sum(in_glide_flags)
    pct = (n_in / n) * 100.0 if n else 0.0

    # Find the longest contiguous run of FALSE.
    longest = 0
    longest_start = None
    cur_len = 0
    cur_start = None
    for i, ok in enumerate(in_glide_flags):
        if not ok:
            if cur_start is None:
                cur_start = i
            cur_len += 1
            if cur_len > longest:
                longest = cur_len
                longest_start = cur_start
        else:
            cur_len = 0
            cur_start = None

    # Convert run-length to NM by summing the haversine spacings.
    longest_nm = 0.0
    if longest_start is not None:
        for i in range(longest_start, longest_start + longest - 1):
            if i + 1 < n:
                longest_nm += haversine_nm(
                    samples[i][0], samples[i][1],
                    samples[i + 1][0], samples[i + 1][1],
                )

    return {
        "n_samples": n,
        "n_in_glide": n_in,
        "pct_in_glide": round(pct, 1),
        "longest_gap_nm": round(longest_nm, 1),
        "worst_exposure_idx": longest_start,
    }
