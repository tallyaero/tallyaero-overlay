"""Steep turn draw + scrubber callbacks.

Inputs: aircraft + environment + entry heading + bank angle + sequence.
Outputs: map layer with path, bounds, info panel, time-scrubber state.
"""

from __future__ import annotations

import math

from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from utility import simulate_steep_turn

from callbacks.map import create_airplane_marker
from layouts.maneuvers._shared import _acs_metric, _power_verdict, _winds_aloft_chip

from core.data_loader import aircraft_data, airport_data


def register(app):
    """Install Steep Turn callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("steepturn-hover-store", "data"),
        Output("steepturn-path-store", "data"),
        Output("steepturn-slider-container", "style"),
        Output("steepturn-time-slider", "max"),
        Output("steepturn-time-slider", "marks"),
        Output("steepturn-time-slider", "value"),
        Output("steepturn-info", "children"),
        Input({"type": "draw-btn", "m_id": "steep_turn"}, "n_clicks"),
        State({"type": "point-store", "m_id": "steep_turn", "role": "start"}, "data"),
        State("steepturn-bank-angle", "value"),
        State("steepturn-sequence", "value"),
        State("steepturn-entry-heading", "value"),
        State("steepturn-altitude", "value"),
        State("steepturn-ias", "value"),
        State("total-weight-display", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("runtime-total-weight-lb", "data"),
        State("selected-airport-id", "data"),
        State("power-setting", "value"),
        State("wind-profile-store", "data"),
        prevent_initial_call=True
    )
    def draw_steep_turn(
        n_clicks,
        start,
        bank_angle,
        sequence,
        entry_heading,
        entry_alt_ft,
        entry_ias,
        weight_str,
        oat_f,
        altimeter_inhg,
        wind_dir,
        wind_speed,
        aircraft_name,
        engine_name,
        runtime_weight,
        selected_airport_id,
        power_setting,
        wind_profile_data,
    ):
        if not n_clicks or not start or not aircraft_name or not engine_name:
            raise PreventUpdate

        ac = aircraft_data[aircraft_name]

        # Use Va as default entry IAS if user left blank
        if int(ac.get("engine_count", 1)) > 1:
            va = float((ac.get("multi_engine_limits", {}) or {}).get("va", 100))
        else:
            va = float((ac.get("single_engine_limits", {}) or {}).get("va", 100))
        entry_ias = float(entry_ias) if entry_ias not in [None, "", "null"] else float(va)

        # Runtime weight should be authoritative. Fallback to parsing the display box.
        weight_lbs = None
        try:
            if runtime_weight not in [None, "", "null"]:
                weight_lbs = float(runtime_weight)
        except Exception:
            weight_lbs = None

        if weight_lbs is None:
            try:
                # total-weight-display is already just a number string in your UI ("1523"), so parse directly.
                weight_lbs = float(str(weight_str).replace(",", "").strip())
            except Exception:
                weight_lbs = float(ac.get("empty_weight", 1200.0)) + 180.0

        altitude_ft = float(entry_alt_ft) if entry_alt_ft not in [None, "", "null"] else float(ac.get("default_altitude", 1000.0))

        oat_c = None
        try:
            oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0
        except Exception:
            oat_c = (52.0 - 32.0) * 5.0 / 9.0

        # Pass runtime weight through the aircraft dict so any helper in utility.py can use it
        ac_rt = dict(ac)
        ac_rt["total_weight_lb"] = float(weight_lbs)

        # Get airport elevation for TAS calculation
        selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
        field_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

        # Parse altimeter setting
        altimeter_val = float(altimeter_inhg) if altimeter_inhg not in [None, "", "null"] else 29.92

        # Design Directive — pipe global Power % through to the sim.
        # Default = design power 0.70 if slider returns no value.
        try:
            power_pct = float(power_setting) if power_setting not in [None, "", "null"] else 0.70
        except (TypeError, ValueError):
            power_pct = 0.70

        # Hydrate live winds-aloft column if airport-pick fetched one.
        wind_profile = None
        if wind_profile_data:
            try:
                from core.winds_aloft import WindProfile
                wind_profile = WindProfile.from_store(wind_profile_data)
            except Exception:
                wind_profile = None

        path, hover = simulate_steep_turn(
            entry_point={"lat": start["lat"], "lon": start["lon"]},
            entry_heading_deg=float(entry_heading),
            altitude_ft=float(altitude_ft),
            bank_angle_deg=float(bank_angle),
            turn_sequence=sequence,
            ias_knots=float(entry_ias),
            wind_dir_deg=float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0,
            wind_speed_kt=float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0,
            oat_c=float(oat_c),
            altimeter_inhg=float(altimeter_val),
            field_elev_ft=float(field_elev_ft),
            power_setting=power_pct,
            # Post-2026-05-21 audit additions
            ac=ac_rt,
            weight_lbs=float(weight_lbs),
            engine_option=engine_name,
            wind_profile=wind_profile,
        )

        if not path or not hover:
            raise PreventUpdate

        # Build elements matching other maneuvers' style — Theme B
        path_line = dl.Polyline(positions=path, color="#0d59f2", weight=3, opacity=0.85)

        start_marker = dl.CircleMarker(
            center=[start["lat"], start["lon"]],
            radius=7,
            color="#22c55e",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip("Start Point"),
        )

        # Phase C8a — exit/target heading delta in the end-marker tooltip
        # so the student can see whether they rolled out on the entry
        # heading (ACS target = entry + 360° = entry).
        exit_hdg = float(hover[-1].get("heading", entry_heading)) if hover else float(entry_heading)
        end_marker = dl.CircleMarker(
            center=path[-1],
            radius=7,
            color="#ef4444",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(
                f"Exit hdg {exit_hdg:.0f}° (target = entry {float(entry_heading):.0f}°)"
            ),
        )

        elements = [start_marker, end_marker, path_line]

        # Time-based scrubber (was index-based) with phase markers
        # derived from the sim's segment field. Matches the marker
        # convention used by impossible_turn / PO180.
        SEGMENT_LABELS = {
            "left_roll_in": "Roll In L",
            "left_turn": "Steady L",
            "left_roll_out": "Roll Out L",
            "right_roll_in": "Roll In R",
            "right_turn": "Steady R",
            "right_roll_out": "Roll Out R",
            "pause": "Wings Level",
        }
        max_time = hover[-1]["time"] if hover else 0
        slider_marks = {}
        seen = set()
        for pt in hover:
            seg = pt.get("segment")
            if seg and seg not in seen:
                seen.add(seg)
                t_mark = int(round(float(pt.get("time", 0))))
                label = SEGMENT_LABELS.get(seg, seg.replace("_", " ").title())
                slider_marks[t_mark] = label
        slider_marks[0] = slider_marks.get(0, "Start")
        slider_marks[int(round(max_time))] = "End"
        slider_max = int(round(max_time)) if max_time > 0 else 100
        slider_style = {"display": "block", "marginTop": "10px"}

        # Calculate performance metrics from hover data
        if hover:
            gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover]
            tas_values = [pt.get('tas', 0) for pt in hover]
            aob_values = [abs(pt.get('aob', 0)) for pt in hover]

            min_gs = min(gs_values) if gs_values else 0
            max_gs = max(gs_values) if gs_values else 0
            avg_tas = sum(tas_values) / len(tas_values) if tas_values else entry_ias
            max_bank = max(aob_values) if aob_values else bank_angle
            total_time = hover[-1].get('time', 0) if hover else 0

            # Calculate load factor from bank angle: n = 1/cos(bank)
            load_factor = 1 / math.cos(math.radians(float(bank_angle))) if bank_angle else 1.0

            # Calculate turn radius: r = V² / (g * tan(bank))
            # V in ft/s, g = 32.2 ft/s²
            tas_fps = avg_tas * 1.68781  # knots to ft/s
            turn_radius_ft = (tas_fps ** 2) / (32.2 * math.tan(math.radians(float(bank_angle)))) if bank_angle else 0
            turn_radius_nm = turn_radius_ft / 6076.12

            # Stall speed at bank (Vs × √n) — uses the corrected
            # weight-interpolated lookup the sim now surfaces on the
            # final hover point. Pre-fix the callback read
            # `stall_speed_clean_kias` which doesn't exist in any
            # airframe JSON — fallback was always 48 kt.
            last_pt = hover[-1] if hover else {}
            vs_clean = float(last_pt.get("vs_clean_kt", 50))
            vs_in_turn = float(last_pt.get("vs_at_bank_kt") or (vs_clean * math.sqrt(load_factor)))

            # Get wind info
            wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 0
            wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0
        else:
            min_gs = max_gs = avg_tas = entry_ias
            max_bank = bank_angle
            total_time = 0
            load_factor = 1.0
            turn_radius_ft = turn_radius_nm = 0
            vs_clean = vs_in_turn = 0
            wind_dir_val = wind_speed_val = 0

        # Phase C8a — turn rate in deg/s for the current bank + TAS.
        # ω = g·tan(φ) / V (rad/s); convert to deg/s.
        if bank_angle and avg_tas > 0:
            turn_rate_dps = (
                (180.0 / math.pi)
                * (32.2 * math.tan(math.radians(float(bank_angle))))
                / (avg_tas * 1.68781)
            )
        else:
            turn_rate_dps = 0.0

        # Stall margin (post-fix, uses real Vs)
        stall_margin = entry_ias - vs_in_turn
        if stall_margin < 4:
            sm_color = "#dc2626"
        elif stall_margin < 8:
            sm_color = "#f59e0b"
        else:
            sm_color = "#16a34a"

        # Build info panel with standardized format
        info_content = dbc.Accordion([
            dbc.AccordionItem([
                html.Div(f"Weight: {weight_lbs:.0f} lb | IAS: {entry_ias:.0f} kt | TAS: {avg_tas:.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"Wind: {wind_dir_val:.0f}° at {wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | Radius: {turn_radius_ft:.0f} ft", style={"fontSize": "11px"}),
                html.Div(f"Turn rate: {turn_rate_dps:.1f} °/s", style={"fontSize": "11px"}),
                html.Div(f"GS: {min_gs:.0f}-{max_gs:.0f} kt | Vs(clean): {vs_clean:.0f} kt → Vs×√n: {vs_in_turn:.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"Stall margin: {stall_margin:+.0f} kt", style={"fontSize": "11px", "color": sm_color, "fontWeight": "500"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"Time: {total_time:.0f}s | {sequence.replace('-', ' → ').title()}", style={"fontSize": "11px"}),
                # Phase C9 — ACS tolerance badges. Sim is "perfect" so
                # deviations are 0 (badges render green); the row teaches
                # the student what they'll be graded against.
                html.Div([
                    _acs_metric("Altitude", 0, "ft", target=0, tol=100, cert_level="private"),
                    _acs_metric("Heading", 0, "°", target=0, tol=10, cert_level="private"),
                    _acs_metric("IAS", 0, "kt", target=0, tol=10, cert_level="private"),
                ], style={"display": "flex", "flexWrap": "wrap", "marginTop": "6px"}),
                # Phase D2 — Design Directive power verdict.
                _power_verdict(
                    power_pct, 0.70,
                    "+/- altitude drift in turn",
                    "altitude lost/gained beyond ACS ±100 ft tolerance",
                ),
            ], title="Simulation Results", style={"fontSize": "12px"}),
        ], start_collapsed=False, style={"marginTop": "8px"})

        # Live winds-aloft chip — matches other maneuvers.
        winds_chip = _winds_aloft_chip(wind_profile_data)
        if winds_chip is not None:
            info_content = html.Div([info_content, winds_chip])

        # Calculate bounds for auto-zoom
        if path:
            lats = [p[0] for p in path]
            lons = [p[1] for p in path]
            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
        else:
            bounds = None

        return (
            elements,
            bounds,
            hover,  # Store hover data
            path,   # Store path data
            slider_style,
            slider_max,
            slider_marks,
            0,  # Reset slider to start
            info_content,
        )

    @app.callback(
        Output("scrubber-layer", "children", allow_duplicate=True),
        Input("steepturn-time-slider", "value"),
        State("steepturn-hover-store", "data"),
        State("steepturn-path-store", "data"),
        prevent_initial_call=True
    )
    def update_steep_turn_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position.

        Time-based lookup (post-2026-05-21) — finds the closest hover
        entry by time rather than by index, so the marks "Roll In L /
        Steady L / Roll Out L / ..." land on the right ticks even when
        the segment timing doesn't divide the index range evenly."""
        if not hover_data or not path_data or slider_value is None:
            return []

        target_time = float(slider_value)
        best_idx = 0
        best_diff = abs(hover_data[0].get("time", 0) - target_time)
        for i, hp in enumerate(hover_data):
            diff = abs(hp.get("time", 0) - target_time)
            if diff < best_diff:
                best_diff = diff
                best_idx = i

        idx = best_idx
        if idx >= len(path_data):
            idx = len(path_data) - 1

        pt = hover_data[idx]
        pos = path_data[idx]

        # Friendly segment label
        SEGMENT_LABELS = {
            "left_roll_in": "Left Roll In",
            "left_turn": "Steady Left Turn",
            "left_roll_out": "Left Roll Out",
            "right_roll_in": "Right Roll In",
            "right_turn": "Steady Right Turn",
            "right_roll_out": "Right Roll Out",
            "pause": "Wings Level",
        }
        seg_raw = pt.get('segment', 'turn')
        segment_label = SEGMENT_LABELS.get(seg_raw, seg_raw.replace("_", " ").title())

        load_factor = pt.get("load_factor")
        bank_for_lf = pt.get("aob", 0)
        if load_factor is None and bank_for_lf is not None and abs(bank_for_lf) < 89.9:
            load_factor = 1.0 / math.cos(math.radians(abs(bank_for_lf)))

        tooltip_content = [
            html.Div(segment_label, style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft (MSL)"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', pt.get('tas', 0)):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}° | Load: {load_factor:.2f}G" if load_factor else f"AOB: {abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
            # Crab intentionally not shown — steep turn is a continuous
            # 360° turn; crab varies constantly around the orbit and is
            # noise to the pilot (consistent with chandelle / lazy 8).
            # Marker visual still uses crab to orient the airplane icon.
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # marker convention: positive = right crab
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]
