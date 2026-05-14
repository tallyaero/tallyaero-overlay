import requests
import math
import os
import json
import dash
from dash import dcc, html, Input, Output, State, MATCH, ALL, ctx, no_update
import dash_bootstrap_components as dbc
import dash_leaflet as dl
from geopy.point import Point as GeoPoint
from geopy.distance import distance as geo_distance
from dash.exceptions import PreventUpdate
from core.log import get_logger

log = get_logger(__name__)
from utility import (
    compute_density_altitude,
    compute_pressure_altitude,
    compute_true_airspeed,
    compute_glide_ratio,
    compute_descent_angle_deg,
    simulate_glide_path_to_target,
    point_from,
    calculate_initial_compass_bearing,
    knots_to_fps,
    fps_to_knots,
    compute_turn_radius,
    compute_required_bank,
    compute_Ps,
    compute_lift_limit_speed,
    compute_load_factor,
    compute_stall_speed,
    wind_components,
    simulate_steep_turn,
    simulate_chandelle,
    simulate_lazy_eight,
    simulate_steep_spiral,
    render_hover_polyline,
    simulate_engineout_glide,
    find_minimum_altitude,
    compute_glide_envelope,
    simulate_impossible_turn,
)

from layouts.maneuvers.impossible_turn import impossible_turn_layout
from layouts.maneuvers.poweroff180 import poweroff180_layout
from layouts.maneuvers.engineout import engineout_layout
from layouts.maneuvers.steep_turn import steep_turn_layout
from layouts.maneuvers.chandelle import chandelle_layout
from layouts.maneuvers.lazy_eight import lazy8_layout
from layouts.maneuvers.steep_spiral import steep_spiral_layout
from layouts.maneuvers.s_turn import s_turn_layout
from layouts.maneuvers.turns_around_point import turns_point_layout
from layouts.maneuvers.rectangular_course import rect_course_layout
from layouts.maneuvers.eights_on_pylons import pylons_layout

from layouts.desktop import desktop_layout, legal_banner_block, _reset_buttons_row
from layouts.mobile import mobile_layout

# Map helpers - relocated to callbacks/map.py in Phase 1f. The remaining
# draw_* callbacks in this file still consume them.
from callbacks.map import (
    get_elevation,
    calculate_runway_geometry,
    create_airplane_marker,
)

# === Load aircraft data ===
def load_aircraft_data(folder="aircraft_data"):
    data = {}
    for filename in os.listdir(folder):
        if filename.endswith(".json"):
            with open(os.path.join(folder, filename)) as f:
                name = filename.replace(".json", "")
                data[name] = json.load(f)
    return data

# === Load airport data ===
def load_airport_data():
    base = os.path.dirname(__file__)
    path = os.path.join(base, "airports", "airports.json")
    with open(path, "r") as f:
        return json.load(f)


# Module-level placeholders — populated by init_data().
aircraft_data: dict = {}
available_aircraft: list = []
airport_data: list = []


def init_data() -> None:
    """Load aircraft and airport data from disk into module-level caches.

    Idempotent. Called automatically at import time unless
    TALLYAERO_NO_AUTO_INIT is set (used by tests that want to load curated
    subsets).
    """
    global aircraft_data, available_aircraft, airport_data
    if aircraft_data:
        return  # already populated; respect idempotency
    aircraft_data = load_aircraft_data()
    available_aircraft = sorted(aircraft_data.keys())
    airport_data = load_airport_data()


# Default: auto-init unless explicitly disabled.
if not os.environ.get("TALLYAERO_NO_AUTO_INIT"):
    init_data()

# === Dash App ===
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    prevent_initial_callbacks="initial_duplicate"
)
server = app.server

app.title = "Maneuver Overlay Tool | TallyAero"

app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


# === Root Layout with Routing ===
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    dcc.Store(id="screen-width"),
    html.Div(id="page-content")
])

# === Screen Width Detection ===
app.clientside_callback(
    """
    function(_) {
        return window.innerWidth;
    }
    """,
    Output("screen-width", "data"),
    Input("url", "pathname")
)






# === Page Router Callback ===
@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
    Input("screen-width", "data")
)
def display_page(pathname, screen_width):
    if screen_width is None:
        screen_width = 1024  # assume desktop by default

    is_mobile = screen_width < 768  # BREAKPOINT: 768px

    if is_mobile:
        return mobile_layout()
    else:
        return desktop_layout()


# === Mobile Settings Toggle ===
@app.callback(
    Output("mobile-settings-collapse", "is_open"),
    Output("mobile-settings-toggle", "children"),
    Input("mobile-settings-toggle", "n_clicks"),
    State("mobile-settings-collapse", "is_open"),
    prevent_initial_call=True
)
def toggle_mobile_settings(n_clicks, is_open):
    if n_clicks:
        new_state = not is_open
        return new_state, "▲" if new_state else "▼"
    return is_open, "▼"


# === Sidebar Collapse Callback ===
app.clientside_callback(
    """
    function(n_clicks, is_collapsed) {
        if (n_clicks === undefined || n_clicks === null) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }

        const sidebar = document.getElementById('sidebar');
        const new_collapsed = !is_collapsed;

        if (new_collapsed) {
            sidebar.classList.add('collapsed');
            return [new_collapsed, '»'];
        } else {
            sidebar.classList.remove('collapsed');
            return [new_collapsed, '«'];
        }
    }
    """,
    Output("sidebar-collapsed-store", "data"),
    Output("sidebar-collapse-btn", "children"),
    Input("sidebar-collapse-btn", "n_clicks"),
    State("sidebar-collapsed-store", "data"),
    prevent_initial_call=True
)


# === Click Target Registry ===
click_target_registry = {
    "poweroff180": {
        "buttons": {
            "poweroff180-touchdown-btn": "touchdown",
            "poweroff180-start-btn": "start"
        },
        "status_id": "poweroff180-click-status"
    },
    "engineout": {
        "buttons": {
            "engineout-touchdown-btn": "touchdown",
            "engineout-start-btn": "start"
        },
        "status_id": "engineout-click-status"
    },
    "steep_turn": {
        "buttons": {
            "steepturn-start-btn": "start"
        },
        "status_id": "steep_turn-click-status"
    },
    # Add other maneuvers as needed
}

# === Impossible Turn Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output({"type": "click-status", "m_id": "impossible_turn"}, "children", allow_duplicate=True),
    Output("impossibleturn-result", "children", allow_duplicate=True),
    Output("impossibleturn-hover-store", "data"),
    Output("impossibleturn-path-store", "data"),
    Output("impossibleturn-slider-container", "style"),
    Output("impossibleturn-time-slider", "max"),
    Output("impossibleturn-time-slider", "marks"),
    Output("impossibleturn-time-slider", "value"),
    Output("impossibleturn-info", "children"),
    Input("impossibleturn-draw-btn", "n_clicks"),
    State({"type": "point-store", "m_id": "impossible_turn", "role": "start"}, "data"),
    State("aircraft-select", "value"),
    State("engine-select", "value"),
    State("occupants", "value"),
    State("occupant-weight", "value"),
    State("fuel-load", "value"),
    State("cg-slider", "value"),
    State("env-wind-dir", "value"),
    State("env-wind-speed", "value"),
    State("env-oat", "value"),
    State("env-altimeter", "value"),
    State("impossibleturn-direction", "value"),
    State("impossibleturn-runway-select", "value"),
    State("impossibleturn-manual-heading", "value"),
    State("impossibleturn-altitude", "value"),
    State("impossibleturn-reaction-sec", "value"),
    State("impossibleturn-climb-speed", "value"),
    State("impossibleturn-flap-config", "value"),
    State("impossibleturn-prop-config", "value"),
    State("selected-airport-id", "data"),
    State("runtime-total-weight-lb", "data"),
    prevent_initial_call=True,
)
def draw_impossible_turn(
    n_clicks,
    failure_data,
    ac_name,
    engine_key,
    occupants,
    occupant_wt,
    fuel_gal,
    cg_pos,
    wind_dir,
    wind_speed,
    oat_f,
    altimeter,
    turn_dir,
    runway_select,
    manual_heading,
    failure_alt_agl,
    reaction_sec,
    entry_ias,
    flap_config,
    prop_config,
    selected_airport_id,
    runtime_weight,
):
    if not n_clicks:
        raise PreventUpdate

    if not failure_data:
        return [], None, "⚠️ Set takeoff point (runway threshold) first.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

    if not ac_name or not engine_key:
        return [], None, "⚠️ Select aircraft and engine first.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

    try:
        from geopy import Point as GeoPoint
        states = dash.callback_context.states

        def safe_float(state_key):
            v = states.get(state_key)
            return float(v) if v not in [None, "", "null"] else None

        # Get runway heading from dropdown selection or manual input
        runway_heading = None
        runway_length_ft = 5000  # Default
        runway_id_selected = states.get("impossibleturn-runway-select.value")

        if runway_id_selected and selected_airport_id:
            # Get heading from airport runway data
            airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
            if airport and "runways" in airport:
                runway = next((r for r in airport["runways"] if r.get("id") == runway_id_selected), None)
                if runway:
                    runway_heading = runway.get("heading")
                    runway_length_ft = runway.get("length_ft", 5000)

        # Fallback to manual heading if no runway selected or no heading data
        if runway_heading is None:
            runway_heading = safe_float("impossibleturn-manual-heading.value")

        failure_alt_agl = safe_float("impossibleturn-altitude.value")
        reaction_sec    = safe_float("impossibleturn-reaction-sec.value")
        entry_ias       = safe_float("impossibleturn-climb-speed.value")
        wind_dir        = safe_float("env-wind-dir.value")
        wind_speed      = safe_float("env-wind-speed.value")
        oat_f           = safe_float("env-oat.value")
        altimeter       = safe_float("env-altimeter.value")

        # Weight: use runtime store only
        total_wt = safe_float("runtime-total-weight-lb.data")
        if total_wt is None:
            # fallback to State value if callback_context didn't capture it
            total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None

        required = [
            runway_heading, failure_alt_agl, reaction_sec, entry_ias,
            wind_dir, wind_speed, oat_f, altimeter,
            total_wt,
        ]
        if any(x is None for x in required):
            return [], None, "⚠️ Missing or invalid inputs.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

        # The clicked point is now the runway threshold (takeoff start point)
        threshold_pt = {"lat": failure_data["lat"], "lon": failure_data["lon"]}
        threshold_geopoint = GeoPoint(failure_data["lat"], failure_data["lon"])

        # Aircraft dict copy + stash runtime weight (no JSON changes)
        ac = dict(aircraft_data[ac_name])
        ac["total_weight_lb"] = float(total_wt)

        # Airport elevation reference
        selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
        airport_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

        # OAT F -> C
        oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0

        # Determine if we should include takeoff/climb simulation
        # Enable when airport is selected and we have runway data
        include_takeoff_climb = bool(selected_airport_id and runway_id_selected)

        path, hover, meta = simulate_impossible_turn(
            start_point=threshold_geopoint,  # Legacy fallback
            runway_heading_deg=float(runway_heading),
            turn_dir=str(turn_dir),
            reaction_sec=float(reaction_sec),
            start_ias_kias=float(entry_ias),
            altitude_agl=float(failure_alt_agl),

            ac=ac,
            engine_option=engine_key,
            weight_lbs=float(total_wt),
            oat_c=float(oat_c),
            altimeter_inhg=float(altimeter),
            wind_dir=float(wind_dir),
            wind_speed=float(wind_speed),
            timestep_sec=0.5,
            flap_config=flap_config,
            prop_config=prop_config,
            touchdown_elev_ft=float(airport_elev_ft),
            find_min_alt=True,

            # NEW: Takeoff/climb parameters
            include_takeoff_climb=include_takeoff_climb,
            threshold_point=threshold_pt if include_takeoff_climb else None,
            runway_length_ft=float(runway_length_ft) if include_takeoff_climb else None,
        )

        if not path:
            return [], None, "⚠️ No path generated. Check inputs.", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""

        # Meta
        meta = meta or {}
        made_it      = bool(meta.get("success", False))
        impact       = meta.get("impact_marker", None)
        reason       = meta.get("reason", "unknown")
        min_required = meta.get("min_feasible_alt_agl", None)
        bank_deg     = meta.get("bank_deg", None)
        has_takeoff_climb = meta.get("include_takeoff_climb", False)
        ground_roll_ft = meta.get("ground_roll_ft", None)

        # Find engine failure point from hover data (end of climb phase or start of reaction)
        failure_point_for_distance = threshold_geopoint  # Default to threshold
        if has_takeoff_climb and hover:
            # Find the first point where phase changes from 'climb' to something else
            for i, pt in enumerate(hover):
                phase = pt.get("phase", "")
                if phase in ["reaction", "turn1"]:
                    # Get position from path at this index
                    if i < len(path):
                        failure_point_for_distance = GeoPoint(float(path[i][0]), float(path[i][1]))
                    break

        # Distance (NM): failure point -> impact (if any) else -> end of path
        dist_nm = None
        try:
            if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
                end_pt = GeoPoint(float(impact[0]), float(impact[1]))
                dist_nm = geo_distance(failure_point_for_distance, end_pt).nm
                dist_label = "Failure distance to impact"
            else:
                end_lat, end_lon = path[-1][0], path[-1][1]
                end_pt = GeoPoint(float(end_lat), float(end_lon))
                dist_nm = geo_distance(failure_point_for_distance, end_pt).nm
                dist_label = "Failure distance to touchdown"
        except Exception:
            dist_nm = None
            dist_label = "Distance"

        dist_txt = f"{dist_label}: {dist_nm:.2f} NM" if isinstance(dist_nm, (int, float)) else f"{dist_label}: n/a"

        elements = []

        # ---------- Multi-phase visualization ----------
        if has_takeoff_climb and hover:
            # Separate path into: takeoff (green), climb (blue), glide (red)
            takeoff_pts = []
            climb_pts = []
            glide_pts = []  # Everything after engine failure

            for i, pt in enumerate(hover):
                phase = pt.get("phase", "unknown")
                if i < len(path):
                    if phase == "takeoff":
                        takeoff_pts.append(path[i])
                    elif phase == "climb":
                        climb_pts.append(path[i])
                    else:
                        # All post-failure phases: reaction, turn1, straight, turn2, final
                        glide_pts.append(path[i])

            # Draw takeoff (green)
            if len(takeoff_pts) >= 2:
                elements.append(dl.Polyline(positions=takeoff_pts, color="#00AA00", weight=4))

            # Draw climb (blue) - connect from last takeoff point
            if len(climb_pts) >= 2:
                # Add connection from takeoff
                if takeoff_pts:
                    climb_with_connection = [takeoff_pts[-1]] + climb_pts
                else:
                    climb_with_connection = climb_pts
                elements.append(dl.Polyline(positions=climb_with_connection, color="#0066FF", weight=3))

            # Draw glide (red) - entire path from engine failure to touchdown
            if len(glide_pts) >= 2:
                # Add connection from climb
                if climb_pts:
                    glide_with_connection = [climb_pts[-1]] + glide_pts
                else:
                    glide_with_connection = glide_pts
                elements.append(dl.Polyline(positions=glide_with_connection, color="#FF0000", weight=3))

            # Add takeoff start marker (threshold)
            elements.append(
                dl.CircleMarker(
                    center=[threshold_geopoint.latitude, threshold_geopoint.longitude],
                    radius=7,
                    color="#00AA00",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip("Takeoff point (runway threshold)"),
                )
            )

            # Add engine failure marker (explosion emoji)
            if failure_point_for_distance != threshold_geopoint:
                failure_icon = {
                    "iconUrl": "data:image/svg+xml;utf8," +
                        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>" +
                        "<text y='80' font-size='80'>💥</text></svg>",
                    "iconSize": [28, 28],
                    "iconAnchor": [14, 14],
                }
                elements.append(
                    dl.Marker(
                        position=[failure_point_for_distance.latitude, failure_point_for_distance.longitude],
                        icon=failure_icon,
                        children=dl.Tooltip(f"Engine failure ({float(failure_alt_agl):.0f} ft AGL)"),
                    )
                )

            # Add runway overlay polygon
            if runway_length_ft and runway_heading:
                try:
                    runway_coords = calculate_runway_geometry(
                        threshold_pt["lat"],
                        threshold_pt["lon"],
                        float(runway_heading),
                        float(runway_length_ft),
                        width_ft=100  # Standard runway width
                    )
                    # Add as solid black polygon at the bottom of the layer stack
                    elements.insert(0, dl.Polygon(
                        positions=runway_coords,
                        color="#000000",
                        fillColor="#1a1a1a",
                        fillOpacity=0.9,
                        weight=2,
                        children=dl.Tooltip(f"Runway {runway_id_selected or ''} ({runway_length_ft:.0f} ft)"),
                    ))

                    from physics import point_from, FT_PER_NM
                    from geopy import Point as GeoPoint
                    threshold_geo = GeoPoint(threshold_pt["lat"], threshold_pt["lon"])
                    rwy_hdg = float(runway_heading)
                    rwy_len = float(runway_length_ft)
                    opposite = point_from(threshold_geo, rwy_hdg, rwy_len / FT_PER_NM)

                    # Add white dashed centerline
                    elements.insert(1, dl.Polyline(
                        positions=[
                            [threshold_pt["lat"], threshold_pt["lon"]],
                            [opposite.latitude, opposite.longitude]
                        ],
                        color="#FFFFFF",
                        weight=2,
                        dashArray="20, 15",
                    ))

                    # === PIANO KEYS (Threshold Markings) at both ends ===
                    # 8 stripes for 100ft runway, each ~6ft wide with gaps
                    # Stripes are 150ft long, start 20ft from threshold
                    piano_key_length_ft = min(150.0, rwy_len * 0.15)  # Scale for short runways
                    piano_key_width_ft = 6.0
                    piano_key_gap_ft = 6.0
                    piano_key_offset_ft = 20.0  # Start 20ft from threshold
                    num_stripes = 8  # For 100ft runway
                    total_stripe_width = num_stripes * piano_key_width_ft + (num_stripes - 1) * piano_key_gap_ft
                    stripe_start_offset = -total_stripe_width / 2 + piano_key_width_ft / 2

                    perp_left = (rwy_hdg - 90) % 360
                    perp_right = (rwy_hdg + 90) % 360
                    opposite_hdg = (rwy_hdg + 180) % 360

                    # Draw piano keys at departure threshold
                    for i in range(num_stripes):
                        lateral_offset_ft = stripe_start_offset + i * (piano_key_width_ft + piano_key_gap_ft)
                        # Start point of stripe
                        start_pt = point_from(threshold_geo, rwy_hdg, piano_key_offset_ft / FT_PER_NM)
                        if lateral_offset_ft > 0:
                            start_pt = point_from(start_pt, perp_right, abs(lateral_offset_ft) / FT_PER_NM)
                        else:
                            start_pt = point_from(start_pt, perp_left, abs(lateral_offset_ft) / FT_PER_NM)
                        # End point of stripe
                        end_pt = point_from(start_pt, rwy_hdg, piano_key_length_ft / FT_PER_NM)
                        elements.append(dl.Polyline(
                            positions=[[start_pt.latitude, start_pt.longitude], [end_pt.latitude, end_pt.longitude]],
                            color="#FFFFFF",
                            weight=3,
                        ))

                    # Draw piano keys at arrival threshold (opposite end)
                    for i in range(num_stripes):
                        lateral_offset_ft = stripe_start_offset + i * (piano_key_width_ft + piano_key_gap_ft)
                        # Start point of stripe (from opposite end, going back toward departure)
                        start_pt = point_from(opposite, opposite_hdg, piano_key_offset_ft / FT_PER_NM)
                        if lateral_offset_ft > 0:
                            start_pt = point_from(start_pt, perp_right, abs(lateral_offset_ft) / FT_PER_NM)
                        else:
                            start_pt = point_from(start_pt, perp_left, abs(lateral_offset_ft) / FT_PER_NM)
                        # End point of stripe
                        end_pt = point_from(start_pt, opposite_hdg, piano_key_length_ft / FT_PER_NM)
                        elements.append(dl.Polyline(
                            positions=[[start_pt.latitude, start_pt.longitude], [end_pt.latitude, end_pt.longitude]],
                            color="#FFFFFF",
                            weight=3,
                        ))

                    # === CAPTAIN'S BARS (Aiming Point Markings) 1000ft from each threshold ===
                    # Two bars per end, 150ft long x 20ft wide, on each side of centerline
                    captains_bar_offset_ft = 1000.0
                    captains_bar_length_ft = min(150.0, rwy_len * 0.1)  # Scale for short runways
                    captains_bar_lateral_offset_ft = 15.0  # Distance from centerline to inner edge

                    # Only draw captain's bars if runway is long enough (>2500ft)
                    if rwy_len >= 2500:
                        # Captain's bars near departure threshold
                        bar_center_dep = point_from(threshold_geo, rwy_hdg, captains_bar_offset_ft / FT_PER_NM)
                        for side_hdg, side_offset in [(perp_left, captains_bar_lateral_offset_ft), (perp_right, captains_bar_lateral_offset_ft)]:
                            bar_start = point_from(bar_center_dep, side_hdg, side_offset / FT_PER_NM)
                            bar_end = point_from(bar_start, rwy_hdg, captains_bar_length_ft / FT_PER_NM)
                            elements.append(dl.Polyline(
                                positions=[[bar_start.latitude, bar_start.longitude], [bar_end.latitude, bar_end.longitude]],
                                color="#FFFFFF",
                                weight=6,
                            ))

                        # Captain's bars near arrival threshold (opposite end)
                        bar_center_arr = point_from(opposite, opposite_hdg, captains_bar_offset_ft / FT_PER_NM)
                        for side_hdg, side_offset in [(perp_left, captains_bar_lateral_offset_ft), (perp_right, captains_bar_lateral_offset_ft)]:
                            bar_start = point_from(bar_center_arr, side_hdg, side_offset / FT_PER_NM)
                            bar_end = point_from(bar_start, opposite_hdg, captains_bar_length_ft / FT_PER_NM)
                            elements.append(dl.Polyline(
                                positions=[[bar_start.latitude, bar_start.longitude], [bar_end.latitude, bar_end.longitude]],
                                color="#FFFFFF",
                                weight=6,
                            ))
                except Exception as e:
                    log.warning(f"Could not draw runway overlay: {e}")
        else:
            # Legacy single-color visualization
            start_marker = dl.CircleMarker(
                center=[threshold_geopoint.latitude, threshold_geopoint.longitude],
                radius=7,
                color="green",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip("Engine failure point"),
            )
            elements.append(start_marker)
            arc_line = dl.Polyline(positions=path, color="red", weight=3)
            elements.append(arc_line)

        # End point marker - smiley for success, skull for failure
        if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
            if made_it:
                # Success: smiley face
                end_icon = {
                    "iconUrl": "data:image/svg+xml;utf8," +
                        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>" +
                        "<text y='80' font-size='80'>😀</text></svg>",
                    "iconSize": [30, 30],
                    "iconAnchor": [15, 15],
                }
                tooltip_text = "Successful landing!"
            else:
                # Failure: skull and crossbones
                end_icon = {
                    "iconUrl": "data:image/svg+xml;utf8," +
                        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>" +
                        "<text y='80' font-size='80'>💀</text></svg>",
                    "iconSize": [30, 30],
                    "iconAnchor": [15, 15],
                }
                tooltip_text = "Impact point"
            elements.append(
                dl.Marker(
                    position=[impact[0], impact[1]],
                    icon=end_icon,
                    children=dl.Tooltip(tooltip_text),
                )
            )

        # Bounds
        lats = [p[0] for p in path] + [threshold_geopoint.latitude]
        lons = [p[1] for p in path] + [threshold_geopoint.longitude]
        if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
            lats.append(impact[0])
            lons.append(impact[1])
        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

        # Status - provide clear failure reasons
        if made_it:
            status = "✅ Impossible turn: successful"
        else:
            # Map failure reasons to user-friendly messages
            reason_messages = {
                "landed_short": "landed short of runway",
                "off_centerline": "missed runway (off centerline)",
                "overshot": "overshot runway (past departure threshold)",
                "impact": "ground impact",
                "timeout": "simulation timeout",
            }
            reason_text = reason_messages.get(reason, reason.replace("_", " "))
            status = f"❌ Impossible turn: unsuccessful - {reason_text}"

        # Result text
        bank_txt = f"{float(bank_deg):.0f}°" if isinstance(bank_deg, (int, float)) else "n/a"

        if isinstance(min_required, (int, float)):
            result = (
                f"Recommended constant bank: {bank_txt}. "
                f"Minimum failure altitude (AGL): {float(min_required):.0f} ft. "
                f"{dist_txt}."
            )
        else:
            result = (
                f"Recommended constant bank: {bank_txt}. "
                f"Minimum failure altitude (AGL): not found in search range. "
                f"{dist_txt}."
            )

        # Build slider marks based on time
        max_time = hover[-1]["time"] if hover and len(hover) > 0 else 100
        slider_marks = {0: "Start", int(max_time): "End"}

        # Prepare hover data for store (ensure JSON-serializable)
        hover_store = []
        if hover and isinstance(hover, list):
            hover_store = [
                {
                    "time": pt.get("time", 0),
                    "alt": pt.get("alt", pt.get("alt_agl", 0)),  # Support both old and new format
                    "alt_agl": pt.get("alt_agl", pt.get("alt", 0)),
                    "alt_msl": pt.get("alt_msl", 0),
                    "ias": pt.get("ias", pt.get("tas", 0)),
                    "tas": pt.get("tas", 0),
                    "gs": pt.get("gs", pt.get("tas", 0)),
                    "aob": pt.get("aob", pt.get("bank", 0)),
                    "vs": pt.get("vs", 0),
                    "track": pt.get("track", 0),
                    "heading": pt.get("heading", 0),
                    "drift": pt.get("drift", 0),
                    "phase": pt.get("phase", "unknown"),  # New: phase name
                }
                for pt in hover
            ]

        # Calculate glide metrics
        glide_ratio = meta.get('glide_ratio', 0) or (failure_alt_agl / (dist_nm * 6076.12) if dist_nm and dist_nm > 0 else 0)
        avg_vs = 0
        avg_gs = 0
        if hover and len(hover) > 0:
            vs_values = [abs(pt.get('vs', 0)) for pt in hover if pt.get('vs') is not None]
            gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover if pt.get('gs') is not None or pt.get('tas') is not None]
            avg_vs = sum(vs_values) / len(vs_values) if vs_values else 0
            avg_gs = sum(gs_values) / len(gs_values) if gs_values else 0

        # Info content - standardized format with glide data
        info_content = dbc.Accordion([
            dbc.AccordionItem([
                html.Div([html.Strong("Aircraft & Environment")], style={"marginBottom": "4px"}),
                html.Div(f"Weight: {total_wt:.0f} lb | Entry IAS: {entry_ias:.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"Wind: {wind_dir:.0f}° at {wind_speed:.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"Flaps: {flap_config or 'None'} | Prop: {prop_config or 'Windmilling'}", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div([html.Strong("Takeoff Performance")], style={"marginBottom": "4px"}),
                html.Div(f"Ground roll: {ground_roll_ft:.0f} ft" if ground_roll_ft else "Ground roll: n/a", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div([html.Strong("Glide Performance")], style={"marginBottom": "4px"}),
                html.Div(f"Glide ratio: ~{glide_ratio:.1f}:1 | Avg GS: {avg_gs:.0f} kt | VS: {avg_vs:.0f} fpm" if glide_ratio > 0 else "Glide ratio: calculating...", style={"fontSize": "11px"}),
                html.Div(f"Distance: {dist_nm:.2f} nm" if dist_nm else "Distance: n/a", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div([html.Strong("Altitude & Timing")], style={"marginBottom": "4px"}),
                html.Div(f"Failure: {failure_alt_agl:.0f} ft AGL | Min req: {min_required:.0f} ft" if min_required else f"Failure: {failure_alt_agl:.0f} ft AGL", style={"fontSize": "11px"}),
                html.Div(f"Turn: {turn_dir.title()} {bank_txt} | Runway: {runway_heading:.0f}° | Time: {max_time:.0f}s", style={"fontSize": "11px"}),
            ], title="Simulation Results", style={"fontSize": "12px"}),
        ], start_collapsed=False, style={"marginTop": "8px"})

        return elements, bounds, status, result, hover_store, path, {"display": "block"}, int(max_time), slider_marks, 0, info_content

    except Exception as e:
        log.error(f"EXCEPTION in draw_impossible_turn(): {e}")
        return [], None, f"⚠️ Error: {str(e)}", "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, ""



from dash import no_update

from dash import callback, Input, Output, State, ctx
from dash.exceptions import PreventUpdate


# === Rectangular Course Edge Calculation ===
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
    import math
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

    # Add start marker
    start_marker = dl.CircleMarker(
        id='rectcourse-preview-start',
        center=[start_lat, start_lon],
        radius=8,
        color="#00aa00",
        fill=True,
        fillColor="#00aa00",
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

        # Draw the downwind leg line
        edge_line = dl.Polyline(
            id='rectcourse-preview-edge',
            positions=[[start_lat, start_lon], [end_lat, end_lon]],
            color="#cc0000",  # Red for downwind
            weight=4,
            dashArray="10, 5",  # Dashed to show it's a preview
            children=dl.Tooltip(f"Downwind Leg: {dist_nm:.2f} nm, Track {bearing:.0f}°")
        )

        # End marker
        end_marker = dl.CircleMarker(
            id='rectcourse-preview-end',
            center=[end_lat, end_lon],
            radius=8,
            color="#cc6600",
            fill=True,
            fillColor="#cc6600",
            fillOpacity=0.8,
            children=dl.Tooltip("Downwind End")
        )

        # Midpoint marker (on the downwind leg itself)
        mid_marker = dl.CircleMarker(
            id='rectcourse-preview-center',
            center=[mid_lat, mid_lon],
            radius=5,
            color="#FFD700",
            fill=True,
            fillColor="#FFD700",
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


# === Rectangular Course Edge Info Display ===
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


# === Impossible Turn Time Scrubber Callback ===
@app.callback(
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("impossibleturn-time-slider", "value"),
    State("impossibleturn-hover-store", "data"),
    State("impossibleturn-path-store", "data"),
    prevent_initial_call=True
)
def update_impossibleturn_scrubber(slider_value, hover_data, path_data):
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

    # Use 'phase' for impossible turn, fallback to 'segment'
    phase = pt.get('phase', pt.get('segment', 'turn'))
    slip_pct = pt.get('slip_pct', 0)

    tooltip_content = [
        html.Div(f"{phase.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
        html.Div(f"Altitude: {pt.get('alt', pt.get('alt_agl', 0)):.0f} ft AGL"),
        html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
        html.Div(f"TAS: {pt.get('tas', pt.get('ias', 0)):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
        html.Div(f"AOB: {'L ' if pt.get('aob', pt.get('bank', 0)) < 0 else ('R ' if pt.get('aob', pt.get('bank', 0)) > 0 else '')}{abs(pt.get('aob', pt.get('bank', 0))):.1f}°"),
        html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
        html.Div(f"Slip: {slip_pct:.0f}%", style={"color": "#fd7e14" if slip_pct > 0 else "#666", "fontWeight": "bold" if slip_pct > 0 else "normal"}),
    ]

    heading = pt.get('heading', 0)
    bank = pt.get('aob', pt.get('bank', 0))
    crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
    return [marker]



# === Rectangular Course Draw Callback ===
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

    # Single red path for consistency
    path_line = dl.Polyline(positions=path, color="red", weight=3)

    # Entry/Exit marker (at the intercept point on downwind - path start and end)
    elements = [path_line]
    if path:
        entry_marker = dl.CircleMarker(
            center=path[0],
            radius=7,
            color="green",
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

    # Performance data - standardized format
    info_elements.append(
        dbc.Accordion([
            dbc.AccordionItem([
                html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb | IAS: {ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {sim_warnings.get('wind_dir', 0):.0f}°/{sim_warnings.get('wind_speed', 0):.0f} kt", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"AOB: {sim_warnings.get('min_bank_achieved', 0):.0f}-{max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {sim_warnings.get('min_groundspeed', 0):.0f}-{sim_warnings.get('max_groundspeed', 0):.0f} kt", style={"fontSize": "11px"}),
                html.Div(f"DW: {dw_length_nm:.2f} nm | Lateral: {lateral_nm:.2f} nm | Crab: {sim_warnings.get('max_crab_angle', 0):.1f}°", style={"fontSize": "11px"}),
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


# === Rectangular Course Time Scrubber Callback ===
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
    except:
        crab_val = 0
    marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab_val)

    return [marker]


@callback(
    Output({"type": "point-store", "m_id": ALL, "role": ALL}, "data", allow_duplicate=True),
    Output("active-click-target", "data", allow_duplicate=True),
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("reset-all", "n_clicks"),
    Input("reset-clicks", "n_clicks"),
    State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
    prevent_initial_call=True
)
def handle_resets(n_reset_all, n_reset_clicks, store_ids):
    trigger = ctx.triggered_id
    if trigger not in ("reset-all", "reset-clicks"):
        raise PreventUpdate

    # Clear every point-store, regardless of maneuver
    cleared_points = [None] * len(store_ids)

    # Clear click target so map clicks do not overwrite anything until re-armed
    cleared_target = None

    # Clear the drawing layer and bounds
    cleared_layer = []
    cleared_bounds = None

    # Clear scrubber layer
    cleared_scrubber = []

    return cleared_points, cleared_target, cleared_layer, cleared_bounds, cleared_scrubber

@app.callback(
    Output("disclaimer-modal", "is_open"),
    Output("terms-policy-modal", "is_open"),
    Output("quickstart-modal", "is_open"),
    Input("open-disclaimer", "n_clicks"),
    Input("close-disclaimer", "n_clicks"),
    Input("open-terms-policy", "n_clicks"),
    Input("close-terms-policy", "n_clicks"),
    Input("open-quickstart", "n_clicks"),
    Input("close-quickstart", "n_clicks"),
    State("disclaimer-modal", "is_open"),
    State("terms-policy-modal", "is_open"),
    State("quickstart-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_legal_modals(open_disc, close_disc, open_terms, close_terms, open_qs, close_qs, disc_open, terms_open, qs_open):
    trigger = ctx.triggered_id

    if trigger == "open-disclaimer":
        return True, False, False
    if trigger == "close-disclaimer":
        return False, terms_open, qs_open
    if trigger == "open-terms-policy":
        return disc_open, True, False
    if trigger == "close-terms-policy":
        return disc_open, False, qs_open
    if trigger == "open-quickstart":
        return False, False, True
    if trigger == "close-quickstart":
        return disc_open, terms_open, False

    return no_update, no_update, no_update


# === Windsock Indicator Callback ===
@app.callback(
    Output("windsock-overlay", "children"),
    Input("env-wind-dir", "value"),
    Input("env-wind-speed", "value"),
    Input("url", "pathname"),  # Trigger on page load
)
def update_windsock(wind_dir, wind_speed, _pathname):
    """
    Update the windsock indicator based on wind direction and speed.
    Top-down view: length represents how extended the sock is.

    Wind speed indication (FAA standard):
    - Under 3 kt: very short (limp, hanging down)
    - 3 kt: ~20% extended
    - 6 kt: ~40% extended
    - 9 kt: ~60% extended
    - 12 kt: ~80% extended
    - 15+ kt: fully extended
    - 40+ kt: windsock blew away! 🌪️
    """
    # Parse values (use same defaults as input fields: dir=360, speed=0)
    wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 360
    wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0

    # Easter egg: windsock blew away in extreme wind!
    if wind_speed_val > 40:
        label_text = f"{int(wind_dir_val):03d}° @ {int(wind_speed_val)} kt"
        return [
            html.Div(
                "🌪️",
                style={"fontSize": "32px", "width": "60px", "height": "60px", "display": "flex", "alignItems": "center", "justifyContent": "center"}
            ),
            html.Span(
                label_text,
                style={
                    "fontSize": "12px",
                    "fontWeight": "bold",
                    "color": "#333",
                    "whiteSpace": "nowrap",
                    "marginLeft": "4px"
                }
            )
        ]

    # Wind FROM direction - windsock points in the direction wind is blowing TO
    sock_rotation = (wind_dir_val + 180) % 360
    # SVG sock points right (east=90°), so rotate accordingly
    svg_rotation = sock_rotation - 90

    # Calculate number of segments to show based on wind speed (FAA: 3 kt per segment, 5 segments)
    # 0 kt = 0 segments, 3 kt = 1, 6 kt = 2, 9 kt = 3, 12 kt = 4, 15+ kt = 5
    if wind_speed_val <= 4:
        num_visible = 0  # Calm wind (4 kts or less) shows limp sock
    else:
        num_visible = min(5, int((wind_speed_val + 2) / 3))  # +2 for rounding up at thresholds

    # SVG dimensions - square for clean rotation
    # Pivot point at center so windsock is always visible regardless of rotation
    svg_size = 60
    pivot_x = 30  # Center of SVG
    pivot_y = 30
    pole_length = 5
    pole_end_x = pivot_x + pole_length

    # Build segments - each segment is a tapered trapezoid
    # Full sock: 5 segments, each 5px wide, tapering from 10px (30% wider base) to 3px height
    segments_svg = ""
    segment_width = 5
    start_height = 10  # 30% wider than original 8px
    end_height = 3

    for i in range(num_visible):
        # Calculate this segment's position and size
        x1 = pole_end_x + i * segment_width
        x2 = x1 + segment_width

        # Taper calculation
        t1 = i / 5
        t2 = (i + 1) / 5
        h1 = start_height - (start_height - end_height) * t1
        h2 = start_height - (start_height - end_height) * t2

        # Trapezoid points (top-left, top-right, bottom-right, bottom-left)
        y1_top = pivot_y - h1 / 2
        y1_bot = pivot_y + h1 / 2
        y2_top = pivot_y - h2 / 2
        y2_bot = pivot_y + h2 / 2

        segments_svg += f'<polygon points="{x1},{y1_top} {x2},{y2_top} {x2},{y2_bot} {x1},{y1_bot}" fill="#FF6600" stroke="#CC5500" stroke-width="0.5"/>'

    # If no wind, show a small circle to indicate limp sock
    if num_visible == 0:
        segments_svg = f'<circle cx="{pole_end_x + 3}" cy="{pivot_y}" r="3" fill="#FF6600" stroke="#CC5500" stroke-width="0.5"/>'

    # Build windsock SVG - pivot point is at center so it's always visible
    windsock_svg = f'''
    <svg width="{svg_size}" height="{svg_size}" viewBox="0 0 {svg_size} {svg_size}"
         style="transform: rotate({svg_rotation}deg); transform-origin: {pivot_x}px {pivot_y}px;">
        <!-- Pole base (pivot point) -->
        <circle cx="{pivot_x}" cy="{pivot_y}" r="2.5" fill="#666"/>
        <!-- Pole arm -->
        <line x1="{pivot_x}" y1="{pivot_y}" x2="{pole_end_x}" y2="{pivot_y}" stroke="#666" stroke-width="2"/>
        <!-- Windsock segments (top-down view, length = extension) -->
        {segments_svg}
    </svg>
    '''

    # Format the label - always show exact values from input fields
    label_text = f"{int(wind_dir_val):03d}° @ {int(wind_speed_val)} kt"

    return [
        html.Div(
            html.Iframe(
                srcDoc=f'<html><body style="margin:0;padding:0;overflow:hidden;background:transparent;">{windsock_svg}</body></html>',
                style={"width": f"{svg_size}px", "height": f"{svg_size}px", "border": "none", "overflow": "hidden", "background": "transparent"}
            ),
            style={"width": f"{svg_size}px", "height": f"{svg_size}px", "flexShrink": "0"}
        ),
        html.Span(
            label_text,
            style={
                "fontSize": "12px",
                "fontWeight": "600",
                "color": "#333",
                "whiteSpace": "nowrap",
            }
        ),
    ]


if __name__ == "__main__":
    # host="0.0.0.0" allows access from other devices on the network.
    # Port is overridable via CLI arg (used by `make run PORT=8052`).
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8050
    app.run(debug=True, host="0.0.0.0", port=port)
