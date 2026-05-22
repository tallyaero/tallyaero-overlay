"""Power-Off 180 draw + scrubber callbacks.

Inputs: aircraft + environment + runway geometry + pattern parameters.
Outputs: map layer with path, bounds, info panel, time-scrubber state.
"""

from __future__ import annotations

from dash import html, Input, Output, State
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.log import get_logger

from callbacks.map import create_airplane_marker

from core.data_loader import aircraft_data, airport_data
from core.profile3d import build_3d_side_view_block, side_view_accordion_item
from layouts.maneuvers._shared import _winds_aloft_chip

log = get_logger(__name__)


def _po180_crab_display(pt: dict) -> str:
    """Format the crab line for PO180's scrubber tooltip.

    PO180's sim emits `drift = heading − track` (positive ⇒ nose right
    of track ⇒ RIGHT crab). If the explicit `drift` is zero / missing,
    fall back to heading − track derived from the same hover entry so
    a re-serialized hover store that lost the field still renders.
    """
    drift = pt.get("drift")
    if drift in (None, 0, 0.0):
        h = pt.get("heading")
        t = pt.get("track")
        if h is not None and t is not None:
            drift = ((float(h) - float(t)) + 540.0) % 360.0 - 180.0
    drift = float(drift or 0.0)
    side = "R " if drift > 0.05 else ("L " if drift < -0.05 else "")
    return f"Crab: {side}{abs(drift):.1f}°"


def _po180_runway_3d_dict(runway_threshold: dict,
                           runway_heading_deg: float,
                           runway_length_ft: float,
                           elev_ft: float) -> dict:
    """Build the `runway` dict the profile3d helper consumes for PO180.

    PO180's user-clicked point is the TOUCHDOWN end of the runway
    (where the aircraft is aiming). The departure end sits opposite at
    runway_heading + 180°. Drawing both into the ground plane gives the
    same orientation cue the 2D map already has.
    """
    from physics import point_from, FT_PER_NM
    from geopy.point import Point as _GP

    td_pt = _GP(float(runway_threshold["lat"]), float(runway_threshold["lon"]))
    # The OPPOSITE threshold is `runway_length_ft` behind the touchdown,
    # in the direction the runway points back toward (heading + 180°).
    far_hdg = (float(runway_heading_deg) + 180.0) % 360.0
    far_pt = point_from(td_pt, far_hdg, float(runway_length_ft) / FT_PER_NM)
    return {
        "start_lat": far_pt.latitude,
        "start_lon": far_pt.longitude,
        "end_lat": td_pt.latitude,
        "end_lon": td_pt.longitude,
        "elev_ft": float(elev_ft or 0.0),
    }


def _phase_transition_indices(hover):
    """Return [(index, segment), ...] for each phase boundary in the hover list.

    Phase C4 — ACS Gap 5. Walks the hover stream and emits one tuple
    per detected segment change, plus an implicit entry for the first
    seen segment at its first index. Entries with no "segment" field
    are skipped (treated as continuations)."""
    out = []
    prev = None
    for i, pt in enumerate(hover):
        seg = pt.get("segment")
        if seg is None:
            continue
        if seg != prev:
            out.append((i, seg))
            prev = seg
    return out


def _po180_procedure_indices(hover, path, td_lat: float, td_lon: float,
                              pattern_direction: str):
    """Procedural milestone indices for the Power-Off 180:

      abeam_idx   — on downwind, touchdown is 90° off the wing (on the
                    correct side per `pattern_direction`).
      key45_idx   — on downwind, AFTER abeam, touchdown is 45° behind
                    the wing (the "key" visual checkpoint at which most
                    pilots begin the descending base turn).
      turn90_idx  — middle of the 180° turn (turn segment midpoint),
                    aircraft has turned 90° from downwind heading and
                    is perpendicular to the runway centerline.

    Returns a dict so callers can render only the milestones that
    resolved cleanly (any value may be `None` if the corresponding
    geometry doesn't appear in the hover stream — e.g. very short
    downwind that never went abeam).
    """
    import math

    out = {"abeam_idx": None, "key45_idx": None, "turn90_idx": None}
    if not hover or not path:
        return out

    # Left pattern → touchdown is to the LEFT of the aircraft on downwind
    # (relative bearing negative); right pattern → touchdown is to the
    # right (positive). We use this sign to disambiguate which side of
    # the aircraft "90° off the wing" means.
    side = -1.0 if str(pattern_direction).lower().startswith("l") else 1.0

    def _bearing_to_td(lat: float, lon: float) -> float:
        # Initial-bearing approximation; for the short distances in a
        # standard pattern (<2 NM), the great-circle term is negligible.
        dlon = math.radians(td_lon - lon)
        lat1 = math.radians(lat)
        lat2 = math.radians(td_lat)
        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0

    def _signed_diff(a: float, b: float) -> float:
        d = (a - b + 180.0) % 360.0 - 180.0
        return d

    # Walk hover; for each downwind / turn tick compute relative bearing.
    # Track which side abeam appears on, then find the 45° angle past it.
    n = min(len(hover), len(path))
    abeam_idx = None
    abeam_err = 1e9   # accumulator finding tightest |rel - 90 × side|
    key45_idx = None
    key45_err = 1e9
    turn_indices: list[int] = []

    for i in range(n):
        pt = hover[i]
        seg = pt.get("segment")
        if seg == "turn":
            turn_indices.append(i)
            continue
        if seg != "downwind":
            continue
        lat, lon = path[i]
        track = float(pt.get("track") or pt.get("heading") or 0.0)
        rel = _signed_diff(_bearing_to_td(lat, lon), track)
        # Abeam: |rel| ≈ 90° on the pattern-direction side.
        target_abeam = 90.0 * side
        err_abeam = abs(rel - target_abeam)
        if err_abeam < abeam_err:
            abeam_err = err_abeam
            abeam_idx = i
        # 45° behind the wing → relative bearing 135° on the same side
        # ("behind" = away from the nose). Only valid AFTER abeam, so
        # we keep the running tightest match but rely on the search
        # naturally hitting it later in the downwind sweep.
        target_45 = 135.0 * side
        err_45 = abs(rel - target_45)
        if err_45 < key45_err:
            key45_err = err_45
            key45_idx = i

    out["abeam_idx"] = abeam_idx if abeam_err < 20.0 else None
    # Only honor the 45° pick if it lies AFTER the abeam tick — otherwise
    # we'd be flagging the approach side of the abeam (touchdown 45°
    # AHEAD of the wing), which isn't the procedural key position.
    if (key45_idx is not None and abeam_idx is not None
            and key45_idx > abeam_idx and key45_err < 20.0):
        out["key45_idx"] = key45_idx

    if turn_indices:
        # Midpoint of the turn ticks is the 90° point (90° into the
        # 180° turn) by construction — the sim emits ticks with even
        # ground-distance steps along the arc.
        out["turn90_idx"] = turn_indices[len(turn_indices) // 2]

    return out


def register(app):
    """Install Power-Off 180 callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output({"type": "click-status", "m_id": "poweroff180"}, "children", allow_duplicate=True),
        Output("poweroff180-hover-store", "data"),
        Output("poweroff180-path-store", "data"),
        Output("poweroff180-slider-container", "style"),
        Output("poweroff180-time-slider", "max"),
        Output("poweroff180-time-slider", "marks"),
        Output("poweroff180-time-slider", "value"),
        Output("poweroff180-info", "children"),
        Output({"type": "sim-results-btn", "m_id": "poweroff180"}, "className", allow_duplicate=True),
        Input({"type": "draw-btn", "m_id": "poweroff180"}, "n_clicks"),
        State({"type": "point-store", "m_id": "poweroff180", "role": "touchdown"}, "data"),
        State("poweroff180-runway-select", "value"),
        State("poweroff180-manual-heading", "value"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("poweroff180-altitude", "value"),
        State("poweroff180-pattern", "value"),
        State("poweroff180-flap-setting", "value"),
        State("poweroff180-prop-condition", "value"),
        State("poweroff180-abeam-distance-nm", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("wind-profile-store", "data"),
        prevent_initial_call=True
    )
    def draw_poweroff180(
        n_clicks,
        touchdown_data,
        runway_select,
        manual_heading,
        ac_name,
        engine_key,
        wind_dir,
        wind_speed,
        oat_f,
        altimeter,
        pattern_alt_agl,
        pattern_dir,
        flap_setting,
        prop_condition,
        abeam_distance_nm,
        selected_airport_id,
        runtime_weight,
        wind_profile_data,
    ):
        """Draw Power-Off 180 accuracy approach using energy-based simulation."""
        from simulation import simulate_power_off_180

        BTN_BASE = "shelf-action shelf-action-results"

        if not n_clicks:
            return [], None, "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

        if not ac_name or not engine_key:
            return [], None, "Select aircraft and engine first.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

        # Touchdown point is always required (user clicks on runway)
        if not touchdown_data:
            return [], None, "Click 'Set Touchdown Point' then click on the runway where you want to land.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

        try:
            # Get airport data for elevation
            selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
            elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

            # Touchdown point from user click
            runway_threshold = touchdown_data
            runway_length_ft = 5000.0

            # Phase F — runway-select drives the runway length. The
            # heading input is the source of truth and is interpreted as
            # magnetic whenever an airport is selected; we convert to true
            # for the geometry the sim renders.
            if selected_airport_id and runway_select:
                from callbacks.aircraft import _resolve_runway_end
                end = _resolve_runway_end(selected_airport_id, runway_select)
                if end and end.get("length_ft"):
                    runway_length_ft = float(end["length_ft"])

            if manual_heading is None or manual_heading == "":
                return [], None, "Enter a runway heading.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE
            heading_mag_or_true = float(manual_heading)
            if selected_airport_id:
                from callbacks.aircraft import _airport_magvar, _mag_to_true
                airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
                runway_heading = _mag_to_true(heading_mag_or_true, _airport_magvar(airport))
            else:
                runway_heading = heading_mag_or_true

            # Get values
            pattern_alt = float(pattern_alt_agl) if pattern_alt_agl else 1000.0
            abeam_dist = float(abeam_distance_nm) if abeam_distance_nm else 0.5
            wind_dir_val = float(wind_dir) if wind_dir else 0.0
            wind_speed_val = float(wind_speed) if wind_speed else 0.0
            oat_c = ((float(oat_f) if oat_f else 59.0) - 32.0) * 5.0 / 9.0
            altimeter_val = float(altimeter) if altimeter else 29.92

            total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None
            if total_wt is None:
                ac_data = aircraft_data.get(ac_name, {})
                total_wt = ac_data.get("max_takeoff_weight", ac_data.get("gross_weight", 2500.0))

            # Get aircraft data
            ac = dict(aircraft_data[ac_name])
            ac["total_weight_lb"] = float(total_wt)

            # Hydrate live winds-aloft column when an airport pick fetched one.
            wind_profile = None
            if wind_profile_data:
                try:
                    from core.winds_aloft import WindProfile
                    wind_profile = WindProfile.from_store(wind_profile_data)
                except Exception:
                    wind_profile = None

            # Run simulation
            path, hover_data, results = simulate_power_off_180(
                runway_threshold=runway_threshold,
                runway_heading_deg=float(runway_heading),
                runway_length_ft=float(runway_length_ft),
                abeam_distance_nm=abeam_dist,
                pattern_direction=pattern_dir or "left",
                ac=ac,
                weight_lbs=float(total_wt),
                flap_config=flap_setting or "clean",
                prop_config=prop_condition or "idle",
                oat_c=oat_c,
                altimeter_inhg=altimeter_val,
                wind_dir_deg=wind_dir_val,
                wind_speed_kt=wind_speed_val,
                field_elev_ft=elev_ft,
                pattern_altitude_agl=pattern_alt,
                timestep_sec=0.5,
                engine_option=engine_key,
                wind_profile=wind_profile,
            )

            if not path or not hover_data:
                return [], None, "No glide path generated. Check inputs.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

            # Build map elements
            elements = []

            # Theme B glide path
            path_line = dl.Polyline(positions=path, color="#0d59f2", weight=3, opacity=0.85)
            elements.append(path_line)

            # Abeam start — green-500
            if path:
                start_marker = dl.CircleMarker(
                    center=path[0],
                    radius=7,
                    color="#22c55e",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip("Abeam (Power Off)")
                )
                elements.append(start_marker)

            # Runway threshold — green for successful touchdown, red
            # for missed approach. Matches the convention in the other
            # landing-maneuver renderers; the old fixed-blue marker
            # made successes and failures look identical.
            success_for_color = bool(results.get('success', False))
            aim_color = "#22c55e" if success_for_color else "#ef4444"
            aim_tooltip = (
                f"Runway {runway_select or 'threshold'} — touchdown"
                if success_for_color
                else f"Runway {runway_select or 'threshold'} — missed"
            )
            aim_marker = dl.CircleMarker(
                center=[runway_threshold['lat'], runway_threshold['lon']],
                radius=7,
                color=aim_color,
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip(aim_tooltip)
            )
            elements.append(aim_marker)

            # Impact marker if failed — red-600 fail
            impact_point = results.get('impact_point')
            if impact_point:
                impact_marker = dl.CircleMarker(
                    center=impact_point,
                    radius=8,
                    color="#dc2626",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip(f"Impact: {results.get('touchdown_error_ft', 0):.0f} ft short")
                )
                elements.append(impact_marker)

            # Procedural-milestone markers on the map. Replaces the
            # earlier "fire on each segment transition" logic, which
            # placed the "Abeam" / "90° turn" / "45° / Final" labels at
            # segment BOUNDARIES — none of which line up with the actual
            # procedural reference points the pilot is judging by:
            #
            #   Abeam  — on downwind, touchdown 90° off the wing
            #   45°    — on downwind, touchdown 45° behind the wing
            #   90°    — middle of the 180° turn (base-leg position)
            #   TD     — touchdown / impact end of run
            proc_idxs = _po180_procedure_indices(
                hover_data, path,
                float(runway_threshold["lat"]),
                float(runway_threshold["lon"]),
                pattern_dir or "left",
            )

            def _milestone(idx, label):
                if idx is None or idx >= len(path):
                    return
                lat, lon = path[idx]
                pt = hover_data[idx]
                tip = (f"{label} — alt {pt.get('alt', 0):.0f} ft AGL, "
                       f"IAS {pt.get('ias', 0):.0f} kt")
                elements.append(dl.CircleMarker(
                    center=[lat, lon],
                    radius=6,
                    color="#f59e0b",
                    fill=True,
                    fillOpacity=0.85,
                    children=dl.Tooltip(tip),
                ))

            _milestone(proc_idxs["abeam_idx"], "Abeam")
            _milestone(proc_idxs["key45_idx"], "45° key")
            _milestone(proc_idxs["turn90_idx"], "90° (base)")

            # Build status message
            success = results.get('success', False)
            td_error = results.get('touchdown_error_ft', 0)

            if success:
                if td_error == 0:
                    msg = "SUCCESS - Touchdown on target!"
                else:
                    msg = f"SUCCESS - Touchdown +{td_error:.0f} ft (within ACS -0/+200)"
            else:
                if td_error < 0:
                    msg = f"FAILED - SHORT by {abs(td_error):.0f} ft"
                else:
                    msg = f"FAILED - LONG by {td_error:.0f} ft (exceeds +200)"

            # Calculate bounds
            lats = [pt[0] for pt in path] + [runway_threshold['lat']]
            lons = [pt[1] for pt in path] + [runway_threshold['lon']]
            if impact_point:
                lats.append(impact_point[0])
                lons.append(impact_point[1])
            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

            # Slider setup. Phase-transition marks let the pilot scrub
            # directly to downwind start / 45° key / 90° (base) / final
            # entry / touchdown without hunting. Mirrors the marker layout
            # used by impossible_turn.
            max_time = hover_data[-1]["time"] if hover_data else 100
            slider_marks = {}
            # Procedural milestones (positions in hover_data) → time labels.
            milestone_label_at = {}
            if proc_idxs.get("abeam_idx") is not None:
                milestone_label_at[int(round(
                    hover_data[proc_idxs["abeam_idx"]]["time"]))] = "Abeam"
            if proc_idxs.get("key45_idx") is not None:
                milestone_label_at[int(round(
                    hover_data[proc_idxs["key45_idx"]]["time"]))] = "45° key"
            if proc_idxs.get("turn90_idx") is not None:
                milestone_label_at[int(round(
                    hover_data[proc_idxs["turn90_idx"]]["time"]))] = "90° base"
            # Segment-transition labels for the remaining boundaries.
            for idx, seg in _phase_transition_indices(hover_data):
                if idx >= len(hover_data):
                    continue
                t_mark = int(round(float(hover_data[idx].get("time", 0))))
                if seg == "downwind" and t_mark == 0:
                    slider_marks[0] = "Start"
                elif seg == "final":
                    slider_marks[t_mark] = "Final"
            # Overlay procedural milestones LAST so they win any collision.
            slider_marks.update(milestone_label_at)
            # End label
            end_label = ("Touchdown" if results.get("success", False)
                         else "Impact")
            slider_marks[int(max_time)] = end_label
            if 0 not in slider_marks:
                slider_marks[0] = "Start"

            # Prepare hover store with slip data. The sim emits `slip_pct`
            # (a percentage 0-100 ready for display) per tick — earlier
            # builds dropped that key and only kept `slip_intensity`
            # (a 0-1 ratio used internally), so the scrubber tooltip's
            # `pt.get('slip_pct', 0)` always returned 0 even mid-slip.
            hover_store = [
                {
                    "time": pt.get("time", 0),
                    "alt": pt.get("alt", 0),
                    "ias": pt.get("ias", 0),
                    "tas": pt.get("tas", 0),
                    "gs": pt.get("gs", 0),
                    "aob": pt.get("aob", 0),
                    "vs": pt.get("vs", 0),
                    "track": pt.get("track", 0),
                    "heading": pt.get("heading", 0),
                    "drift": pt.get("drift", 0),
                    "segment": pt.get("segment", ""),
                    "slip_active": pt.get("slip_active", False),
                    "slip_intensity": pt.get("slip_intensity", 0),
                    "slip_pct": pt.get("slip_pct", 0),
                }
                for pt in hover_data
            ]

            # Build info panel with slip reporting
            slip_used = results.get('slip_used', False)
            slip_pct = results.get('slip_intensity_pct', 0)
            best_glide = results.get('best_glide_kias', 0)
            base_gr = results.get('base_glide_ratio', 0)
            eff_gr = results.get('effective_glide_ratio', base_gr)
            max_bank = results.get('max_bank_deg', 0)
            headwind = results.get('headwind_on_final_kt', 0)
            crosswind = results.get('crosswind_on_final_kt', 0)
            xwind_dir = results.get('crosswind_direction', 'none')

            # Success/Failure banner
            if success:
                result_banner = html.Div(
                    f"SUCCESSFUL - Touchdown {'+' if td_error >= 0 else ''}{td_error:.0f} ft",
                    style={"fontWeight": "bold", "color": "#28a745", "marginBottom": "8px", "fontSize": "12px"}
                )
            else:
                result_banner = html.Div(
                    f"{'SHORT' if td_error < 0 else 'LONG'} - {abs(td_error):.0f} ft {'before' if td_error < 0 else 'beyond'} target",
                    style={"fontWeight": "bold", "color": "#dc3545", "marginBottom": "8px", "fontSize": "12px"}
                )

            # Slip info section
            if slip_used:
                slip_section = [
                    html.Div([html.Strong("Forward Slip Applied")], style={"marginBottom": "4px", "color": "#fd7e14"}),
                    html.Div(f"Intensity: {slip_pct:.0f}%", style={"fontSize": "11px"}),
                    html.Div(f"Glide ratio reduced: {base_gr:.1f}:1 → {eff_gr:.1f}:1", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                ]
            else:
                slip_section = [
                    html.Div("No slip required", style={"fontSize": "11px", "color": "#28a745"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                ]

            # Post-2026-05-21 audit fields — surface stall margin + clamp
            # warning + bank-cap state so the pilot sees what the sim
            # had to compromise on.
            stall_margin = results.get("stall_margin_kt")
            stall_v_at_n = results.get("stall_speed_at_bank_kt")
            stall_capped = results.get("bank_stall_capped", False)
            bank_geo_unclamped = results.get("bank_geometry_unclamped_deg")
            final_clamp = results.get("final_distance_clamp")

            if isinstance(stall_margin, (int, float)):
                if stall_margin < 4:
                    sc_color = "#dc2626"
                elif stall_margin < 8:
                    sc_color = "#f59e0b"
                else:
                    sc_color = "#16a34a"
                stall_line = (f"Stall margin: {stall_margin:+.1f} kt "
                              f"(Vs×√n = {stall_v_at_n:.0f} kt)")
                if stall_capped:
                    stall_line += f" · bank capped from {bank_geo_unclamped:.0f}° to keep margin"
            else:
                sc_color = "#666"
                stall_line = "Stall margin: n/a"

            clamp_msg = None
            if final_clamp == "too_short":
                clamp_msg = ("Energy budget: too LITTLE altitude for this "
                             "abeam distance — final-leg clamped to 300 ft. "
                             "Consider higher pattern altitude or shorter abeam.")
            elif final_clamp == "too_long":
                clamp_msg = ("Energy budget: too MUCH altitude for this "
                             "abeam distance — final-leg clamped to 1,500 ft. "
                             "Consider lower pattern altitude or longer abeam.")

            info_content = dbc.Accordion([
                dbc.AccordionItem([
                    result_banner,
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    html.Div([html.Strong("Aircraft Performance")], style={"marginBottom": "4px"}),
                    html.Div(f"Best Glide: {best_glide:.0f} KIAS | Weight: {total_wt:.0f} lb", style={"fontSize": "11px"}),
                    html.Div(f"Glide Ratio: {base_gr:.1f}:1 | Max Bank: {max_bank:.1f}°", style={"fontSize": "11px"}),
                    html.Div(stall_line, style={"fontSize": "11px", "color": sc_color, "fontWeight": "500"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    *slip_section,

                    html.Div([html.Strong("Wind Analysis")], style={"marginBottom": "4px"}),
                    html.Div(f"Wind: {wind_dir_val:.0f}° at {wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                    html.Div(f"On Final: {'Headwind' if headwind > 0 else 'Tailwind'} {abs(headwind):.0f} kt | Crosswind {crosswind:.0f} kt from {xwind_dir}", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    html.Div([html.Strong("Pattern Data")], style={"marginBottom": "4px"}),
                    html.Div(f"Altitude: {pattern_alt:.0f} ft AGL | Abeam: {abeam_dist:.2f} nm", style={"fontSize": "11px"}),
                    html.Div(f"Runway: {runway_heading:.0f}° | {pattern_dir.title()} pattern", style={"fontSize": "11px"}),
                    html.Div(f"Flaps: {flap_setting or 'clean'} | Time: {max_time:.1f}s", style={"fontSize": "11px"}),
                    *([html.Div(clamp_msg, style={"fontSize": "11px", "color": "#f59e0b", "fontWeight": "500", "marginTop": "4px"})]
                      if clamp_msg else []),
                ], title="Simulation Results", style={"fontSize": "12px"}),
                # 3D Side View — the entire power-off 180 maneuver is a
                # glide from pattern altitude down to touchdown; the side
                # view shows the descent profile through the turn. Runway
                # is rendered on the ground plane so the pilot can see
                # exactly where the path lands relative to the strip.
                side_view_accordion_item(
                    build_3d_side_view_block(
                        path=path,
                        hover=hover_data,
                        elev_ft=float(elev_ft or 0.0),
                        runway=_po180_runway_3d_dict(
                            runway_threshold,
                            float(runway_heading),
                            float(runway_length_ft),
                            float(elev_ft or 0.0),
                        ),
                    )
                ),
            ], start_collapsed=False, style={"marginTop": "8px"})

            # Live winds-aloft chip — matches impossible_turn / engine-out.
            winds_chip = _winds_aloft_chip(wind_profile_data)
            if winds_chip is not None:
                info_content = html.Div([info_content, winds_chip])

            btn_class = (BTN_BASE + " shelf-action-success" if success
                          else BTN_BASE + " shelf-action-failure")
            return elements, bounds, msg, hover_store, path, {"display": "block"}, int(max_time), slider_marks, 0, info_content, btn_class

        except Exception as e:
            import traceback
            log.error(f"EXCEPTION in draw_poweroff180(): {e}")
            traceback.print_exc()
            return [], None, f"Error: {str(e)}", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

    @app.callback(
        Output("scrubber-layer", "children", allow_duplicate=True),
        Input("poweroff180-time-slider", "value"),
        State("poweroff180-hover-store", "data"),
        State("poweroff180-path-store", "data"),
        prevent_initial_call=True
    )
    def update_poweroff180_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position."""
        if not hover_data or not path_data or slider_value is None:
            return []

        # Find the closest hover point by time
        target_time = slider_value
        best_idx = 0
        best_diff = abs(hover_data[0]["time"] - target_time)
        for i, pt in enumerate(hover_data):
            diff = abs(pt["time"] - target_time)
            if diff < best_diff:
                best_diff = diff
                best_idx = i

        idx = best_idx
        if idx >= len(path_data):
            idx = len(path_data) - 1

        pt = hover_data[best_idx]
        pos = path_data[idx]

        segment = pt.get('segment', 'glide')
        slip_pct = pt.get('slip_pct', 0)

        # Build tooltip with slip info (always show slip percentage)
        tooltip_content = [
            html.Div(f"{segment.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
            # PO180 sim emits `drift = heading − track` (positive ⇒ nose
            # right of track ⇒ RIGHT crab). The earlier label flipped the
            # sign — same code path as impossible_turn's tooltip, but
            # impossible_turn's sim uses the opposite convention, so the
            # label happened to be correct there. Resolve drift via
            # heading/track if the explicit value isn't present.
            html.Div(
                _po180_crab_display(pt),
            ),
            html.Div(f"Slip: {slip_pct:.0f}%", style={"color": "#fd7e14" if slip_pct > 0 else "#666", "fontWeight": "bold" if slip_pct > 0 else "normal"}),
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        # Marker `crab` parameter expects "nose offset from track" in
        # the standard right-positive convention, which matches the
        # sim's drift sign. (Earlier code negated — but that produced
        # the visually wrong marker orientation as well; the visual
        # being "approximately right" before was a coincidence of
        # symmetric scenarios.)
        crab = float(pt.get('drift', 0) or 0)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]
