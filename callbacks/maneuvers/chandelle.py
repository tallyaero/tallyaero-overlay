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
from layouts.maneuvers._charts import altitude_profile_chart
from layouts.maneuvers._shared import _acs_metric, _power_verdict, _winds_aloft_chip

from core.data_loader import aircraft_data, airport_data
from core.profile3d import build_3d_side_view_block, side_view_accordion_item


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
        Input({"type": "draw-btn", "m_id": "chandelle"}, "n_clicks"),
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
        State("engine-select", "value"),
        State("selected-airport-id", "data"),
        State("runtime-total-weight-lb", "data"),
        State("power-setting", "value"),
        State("wind-profile-store", "data"),
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
        engine_name,
        selected_airport_id,
        weight_lb,
        power_setting,
        wind_profile_data,
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

        # Design Directive — Chandelle design power = 1.0 (FULL throttle).
        # Below 50% the sim truncates the path and surfaces failure_reason.
        try:
            power_pct = float(power_setting) if power_setting not in [None, "", "null"] else 1.0
        except (TypeError, ValueError):
            power_pct = 1.0

        # Phase H — hydrate live winds-aloft column when staged.
        wind_profile = None
        if wind_profile_data:
            try:
                from core.winds_aloft import WindProfile
                wind_profile = WindProfile.from_store(wind_profile_data)
            except Exception:
                wind_profile = None

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
            power_setting=power_pct,
            wind_profile=wind_profile,
            engine_option=engine_name,
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
            children=dl.Tooltip(
                f"Roll-out: {hover[-1].get('heading', 0):.0f}° "
                f"(target {(float(heading) + 180) % 360:.0f}°) "
                f"at {hover[-1].get('alt', 0):.0f} ft"
            ),
        )

        elements = [start_marker, end_marker] + path_segments

        # Time-based scrubber with phase markers. Mirrors the convention
        # used by impossible_turn / PO180 / steep_turn — pilot can scrub
        # directly to entry / 90° point / rollout / exit.
        SEGMENT_LABELS = {
            "roll_in": "Roll In",
            "first_90": "First 90°",
            "second_90": "Second 90°",
            "rollout": "Rollout",
        }
        max_time = hover[-1].get("time", 0) if hover else 0
        slider_marks = {}
        # Phase transitions
        seen_seg = set()
        ninety_marked = False
        for pt in hover:
            t_mark = int(round(float(pt.get("time", 0))))
            seg = pt.get("segment")
            if seg and seg not in seen_seg:
                seen_seg.add(seg)
                label = SEGMENT_LABELS.get(seg, seg.replace("_", " ").title())
                slider_marks[t_mark] = label
            # 90° pin — first tick at or past 90° heading change.
            if not ninety_marked and pt.get("turn_progress", 0) >= 90.0:
                slider_marks[t_mark] = "90°"
                ninety_marked = True
        slider_marks[0] = slider_marks.get(0, "Start")
        slider_marks[int(round(max_time))] = "Exit"
        slider_max = int(round(max_time)) if max_time > 0 else 100
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

        # Stall reference — surfaced by the sim. The ACS-graded chandelle
        # exit condition is "wings-level within 10 KIAS of power-on
        # stall", so the margin we surface is min_IAS against
        # vs_power_on (sim field `stall_margin_kt`). The in-turn margin
        # (min_IAS against Vs×√n at max bank) is also surfaced for
        # context.
        last_hover = hover[-1] if hover else {}
        vs_clean = float(last_hover.get("vs_clean_kt", 50))
        vs_power_on = float(last_hover.get("vs_power_on_kt", vs_clean * 0.93))
        vs_in_turn = float(last_hover.get("vs_at_bank_kt") or (vs_clean * math.sqrt(load_factor)))
        min_ias = float(last_hover.get("min_ias_kt") or entry_ias)
        exit_margin = float(last_hover.get("stall_margin_kt", min_ias - vs_power_on))
        in_turn_margin = float(last_hover.get("stall_margin_in_turn_kt", min_ias - vs_in_turn))

        # Build info panel with standardized format
        info_accordion = dbc.Accordion([
            dbc.AccordionItem([
                html.Div(f"Weight: {weight:.0f} lb | IAS: {entry_ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {wind_dir_val:.0f}°/{wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {min_gs:.0f}-{max_gs:.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"Alt: {altitude_ft:.0f}→{exit_alt:.0f} ft (+{alt_gain:.0f}) | {direction.title()} 180°", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(
                    f"Vs(clean): {vs_clean:.0f} → Vs(power-on): {vs_power_on:.0f} kt | min IAS: {min_ias:.0f} kt | Time: {total_time:.0f}s",
                    style={"fontSize": "11px"},
                ),
                html.Div(
                    f"Exit margin vs power-on Vs: {exit_margin:+.0f} kt"
                    f"  ·  In-turn margin (Vs×√n at {max_bank:.0f}°): {in_turn_margin:+.0f} kt",
                    style={
                        "fontSize": "11px",
                        "color": (
                            "#dc2626" if exit_margin < 4
                            else "#f59e0b" if exit_margin < 8
                            else "#16a34a"
                        ),
                        "fontWeight": "500",
                    },
                ),
                html.Div([
                    html.Span("Color: ", style={"fontSize": "10px"}),
                    html.Span("■ Low", style={"color": "#ff0000", "fontSize": "10px", "marginRight": "6px"}),
                    html.Span("■ Mid", style={"color": "#804080", "fontSize": "10px", "marginRight": "6px"}),
                    html.Span("■ High", style={"color": "#0000ff", "fontSize": "10px"}),
                ], style={"marginTop": "4px"}),
                # Phase C9 — Commercial ACS tolerances.
                # Stall margin = min IAS over the maneuver vs. power-on
                # Vs at exit (the ACS-graded reference). ACS target is
                # "within 10 KIAS of power-on stall" → tolerance ±10.
                html.Div([
                    _acs_metric("Roll-out", 0, "°", target=0, tol=10, cert_level="commercial"),
                    _acs_metric("Exit stall margin", exit_margin, "kt", target=10, tol=10, cert_level="commercial"),
                ], style={"display": "flex", "flexWrap": "wrap", "marginTop": "6px"}),
                # Phase D2 — Design Directive power verdict. The sim
                # only writes `failure_reason` when power_pct < 0.5
                # caused it to truncate the maneuver short of 180°;
                # at 50-80% power the maneuver still completes (with
                # less altitude gain), so the red "failed" banner is
                # gated on the sim's actual outcome, not the slider.
                _power_verdict(
                    power_pct, 1.0,
                    "altitude gained reduced",
                    "could not reach 180° within target IAS",
                    actually_failed=bool(last_hover.get("failure_reason")),
                ),
            ], title="Simulation Results", style={"fontSize": "12px"}),
            # 3D Side View — chandelle is a climbing turn so vertical
            # profile is the entire point of the maneuver.
            side_view_accordion_item(
                build_3d_side_view_block(
                    path=path,
                    hover=hover,
                    elev_ft=float(field_elev_ft or 0.0),
                )
            ),
        ], start_collapsed=False, style={"marginTop": "8px"})

        # Phase C5 — altitude profile chart with phase markers at 90° pitch (transition
        # from first_90 → second_90) and 180° exit. The student sees the characteristic
        # Chandelle climbing profile rather than just an accordion full of numbers.
        times = [pt.get("time", 0) for pt in hover]
        alts = [pt.get("alt", 0) for pt in hover]
        markers = []
        prev_seg = None
        for pt in hover:
            seg = pt.get("segment")
            if seg == "second_90" and prev_seg != "second_90":
                markers.append((pt.get("time", 0), "90°"))
            prev_seg = seg
        if hover:
            markers.append((hover[-1].get("time", 0), "Exit"))
        profile_chart = altitude_profile_chart(
            times, alts, chart_id="chandelle-profile-chart", markers=markers,
        )
        winds_chip = _winds_aloft_chip(wind_profile_data)
        info_content = html.Div(
            [info_accordion]
            + ([winds_chip] if winds_chip is not None else [])
            + [profile_chart]
        )

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
        """Update the scrubber marker and tooltip based on slider position.

        Time-based lookup (post-2026-05-21) — finds the closest hover
        entry by time, so phase marks land on the right ticks even when
        segment timing doesn't divide the index range evenly.
        """
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

        SEGMENT_LABELS = {
            "roll_in": "Roll In",
            "first_90": "First 90°",
            "second_90": "Second 90°",
            "rollout": "Rollout",
        }
        seg_raw = pt.get("segment", "climb")
        segment_label = SEGMENT_LABELS.get(seg_raw, seg_raw.replace("_", " ").title())
        progress = pt.get("turn_progress", 0)

        load_factor = pt.get("load_factor")
        if load_factor is None and pt.get("aob") is not None and abs(pt["aob"]) < 89.9:
            load_factor = 1.0 / math.cos(math.radians(abs(pt["aob"])))

        tooltip_content = [
            html.Div(segment_label, style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
            html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL  ·  Turn: {progress:.0f}° of 180°"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(
                f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}° | Pitch: {pt.get('pitch', 0):.1f}°"
                + (f" | Load: {load_factor:.2f}G" if load_factor else "")
            ),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Margin above power-on Vs: {pt.get('speed_margin', 0):+.0f} kt"),
        ]

        heading = pt.get('heading', 0)
        bank = pt.get('aob', 0)
        crab = -pt.get('drift', 0)  # marker visual only — crab not displayed in tooltip per user note (continuous turn)
        marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
        return [marker]
