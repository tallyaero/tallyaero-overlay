"""Power-Off 180 draw + scrubber callbacks.

Inputs: aircraft + environment + runway geometry + pattern parameters.
Outputs: map layer with path, bounds, info panel, time-scrubber state.
"""

from __future__ import annotations

from dash import html, Input, Output, State
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.log import get_logger

from callbacks.map import create_airplane_marker

import app as app_module

log = get_logger(__name__)


def register(app):
    """Install Power-Off 180 callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output({"type": "click-status", "m_id": "poweroff180"}, "children", allow_duplicate=True),
        Output("poweroff180-hover-store", "data"),
        Output("poweroff180-path-store", "data"),
        Output("poweroff180-slider-container", "style"),
        Output("poweroff180-time-slider", "max"),
        Output("poweroff180-time-slider", "marks"),
        Output("poweroff180-time-slider", "value"),
        Output("poweroff180-info", "children"),
        Input("poweroff180-draw-btn", "n_clicks"),
        State({"type": "point-store", "m_id": "poweroff180", "role": "touchdown"}, "data"),
        State("poweroff180-runway-select", "value"),
        State("poweroff180-manual-heading", "value"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("poweroff180-altitude", "value"),
        State("poweroff180-pattern", "value"),
        State("poweroff180-flap-setting", "value"),
        State("poweroff180-prop-condition", "value"),
        State("poweroff180-abeam-distance-nm", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        prevent_initial_call=True
    )
    def draw_poweroff180(
        n_clicks,
        touchdown_data,
        runway_select,
        manual_heading,
        ac_name,
        engine_key,
        wind_dir,
        wind_speed,
        oat_f,
        altimeter,
        pattern_alt_agl,
        pattern_dir,
        flap_setting,
        prop_condition,
        abeam_distance_nm,
        selected_airport_id,
        runtime_weight
    ):
        """Draw Power-Off 180 accuracy approach using energy-based simulation."""
        from simulation import simulate_power_off_180

        aircraft_data = app_module.aircraft_data
        airport_data = app_module.airport_data

        if not n_clicks:
            return [], None, "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

        if not ac_name or not engine_key:
            return [], None, "⚠️ Select aircraft and engine first.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

        # Touchdown point is always required (user clicks on runway)
        if not touchdown_data:
            return [], None, "⚠️ Click 'Set Touchdown Point' then click on the runway where you want to land.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

        try:
            # Get airport data for elevation
            selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
            elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

            # Touchdown point from user click
            runway_threshold = touchdown_data
            runway_length_ft = 5000.0

            # Get runway heading from dropdown or manual input
            runway_heading = None

            if selected_airport_id and runway_select and selected_airport:
                # Get heading from selected runway
                runways = selected_airport.get("runways", [])
                runway = next((r for r in runways if r.get("id") == runway_select), None)
                if runway:
                    runway_heading = runway.get("heading")
                    runway_length_ft = runway.get("length_ft", 5000.0)

            # Fallback to manual heading
            if runway_heading is None:
                if manual_heading:
                    runway_heading = float(manual_heading)
                else:
                    return [], None, "⚠️ Select a runway or enter manual heading.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

            # Get values
            pattern_alt = float(pattern_alt_agl) if pattern_alt_agl else 1000.0
            abeam_dist = float(abeam_distance_nm) if abeam_distance_nm else 0.5
            wind_dir_val = float(wind_dir) if wind_dir else 0.0
            wind_speed_val = float(wind_speed) if wind_speed else 0.0
            oat_c = ((float(oat_f) if oat_f else 59.0) - 32.0) * 5.0 / 9.0
            altimeter_val = float(altimeter) if altimeter else 29.92

            total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None
            if total_wt is None:
                ac_data = aircraft_data.get(ac_name, {})
                total_wt = ac_data.get("max_takeoff_weight", ac_data.get("gross_weight", 2500.0))

            # Get aircraft data
            ac = dict(aircraft_data[ac_name])
            ac["total_weight_lb"] = float(total_wt)

            # Run simulation
            path, hover_data, results = simulate_power_off_180(
                runway_threshold=runway_threshold,
                runway_heading_deg=float(runway_heading),
                runway_length_ft=float(runway_length_ft),
                abeam_distance_nm=abeam_dist,
                pattern_direction=pattern_dir or "left",
                ac=ac,
                weight_lbs=float(total_wt),
                flap_config=flap_setting or "clean",
                prop_config=prop_condition or "idle",
                oat_c=oat_c,
                altimeter_inhg=altimeter_val,
                wind_dir_deg=wind_dir_val,
                wind_speed_kt=wind_speed_val,
                field_elev_ft=elev_ft,
                pattern_altitude_agl=pattern_alt,
                timestep_sec=0.5,
            )

            if not path or not hover_data:
                return [], None, "⚠️ No glide path generated. Check inputs.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

            # Build map elements
            elements = []

            # Main path
            path_line = dl.Polyline(positions=path, color="red", weight=3)
            elements.append(path_line)

            # Start marker (abeam position)
            if path:
                start_marker = dl.CircleMarker(
                    center=path[0],
                    radius=7,
                    color="green",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip("Abeam (Power Off)")
                )
                elements.append(start_marker)

            # Touchdown/Aim marker
            aim_marker = dl.CircleMarker(
                center=[runway_threshold['lat'], runway_threshold['lon']],
                radius=7,
                color="blue",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip(f"Runway {runway_select or 'threshold'}")
            )
            elements.append(aim_marker)

            # Impact marker if failed
            impact_point = results.get('impact_point')
            if impact_point:
                impact_marker = dl.CircleMarker(
                    center=impact_point,
                    radius=8,
                    color="black",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip(f"Impact: {results.get('touchdown_error_ft', 0):.0f} ft short")
                )
                elements.append(impact_marker)

            # Build status message
            success = results.get('success', False)
            td_error = results.get('touchdown_error_ft', 0)

            if success:
                if td_error == 0:
                    msg = "✅ SUCCESS - Touchdown on target!"
                else:
                    msg = f"✅ SUCCESS - Touchdown +{td_error:.0f} ft (within ACS -0/+200)"
            else:
                if td_error < 0:
                    msg = f"❌ FAILED - SHORT by {abs(td_error):.0f} ft"
                else:
                    msg = f"❌ FAILED - LONG by {td_error:.0f} ft (exceeds +200)"

            # Calculate bounds
            lats = [pt[0] for pt in path] + [runway_threshold['lat']]
            lons = [pt[1] for pt in path] + [runway_threshold['lon']]
            if impact_point:
                lats.append(impact_point[0])
                lons.append(impact_point[1])
            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

            # Slider setup
            max_time = hover_data[-1]["time"] if hover_data else 100
            slider_marks = {0: "Start", int(max_time): "End"}

            # Prepare hover store with slip data
            hover_store = [
                {
                    "time": pt.get("time", 0),
                    "alt": pt.get("alt", 0),
                    "ias": pt.get("ias", 0),
                    "tas": pt.get("tas", 0),
                    "gs": pt.get("gs", 0),
                    "aob": pt.get("aob", 0),
                    "vs": pt.get("vs", 0),
                    "track": pt.get("track", 0),
                    "heading": pt.get("heading", 0),
                    "drift": pt.get("drift", 0),
                    "segment": pt.get("segment", ""),
                    "slip_active": pt.get("slip_active", False),
                    "slip_intensity": pt.get("slip_intensity", 0),
                }
                for pt in hover_data
            ]

            # Build info panel with slip reporting
            slip_used = results.get('slip_used', False)
            slip_pct = results.get('slip_intensity_pct', 0)
            best_glide = results.get('best_glide_kias', 0)
            base_gr = results.get('base_glide_ratio', 0)
            eff_gr = results.get('effective_glide_ratio', base_gr)
            max_bank = results.get('max_bank_deg', 0)
            headwind = results.get('headwind_on_final_kt', 0)
            crosswind = results.get('crosswind_on_final_kt', 0)
            xwind_dir = results.get('crosswind_direction', 'none')

            # Success/Failure banner
            if success:
                result_banner = html.Div(
                    f"✅ SUCCESSFUL - Touchdown {'+' if td_error >= 0 else ''}{td_error:.0f} ft",
                    style={"fontWeight": "bold", "color": "#28a745", "marginBottom": "8px", "fontSize": "12px"}
                )
            else:
                result_banner = html.Div(
                    f"❌ {'SHORT' if td_error < 0 else 'LONG'} - {abs(td_error):.0f} ft {'before' if td_error < 0 else 'beyond'} target",
                    style={"fontWeight": "bold", "color": "#dc3545", "marginBottom": "8px", "fontSize": "12px"}
                )

            # Slip info section
            if slip_used:
                slip_section = [
                    html.Div([html.Strong("Forward Slip Applied")], style={"marginBottom": "4px", "color": "#fd7e14"}),
                    html.Div(f"Intensity: {slip_pct:.0f}%", style={"fontSize": "11px"}),
                    html.Div(f"Glide ratio reduced: {base_gr:.1f}:1 → {eff_gr:.1f}:1", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                ]
            else:
                slip_section = [
                    html.Div("No slip required", style={"fontSize": "11px", "color": "#28a745"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                ]

            info_content = dbc.Accordion([
                dbc.AccordionItem([
                    result_banner,
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    html.Div([html.Strong("Aircraft Performance")], style={"marginBottom": "4px"}),
                    html.Div(f"Best Glide: {best_glide:.0f} KIAS | Weight: {total_wt:.0f} lb", style={"fontSize": "11px"}),
                    html.Div(f"Glide Ratio: {base_gr:.1f}:1 | Max Bank: {max_bank:.1f}°", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    *slip_section,

                    html.Div([html.Strong("Wind Analysis")], style={"marginBottom": "4px"}),
                    html.Div(f"Wind: {wind_dir_val:.0f}° at {wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                    html.Div(f"On Final: {'Headwind' if headwind > 0 else 'Tailwind'} {abs(headwind):.0f} kt | Crosswind {crosswind:.0f} kt from {xwind_dir}", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                    html.Div([html.Strong("Pattern Data")], style={"marginBottom": "4px"}),
                    html.Div(f"Altitude: {pattern_alt:.0f} ft AGL | Abeam: {abeam_dist:.2f} nm", style={"fontSize": "11px"}),
                    html.Div(f"Runway: {runway_heading:.0f}° | {pattern_dir.title()} pattern", style={"fontSize": "11px"}),
                    html.Div(f"Flaps: {flap_setting or 'clean'} | Time: {max_time:.1f}s", style={"fontSize": "11px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
            ], start_collapsed=False, style={"marginTop": "8px"})

            return elements, bounds, msg, hover_store, path, {"display": "block"}, int(max_time), slider_marks, 0, info_content

        except Exception as e:
            import traceback
            log.error(f"EXCEPTION in draw_poweroff180(): {e}")
            traceback.print_exc()
            return [], None, f"⚠️ Error: {str(e)}", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

    @app.callback(
        Output("scrubber-layer", "children", allow_duplicate=True),
        Input("poweroff180-time-slider", "value"),
        State("poweroff180-hover-store", "data"),
        State("poweroff180-path-store", "data"),
        prevent_initial_call=True
    )
    def update_poweroff180_scrubber(slider_value, hover_data, path_data):
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

        segment = pt.get('segment', 'glide')
        slip_pct = pt.get('slip_pct', 0)

        # Build tooltip with slip info (always show slip percentage)
        tooltip_content = [
            html.Div(f"{segment.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
            html.Div(f"Slip: {slip_pct:.0f}%", style={"color": "#fd7e14" if slip_pct > 0 else "#666", "fontWeight": "bold" if slip_pct > 0 else "normal"}),
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]
