"""VFR Pattern overlay callbacks.

Inputs: picked airport (from top-bar search) + wind + pattern knobs.
Outputs: pattern polyline + entry segment + leg labels on the map.

The geometry follows FAA AC 90-66B + AFH Ch. 8:

    [entry vector] --> [downwind] --> [base] --> [final] --> threshold

Pattern legs:
  - Upwind / Departure: aligned with runway, climbing (not drawn — we
    draw arrival pattern only).
  - Crosswind: perpendicular at the end of upwind (not drawn).
  - Downwind: parallel to runway, OPPOSITE direction, at TPA, offset
    laterally by `pattern_leg_nm` on the pattern side.
  - Base: perpendicular, abeam approach end, beginning descent.
  - Final: aligned with runway centerline, descending from TPA to
    threshold.

Entry segments per AC 90-66B:
  - 45_downwind  — 45° intercept to downwind midpoint, on the pattern
                    side, 1.5 NM out from the downwind leg.
  - midfield_crossover — start at the upwind side of the field, cross
                    midfield at TPA + 500, descend to TPA on the
                    pattern side at the downwind midpoint.
  - straight_in   — extended runway centerline, 5 NM final, descending
                    from FAF altitude (TPA + 500 in this MVP).
  - teardrop      — entry from the upwind side, 45° to the runway
                    heading, crossing the upwind threshold and
                    teardropping back into the downwind. Marked as
                    NOT FAA-PREFERRED in the tooltip.
"""

from __future__ import annotations

import math

from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.data_loader import airport_data
from physics import point_from
from geopy import Point as GeoPoint


# ---------------------------------------------------------------------------
# Pure helpers (no Dash) — easier to unit-test.
# ---------------------------------------------------------------------------

def _pick_wind_favored_end(ends: list, wind_dir_deg: float, wind_speed_kt: float):
    """Return the runway end with the strongest headwind component.

    `ends` are runway end dicts with `heading` (compass, where 0 = N).
    Wind direction is the FROM direction. Headwind component =
    `wind_speed * cos(heading - wind_dir)`. Tie-break: lower
    crosswind magnitude (`sin` term).
    """
    if not ends:
        return None
    if wind_speed_kt < 1.0:
        # Calm or near-calm — return the first end so we have a deterministic
        # default. Pilot can override with the manual dropdown.
        return ends[0]
    best = None
    best_score = (-1e9, 1e9)  # (headwind, -crosswind) — maximize headwind, minimize |crosswind|
    for end in ends:
        h = end.get("heading")
        if h is None:
            continue
        delta = math.radians(float(h) - float(wind_dir_deg))
        headwind = float(wind_speed_kt) * math.cos(delta)
        crosswind = abs(float(wind_speed_kt) * math.sin(delta))
        score = (headwind, -crosswind)
        if score > best_score:
            best_score = score
            best = end
    return best or ends[0]


def _runway_ends_for(airport: dict) -> list:
    """Flatten airport.runways[].ends[] with each end's parent runway
    annotated so the picker dropdown can label them.

    `pattern_direction` on each end is one of:
        "left"  — standard FAA left traffic (chart supplement default)
        "right" — RIGHT TRAFFIC published for this end (per AC 90-66B,
                  must follow what's published)
        None    — unknown / not populated yet. Caller treats this as
                  "left (default — verify against chart supplement)".
    """
    out: list = []
    for rwy in airport.get("runways", []) or []:
        for end in rwy.get("ends", []) or []:
            d = dict(end)
            d["_runway_id"] = rwy.get("id")
            d["_surface"] = rwy.get("surface")
            d["_length_ft"] = rwy.get("length_ft")
            # Normalize the field name — some import sources call it
            # `right_traffic` (boolean) or `right_pattern`; we
            # standardize to `pattern_direction`.
            if "pattern_direction" not in d:
                if d.get("right_traffic") or d.get("right_pattern"):
                    d["pattern_direction"] = "right"
                elif "right_traffic" in d or "right_pattern" in d:
                    d["pattern_direction"] = "left"
                else:
                    d["pattern_direction"] = None  # unknown
            out.append(d)
    return out


def pattern_ias_for(ac: dict | None) -> float:
    """Best estimate of pattern IAS for the aircraft (KIAS).

    Priority order (highest to lowest authority):
      1. Explicit POH pattern_ias_kt (if the JSON has it)
      2. 1.3 × Vs0 (clean stall, FAA-standard pattern speed = 1.3 Vs)
      3. Vy minus 10 kt (slowed for pattern)
      4. Generic 80 KIAS fallback

    Used to compute the pattern turn radius at standard 30° bank.
    """
    if not ac:
        return 80.0
    explicit = ac.get("pattern_ias_kt") or ac.get("pattern_speed_kt")
    if explicit:
        return float(explicit)

    # 1.3 × Vs0 — FAA standard pattern speed reference.
    try:
        stall = ((ac.get("stall_speeds") or {}).get("landing") or {})
        speeds = stall.get("speeds") or []
        weights = stall.get("weights") or []
        if speeds and weights:
            mtow = float(ac.get("max_takeoff_weight",
                                 ac.get("gross_weight", 0)) or 0)
            # interpolate at MTOW; fallback to max speed if no weight.
            if mtow > 0:
                for i in range(len(weights) - 1):
                    if weights[i] <= mtow <= weights[i + 1]:
                        r = ((mtow - weights[i])
                              / (weights[i + 1] - weights[i]))
                        vs0 = float(speeds[i]) + r * (
                            float(speeds[i + 1]) - float(speeds[i]))
                        return round(vs0 * 1.3, 0)
            return round(float(speeds[-1]) * 1.3, 0)
    except (TypeError, ValueError, KeyError):
        pass

    # Vy − 10 fallback.
    vy = ac.get("Vy") or ac.get("vy")
    if vy:
        return float(vy) - 10.0
    return 80.0


def pattern_dimensions_for(ac: dict | None,
                            bank_deg: float = 30.0,
                            min_leg_nm: float = 0.4) -> dict:
    """Compute pattern leg width + final length scaled to the aircraft.

    Math: at standard pattern bank (30°), the turn radius is
        R = V² / (g · tan(bank))
    For the two 90° turns (downwind→base, base→final) to fit cleanly
    inside the pattern, the lateral spacing should be ≥ 2 × turn
    radius. We add a small safety margin so the wings level on
    base for a beat or two.

    Returns:
        {
            "pattern_ias_kt": float,
            "turn_radius_nm": float,
            "pattern_leg_nm": float,   # downwind lateral spacing
            "final_leg_nm": float,     # short-final length
        }

    Examples (30° bank):
        Cessna 152  @ 70 KIAS  → R=0.12 NM, leg=0.40 NM (clamped to min)
        Cessna 172  @ 80 KIAS  → R=0.16 NM, leg=0.40 NM
        Bonanza A36 @ 100 KIAS → R=0.25 NM, leg=0.50 NM
        King Air    @ 120 KIAS → R=0.36 NM, leg=0.71 NM
        TBM 900     @ 140 KIAS → R=0.49 NM, leg=0.99 NM
    """
    ias_kt = pattern_ias_for(ac)
    # TAS ≈ IAS at TPA (1000 AGL) under standard conditions — good enough
    # for pattern geometry, density-altitude correction is < 5% inside
    # the pattern.
    tas_fps = ias_kt * 1.68781
    g_fps2 = 32.174
    tan_b = math.tan(math.radians(bank_deg))
    if tan_b <= 0:
        return {
            "pattern_ias_kt": ias_kt,
            "turn_radius_nm": 0.0,
            "pattern_leg_nm": min_leg_nm,
            "final_leg_nm": 0.5,
        }
    radius_ft = (tas_fps ** 2) / (g_fps2 * tan_b)
    radius_nm = radius_ft / 6076.115
    # Lateral spacing >= 2R + small margin (~0.1 NM for wings-level
    # window on base before the base→final turn begins).
    leg_nm = max(min_leg_nm, 2.0 * radius_nm + 0.1)
    # Round to 0.05 NM so the displayed number doesn't look fussy.
    leg_nm = round(leg_nm * 20.0) / 20.0
    final_nm = max(0.4, 1.5 * radius_nm + 0.2)
    final_nm = round(final_nm * 20.0) / 20.0
    return {
        "pattern_ias_kt": ias_kt,
        "turn_radius_nm": round(radius_nm, 2),
        "pattern_leg_nm": leg_nm,
        "final_leg_nm": final_nm,
    }


def _bearing_to_xy_offset(bearing_deg: float, dist_nm: float):
    """Return (delta_lat_deg, delta_lon_deg_factor) for a great-circle
    step of `dist_nm` along `bearing_deg`. The longitude factor must
    be scaled by 1/cos(lat) by the caller."""
    rad = math.radians(bearing_deg)
    dlat = (dist_nm / 60.0) * math.cos(rad)
    dlon_factor = (dist_nm / 60.0) * math.sin(rad)
    return dlat, dlon_factor


def _step(lat: float, lon: float, bearing_deg: float, dist_nm: float):
    """Move (lat, lon) by `dist_nm` along `bearing_deg` (great-circle approx)."""
    dlat, dlon_f = _bearing_to_xy_offset(bearing_deg, dist_nm)
    dlon = dlon_f / max(0.2, math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def build_pattern_geometry(*, runway_end: dict, pattern_dir: str,
                            entry_method: str, tpa_agl: float,
                            pattern_leg_nm: float,
                            field_elev_ft: float = 0.0,
                            final_leg_nm: float = 0.5) -> dict:
    """Build the polyline + leg breakdown for a VFR traffic pattern.

    Returns:
        {
            "legs": [
                {"name": "entry", "positions": [[lat, lon], ...]},
                {"name": "downwind", "positions": [...]},
                {"name": "base", "positions": [...]},
                {"name": "final", "positions": [...]},
            ],
            "runway_heading": float,
            "pattern_dir": "left" | "right",
            "tpa_msl": float,
        }
    """
    if runway_end is None:
        return {"legs": [], "runway_heading": 0, "pattern_dir": pattern_dir,
                "tpa_msl": float(tpa_agl) + float(field_elev_ft)}

    end_lat = float(runway_end["lat"])
    end_lon = float(runway_end["lon"])
    rwy_hdg = float(runway_end.get("heading", 0.0))
    # Reciprocal — the direction the aircraft FLIES on the runway for
    # this end. Downwind is the opposite.
    downwind_hdg = (rwy_hdg + 180.0) % 360.0
    final_hdg = rwy_hdg  # arriving on this heading at the threshold

    # Pattern side — LEFT = downwind is on the pilot's left when on final.
    # If final heading is N (0°), LEFT downwind is on the WEST side
    # (perpendicular bearing 270°).
    if pattern_dir == "right":
        downwind_side_bearing = (final_hdg + 90.0) % 360.0
    else:
        downwind_side_bearing = (final_hdg - 90.0 + 360.0) % 360.0

    # Threshold position = the runway end the aircraft is landing on.
    # We use the END coords (which is the runway end's lat/lon).
    thresh_lat, thresh_lon = end_lat, end_lon

    # === Downwind leg ============================================================
    # Centered laterally `pattern_leg_nm` off the runway, on the pattern
    # side, parallel to the runway. Endpoints: abeam approach + abeam
    # departure end. We don't have the opposite-end coords directly, so
    # synthesize one ~ runway-length out along the runway heading from
    # the threshold, then offset both points laterally.
    runway_length_nm = float(runway_end.get("_length_ft", 5000.0)) / 6076.115
    # Departure end = threshold + runway_length along the upwind direction
    # (which is the same as final_hdg in reverse; from the runway end's
    # perspective the runway extends back along the reciprocal of its
    # own heading, but since heading IS the direction of takeoff from
    # this end, the "other end" is opposite this end's heading.)
    # Actually the runway end's `heading` IS the direction of takeoff FROM
    # this end. So the OTHER end is at threshold + runway_length in
    # direction (heading - 180). For the downwind, we want abeam BOTH
    # ends — abeam approach end (at threshold) and abeam departure end
    # (at threshold + length along upwind = -heading).
    upwind_hdg = (rwy_hdg + 180.0) % 360.0
    # Wait — `rwy_hdg` is the heading you take off from this end. The
    # other end is at threshold + runway_length along `rwy_hdg`.
    # Re-check: for runway "06/24", the "06" end has heading 049° (049
    # being the direction of departure from the 06 end → roughly NE).
    # The "24" end is then SW of "06", at threshold_06 + length × bearing
    # 049° = threshold_06 moved NE. Yes — departure end is along
    # rwy_hdg.
    other_end_lat, other_end_lon = _step(
        thresh_lat, thresh_lon, rwy_hdg, runway_length_nm)

    # Downwind abeam approach — also shifted "past the threshold" by
    # `final_leg_nm` along the downwind direction so the base-final
    # turn lands on the extended centerline UPWIND of the threshold,
    # leaving a real final leg to fly. Pre-fix the abeam point was
    # directly perpendicular to the threshold, which made base_end
    # land AT the threshold (no final length).
    abeam_app_lat, abeam_app_lon = _step(
        thresh_lat, thresh_lon,
        downwind_hdg,  # extend along the downwind direction (reciprocal of final)
        final_leg_nm,
    )
    abeam_app_lat, abeam_app_lon = _step(
        abeam_app_lat, abeam_app_lon,
        downwind_side_bearing,
        pattern_leg_nm,
    )
    # Downwind abeam departure end — offset both ways the same way.
    abeam_dep_lat, abeam_dep_lon = _step(
        other_end_lat, other_end_lon, downwind_side_bearing, pattern_leg_nm)

    # === Base leg ================================================================
    # From abeam-approach on downwind, perpendicular to final approach
    # heading, back to the extended centerline at the base-final turn
    # point. Length = pattern_leg_nm.
    # The base flies in direction (final_hdg + 90) for LEFT pattern
    # (turning from downwind to base = 90° turn toward the runway side).
    # Actually: on a LEFT pattern with final heading N, downwind heading
    # is S, base turn is LEFT from south = east heading. Bringing the
    # aircraft FROM the west-side downwind back TOWARD the centerline
    # = heading east. That's (final_hdg + 90) for LEFT, or
    # (final_hdg - 90) for RIGHT.
    if pattern_dir == "right":
        base_hdg = (final_hdg - 90.0 + 360.0) % 360.0
    else:
        base_hdg = (final_hdg + 90.0) % 360.0
    base_end_lat, base_end_lon = _step(
        abeam_app_lat, abeam_app_lon, base_hdg, pattern_leg_nm)

    # === Final ===================================================================
    # From base-final turn point back to threshold along final_hdg.
    # Already have both endpoints (base_end → thresh).

    # === Entry ===================================================================
    entry_positions: list = []
    # 45° to downwind: intercept the downwind midpoint at 45°,
    # ~1.5 NM upwind of the downwind leg (on the pattern side).
    if entry_method == "45_downwind":
        # Midpoint of downwind.
        mid_lat = (abeam_app_lat + abeam_dep_lat) / 2.0
        mid_lon = (abeam_app_lon + abeam_dep_lon) / 2.0
        # 45° entry vector — comes in at 45° to the downwind heading,
        # from the OUTSIDE (away from the runway). For a left pattern:
        # downwind heads (final + 180). 45° outside the downwind on the
        # pattern side means the entry comes from
        # (downwind_hdg + 135) reversed... easier: walk OUT from the
        # midpoint perpendicular to the downwind (i.e. further away from
        # the runway), then BACK along the entry bearing.
        if pattern_dir == "right":
            entry_bearing_into = (downwind_hdg - 45.0 + 360.0) % 360.0
        else:
            entry_bearing_into = (downwind_hdg + 45.0) % 360.0
        # Outside-corner anchor: midpoint + 1.5 NM in direction
        # opposite to entry_bearing_into.
        anchor_lat, anchor_lon = _step(
            mid_lat, mid_lon,
            (entry_bearing_into + 180.0) % 360.0,
            1.5,
        )
        entry_positions = [[anchor_lat, anchor_lon], [mid_lat, mid_lon]]
        # Truncate downwind to start from the midpoint (the rest is
        # the part we fly).
        downwind_positions = [[mid_lat, mid_lon],
                              [abeam_app_lat, abeam_app_lon]]
    elif entry_method == "midfield_crossover":
        # Cross the field at midfield perpendicular to the runway,
        # from the side OPPOSITE the pattern. Land on the pattern side
        # at the downwind midpoint after descending.
        mid_lat_field, mid_lon_field = _step(
            thresh_lat, thresh_lon, rwy_hdg, runway_length_nm / 2.0)
        # OPPOSITE pattern side bearing
        if pattern_dir == "right":
            opposite_side = (final_hdg - 90.0 + 360.0) % 360.0
        else:
            opposite_side = (final_hdg + 90.0) % 360.0
        # Anchor 1.5 NM out on the OPPOSITE side, perpendicular.
        anchor_lat, anchor_lon = _step(
            mid_lat_field, mid_lon_field, opposite_side, 1.5)
        # Midfield point AT runway center
        midfield_lat, midfield_lon = mid_lat_field, mid_lon_field
        # Downwind entry point — midpoint of downwind leg on pattern side
        dw_mid_lat = (abeam_app_lat + abeam_dep_lat) / 2.0
        dw_mid_lon = (abeam_app_lon + abeam_dep_lon) / 2.0
        entry_positions = [[anchor_lat, anchor_lon],
                            [midfield_lat, midfield_lon],
                            [dw_mid_lat, dw_mid_lon]]
        downwind_positions = [[dw_mid_lat, dw_mid_lon],
                              [abeam_app_lat, abeam_app_lon]]
    elif entry_method == "straight_in":
        # Extended runway centerline, 5 NM final.
        far_final_lat, far_final_lon = _step(
            thresh_lat, thresh_lon,
            (rwy_hdg + 180.0) % 360.0,  # AWAY from threshold along reciprocal
            5.0,
        )
        entry_positions = [[far_final_lat, far_final_lon], [thresh_lat, thresh_lon]]
        # No downwind / base in straight-in mode.
        downwind_positions = []
        base_positions = []
    elif entry_method == "direct_downwind":
        # Pilot is arriving roughly aligned with the downwind direction
        # already. Entry is a short straight line OUT from the abeam-
        # departure end, ~1 NM beyond, intercepting downwind. Most
        # common at towered fields when ATC says "enter direct
        # downwind 18 right". Always YIELD to aircraft on the 45°
        # entry per AC 90-66B.
        anchor_lat, anchor_lon = _step(
            abeam_dep_lat, abeam_dep_lon, downwind_hdg, 1.0)
        entry_positions = [[anchor_lat, anchor_lon],
                            [abeam_dep_lat, abeam_dep_lon]]
        # Full downwind flown from abeam-departure → abeam-approach.
        downwind_positions = [[abeam_dep_lat, abeam_dep_lon],
                              [abeam_app_lat, abeam_app_lon]]
    elif entry_method == "direct_crosswind":
        # Pilot is arriving aligned with the CROSSWIND leg — perpendicular
        # to the runway from the upwind end side. Entry intercepts the
        # crosswind leg at the departure end and flies onto downwind.
        if pattern_dir == "right":
            crosswind_hdg_into = (final_hdg - 90.0 + 360.0) % 360.0
        else:
            crosswind_hdg_into = (final_hdg + 90.0) % 360.0
        # Start point: 1 NM out on the OPPOSITE side from the pattern,
        # crosswind direction in.
        if pattern_dir == "right":
            opposite_side = (final_hdg + 90.0) % 360.0
        else:
            opposite_side = (final_hdg - 90.0 + 360.0) % 360.0
        anchor_lat, anchor_lon = _step(
            other_end_lat, other_end_lon, opposite_side, 1.0)
        # Crosswind handoff point: roughly the departure end + pattern_leg_nm
        # perpendicular toward the pattern side.
        crosswind_end_lat, crosswind_end_lon = _step(
            other_end_lat, other_end_lon, downwind_side_bearing,
            pattern_leg_nm,
        )
        entry_positions = [[anchor_lat, anchor_lon],
                            [other_end_lat, other_end_lon],
                            [crosswind_end_lat, crosswind_end_lon]]
        downwind_positions = [[crosswind_end_lat, crosswind_end_lon],
                              [abeam_app_lat, abeam_app_lon]]
    elif entry_method == "direct_base":
        # Towered-field permission required. Entry is a short straight
        # line intercepting the base leg at its midpoint.
        base_start = (abeam_app_lat, abeam_app_lon)
        base_end = (base_end_lat, base_end_lon) if False else (
            # base_end isn't computed yet in this branch — derive here
            _step(abeam_app_lat, abeam_app_lon,
                  (final_hdg + 90.0) % 360.0 if pattern_dir == "left"
                  else (final_hdg - 90.0 + 360.0) % 360.0,
                  pattern_leg_nm)
        )
        base_mid_lat = (base_start[0] + base_end[0]) / 2.0
        base_mid_lon = (base_start[1] + base_end[1]) / 2.0
        # Anchor 1 NM out from base midpoint, perpendicular to base.
        if pattern_dir == "right":
            base_hdg_local = (final_hdg - 90.0 + 360.0) % 360.0
        else:
            base_hdg_local = (final_hdg + 90.0) % 360.0
        anchor_lat, anchor_lon = _step(
            base_mid_lat, base_mid_lon,
            (base_hdg_local + 180.0) % 360.0,
            1.0,
        )
        entry_positions = [[anchor_lat, anchor_lon],
                            [base_mid_lat, base_mid_lon]]
        # Downwind not flown — start the rectangle at base midpoint.
        downwind_positions = []
    elif entry_method == "teardrop":
        # Cross over the field FROM the upwind side (departure end),
        # at TPA + 500, then teardrop back. Enters downwind at midpoint
        # going in the wrong direction first — this is the FAA-
        # discouraged option but pilots still use it.
        if pattern_dir == "right":
            opposite_side = (final_hdg - 90.0 + 360.0) % 360.0
        else:
            opposite_side = (final_hdg + 90.0) % 360.0
        anchor_lat, anchor_lon = _step(
            other_end_lat, other_end_lon, opposite_side, 1.5)
        # Teardrop pivot point — abeam departure end on the OPPOSITE side,
        # then 180° turn back toward downwind midpoint.
        dw_mid_lat = (abeam_app_lat + abeam_dep_lat) / 2.0
        dw_mid_lon = (abeam_app_lon + abeam_dep_lon) / 2.0
        # Arc through ~3 points to suggest the teardrop curve.
        entry_positions = [[anchor_lat, anchor_lon],
                            [other_end_lat, other_end_lon],
                            [abeam_dep_lat, abeam_dep_lon],
                            [dw_mid_lat, dw_mid_lon]]
        downwind_positions = [[dw_mid_lat, dw_mid_lon],
                              [abeam_app_lat, abeam_app_lon]]
    else:
        downwind_positions = [[abeam_dep_lat, abeam_dep_lon],
                              [abeam_app_lat, abeam_app_lon]]

    # Standard downwind = full leg (used when entry pre-truncates it).
    if entry_method == "straight_in":
        downwind_positions = []
        base_positions = []
        final_positions = [[entry_positions[0][0], entry_positions[0][1]],
                            [thresh_lat, thresh_lon]]
    else:
        # If entry method didn't pre-set downwind, give the full leg.
        if not downwind_positions:
            downwind_positions = [[abeam_dep_lat, abeam_dep_lon],
                                   [abeam_app_lat, abeam_app_lon]]
        base_positions = [[abeam_app_lat, abeam_app_lon],
                           [base_end_lat, base_end_lon]]
        final_positions = [[base_end_lat, base_end_lon],
                            [thresh_lat, thresh_lon]]

    legs = []
    if entry_positions:
        legs.append({"name": "entry", "positions": entry_positions})
    if downwind_positions:
        legs.append({"name": "downwind", "positions": downwind_positions})
    if base_positions:
        legs.append({"name": "base", "positions": base_positions})
    if final_positions:
        legs.append({"name": "final", "positions": final_positions})

    return {
        "legs": legs,
        "runway_heading": rwy_hdg,
        "pattern_dir": pattern_dir,
        "tpa_msl": float(tpa_agl) + float(field_elev_ft),
        "runway_end_lat": thresh_lat,
        "runway_end_lon": thresh_lon,
    }


def register(app):
    """Install VFR pattern overlay callbacks."""

    # === Populate the runway dropdown when an airport is picked ===
    @app.callback(
        Output("pattern-runway", "options"),
        Output("pattern-runway", "value"),
        Input("selected-airport-id", "data"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        prevent_initial_call=True,
    )
    def populate_runway_options(airport_id, wind_dir, wind_speed):
        if not airport_id:
            return [], None
        ap = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not ap:
            return [], None
        ends = _runway_ends_for(ap)
        if not ends:
            return [], None
        try:
            wd = float(wind_dir) if wind_dir is not None else 0.0
        except (TypeError, ValueError):
            wd = 0.0
        try:
            ws = float(wind_speed) if wind_speed is not None else 0.0
        except (TypeError, ValueError):
            ws = 0.0
        preferred = _pick_wind_favored_end(ends, wd, ws)
        preferred_id = preferred.get("id") if preferred else None

        opts = []
        for end in ends:
            h = end.get("heading")
            hw = (ws * math.cos(math.radians(float(h) - wd))
                  if h is not None and ws > 0 else 0.0)
            label = f"{end.get('id', '?')} ({end.get('heading', 0):03.0f}°)"
            if ws > 0:
                label += f"  HW {hw:+.0f}"
            opts.append({"label": label, "value": end.get("id")})

        return opts, preferred_id

    # === Draw the pattern ===
    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("pattern-info", "children"),
        Input({"type": "draw-btn", "m_id": "pattern"}, "n_clicks"),
        State("selected-airport-id", "data"),
        State("pattern-runway", "value"),
        State("pattern-entry-method", "value"),
        State("pattern-direction", "value"),
        State("pattern-tpa-agl", "value"),
        State("pattern-leg-nm", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def draw_pattern(n_clicks, airport_id, runway_id, entry_method,
                      pattern_dir_choice, tpa_agl, leg_nm,
                      wind_dir, wind_speed, aircraft_name):
        if not n_clicks:
            raise PreventUpdate
        if not airport_id:
            return [], None, html.Div(
                "Pick an airport in the top bar first.",
                style={"color": "var(--acs-marginal, #b45309)",
                       "padding": "10px"})

        ap = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not ap:
            raise PreventUpdate

        ends = _runway_ends_for(ap)
        if not ends:
            return [], None, html.Div(
                f"{airport_id} has no runway end data — pattern can't be drawn.",
                style={"color": "var(--acs-marginal, #b45309)",
                       "padding": "10px"})

        # Wind
        try:
            wd = float(wind_dir) if wind_dir is not None else 0.0
        except (TypeError, ValueError):
            wd = 0.0
        try:
            ws = float(wind_speed) if wind_speed is not None else 0.0
        except (TypeError, ValueError):
            ws = 0.0

        # Pick runway end
        chosen_end = None
        if runway_id:
            chosen_end = next((e for e in ends if e.get("id") == runway_id), None)
        if chosen_end is None:
            chosen_end = _pick_wind_favored_end(ends, wd, ws) or ends[0]

        # Pattern direction — prefer the chosen end's PUBLISHED
        # pattern direction (FAA chart supplement / AFD). Falls back
        # to LEFT (FAA default for unmarked runways) when the field
        # isn't populated. Manual override always wins.
        published_dir = chosen_end.get("pattern_direction")
        if pattern_dir_choice in ("left", "right"):
            pattern_dir = pattern_dir_choice
            pattern_dir_source = "manual override"
        elif published_dir in ("left", "right"):
            pattern_dir = published_dir
            pattern_dir_source = "published (chart supplement)"
        else:
            pattern_dir = "left"
            pattern_dir_source = "default (data not populated — verify chart supplement)"

        # Aircraft-aware dimensions — pulls pattern IAS from the
        # aircraft POH and sizes downwind / final legs to fit the
        # turn radius at standard 30° bank. Pilot can still override
        # the leg via the input.
        from core.data_loader import aircraft_data
        ac = aircraft_data.get(aircraft_name) if aircraft_name else None
        dims = pattern_dimensions_for(ac)

        # TPA + leg — user override wins; otherwise use aircraft-aware default.
        try:
            tpa = float(tpa_agl) if tpa_agl is not None else 1000.0
        except (TypeError, ValueError):
            tpa = 1000.0

        # If the shelf's leg input is at its default 0.5 AND the
        # aircraft suggests something different, use the aircraft-aware
        # value. The user can always type their own to override.
        # Detection: if value matches the layout default exactly, treat
        # as "not yet customized."
        try:
            leg_input = float(leg_nm) if leg_nm is not None else 0.5
        except (TypeError, ValueError):
            leg_input = 0.5
        if abs(leg_input - 0.5) < 1e-6:
            leg = dims["pattern_leg_nm"]
            leg_source = f"aircraft-aware (pattern IAS {dims['pattern_ias_kt']:.0f} kt → R={dims['turn_radius_nm']:.2f} NM @ 30° bank)"
        else:
            leg = leg_input
            leg_source = "manual"

        field_elev = float(ap.get("elevation_ft") or 0.0)

        geo = build_pattern_geometry(
            runway_end=chosen_end,
            pattern_dir=pattern_dir,
            entry_method=entry_method or "45_downwind",
            tpa_agl=tpa,
            pattern_leg_nm=leg,
            field_elev_ft=field_elev,
            final_leg_nm=dims["final_leg_nm"],
        )

        # === Render legs ============================================================
        LEG_COLORS = {
            "entry":    "#0d59f2",
            "downwind": "#16a34a",
            "base":     "#16a34a",
            "final":    "#16a34a",
        }
        LEG_DASH = {
            "entry": "8,8",
        }
        elements: list = []
        all_lats: list = []
        all_lons: list = []
        for leg_data in geo["legs"]:
            color = LEG_COLORS.get(leg_data["name"], "#16a34a")
            dash = LEG_DASH.get(leg_data["name"])
            elements.append(dl.Polyline(
                positions=leg_data["positions"],
                color=color,
                weight=4,
                opacity=0.95,
                dashArray=dash,
                children=dl.Tooltip(leg_data["name"].capitalize()),
            ))
            for lat, lon in leg_data["positions"]:
                all_lats.append(lat)
                all_lons.append(lon)

        # Runway markers — threshold + departure end.
        elements.append(dl.CircleMarker(
            center=[geo["runway_end_lat"], geo["runway_end_lon"]],
            radius=6, color="#dc2626", fill=True, fillColor="#dc2626",
            fillOpacity=1.0,
            children=dl.Tooltip(
                f"Threshold {chosen_end.get('id')} · "
                f"{chosen_end.get('heading', 0):03.0f}°"),
        ))

        # Headwind / crosswind components for the info panel.
        h = float(chosen_end.get("heading", 0))
        delta = math.radians(h - wd)
        hw = ws * math.cos(delta)
        xw = ws * math.sin(delta)

        is_teardrop = entry_method == "teardrop"
        is_straight_in = entry_method == "straight_in"

        # Info panel — short, actionable.
        info = dbc.Accordion([
            dbc.AccordionItem([
                html.Div(
                    f"Airport: {ap.get('id')} — {ap.get('name')}",
                    style={"fontSize": "12px", "fontWeight": "600"}),
                html.Hr(style={"margin": "5px 0"}),
                html.Div(
                    f"Runway in use: {chosen_end.get('id')} "
                    f"({h:03.0f}°)  ·  "
                    f"surface: {chosen_end.get('_surface', '?')}  ·  "
                    f"length: {chosen_end.get('_length_ft', 0):.0f} ft",
                    style={"fontSize": "11px"}),
                html.Div(
                    f"Wind: {wd:03.0f}° @ {ws:.0f} kt  ·  "
                    f"HW {hw:+.1f}  XW {xw:+.1f}",
                    style={"fontSize": "11px"}),
                html.Div(
                    f"Pattern: {pattern_dir.upper()} ({pattern_dir_source})  ·  "
                    f"TPA: {tpa:.0f} ft AGL ({tpa + field_elev:.0f} ft MSL)  ·  "
                    f"Spacing: {leg:.2f} NM",
                    style={
                        "fontSize": "11px",
                        "color": ("var(--acs-marginal, #b45309)"
                                  if "default" in pattern_dir_source
                                  else "var(--ta-text, #1e293b)"),
                    }),
                html.Div(
                    f"Spacing source: {leg_source}",
                    style={"fontSize": "10px",
                           "color": "var(--ta-text-muted, #6b7280)"}),
                html.Div(
                    f"Entry: {entry_method.replace('_', ' ')}",
                    style={
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "color": ("var(--acs-marginal, #b45309)"
                                  if is_teardrop else
                                  "var(--ta-text, #1e293b)"),
                    }),
                html.Div(
                    "Teardrop is the FAA-discouraged alternative — "
                    "AC 90-66B prefers the 45° to downwind entry. "
                    "Use teardrop only when you have a specific "
                    "reason (e.g. terrain on the pattern side)."
                    if is_teardrop else
                    "Straight-in is appropriate for IFR or specific "
                    "VFR cases — call intentions on CTAF 10 NM out "
                    "and yield to aircraft on the standard pattern."
                    if is_straight_in else
                    "FAA-recommended entry. Cross over downwind "
                    "midpoint at 45° on the pattern side.",
                    style={"fontSize": "10px",
                           "color": "var(--ta-text-muted, #6b7280)",
                           "marginTop": "4px"}),
            ], title="Pattern Geometry", style={"fontSize": "12px"}),
        ], start_collapsed=False, style={"marginTop": "8px"})

        bounds = None
        if all_lats and all_lons:
            pad_lat = 0.005
            pad_lon = 0.005
            bounds = [[min(all_lats) - pad_lat, min(all_lons) - pad_lon],
                       [max(all_lats) + pad_lat, max(all_lons) + pad_lon]]

        return elements, bounds, info
