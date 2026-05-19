"""Rectangular Course edge-preview + edge-info-display + draw + scrubber callbacks.

Inputs: aircraft + environment + two clicked points defining the downwind
leg + pattern parameters. Outputs: map layer with preview line, then the
full simulated pattern path, bounds, info panel, scrubber state.
"""

from __future__ import annotations

import math

from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from callbacks.map import create_airplane_marker

from core.data_loader import aircraft_data, airport_data


_STRAIGHT_LEGS = ("downwind", "base", "upwind", "crosswind")


def _per_leg_wca(hover):
    """Group a Rectangular Course hover list by straight-leg segment and
    return aggregate stats per leg (Phase C3 — ACS Gap 4).

    Skips the entry leg and all turn segments (turn_to_base etc.).
    Returns rows in canonical pattern order: downwind, base, upwind,
    crosswind. Caller renders these as a 4-row mini-table in the info
    accordion."""
    buckets = {leg: {"gs": [], "drift": []} for leg in _STRAIGHT_LEGS}
    for pt in hover:
        seg = pt.get("segment")
        if seg not in buckets:
            continue
        buckets[seg]["gs"].append(float(pt.get("gs", 0)))
        buckets[seg]["drift"].append(float(pt.get("drift", 0)))

    rows = []
    for leg in _STRAIGHT_LEGS:
        gs = buckets[leg]["gs"]
        drift = buckets[leg]["drift"]
        if not gs:
            continue
        rows.append({
            "leg": leg,
            "avg_gs": round(sum(gs) / len(gs), 1),
            "avg_crab": round(sum(drift) / len(drift), 1),
            "max_crab": round(max(abs(d) for d in drift), 1),
        })
    return rows


def register(app):
    """Install Rectangular Course callbacks against the given Dash app."""

    @app.callback(
        Output("rectcourse-calculated-edge", "data"),
        Output("rectcourse-edge-info-display", "children"),
        Output("layer", "children", allow_duplicate=True),
        Input({"type": "point-store", "m_id": "rect_course", "role": "dw_start"}, "data"),
        Input({"type": "point-store", "m_id": "rect_course", "role": "dw_end"}, "data"),
        State("layer", "children"),
        State("maneuver-select", "value"),
        prevent_initial_call=True
    )
    def calculate_rectcourse_edge_and_preview(dw_start, dw_end, layer_children, current_maneuver):
        """
        Calculate the downwind leg length and bearing from two clicked points.
        Draw a preview of the downwind leg on the map.
        """
        from physics import calculate_initial_compass_bearing

        # Only run when rect_course maneuver is selected
        if current_maneuver != "rect_course":
            raise PreventUpdate

        # Remove any existing rectangular course preview
        if layer_children is None:
            layer_children = []

        def should_keep(c):
            if not isinstance(c, dict):
                return True
            el_id = c.get('props', {}).get('id', '')
            # ID can be a string or a dict (for pattern-matching IDs)
            if isinstance(el_id, str) and el_id.startswith('rectcourse-preview'):
                return False
            return True

        layer_children = [c for c in layer_children if should_keep(c)]

        # If we don't have the start point, return defaults
        if not dw_start or not isinstance(dw_start, dict) or dw_start.get('lat') is None:
            return {}, "Click both points to see downwind leg info", layer_children

        start_lat = dw_start['lat']
        start_lon = dw_start['lon']

        # Add start marker — Theme B start (green-500)
        start_marker = dl.CircleMarker(
            id='rectcourse-preview-start',
            center=[start_lat, start_lon],
            radius=8,
            color="#22c55e",
            fill=True,
            fillColor="#22c55e",
            fillOpacity=0.8,
            children=dl.Tooltip("Downwind Start (Entry)")
        )
        layer_children.append(start_marker)

        # If we have both points, calculate edge
        if dw_end and isinstance(dw_end, dict) and dw_end.get('lat') is not None:
            end_lat = dw_end['lat']
            end_lon = dw_end['lon']

            # Calculate bearing from start to end (this is the downwind track)
            from geopy import Point as GeoPoint
            start_geo = GeoPoint(start_lat, start_lon)
            end_geo = GeoPoint(end_lat, end_lon)
            bearing = calculate_initial_compass_bearing(start_geo, end_geo)
            bearing = round(bearing, 1)

            # Calculate distance
            ft_per_deg_lat = 364567.2
            ft_per_deg_lon = 364567.2 * math.cos(math.radians(start_lat))
            dn = (end_lat - start_lat) * ft_per_deg_lat
            de = (end_lon - start_lon) * ft_per_deg_lon
            dist_ft = math.hypot(dn, de)
            dist_nm = dist_ft / 6076.12

            # Midpoint of downwind leg
            mid_lat = (start_lat + end_lat) / 2
            mid_lon = (start_lon + end_lon) / 2

            # Theme B downwind preview — path-active dashed
            edge_line = dl.Polyline(
                id='rectcourse-preview-edge',
                positions=[[start_lat, start_lon], [end_lat, end_lon]],
                color="#0d59f2",
                weight=2,
                opacity=0.65,
                dashArray="6,6",
                children=dl.Tooltip(f"Downwind Leg: {dist_nm:.2f} nm, Track {bearing:.0f}°")
            )

            # Theme B downwind end — end (red-500)
            end_marker = dl.CircleMarker(
                id='rectcourse-preview-end',
                center=[end_lat, end_lon],
                radius=8,
                color="#ef4444",
                fill=True,
                fillColor="#ef4444",
                fillOpacity=0.8,
                children=dl.Tooltip("Downwind End")
            )

            # Theme B midpoint — intermediate (amber-500)
            mid_marker = dl.CircleMarker(
                id='rectcourse-preview-center',
                center=[mid_lat, mid_lon],
                radius=5,
                color="#f59e0b",
                fill=True,
                fillColor="#f59e0b",
                fillOpacity=0.8,
                children=dl.Tooltip("Downwind Midpoint")
            )

            layer_children.extend([edge_line, end_marker, mid_marker])

            # Store calculated values
            edge_data = {
                "start_lat": start_lat,
                "start_lon": start_lon,
                "end_lat": end_lat,
                "end_lon": end_lon,
                "mid_lat": mid_lat,
                "mid_lon": mid_lon,
                "bearing": bearing,
                "length_nm": round(dist_nm, 3),
                "length_ft": round(dist_ft, 0),
            }

            edge_info = [
                html.Span("Downwind Length: ", style={"fontWeight": "bold"}),
                html.Span(f"{dist_nm:.2f} nm"),
                html.Span(" | Track: ", style={"fontWeight": "bold", "marginLeft": "15px"}),
                html.Span(f"{bearing:.0f}°"),
            ]
            return edge_data, edge_info, layer_children
        else:
            # Only start point set
            return {}, "Start point set - click end point", layer_children

    @app.callback(
        Output("rectcourse-edge-visible-info", "children"),
        Input("rectcourse-calculated-edge", "data"),
        prevent_initial_call=True
    )
    def update_rectcourse_edge_visible_info(edge_data):
        """Update the visible edge info display from the calculated edge Store."""
        if not edge_data or not isinstance(edge_data, dict):
            return "Click both points to see downwind leg info"

        length_nm = edge_data.get("length_nm")
        bearing = edge_data.get("bearing")

        if length_nm is not None and bearing is not None:
            return [
                html.Span("Downwind Length: ", style={"fontWeight": "bold"}),
                html.Span(f"{length_nm:.2f} nm"),
                html.Span(" | Track: ", style={"fontWeight": "bold", "marginLeft": "15px"}),
                html.Span(f"{bearing:.0f}°"),
            ]

        return "Click both points to see downwind leg info"

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("rectcourse-info", "children"),
        Output("rectcourse-hover-store", "data"),
        Output("rectcourse-path-store", "data"),
        Output("rectcourse-warnings-store", "data"),
        Output("rectcourse-slider-container", "style"),
        Output("rectcourse-time-slider", "max"),
        Output("rectcourse-time-slider", "marks"),
        Output("rectcourse-time-slider", "value"),
        Input("rectcourse-draw-btn", "n_clicks"),
        State("rectcourse-calculated-edge", "data"),
        State("rectcourse-altitude", "value"),
        State("rectcourse-ias", "value"),
        State("rectcourse-width", "value"),
        State("rectcourse-direction", "value"),
        State("rectcourse-circuits", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("power-setting", "value"),
        State("cg-slider", "value"),
        State("layer", "children"),
        prevent_initial_call=True
    )
    def draw_rectangular_course(
        n_clicks,
        edge_data,
        altitude_ft,
        ias_knots,
        lateral_offset,
        pattern_direction,
        num_circuits,
        oat_f,
        altimeter_inhg,
        wind_dir,
        wind_speed,
        aircraft_name,
        selected_airport_id,
        runtime_weight,
        power_setting,
        cg_position,
        layer_children,
    ):
        # Check we have the edge data from the two-click selection
        if not n_clicks or not edge_data or not edge_data.get('start_lat'):
            raise PreventUpdate

        # Remove preview markers from layer
        if layer_children is None:
            layer_children = []

        def should_keep(c):
            if not isinstance(c, dict):
                return True
            el_id = c.get('props', {}).get('id', '')
            if isinstance(el_id, str) and el_id.startswith('rectcourse-preview'):
                return False
            # Also remove the click markers for rect_course
            if isinstance(el_id, dict) and el_id.get('m_id') == 'rect_course':
                return False
            return True

        layer_children = [c for c in layer_children if should_keep(c)]

        # Extract downwind leg endpoints from the two clicks
        dw_start = {"lat": edge_data['start_lat'], "lon": edge_data['start_lon']}
        dw_end = {"lat": edge_data['end_lat'], "lon": edge_data['end_lon']}
        dw_length_nm = edge_data.get('length_nm', 0.5)
        dw_track = edge_data.get('bearing', 0.0)

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
        ias = float(ias_knots) if ias_knots not in [None, "", "null"] else 95.0
        lateral_nm = float(lateral_offset) if lateral_offset not in [None, "", "null"] else 0.25
        direction = str(pattern_direction) if pattern_direction not in [None, "", "null"] else "left"
        circuits = int(num_circuits) if num_circuits not in [None, "", "null"] else 1

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
        from simulation import simulate_rectangular_course
        path, hover, sim_warnings = simulate_rectangular_course(
            dw_start=dw_start,
            dw_end=dw_end,
            lateral_offset_nm=lateral_nm,
            pattern_direction=direction,
            altitude_ft=altitude,
            ias_knots=ias,
            num_circuits=circuits,
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

        # Theme B entry/exit (green-500)
        elements = [path_line]
        if path:
            entry_marker = dl.CircleMarker(
                center=path[0],
                radius=7,
                color="#22c55e",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip(f"45° Entry/Exit: {altitude:.0f} ft AGL"),
            )
            elements.append(entry_marker)

        # Info display
        info_elements = []

        # Warnings section
        has_warnings = (
            sim_warnings.get("stall_margin_warning") or
            sim_warnings.get("g_limit_warning") or
            sim_warnings.get("airspeed_warning")
        )
        if has_warnings:
            warning_items = []
            if sim_warnings.get("airspeed_warning"):
                warning_items.append(html.Div(f"Airspeed: {sim_warnings['airspeed_warning']}"))
            if sim_warnings.get("stall_margin_warning"):
                warning_items.append(html.Div("Low stall margin in turns"))
            if sim_warnings.get("g_limit_warning"):
                warning_items.append(html.Div("G-limit warning in turns"))

            info_elements.append(
                html.Div(warning_items, style={"color": "#856404", "backgroundColor": "#fff3cd", "padding": "8px", "borderRadius": "4px", "marginBottom": "5px"})
            )

        # Calculate stall margins
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

        # Phase C3 — ACS Gap 4 — per-leg WCA breakdown table.
        per_leg = _per_leg_wca(hover)
        per_leg_table = html.Table([
            html.Thead(html.Tr([
                html.Th("Leg"),
                html.Th("GS (kt)"),
                html.Th("Crab (°)"),
                html.Th("Max crab"),
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(row["leg"].title()),
                    html.Td(f"{row['avg_gs']:.0f}"),
                    html.Td(f"{row['avg_crab']:+.1f}"),
                    html.Td(f"{row['max_crab']:.1f}"),
                ])
                for row in per_leg
            ]),
        ], className="rect-per-leg-table", style={"width": "100%", "marginTop": "4px"}) if per_leg else None

        # Performance data - standardized format
        info_elements.append(
            dbc.Accordion([
                dbc.AccordionItem([
                    html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb | IAS: {ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {sim_warnings.get('wind_dir', 0):.0f}°/{sim_warnings.get('wind_speed', 0):.0f} kt", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"AOB: {sim_warnings.get('min_bank_achieved', 0):.0f}-{max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {sim_warnings.get('min_groundspeed', 0):.0f}-{sim_warnings.get('max_groundspeed', 0):.0f} kt", style={"fontSize": "11px"}),
                    html.Div(f"DW: {dw_length_nm:.2f} nm | Lateral: {lateral_nm:.2f} nm | Crab: {sim_warnings.get('max_crab_angle', 0):.1f}°", style={"fontSize": "11px"}),
                    per_leg_table,
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"Vs turn: {vs_in_turn:.0f} kt | Margin: {min_ias_achieved - vs_in_turn:.0f} kt | Time: {sim_warnings.get('total_time_sec', 0):.0f}s", style={"fontSize": "11px"}),
                    html.Div(f"{direction.title()} pattern | {circuits} circuits", style={"fontSize": "11px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
            ], start_collapsed=False, style={"marginTop": "8px"})
        )

        # Slider configuration
        num_points = len(hover)
        slider_max = max(0, num_points - 1)
        slider_marks = {0: "Start"}
        if slider_max > 0:
            slider_marks[slider_max] = "End"
        slider_style = {"display": "block", "marginTop": "10px"}

        # Calculate bounds for auto-zoom
        if path:
            lats = [p[0] for p in path]
            lons = [p[1] for p in path]
            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
        else:
            bounds = None

        # Combine cleaned layer (without preview) with new elements
        final_layer = layer_children + elements

        return (
            final_layer,
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
        Input("rectcourse-time-slider", "value"),
        State("rectcourse-hover-store", "data"),
        State("rectcourse-path-store", "data"),
        prevent_initial_call=True
    )
    def update_rectangular_course_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position."""
        if not hover_data or not path_data or slider_value is None:
            return []

        idx = int(slider_value)
        if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
            return []

        pt = hover_data[idx]
        pos = path_data[idx]

        # Get segment for display
        segment = pt.get('segment', 'downwind')
        if segment.startswith('turn_'):
            segment_display = segment.replace('_', ' ').title()
        else:
            segment_display = segment.title() + " Leg"

        # Build tooltip content
        tooltip_content = [
            html.Div(f"{segment_display}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Circuit: {pt.get('circuit', 1)}"),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"GS: {pt.get('gs', 0):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Crab: {pt.get('crab', '0°')}"),
        ]

        # Create airplane marker pointing in direction of heading
        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        # Parse crab from string format like "5.2°R" or "3.1°L" to numeric
        crab_str = pt.get('crab', '0°')
        try:
            crab_val = float(crab_str.replace('°', '').replace('R', '').replace('L', ''))
            if 'L' in crab_str:
                crab_val = -crab_val
        except Exception:
            crab_val = 0
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab_val)

        return [marker]
