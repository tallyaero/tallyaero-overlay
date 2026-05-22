"""Impossible Turn draw + scrubber callbacks.

Engine-failure-after-takeoff simulation. Inputs: aircraft + environment +
runway geometry + reaction parameters. Outputs: map layer with takeoff/climb/
glide path (color-coded by phase), runway overlay, success/impact marker,
bounds, info panel, scrubber state.
"""

from __future__ import annotations

import dash
from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
from geopy.point import Point as GeoPoint
from geopy.distance import distance as geo_distance
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.log import get_logger

from utility import simulate_impossible_turn

from callbacks.map import calculate_runway_geometry, create_airplane_marker
from layouts.maneuvers._shared import _winds_aloft_chip

from core.data_loader import aircraft_data, airport_data
from core.profile3d import build_3d_side_view_block, side_view_accordion_item

log = get_logger(__name__)


def _runway_3d_dict_for_impossible_turn(
    threshold_pt: dict,
    runway_heading_deg: float,
    runway_length_ft: float,
    elev_ft: float,
) -> dict:
    """Build the `runway` dict the profile3d helper consumes.

    Departure threshold (where the user clicked) becomes the START point;
    the opposite end (advance along runway_heading by runway_length_ft)
    becomes the END point. Drawing both into the ground plane gives the
    pilot the same orientation cue they have on the 2D map.
    """
    from physics import point_from, FT_PER_NM
    from geopy.point import Point as _GP

    start_pt = _GP(float(threshold_pt["lat"]), float(threshold_pt["lon"]))
    end_pt = point_from(start_pt, float(runway_heading_deg),
                        float(runway_length_ft) / FT_PER_NM)
    return {
        "start_lat": start_pt.latitude,
        "start_lon": start_pt.longitude,
        "end_lat": end_pt.latitude,
        "end_lon": end_pt.longitude,
        "elev_ft": float(elev_ft or 0.0),
    }


def register(app):
    """Install Impossible Turn callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output({"type": "click-status", "m_id": "impossible_turn"}, "children", allow_duplicate=True),
        Output("impossibleturn-result", "children", allow_duplicate=True),
        Output("impossibleturn-hover-store", "data"),
        Output("impossibleturn-path-store", "data"),
        Output("impossibleturn-slider-container", "style"),
        Output("impossibleturn-time-slider", "max"),
        Output("impossibleturn-time-slider", "marks"),
        Output("impossibleturn-time-slider", "value"),
        Output("impossibleturn-info", "children"),
        Output({"type": "sim-results-btn", "m_id": "impossible_turn"}, "className", allow_duplicate=True),
        Input({"type": "draw-btn", "m_id": "impossible_turn"}, "n_clicks"),
        State({"type": "point-store", "m_id": "impossible_turn", "role": "start"}, "data"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("occupants", "value"),
        State("occupant-weight", "value"),
        State("fuel-load", "value"),
        State("cg-slider", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("impossibleturn-direction", "value"),
        State("impossibleturn-runway-select", "value"),
        State("impossibleturn-manual-heading", "value"),
        State("impossibleturn-altitude", "value"),
        State("impossibleturn-reaction-sec", "value"),
        State("impossibleturn-climb-speed", "value"),
        State("impossibleturn-flap-config", "value"),
        State("impossibleturn-prop-config", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("wind-profile-store", "data"),
        prevent_initial_call=True,
    )
    def draw_impossible_turn(
        n_clicks,
        failure_data,
        ac_name,
        engine_key,
        occupants,
        occupant_wt,
        fuel_gal,
        cg_pos,
        wind_dir,
        wind_speed,
        oat_f,
        altimeter,
        turn_dir,
        runway_select,
        manual_heading,
        failure_alt_agl,
        reaction_sec,
        entry_ias,
        flap_config,
        prop_config,
        selected_airport_id,
        runtime_weight,
        wind_profile_data,
    ):
        if not n_clicks:
            raise PreventUpdate

        BTN_BASE = "shelf-action shelf-action-results"

        if not failure_data:
            return [], None, "Set takeoff point (runway threshold) first.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

        if not ac_name or not engine_key:
            return [], None, "Select aircraft and engine first.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

        try:
            states = dash.callback_context.states

            def safe_float(state_key):
                v = states.get(state_key)
                return float(v) if v not in [None, "", "null"] else None

            # Phase F — runway-select drives the runway length + threshold
            # point only. The heading input is the single source of truth,
            # interpreted as magnetic when an airport is selected (pilot
            # convention) and converted to true for the geometry.
            runway_length_ft = 5000  # Default
            runway_id_selected = states.get("impossibleturn-runway-select.value")
            if runway_id_selected and selected_airport_id:
                from callbacks.aircraft import _resolve_runway_end
                end = _resolve_runway_end(selected_airport_id, runway_id_selected)
                if end and end.get("length_ft"):
                    runway_length_ft = float(end["length_ft"])

            heading_input = safe_float("impossibleturn-manual-heading.value")
            if heading_input is None:
                runway_heading = None
            elif selected_airport_id:
                from callbacks.aircraft import _airport_magvar, _mag_to_true
                airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
                runway_heading = _mag_to_true(heading_input, _airport_magvar(airport))
            else:
                runway_heading = float(heading_input)

            failure_alt_agl = safe_float("impossibleturn-altitude.value")
            reaction_sec    = safe_float("impossibleturn-reaction-sec.value")
            entry_ias       = safe_float("impossibleturn-climb-speed.value")
            wind_dir        = safe_float("env-wind-dir.value")
            wind_speed      = safe_float("env-wind-speed.value")
            oat_f           = safe_float("env-oat.value")
            altimeter       = safe_float("env-altimeter.value")

            # Weight: use runtime store only
            total_wt = safe_float("runtime-total-weight-lb.data")
            if total_wt is None:
                # fallback to State value if callback_context didn't capture it
                total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None

            required = [
                runway_heading, failure_alt_agl, reaction_sec, entry_ias,
                wind_dir, wind_speed, oat_f, altimeter,
                total_wt,
            ]
            if any(x is None for x in required):
                return [], None, "Missing or invalid inputs.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

            # The clicked point is now the runway threshold (takeoff start point)
            threshold_pt = {"lat": failure_data["lat"], "lon": failure_data["lon"]}
            threshold_geopoint = GeoPoint(failure_data["lat"], failure_data["lon"])

            # Aircraft dict copy + stash runtime weight (no JSON changes)
            ac = dict(aircraft_data[ac_name])
            ac["total_weight_lb"] = float(total_wt)

            # Airport elevation reference
            selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
            airport_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

            # OAT F -> C
            oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0

            # Determine if we should include takeoff/climb simulation
            # Enable when airport is selected and we have runway data
            include_takeoff_climb = bool(selected_airport_id and runway_id_selected)

            # Phase H — hydrate live winds-aloft column if airport-pick
            # staged one. Sim picks wind at the maneuver's mid-altitude.
            wind_profile = None
            if wind_profile_data:
                try:
                    from core.winds_aloft import WindProfile
                    wind_profile = WindProfile.from_store(wind_profile_data)
                except Exception:
                    wind_profile = None

            path, hover, meta = simulate_impossible_turn(
                start_point=threshold_geopoint,  # Legacy fallback
                runway_heading_deg=float(runway_heading),
                turn_dir=str(turn_dir),
                reaction_sec=float(reaction_sec),
                start_ias_kias=float(entry_ias),
                altitude_agl=float(failure_alt_agl),

                ac=ac,
                engine_option=engine_key,
                weight_lbs=float(total_wt),
                oat_c=float(oat_c),
                altimeter_inhg=float(altimeter),
                wind_dir=float(wind_dir),
                wind_speed=float(wind_speed),
                wind_profile=wind_profile,
                timestep_sec=0.5,
                flap_config=flap_config,
                prop_config=prop_config,
                touchdown_elev_ft=float(airport_elev_ft),
                find_min_alt=True,

                # NEW: Takeoff/climb parameters
                include_takeoff_climb=include_takeoff_climb,
                threshold_point=threshold_pt if include_takeoff_climb else None,
                runway_length_ft=float(runway_length_ft) if include_takeoff_climb else None,
            )

            if not path:
                return [], None, "No path generated. Check inputs.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

            # Meta
            meta = meta or {}
            made_it      = bool(meta.get("success", False))
            impact       = meta.get("impact_marker", None)
            reason       = meta.get("reason", "unknown")
            min_required = meta.get("min_feasible_alt_agl", None)
            bank_deg     = meta.get("bank_deg", None)
            has_takeoff_climb = meta.get("include_takeoff_climb", False)
            ground_roll_ft = meta.get("ground_roll_ft", None)

            # Find engine failure point from hover data (end of climb phase or start of reaction)
            failure_point_for_distance = threshold_geopoint  # Default to threshold
            if has_takeoff_climb and hover:
                # Find the first point where phase changes from 'climb' to something else
                for i, pt in enumerate(hover):
                    phase = pt.get("phase", "")
                    if phase in ["reaction", "turn1"]:
                        # Get position from path at this index
                        if i < len(path):
                            failure_point_for_distance = GeoPoint(float(path[i][0]), float(path[i][1]))
                        break

            # Distance (NM): failure point -> impact (if any) else -> end of path
            dist_nm = None
            try:
                if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
                    end_pt = GeoPoint(float(impact[0]), float(impact[1]))
                    dist_nm = geo_distance(failure_point_for_distance, end_pt).nm
                    dist_label = "Failure distance to impact"
                else:
                    end_lat, end_lon = path[-1][0], path[-1][1]
                    end_pt = GeoPoint(float(end_lat), float(end_lon))
                    dist_nm = geo_distance(failure_point_for_distance, end_pt).nm
                    dist_label = "Failure distance to touchdown"
            except Exception:
                dist_nm = None
                dist_label = "Distance"

            dist_txt = f"{dist_label}: {dist_nm:.2f} NM" if isinstance(dist_nm, (int, float)) else f"{dist_label}: n/a"

            elements = []

            # ---------- Multi-phase visualization ----------
            if has_takeoff_climb and hover:
                # Separate path into: takeoff (green), climb (blue), glide (red)
                takeoff_pts = []
                climb_pts = []
                glide_pts = []  # Everything after engine failure

                for i, pt in enumerate(hover):
                    phase = pt.get("phase", "unknown")
                    if i < len(path):
                        if phase == "takeoff":
                            takeoff_pts.append(path[i])
                        elif phase == "climb":
                            climb_pts.append(path[i])
                        else:
                            # All post-failure phases: reaction, turn1, straight, turn2, final
                            glide_pts.append(path[i])

                # Theme B takeoff phase — start (green-500)
                if len(takeoff_pts) >= 2:
                    elements.append(dl.Polyline(positions=takeoff_pts, color="#22c55e", weight=4, opacity=0.85))

                # Theme B climb phase — path-active (blue-600)
                if len(climb_pts) >= 2:
                    if takeoff_pts:
                        climb_with_connection = [takeoff_pts[-1]] + climb_pts
                    else:
                        climb_with_connection = climb_pts
                    elements.append(dl.Polyline(positions=climb_with_connection, color="#0d59f2", weight=3, opacity=0.85))

                # Theme B glide phase — intermediate (amber-500)
                if len(glide_pts) >= 2:
                    if climb_pts:
                        glide_with_connection = [climb_pts[-1]] + glide_pts
                    else:
                        glide_with_connection = glide_pts
                    elements.append(dl.Polyline(positions=glide_with_connection, color="#f59e0b", weight=3, opacity=0.85))

                # Takeoff threshold — start (green-500)
                elements.append(
                    dl.CircleMarker(
                        center=[threshold_geopoint.latitude, threshold_geopoint.longitude],
                        radius=7,
                        color="#22c55e",
                        fill=True,
                        fillOpacity=1.0,
                        children=dl.Tooltip("Takeoff point (runway threshold)"),
                    )
                )

                # Engine-failure marker — red circle, white "X", professional
                # geometric SVG (replaces the prior literal `<text>X</text>`
                # placeholder which rendered as raw black text).
                if failure_point_for_distance != threshold_geopoint:
                    failure_icon = {
                        "iconUrl": "data:image/svg+xml;utf8," + (
                            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
                            "<circle cx='16' cy='16' r='13' fill='%23dc2626' stroke='white' stroke-width='2'/>"
                            "<path d='M 10 10 L 22 22 M 22 10 L 10 22' stroke='white' stroke-width='3' stroke-linecap='round'/>"
                            "</svg>"
                        ),
                        "iconSize": [30, 30],
                        "iconAnchor": [15, 15],
                    }
                    elements.append(
                        dl.Marker(
                            position=[failure_point_for_distance.latitude, failure_point_for_distance.longitude],
                            icon=failure_icon,
                            children=dl.Tooltip(f"Engine failure ({float(failure_alt_agl):.0f} ft AGL)"),
                        )
                    )

                # Add runway overlay polygon
                if runway_length_ft and runway_heading:
                    try:
                        runway_coords = calculate_runway_geometry(
                            threshold_pt["lat"],
                            threshold_pt["lon"],
                            float(runway_heading),
                            float(runway_length_ft),
                            width_ft=100  # Standard runway width
                        )
                        # Add as solid black polygon at the bottom of the layer stack
                        elements.insert(0, dl.Polygon(
                            positions=runway_coords,
                            color="#000000",
                            fillColor="#1a1a1a",
                            fillOpacity=0.9,
                            weight=2,
                            children=dl.Tooltip(f"Runway {runway_id_selected or ''} ({runway_length_ft:.0f} ft)"),
                        ))

                        from physics import point_from, FT_PER_NM
                        threshold_geo = GeoPoint(threshold_pt["lat"], threshold_pt["lon"])
                        rwy_hdg = float(runway_heading)
                        rwy_len = float(runway_length_ft)
                        opposite = point_from(threshold_geo, rwy_hdg, rwy_len / FT_PER_NM)

                        # Add white dashed centerline
                        elements.insert(1, dl.Polyline(
                            positions=[
                                [threshold_pt["lat"], threshold_pt["lon"]],
                                [opposite.latitude, opposite.longitude]
                            ],
                            color="#FFFFFF",
                            weight=2,
                            dashArray="20, 15",
                        ))

                        # === PIANO KEYS (Threshold Markings) at both ends ===
                        # 8 stripes for 100ft runway, each ~6ft wide with gaps
                        # Stripes are 150ft long, start 20ft from threshold
                        piano_key_length_ft = min(150.0, rwy_len * 0.15)  # Scale for short runways
                        piano_key_width_ft = 6.0
                        piano_key_gap_ft = 6.0
                        piano_key_offset_ft = 20.0  # Start 20ft from threshold
                        num_stripes = 8  # For 100ft runway
                        total_stripe_width = num_stripes * piano_key_width_ft + (num_stripes - 1) * piano_key_gap_ft
                        stripe_start_offset = -total_stripe_width / 2 + piano_key_width_ft / 2

                        perp_left = (rwy_hdg - 90) % 360
                        perp_right = (rwy_hdg + 90) % 360
                        opposite_hdg = (rwy_hdg + 180) % 360

                        # Draw piano keys at departure threshold
                        for i in range(num_stripes):
                            lateral_offset_ft = stripe_start_offset + i * (piano_key_width_ft + piano_key_gap_ft)
                            # Start point of stripe
                            start_pt = point_from(threshold_geo, rwy_hdg, piano_key_offset_ft / FT_PER_NM)
                            if lateral_offset_ft > 0:
                                start_pt = point_from(start_pt, perp_right, abs(lateral_offset_ft) / FT_PER_NM)
                            else:
                                start_pt = point_from(start_pt, perp_left, abs(lateral_offset_ft) / FT_PER_NM)
                            # End point of stripe
                            end_pt = point_from(start_pt, rwy_hdg, piano_key_length_ft / FT_PER_NM)
                            elements.append(dl.Polyline(
                                positions=[[start_pt.latitude, start_pt.longitude], [end_pt.latitude, end_pt.longitude]],
                                color="#FFFFFF",
                                weight=3,
                            ))

                        # Draw piano keys at arrival threshold (opposite end)
                        for i in range(num_stripes):
                            lateral_offset_ft = stripe_start_offset + i * (piano_key_width_ft + piano_key_gap_ft)
                            # Start point of stripe (from opposite end, going back toward departure)
                            start_pt = point_from(opposite, opposite_hdg, piano_key_offset_ft / FT_PER_NM)
                            if lateral_offset_ft > 0:
                                start_pt = point_from(start_pt, perp_right, abs(lateral_offset_ft) / FT_PER_NM)
                            else:
                                start_pt = point_from(start_pt, perp_left, abs(lateral_offset_ft) / FT_PER_NM)
                            # End point of stripe
                            end_pt = point_from(start_pt, opposite_hdg, piano_key_length_ft / FT_PER_NM)
                            elements.append(dl.Polyline(
                                positions=[[start_pt.latitude, start_pt.longitude], [end_pt.latitude, end_pt.longitude]],
                                color="#FFFFFF",
                                weight=3,
                            ))

                        # === CAPTAIN'S BARS (Aiming Point Markings) 1000ft from each threshold ===
                        # Two bars per end, 150ft long x 20ft wide, on each side of centerline
                        captains_bar_offset_ft = 1000.0
                        captains_bar_length_ft = min(150.0, rwy_len * 0.1)  # Scale for short runways
                        captains_bar_lateral_offset_ft = 15.0  # Distance from centerline to inner edge

                        # Only draw captain's bars if runway is long enough (>2500ft)
                        if rwy_len >= 2500:
                            # Captain's bars near departure threshold
                            bar_center_dep = point_from(threshold_geo, rwy_hdg, captains_bar_offset_ft / FT_PER_NM)
                            for side_hdg, side_offset in [(perp_left, captains_bar_lateral_offset_ft), (perp_right, captains_bar_lateral_offset_ft)]:
                                bar_start = point_from(bar_center_dep, side_hdg, side_offset / FT_PER_NM)
                                bar_end = point_from(bar_start, rwy_hdg, captains_bar_length_ft / FT_PER_NM)
                                elements.append(dl.Polyline(
                                    positions=[[bar_start.latitude, bar_start.longitude], [bar_end.latitude, bar_end.longitude]],
                                    color="#FFFFFF",
                                    weight=6,
                                ))

                            # Captain's bars near arrival threshold (opposite end)
                            bar_center_arr = point_from(opposite, opposite_hdg, captains_bar_offset_ft / FT_PER_NM)
                            for side_hdg, side_offset in [(perp_left, captains_bar_lateral_offset_ft), (perp_right, captains_bar_lateral_offset_ft)]:
                                bar_start = point_from(bar_center_arr, side_hdg, side_offset / FT_PER_NM)
                                bar_end = point_from(bar_start, opposite_hdg, captains_bar_length_ft / FT_PER_NM)
                                elements.append(dl.Polyline(
                                    positions=[[bar_start.latitude, bar_start.longitude], [bar_end.latitude, bar_end.longitude]],
                                    color="#FFFFFF",
                                    weight=6,
                                ))
                    except Exception as e:
                        log.warning(f"Could not draw runway overlay: {e}")
            else:
                # Legacy single-color visualization — Theme B
                start_marker = dl.CircleMarker(
                    center=[threshold_geopoint.latitude, threshold_geopoint.longitude],
                    radius=7,
                    color="#22c55e",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip("Engine failure point"),
                )
                elements.append(start_marker)
                arc_line = dl.Polyline(positions=path, color="#f59e0b", weight=3, opacity=0.85)
                elements.append(arc_line)

            # End-point marker — proper geometric icons keyed to the
            # outcome. Success = green check, failure = red X. Both ride
            # on a white-bordered circle so they pop against any basemap.
            if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
                if made_it:
                    end_icon = {
                        "iconUrl": "data:image/svg+xml;utf8," + (
                            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
                            "<circle cx='16' cy='16' r='13' fill='%2316a34a' stroke='white' stroke-width='2'/>"
                            "<path d='M 9 16 L 14 21 L 23 11' stroke='white' stroke-width='3' fill='none' stroke-linecap='round' stroke-linejoin='round'/>"
                            "</svg>"
                        ),
                        "iconSize": [32, 32],
                        "iconAnchor": [16, 16],
                    }
                    tooltip_text = "Successful landing"
                else:
                    end_icon = {
                        "iconUrl": "data:image/svg+xml;utf8," + (
                            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
                            "<circle cx='16' cy='16' r='13' fill='%23dc2626' stroke='white' stroke-width='2'/>"
                            "<path d='M 10 10 L 22 22 M 22 10 L 10 22' stroke='white' stroke-width='3' stroke-linecap='round'/>"
                            "</svg>"
                        ),
                        "iconSize": [32, 32],
                        "iconAnchor": [16, 16],
                    }
                    tooltip_text = "Impact point"
                elements.append(
                    dl.Marker(
                        position=[impact[0], impact[1]],
                        icon=end_icon,
                        children=dl.Tooltip(tooltip_text),
                    )
                )

            # Bounds
            lats = [p[0] for p in path] + [threshold_geopoint.latitude]
            lons = [p[1] for p in path] + [threshold_geopoint.longitude]
            if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
                lats.append(impact[0])
                lons.append(impact[1])
            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

            # Status - provide clear failure reasons
            if made_it:
                status = "Impossible turn: successful"
            else:
                # Map failure reasons to user-friendly messages
                reason_messages = {
                    "landed_short": "landed short of runway",
                    "off_centerline": "missed runway (off centerline)",
                    "overshot": "overshot runway (past departure threshold)",
                    "impact": "ground impact",
                    "timeout": "simulation timeout",
                }
                reason_text = reason_messages.get(reason, reason.replace("_", " "))
                status = f"Impossible turn: unsuccessful - {reason_text}"

            # Result text
            bank_txt = f"{float(bank_deg):.0f}°" if isinstance(bank_deg, (int, float)) else "n/a"

            # Result-text logic (the headline shown above the diagnostics).
            # Branch on whether the main run actually succeeded FIRST so a
            # successful turn-back never gets the "not feasible" message
            # just because the min-altitude bisection couldn't converge.
            if made_it:
                if isinstance(min_required, (int, float)):
                    result = (
                        f"Recommended constant bank: {bank_txt}. "
                        f"Minimum failure altitude (AGL): {float(min_required):.0f} ft. "
                        f"{dist_txt}."
                    )
                else:
                    # Main run worked but the bisection didn't find a
                    # tighter floor (search exhausted or skipped).
                    # Report the user's altitude as the known-working
                    # value so they have a real number to compare.
                    result = (
                        f"Recommended constant bank: {bank_txt}. "
                        f"Minimum failure altitude (AGL): not refined further (works at {float(failure_alt_agl):.0f} ft). "
                        f"{dist_txt}."
                    )
            elif meta.get("min_feasible_alt_exceeds_ceiling"):
                # Main run failed AND the search couldn't find any
                # altitude that works — the configuration is infeasible.
                reason_kind = meta.get("min_infeasibility_reason") or "needs_more_altitude"
                if reason_kind == "structurally_infeasible":
                    result = (
                        f"Maneuver not feasible at this weight, runway, and reaction-time combination. "
                        f"Adding altitude makes the aircraft overshoot further — the airframe doesn't lose enough energy in the turn-back to land on this runway. "
                        f"{dist_txt}."
                    )
                else:
                    result = (
                        f"No feasible altitude found in the search range (up to 3,000 ft AGL). "
                        f"The maneuver may work at a higher engine-failure altitude, but that's outside the realistic impossible-turn band. "
                        f"{dist_txt}."
                    )
            else:
                # Main run failed; min-alt didn't fire (find_min_alt=False)
                # or fell through without a result.
                result = (
                    f"Maneuver did not succeed at {float(failure_alt_agl):.0f} ft AGL: {reason.replace('_', ' ')}. "
                    f"{dist_txt}."
                )

            # Build slider marks based on time
            max_time = hover[-1]["time"] if hover and len(hover) > 0 else 100
            # Phase-transition markers on the time scrubber so the pilot
            # can scrub directly to takeoff start / climb start / engine
            # failure / impact-or-touchdown without hunting. We walk the
            # hover stream once and record the first time each phase is
            # observed; the engine failure marker is the first non-climb
            # tick after climb ends (i.e. reaction phase start).
            slider_marks = {}
            phase_label_map = {
                "takeoff":  "Takeoff",
                "climb":    "Climb",
                "reaction": "Eng fail",   # short — fits in the slider's mark width
                "turn1":    "Turn",
                "final":    "Final",
            }
            seen_phases = set()
            for pt in (hover or []):
                ph = pt.get("phase")
                label = phase_label_map.get(ph)
                if label and ph not in seen_phases:
                    seen_phases.add(ph)
                    t_mark = int(round(float(pt.get("time", 0))))
                    # Skip duplicate-second collisions — Dash slider marks
                    # are keyed by their position int, so two marks at the
                    # same second would overwrite each other anyway.
                    slider_marks[t_mark] = label
            # End marker — "Touchdown" on success, "Impact" on failure.
            end_label = "Touchdown" if made_it else "Impact"
            slider_marks[int(max_time)] = end_label
            # Ensure there's always a Start label at t=0 even if takeoff
            # mark already used it; takeoff IS the start, so keep takeoff's
            # label there. If no takeoff phase (legacy single-phase mode),
            # fall back to "Start".
            if 0 not in slider_marks:
                slider_marks[0] = "Start"

            # Prepare hover data for store (ensure JSON-serializable)
            # Resolve `drift` for every step. The takeoff + climb sim emits
            # `wca` (wind-correction angle: heading − track); the glide sim
            # emits `drift` (track − heading). They are sign-flipped versions
            # of the same number. Bridging them here so the scrubber tooltip
            # has a single coherent "Crab" reading for every tick.
            def _resolve_drift(pt):
                d = pt.get("drift")
                if d is not None:
                    return float(d)
                wca = pt.get("wca")
                if wca is not None:
                    return -float(wca)
                return 0.0

            hover_store = []
            if hover and isinstance(hover, list):
                hover_store = [
                    {
                        "time": pt.get("time", 0),
                        "alt": pt.get("alt", pt.get("alt_agl", 0)),  # Support both old and new format
                        "alt_agl": pt.get("alt_agl", pt.get("alt", 0)),
                        "alt_msl": pt.get("alt_msl", 0),
                        "ias": pt.get("ias", pt.get("tas", 0)),
                        "tas": pt.get("tas", 0),
                        "gs": pt.get("gs", pt.get("tas", 0)),
                        "aob": pt.get("aob", pt.get("bank", 0)),
                        "vs": pt.get("vs", 0),
                        "track": pt.get("track", 0),
                        "heading": pt.get("heading", 0),
                        "drift": _resolve_drift(pt),
                        "phase": pt.get("phase", "unknown"),  # New: phase name
                        # Slip percent must be preserved so the scrubber's
                        # tooltip displays an actual number (was always 0
                        # pre-fix because the store dropped the field).
                        "slip_pct": pt.get("slip_pct", 0),
                    }
                    for pt in hover
                ]

            # Calculate glide metrics. Glide ratio = horizontal distance
            # covered per unit altitude lost. Pre-fix the formula was
            # alt / dist (inverse), so a 10:1 glide was displayed as
            # 0.1:1 — the displayed number was meaningless.
            dist_ft = (dist_nm * 6076.12) if dist_nm and dist_nm > 0 else 0
            if meta.get('glide_ratio'):
                glide_ratio = meta['glide_ratio']
            elif dist_ft > 0 and failure_alt_agl > 0:
                glide_ratio = dist_ft / float(failure_alt_agl)
            else:
                glide_ratio = 0
            avg_vs = 0
            avg_gs = 0
            if hover and len(hover) > 0:
                vs_values = [abs(pt.get('vs', 0)) for pt in hover if pt.get('vs') is not None]
                gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover if pt.get('gs') is not None or pt.get('tas') is not None]
                avg_vs = sum(vs_values) / len(vs_values) if vs_values else 0
                avg_gs = sum(gs_values) / len(gs_values) if gs_values else 0

            # Headline result line. Phase 6 — color-code by outcome so
            # success is unmistakeably green, near-miss is amber, and a
            # full failure is red. Border + background are tinted; text
            # color stays neutral for legibility against varied themes.
            if made_it:
                hl_bg = "rgba(22, 163, 74, 0.10)"   # green-600 @ 10%
                hl_border = "#16a34a"
            elif reason in ("off_centerline", "landed_short"):
                # Near-miss — fell just outside tolerance; amber.
                hl_bg = "rgba(245, 158, 11, 0.10)"
                hl_border = "#f59e0b"
            else:
                # Hard failure (overshot, impact, timeout) — red.
                hl_bg = "rgba(220, 38, 38, 0.10)"
                hl_border = "#dc2626"

            headline = html.Div(
                result,
                style={
                    "fontSize": "12px",
                    "fontWeight": "600",
                    "padding": "8px 10px",
                    "marginBottom": "8px",
                    "background": hl_bg,
                    "borderLeft": f"3px solid {hl_border}",
                    "borderRadius": "3px",
                    "color": "var(--ta-text-primary, #1e293b)",
                },
            )

            # Phase 6 — "Why it failed" bullet list when the run wasn't a
            # success. Surfaces the specific failure mode (overshot,
            # landed short, off centerline, etc.) plus the magnitude
            # of the miss so the pilot knows whether tweaking inputs
            # is likely to help or whether the maneuver is just
            # infeasible at this weight / altitude.
            failure_bullets = None
            if not made_it:
                final_xtrack = meta.get("final_xtrack_ft")
                final_along = meta.get("final_along_ft")
                bullets = []
                if reason == "overshot":
                    bullets.append("Flew past the departure-end threshold before reaching the centerline — try less reaction time, more bank, or higher failure altitude.")
                elif reason == "landed_short":
                    bullets.append(f"Ran out of altitude {abs(float(final_along) + (runway_length_ft or 0)):.0f} ft short of the arrival threshold." if isinstance(final_along, (int, float)) else "Ran out of altitude short of the runway.")
                elif reason == "off_centerline":
                    bullets.append(
                        f"Missed runway laterally by {abs(float(final_xtrack)):.0f} ft." if isinstance(final_xtrack, (int, float)) else "Missed runway laterally."
                    )
                elif reason == "timeout":
                    bullets.append("Simulation timed out before the aircraft could land — inputs may be inconsistent (heading vs runway, etc.).")
                elif reason == "impact":
                    bullets.append("Aircraft impacted before reaching the runway extended centerline.")
                if meta.get("min_feasible_alt_exceeds_ceiling"):
                    bullets.append("Maneuver appears not feasible at this aircraft/weight/wind — even at 5,000 ft AGL the turn-back didn't succeed.")
                elif isinstance(min_required, (int, float)) and min_required > failure_alt_agl:
                    bullets.append(f"This configuration would need at least {float(min_required):.0f} ft AGL at engine failure.")
                if bullets:
                    failure_bullets = html.Div([
                        html.Strong("Why it failed", style={"fontSize": "11px"}),
                        html.Ul(
                            [html.Li(b, style={"fontSize": "11px"}) for b in bullets],
                            style={"margin": "4px 0 8px 16px", "padding": 0},
                        ),
                    ])

            # Extra telemetry derived from hover stream (post-fix, Phase 7):
            #   max_bank_used — what the sim actually flew (vs recommended)
            #   capture_time  — when the turn-back finished alignment with final
            #   final_headwind — headwind component on the final glide leg
            max_bank_used = 0.0
            for pt in hover or []:
                aob = pt.get('aob', pt.get('bank', 0)) or 0
                if abs(aob) > max_bank_used:
                    max_bank_used = abs(aob)
            captured_t = meta.get('captured_time_sec')
            captured_txt = f"{captured_t:.1f}s" if isinstance(captured_t, (int, float)) else "n/a"

            # Phase 4 — stall margin at the recommended bank. Margin = best-
            # glide IAS − stall speed at that load factor. <8 kt is squeaky.
            stall_margin = meta.get("stall_margin_kt")
            stall_v_at_n = meta.get("stall_speed_at_bank_kt")
            stall_capped = meta.get("stall_capped_bank_deg")
            if isinstance(stall_margin, (int, float)):
                if stall_margin < 4:
                    stall_color = "#dc2626"   # red — at or below margin floor
                elif stall_margin < 8:
                    stall_color = "#f59e0b"   # amber — thin margin
                else:
                    stall_color = "#16a34a"   # green
                stall_txt = f"Stall margin: {stall_margin:+.1f} kt (Vs×√n = {stall_v_at_n:.0f} kt)"
            else:
                stall_color = "#666"
                stall_txt = "Stall margin: n/a"
            stall_cap_txt = (
                f" · bank capped at {stall_capped:.0f}° (stall)"
                if isinstance(stall_capped, (int, float)) else ""
            )

            # Headwind component on final = wind_speed × cos(wind_dir − final_track)
            # final_track = hdg of the last few hover points in final phase
            final_track = None
            for pt in reversed(hover or []):
                if pt.get('phase') in ('final', 'rollout'):
                    final_track = pt.get('track')
                    break
            if final_track is None and hover:
                final_track = hover[-1].get('track')
            if final_track is not None and wind_speed:
                import math as _m
                # Wind direction is FROM; convert to TO by adding 180 then take
                # component along reciprocal of final track (i.e. headwind).
                rel_deg = (float(wind_dir) - float(final_track)) % 360.0
                final_headwind = float(wind_speed) * _m.cos(_m.radians(rel_deg))
            else:
                final_headwind = None
            final_headwind_txt = (
                f"{final_headwind:+.0f} kt" if isinstance(final_headwind, (int, float)) else "n/a"
            )

            # Info content - standardized format with glide data
            info_content = dbc.Accordion([
                dbc.AccordionItem([
                    headline,
                    *( [failure_bullets] if failure_bullets is not None else [] ),
                    html.Div([html.Strong("Aircraft & Environment")], style={"marginBottom": "4px"}),
                    html.Div(f"Weight: {total_wt:.0f} lb | Entry IAS: {entry_ias:.0f} kt", style={"fontSize": "11px"}),
                    html.Div(f"Wind: {wind_dir:.0f}° at {wind_speed:.0f} kt | Final headwind: {final_headwind_txt}", style={"fontSize": "11px"}),
                    html.Div(f"Flaps: {flap_config or 'None'} | Prop: {prop_config or 'Windmilling'}", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div([html.Strong("Takeoff Performance")], style={"marginBottom": "4px"}),
                    html.Div(f"Ground roll: {ground_roll_ft:.0f} ft" if ground_roll_ft else "Ground roll: n/a", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div([html.Strong("Glide Performance")], style={"marginBottom": "4px"}),
                    html.Div(f"Glide ratio: ~{glide_ratio:.1f}:1 | Avg GS: {avg_gs:.0f} kt | VS: {avg_vs:.0f} fpm" if glide_ratio > 0 else "Glide ratio: calculating...", style={"fontSize": "11px"}),
                    html.Div(f"Distance: {dist_nm:.2f} nm | Max bank used: {max_bank_used:.0f}°{stall_cap_txt}" if dist_nm else f"Max bank used: {max_bank_used:.0f}°{stall_cap_txt}", style={"fontSize": "11px"}),
                    html.Div(stall_txt, style={"fontSize": "11px", "color": stall_color, "fontWeight": "500"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div([html.Strong("Altitude & Timing")], style={"marginBottom": "4px"}),
                    html.Div(f"Failure: {failure_alt_agl:.0f} ft AGL | Min req: {min_required:.0f} ft" if min_required else f"Failure: {failure_alt_agl:.0f} ft AGL", style={"fontSize": "11px"}),
                    html.Div(f"Turn: {turn_dir.title()} {bank_txt} | Runway: {runway_heading:.0f}° | Total: {max_time:.0f}s | Capture: {captured_txt}", style={"fontSize": "11px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
                # 3D Side View — vertical-altitude maneuver, same affordance
                # as engine-out. Pulls lat/lon from `path` and AGL altitude
                # from `hover`'s `alt` / `alt_agl` keys (per-step resolution,
                # so the climb's `alt_agl` and the glide's `alt` both
                # render); offsets by `airport_elev_ft` so the runway sits
                # at its real MSL height. Runway is drawn on the ground
                # plane so the pilot can see exactly where the turn-back
                # is landing relative to the strip.
                side_view_accordion_item(
                    build_3d_side_view_block(
                        path=path,
                        hover=hover,
                        elev_ft=airport_elev_ft,
                        runway=_runway_3d_dict_for_impossible_turn(
                            threshold_pt, runway_heading, runway_length_ft, airport_elev_ft
                        ) if (include_takeoff_climb and runway_length_ft and runway_heading is not None) else None,
                    )
                ),
            ], start_collapsed=False, style={"marginTop": "8px"})

            winds_chip = _winds_aloft_chip(wind_profile_data)
            if winds_chip is not None:
                info_content = html.Div([info_content, winds_chip])

            btn_class = (BTN_BASE + " shelf-action-success" if made_it
                          else BTN_BASE + " shelf-action-failure")
            return elements, bounds, status, result, hover_store, path, {"display": "block"}, int(max_time), slider_marks, 0, info_content, btn_class

        except Exception as e:
            log.error(f"EXCEPTION in draw_impossible_turn(): {e}")
            return [], None, f"Error: {str(e)}", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", BTN_BASE

    @app.callback(
        Output("scrubber-layer", "children", allow_duplicate=True),
        Input("impossibleturn-time-slider", "value"),
        State("impossibleturn-hover-store", "data"),
        State("impossibleturn-path-store", "data"),
        prevent_initial_call=True
    )
    def update_impossibleturn_scrubber(slider_value, hover_data, path_data):
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

        # Use 'phase' for impossible turn, fallback to 'segment'
        phase = pt.get('phase', pt.get('segment', 'turn'))
        slip_pct = pt.get('slip_pct', 0)

        tooltip_content = [
            html.Div(f"{phase.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', pt.get('alt_agl', 0)):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"TAS: {pt.get('tas', pt.get('ias', 0)):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', pt.get('bank', 0)) < 0 else ('R ' if pt.get('aob', pt.get('bank', 0)) > 0 else '')}{abs(pt.get('aob', pt.get('bank', 0))):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
            html.Div(f"Slip: {slip_pct:.0f}%", style={"color": "#fd7e14" if slip_pct > 0 else "#666", "fontWeight": "bold" if slip_pct > 0 else "normal"}),
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', pt.get('bank', 0))
        crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]
