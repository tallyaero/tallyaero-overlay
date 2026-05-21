"""Engine-out trajectory executor — forward integrator that follows a
pre-built `GlidePlan` from `simulation.eo_planner`.

The planner produces geometric segments (straight / turn / spiral). The
executor walks each segment at small time steps and emits position
samples in the same (path, hover_data, metadata) shape the legacy
`simulate_engineout_glide` returned — so the engineout callback, the
scrubber, the 3D side view, and the results modal all keep working
without touching their consumers.

Per-tick state:
  position (lat, lon)
  altitude AGL
  heading (deg true)
  track (deg true) — equals heading in calm wind; drifts in wind
  TAS (kt) — held at best-glide
  bank (deg, signed)
  phase string — derived from current segment label
  time (sec)

Wind handling: the executor treats heading = wind-corrected to maintain
the planned ground track. The aircraft "crabs" through wind by adjusting
heading; the visible trajectory matches the planner's geometry.
Altitude burn during a segment is computed by the planner (start_alt →
end_alt) so the per-tick interpolation is linear in arc-length.
"""

from __future__ import annotations

import math
from typing import Optional

from geopy import Point as GeoPoint
from geopy.distance import distance as geo_distance

from .eo_planner import GlidePlan, GlideSegment


FT_PER_NM = 6076.115
KT_TO_FPS = 1.68781


# =============================================================================
# Helpers
# =============================================================================

def _bearing(p1: GeoPoint, p2: GeoPoint) -> float:
    lat1 = math.radians(p1.latitude); lat2 = math.radians(p2.latitude)
    dlon = math.radians(p2.longitude - p1.longitude)
    y = math.sin(dlon) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(y, x))) % 360.0


def _offset_point(origin: GeoPoint, bearing_deg: float,
                    distance_ft: float) -> GeoPoint:
    return geo_distance(feet=distance_ft).destination(origin, bearing_deg)


def _ground_speed_kt(tas_kt: float, track_deg: float,
                       wind_dir_deg: float, wind_speed_kt: float) -> float:
    """Ground speed along bearing `track_deg` with wind from `wind_dir_deg`."""
    angle = math.radians((wind_dir_deg - track_deg + 540.0) % 360.0 - 180.0)
    headwind = wind_speed_kt * math.cos(angle)
    return max(1.0, tas_kt - headwind)


# =============================================================================
# Per-segment samplers
# =============================================================================

def _sample_straight(seg: GlideSegment, dt: float, tas_kt: float,
                       wind_dir_deg: float, wind_speed_kt: float,
                       time_start: float) -> tuple[list[dict], float]:
    """Sample a straight segment at fixed dt steps."""
    start = GeoPoint(seg.start_lat, seg.start_lon)
    end = GeoPoint(seg.end_lat, seg.end_lon)
    track = _bearing(start, end) if seg.ground_distance_ft > 1e-3 \
             else seg.start_heading_deg
    gs_kt = _ground_speed_kt(tas_kt, track, wind_dir_deg, wind_speed_kt)
    gs_fps = gs_kt * KT_TO_FPS
    if seg.ground_distance_ft < 1e-3 or gs_fps < 1e-3:
        return [], time_start
    duration_sec = seg.ground_distance_ft / gs_fps
    n_steps = max(1, int(math.ceil(duration_sec / dt)))
    # Vertical speed for this segment (fpm, negative = descending)
    vs_fpm = ((seg.end_alt_agl_ft - seg.start_alt_agl_ft)
                / max(1e-3, duration_sec) * 60.0)

    # Crab angle: to maintain the desired track in crosswind, the
    # aircraft must point its nose into the wind. Positive crab = nose
    # to the right of track (= heading > track).
    #   crosswind_kt = -wind_speed × sin(wind_dir − track)
    #     (positive crosswind component pushes aircraft right of track)
    #   crab = asin(crosswind / TAS) flips the sign — aircraft yaws
    #   opposite the push direction so its track stays on the desired
    #   line.
    if wind_speed_kt > 0.1 and tas_kt > 1.0:
        wind_perp_kt = wind_speed_kt * math.sin(
            math.radians(wind_dir_deg - track))
        crab_arg = max(-1.0, min(1.0, wind_perp_kt / tas_kt))
        crab_deg = math.degrees(math.asin(crab_arg))
    else:
        crab_deg = 0.0
    heading_with_crab = (track + crab_deg) % 360.0

    samples: list[dict] = []
    for k in range(1, n_steps + 1):
        f = k / n_steps
        # Linear interpolate position along the segment
        dist_ft = seg.ground_distance_ft * f
        pos = _offset_point(start, track, dist_ft)
        alt = (seg.start_alt_agl_ft +
               f * (seg.end_alt_agl_ft - seg.start_alt_agl_ft))
        t = time_start + f * duration_sec
        samples.append({
            "lat": pos.latitude,
            "lon": pos.longitude,
            "alt_agl": alt,
            "heading": heading_with_crab,
            "track": track,
            "crab": crab_deg,
            "bank": 0.0,
            "tas": tas_kt,
            "gs": gs_kt,
            "vs": vs_fpm,
            "time": t,
            "phase": _phase_for(seg),
        })
    return samples, time_start + duration_sec


def _sample_turn(seg: GlideSegment, dt: float, tas_kt: float,
                   wind_dir_deg: float, wind_speed_kt: float,
                   time_start: float) -> tuple[list[dict], float]:
    """Sample a constant-radius arc."""
    center = GeoPoint(seg.center_lat, seg.center_lon)
    R = seg.turn_radius_ft
    bank = math.degrees(math.atan(
        (tas_kt * KT_TO_FPS) ** 2 / (32.174 * R)))
    sign = 1.0 if (seg.turn_angle_deg or 0) > 0 else -1.0
    # Compute the radial bearing at start (from center to start position)
    start_pt = GeoPoint(seg.start_lat, seg.start_lon)
    radial_at_start = _bearing(center, start_pt)
    total_angle = abs(seg.turn_angle_deg or 180.0)
    # Average ground speed on arc — depends on track; use TAS as approximation
    # since the arc's heading changes continuously
    avg_gs_kt = tas_kt  # wind drift averages out on a closed arc
    arc_speed_fps = avg_gs_kt * KT_TO_FPS
    duration_sec = seg.ground_distance_ft / max(1.0, arc_speed_fps)
    n_steps = max(4, int(math.ceil(duration_sec / dt)))
    vs_fpm = ((seg.end_alt_agl_ft - seg.start_alt_agl_ft)
                / max(1e-3, duration_sec) * 60.0)

    samples: list[dict] = []
    for k in range(1, n_steps + 1):
        f = k / n_steps
        # Walk the radial bearing from start by f × total_angle in `sign` direction
        radial = (radial_at_start + sign * f * total_angle) % 360.0
        pos = _offset_point(center, radial, R)
        # Heading along the arc is perpendicular to the radial (in direction
        # of motion)
        heading = (radial + sign * 90.0) % 360.0
        alt = (seg.start_alt_agl_ft +
               f * (seg.end_alt_agl_ft - seg.start_alt_agl_ft))
        t = time_start + f * duration_sec
        samples.append({
            "lat": pos.latitude,
            "lon": pos.longitude,
            "alt_agl": alt,
            "heading": heading,
            "track": heading,
            "bank": sign * bank,
            "tas": tas_kt,
            "gs": avg_gs_kt,
            "vs": vs_fpm,
            "time": t,
            "phase": _phase_for(seg),
        })
    return samples, time_start + duration_sec


def _sample_spiral(seg: GlideSegment, dt: float, tas_kt: float,
                     wind_dir_deg: float, wind_speed_kt: float,
                     time_start: float) -> tuple[list[dict], float]:
    """Sample N orbits around the spiral center."""
    center = GeoPoint(seg.center_lat, seg.center_lon)
    R = seg.turn_radius_ft
    bank = seg.spiral_bank_deg
    sign = -1.0 if seg.spiral_direction == "left" else 1.0
    start_pt = GeoPoint(seg.start_lat, seg.start_lon)
    radial_at_start = _bearing(center, start_pt)
    n_turns = seg.spiral_turns
    total_angle = abs(n_turns * 360.0)
    arc_speed_fps = tas_kt * KT_TO_FPS
    duration_sec = seg.ground_distance_ft / max(1.0, arc_speed_fps)
    n_steps = max(int(n_turns * 12), int(math.ceil(duration_sec / dt)))
    vs_fpm = ((seg.end_alt_agl_ft - seg.start_alt_agl_ft)
                / max(1e-3, duration_sec) * 60.0)

    samples: list[dict] = []
    for k in range(1, n_steps + 1):
        f = k / n_steps
        radial = (radial_at_start + sign * f * total_angle) % 360.0
        pos = _offset_point(center, radial, R)
        heading = (radial + sign * 90.0) % 360.0
        alt = (seg.start_alt_agl_ft +
               f * (seg.end_alt_agl_ft - seg.start_alt_agl_ft))
        t = time_start + f * duration_sec
        samples.append({
            "lat": pos.latitude,
            "lon": pos.longitude,
            "alt_agl": alt,
            "heading": heading,
            "track": heading,
            "bank": sign * bank,
            "tas": tas_kt,
            "gs": tas_kt,
            "vs": vs_fpm,
            "time": t,
            "phase": _phase_for(seg),
        })
    return samples, time_start + duration_sec


def _phase_for(seg: GlideSegment) -> str:
    """Map a segment label to a short phase tag for hover_data."""
    label_lower = (seg.label or "").lower()
    # Order matters — labels can contain multiple keywords.
    if "entry" in label_lower:
        return "entry"
    if "downwind" in label_lower and "tight" not in label_lower:
        return "downwind"
    if "base turn" in label_lower:
        return "base_turn"
    if "base leg" in label_lower or label_lower == "base":
        return "base"
    if "final turn" in label_lower:
        return "final_turn"
    if "final" in label_lower and "touchdown" in label_lower:
        return "final"
    if "tight base" in label_lower or "180" in label_lower or "base→final" in label_lower or "po180" in label_lower:
        return "po180"
    if "spiral" in label_lower or "orbit" in label_lower:
        return "spiral"
    if "straight-in" in label_lower or "best-effort" in label_lower:
        return "straight_in"
    if "abeam" in label_lower:
        return "to_abeam"
    return "transit"


# =============================================================================
# Top-level executor
# =============================================================================

def execute_plan(plan: GlidePlan,
                   *,
                   tas_kt: float,
                   wind_dir_deg: float = 0.0,
                   wind_speed_kt: float = 0.0,
                   dt_sec: float = 0.5,
                   touchdown_elev_ft: float = 0.0,
                   start_heading_deg: float = 0.0,
                   ) -> tuple[list, list, dict]:
    """Walk the plan and emit (path, hover_data, metadata) in the legacy shape.

    path:       list of [lat, lon] pairs
    hover_data: list of per-step dicts (time, phase, alt, ias, tas, gs,
                heading, track, aob, ...) — same keys the existing UI consumes
    metadata:   dict with the diagnostics + a summary
    """
    path: list[list[float]] = []
    hover_data: list[dict] = []
    time_cursor = 0.0

    # First sample: engine failure point. Use the legacy hover-data shape so
    # downstream consumers (scrubber + 3D side view) read the same keys for
    # every sample.
    if plan.segments:
        first = plan.segments[0]
        path.append([first.start_lat, first.start_lon])
        hover_data.append({
            "time": 0.0,
            "phase": "engine_failure",
            "alt": round(first.start_alt_agl_ft, 1),
            "ias": round(tas_kt, 1),
            "tas": round(tas_kt, 1),
            "gs": round(tas_kt, 1),
            "heading": round(start_heading_deg, 1),
            "track": round(start_heading_deg, 1),
            "aob": 0.0,
            "vs": 0,
            "crab": 0.0,
            "slip": 0,
        })

    impacted = False
    impact_point = None
    # Find touchdown coords (for distinguishing landing from premature impact).
    td_kp = next((kp for kp in plan.key_positions
                       if getattr(kp, "name", "") == "touchdown"), None)
    td_lat = td_kp.lat if td_kp else None
    td_lon = td_kp.lon if td_kp else None
    last_seg_idx = len(plan.segments) - 1
    for seg_idx, seg in enumerate(plan.segments):
        if impacted:
            break
        if seg.kind == "straight":
            samples, time_cursor = _sample_straight(
                seg, dt_sec, tas_kt, wind_dir_deg, wind_speed_kt, time_cursor)
        elif seg.kind == "turn":
            samples, time_cursor = _sample_turn(
                seg, dt_sec, tas_kt, wind_dir_deg, wind_speed_kt, time_cursor)
        elif seg.kind == "spiral":
            samples, time_cursor = _sample_spiral(
                seg, dt_sec, tas_kt, wind_dir_deg, wind_speed_kt, time_cursor)
        else:
            samples = []
        for idx, s in enumerate(samples):
            if s["alt_agl"] <= 0.0 and not impacted:
                # Distinguish "successful touchdown at TD" from "premature
                # impact short of TD". If we're within ~300 ft of the
                # planned touchdown and on the final segment, this is a
                # successful landing, not a ground impact.
                near_td = False
                if td_lat is not None and seg_idx == last_seg_idx:
                    dlat_ft = (s["lat"] - td_lat) * 364000.0
                    dlon_ft = ((s["lon"] - td_lon) * 364000.0
                                  * math.cos(math.radians(td_lat)))
                    near_td = (dlat_ft * dlat_ft + dlon_ft * dlon_ft
                                < 300.0 * 300.0)
                if near_td:
                    path.append([s["lat"], s["lon"]])
                    hover_data.append({
                        "time": round(s["time"], 2),
                        "phase": "touchdown",
                        "alt": 0.0,
                        "ias": round(s["tas"], 1),
                        "tas": round(s["tas"], 1),
                        "gs": round(s["gs"], 1),
                        "heading": round(s["heading"], 1),
                        "track": round(s["track"], 1),
                        "aob": round(s["bank"], 1),
                        "vs": round(s.get("vs", 0.0), 0),
                        "crab": 0.0,
                        "slip": 0,
                    })
                    impacted = False  # mark as successful landing
                    break
                # Ground impact — interpolate exact crossing point with
                # the previous sample (or use this sample if first).
                if hover_data:
                    prev_alt = hover_data[-1]["alt"]
                    prev_lat = path[-1][0]
                    prev_lon = path[-1][1]
                    prev_time = hover_data[-1]["time"]
                    if prev_alt > 0.0:
                        frac = prev_alt / (prev_alt - s["alt_agl"])
                        lat_i = prev_lat + frac * (s["lat"] - prev_lat)
                        lon_i = prev_lon + frac * (s["lon"] - prev_lon)
                        t_i = prev_time + frac * (s["time"] - prev_time)
                        path.append([lat_i, lon_i])
                        hover_data.append({
                            "time": round(t_i, 2),
                            "phase": "impact",
                            "alt": 0.0,
                            "ias": round(s["tas"], 1),
                            "tas": round(s["tas"], 1),
                            "gs": round(s["gs"], 1),
                            "heading": round(s["heading"], 1),
                            "track": round(s["track"], 1),
                            "aob": round(s["bank"], 1),
                            "vs": round(s.get("vs", 0.0), 0),
                            "crab": 0.0,
                            "slip": 0,
                        })
                        impact_point = (lat_i, lon_i)
                    else:
                        path.append([s["lat"], s["lon"]])
                        hover_data.append({
                            "time": round(s["time"], 2),
                            "phase": "impact",
                            "alt": 0.0,
                            "ias": round(s["tas"], 1),
                            "tas": round(s["tas"], 1),
                            "gs": round(s["gs"], 1),
                            "heading": round(s["heading"], 1),
                            "track": round(s["track"], 1),
                            "aob": round(s["bank"], 1),
                            "vs": round(s.get("vs", 0.0), 0),
                            "crab": 0.0,
                            "slip": 0,
                        })
                        impact_point = (s["lat"], s["lon"])
                impacted = True
                break
            path.append([s["lat"], s["lon"]])
            hover_data.append({
                "time": round(s["time"], 2),
                "phase": s["phase"],
                "alt": round(s["alt_agl"], 1),
                "ias": round(s["tas"], 1),
                "tas": round(s["tas"], 1),
                "gs": round(s["gs"], 1),
                "heading": round(s["heading"], 1),
                "track": round(s["track"], 1),
                "aob": round(s["bank"], 1),
                "vs": round(s.get("vs", 0.0), 0),
                "crab": round(
                    ((s["heading"] - s["track"] + 540.0) % 360.0) - 180.0,
                    1),
                "slip": 0,
            })

    # Metadata block — includes diagnostics for the results popup
    d = plan.diagnostics
    meta = {
        "feasible": d.feasible and not impacted,
        "impacted": impacted,
        "impact_point": (list(impact_point) if impact_point else None),
        "approach_strategy": d.approach_strategy,
        "pattern_side": d.pattern_side,
        "spiral_turns": d.spiral_turns,
        "total_time_sec": time_cursor,
        "total_distance_ft": sum(s.ground_distance_ft for s in plan.segments),
        "diagnostics": {
            # Energy state
            "start_alt_msl_ft": d.start_alt_msl_ft,
            "start_alt_agl_ft": d.start_alt_agl_ft,
            "direct_dist_nm": d.direct_dist_nm,
            "direct_glide_alt_ft": d.direct_glide_alt_ft,
            "arrival_alt_agl_ft": d.arrival_alt_agl_ft,
            "excess_at_high_key_ft": d.excess_at_high_key_ft,
            "excess_at_low_key_ft": d.excess_at_low_key_ft,
            # Plan
            "approach_strategy": d.approach_strategy,
            "pattern_side": d.pattern_side,
            "on_final_side": d.on_final_side,
            # Aircraft
            "best_glide_tas_kt": d.best_glide_tas_kt,
            "glide_ratio": d.glide_ratio,
            "planning_bank_deg": d.planning_bank_deg,
            "max_bank_deg": d.max_bank_deg,
            "turn_radius_ft": d.turn_radius_ft,
            # Spiral
            "spiral_turns": d.spiral_turns,
            "spiral_bank_deg": d.spiral_bank_deg,
            # Retrospective
            "required_alt_agl_to_make_it_ft": d.required_alt_agl_to_make_it_ft,
            "required_max_dist_nm": d.required_max_dist_nm,
            # Wind
            "wind_dir_deg": d.wind_dir_deg,
            "wind_speed_kt": d.wind_speed_kt,
            "final_wind_component_kt": d.final_wind_component_kt,
            # Outcome
            "feasible": d.feasible,
            "failure_reason": d.failure_reason,
        },
        "key_positions": [
            {"name": kp.name, "lat": kp.lat, "lon": kp.lon,
             "alt_agl_ft": kp.alt_agl_ft, "heading_deg": kp.heading_deg}
            for kp in plan.key_positions
        ],
    }
    return path, hover_data, meta
