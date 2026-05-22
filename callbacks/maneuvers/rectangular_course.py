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
from layouts.maneuvers._shared import _acs_metric, _winds_aloft_chip

from core.data_loader import aircraft_data, airport_data


# ---------------------------------------------------------------------------
# 4-corner snap math — post-2026-05-21 UX rewrite.
#
# Pilot clicks four corners of the rectangle they want to fly. The clicks
# rarely form a perfect rectangle, so we snap to one before running the sim.
#
# Strategy (keeps the pilot's downwind orientation intact):
#   * Clicks 1 and 2 are treated as the DOWNWIND edge — kept verbatim.
#   * Compute the perpendicular axis from the 1→2 vector.
#   * Project clicks 3 and 4 onto that perpendicular; AVERAGE their
#     perpendicular offset to derive the rectangle's width.
#   * Choose the perpendicular DIRECTION as the side clicks 3+4 fall on
#     (sign of the averaged offset).
#   * Rebuild corners C and D so the resulting polygon is a true
#     right-angled rectangle with the first edge unchanged.
# ---------------------------------------------------------------------------

def _rotate_clicks(clicks: list, downwind_idx: int) -> list:
    """Rotate the 4-click list so the chosen downwind edge is first.

    `downwind_idx` is the index of the FIRST click of the desired
    downwind edge (0..3). After rotation, clicks[0]→clicks[1] is the
    downwind edge — which is what `_snap_corners_to_rectangle` expects.
    """
    n = len(clicks)
    if n != 4:
        return list(clicks)
    i = max(0, min(3, int(downwind_idx)))
    return [clicks[(i + k) % n] for k in range(n)]


def _auto_downwind_edge(clicks: list, wind_dir_deg: float) -> int:
    """Pick the edge whose bearing best matches the DOWNWIND direction
    (= wind_to, i.e. wind_dir + 180°). Returns 0..3 — the index of the
    first click of the chosen edge."""
    import math as _m
    if len(clicks) != 4:
        return 0
    wind_to = (float(wind_dir_deg) + 180.0) % 360.0
    best_idx = 0
    best_err = 1e9
    for i in range(4):
        a = clicks[i]
        b = clicks[(i + 1) % 4]
        dn = (b["lat"] - a["lat"]) * 364567.2
        de = (b["lon"] - a["lon"]) * 364567.2 * _m.cos(_m.radians(a["lat"]))
        bearing = (_m.degrees(_m.atan2(de, dn)) + 360.0) % 360.0
        err = abs(((bearing - wind_to) + 180.0) % 360.0 - 180.0)
        if err < best_err:
            best_err = err
            best_idx = i
    return best_idx


def _snap_corners_to_rectangle(c1: dict, c2: dict, c3: dict, c4: dict) -> dict:
    """Return {'dw_start', 'dw_end', 'lateral_offset_nm',
              'corners_snapped': [c1, c2, c3', c4'],
              'corners_raw': [c1, c2, c3, c4]}."""
    ft_per_deg_lat = 364567.2
    ref_lat = (c1["lat"] + c2["lat"]) / 2
    ft_per_deg_lon = ft_per_deg_lat * math.cos(math.radians(ref_lat))

    def to_xy(p):
        n = (p["lat"] - ref_lat) * ft_per_deg_lat
        e = (p["lon"] - (c1["lon"] + c2["lon"]) / 2) * ft_per_deg_lon
        return n, e

    def to_latlon(n, e):
        return {
            "lat": ref_lat + n / ft_per_deg_lat,
            "lon": (c1["lon"] + c2["lon"]) / 2 + e / ft_per_deg_lon,
        }

    n1, e1 = to_xy(c1)
    n2, e2 = to_xy(c2)
    n3, e3 = to_xy(c3)
    n4, e4 = to_xy(c4)

    # Edge 1→2 vector + length
    edge_n = n2 - n1
    edge_e = e2 - e1
    edge_len = math.hypot(edge_n, edge_e)
    if edge_len < 1.0:
        return {}  # degenerate — clicks 1 and 2 coincide

    # Unit along 1→2
    u_n = edge_n / edge_len
    u_e = edge_e / edge_len
    # Unit perpendicular (rotate +90°: (n, e) → (-e, n))
    perp_n = -u_e
    perp_e = u_n

    # Signed perpendicular offset of each of c3, c4 from line through c1
    def perp_offset(n, e):
        return (n - n1) * perp_n + (e - e1) * perp_e

    off3 = perp_offset(n3, e3)
    off4 = perp_offset(n4, e4)
    # Average gives the rectangle width; sign chooses which side.
    width_signed = (off3 + off4) / 2.0
    width = abs(width_signed)
    side_sign = 1.0 if width_signed >= 0 else -1.0

    # Snapped corners C and D — rectangle sits on the side clicks 3+4
    # were averaged onto.
    n_c = n2 + side_sign * perp_n * width
    e_c = e2 + side_sign * perp_e * width
    n_d = n1 + side_sign * perp_n * width
    e_d = e1 + side_sign * perp_e * width

    return {
        "dw_start": {"lat": c1["lat"], "lon": c1["lon"]},
        "dw_end": {"lat": c2["lat"], "lon": c2["lon"]},
        "lateral_offset_nm": round(width / 6076.12, 3),
        "corners_snapped": [
            {"lat": c1["lat"], "lon": c1["lon"]},
            {"lat": c2["lat"], "lon": c2["lon"]},
            to_latlon(n_c, e_c),
            to_latlon(n_d, e_d),
        ],
        "corners_raw": [c1, c2, c3, c4],
    }


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

    # Mirror the shelf dropdown value into the always-present Store.
    # The shelf dropdown is only mounted when rect_course is the active
    # maneuver; the Store is always in the layout (defined in
    # desktop.py) so the snap-preview callback's Input stays valid in
    # every maneuver context.
    @app.callback(
        Output("rectcourse-downwind-edge", "data"),
        Input("rectcourse-downwind-edge-select", "value"),
        prevent_initial_call=True,
    )
    def mirror_downwind_edge_choice(value):
        return value if value is not None else "auto"

    @app.callback(
        Output("rectcourse-snapped-store", "data"),
        Output("rectcourse-calculated-edge", "data"),
        Output("rectcourse-edge-info-display", "children"),
        Output("layer", "children", allow_duplicate=True),
        Input({"type": "point-store", "m_id": "rect_course", "role": "c1"}, "data"),
        Input({"type": "point-store", "m_id": "rect_course", "role": "c2"}, "data"),
        Input({"type": "point-store", "m_id": "rect_course", "role": "c3"}, "data"),
        Input({"type": "point-store", "m_id": "rect_course", "role": "c4"}, "data"),
        # Read from the always-present Store (mirrored from the shelf
        # dropdown). Pre-fix this referenced the dropdown directly,
        # which raised "nonexistent object" errors any time the user
        # was on another maneuver and a point-store fired.
        Input("rectcourse-downwind-edge", "data"),
        State("env-wind-dir", "value"),
        State("layer", "children"),
        State("maneuver-select", "value"),
        prevent_initial_call=True
    )
    def calculate_rectcourse_corners_and_preview(c1, c2, c3, c4, downwind_choice,
                                                  wind_dir, layer_children, current_maneuver):
        """4-corner UX preview.

        Draws a progressive preview after each of the four corner clicks:
          1 click  → dot
          2 clicks → first-edge dashed line (downwind orientation)
          3 clicks → 3-side polyline (raw clicks)
          4 clicks → snapped rectangle (solid outline) + raw-click dots
                      for reference, plus a dashed line on the first edge.

        Returns three stores:
          - rectcourse-snapped-store: snapped rectangle + dw_start/dw_end/
            lateral_offset_nm (drives the draw callback)
          - rectcourse-calculated-edge: legacy edge data (kept for
            backward-compat with any consumers still reading it)
          - rectcourse-edge-info-display: hidden status line
        """
        from physics import calculate_initial_compass_bearing

        if current_maneuver != "rect_course":
            raise PreventUpdate

        if layer_children is None:
            layer_children = []

        # Strip any existing rect_course preview elements.
        def should_keep(c):
            if not isinstance(c, dict):
                return True
            el_id = c.get("props", {}).get("id", "")
            if isinstance(el_id, str) and el_id.startswith("rectcourse-preview"):
                return False
            return True

        layer_children = [c for c in layer_children if should_keep(c)]

        # Collect non-empty clicks in order.
        clicks = []
        for c in (c1, c2, c3, c4):
            if c and isinstance(c, dict) and c.get("lat") is not None:
                clicks.append(c)

        if not clicks:
            return {}, {}, "Click corner 1 to begin.", layer_children

        # Always render the click dots so the pilot can see exactly where
        # they clicked vs. where the snap landed.
        marker_colors = ["#22c55e", "#f59e0b", "#f59e0b", "#ef4444"]
        for i, p in enumerate(clicks):
            layer_children.append(dl.CircleMarker(
                id=f"rectcourse-preview-dot-{i + 1}",
                center=[p["lat"], p["lon"]],
                radius=7,
                color=marker_colors[i],
                fill=True,
                fillColor=marker_colors[i],
                fillOpacity=0.85,
                children=dl.Tooltip(f"Corner {i + 1}"),
            ))

        snapped: dict = {}
        edge_data: dict = {}
        status_text = ""

        if len(clicks) == 1:
            status_text = "1/4 clicks — set corner 2 (defines downwind direction)."

        elif len(clicks) == 2:
            # First edge (downwind direction).
            p1, p2 = clicks[0], clicks[1]
            from geopy import Point as GeoPoint
            bearing = round(calculate_initial_compass_bearing(
                GeoPoint(p1["lat"], p1["lon"]),
                GeoPoint(p2["lat"], p2["lon"]),
            ), 1)
            layer_children.append(dl.Polyline(
                id="rectcourse-preview-edge12",
                positions=[[p1["lat"], p1["lon"]], [p2["lat"], p2["lon"]]],
                color="#0d59f2",
                weight=2,
                opacity=0.7,
                dashArray="6,6",
                children=dl.Tooltip(f"Downwind edge — bearing {bearing:.0f}°"),
            ))
            status_text = f"2/4 clicks — downwind bearing {bearing:.0f}° set. Click corners 3 + 4 to define width."

        elif len(clicks) == 3:
            # Raw polyline 1→2→3.
            positions = [[p["lat"], p["lon"]] for p in clicks]
            layer_children.append(dl.Polyline(
                id="rectcourse-preview-poly3",
                positions=positions,
                color="#0d59f2",
                weight=2,
                opacity=0.7,
                dashArray="6,6",
            ))
            status_text = "3/4 clicks — set corner 4 to close the rectangle."

        else:
            # 4 clicks — snap and render the perfect rectangle. The
            # downwind edge is either user-selected (Auto / 0..3) or
            # auto-picked from wind. We rotate the click list so the
            # chosen edge comes first, then snap.
            wind_dir_v = float(wind_dir) if wind_dir not in (None, "", "null") else 0.0
            if downwind_choice in (None, "", "auto"):
                dw_idx = _auto_downwind_edge(clicks, wind_dir_v)
                dw_choice_kind = "auto"
            else:
                try:
                    dw_idx = int(downwind_choice)
                except (TypeError, ValueError):
                    dw_idx = _auto_downwind_edge(clicks, wind_dir_v)
                dw_choice_kind = "manual"

            rotated = _rotate_clicks(clicks, dw_idx)
            snapped = _snap_corners_to_rectangle(*rotated)
            if snapped:
                # Track which raw-click indices form the downwind edge so
                # the preview can highlight them.
                snapped["downwind_click_indices"] = [dw_idx, (dw_idx + 1) % 4]
                snapped["downwind_choice"] = dw_choice_kind

                corners_snap = snapped["corners_snapped"]
                # Draw the snapped rectangle as 4 separate edges so the
                # downwind one can be colored green (highlighted) and
                # the rest blue. Edge 0 = corners_snap[0] → [1] = downwind.
                EDGE_COLOR_DOWNWIND = "#16a34a"  # green-600
                EDGE_COLOR_OTHER = "#0d59f2"     # brand-blue
                for i in range(4):
                    a = corners_snap[i]
                    b = corners_snap[(i + 1) % 4]
                    is_downwind = (i == 0)
                    layer_children.append(dl.Polyline(
                        id=f"rectcourse-preview-edge-{i}",
                        positions=[[a["lat"], a["lon"]], [b["lat"], b["lon"]]],
                        color=EDGE_COLOR_DOWNWIND if is_downwind else EDGE_COLOR_OTHER,
                        weight=4 if is_downwind else 3,
                        opacity=0.9,
                        children=dl.Tooltip(
                            f"DOWNWIND leg — flown with the wind"
                            if is_downwind else f"Edge {i + 1}"
                        ),
                    ))

                # Dashed line showing the user's raw 3→4 edge for
                # comparison (only when the snap moved it noticeably).
                layer_children.append(dl.Polyline(
                    id="rectcourse-preview-raw34",
                    positions=[[clicks[2]["lat"], clicks[2]["lon"]],
                               [clicks[3]["lat"], clicks[3]["lon"]]],
                    color="#94a3b8",
                    weight=1,
                    opacity=0.5,
                    dashArray="3,4",
                ))

                # Edge data for backward compat.
                edge_data = {
                    "start_lat": snapped["dw_start"]["lat"],
                    "start_lon": snapped["dw_start"]["lon"],
                    "end_lat": snapped["dw_end"]["lat"],
                    "end_lon": snapped["dw_end"]["lon"],
                    "mid_lat": (snapped["dw_start"]["lat"] + snapped["dw_end"]["lat"]) / 2,
                    "mid_lon": (snapped["dw_start"]["lon"] + snapped["dw_end"]["lon"]) / 2,
                    "length_nm": None,
                    "length_ft": None,
                }
                choice_note = (
                    f"auto-picked from wind {wind_dir_v:.0f}°"
                    if dw_choice_kind == "auto"
                    else "manual override"
                )
                status_text = (
                    f"Rectangle set — DW = edge {dw_idx + 1}→{((dw_idx + 1) % 4) + 1} "
                    f"({choice_note}); width {snapped['lateral_offset_nm']:.2f} nm. "
                    f"Click Draw to simulate."
                )
            else:
                status_text = "Could not snap rectangle — clicks 1 and 2 too close. Try again."

        return snapped, edge_data, status_text, layer_children

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
        Input({"type": "draw-btn", "m_id": "rect_course"}, "n_clicks"),
        State("rectcourse-snapped-store", "data"),
        State("rectcourse-altitude", "value"),
        State("rectcourse-ias", "value"),
        State("rectcourse-direction", "value"),
        State("rectcourse-circuits", "value"),
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
    def draw_rectangular_course(
        n_clicks,
        snapped,
        altitude_ft,
        ias_knots,
        pattern_direction,
        num_circuits,
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
        # Snapped rectangle from the 4-corner UX must be present.
        if not n_clicks or not snapped or not snapped.get("dw_start"):
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

        # 4-corner snap output drives the sim's dw_start / dw_end /
        # lateral_offset. Pre-fix used a separate user-typed
        # `rectcourse-width` input; now derived from the 4 clicks.
        dw_start = dict(snapped["dw_start"])
        dw_end = dict(snapped["dw_end"])
        lateral_nm = float(snapped.get("lateral_offset_nm", 0.5))
        # Recompute DW length from the snapped corners for the panel.
        _dn = (dw_end["lat"] - dw_start["lat"]) * 364567.2
        _de = (dw_end["lon"] - dw_start["lon"]) * 364567.2 * math.cos(math.radians(dw_start["lat"]))
        dw_length_nm = math.hypot(_dn, _de) / 6076.12
        dw_track = math.degrees(math.atan2(_de, _dn)) % 360.0

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

        # Hydrate live winds-aloft column if airport-pick fetched one.
        wind_profile = None
        if wind_profile_data:
            try:
                from core.winds_aloft import WindProfile
                wind_profile = WindProfile.from_store(wind_profile_data)
            except Exception:
                wind_profile = None

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
            wind_profile=wind_profile,
            engine_option=engine_name,
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

        # Stall references — sim surfaces real values post-audit (was
        # hardcoding stall_speed_clean=48 in the warnings dict).
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
                    html.Div(
                        f"Turn radius at corners (30° bank): "
                        f"{((avg_tas * 1.68781) ** 2 / (32.2 * math.tan(math.radians(30.0)))):.0f} ft",
                        style={"fontSize": "11px"},
                        title="Geometric radius required at the four corners assuming "
                              "a typical 30° pattern bank. Tighter bank shrinks this.",
                    ),
                    html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                    html.Div(
                        f"Vs(clean): {vs_clean:.0f} → Vs×√n at {max_bank:.0f}°: {vs_in_turn:.0f} kt | min IAS: {min_ias_achieved:.0f} kt | Time: {sim_warnings.get('total_time_sec', 0):.0f}s",
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
                    html.Div(f"{direction.title()} pattern | {circuits} circuits", style={"fontSize": "11px"}),
                    # Phase C9 — Private ACS tolerances.
                    html.Div([
                        _acs_metric("Altitude", 0, "ft", target=0, tol=100, cert_level="private"),
                        _acs_metric("Pattern radius", 0, "%", target=0, tol=10, cert_level="private"),
                    ], style={"display": "flex", "flexWrap": "wrap", "marginTop": "6px"}),
                ], title="Simulation Results", style={"fontSize": "12px"}),
            ], start_collapsed=False, style={"marginTop": "8px"})
        )

        # Live winds-aloft chip — parity with other maneuvers.
        chip = _winds_aloft_chip(wind_profile_data)
        if chip is not None:
            info_elements.append(chip)

        # Time-based scrubber with leg-transition marks. Walks the hover
        # stream once and records the time each new segment first appears
        # (downwind → turn_to_base → base → turn_to_upwind → ...).
        max_time = hover[-1].get("time", 0) if hover else 0
        slider_marks = {0: "Start"}
        seen_segs = set()
        SEG_SHORT = {
            "entry": "Entry",
            "downwind": "DW",
            "turn_to_base": "↻Base",
            "base": "Base",
            "turn_to_upwind": "↻UW",
            "upwind": "UW",
            "turn_to_crosswind": "↻XW",
            "crosswind": "XW",
            "turn_to_downwind": "↻DW",
        }
        for pt in hover:
            seg = pt.get("segment", "")
            if seg and seg not in seen_segs:
                seen_segs.add(seg)
                label = SEG_SHORT.get(seg, seg.replace("_", " ").title())
                t_mark = int(round(float(pt.get("time", 0))))
                slider_marks[t_mark] = label
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
        """Update the scrubber marker and tooltip based on slider position.

        Time-based lookup so leg labels (DW / Base / Upwind / Crosswind)
        align with the actual transition ticks regardless of timestep."""
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
