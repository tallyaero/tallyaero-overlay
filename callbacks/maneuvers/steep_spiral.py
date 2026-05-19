"""Steep Spiral draw + scrubber callbacks.

Inputs: aircraft + environment + reference point + turn parameters.
Outputs: map layer with spiral path, bounds, warnings, scrubber state.
"""

from __future__ import annotations

import math

from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from utility import simulate_steep_spiral

from callbacks.map import create_airplane_marker
from layouts.maneuvers._charts import altitude_profile_chart
from layouts.maneuvers._shared import _acs_metric

from core.data_loader import aircraft_data, airport_data


def register(app):
    """Install Steep Spiral callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("steepspiral-warnings", "children"),
        Output("steepspiral-hover-store", "data"),
        Output("steepspiral-path-store", "data"),
        Output("steepspiral-slider-container", "style"),
        Output("steepspiral-time-slider", "max"),
        Output("steepspiral-time-slider", "marks"),
        Output("steepspiral-time-slider", "value"),
        Input("steepspiral-draw-btn", "n_clicks"),
        State({"type": "point-store", "m_id": "steep_spiral", "role": "ref"}, "data"),
        State("steepspiral-turns", "value"),
        State("steepspiral-altitude", "value"),
        State("steepspiral-bank-angle", "value"),
        State("steepspiral-clock-position", "value"),
        State("steepspiral-direction", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("power-setting", "value"),
        prevent_initial_call=True
    )
    def draw_steep_spiral(
        n_clicks,
        ref_point,
        num_turns,
        entry_alt_ft,
        bank_angle,
        clock_position,
        turn_direction,
        oat_f,
        altimeter_inhg,
        wind_dir,
        wind_speed,
        aircraft_name,
        selected_airport_id,
        weight_lb,
        power_setting,
    ):
        if not n_clicks or not ref_point or not aircraft_name:
            raise PreventUpdate

        ac = aircraft_data[aircraft_name]

        # Parse inputs
        num_turns = int(num_turns) if num_turns not in [None, "", "null"] else 3
        num_turns = max(3, num_turns)  # Minimum 3 per FAA

        altitude_ft = float(entry_alt_ft) if entry_alt_ft not in [None, "", "null"] else 5000.0
        bank = float(bank_angle) if bank_angle not in [None, "", "null"] else 45.0
        clock_pos = str(clock_position) if clock_position not in [None, "", "null"] else "12"

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

        # Get weight
        weight = float(weight_lb) if weight_lb not in [None, "", "null"] else ac.get("max_takeoff_weight", 2300.0)

        # Phase C7 — global power slider becomes residual_power for Steep
        # Spiral. Stock ACS is idle (0); any value > 5% is off-design and
        # the sim surfaces it as a warning.
        try:
            power_pct = float(power_setting) if power_setting not in [None, "", "null"] else 0.0
        except (TypeError, ValueError):
            power_pct = 0.0
        residual_pwr = power_pct if power_pct > 0.05 else 0.0

        # Run simulation
        path, hover, warnings = simulate_steep_spiral(
            reference_point={"lat": ref_point["lat"], "lon": ref_point["lon"]},
            clock_position=clock_pos,
            turn_direction=turn_direction,
            entry_altitude_ft=altitude_ft,
            bank_angle_deg=bank,
            num_turns=num_turns,
            wind_dir_deg=float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0,
            wind_speed_kt=float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0,
            oat_c=oat_c,
            altimeter_inhg=altimeter_val,
            field_elev_ft=field_elev_ft,
            ac=ac,
            weight_lb=weight,
            residual_power=residual_pwr,
        )

        if not path or not hover:
            raise PreventUpdate

        # Get entry point from warnings (calculated by simulation)
        entry_pt = warnings.get('entry_point', {})

        # Theme B path
        path_line = dl.Polyline(positions=path, color="#0d59f2", weight=3, opacity=0.85)

        # Theme B reference point (spiral center)
        ref_marker = dl.CircleMarker(
            center=[ref_point["lat"], ref_point["lon"]],
            radius=10,
            color="#3b82f6",
            fill=True,
            fillOpacity=0.5,
            children=dl.Tooltip(f"Reference Point (Spiral Center)\nRadius: {warnings.get('orbit_radius_ft', 0):.0f} ft"),
        )

        # Theme B entry (green-500)
        entry_marker = dl.CircleMarker(
            center=[entry_pt.get('lat', path[0][0]), entry_pt.get('lon', path[0][1])],
            radius=7,
            color="#22c55e",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(f"Entry: {altitude_ft:.0f} ft AGL\nHeading: {warnings.get('entry_heading', 0):.0f}°"),
        )

        # Theme B end (red-500) + Phase C7 exit-heading enrichment
        exit_hdg = warnings.get('exit_heading', 0)
        end_marker = dl.CircleMarker(
            center=path[-1],
            radius=7,
            color="#ef4444",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(
                f"Exit: {warnings.get('final_altitude_agl', 0):.0f} ft AGL — "
                f"hdg {exit_hdg:.0f}° (entry {warnings.get('entry_heading', 0):.0f}°)"
            ),
        )

        elements = [ref_marker, entry_marker, end_marker, path_line]

        # Build warnings display
        warning_elements = []

        # Phase C7 — tier-3 verdict banner when the required (unclamped)
        # bank exceeded 60° at any step.
        if warnings.get('peak_bank_exceeded_60'):
            warning_elements.append(html.Div([
                html.Strong("Peak bank exceeded 60° — "),
                html.Span("required bank for the chosen orbit + wind would exceed the ACS allowable. "
                          "Reduce bank or increase orbit radius."),
            ], style={
                "color": "white",
                "backgroundColor": "var(--ta-path-fail, #dc2626)",
                "padding": "8px",
                "borderRadius": "4px",
                "marginBottom": "5px",
                "fontSize": "12px",
            }))

        # Phase C7 — tier-2 amber chip for off-design residual power.
        if warnings.get('off_design_residual_power'):
            rp = warnings['off_design_residual_power']
            warning_elements.append(html.Div(
                f"Off-design power: {rp:.0f}% — Steep Spiral is an idle-power maneuver. "
                f"Descent rate reduced; may not reach 1500 ft AGL completion.",
                style={
                    "borderLeft": "3px solid var(--acs-marginal, #f59e0b)",
                    "color": "var(--acs-marginal, #f59e0b)",
                    "padding": "4px 8px",
                    "marginBottom": "6px",
                    "fontSize": "11px",
                    "backgroundColor": "rgba(245, 158, 11, 0.05)",
                },
            ))

        # Ground impact warning (critical)
        if warnings.get('ground_impact'):
            warning_elements.append(
                html.Div([
                    html.Strong("GROUND IMPACT: "),
                    html.Span("Aircraft would impact terrain before completing the maneuver. "),
                    html.Span(f"Suggested minimum start altitude: {warnings.get('suggested_min_start_alt', 0):.0f} ft AGL"),
                ], style={"color": "white", "backgroundColor": "#dc3545", "padding": "8px", "borderRadius": "4px", "marginBottom": "5px"})
            )

        # Below minimum warning
        elif warnings.get('below_minimum'):
            warning_elements.append(
                html.Div([
                    html.Strong("BELOW MINIMUM: "),
                    html.Span(f"Final altitude {warnings.get('final_altitude_agl', 0):.0f} ft AGL is below 1,500 ft AGL minimum. "),
                    html.Span(f"Suggested minimum start altitude: {warnings.get('suggested_min_start_alt', 0):.0f} ft AGL"),
                ], style={"color": "#856404", "backgroundColor": "#fff3cd", "padding": "8px", "borderRadius": "4px", "marginBottom": "5px"})
            )

        # Calculate performance metrics
        wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0
        wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0

        if hover:
            gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover]
            tas_values = [pt.get('tas', pt.get('ias', 0)) for pt in hover]
            ias_values = [pt.get('ias', 0) for pt in hover]
            aob_values = [abs(pt.get('aob', 0)) for pt in hover]
            vs_values = [abs(pt.get('vs', 0)) for pt in hover]

            min_gs = min(gs_values) if gs_values else 0
            max_gs = max(gs_values) if gs_values else 0
            avg_ias = sum(ias_values) / len(ias_values) if ias_values else 0
            avg_tas = sum(tas_values) / len(tas_values) if tas_values else 0
            max_bank = max(aob_values) if aob_values else bank
            avg_vs = sum(vs_values) / len(vs_values) if vs_values else 0
            total_time = hover[-1].get('time', 0) if hover else 0
        else:
            min_gs = max_gs = avg_ias = avg_tas = 0
            max_bank = bank
            avg_vs = 0
            total_time = 0

        # Calculate load factor at max bank
        load_factor = 1 / math.cos(math.radians(float(max_bank))) if max_bank > 0 else 1.0

        # Stall speed calculations
        vs_clean = float(ac.get("stall_speed_clean_kias", 48))
        vs_in_turn = vs_clean * math.sqrt(load_factor)
        min_ias = min([pt.get('ias', avg_ias) for pt in hover]) if hover else avg_ias

        # Standardized info display
        warning_elements.append(
            dbc.Accordion([
                dbc.AccordionItem([
                    html.Div(f"Weight: {weight:.0f} lb | IAS: {avg_ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {wind_dir_val:.0f}°/{wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {min_gs:.0f}-{max_gs:.0f} kt", style={"fontSize": "11px"}),
                    html.Div(f"Orbit: {warnings.get('orbit_radius_ft', 0):.0f} ft | VS: {avg_vs:.0f} fpm", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"Alt: {altitude_ft:.0f}→{warnings.get('final_altitude_agl', 0):.0f} ft | Loss: {altitude_ft - warnings.get('final_altitude_agl', 0):.0f} ft ({warnings.get('altitude_per_turn', 0):.0f}/turn)", style={"fontSize": "11px"}),
                    html.Div(f"Vs turn: {vs_in_turn:.0f} kt | Margin: {min_ias - vs_in_turn:.0f} kt | Time: {total_time:.0f}s", style={"fontSize": "11px"}),
                    # Phase C9 — Commercial ACS tolerances.
                    html.Div([
                        _acs_metric("Exit heading", 0, "°", target=0, tol=10, cert_level="commercial"),
                        _acs_metric("Altitude at exit", 0, "ft", target=0, tol=100, cert_level="commercial"),
                    ], style={"display": "flex", "flexWrap": "wrap", "marginTop": "6px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
            ], start_collapsed=False, style={"marginTop": "8px"})
        )

        # Phase C7 — altitude profile chart with one marker per completed turn.
        times = [pt.get("time", 0) for pt in hover]
        alts = [pt.get("alt", 0) for pt in hover]
        markers = []
        prev_turn = 0
        for pt in hover:
            tn = int(pt.get("turn_number", 1))
            if tn != prev_turn and prev_turn > 0:
                markers.append((pt.get("time", 0), f"T{tn}"))
            prev_turn = tn
        warning_elements.append(altitude_profile_chart(
            times, alts, chart_id="steepspiral-profile-chart",
            markers=markers, y_title="Altitude (ft AGL)",
        ))

        # Prepare slider configuration
        num_points = len(hover)
        slider_max = max(0, num_points - 1)

        # Create marks at key intervals (start, each turn boundary, end)
        slider_marks = {0: "Start"}
        if slider_max > 0:
            slider_marks[slider_max] = "End"
            # Add marks at approximate turn boundaries
            for i, pt in enumerate(hover):
                if pt.get('turn_progress', 0) < 5 and pt.get('turn_number', 1) > 1:
                    turn_num = pt.get('turn_number', 1)
                    slider_marks[i] = f"T{turn_num}"

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
            warning_elements,
            hover,  # Store hover data
            path,   # Store path data
            slider_style,
            slider_max,
            slider_marks,
            0,  # Reset slider to start
        )

    @app.callback(
        Output("scrubber-layer", "children"),
        Input("steepspiral-time-slider", "value"),
        State("steepspiral-hover-store", "data"),
        State("steepspiral-path-store", "data"),
        prevent_initial_call=True
    )
    def update_steep_spiral_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position."""
        if not hover_data or not path_data or slider_value is None:
            return []

        # Ensure slider value is within bounds
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
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
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
