"""Eights on Pylons draw + scrubber callbacks.

Inputs: aircraft + environment + two pylon points + bank parameters.
Outputs: map layer with figure-eight path colored by pivotal altitude,
bounds, info panel with PA range, scrubber state.
"""

from __future__ import annotations

import math

from dash import html, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from callbacks.map import create_airplane_marker
from layouts.maneuvers._shared import _acs_metric, _winds_aloft_chip

from core.data_loader import aircraft_data, airport_data
from core.profile3d import build_3d_side_view_block, side_view_accordion_item


def register(app):
    """Install Eights on Pylons callbacks against the given Dash app."""

    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("pylons-info", "children"),
        Output("pylons-hover-store", "data"),
        Output("pylons-path-store", "data"),
        Output("pylons-slider-container", "style"),
        Output("pylons-time-slider", "max"),
        Output("pylons-time-slider", "marks"),
        Output("pylons-time-slider", "value"),
        Input({"type": "draw-btn", "m_id": "pylons"}, "n_clicks"),
        State({"type": "point-store", "m_id": "pylons", "role": "pylon_a"}, "data"),
        State({"type": "point-store", "m_id": "pylons", "role": "pylon_b"}, "data"),
        State("pylons-ias", "value"),
        State("pylons-bank-angle", "value"),
        State("pylons-num-eights", "value"),
        State("pylons-entry-direction", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("power-setting", "value"),
        State("cg-slider", "value"),
        State("layer", "children"),
        State("wind-profile-store", "data"),
        prevent_initial_call=True
    )
    def draw_eights_on_pylons(
        n_clicks,
        pylon_a_data,
        pylon_b_data,
        ias_knots,
        bank_angle,
        num_eights,
        entry_direction,
        oat_f,
        altimeter_inhg,
        wind_dir,
        wind_speed,
        aircraft_name,
        engine_name,
        selected_airport_id,
        runtime_weight,
        power_setting,
        cg_position,
        layer_children,
        wind_profile_data,
    ):
        """Draw Eights on Pylons with integrated pivotal altitude calculator."""
        if not n_clicks:
            raise PreventUpdate

        # Validate we have both pylons
        if not pylon_a_data or not pylon_b_data:
            return (
                layer_children or [],
                None,  # bounds
                html.Div("Please set both pylon locations first.", style={"color": "red"}),
                [], [], {"display": "none"}, 0, {}, 0
            )

        pylon1 = {"lat": pylon_a_data.get("lat"), "lon": pylon_a_data.get("lon")}
        pylon2 = {"lat": pylon_b_data.get("lat"), "lon": pylon_b_data.get("lon")}

        if not pylon1.get("lat") or not pylon2.get("lat"):
            return (
                layer_children or [],
                None,  # bounds
                html.Div("Please set both pylon locations first.", style={"color": "red"}),
                [], [], {"display": "none"}, 0, {}, 0
            )

        # Remove existing pylon markers from layer
        if layer_children is None:
            layer_children = []

        def should_keep(c):
            if not isinstance(c, dict):
                return True
            el_id = c.get('props', {}).get('id', '')
            if isinstance(el_id, dict) and el_id.get('m_id') == 'pylons':
                return False
            return True

        layer_children = [c for c in layer_children if should_keep(c)]

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
        ias = float(ias_knots) if ias_knots not in [None, "", "null"] else 100.0
        bank_deg = float(bank_angle) if bank_angle not in [None, "", "null"] else 30.0
        n_eights = int(num_eights) if num_eights not in [None, "", "null"] else 1
        entry_dir = str(entry_direction) if entry_direction not in [None, "", "null"] else "downwind"
        # Design Directive — design power is cruise (0.625). Parsed once so
        # both the sim call and the D2 verdict chip share the value.
        try:
            power_pct = float(power_setting) if power_setting not in [None, "", "null"] else 0.625
        except (TypeError, ValueError):
            power_pct = 0.625

        # OAT F -> C
        try:
            oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0
        except Exception:
            oat_c = (52.0 - 32.0) * 5.0 / 9.0

        # Get airport elevation
        selected_airport_elev_ft = 0.0
        if selected_airport_id:
            ap = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
            if ap:
                selected_airport_elev_ft = ap.get("elevation_ft", 0.0)

        # Hydrate live winds-aloft column when staged.
        wind_profile = None
        if wind_profile_data:
            try:
                from core.winds_aloft import WindProfile
                wind_profile = WindProfile.from_store(wind_profile_data)
            except Exception:
                wind_profile = None

        # Run simulation
        from simulation import simulate_eights_on_pylons
        path, hover, sim_warnings = simulate_eights_on_pylons(
            pylon1=pylon1,
            pylon2=pylon2,
            ias_knots=ias,
            num_eights=n_eights,
            wind_dir_deg=float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0,
            wind_speed_kt=float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0,
            oat_c=oat_c,
            altimeter_inhg=float(altimeter_inhg) if altimeter_inhg not in [None, "", "null"] else 29.92,
            field_elev_ft=selected_airport_elev_ft,
            ac=ac,
            weight_lb=weight_lb,
            power_setting=power_pct,
            cg_position=float(cg_position) if cg_position not in [None, "", "null"] else 0.5,
            bank_angle_deg=bank_deg,
            entry_direction=entry_dir,
            wind_profile=wind_profile,
            engine_option=engine_name,
        )

        if not path:
            return (
                layer_children,
                None,  # bounds
                html.Div("Failed to generate path. Check inputs.", style={"color": "red"}),
                [], [], {"display": "none"}, 0, {}, 0
            )

        # Build path segments with pivotal altitude-based coloring
        # Lower PA (upwind, slower) = red, Higher PA (downwind, faster) = blue
        min_pa = sim_warnings.get('pivotal_alt_min', 800)
        max_pa = sim_warnings.get('pivotal_alt_max', 900)
        pa_range = max(max_pa - min_pa, 1)  # Avoid division by zero

        def pa_to_color(pa):
            """Map pivotal altitude to color: low=red, high=blue"""
            # Normalize to 0-1 range
            t = (pa - min_pa) / pa_range
            t = max(0, min(1, t))  # Clamp to [0, 1]
            # Interpolate from red (low) to blue (high)
            r = int(255 * (1 - t))
            g = int(100 * (1 - abs(t - 0.5) * 2))  # Green peaks in middle
            b = int(255 * t)
            return f"#{r:02x}{g:02x}{b:02x}"

        # Create colored path segments
        path_segments = []
        for i in range(len(path) - 1):
            if i < len(hover):
                pa = hover[i].get('pivotal_alt', hover[i].get('alt', min_pa))
                color = pa_to_color(pa)
            else:
                color = "#888888"

            path_segments.append(
                dl.Polyline(
                    positions=[path[i], path[i + 1]],
                    color=color,
                    weight=4,
                )
            )

        # Pylon markers
        pylon_markers = [
            dl.CircleMarker(
                center=[pylon1['lat'], pylon1['lon']],
                radius=8,
                color='#e74c3c',
                fill=True,
                fillColor='#e74c3c',
                fillOpacity=0.8,
                children=dl.Tooltip("Pylon 1")
            ),
            dl.CircleMarker(
                center=[pylon2['lat'], pylon2['lon']],
                radius=8,
                color='#3498db',
                fill=True,
                fillColor='#3498db',
                fillOpacity=0.8,
                children=dl.Tooltip("Pylon 2")
            ),
        ]

        elements = path_segments + pylon_markers

        # Build warnings if any
        warning_elements = []

        # ACS pylon-spacing — most actionable. Surface FIRST so it isn't
        # lost below other warnings. Error tier means the geometry is
        # invalid; the sim still draws a path but transitions will snap.
        spacing_tier = sim_warnings.get("pylon_spacing_tier", "ok")
        if spacing_tier == "error":
            warning_elements.append(html.Div(
                [
                    html.Strong("Pylon spacing invalid — "),
                    html.Span(sim_warnings.get("pylon_spacing_error", "")),
                    html.Br(),
                    html.Span(
                        f"Ideal: {sim_warnings.get('pylon_spacing_ideal_min_nm', 0):.2f}–"
                        f"{sim_warnings.get('pylon_spacing_ideal_max_nm', 0):.2f} NM "
                        f"(for {sim_warnings.get('turn_radius_nm', 0):.2f} NM turn radius).",
                        style={"fontSize": "11px", "opacity": 0.95},
                    ),
                ],
                style={
                    "color": "white",
                    "backgroundColor": "var(--ta-path-fail, #dc2626)",
                    "padding": "8px 10px",
                    "borderRadius": "4px",
                    "marginBottom": "6px",
                    "fontSize": "12px",
                    "lineHeight": "1.35",
                },
            ))
        elif spacing_tier == "warning":
            warning_elements.append(html.Div(
                [
                    html.Strong("Pylon spacing — "),
                    html.Span(sim_warnings.get("pylon_spacing_warning", "")),
                ],
                style={
                    "borderLeft": "3px solid var(--acs-marginal, #f59e0b)",
                    "color": "var(--acs-marginal, #f59e0b)",
                    "padding": "4px 8px",
                    "marginBottom": "6px",
                    "fontSize": "11px",
                    "backgroundColor": "rgba(245, 158, 11, 0.05)",
                },
            ))

        if sim_warnings.get("airspeed_warning"):
            warning_elements.append(html.Div(f"Warning: {sim_warnings['airspeed_warning']}", style={"color": "#c0392b", "fontWeight": "bold"}))
        if sim_warnings.get("bank_limited"):
            warning_elements.append(html.Div("AOB limited to 40° (ACS maximum)", style={"color": "#e67e22"}))
        if sim_warnings.get("stall_margin_warning"):
            warning_elements.append(html.Div("Warning: Stall margin below 1.2", style={"color": "#c0392b"}))
        # ACS compliance warnings
        if sim_warnings.get("pylon_distance_warning"):
            warning_elements.append(html.Div(f"{sim_warnings['pylon_distance_warning']}", style={"color": "#e67e22"}))
        if sim_warnings.get("transition_time_warning"):
            warning_elements.append(html.Div(f"ℹ {sim_warnings['transition_time_warning']}", style={"color": "#3498db"}))

        # Phase C8f — min/max safe altitude warning. The standard ACS
        # Eights on Pylons targets 600-1000 ft AGL pivotal altitude. PA
        # outside that range means the chosen IAS yields a PA the pilot
        # can't actually fly safely (too low = obstacles/regulation, too
        # high = no longer the standard maneuver).
        pa_avg = float(sim_warnings.get("pivotal_alt_avg", 0))
        if pa_avg > 0 and (pa_avg < 600 or pa_avg > 1000):
            if pa_avg < 600:
                tip = "increase IAS to lift PA into 600-1000 ft band"
            else:
                tip = "reduce IAS to lower PA into 600-1000 ft band"
            warning_elements.append(html.Div(
                f"PA avg {pa_avg:.0f} ft outside typical 600-1000 AGL — {tip}",
                style={
                    "borderLeft": "3px solid var(--acs-marginal, #f59e0b)",
                    "color": "var(--acs-marginal, #f59e0b)",
                    "padding": "4px 8px",
                    "marginBottom": "6px",
                    "fontSize": "11px",
                    "backgroundColor": "rgba(245, 158, 11, 0.05)",
                },
            ))

        # Stall references — sim surfaces real values post-audit (was
        # falling back to hardcoded 48 because the key was never emitted).
        vs_clean = sim_warnings.get('vs_clean_kt', sim_warnings.get('stall_speed_clean', 48))
        vs_in_turn = sim_warnings.get('vs_at_max_bank_kt', sim_warnings.get('stall_speed_in_turn', vs_clean))
        min_ias_achieved = sim_warnings.get('min_ias_achieved', ias)
        max_bank = sim_warnings.get('max_bank_achieved', 0)
        load_factor = 1 / math.cos(math.radians(float(max_bank))) if max_bank > 0 else 1.0
        stall_margin = min_ias_achieved - vs_in_turn

        # Calculate avg TAS from hover data
        if hover:
            tas_values = [pt.get('tas', pt.get('ias', 0)) for pt in hover]
            avg_tas = sum(tas_values) / len(tas_values) if tas_values else ias
        else:
            avg_tas = ias

        # Build info panel - standardized format with pivotal altitude prominent
        info_children = []

        if warning_elements:
            info_children.append(html.Div(warning_elements, style={"marginBottom": "8px"}))

        # Compact accordion for results
        info_children.append(
            dbc.Accordion([
                dbc.AccordionItem([
                    html.Div([html.Strong("Pivotal Altitude", style={"color": "#27ae60"})], style={"marginBottom": "4px"}),
                    html.Div(f"PA: {sim_warnings.get('pivotal_alt_min', 0):.0f}-{sim_warnings.get('pivotal_alt_max', 0):.0f} ft (avg {sim_warnings.get('pivotal_alt_avg', 0):.0f}, range {sim_warnings.get('pivotal_alt_range', 0):.0f} ft)", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb | IAS: {sim_warnings.get('ias_knots', 0):.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {sim_warnings.get('wind_dir', 0):.0f}°/{sim_warnings.get('wind_speed', 0):.0f} kt", style={"fontSize": "11px"}),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(f"AOB: {sim_warnings.get('min_bank_achieved', 0):.0f}-{max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {sim_warnings.get('min_groundspeed', 0):.0f}-{sim_warnings.get('max_groundspeed', 0):.0f} kt", style={"fontSize": "11px"}),
                    html.Div(
                        f"Pylon sep: {sim_warnings.get('pylon_distance_nm', 0):.2f} nm "
                        f"({sim_warnings.get('pylon_distance_ft', 0):.0f} ft) "
                        f"| Trans: {sim_warnings.get('transition_time_avg_sec', 0):.1f}s",
                        style={"fontSize": "11px"},
                        title="Pylon separation in NM and ft. ACS Commercial expects "
                              "the pilot to choose pylons spaced appropriately for the "
                              "chosen pivotal altitude (typically 0.4-0.7 NM at GA IAS).",
                    ),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(
                        f"Vs(clean): {vs_clean:.0f} → Vs×√n at {max_bank:.0f}°: {vs_in_turn:.0f} kt | Time: {sim_warnings.get('total_time_sec', 0):.0f}s | {n_eights} eights",
                        style={"fontSize": "11px"},
                    ),
                    html.Div(
                        f"Stall margin: {stall_margin:+.0f} kt",
                        style={
                            "fontSize": "11px",
                            "color": (
                                "#dc2626" if stall_margin < 4
                                else "#f59e0b" if stall_margin < 8
                                else "#16a34a"
                            ),
                            "fontWeight": "500",
                        },
                    ),
                    html.Div([
                        html.Span("Color: ", style={"fontSize": "10px"}),
                        html.Span("■ Low PA", style={"color": "#ff0000", "fontSize": "10px", "marginRight": "6px"}),
                        html.Span("■ Mid", style={"color": "#804080", "fontSize": "10px", "marginRight": "6px"}),
                        html.Span("■ High PA", style={"color": "#0000ff", "fontSize": "10px"}),
                    ], style={"marginTop": "4px"}),
                    # Phase C9 — Commercial ACS tolerances.
                    html.Div([
                        _acs_metric("Heading", 0, "°", target=0, tol=10, cert_level="commercial"),
                    ], style={"display": "flex", "flexWrap": "wrap", "marginTop": "6px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
                # 3D Side View — the two reference pylons rise from the
                # ground (field elevation) up to the pivotal altitude so
                # the pilot can see the geometric relationship between
                # the aircraft's orbit and the pylons in 3-space. The
                # wing tip "points at" the pylon all the way around.
                side_view_accordion_item(
                    build_3d_side_view_block(
                        path=path,
                        hover=hover,
                        elev_ft=float(selected_airport_elev_ft or 0.0),
                        vertical_features=[
                            {
                                "lat": pylon1["lat"],
                                "lon": pylon1["lon"],
                                "alt_ft_base": float(selected_airport_elev_ft or 0.0),
                                # Pylon top at the maneuver's average
                                # pivotal altitude (MSL): field elev +
                                # average PA. This makes the pole
                                # visibly extend to the aircraft's
                                # orbit altitude.
                                "alt_ft_top": float(selected_airport_elev_ft or 0.0)
                                              + float(sim_warnings.get("pivotal_alt_avg", 800) or 800),
                                "label": "Pylon 1",
                                "color": "#e74c3c",  # red — matches map marker
                            },
                            {
                                "lat": pylon2["lat"],
                                "lon": pylon2["lon"],
                                "alt_ft_base": float(selected_airport_elev_ft or 0.0),
                                "alt_ft_top": float(selected_airport_elev_ft or 0.0)
                                              + float(sim_warnings.get("pivotal_alt_avg", 800) or 800),
                                "label": "Pylon 2",
                                "color": "#3498db",  # blue — matches map marker
                            },
                        ],
                    )
                ),
            ], start_collapsed=False, style={"marginTop": "8px"})
        )

        # Live winds-aloft chip — parity with other maneuvers.
        chip = _winds_aloft_chip(wind_profile_data)
        if chip is not None:
            info_children.append(chip)

        info_elements = html.Div(info_children)

        # Time-based scrubber with segment markers. Walks the hover stream
        # and records the first time each segment appears. Pylon-orbit
        # segments are emitted by the sim as "pylon_1_entry", "pylon_1",
        # "pylon_2", "transition_p1_to_p2", "transition_p2_to_p1".
        SEG_LABELS = {
            "entry": "Entry",
            "pylon_1_entry": "P1",
            "pylon_1": "P1",
            "pylon_2": "P2",
            "transition_p1_to_p2": "→P2",
            "transition_p2_to_p1": "→P1",
        }
        max_time = hover[-1].get("time", 0) if hover else 0
        slider_marks = {0: "Start"}
        prev_label = None
        for pt in hover:
            seg = pt.get("segment", "")
            label = SEG_LABELS.get(seg, seg.replace("_", " ").title())
            # Avoid stamping the same label twice in a row at the same second.
            t_mark = int(round(float(pt.get("time", 0))))
            if label != prev_label and t_mark not in slider_marks:
                slider_marks[t_mark] = label
                prev_label = label
        slider_marks[int(round(max_time))] = "End"
        slider_max = int(round(max_time)) if max_time > 0 else 100
        slider_style = {"display": "block", "marginTop": "10px"}

        # Calculate bounds for auto-zoom
        if path:
            lats = [p[0] for p in path]
            lons = [p[1] for p in path]
            bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
        else:
            bounds = None

        final_layer = layer_children + elements

        return (
            final_layer,
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
        Input("pylons-time-slider", "value"),
        State("pylons-hover-store", "data"),
        State("pylons-path-store", "data"),
        prevent_initial_call=True
    )
    def update_eights_on_pylons_scrubber(slider_value, hover_data, path_data):
        """Update the scrubber marker and tooltip based on slider position.

        Time-based lookup so segment marks (P1 / →P2 / P2 / …) land on
        actual transition ticks regardless of timestep granularity."""
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

        # Get segment for display
        segment = pt.get('segment', 'pylon_1')
        if 'pylon_1' in segment:
            segment_display = "Pylon 1 Orbit"
        elif 'pylon_2' in segment:
            segment_display = "Pylon 2 Orbit"
        else:
            segment_display = segment.replace('_', ' ').title()

        # Build tooltip - prominently show pivotal altitude
        tooltip_content = [
            html.Div(f"{segment_display}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"PIVOTAL ALT: {pt.get('pivotal_alt', 0):.0f} ft AGL", style={"fontWeight": "bold", "color": "#27ae60"}),
            html.Div(f"Groundspeed: {pt.get('gs', 0):.0f} kt"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
            html.Div(f"Load: {pt.get('load_factor', 1.0):.2f}G"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Wind corr: {pt.get('wind_correction', 0):.1f}°"),
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = pt.get('wind_correction', 0)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)

        return [marker]
