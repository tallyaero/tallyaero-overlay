"""Turns Around a Point draw + scrubber callbacks.

Inputs: aircraft + environment + center point + radius + turn parameters.
Outputs: map layer with orbit path, bounds, info panel, scrubber state.
"""

from __future__ import annotations

import math

from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from callbacks.map import create_airplane_marker

from core.data_loader import aircraft_data, airport_data


def register(app):
    """Install Turns Around a Point callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("turnspoint-info", "children"),
        Output("turnspoint-hover-store", "data"),
        Output("turnspoint-path-store", "data"),
        Output("turnspoint-warnings-store", "data"),
        Output("turnspoint-slider-container", "style"),
        Output("turnspoint-time-slider", "max"),
        Output("turnspoint-time-slider", "marks"),
        Output("turnspoint-time-slider", "value"),
        Input("turnspoint-draw-btn", "n_clicks"),
        State({"type": "point-store", "m_id": "turns_point", "role": "center"}, "data"),
        State("turnspoint-altitude", "value"),
        State("turnspoint-ias", "value"),
        State("turnspoint-radius", "value"),
        State("turnspoint-num-turns", "value"),
        State("turnspoint-direction", "value"),
        State("turnspoint-entry-heading", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("power-setting", "value"),
        State("cg-slider", "value"),
        prevent_initial_call=True
    )
    def draw_turns_around_point(
        n_clicks,
        center_point,
        altitude_ft,
        ias_knots,
        orbit_radius,
        num_turns,
        turn_direction,
        entry_heading,
        oat_f,
        altimeter_inhg,
        wind_dir,
        wind_speed,
        aircraft_name,
        selected_airport_id,
        runtime_weight,
        power_setting,
        cg_position,
    ):
        if not n_clicks or not center_point:
            raise PreventUpdate

        # Get aircraft data
        if aircraft_name and aircraft_name in aircraft_data:
            ac = dict(aircraft_data[aircraft_name])
        else:
            ac = {}

        # Get weight
        weight_lb = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None
        if weight_lb:
            ac["total_weight_lb"] = weight_lb

        # Parse inputs
        altitude = float(altitude_ft) if altitude_ft not in [None, "", "null"] else 800.0
        ias = float(ias_knots) if ias_knots not in [None, "", "null"] else 100.0
        radius_nm = float(orbit_radius) if orbit_radius not in [None, "", "null"] else 0.25
        turns = int(num_turns) if num_turns not in [None, "", "null"] else 2
        direction = str(turn_direction) if turn_direction not in [None, "", "null"] else "left"
        entry_hdg = float(entry_heading) if entry_heading not in [None, "", "null"] else None

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

        # Parse power setting and CG
        power_pct = float(power_setting) if power_setting not in [None, "", "null"] else 0.5
        cg_pct = float(cg_position) if cg_position not in [None, "", "null"] else 0.5

        # Run simulation
        from simulation import simulate_turns_around_point
        path, hover, sim_warnings = simulate_turns_around_point(
            center_point={"lat": center_point["lat"], "lon": center_point["lon"]},
            turn_direction=direction,
            entry_heading_deg=entry_hdg,
            altitude_ft=altitude,
            ias_knots=ias,
            orbit_radius_nm=radius_nm,
            num_turns=turns,
            wind_dir_deg=float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0,
            wind_speed_kt=float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0,
            oat_c=oat_c,
            altimeter_inhg=altimeter_val,
            field_elev_ft=field_elev_ft,
            ac=ac,
            weight_lb=weight_lb,
            power_setting=power_pct,
            cg_position=cg_pct,
        )

        if not path or not hover:
            raise PreventUpdate

        # Theme B path
        path_line = dl.Polyline(positions=path, color="#0d59f2", weight=3, opacity=0.85)

        # Center reference — blue-500 with fill
        center_marker = dl.CircleMarker(
            center=[center_point["lat"], center_point["lon"]],
            radius=8,
            color="#3b82f6",
            fill=True,
            fillOpacity=0.8,
            children=dl.Tooltip("Reference Point (center)"),
        )

        # Draw the ideal orbit circle
        orbit_radius_ft = radius_nm * 6076.12
        orbit_circle_points = []
        for angle_deg in range(0, 361, 5):
            angle_rad = math.radians(angle_deg)
            n_offset = orbit_radius_ft * math.cos(angle_rad)
            e_offset = orbit_radius_ft * math.sin(angle_rad)
            lat = center_point["lat"] + (n_offset / 364567.2)
            lon = center_point["lon"] + (e_offset / (364567.2 * math.cos(math.radians(center_point["lat"]))))
            orbit_circle_points.append([lat, lon])

        # Theme B target orbit — path-active dashed (not gray)
        orbit_circle = dl.Polyline(
            positions=orbit_circle_points,
            color="#0d59f2",
            weight=2,
            opacity=0.65,
            dashArray="6,6",
            children=dl.Tooltip(f"Target orbit: {radius_nm:.2f} nm ({orbit_radius_ft:.0f} ft)"),
        )

        # Theme B entry (green-500)
        if path:
            entry_marker = dl.CircleMarker(
                center=path[0],
                radius=7,
                color="#22c55e",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip(f"Entry: {altitude:.0f} ft AGL, Hdg {sim_warnings.get('entry_heading', 0):.0f}°"),
            )
        else:
            entry_marker = None

        # Theme B exit (red-500)
        if path:
            exit_marker = dl.CircleMarker(
                center=path[-1],
                radius=7,
                color="#ef4444",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip("Exit"),
            )
        else:
            exit_marker = None

        elements = [center_marker, orbit_circle, path_line]
        if entry_marker:
            elements.append(entry_marker)
        if exit_marker:
            elements.append(exit_marker)

        # Info display with warnings and performance data
        info_elements = []

        # Warnings section (if any)
        has_warnings = (
            sim_warnings.get("stall_margin_warning") or
            sim_warnings.get("g_limit_warning") or
            sim_warnings.get("airspeed_warning") or
            sim_warnings.get("altitude_warning")
        )
        if has_warnings:
            warning_items = []
            if sim_warnings.get("airspeed_warning"):
                warning_items.append(html.Div(f"Airspeed: {sim_warnings['airspeed_warning']}"))
            if sim_warnings.get("stall_margin_warning"):
                warning_items.append(html.Div("Low stall margin - maintain airspeed!"))
            if sim_warnings.get("g_limit_warning"):
                warning_items.append(html.Div("G-limit warning - reduce bank angle"))
            if sim_warnings.get("altitude_warning"):
                warning_items.append(html.Div(f"Altitude: {sim_warnings['altitude_warning']}"))

            info_elements.append(
                html.Div(warning_items, style={"color": "#856404", "backgroundColor": "#fff3cd", "padding": "8px", "borderRadius": "4px", "marginBottom": "5px"})
            )

        # Parse wind values for display
        wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0
        wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0

        # Calculate stall margin
        vs_clean = sim_warnings.get('stall_speed_clean', 48)
        vs_in_turn = sim_warnings.get('stall_speed_in_turn', vs_clean)
        min_ias_achieved = sim_warnings.get('min_ias_achieved', ias)
        max_bank = sim_warnings.get('max_bank_achieved', 0)
        load_factor = 1 / math.cos(math.radians(float(max_bank))) if max_bank > 0 else 1.0

        # Calculate avg TAS from hover data
        if hover:
            tas_values = [pt.get('tas', pt.get('ias', 0)) for pt in hover]
            avg_tas = sum(tas_values) / len(tas_values) if tas_values else ias
        else:
            avg_tas = ias

        # Performance data - standardized format
        info_elements.append(
            dbc.Accordion([
                dbc.AccordionItem([
                    html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb | IAS: {ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {wind_dir_val:.0f}°/{wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"AOB: {sim_warnings.get('min_bank_achieved', 0):.0f}-{max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {sim_warnings.get('min_groundspeed', 0):.0f}-{sim_warnings.get('max_groundspeed', 0):.0f} kt", style={"fontSize": "11px"}),
                    html.Div(f"Orbit: {sim_warnings.get('orbit_radius_ft', 0):.0f} ft | Alt loss: {sim_warnings.get('altitude_loss_ft', 0):.0f} ft", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"Vs turn: {vs_in_turn:.0f} kt | Margin: {min_ias_achieved - vs_in_turn:.0f} kt | Time: {sim_warnings.get('total_time_sec', 0):.0f}s", style={"fontSize": "11px"}),
                    html.Div(f"Turns: {turns} | {direction.title()} | Entry: {sim_warnings.get('entry_heading', 0):.0f}°", style={"fontSize": "11px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
            ], start_collapsed=False, style={"marginTop": "8px"})
        )

        # Prepare slider configuration
        num_points = len(hover)
        slider_max = max(0, num_points - 1)

        # Create marks at key intervals
        slider_marks = {0: "Start"}
        if slider_max > 0:
            slider_marks[slider_max] = "End"

        # Show slider container
        slider_style = {"display": "block", "marginTop": "10px"}

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
            info_elements,
            hover,
            path,
            sim_warnings,
            slider_style,
            slider_max,
            slider_marks,
            0,
        )

    @app.callback(
        Output("scrubber-layer", "children", allow_duplicate=True),
        Input("turnspoint-time-slider", "value"),
        State("turnspoint-hover-store", "data"),
        State("turnspoint-path-store", "data"),
        prevent_initial_call=True
    )
    def update_turns_around_point_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position."""
        if not hover_data or not path_data or slider_value is None:
            return []

        idx = int(slider_value)
        if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
            return []

        pt = hover_data[idx]
        pos = path_data[idx]

        # Build tooltip content
        turn_num = pt.get('turn_number', 1)
        tooltip_content = [
            html.Div(f"Turn {turn_num} - {pt.get('turn_progress', 0):.0f}°", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"GS: {pt.get('gs', 0):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"Load factor: {pt.get('load_factor', 1.0):.2f}G"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
        ]

        # Create airplane marker pointing in direction of heading
        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)

        return [marker]
