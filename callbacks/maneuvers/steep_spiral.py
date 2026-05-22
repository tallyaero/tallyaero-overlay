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
from layouts.maneuvers._shared import _acs_metric, _power_verdict, _winds_aloft_chip

from core.data_loader import aircraft_data, airport_data
from core.profile3d import build_3d_side_view_block, side_view_accordion_item


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
        Input({"type": "draw-btn", "m_id": "steep_spiral"}, "n_clicks"),
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
        State("engine-select", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("power-setting", "value"),
        State("wind-profile-store", "data"),
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
        engine_name,
        selected_airport_id,
        weight_lb,
        power_setting,
        wind_profile_data,
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

        # Phase H — hydrate live winds-aloft column when staged.
        wind_profile = None
        if wind_profile_data:
            try:
                from core.winds_aloft import WindProfile
                wind_profile = WindProfile.from_store(wind_profile_data)
            except Exception:
                wind_profile = None

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
            wind_profile=wind_profile,
            engine_option=engine_name,
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

        # Phase D2 — the graded Design Directive power verdict (added below
        # inside the accordion) supersedes the C7 binary amber chip. The
        # off_design_residual_power warning is still emitted by the sim but
        # the chip is now consolidated into the accordion verdict.

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

        # Stall references — surfaced by the sim. Pre-fix the callback
        # read `stall_speed_clean_kias` (non-existent key) and got Vs=48
        # for every airframe. Now uses the correct weight-interpolated Vs
        # and the load-factor-adjusted Vs at the max bank ACTUALLY flown
        # (after τ-smoothing, distinct from the geometry's required bank).
        last_hover = hover[-1] if hover else {}
        vs_clean = float(last_hover.get("vs_clean_kt", 50))
        vs_in_turn = float(last_hover.get("vs_at_bank_kt") or (vs_clean * math.sqrt(load_factor)))
        min_ias = float(last_hover.get("min_ias_kt") or (
            min([pt.get('ias', avg_ias) for pt in hover]) if hover else avg_ias
        ))
        stall_margin_min = min_ias - vs_in_turn
        peak_unclamped = last_hover.get("peak_unclamped_bank_deg")

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
                    html.Div(
                        f"Vs(clean): {vs_clean:.0f} → Vs×√n at {max_bank:.0f}°: {vs_in_turn:.0f} kt | min IAS: {min_ias:.0f} kt | Time: {total_time:.0f}s",
                        style={"fontSize": "11px"},
                    ),
                    html.Div(
                        f"Stall margin (min IAS): {stall_margin_min:+.0f} kt"
                        + (f"  ·  Geometry required {peak_unclamped:.0f}° bank (capped at 60°)"
                           if peak_unclamped is not None and peak_unclamped > 60.5 else ""),
                        style={
                            "fontSize": "11px",
                            "color": (
                                "#dc2626" if stall_margin_min < 4
                                else "#f59e0b" if stall_margin_min < 8
                                else "#16a34a"
                            ),
                            "fontWeight": "500",
                        },
                    ),
                    # Phase C9 — Commercial ACS tolerances.
                    html.Div([
                        _acs_metric("Exit heading", 0, "°", target=0, tol=10, cert_level="commercial"),
                        _acs_metric("Altitude at exit", 0, "ft", target=0, tol=100, cert_level="commercial"),
                    ], style={"display": "flex", "flexWrap": "wrap", "marginTop": "6px"}),
                    # Phase D2 — Design Directive power verdict.
                    _power_verdict(
                        power_pct, 0.0,
                        "reduced descent rate, longer time to lose altitude",
                        "descent rate too low to complete training profile",
                    ),
                ], title="Simulation Results", style={"fontSize": "12px"}),
                # 3D Side View — steep spiral descends through 3+ turns;
                # the side view shows the corkscrew descent in space.
                side_view_accordion_item(
                    build_3d_side_view_block(
                        path=path,
                        hover=hover,
                        elev_ft=float(field_elev_ft or 0.0),
                    )
                ),
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

        # Phase H — live winds-aloft column chip.
        chip = _winds_aloft_chip(wind_profile_data)
        if chip is not None:
            warning_elements.append(chip)

        # Time-based scrubber (was index). Marks: Start · T2 · T3 · End,
        # where Tn is the first tick where turn_number flips to n. The
        # pre-fix code used hover index as both the scrubber position
        # AND the mark key; for high-resolution sims that produced
        # marks at indices the slider couldn't navigate to cleanly.
        max_time = hover[-1].get("time", 0) if hover else 0
        slider_marks = {}
        prev_turn = 0
        for pt in hover:
            tn = int(pt.get("turn_number", 1))
            if tn != prev_turn and prev_turn > 0:
                t_mark = int(round(float(pt.get("time", 0))))
                slider_marks[t_mark] = f"T{tn}"
            prev_turn = tn
        slider_marks[0] = "Start"
        slider_marks[int(round(max_time))] = "End"
        slider_max = int(round(max_time)) if max_time > 0 else 100

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
        """Update the scrubber marker and tooltip based on slider position.

        Time-based lookup (post-2026-05-21) — finds the closest hover
        entry by time so T2 / T3 marks land on the right turn boundary
        regardless of timestep granularity."""
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
            # Crab intentionally not shown — steep spiral is a continuous
            # descending orbit; crab varies through every turn and is
            # noise to the pilot. Marker visual still uses crab to
            # orient the airplane icon.
        ]

        # Create airplane marker pointing in direction of heading
        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)

        return [marker]
