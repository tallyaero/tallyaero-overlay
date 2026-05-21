"""Engine-Out Glide draw + scrubber callbacks.

Inputs: aircraft + environment + start point + touchdown point + reaction parameters.
Outputs: map layer with glide path, optional envelope ring, bounds,
info panel, min-altitude readout, scrubber state.
"""

from __future__ import annotations

import dash
from dash import html, dcc, Input, Output, State, no_update
from dash.exceptions import PreventUpdate
from geopy.point import Point as GeoPoint
from geopy.distance import distance as geo_distance
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.log import get_logger
from core.profile3d import make_3d_track_figure

from layouts.maneuvers._shared import _winds_aloft_chip
from utility import (
    find_minimum_altitude,
    compute_glide_envelope,
)
from simulation.eo_planner import simulate_engineout_planned

from callbacks.map import create_airplane_marker

from core.data_loader import aircraft_data, airport_data

log = get_logger(__name__)


def _safe_min_alt(s):
    """Parse the numeric min-alt out of 'Minimum Altitude Required: 1234 ft AGL'."""
    try:
        return float(s.split(":")[1].split("ft")[0].strip())
    except Exception:
        return float("inf")


def register(app):
    """Install Engine-Out callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output({"type": "click-status", "m_id": "engineout"}, "children", allow_duplicate=True),
        Output("engineout-hover-store", "data"),
        Output("engineout-path-store", "data"),
        Output("engineout-slider-container", "style"),
        Output("engineout-time-slider", "max"),
        Output("engineout-time-slider", "marks"),
        Output("engineout-time-slider", "value"),
        Output("engineout-info", "children"),
        Output("engineout-envelope-store", "data"),
        Output("engineout-min-alt-result", "children"),
        Output({"type": "sim-results-btn", "m_id": "engineout"}, "className", allow_duplicate=True),
        Input({"type": "draw-btn", "m_id": "engineout"}, "n_clicks"),
        State({"type": "point-store", "m_id": "engineout", "role": "start"}, "data"),
        State({"type": "point-store", "m_id": "engineout", "role": "touchdown"}, "data"),
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
        State("engineout-start-heading", "value"),
        State("engineout-altitude", "value"),
        State("engineout-flap-setting", "value"),
        State("engineout-prop-condition", "value"),
        State("engineout-runway-select", "value"),
        State("engineout-touchdown-heading", "value"),
        State("engineout-manual-elev", "value"),
        State("engineout-reaction-time", "value"),
        State("engineout-max-bank", "value"),
        State("engineout-speed-tau", "value"),
        State("engineout-bank-tau", "value"),
        State("engineout-show-envelope", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("wind-profile-store", "data"),
        prevent_initial_call=True,
    )
    def draw_engineout(
        n_clicks,
        start_data,
        touchdown_data,
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
        start_heading,
        start_alt_agl,
        flap_setting,
        prop_condition,
        runway_select,
        manual_touchdown_heading,
        manual_td_elev,
        reaction_time,
        max_bank,
        speed_tau,
        bank_tau,
        show_envelope,
        selected_airport_id,
        runtime_weight,
        wind_profile_data,
    ):
        if not n_clicks:
            raise PreventUpdate

        # 13 outputs: layer, bounds, status, hover_store, path_store, slider_style, max, marks, value, info, envelope, min_alt, results_btn_class
        BTN_BASE = "shelf-action shelf-action-results"
        empty_return = [], None, "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE

        # Failure paths: keep the user's existing markers + map view
        # in place (no_update for layer + bounds) so a half-set state
        # (e.g. start placed, touchdown missing) doesn't blank out
        # the user's work the moment they click Draw too early.
        if not start_data or not touchdown_data:
            return no_update, no_update, "Set start and touchdown points first.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE

        if not ac_name or not engine_key:
            return no_update, no_update, "Select aircraft and engine first.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE

        try:
            states = dash.callback_context.states

            def safe_float(key, default=None):
                val = states.get(key)
                if val in [None, "", "null"]:
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            start_heading      = safe_float("engineout-start-heading.value")
            start_alt_msl      = safe_float("engineout-altitude.value")
            manual_td_elev     = safe_float("engineout-manual-elev.value")
            wind_dir           = safe_float("env-wind-dir.value")
            wind_speed         = safe_float("env-wind-speed.value")
            oat_f              = safe_float("env-oat.value")
            altimeter          = safe_float("env-altimeter.value")
            reaction_time      = safe_float("engineout-reaction-time.value", 2.0)
            max_bank           = safe_float("engineout-max-bank.value", 45.0)
            speed_tau          = safe_float("engineout-speed-tau.value", 4.0)
            bank_tau           = safe_float("engineout-bank-tau.value", 1.5)

            total_wt = safe_float("runtime-total-weight-lb.data")
            if total_wt is None:
                total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None

            # Phase F — touchdown-heading input is the source of truth.
            # When an airport is selected, the value is interpreted as
            # magnetic (pilot convention) and converted to true for
            # geometry. With no airport selected we treat as true.
            selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
            airport_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

            heading_input = safe_float("engineout-touchdown-heading.value")
            if heading_input is None:
                return [], None, "Enter a touchdown heading.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE
            if selected_airport_id:
                from callbacks.aircraft import _airport_magvar, _mag_to_true
                touchdown_heading = _mag_to_true(heading_input, _airport_magvar(selected_airport))
            else:
                touchdown_heading = float(heading_input)

            required = [
                start_heading, start_alt_msl, touchdown_heading,
                wind_dir, wind_speed, oat_f, altimeter,
                total_wt
            ]
            if any(x is None for x in required):
                return [], None, "Missing or invalid input values.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE

            start = GeoPoint(start_data["lat"], start_data["lon"])
            touchdown = GeoPoint(touchdown_data["lat"], touchdown_data["lon"])

            ac = dict(aircraft_data[ac_name])
            ac["total_weight_lb"] = float(total_wt)

            td_store_elev = touchdown_data.get("elevation_ft") if isinstance(touchdown_data, dict) else None

            if manual_td_elev is not None:
                touchdown_elev_ft = float(manual_td_elev)
            elif td_store_elev is not None:
                touchdown_elev_ft = float(td_store_elev)
            else:
                touchdown_elev_ft = float(airport_elev_ft)

            # Start Alt input is MSL (altimeter reading); the sim
            # wants AGL energy above the touchdown field. Reject runs
            # where the pilot's typed MSL is below the field elevation
            # — that's not a glide, that's an impact.
            start_alt_agl = float(start_alt_msl) - float(touchdown_elev_ft)
            if start_alt_agl < 100:
                return ([], None,
                        f"Start altitude {start_alt_msl:.0f} ft MSL is "
                        f"below or too close to touchdown elevation "
                        f"{touchdown_elev_ft:.0f} ft MSL.",
                        [], [], {"display": "none"}, 100,
                        {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE)

            oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0

            # Phase H — hydrate the WindProfile from the dcc.Store if
            # the airport-pick callback fetched live winds aloft.
            wind_profile = None
            if wind_profile_data:
                try:
                    from core.winds_aloft import WindProfile
                    wind_profile = WindProfile.from_store(wind_profile_data)
                except Exception:
                    wind_profile = None

            path, hover_data, meta = simulate_engineout_planned(
                start_point=start,
                start_heading=float(start_heading),
                touchdown_point=touchdown,
                touchdown_heading=float(touchdown_heading),
                ac=ac,
                engine_option=engine_key,
                weight_lbs=float(total_wt),
                flap_config=flap_setting,
                prop_config=prop_condition,
                oat_c=float(oat_c),
                altimeter_inhg=float(altimeter),
                wind_dir=float(wind_dir),
                wind_speed=float(wind_speed),
                wind_profile=wind_profile,
                altitude_agl=float(start_alt_agl),
                touchdown_elev_ft=float(touchdown_elev_ft),
                max_bank_deg=float(max_bank),
                reaction_sec=float(reaction_time),
                speed_tau_sec=float(speed_tau),
                bank_tau_sec=float(bank_tau),
                timestep_sec=0.5,
            )

            if not path or not hover_data:
                return [], None, "No glide path generated. Check inputs.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE

            # Extract success/impact info from meta
            success = meta.get("success", False)
            impact_point = meta.get("impact_point")  # (lat, lon) or None
            turn_direction = meta.get("turn_direction", "auto")

            # ---------- Auto-calculate minimum altitude ----------
            min_alt_display = ""
            try:
                min_alt, _, _, _ = find_minimum_altitude(
                    start_point=start,
                    start_heading=float(start_heading),
                    touchdown_point=touchdown,
                    touchdown_heading=float(touchdown_heading),
                    ac=ac,
                    engine_option=engine_key,
                    weight_lbs=float(total_wt),
                    flap_config=flap_setting or "clean",
                    prop_config=prop_condition or "windmilling",
                    oat_c=oat_c,
                    altimeter_inhg=float(altimeter),
                    wind_dir=float(wind_dir),
                    wind_speed=float(wind_speed),
                    touchdown_elev_ft=touchdown_elev_ft,
                    max_bank_deg=float(max_bank),
                    reaction_sec=float(reaction_time),
                    alt_low=100.0,
                    alt_high=5000.0,
                    resolution=25.0,
                )
                min_alt_display = f"Minimum Altitude Required: {min_alt:.0f} ft AGL"
            except Exception as min_err:
                log.warning(f"Min altitude calc error: {min_err}")
                min_alt_display = "Could not calculate minimum altitude"

            # ---------- Core visuals: full glide track, phase-colored ----------
            # Split the path into per-phase polylines so the pattern legs
            # (entry/downwind/base/final) are visually distinct on the map.
            _PHASE_PALETTE = {
                "engine_failure": "#dc2626",
                "entry":          "#0d59f2",
                "to_abeam":       "#0d59f2",
                "downwind":       "#1d4ed8",
                "base_turn":      "#0891b2",
                "base":           "#0891b2",
                "final_turn":     "#15803d",
                "final":          "#15803d",
                "po180":          "#0891b2",
                "straight_in":    "#0d59f2",
                "spiral":         "#a855f7",
                "transit":        "#475569",
            }
            arc_lines = []
            if path and hover_data:
                n = min(len(path), len(hover_data))
                i = 0
                while i < n:
                    phase = hover_data[i].get("phase", "transit")
                    j = i + 1
                    while j < n and hover_data[j].get("phase", "transit") == phase:
                        j += 1
                    # Include the next point so segments visually connect.
                    end = min(j + 1, n)
                    color = _PHASE_PALETTE.get(phase, "#0d59f2")
                    arc_lines.append(dl.Polyline(
                        positions=path[i:end], color=color,
                        weight=4, opacity=0.85,
                        children=dl.Tooltip(
                            phase.replace("_", " ").title())))
                    i = j

            # Start (engine failure) — green-500
            start_marker = dl.CircleMarker(
                center=[start.latitude, start.longitude],
                radius=7,
                color="#22c55e",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip("Engine Failure Point"),
            )
            # Touchdown — green for a successful landing, red for not.
            # Red-dot-as-target made the result ambiguous: even when
            # the aircraft actually landed on the runway, the marker
            # still looked like a failure indicator.
            td_color = "#22c55e" if success else "#ef4444"
            td_tooltip = ("Touchdown" if success
                            else "Target Touchdown (missed)")
            touchdown_marker = dl.CircleMarker(
                center=[touchdown.latitude, touchdown.longitude],
                radius=7,
                color=td_color,
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip(td_tooltip),
            )

            elements = [start_marker, touchdown_marker, *arc_lines]

            # Glide envelope is now rendered into its own envelope-layer
            # by `render_glide_ring` (below), driven by the Glide Ring
            # toggle and updated reactively as the user changes the
            # start point / altitude / wind / aircraft. Keep an empty
            # `envelope_data` here so the rest of this callback (bounds,
            # envelope-store output) continues to work.
            envelope_data: list = []
            if False:  # legacy fallback removed — see render_glide_ring
                if envelope_data:
                    envelope_polygon = dl.Polygon(
                        positions=envelope_data,
                        color="#84cc16",
                        weight=1,
                        opacity=0.85,
                        dashArray="4,4",
                        fillColor="#84cc16",
                        fillOpacity=0.15,
                        children=dl.Tooltip("Max glide distance ring"),
                    )

            # Impact vs success messaging / marker
            if impact_point and isinstance(impact_point, (list, tuple)):
                impact_lat, impact_lon = impact_point[0], impact_point[1]
                impact_mark = dl.CircleMarker(
                    center=[impact_lat, impact_lon],
                    radius=7,
                    color="#dc2626",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip("Impact Point"),
                )
                elements.append(impact_mark)
                failure_reason = meta.get("reason", "ground_impact")
                msg = f"{failure_reason.replace('_', ' ').title()} at ({impact_lat:.4f}, {impact_lon:.4f})"
            else:
                msg = "Engine-out glide successful."

            # ---------- Bounds ----------
            lats = [pt[0] for pt in path] + [start.latitude, touchdown.latitude]
            lons = [pt[1] for pt in path] + [start.longitude, touchdown.longitude]
            if impact_point and isinstance(impact_point, (list, tuple)):
                lats.append(impact_point[0])
                lons.append(impact_point[1])
            if envelope_data:
                lats.extend([pt[0] for pt in envelope_data])
                lons.extend([pt[1] for pt in envelope_data])

            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

            # Build slider marks based on time
            max_time = hover_data[-1].get("time", 100) if hover_data else 100
            # Build phase-labeled marks: a tick at the start of each unique
            # phase + endpoints.
            _PHASE_LABELS = {
                "engine_failure": "EF",
                "entry": "Entry",
                "transit": "Transit",
                "to_abeam": "Abeam",
                "downwind": "Downwd",
                "base_turn": "Base T",
                "base": "Base",
                "final_turn": "Fin T",
                "final": "Final",
                "po180": "PO180",
                "straight_in": "Strt-in",
                "spiral": "Spiral",
                "to_high_key": "High K",
                "to_low_key": "Low K",
            }
            slider_marks = {0: "Start", int(max_time): "End"}
            if hover_data:
                seen_phase = None
                for h in hover_data:
                    ph = h.get("phase", "")
                    if ph and ph != seen_phase:
                        t = int(round(h.get("time", 0)))
                        if 1 <= t < int(max_time):
                            slider_marks[t] = {
                                "label": _PHASE_LABELS.get(ph, ph),
                                "style": {"fontSize": "9px",
                                            "color": "#475569",
                                            "transform": "rotate(-30deg)",
                                            "transformOrigin": "0 50%",
                                            "whiteSpace": "nowrap"},
                            }
                        seen_phase = ph

            # Prepare hover data for store (ensure JSON-serializable)
            hover_store = [
                {
                    "time": pt.get("time", 0),
                    "phase": pt.get("phase", "glide"),
                    "bucket": pt.get("bucket", ""),
                    "alt": pt.get("alt", 0),
                    "ias": pt.get("ias", 0),
                    "tas": pt.get("tas", 0),
                    "gs": pt.get("gs", pt.get("tas", 0)),
                    "aob": pt.get("aob", 0),
                    "vs": pt.get("vs", 0),
                    "track": pt.get("track", 0),
                    "heading": pt.get("heading", 0),
                    "drift": pt.get("drift", 0),
                    "glide_ratio": pt.get("glide_ratio", 0),
                    "load_factor": pt.get("load_factor", 1),
                    "stall_margin_kt": pt.get("stall_margin_kt", 0),
                    "slipping": pt.get("slipping", False),
                    "slip_pct": pt.get("slip_pct", 0),
                    # Debug fields for abeam bucket capture diagnostics
                    "dist_to_abeam": pt.get("dist_to_abeam", 0),
                    "xtrack_abeam": pt.get("xtrack_abeam", 0),
                    "along_abeam": pt.get("along_abeam", 0),
                    "in_xtrack": pt.get("in_xtrack", ""),
                    "in_along": pt.get("in_along", ""),
                    "in_alt": pt.get("in_alt", ""),
                    "in_hdg": pt.get("in_hdg", ""),
                    "alt_range": pt.get("alt_range", ""),
                    "abeam_bucket": pt.get("abeam_bucket", ""),
                    "bucket_idx": pt.get("bucket_idx", 0),
                    "bucket_chain": pt.get("bucket_chain", ""),
                    "pattern_side": pt.get("pattern_side", ""),
                    "trans_bucket": pt.get("trans_bucket", ""),
                    "trans_alt": pt.get("trans_alt", ""),
                    "trans_check": pt.get("trans_check", ""),
                    # Spiral debug fields
                    "spiral_n": pt.get("spiral_n", 0),
                    "spiral_r": pt.get("spiral_r", 0),
                    "spiral_alt_lose": pt.get("spiral_alt_lose", 0),
                }
                for pt in hover_data
            ]

            # Calculate glide metrics
            total_distance_nm = geo_distance(start, touchdown).nm if start and touchdown else 0
            avg_vs = 0
            avg_gs = 0
            avg_gr = 0
            if hover_data and len(hover_data) > 0:
                vs_values = [abs(pt.get('vs', 0)) for pt in hover_data if pt.get('vs') is not None]
                gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover_data if pt.get('gs') is not None]
                gr_values = [pt.get('glide_ratio', 0) for pt in hover_data if pt.get('glide_ratio')]
                avg_vs = sum(vs_values) / len(vs_values) if vs_values else 0
                avg_gs = sum(gs_values) / len(gs_values) if gs_values else 0
                avg_gr = sum(gr_values) / len(gr_values) if gr_values else 0

            # Extract phase information for display
            phases_seen = []
            if hover_data:
                current_phase = None
                for h in hover_data:
                    phase = h.get("phase", "unknown")
                    if phase != current_phase:
                        phases_seen.append(phase)
                        current_phase = phase

            phase_display = " → ".join(phases_seen) if phases_seen else "N/A"

            # Check for slip usage
            slip_used = any(h.get("slipping", False) for h in hover_data) if hover_data else False

            # Build info content with enhanced data
            status_color = "#28a745" if success else "#dc3545"
            status_text = "TOUCHDOWN" if success else "IMPACT"

            min_alt_color = (
                "#28a745" if (isinstance(min_alt_display, str)
                              and start_alt_agl is not None
                              and "ft AGL" in min_alt_display
                              and start_alt_agl >= _safe_min_alt(min_alt_display))
                else "#dc3545")
            min_alt_row = html.Div(
                min_alt_display,
                style={
                    "fontSize": "11px",
                    "fontWeight": "600",
                    "color": min_alt_color,
                    "marginBottom": "8px",
                },
            ) if min_alt_display else None

            # Build the 3D side-view figure (Phase 5AH). Pull lat/lon
            # from path + altitude/phase from the aligned hover_data
            # so the rendered track is exactly what got drawn on the
            # map, just with the vertical dimension restored.
            try:
                lat3d = [p[0] for p in path]
                lon3d = [p[1] for p in path]
                # hover_data carries AGL ft; convert to MSL by adding
                # the touchdown elevation so the runway sits at its
                # real height.
                # touchdown is a geopy.Point — has no __len__ but
                # supports tuple-style indexing (0=lat, 1=lon, 2=alt).
                try:
                    td_elev = float(touchdown[2]) if touchdown else 0.0
                except (IndexError, TypeError):
                    td_elev = 0.0
                alts3d = [(h.get("alt") or 0.0) + td_elev for h in hover_data]
                phases3d = [h.get("phase") or "" for h in hover_data]
                # Length-align the per-step arrays to path length.
                n3d = min(len(lat3d), len(alts3d), len(phases3d))
                lat3d, lon3d = lat3d[:n3d], lon3d[:n3d]
                alts3d, phases3d = alts3d[:n3d], phases3d[:n3d]
                runway_ref = None
                if touchdown is not None and len(path) >= 1:
                    # Render a 3,000-ft centerline through the touchdown
                    # point on the touchdown heading so the pilot has a
                    # ground reference.
                    from geopy.point import Point as _GP
                    from geopy.distance import distance as _gd
                    td_lat, td_lon = touchdown[0], touchdown[1]
                    ahead = _gd(feet=1500).destination(
                        _GP(td_lat, td_lon), touchdown_heading)
                    behind = _gd(feet=1500).destination(
                        _GP(td_lat, td_lon), (touchdown_heading + 180) % 360)
                    runway_ref = {
                        "start_lat": behind.latitude,
                        "start_lon": behind.longitude,
                        "end_lat": ahead.latitude,
                        "end_lon": ahead.longitude,
                        "elev_ft": td_elev,
                    }
                fig3d = make_3d_track_figure(
                    path_lat=lat3d, path_lon=lon3d, alts_ft=alts3d,
                    phases=phases3d, runway=runway_ref,
                    height=380,
                )
                profile3d_graph = dcc.Graph(
                    figure=fig3d,
                    config={"displayModeBar": False},
                    style={"width": "100%"},
                )
            except Exception as _e3:
                log.warning("3D side-view failed to build: %s", _e3)
                profile3d_graph = html.Div(
                    "3D side view unavailable for this run.",
                    style={"fontSize": "11px", "color": "#94a3b8",
                            "padding": "12px"})

            # Structured plan diagnostics — populated by the new backward-
            # construction planner via `simulate_engineout_planned`. Falls
            # back to {} so the accordion still renders if a legacy path is
            # ever wired in.
            diag = meta.get("diagnostics", {}) or {}
            plan_rows: list = []
            if diag:
                strategy = (diag.get("approach_strategy") or "").replace("_", " ").title()
                pattern = (diag.get("pattern_side") or "").title()
                plan_rows.append(html.Div([html.Strong("Plan")],
                                            style={"marginBottom": "4px"}))
                plan_rows.append(html.Div(
                    f"Strategy: {strategy} | Pattern: {pattern} | "
                    f"On final side: {'Yes' if diag.get('on_final_side') else 'No'}",
                    style={"fontSize": "11px"}))
                if diag.get("spiral_turns", 0) > 0:
                    plan_rows.append(html.Div(
                        f"Overhead spiral: {diag['spiral_turns']:.2f} turns @ "
                        f"{diag['spiral_bank_deg']:.0f}° bank",
                        style={"fontSize": "11px"}))
                plan_rows.append(html.Hr(style={"margin": "5px 0",
                                                  "borderTop": "1px solid #ddd"}))

                plan_rows.append(html.Div([html.Strong("Energy budget")],
                                            style={"marginBottom": "4px"}))
                plan_rows.append(html.Div(
                    f"Start: {diag.get('start_alt_agl_ft', 0):.0f} ft AGL — "
                    f"Direct cost: {diag.get('direct_glide_alt_ft', 0):.0f} ft — "
                    f"Arrival over field: {diag.get('arrival_alt_agl_ft', 0):.0f} ft AGL",
                    style={"fontSize": "11px"}))
                excess_hk = diag.get("excess_at_high_key_ft", 0)
                excess_lk = diag.get("excess_at_low_key_ft", 0)
                hk_color = "#22c55e" if excess_hk >= 0 else "#dc2626"
                lk_color = "#22c55e" if excess_lk >= 0 else "#dc2626"
                plan_rows.append(html.Div([
                    html.Span(
                        f"Excess at High Key (1500 AGL): {excess_hk:+.0f} ft",
                        style={"color": hk_color, "marginRight": "12px"}),
                    html.Span(
                        f"Low Key (1000 AGL): {excess_lk:+.0f} ft",
                        style={"color": lk_color}),
                ], style={"fontSize": "11px"}))
                plan_rows.append(html.Hr(style={"margin": "5px 0",
                                                  "borderTop": "1px solid #ddd"}))

                plan_rows.append(html.Div([html.Strong("What would need to be true")],
                                            style={"marginBottom": "4px"}))
                plan_rows.append(html.Div(
                    f"Minimum start altitude: ~{diag.get('required_alt_agl_to_make_it_ft', 0):.0f} ft AGL",
                    style={"fontSize": "11px"}))
                plan_rows.append(html.Div(
                    f"Maximum direct distance at current altitude: "
                    f"~{diag.get('required_max_dist_nm', 0):.2f} nm",
                    style={"fontSize": "11px"}))
                plan_rows.append(html.Div(
                    f"Planning bank: {diag.get('planning_bank_deg', 0):.0f}° "
                    f"(max {diag.get('max_bank_deg', 0):.0f}°) | "
                    f"Turn radius: {diag.get('turn_radius_ft', 0):.0f} ft",
                    style={"fontSize": "11px"}))
                if diag.get("final_wind_component_kt", 0) != 0:
                    fwc = diag["final_wind_component_kt"]
                    plan_rows.append(html.Div(
                        f"Final wind component: "
                        f"{abs(fwc):.0f} kt {'headwind' if fwc >= 0 else 'tailwind'}",
                        style={"fontSize": "11px"}))
                if not diag.get("feasible", True) and diag.get("failure_reason"):
                    plan_rows.append(html.Hr(style={"margin": "5px 0",
                                                      "borderTop": "1px solid #ddd"}))
                    plan_rows.append(html.Div(
                        f"Reason: {diag['failure_reason']}",
                        style={"fontSize": "11px", "color": "#dc2626",
                                "fontWeight": "600"}))

            info_content = dbc.Accordion([
                dbc.AccordionItem([
                    html.Div(status_text, style={"fontWeight": "bold", "color": status_color, "marginBottom": "8px", "fontSize": "13px"}),

                    *([min_alt_row] if min_alt_row else []),

                    html.Div([html.Strong("Flight Phases")], style={"marginBottom": "4px"}),
                    html.Div(phase_display, style={"fontSize": "10px", "color": "#555", "marginBottom": "8px", "wordWrap": "break-word"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    html.Div([html.Strong("Aircraft & Environment")], style={"marginBottom": "4px"}),
                    html.Div(f"Weight: {total_wt:.0f} lb | Entry hdg: {start_heading:.0f}°", style={"fontSize": "11px"}),
                    html.Div(f"Wind: {wind_dir:.0f}° at {wind_speed:.0f} kt | Flaps: {flap_setting or 'clean'}", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    html.Div([html.Strong("Glide Performance")], style={"marginBottom": "4px"}),
                    html.Div(f"Avg G/R: {avg_gr:.1f}:1 | GS: {avg_gs:.0f} kt | VS: {avg_vs:.0f} fpm", style={"fontSize": "11px"}),
                    html.Div(f"Distance: {total_distance_nm:.2f} nm | Start alt: {start_alt_msl:.0f} ft MSL ({start_alt_agl:.0f} ft AGL)", style={"fontSize": "11px"}),
                    html.Div(f"Slip used: {'Yes' if slip_used else 'No'}", style={"fontSize": "11px", "color": "#fd7e14" if slip_used else "#666"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    html.Div([html.Strong("Approach & Timing")], style={"marginBottom": "4px"}),
                    html.Div(f"Turn direction: {turn_direction} | Runway: {touchdown_heading:.0f}°", style={"fontSize": "11px"}),
                    html.Div(f"Total time: {max_time:.1f}s | Reaction: {reaction_time:.1f}s", style={"fontSize": "11px"}),
                    html.Div(f"Max bank: {max_bank:.0f}° | Bank τ: {bank_tau:.1f}s", style={"fontSize": "11px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
                *([dbc.AccordionItem(plan_rows, title="Glide Plan",
                                       style={"fontSize": "12px"})]
                  if plan_rows else []),
                dbc.AccordionItem([
                    html.Div("Drag to rotate. Scroll to zoom. "
                              "Vertical axis is exaggerated for readability.",
                              style={"fontSize": "10px", "color": "#94a3b8",
                                       "marginBottom": "4px"}),
                    profile3d_graph,
                ], title="3D Side View", style={"fontSize": "12px"}),
            ], start_collapsed=False, style={"marginTop": "8px"})

            winds_chip = _winds_aloft_chip(wind_profile_data)
            if winds_chip is not None:
                info_content = html.Div([info_content, winds_chip])

            btn_class = (BTN_BASE + " shelf-action-success" if success
                          else BTN_BASE + " shelf-action-failure")
            return elements, bounds, msg, hover_store, path, {"display": "block"}, int(max_time), slider_marks, 0, info_content, envelope_data, min_alt_display, btn_class

        except Exception as e:
            import traceback
            log.error(f"EXCEPTION in draw_engineout(): {e}")
            traceback.print_exc()
            return [], None, f"Error generating path: {str(e)}", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], "", BTN_BASE

    @app.callback(
        Output("scrubber-layer", "children", allow_duplicate=True),
        Input("engineout-time-slider", "value"),
        State("engineout-hover-store", "data"),
        State("engineout-path-store", "data"),
        prevent_initial_call=True
    )
    def update_engineout_scrubber(slider_value, hover_data, path_data):
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

        phase = pt.get('phase', 'glide')
        slip_pct = pt.get('slip_pct', 0)
        bucket = pt.get('bucket', '')

        tooltip_content = [
            html.Div(f"{phase.replace('_', ' ').title()}" + (f" → {bucket}" if bucket else ""), style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"TAS: {pt.get('tas', 0):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
            html.Div(f"Slip: {slip_pct:.0f}%", style={"color": "#fd7e14" if slip_pct > 0 else "#666", "fontWeight": "bold" if slip_pct > 0 else "normal"}),
        ]

        # Add debug info for ABEAM bucket capture
        if pt.get('dist_to_abeam', 0) > 0 or pt.get('bucket_chain', ''):
            tooltip_content.append(html.Div("─── Bucket Debug ───", style={"borderTop": "1px solid #ccc", "marginTop": "3px", "paddingTop": "3px", "fontSize": "10px"}))
            tooltip_content.append(html.Div(f"Chain: {pt.get('bucket_chain', '')}"))
            tooltip_content.append(html.Div(f"Idx: {pt.get('bucket_idx', 0)} | Side: {pt.get('pattern_side', '')}"))
            abeam_bkt = pt.get('abeam_bucket', '')
            if abeam_bkt:
                tooltip_content.append(html.Div(f"{abeam_bkt}", style={"fontSize": "9px"}))
            if pt.get('dist_to_abeam', 0) > 0:
                tooltip_content.append(html.Div(f"Dist to ABEAM: {pt.get('dist_to_abeam', 0):.0f} ft"))
                tooltip_content.append(html.Div(f"Xtrack: {pt.get('xtrack_abeam', 0):.0f} | Along: {pt.get('along_abeam', 0):.0f}"))
                in_x = pt.get('in_xtrack', '')
                in_a = pt.get('in_along', '')
                in_alt = pt.get('in_alt', '')
                in_hdg = pt.get('in_hdg', '')
                tooltip_content.append(html.Div(f"X:{in_x} | A:{in_a} | Alt:{in_alt}"))
                if in_hdg:
                    tooltip_content.append(html.Div(f"Hdg:{in_hdg}"))
                alt_range = pt.get('alt_range', '')
                if alt_range:
                    tooltip_content.append(html.Div(f"ABEAM alt: {alt_range} ft"))
            # Show what the transition code is ACTUALLY checking
            trans_bucket = pt.get('trans_bucket', '')
            if trans_bucket:
                tooltip_content.append(html.Div("─── Transition Check ───", style={"borderTop": "1px solid #f00", "marginTop": "3px", "paddingTop": "3px", "fontSize": "10px", "color": "#f00"}))
                tooltip_content.append(html.Div(f"Checking: {trans_bucket} ({pt.get('trans_alt', '')} ft)"))
                tooltip_content.append(html.Div(f"Result: {pt.get('trans_check', '')}"))
            # Spiral planning info (during spiral phase)
            spiral_n = pt.get('spiral_n', 0)
            if spiral_n > 0:
                tooltip_content.append(html.Div("─── Spiral Plan ───", style={"borderTop": "1px solid #06c", "marginTop": "3px", "paddingTop": "3px", "fontSize": "10px", "color": "#06c"}))
                tooltip_content.append(html.Div(f"Spirals: {spiral_n} | Radius: {pt.get('spiral_r', 0):.0f} ft"))
                tooltip_content.append(html.Div(f"Alt to lose: {pt.get('spiral_alt_lose', 0):.0f} ft"))

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]

    # ------------------------------------------------------------------
    # Mirror callbacks — copy the engine-out form fields into globally-
    # mounted Stores so the glide-ring callback can State them. The
    # form components only exist in the DOM while engine-out is the
    # active maneuver, so we can't State them directly without
    # crashing callback dispatch when other maneuvers are mounted.
    # ------------------------------------------------------------------
    @app.callback(
        Output("engineout-altitude-mirror", "data"),
        Input("engineout-altitude", "value"),
        prevent_initial_call=True,
    )
    def _mirror_engineout_altitude(value):
        try:
            return float(value) if value not in (None, "") else 5000.0
        except (TypeError, ValueError):
            return 5000.0

    @app.callback(
        Output("engineout-flap-mirror", "data"),
        Input("engineout-flap-setting", "value"),
        prevent_initial_call=True,
    )
    def _mirror_engineout_flap(value):
        return value or "clean"

    @app.callback(
        Output("engineout-prop-mirror", "data"),
        Input("engineout-prop-condition", "value"),
        prevent_initial_call=True,
    )
    def _mirror_engineout_prop(value):
        return value or "idle"

    @app.callback(
        Output("engineout-td-elev-mirror", "data"),
        Input("engineout-manual-elev", "value"),
        prevent_initial_call=True,
    )
    def _mirror_engineout_td_elev(value):
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Phase I2 — Glide Ring toggle auto-draw + wind-aloft awareness.
    # ------------------------------------------------------------------
    # Reads the engine-out form fields via the mirror stores above,
    # which ARE always mounted in the DOM (layouts/desktop.py). That
    # way the ring re-renders whenever altitude/flap/prop/td-elev
    # change AND doesn't crash callback dispatch when a non-engineout
    # maneuver is the currently mounted one.
    @app.callback(
        Output("envelope-layer", "children", allow_duplicate=True),
        Input("engineout-show-envelope", "value"),
        Input({"type": "point-store", "m_id": "engineout", "role": "start"}, "data"),
        Input("aircraft-select", "value"),
        Input("engine-select", "value"),
        Input("env-wind-dir", "value"),
        Input("env-wind-speed", "value"),
        Input("wind-profile-store", "data"),
        Input("env-oat", "value"),
        Input("env-altimeter", "value"),
        Input("maneuver-select", "value"),
        Input("engineout-altitude-mirror", "data"),
        Input("engineout-flap-mirror", "data"),
        Input("engineout-prop-mirror", "data"),
        Input("engineout-td-elev-mirror", "data"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True,
    )
    def render_glide_ring(show_envelope, start_data,
                           ac_name, engine_key, wind_dir, wind_speed,
                           wind_profile_data, oat_f, altimeter,
                           maneuver,
                           start_alt_msl_in, flap_setting_in,
                           prop_condition_in, manual_td_elev_in,
                           airport_id):
        # Coerce the mirror values (with fallbacks if they're still
        # at default).
        try:
            start_alt_msl = (float(start_alt_msl_in)
                             if start_alt_msl_in not in (None, "") else 5000.0)
        except (TypeError, ValueError):
            start_alt_msl = 5000.0
        flap_setting = flap_setting_in or "clean"
        prop_condition = prop_condition_in or "idle"
        try:
            manual_td_elev_ring = (float(manual_td_elev_in)
                                   if manual_td_elev_in not in (None, "")
                                   else None)
        except (TypeError, ValueError):
            manual_td_elev_ring = None
        # Hide the ring outside engine-out so it doesn't bleed into
        # the other maneuver tabs.
        if maneuver != "engineout":
            return []
        if not show_envelope or "show" not in show_envelope:
            log.info("Glide Ring: toggle off")
            return []
        if not start_data or not isinstance(start_data, dict):
            log.info("Glide Ring: no start point set")
            return []
        if not ac_name or ac_name not in aircraft_data:
            log.info(f"Glide Ring: aircraft not selected (got {ac_name!r})")
            return []
        if not engine_key:
            log.info("Glide Ring: engine not selected")
            return []

        # Convert MSL → AGL using the touchdown field elevation. Pick
        # order matches the Draw flow: manual override > selected
        # airport > 0 (ring at MSL).
        try:
            start_alt_msl_val = float(start_alt_msl) if start_alt_msl else 0.0
        except (TypeError, ValueError):
            log.info(f"Glide Ring: bad altitude {start_alt_msl!r}")
            return []
        ring_field_elev = 0.0
        if manual_td_elev_ring is not None:
            ring_field_elev = float(manual_td_elev_ring)
        elif airport_id:
            _ap = next((a for a in airport_data if a.get("id") == airport_id), None)
            if _ap:
                ring_field_elev = float(_ap.get("elevation_ft", 0.0))
        start_alt = start_alt_msl_val - ring_field_elev
        if start_alt <= 0:
            log.info(f"Glide Ring: MSL {start_alt_msl_val} below field "
                     f"elev {ring_field_elev} → no glide possible")
            return []

        try:
            wd = float(wind_dir) if wind_dir not in (None, "") else 0.0
            ws = float(wind_speed) if wind_speed not in (None, "") else 0.0
        except (TypeError, ValueError):
            wd, ws = 0.0, 0.0

        # Aircraft glide ratio + best-glide TAS pulled from the same
        # _get_best_glide_and_ratio helper the sim uses, so the ring
        # reflects the actual aircraft's POH-derived performance.
        try:
            from simulation.engine_out import _get_best_glide_and_ratio
            from physics.atmosphere import compute_pressure_altitude, compute_air_density
            from physics.aerodynamics import compute_true_airspeed
            from simulation.engine_out import adjust_glide_ratio_for_density
            ac = aircraft_data[ac_name]
            best_glide_kias, straight_gr = _get_best_glide_and_ratio(
                ac, engine_key, flap_setting or "clean",
                prop_condition or "idle",
            )
        except Exception as e:
            log.warning(f"Glide Ring: best-glide lookup failed: {e}")
            return []

        # Honor live env so the ring matches the sim's altitude perf.
        try:
            oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0 if oat_f not in (None, "") else 15.0
            altim = float(altimeter) if altimeter not in (None, "") else 29.92
        except (TypeError, ValueError):
            oat_c, altim = 15.0, 29.92

        # Field elev for atmospheric calcs + wind-profile MSL lookup.
        # Uses the same elevation we just used to convert MSL → AGL above
        # so the energy budget and the air-density calc agree.
        elev_ft = ring_field_elev

        try:
            # Density-adjusted glide ratio mirrors what the engine_out
            # sim does — important so the ring matches the sim's
            # reachable area at altitude.
            pa = compute_pressure_altitude(elev_ft + start_alt, altim)
            rho = compute_air_density(pa, oat_c)
            gr_adj = adjust_glide_ratio_for_density(straight_gr, rho)
            gr_adj = max(3.0, min(gr_adj, 25.0))
            tas_kt = compute_true_airspeed(best_glide_kias, pa, oat_c)
        except Exception:
            gr_adj = straight_gr
            tas_kt = best_glide_kias

        # Hydrate the WindProfile if the airport pick fetched it.
        wind_profile = None
        if wind_profile_data:
            try:
                from core.winds_aloft import WindProfile
                wind_profile = WindProfile.from_store(wind_profile_data)
            except Exception:
                wind_profile = None

        # Terrain-clip the ring like the Route Planner's corridor —
        # the reachable area shrinks toward terrain that rises faster
        # than the aircraft descends. Lazy-imported so engineout still
        # boots when the terrain layer can't be hydrated.
        try:
            from core.terrain import elevation_m as _terrain_elev_m
        except Exception:
            _terrain_elev_m = None

        try:
            envelope = compute_glide_envelope(
                start_point=GeoPoint(start_data["lat"], start_data["lon"]),
                altitude_ft=start_alt,
                glide_ratio=gr_adj,
                wind_dir=wd,
                wind_speed=ws,
                tas_knots=tas_kt,
                num_points=48,  # smoother polygon than the sim default 36
                wind_profile=wind_profile,
                start_elev_ft=elev_ft,
                elevation_fn=_terrain_elev_m,
            )
        except Exception as e:
            log.warning(f"Glide ring compute failed: {e}")
            return []

        if not envelope:
            log.info("Glide Ring: compute returned empty envelope")
            return []

        log.info(f"Glide Ring: drawing {len(envelope)}-pt polygon, alt={start_alt:.0f}, GR={gr_adj:.1f}, TAS={tas_kt:.0f}")
        tooltip = ("Max-glide reach (live winds aloft)" if wind_profile
                   else "Max-glide reach (surface wind only)")
        polygon = dl.Polygon(
            positions=envelope,
            color="#84cc16",
            weight=1,
            opacity=0.85,
            dashArray="4,4",
            fillColor="#84cc16",
            fillOpacity=0.15,
            children=dl.Tooltip(tooltip),
        )
        return [polygon]
