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
        Input("steepturn-draw-btn", "n_clicks"),
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
        selected_airport_id
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

        end_marker = dl.CircleMarker(
            center=path[-1],
            radius=7,
            color="#ef4444",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip("End Point"),
        )

        elements = [start_marker, end_marker, path_line]

        # Prepare slider configuration
        num_points = len(hover)
        slider_max = max(0, num_points - 1)
        slider_marks = {0: "Start"}
        if slider_max > 0:
            slider_marks[slider_max] = "End"

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

            # Calculate stall speed in turn: Vs_turn = Vs * sqrt(load_factor)
            vs_clean = float(ac.get("stall_speed_clean_kias", 48))
            vs_in_turn = vs_clean * math.sqrt(load_factor)

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

        # Build info panel with standardized format
        info_content = dbc.Accordion([
            dbc.AccordionItem([
                html.Div(f"Weight: {weight_lbs:.0f} lb | IAS: {entry_ias:.0f} kt | TAS: {avg_tas:.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"Wind: {wind_dir_val:.0f}° at {wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | Radius: {turn_radius_ft:.0f} ft", style={"fontSize": "11px"}),
                html.Div(f"GS: {min_gs:.0f}-{max_gs:.0f} kt | Vs turn: {vs_in_turn:.0f} kt | Margin: {entry_ias - vs_in_turn:.0f} kt", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"Time: {total_time:.0f}s | {sequence.replace('-', ' → ').title()}", style={"fontSize": "11px"}),
            ], title="Simulation Results", style={"fontSize": "12px"}),
        ], start_collapsed=False, style={"marginTop": "8px"})

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
        """Update the scrubber marker and tooltip based on slider position."""
        if not hover_data or not path_data or slider_value is None:
            return []

        idx = int(slider_value)
        if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
            return []

        pt = hover_data[idx]
        pos = path_data[idx]

        segment = pt.get('segment', 'turn')

        tooltip_content = [
            html.Div(f"{segment.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"TAS: {pt.get('tas', 0):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]
