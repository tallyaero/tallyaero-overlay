"""S-Turn bearing-preview + draw + scrubber callbacks.

Inputs: aircraft + environment + reference point + bearing + turn parameters.
Outputs: map layer with reference line preview, simulated S-turn path,
bounds, info panel, scrubber state.
"""

from __future__ import annotations

from dash import html, Input, Output, State, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from callbacks.map import create_airplane_marker
from layouts.maneuvers._shared import _acs_metric, _power_verdict

from core.data_loader import aircraft_data, airport_data


def _wind_perp_offset_deg(line_bearing: float, wind_dir: float) -> float:
    """Return angular offset (deg) between the reference line and the
    wind-perpendicular axis, in the range [0, 90].

    Phase C2 — ACS Gap 3. S-Turns is meant to be flown across the wind,
    so the reference line should be perpendicular to wind. Offset 0
    means the line is perfectly perpendicular; offset 90 means the line
    is parallel to wind (worst case). Caller renders an amber chip
    above the info panel when offset > 15°."""
    return abs(((line_bearing - wind_dir) % 180) - 90)


def register(app):
    """Install S-Turn callbacks against the given Dash app."""

    @app.callback(
        Output("sturn-calculated-bearing", "data"),
        Output("layer", "children", allow_duplicate=True),
        Input({"type": "point-store", "m_id": "s_turn", "role": "ref"}, "data"),
        Input({"type": "point-store", "m_id": "s_turn", "role": "bearing"}, "data"),
        State("layer", "children"),
        State("maneuver-select", "value"),
        prevent_initial_call=True
    )
    def calculate_sturn_bearing_and_preview(ref_point, bearing_point, layer_children, current_maneuver):
        """
        Calculate bearing from reference point to bearing point and draw a preview line.
        The reference line extends in both directions from the reference point.
        """
        from physics import calculate_initial_compass_bearing, point_from

        # Only run this callback when S-turn maneuver is selected
        if current_maneuver != "s_turn":
            raise PreventUpdate

        # Remove any existing S-turn reference line preview
        if layer_children is None:
            layer_children = []
        layer_children = [c for c in layer_children if not (isinstance(c, dict) and c.get('props', {}).get('id') == 'sturn-ref-line-preview')]

        # If we don't have both points, just return current state
        if not ref_point or not isinstance(ref_point, dict) or ref_point.get('lat') is None:
            return no_update, layer_children

        ref_lat = ref_point['lat']
        ref_lon = ref_point['lon']

        # If we have a bearing point, calculate the bearing
        if bearing_point and isinstance(bearing_point, dict) and bearing_point.get('lat') is not None:
            bearing_lat = bearing_point['lat']
            bearing_lon = bearing_point['lon']

            # Calculate bearing from ref to bearing point
            from geopy import Point as GeoPoint
            ref_geo = GeoPoint(ref_lat, ref_lon)
            bearing_geo = GeoPoint(bearing_lat, bearing_lon)
            calculated_bearing = calculate_initial_compass_bearing(ref_geo, bearing_geo)
            calculated_bearing = round(calculated_bearing, 1)

            # Draw a reference line extending in both directions (about 1 nm each way)
            line_length_nm = 1.0
            pt_forward = point_from(ref_geo, calculated_bearing, line_length_nm)
            pt_backward = point_from(ref_geo, (calculated_bearing + 180) % 360, line_length_nm)

            # Theme B preview reference line — path-active dashed
            preview_line = dl.Polyline(
                id='sturn-ref-line-preview',
                positions=[
                    [pt_backward.latitude, pt_backward.longitude],
                    [ref_lat, ref_lon],
                    [pt_forward.latitude, pt_forward.longitude]
                ],
                color="#0d59f2",
                weight=2,
                opacity=0.65,
                dashArray="6,6",
                children=dl.Tooltip(f"Reference Line: {calculated_bearing:.0f}°")
            )
            layer_children.append(preview_line)

            # Maneuver start — intermediate amber (will become entry green after Draw)
            ref_marker = dl.CircleMarker(
                center=[ref_lat, ref_lon],
                radius=8,
                color="#f59e0b",
                fill=True,
                fillColor="#f59e0b",
                fillOpacity=0.8,
                children=dl.Tooltip("Maneuver Start")
            )
            bearing_marker = dl.CircleMarker(
                center=[bearing_lat, bearing_lon],
                radius=6,
                color="#f59e0b",
                fill=True,
                fillColor="#f59e0b",
                fillOpacity=0.6,
                children=dl.Tooltip("Bearing Point")
            )
            layer_children.extend([ref_marker, bearing_marker])

            return calculated_bearing, layer_children
        else:
            # Only ref point set - just show the ref marker
            ref_marker = dl.CircleMarker(
                center=[ref_lat, ref_lon],
                radius=8,
                color="#f59e0b",
                fill=True,
                fillColor="#f59e0b",
                fillOpacity=0.8,
                children=dl.Tooltip("Reference Point (click 2nd point to set bearing)")
            )
            layer_children.append(ref_marker)
            return no_update, layer_children

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("sturn-info", "children"),
        Output("sturn-hover-store", "data"),
        Output("sturn-path-store", "data"),
        Output("sturn-slider-container", "style"),
        Output("sturn-time-slider", "max"),
        Output("sturn-time-slider", "marks"),
        Output("sturn-time-slider", "value"),
        Input("sturn-draw-btn", "n_clicks"),
        State({"type": "point-store", "m_id": "s_turn", "role": "ref"}, "data"),
        State("sturn-line-bearing", "data"),
        State("sturn-calculated-bearing", "data"),
        State("sturn-altitude", "value"),
        State("sturn-ias", "value"),
        State("sturn-bank-angle", "value"),
        State("sturn-num-turns", "value"),
        State("sturn-entry-side", "value"),
        State("sturn-first-turn", "value"),
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
    def draw_s_turn(
        n_clicks,
        ref_point,
        line_bearing_input,
        calculated_bearing,
        altitude_ft,
        ias_knots,
        bank_angle,
        num_s_turns,
        entry_side,
        first_turn,
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
        if not n_clicks or not ref_point:
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

        # Parse inputs - prefer calculated bearing from map clicks, fallback to manual input
        if calculated_bearing is not None and calculated_bearing not in ["", "null"]:
            line_bearing = float(calculated_bearing)
        elif line_bearing_input not in [None, "", "null"]:
            line_bearing = float(line_bearing_input)
        else:
            line_bearing = 90.0
        altitude = float(altitude_ft) if altitude_ft not in [None, "", "null"] else 800.0
        ias = float(ias_knots) if ias_knots not in [None, "", "null"] else 100.0
        bank = float(bank_angle) if bank_angle not in [None, "", "null"] else 35.0
        num_turns = int(num_s_turns) if num_s_turns not in [None, "", "null"] else 2

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

        # Parse power setting (slider is 0.05-1.0 percentage)
        power_pct = float(power_setting) if power_setting not in [None, "", "null"] else 0.5

        # Parse CG position (slider is 0.0-1.0, where 0=forward, 1=aft within envelope)
        cg_pct = float(cg_position) if cg_position not in [None, "", "null"] else 0.5

        # Run simulation
        from simulation import simulate_s_turn
        path, hover, sim_warnings = simulate_s_turn(
            reference_point={"lat": ref_point["lat"], "lon": ref_point["lon"]},
            line_bearing_deg=line_bearing,
            entry_side=entry_side,
            turn_direction_first=first_turn,
            altitude_ft=altitude,
            ias_knots=ias,
            base_bank_deg=bank,
            num_s_turns=num_turns,
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

        # Theme B reference start point
        ref_marker = dl.CircleMarker(
            center=[ref_point["lat"], ref_point["lon"]],
            radius=8,
            color="#3b82f6",
            fill=True,
            fillOpacity=0.7,
            children=dl.Tooltip("Maneuver Start"),
        )

        # Theme B reference line (active path color, dashed)
        if path and len(path) >= 2:
            reference_line = dl.Polyline(
                positions=[
                    [ref_point["lat"], ref_point["lon"]],
                    path[-1]  # Exit point
                ],
                color="#0d59f2",
                weight=2,
                opacity=0.65,
                dashArray="6,6",
                children=dl.Tooltip(f"Reference Line ({line_bearing:.0f}°)"),
            )
        else:
            # Fallback if no path
            from geopy import Point as GeoPoint
            from physics import point_from
            ref_geo = GeoPoint(ref_point["lat"], ref_point["lon"])
            pt_forward = point_from(ref_geo, line_bearing, 0.5)
            reference_line = dl.Polyline(
                positions=[
                    [ref_point["lat"], ref_point["lon"]],
                    [pt_forward.latitude, pt_forward.longitude]
                ],
                color="#0d59f2",
                weight=2,
                opacity=0.65,
                dashArray="6,6",
                children=dl.Tooltip(f"Reference Line ({line_bearing:.0f}°)"),
            )

        # Theme B entry (green-500)
        if path:
            entry_marker = dl.CircleMarker(
                center=path[0],
                radius=7,
                color="#22c55e",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip(f"Entry: {altitude:.0f} ft AGL"),
            )
        else:
            entry_marker = None

        # Theme B end (red-500)
        if path:
            end_marker = dl.CircleMarker(
                center=path[-1],
                radius=7,
                color="#ef4444",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip("Exit"),
            )
        else:
            end_marker = None

        elements = [ref_marker, reference_line, path_line]
        if entry_marker:
            elements.append(entry_marker)
        if end_marker:
            elements.append(end_marker)

        # Info display with warnings and performance data
        info_elements = []

        # Phase C2 — ACS Gap 3 — wind-alignment chip.
        # S-Turns is meant to be flown across the wind; flag any reference
        # line off more than 15° from wind-perpendicular.
        wind_dir_chip = float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0
        wind_perp = _wind_perp_offset_deg(line_bearing, wind_dir_chip)
        if wind_perp > 15:
            info_elements.append(html.Div(
                f"Wind alignment off by {wind_perp:.0f}° — "
                f"ACS expects reference line perpendicular to wind",
                style={
                    "borderLeft": "3px solid var(--acs-marginal)",
                    "color": "var(--acs-marginal)",
                    "padding": "4px 8px",
                    "marginBottom": "6px",
                    "fontSize": "11px",
                    "backgroundColor": "rgba(245, 158, 11, 0.05)",
                },
            ))

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
                warning_items.append(html.Div("Stall margin low - bank angle reduced for safety"))
            if sim_warnings.get("g_limit_warning"):
                warning_items.append(html.Div("G-limit exceeded - bank angle reduced"))
            if sim_warnings.get("bank_limited"):
                warning_items.append(html.Div(f"AOB limited: {sim_warnings.get('original_bank', 0):.0f}° → {sim_warnings.get('effective_bank', 0):.0f}°"))
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
        vs_in_turn = sim_warnings.get('stall_speed_in_turn', 48)
        min_ias_achieved = sim_warnings.get('min_ias_achieved', ias)

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
                    html.Div(f"AOB: {sim_warnings.get('min_bank_achieved', 0):.0f}-{sim_warnings.get('max_bank_achieved', 0):.0f}° | Load: {sim_warnings.get('load_factor', 1):.2f}G | GS: {sim_warnings.get('min_groundspeed', 0):.0f}-{sim_warnings.get('max_groundspeed', 0):.0f} kt", style={"fontSize": "11px"}),
                    html.Div(f"Radius: {sim_warnings.get('turn_radius_ft', 0):.0f} ft | Alt loss: {sim_warnings.get('altitude_loss_ft', 0):.0f} ft", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"Vs turn: {vs_in_turn:.0f} kt | Margin: {min_ias_achieved - vs_in_turn:.0f} kt | Time: {sim_warnings.get('total_time_sec', 0):.0f}s", style={"fontSize": "11px"}),
                    html.Div(f"S-Turns: {num_turns} | Ref: {line_bearing:.0f}° | {entry_side.title()} entry", style={"fontSize": "11px"}),
                    # Phase C9 — Private ACS tolerances.
                    html.Div([
                        _acs_metric("Altitude", 0, "ft", target=0, tol=100, cert_level="private"),
                        _acs_metric("Track radius", 0, "%", target=0, tol=10, cert_level="private"),
                        _acs_metric("Wing-level crossing", 0, "°", target=0, tol=10, cert_level="private"),
                    ], style={"display": "flex", "flexWrap": "wrap", "marginTop": "6px"}),
                    # Phase D2 — Design Directive power verdict.
                    _power_verdict(
                        power_pct, 0.60,
                        "wider arcs, more crab",
                        "ground track exceeded 10% radius tolerance",
                    ),
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
            slider_style,
            slider_max,
            slider_marks,
            0,
        )

    @app.callback(
        Output("scrubber-layer", "children", allow_duplicate=True),
        Input("sturn-time-slider", "value"),
        State("sturn-hover-store", "data"),
        State("sturn-path-store", "data"),
        prevent_initial_call=True
    )
    def update_s_turn_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position."""
        if not hover_data or not path_data or slider_value is None:
            return []

        idx = int(slider_value)
        if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
            return []

        pt = hover_data[idx]
        pos = path_data[idx]

        # Get segment for display
        segment = pt.get('segment', 'approach')

        # Build tooltip content
        tooltip_content = [
            html.Div(f"{segment.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"GS: {pt.get('gs', 0):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
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
