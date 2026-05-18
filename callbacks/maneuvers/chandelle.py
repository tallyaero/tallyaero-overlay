"""Chandelle draw + scrubber callbacks.

Inputs: aircraft + environment + entry heading + bank + direction.
Outputs: map layer with altitude-colored path, bounds, info panel, scrubber state.
"""

from __future__ import annotations

import math

from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from utility import simulate_chandelle

from callbacks.map import create_airplane_marker

from core.data_loader import aircraft_data, airport_data


def register(app):
    """Install Chandelle callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("chandelle-hover-store", "data"),
        Output("chandelle-path-store", "data"),
        Output("chandelle-slider-container", "style"),
        Output("chandelle-time-slider", "max"),
        Output("chandelle-time-slider", "marks"),
        Output("chandelle-time-slider", "value"),
        Output("chandelle-info", "children"),
        Input("chandelle-draw-btn", "n_clicks"),
        State({"type": "point-store", "m_id": "chandelle", "role": "start"}, "data"),
        State("chandelle-entry-heading", "value"),
        State("chandelle-bank-angle", "value"),
        State("chandelle-direction", "value"),
        State("chandelle-altitude", "value"),
        State("chandelle-ias", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        prevent_initial_call=True
    )
    def draw_chandelle(
        n_clicks,
        start,
        entry_heading,
        bank_angle,
        direction,
        entry_alt_ft,
        entry_ias,
        oat_f,
        altimeter_inhg,
        wind_dir,
        wind_speed,
        aircraft_name,
        selected_airport_id,
        weight_lb
    ):
        if not n_clicks or not start or not aircraft_name:
            raise PreventUpdate

        ac = aircraft_data[aircraft_name]

        # Use Va as default entry IAS if user left blank
        if int(ac.get("engine_count", 1)) > 1:
            va = float((ac.get("multi_engine_limits", {}) or {}).get("va", 100))
        else:
            va = float((ac.get("single_engine_limits", {}) or {}).get("va", 100))
        entry_ias = float(entry_ias) if entry_ias not in [None, "", "null"] else float(va)

        # Parse altitude
        altitude_ft = float(entry_alt_ft) if entry_alt_ft not in [None, "", "null"] else 3000.0

        # OAT F -> C
        try:
            oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0
        except Exception:
            oat_c = (52.0 - 32.0) * 5.0 / 9.0

        # Get airport elevation
        selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
        field_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

        # Parse altimeter
        altimeter_val = float(altimeter_inhg) if altimeter_inhg not in [None, "", "null"] else 29.92

        # Parse bank angle
        bank = float(bank_angle) if bank_angle not in [None, "", "null"] else 30.0

        # Parse heading
        heading = float(entry_heading) if entry_heading not in [None, "", "null"] else 0.0

        # Get weight (use runtime total weight or fall back to max takeoff)
        weight = float(weight_lb) if weight_lb not in [None, "", "null"] else ac.get("max_takeoff_weight", 2300.0)

        path, hover = simulate_chandelle(
            entry_point={"lat": start["lat"], "lon": start["lon"]},
            entry_heading_deg=heading,
            turn_direction=direction,
            entry_altitude_ft=altitude_ft,
            entry_ias_knots=entry_ias,
            bank_angle_deg=bank,
            wind_dir_deg=float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0,
            wind_speed_kt=float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0,
            oat_c=oat_c,
            altimeter_inhg=altimeter_val,
            field_elev_ft=field_elev_ft,
            ac=ac,
            weight_lb=weight,
        )

        if not path or not hover:
            raise PreventUpdate

        # Build path segments with altitude-based coloring
        # Entry (min alt) = red, Max altitude = blue
        altitudes = [pt.get('alt', 0) for pt in hover]
        min_alt = min(altitudes) if altitudes else 0
        max_alt = max(altitudes) if altitudes else 1
        alt_range = max(max_alt - min_alt, 1)  # Avoid division by zero

        def alt_to_color(alt):
            """Map altitude to color: low=red, high=blue"""
            t = (alt - min_alt) / alt_range
            t = max(0, min(1, t))
            r = int(255 * (1 - t))
            g = int(100 * (1 - abs(t - 0.5) * 2))
            b = int(255 * t)
            return f"#{r:02x}{g:02x}{b:02x}"

        # Create colored path segments
        path_segments = []
        for i in range(len(path) - 1):
            if i < len(hover):
                alt = hover[i].get('alt', min_alt)
                color = alt_to_color(alt)
            else:
                color = "#888888"

            path_segments.append(
                dl.Polyline(
                    positions=[path[i], path[i + 1]],
                    color=color,
                    weight=4,
                )
            )

        # Start marker — Theme B start (green-500)
        start_marker = dl.CircleMarker(
            center=[start["lat"], start["lon"]],
            radius=7,
            color="#22c55e",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip("Entry Point"),
        )

        # End marker — Theme B end (red-500)
        end_marker = dl.CircleMarker(
            center=path[-1],
            radius=7,
            color="#ef4444",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(f"Exit: {hover[-1].get('heading', 0):.0f}° hdg, {hover[-1].get('alt', 0):.0f} ft"),
        )

        elements = [start_marker, end_marker] + path_segments

        # Prepare slider configuration
        num_points = len(hover)
        slider_max = max(0, num_points - 1)
        slider_marks = {0: "Start"}
        if slider_max > 0:
            slider_marks[slider_max] = "End"
            # Add 90° point marker
            for i, pt in enumerate(hover):
                if abs(pt.get('turn_progress', 0) - 90) < 5:
                    slider_marks[i] = "90°"
                    break

        slider_style = {"display": "block", "marginTop": "10px"}

        # Calculate performance metrics
        wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0
        wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0

        if hover:
            gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover]
            tas_values = [pt.get('tas', 0) for pt in hover]
            aob_values = [abs(pt.get('aob', 0)) for pt in hover]

            min_gs = min(gs_values) if gs_values else 0
            max_gs = max(gs_values) if gs_values else 0
            avg_tas = sum(tas_values) / len(tas_values) if tas_values else entry_ias
            max_bank = max(aob_values) if aob_values else bank
            total_time = hover[-1].get('time', 0) if hover else 0
            exit_heading = hover[-1].get('heading', 0) if hover else heading
            exit_alt = hover[-1].get('alt', altitude_ft) if hover else altitude_ft
            alt_gain = exit_alt - altitude_ft
        else:
            min_gs = max_gs = avg_tas = entry_ias
            max_bank = bank
            total_time = 0
            exit_heading = heading + (180 if direction == "right" else -180)
            exit_alt = altitude_ft
            alt_gain = 0

        # Calculate load factor at max bank
        load_factor = 1 / math.cos(math.radians(float(max_bank))) if max_bank > 0 else 1.0

        # Stall speed calculations
        vs_clean = float(ac.get("stall_speed_clean_kias", 48))
        vs_in_turn = vs_clean * math.sqrt(load_factor)
        min_ias = min([pt.get('tas', entry_ias) for pt in hover]) if hover else entry_ias

        # Build info panel with standardized format
        info_content = dbc.Accordion([
            dbc.AccordionItem([
                html.Div(f"Weight: {weight:.0f} lb | IAS: {entry_ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {wind_dir_val:.0f}°/{wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {min_gs:.0f}-{max_gs:.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"Alt: {altitude_ft:.0f}→{exit_alt:.0f} ft (+{alt_gain:.0f}) | {direction.title()} 180°", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"Vs turn: {vs_in_turn:.0f} kt | Margin: {min_ias - vs_in_turn:.0f} kt | Time: {total_time:.0f}s", style={"fontSize": "11px"}),
                html.Div([
                    html.Span("Color: ", style={"fontSize": "10px"}),
                    html.Span("■ Low", style={"color": "#ff0000", "fontSize": "10px", "marginRight": "6px"}),
                    html.Span("■ Mid", style={"color": "#804080", "fontSize": "10px", "marginRight": "6px"}),
                    html.Span("■ High", style={"color": "#0000ff", "fontSize": "10px"}),
                ], style={"marginTop": "4px"}),
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
        Input("chandelle-time-slider", "value"),
        State("chandelle-hover-store", "data"),
        State("chandelle-path-store", "data"),
        prevent_initial_call=True
    )
    def update_chandelle_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position."""
        if not hover_data or not path_data or slider_value is None:
            return []

        idx = int(slider_value)
        if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
            return []

        pt = hover_data[idx]
        pos = path_data[idx]

        segment = pt.get('segment', 'climb')

        tooltip_content = [
            html.Div(f"{segment.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}° | Pitch: {pt.get('pitch', 0):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Stall Margin: +{pt.get('speed_margin', 0):.0f} kt"),
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]
