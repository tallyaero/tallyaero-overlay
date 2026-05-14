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

from dash import no_update
from dash.exceptions import PreventUpdate

@app.callback(
    Output("active-click-target", "data", allow_duplicate=True),
    Input({"type": "click-button", "m_id": ALL, "role": ALL}, "n_clicks"),
    State("maneuver-select", "value"),
    prevent_initial_call=True
)
def set_active_click_target(n_clicks_list, maneuver):
    if not ctx.triggered_id:
        raise PreventUpdate

    trig = ctx.triggered_id  # dict: {type, m_id, role}
    if not isinstance(trig, dict):
        raise PreventUpdate

    # Only accept clicks for the currently selected maneuver
    if trig.get("m_id") != maneuver:
        raise PreventUpdate

    return {"m_id": trig.get("m_id"), "role": trig.get("role")}

@app.callback(
    Output({"type": "click-status", "m_id": MATCH}, "children", allow_duplicate=True),
    Input({"type": "click-button", "m_id": MATCH, "role": ALL}, "n_clicks"),
    prevent_initial_call=True
)
def show_click_prompt(n_clicks_list):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered_id = ctx.triggered_id
    role = triggered_id.get("role")
    return f"🖱 Click on the map to set the {role.replace('_', ' ')} point."

from dash import no_update
from dash.exceptions import PreventUpdate

from dash import no_update
from dash.exceptions import PreventUpdate

from dash import no_update
from dash.exceptions import PreventUpdate

@app.callback(
    Output({"type": "point-store", "m_id": ALL, "role": ALL}, "data", allow_duplicate=True),
    Output("active-click-target", "data", allow_duplicate=True),
    Output("layer", "children", allow_duplicate=True),
    Output("click_debug", "children", allow_duplicate=True),
    Output("last-click-info", "data"),
    Input("map", "clickData"),
    State("active-click-target", "data"),
    State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
    State({"type": "point-store", "m_id": ALL, "role": ALL}, "data"),
    State("layer", "children"),
    State("pylons-ias-store", "data"),
    State("pylons-bank-store", "data"),
    State("env-wind-speed", "value"),
    prevent_initial_call=True
)
def write_point_to_scoped_store(click, target, store_ids, store_data, layer_children, pylons_ias, pylons_bank, wind_speed):
    if not click or "latlng" not in click or not isinstance(target, dict):
        raise PreventUpdate

    m_id = target.get("m_id")
    role = target.get("role")
    if not m_id or not role:
        raise PreventUpdate

    lat = click["latlng"]["lat"]
    lon = click["latlng"]["lng"]
    elev = get_elevation(lat, lon)

    # Minimum pylon distance enforcement for Eights on Pylons
    # Distance is calculated based on turn radius = 2 × radius so circles don't overlap
    # Turn radius R = V² / (g × tan(bank)), where V is groundspeed in ft/s
    min_pylon_distance_warning = None

    if m_id == "pylons" and role == "pylon_b":
        import math

        # Calculate dynamic minimum distance based on aircraft performance
        ias_kt = float(pylons_ias) if pylons_ias else 100
        bank_deg = float(pylons_bank) if pylons_bank else 30
        wind_kt = float(wind_speed) if wind_speed else 0

        # Approximate groundspeed (worst case: direct tailwind adds to speed)
        gs_kt = ias_kt + wind_kt
        gs_fps = gs_kt * 1.68781  # Convert to ft/s

        # Turn radius: R = V² / (g × tan(bank))
        g_fps2 = 32.174
        bank_rad = math.radians(bank_deg)
        if bank_rad > 0.01:  # Avoid division by zero
            turn_radius_ft = (gs_fps ** 2) / (g_fps2 * math.tan(bank_rad))
        else:
            turn_radius_ft = 10000  # Large default if bank is near zero

        # Minimum distance = 2 × turn radius (so circles just touch)
        # Add 10% margin for realistic transition
        min_distance_ft = turn_radius_ft * 2.2
        MIN_PYLON_DISTANCE_NM = min_distance_ft / 6076.12

        # Find pylon_a data to check distance
        pylon_a_data = None
        for i, sid in enumerate(store_ids):
            if isinstance(sid, dict) and sid.get("m_id") == "pylons" and sid.get("role") == "pylon_a":
                pylon_a_data = store_data[i]
                break

        if pylon_a_data and pylon_a_data.get("lat") and pylon_a_data.get("lon"):
            from geopy import Point as GeoPoint
            from geopy.distance import distance as geo_dist
            from physics import calculate_initial_compass_bearing, point_from

            pylon_a_geo = GeoPoint(pylon_a_data["lat"], pylon_a_data["lon"])
            clicked_geo = GeoPoint(lat, lon)

            # Calculate distance between pylons
            dist_nm = geo_dist(pylon_a_geo, clicked_geo).nm

            if dist_nm < MIN_PYLON_DISTANCE_NM:
                # Clicked too close - move pylon_b to minimum distance along the clicked bearing
                bearing = calculate_initial_compass_bearing(pylon_a_geo, clicked_geo)
                adjusted_pt = point_from(pylon_a_geo, bearing, MIN_PYLON_DISTANCE_NM)
                lat = adjusted_pt.latitude
                lon = adjusted_pt.longitude
                elev = get_elevation(lat, lon)
                min_pylon_distance_warning = f"Min {MIN_PYLON_DISTANCE_NM:.2f} NM for {ias_kt:.0f}kt/{bank_deg:.0f}° (clicked {dist_nm:.2f} NM)"

    new_pt = {"lat": lat, "lon": lon, "elevation_ft": elev}

    # ----- write to the correct scoped store -----
    updated = list(store_data)  # same order as store_ids
    wrote = False
    for i, sid in enumerate(store_ids):
        if isinstance(sid, dict) and sid.get("m_id") == m_id and sid.get("role") == role:
            updated[i] = new_pt
            wrote = True
            break

    if not wrote:
        raise PreventUpdate

    # ----- immediate marker on the map -----
    layer_children = layer_children or []

    marker_id = {"type": "pt-marker", "m_id": m_id, "role": role}

    kept = []
    for child in layer_children:
        try:
            # Drop any existing marker for this exact (m_id, role)
            if getattr(child, "id", None) != marker_id:
                kept.append(child)
        except Exception:
            kept.append(child)

    # Color convention
    color = "green"
    if role == "touchdown":
        color = "red"
    elif role in ("impact", "failure", "engine_failure"):
        color = "black"
    elif role in ("ref", "reference", "center"):
        color = "blue"
    elif role in ("entry", "start"):
        color = "green"
    elif role == "dw_start":
        color = "green"
    elif role == "dw_end":
        color = "orange"

    marker = dl.CircleMarker(
        id=marker_id,
        center=[lat, lon],
        radius=7,
        color=color,
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip(f"{m_id} {role}: {lat:.5f}, {lon:.5f}")
    )

    new_layer = kept + [marker]

    # Click confirmation feedback (minimal)
    role_display = role.replace("_", " ").title()
    if min_pylon_distance_warning:
        # Show warning when pylon was adjusted due to minimum distance
        feedback = html.Div([
            html.Div([
                html.Span("⚠", style={"color": "#e67e22", "fontSize": "8px", "marginRight": "3px"}),
                html.Span(min_pylon_distance_warning, style={"fontSize": "8px", "color": "#e67e22"}),
            ]),
            html.Div([
                html.Span("✓", style={"color": "#aaa", "fontSize": "6px", "marginRight": "2px"}),
                html.Span(f"{role_display} adjusted: {lat:.4f}, {lon:.4f}", style={"fontSize": "7px", "color": "#999"}),
            ]),
        ], style={"padding": "1px 0", "marginTop": "1px", "lineHeight": "1.2"})
    else:
        feedback = html.Div([
            html.Span("✓", style={"color": "#aaa", "fontSize": "6px", "marginRight": "2px"}),
            html.Span(f"{role_display}: {lat:.4f}, {lon:.4f}", style={"fontSize": "7px", "color": "#999"}),
        ], style={"padding": "1px 0", "marginTop": "1px", "lineHeight": "1"})

    # Save last click info for undo
    last_click = {"m_id": m_id, "role": role, "store_index": None}
    for i, sid in enumerate(store_ids):
        if isinstance(sid, dict) and sid.get("m_id") == m_id and sid.get("role") == role:
            last_click["store_index"] = i
            break

    # Clear target after one successful click so extra clicks don't overwrite
    return updated, None, new_layer, feedback, last_click

@app.callback(
    Output({"type": "click-status", "m_id": MATCH}, "children", allow_duplicate=True),
    Input({"type": "point-store", "m_id": MATCH, "role": ALL}, "data"),
    State({"type": "point-store", "m_id": MATCH, "role": ALL}, "id"),
    prevent_initial_call=True
)
def summarize_points(points, ids):
    parts = []
    for pid, pdata in zip(ids, points):
        role = pid.get("role", "point").replace("_", " ")
        if isinstance(pdata, dict) and pdata.get("lat") is not None and pdata.get("lon") is not None:
            lat = pdata["lat"]
            lon = pdata["lon"]
            elev = pdata.get("elevation_ft")
            if role == "touchdown" and elev is not None:
                parts.append(f"✅ {role} set ({lat:.4f}, {lon:.4f}) elev {int(round(elev))} ft")
            else:
                parts.append(f"✅ {role} set ({lat:.4f}, {lon:.4f})")
        else:
            parts.append(f"⬜ {role} not set")
    return " | ".join(parts)


# === Undo Last Click Callback ===
@app.callback(
    Output({"type": "point-store", "m_id": ALL, "role": ALL}, "data", allow_duplicate=True),
    Output("layer", "children", allow_duplicate=True),
    Output("click_debug", "children", allow_duplicate=True),
    Output("last-click-info", "data", allow_duplicate=True),
    Input("undo-last-click", "n_clicks"),
    State("last-click-info", "data"),
    State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
    State({"type": "point-store", "m_id": ALL, "role": ALL}, "data"),
    State("layer", "children"),
    prevent_initial_call=True
)
def undo_last_click(n_clicks, last_click, store_ids, store_data, layer_children):
    """Undo the last point that was clicked."""
    if not n_clicks or not last_click:
        raise PreventUpdate

    m_id = last_click.get("m_id")
    role = last_click.get("role")
    if not m_id or not role:
        raise PreventUpdate

    # Clear the point store for the last click
    updated = list(store_data)
    for i, sid in enumerate(store_ids):
        if isinstance(sid, dict) and sid.get("m_id") == m_id and sid.get("role") == role:
            updated[i] = None
            break

    # Remove marker from layer
    marker_id = {"type": "pt-marker", "m_id": m_id, "role": role}
    layer_children = layer_children or []
    new_layer = [c for c in layer_children if getattr(c, "id", None) != marker_id]

    # Feedback (minimal)
    role_display = role.replace("_", " ").title()
    feedback = html.Div([
        html.Span("↩", style={"color": "#aaa", "fontSize": "6px", "marginRight": "2px"}),
        html.Span(f"{role_display} cleared", style={"color": "#999", "fontSize": "7px"}),
    ], style={"padding": "1px 0", "marginTop": "1px", "lineHeight": "1"})

    return updated, new_layer, feedback, None


# === Elevation ===

from dash import no_update
from dash.exceptions import PreventUpdate

@app.callback(
    Output("engineout-manual-elev", "value"),
    Input({"type": "point-store", "m_id": "engineout", "role": "touchdown"}, "data"),
    State("maneuver-select", "value"),
    prevent_initial_call=True
)
def autofill_engineout_touchdown_elev(td_data, maneuver):
    if maneuver != "engineout":
        raise PreventUpdate
    if not isinstance(td_data, dict):
        raise PreventUpdate

    elev = td_data.get("elevation_ft")
    if elev is None:
        raise PreventUpdate

    return int(round(elev))

def get_elevation(lat, lon):
    if lat is None or lon is None:
        return None

    try:
        url = "https://api.open-meteo.com/v1/elevation"
        r = requests.get(url, params={"latitude": lat, "longitude": lon}, timeout=5)
        r.raise_for_status()
        data = r.json()

        elev_m = data.get("elevation")
        if isinstance(elev_m, list) and elev_m:
            elev_m = elev_m[0]

        if elev_m is None:
            return None

        return int(round(float(elev_m) * 3.28084))
    except Exception as e:
        log.error(f"Open-Meteo elevation lookup failed: {e}")
        return None

@app.callback(
    Output("click_debug", "children"),
    Input("map", "clickData"),
    prevent_initial_call=True
)
def display_click_location(click):
    if not click or "latlng" not in click:
        raise dash.exceptions.PreventUpdate

    lat = click["latlng"]["lat"]
    lon = click["latlng"]["lng"]
    return f"🗺️ Location clicked: {lat:.5f}, {lon:.5f}"


def calculate_runway_geometry(threshold_lat, threshold_lon, heading_deg, length_ft, width_ft=100):
    """
    Calculate runway polygon coordinates for map overlay.

    Args:
        threshold_lat: Latitude of runway threshold (clicked point)
        threshold_lon: Longitude of runway threshold
        heading_deg: Runway heading in degrees
        length_ft: Runway length in feet
        width_ft: Runway width in feet (default 100 ft)

    Returns:
        List of [lat, lon] coordinates for polygon corners
    """
    from physics import point_from, FT_PER_NM
    from geopy import Point as GeoPoint

    # Convert feet to nautical miles
    length_nm = length_ft / FT_PER_NM
    width_nm = width_ft / FT_PER_NM

    # Create threshold point object
    threshold = GeoPoint(threshold_lat, threshold_lon)

    # Calculate opposite threshold
    opposite = point_from(threshold, heading_deg, length_nm)

    # Calculate perpendicular heading for width
    perp_left = (heading_deg - 90) % 360
    perp_right = (heading_deg + 90) % 360
    half_width_nm = width_nm / 2

    # Corner 1: threshold left
    c1 = point_from(threshold, perp_left, half_width_nm)
    # Corner 2: threshold right
    c2 = point_from(threshold, perp_right, half_width_nm)
    # Corner 3: opposite right
    c3 = point_from(opposite, perp_right, half_width_nm)
    # Corner 4: opposite left
    c4 = point_from(opposite, perp_left, half_width_nm)

    return [
        [c1.latitude, c1.longitude],
        [c2.latitude, c2.longitude],
        [c3.latitude, c3.longitude],
        [c4.latitude, c4.longitude],
        [c1.latitude, c1.longitude],  # Close the polygon
    ]


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

# === Power-Off 180 Rendering Callback ===
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

# ============== Engine-Out Glide Rendering Callback ======================#

# === Engine-Out Glide Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output({"type": "click-status", "m_id": "engineout"}, "children", allow_duplicate=True),
    Output("engineout-hover-store", "data"),
    Output("engineout-path-store", "data"),
    Output("engineout-slider-container", "style"),
    Output("engineout-time-slider", "max"),
    Output("engineout-time-slider", "marks"),
    Output("engineout-time-slider", "value"),
    Output("engineout-info", "children"),
    Output("engineout-envelope-store", "data"),
    Output("engineout-min-alt-result", "children"),
    Input("engineout-draw-btn", "n_clicks"),
    State({"type": "point-store", "m_id": "engineout", "role": "start"}, "data"),
    State({"type": "point-store", "m_id": "engineout", "role": "touchdown"}, "data"),
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
    State("engineout-start-heading", "value"),
    State("engineout-altitude", "value"),
    State("engineout-flap-setting", "value"),
    State("engineout-prop-condition", "value"),
    State("engineout-runway-select", "value"),
    State("engineout-touchdown-heading", "value"),
    State("engineout-manual-elev", "value"),
    State("engineout-reaction-time", "value"),
    State("engineout-max-bank", "value"),
    State("engineout-speed-tau", "value"),
    State("engineout-bank-tau", "value"),
    State("engineout-show-envelope", "value"),
    State("selected-airport-id", "data"),
    State("runtime-total-weight-lb", "data"),
    prevent_initial_call=True,
)
def draw_engineout(
    n_clicks,
    start_data,
    touchdown_data,
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
    start_heading,
    start_alt_agl,
    flap_setting,
    prop_condition,
    runway_select,
    manual_touchdown_heading,
    manual_td_elev,
    reaction_time,
    max_bank,
    speed_tau,
    bank_tau,
    show_envelope,
    selected_airport_id,
    runtime_weight
):
    if not n_clicks:
        raise PreventUpdate

    # 12 outputs: layer, bounds, status, hover_store, path_store, slider_style, max, marks, value, info, envelope, min_alt
    empty_return = [], None, "", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], ""

    if not start_data or not touchdown_data:
        return [], None, "⚠️ Set start and touchdown points first.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], ""

    if not ac_name or not engine_key:
        return [], None, "⚠️ Select aircraft and engine first.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], ""

    try:
        states = dash.callback_context.states

        def safe_float(key, default=None):
            val = states.get(key)
            if val in [None, "", "null"]:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        start_heading      = safe_float("engineout-start-heading.value")
        start_alt_agl      = safe_float("engineout-altitude.value")
        manual_td_elev     = safe_float("engineout-manual-elev.value")
        wind_dir           = safe_float("env-wind-dir.value")
        wind_speed         = safe_float("env-wind-speed.value")
        oat_f              = safe_float("env-oat.value")
        altimeter          = safe_float("env-altimeter.value")
        reaction_time      = safe_float("engineout-reaction-time.value", 2.0)
        max_bank           = safe_float("engineout-max-bank.value", 45.0)
        speed_tau          = safe_float("engineout-speed-tau.value", 4.0)
        bank_tau           = safe_float("engineout-bank-tau.value", 1.5)

        total_wt = safe_float("runtime-total-weight-lb.data")
        if total_wt is None:
            total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None

        # Get touchdown heading from runway dropdown or manual input
        touchdown_heading = None
        selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
        airport_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

        if runway_select and selected_airport:
            # Get heading from selected runway
            runways = selected_airport.get("runways", [])
            selected_rwy = next((r for r in runways if r.get("id") == runway_select), None)
            if selected_rwy:
                touchdown_heading = float(selected_rwy.get("heading", 0))

        # Fall back to manual heading if no runway selected
        if touchdown_heading is None:
            manual_hdg = safe_float("engineout-touchdown-heading.value")
            if manual_hdg is not None:
                touchdown_heading = manual_hdg
            else:
                return [], None, "⚠️ Select a runway or enter manual heading.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], ""

        required = [
            start_heading, start_alt_agl, touchdown_heading,
            wind_dir, wind_speed, oat_f, altimeter,
            total_wt
        ]
        if any(x is None for x in required):
            return [], None, "⚠️ Missing or invalid input values.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], ""

        start = GeoPoint(start_data["lat"], start_data["lon"])
        touchdown = GeoPoint(touchdown_data["lat"], touchdown_data["lon"])

        ac = dict(aircraft_data[ac_name])
        ac["total_weight_lb"] = float(total_wt)

        td_store_elev = touchdown_data.get("elevation_ft") if isinstance(touchdown_data, dict) else None

        if manual_td_elev is not None:
            touchdown_elev_ft = float(manual_td_elev)
        elif td_store_elev is not None:
            touchdown_elev_ft = float(td_store_elev)
        else:
            touchdown_elev_ft = float(airport_elev_ft)

        oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0

        path, hover_data, meta = simulate_engineout_glide(
            start_point=start,
            start_heading=float(start_heading),
            touchdown_point=touchdown,
            touchdown_heading=float(touchdown_heading),
            ac=ac,
            engine_option=engine_key,
            weight_lbs=float(total_wt),
            flap_config=flap_setting,
            prop_config=prop_condition,
            oat_c=float(oat_c),
            altimeter_inhg=float(altimeter),
            wind_dir=float(wind_dir),
            wind_speed=float(wind_speed),
            altitude_agl=float(start_alt_agl),
            touchdown_elev_ft=float(touchdown_elev_ft),
            max_bank_deg=float(max_bank),
            reaction_sec=float(reaction_time),
            speed_tau_sec=float(speed_tau),
            bank_tau_sec=float(bank_tau),
            timestep_sec=0.5,
        )

        if not path or not hover_data:
            return [], None, "⚠️ No glide path generated. Check inputs.", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], ""

        # Extract success/impact info from meta
        success = meta.get("success", False)
        impact_point = meta.get("impact_point")  # (lat, lon) or None
        turn_direction = meta.get("turn_direction", "auto")

        # ---------- Auto-calculate minimum altitude ----------
        min_alt_display = ""
        try:
            min_alt, _, _, _ = find_minimum_altitude(
                start_point=start,
                start_heading=float(start_heading),
                touchdown_point=touchdown,
                touchdown_heading=float(touchdown_heading),
                ac=ac,
                engine_option=engine_key,
                weight_lbs=float(total_wt),
                flap_config=flap_setting or "clean",
                prop_config=prop_condition or "windmilling",
                oat_c=oat_c,
                altimeter_inhg=float(altimeter),
                wind_dir=float(wind_dir),
                wind_speed=float(wind_speed),
                touchdown_elev_ft=touchdown_elev_ft,
                max_bank_deg=float(max_bank),
                reaction_sec=float(reaction_time),
                alt_low=100.0,
                alt_high=5000.0,
                resolution=25.0,
            )
            min_alt_display = f"📐 Minimum Altitude Required: {min_alt:.0f} ft AGL"
        except Exception as min_err:
            log.warning(f"Min altitude calc error: {min_err}")
            min_alt_display = "⚠️ Could not calculate minimum altitude"

        # ---------- Core visuals: full glide track ----------
        # Color-code path by phase if available
        arc_line = dl.Polyline(positions=path, color="red", weight=3)

        # Start / touchdown markers
        start_marker = dl.CircleMarker(
            center=[start.latitude, start.longitude],
            radius=7,
            color="green",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip("Engine Failure Point"),
        )
        touchdown_marker = dl.CircleMarker(
            center=[touchdown.latitude, touchdown.longitude],
            radius=7,
            color="blue",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip("Target Touchdown"),
        )

        elements = [start_marker, touchdown_marker, arc_line]

        # Compute and show glide envelope if enabled
        envelope_data = []
        if show_envelope and "show" in show_envelope:
            # Get glide ratio from hover data or calculate
            avg_gr = 9.0  # Default
            if hover_data:
                gr_values = [h.get("glide_ratio", 9.0) for h in hover_data if h.get("glide_ratio")]
                avg_gr = sum(gr_values) / len(gr_values) if gr_values else 9.0

            # Get TAS
            avg_tas = 80.0
            if hover_data:
                tas_values = [h.get("tas", 80) for h in hover_data if h.get("tas")]
                avg_tas = sum(tas_values) / len(tas_values) if tas_values else 80.0

            envelope = compute_glide_envelope(
                start_point=start,
                altitude_ft=float(start_alt_agl),
                glide_ratio=avg_gr,
                wind_dir=float(wind_dir),
                wind_speed=float(wind_speed),
                tas_knots=avg_tas,
                num_points=36,
            )
            envelope_data = [[lat, lon] for lat, lon in envelope]

            if envelope_data:
                envelope_polygon = dl.Polygon(
                    positions=envelope_data,
                    color="orange",
                    weight=2,
                    fillColor="orange",
                    fillOpacity=0.15,
                    children=dl.Tooltip("Max glide distance ring"),
                )
                elements.insert(0, envelope_polygon)  # Add behind other elements

        # Impact vs success messaging / marker
        if impact_point and isinstance(impact_point, (list, tuple)):
            impact_lat, impact_lon = impact_point[0], impact_point[1]
            impact_mark = dl.CircleMarker(
                center=[impact_lat, impact_lon],
                radius=7,
                color="black",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip("☠️ Impact Point"),
            )
            elements.append(impact_mark)
            failure_reason = meta.get("reason", "ground_impact")
            msg = f"⚠️ {failure_reason.replace('_', ' ').title()} at ({impact_lat:.4f}, {impact_lon:.4f})"
        else:
            msg = "✅ Engine-out glide successful."

        # ---------- Bounds ----------
        lats = [pt[0] for pt in path] + [start.latitude, touchdown.latitude]
        lons = [pt[1] for pt in path] + [start.longitude, touchdown.longitude]
        if impact_point and isinstance(impact_point, (list, tuple)):
            lats.append(impact_point[0])
            lons.append(impact_point[1])
        if envelope_data:
            lats.extend([pt[0] for pt in envelope_data])
            lons.extend([pt[1] for pt in envelope_data])

        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

        # Build slider marks based on time
        max_time = hover_data[-1].get("time", 100) if hover_data else 100
        slider_marks = {0: "Start", int(max_time): "End"}

        # Prepare hover data for store (ensure JSON-serializable)
        hover_store = [
            {
                "time": pt.get("time", 0),
                "phase": pt.get("phase", "glide"),
                "bucket": pt.get("bucket", ""),
                "alt": pt.get("alt", 0),
                "ias": pt.get("ias", 0),
                "tas": pt.get("tas", 0),
                "gs": pt.get("gs", pt.get("tas", 0)),
                "aob": pt.get("aob", 0),
                "vs": pt.get("vs", 0),
                "track": pt.get("track", 0),
                "heading": pt.get("heading", 0),
                "drift": pt.get("drift", 0),
                "glide_ratio": pt.get("glide_ratio", 0),
                "load_factor": pt.get("load_factor", 1),
                "stall_margin_kt": pt.get("stall_margin_kt", 0),
                "slipping": pt.get("slipping", False),
                "slip_pct": pt.get("slip_pct", 0),
                # Debug fields for abeam bucket capture diagnostics
                "dist_to_abeam": pt.get("dist_to_abeam", 0),
                "xtrack_abeam": pt.get("xtrack_abeam", 0),
                "along_abeam": pt.get("along_abeam", 0),
                "in_xtrack": pt.get("in_xtrack", ""),
                "in_along": pt.get("in_along", ""),
                "in_alt": pt.get("in_alt", ""),
                "in_hdg": pt.get("in_hdg", ""),
                "alt_range": pt.get("alt_range", ""),
                "abeam_bucket": pt.get("abeam_bucket", ""),
                "bucket_idx": pt.get("bucket_idx", 0),
                "bucket_chain": pt.get("bucket_chain", ""),
                "pattern_side": pt.get("pattern_side", ""),
                "trans_bucket": pt.get("trans_bucket", ""),
                "trans_alt": pt.get("trans_alt", ""),
                "trans_check": pt.get("trans_check", ""),
                # Spiral debug fields
                "spiral_n": pt.get("spiral_n", 0),
                "spiral_r": pt.get("spiral_r", 0),
                "spiral_alt_lose": pt.get("spiral_alt_lose", 0),
            }
            for pt in hover_data
        ]

        # Calculate glide metrics
        total_distance_nm = geo_distance(start, touchdown).nm if start and touchdown else 0
        avg_vs = 0
        avg_gs = 0
        avg_gr = 0
        if hover_data and len(hover_data) > 0:
            vs_values = [abs(pt.get('vs', 0)) for pt in hover_data if pt.get('vs') is not None]
            gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover_data if pt.get('gs') is not None]
            gr_values = [pt.get('glide_ratio', 0) for pt in hover_data if pt.get('glide_ratio')]
            avg_vs = sum(vs_values) / len(vs_values) if vs_values else 0
            avg_gs = sum(gs_values) / len(gs_values) if gs_values else 0
            avg_gr = sum(gr_values) / len(gr_values) if gr_values else 0

        # Extract phase information for display
        phases_seen = []
        if hover_data:
            current_phase = None
            for h in hover_data:
                phase = h.get("phase", "unknown")
                if phase != current_phase:
                    phases_seen.append(phase)
                    current_phase = phase

        phase_display = " → ".join(phases_seen) if phases_seen else "N/A"

        # Check for slip usage
        slip_used = any(h.get("slipping", False) for h in hover_data) if hover_data else False

        # Build info content with enhanced data
        status_color = "#28a745" if success else "#dc3545"
        status_text = "✅ TOUCHDOWN" if success else "❌ IMPACT"

        info_content = dbc.Accordion([
            dbc.AccordionItem([
                html.Div(status_text, style={"fontWeight": "bold", "color": status_color, "marginBottom": "8px", "fontSize": "13px"}),

                html.Div([html.Strong("Flight Phases")], style={"marginBottom": "4px"}),
                html.Div(phase_display, style={"fontSize": "10px", "color": "#555", "marginBottom": "8px", "wordWrap": "break-word"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                html.Div([html.Strong("Aircraft & Environment")], style={"marginBottom": "4px"}),
                html.Div(f"Weight: {total_wt:.0f} lb | Entry hdg: {start_heading:.0f}°", style={"fontSize": "11px"}),
                html.Div(f"Wind: {wind_dir:.0f}° at {wind_speed:.0f} kt | Flaps: {flap_setting or 'clean'}", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                html.Div([html.Strong("Glide Performance")], style={"marginBottom": "4px"}),
                html.Div(f"Avg G/R: {avg_gr:.1f}:1 | GS: {avg_gs:.0f} kt | VS: {avg_vs:.0f} fpm", style={"fontSize": "11px"}),
                html.Div(f"Distance: {total_distance_nm:.2f} nm | Start alt: {start_alt_agl:.0f} ft", style={"fontSize": "11px"}),
                html.Div(f"Slip used: {'Yes' if slip_used else 'No'}", style={"fontSize": "11px", "color": "#fd7e14" if slip_used else "#666"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),

                html.Div([html.Strong("Approach & Timing")], style={"marginBottom": "4px"}),
                html.Div(f"Turn direction: {turn_direction} | Runway: {touchdown_heading:.0f}°", style={"fontSize": "11px"}),
                html.Div(f"Total time: {max_time:.1f}s | Reaction: {reaction_time:.1f}s", style={"fontSize": "11px"}),
                html.Div(f"Max bank: {max_bank:.0f}° | Bank τ: {bank_tau:.1f}s", style={"fontSize": "11px"}),
            ], title="Simulation Results", style={"fontSize": "12px"}),
        ], start_collapsed=False, style={"marginTop": "8px"})

        return elements, bounds, msg, hover_store, path, {"display": "block"}, int(max_time), slider_marks, 0, info_content, envelope_data, min_alt_display

    except Exception as e:
        import traceback
        log.error(f"EXCEPTION in draw_engineout(): {e}")
        traceback.print_exc()
        return [], None, f"⚠️ Error generating path: {str(e)}", [], [], {"display": "none"}, 100, {0: "Start", 100: "End"}, 0, "", [], ""


# === Steep Turn Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output("steepturn-hover-store", "data"),
    Output("steepturn-path-store", "data"),
    Output("steepturn-slider-container", "style"),
    Output("steepturn-time-slider", "max"),
    Output("steepturn-time-slider", "marks"),
    Output("steepturn-time-slider", "value"),
    Output("steepturn-info", "children"),
    Input("steepturn-draw-btn", "n_clicks"),
    State({"type": "point-store", "m_id": "steep_turn", "role": "start"}, "data"),
    State("steepturn-bank-angle", "value"),
    State("steepturn-sequence", "value"),
    State("steepturn-entry-heading", "value"),
    State("steepturn-altitude", "value"),
    State("steepturn-ias", "value"),
    State("total-weight-display", "value"),
    State("env-oat", "value"),
    State("env-altimeter", "value"),
    State("env-wind-dir", "value"),
    State("env-wind-speed", "value"),
    State("aircraft-select", "value"),
    State("engine-select", "value"),
    State("runtime-total-weight-lb", "data"),
    State("selected-airport-id", "data"),
    prevent_initial_call=True
)
def draw_steep_turn(
    n_clicks,
    start,
    bank_angle,
    sequence,
    entry_heading,
    entry_alt_ft,
    entry_ias,
    weight_str,
    oat_f,
    altimeter_inhg,
    wind_dir,
    wind_speed,
    aircraft_name,
    engine_name,
    runtime_weight,
    selected_airport_id
):
    if not n_clicks or not start or not aircraft_name or not engine_name:
        raise PreventUpdate

    ac = aircraft_data[aircraft_name]

    # Use Va as default entry IAS if user left blank
    if int(ac.get("engine_count", 1)) > 1:
        va = float((ac.get("multi_engine_limits", {}) or {}).get("va", 100))
    else:
        va = float((ac.get("single_engine_limits", {}) or {}).get("va", 100))
    entry_ias = float(entry_ias) if entry_ias not in [None, "", "null"] else float(va)

    # Runtime weight should be authoritative. Fallback to parsing the display box.
    weight_lbs = None
    try:
        if runtime_weight not in [None, "", "null"]:
            weight_lbs = float(runtime_weight)
    except Exception:
        weight_lbs = None

    if weight_lbs is None:
        try:
            # total-weight-display is already just a number string in your UI ("1523"), so parse directly.
            weight_lbs = float(str(weight_str).replace(",", "").strip())
        except Exception:
            weight_lbs = float(ac.get("empty_weight", 1200.0)) + 180.0

    altitude_ft = float(entry_alt_ft) if entry_alt_ft not in [None, "", "null"] else float(ac.get("default_altitude", 1000.0))

    oat_c = None
    try:
        oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0
    except Exception:
        oat_c = (52.0 - 32.0) * 5.0 / 9.0

    # Pass runtime weight through the aircraft dict so any helper in utility.py can use it
    ac_rt = dict(ac)
    ac_rt["total_weight_lb"] = float(weight_lbs)

    # Get airport elevation for TAS calculation
    selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
    field_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

    # Parse altimeter setting
    altimeter_val = float(altimeter_inhg) if altimeter_inhg not in [None, "", "null"] else 29.92

    path, hover = simulate_steep_turn(
        entry_point={"lat": start["lat"], "lon": start["lon"]},
        entry_heading_deg=float(entry_heading),
        altitude_ft=float(altitude_ft),
        bank_angle_deg=float(bank_angle),
        turn_sequence=sequence,
        ias_knots=float(entry_ias),
        wind_dir_deg=float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0,
        wind_speed_kt=float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0,
        oat_c=float(oat_c),
        altimeter_inhg=float(altimeter_val),
        field_elev_ft=float(field_elev_ft),
    )

    if not path or not hover:
        raise PreventUpdate

    # Build elements matching other maneuvers' style
    # Red polyline for the path
    path_line = dl.Polyline(positions=path, color="red", weight=3)

    # Start marker (green, larger)
    start_marker = dl.CircleMarker(
        center=[start["lat"], start["lon"]],
        radius=7,
        color="green",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip("Start Point"),
    )

    # End marker (red, larger)
    end_marker = dl.CircleMarker(
        center=path[-1],
        radius=7,
        color="red",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip("End Point"),
    )

    elements = [start_marker, end_marker, path_line]

    # Prepare slider configuration
    num_points = len(hover)
    slider_max = max(0, num_points - 1)
    slider_marks = {0: "Start"}
    if slider_max > 0:
        slider_marks[slider_max] = "End"

    slider_style = {"display": "block", "marginTop": "10px"}

    # Calculate performance metrics from hover data
    if hover:
        gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover]
        tas_values = [pt.get('tas', 0) for pt in hover]
        aob_values = [abs(pt.get('aob', 0)) for pt in hover]

        min_gs = min(gs_values) if gs_values else 0
        max_gs = max(gs_values) if gs_values else 0
        avg_tas = sum(tas_values) / len(tas_values) if tas_values else entry_ias
        max_bank = max(aob_values) if aob_values else bank_angle
        total_time = hover[-1].get('time', 0) if hover else 0

        # Calculate load factor from bank angle: n = 1/cos(bank)
        import math
        load_factor = 1 / math.cos(math.radians(float(bank_angle))) if bank_angle else 1.0

        # Calculate turn radius: r = V² / (g * tan(bank))
        # V in ft/s, g = 32.2 ft/s²
        tas_fps = avg_tas * 1.68781  # knots to ft/s
        turn_radius_ft = (tas_fps ** 2) / (32.2 * math.tan(math.radians(float(bank_angle)))) if bank_angle else 0
        turn_radius_nm = turn_radius_ft / 6076.12

        # Calculate stall speed in turn: Vs_turn = Vs * sqrt(load_factor)
        vs_clean = float(ac.get("stall_speed_clean_kias", 48))
        vs_in_turn = vs_clean * math.sqrt(load_factor)

        # Get wind info
        wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 0
        wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0
    else:
        min_gs = max_gs = avg_tas = entry_ias
        max_bank = bank_angle
        total_time = 0
        load_factor = 1.0
        turn_radius_ft = turn_radius_nm = 0
        vs_clean = vs_in_turn = 0
        wind_dir_val = wind_speed_val = 0

    # Build info panel with standardized format
    info_content = dbc.Accordion([
        dbc.AccordionItem([
            html.Div(f"Weight: {weight_lbs:.0f} lb | IAS: {entry_ias:.0f} kt | TAS: {avg_tas:.0f} kt", style={"fontSize": "11px"}),
            html.Div(f"Wind: {wind_dir_val:.0f}° at {wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
            html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
            html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | Radius: {turn_radius_ft:.0f} ft", style={"fontSize": "11px"}),
            html.Div(f"GS: {min_gs:.0f}-{max_gs:.0f} kt | Vs turn: {vs_in_turn:.0f} kt | Margin: {entry_ias - vs_in_turn:.0f} kt", style={"fontSize": "11px"}),
            html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
            html.Div(f"Time: {total_time:.0f}s | {sequence.replace('-', ' → ').title()}", style={"fontSize": "11px"}),
        ], title="Simulation Results", style={"fontSize": "12px"}),
    ], start_collapsed=False, style={"marginTop": "8px"})

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


# === Chandelle Rendering Callback ===
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
    Input("chandelle-draw-btn", "n_clicks"),
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
    State("selected-airport-id", "data"),
    State("runtime-total-weight-lb", "data"),
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
    selected_airport_id,
    weight_lb
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

    # Start marker (green)
    start_marker = dl.CircleMarker(
        center=[start["lat"], start["lon"]],
        radius=7,
        color="green",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip("Entry Point"),
    )

    # End marker (red)
    end_marker = dl.CircleMarker(
        center=path[-1],
        radius=7,
        color="red",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip(f"Exit: {hover[-1].get('heading', 0):.0f}° hdg, {hover[-1].get('alt', 0):.0f} ft"),
    )

    elements = [start_marker, end_marker] + path_segments

    # Prepare slider configuration
    num_points = len(hover)
    slider_max = max(0, num_points - 1)
    slider_marks = {0: "Start"}
    if slider_max > 0:
        slider_marks[slider_max] = "End"
        # Add 90° point marker
        for i, pt in enumerate(hover):
            if abs(pt.get('turn_progress', 0) - 90) < 5:
                slider_marks[i] = "90°"
                break

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

    # Stall speed calculations
    vs_clean = float(ac.get("stall_speed_clean_kias", 48))
    vs_in_turn = vs_clean * math.sqrt(load_factor)
    min_ias = min([pt.get('tas', entry_ias) for pt in hover]) if hover else entry_ias

    # Build info panel with standardized format
    info_content = dbc.Accordion([
        dbc.AccordionItem([
            html.Div(f"Weight: {weight:.0f} lb | IAS: {entry_ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {wind_dir_val:.0f}°/{wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
            html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
            html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {min_gs:.0f}-{max_gs:.0f} kt", style={"fontSize": "11px"}),
            html.Div(f"Alt: {altitude_ft:.0f}→{exit_alt:.0f} ft (+{alt_gain:.0f}) | {direction.title()} 180°", style={"fontSize": "11px"}),
            html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
            html.Div(f"Vs turn: {vs_in_turn:.0f} kt | Margin: {min_ias - vs_in_turn:.0f} kt | Time: {total_time:.0f}s", style={"fontSize": "11px"}),
            html.Div([
                html.Span("Color: ", style={"fontSize": "10px"}),
                html.Span("■ Low", style={"color": "#ff0000", "fontSize": "10px", "marginRight": "6px"}),
                html.Span("■ Mid", style={"color": "#804080", "fontSize": "10px", "marginRight": "6px"}),
                html.Span("■ High", style={"color": "#0000ff", "fontSize": "10px"}),
            ], style={"marginTop": "4px"}),
        ], title="Simulation Results", style={"fontSize": "12px"}),
    ], start_collapsed=False, style={"marginTop": "8px"})

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


# === Lazy Eight Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output("lazy8-hover-store", "data"),
    Output("lazy8-path-store", "data"),
    Output("lazy8-slider-container", "style"),
    Output("lazy8-time-slider", "max"),
    Output("lazy8-time-slider", "marks"),
    Output("lazy8-time-slider", "value"),
    Output("lazy8-info", "children"),
    Input("lazy8-draw-btn", "n_clicks"),
    State({"type": "point-store", "m_id": "lazy8", "role": "start"}, "data"),
    State("lazy8-entry-heading", "value"),
    State("lazy8-entry-altitude", "value"),
    State("lazy8-ias", "value"),
    State("lazy8-bank-angle", "value"),
    State("lazy8-direction-sequence", "value"),
    State("env-oat", "value"),
    State("env-altimeter", "value"),
    State("env-wind-dir", "value"),
    State("env-wind-speed", "value"),
    State("aircraft-select", "value"),
    State("selected-airport-id", "data"),
    State("runtime-total-weight-lb", "data"),
    prevent_initial_call=True
)
def draw_lazy_eight(
    n_clicks,
    start,
    entry_heading,
    entry_alt_ft,
    entry_ias,
    bank_angle,
    first_turn_direction,
    oat_f,
    altimeter_inhg,
    wind_dir,
    wind_speed,
    aircraft_name,
    selected_airport_id,
    weight_lb
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

    # Get weight
    weight = float(weight_lb) if weight_lb not in [None, "", "null"] else ac.get("max_takeoff_weight", 2300.0)

    path, hover = simulate_lazy_eight(
        entry_point={"lat": start["lat"], "lon": start["lon"]},
        entry_heading_deg=heading,
        first_turn_direction=first_turn_direction,
        entry_altitude_ft=altitude_ft,
        entry_ias_knots=entry_ias,
        max_bank_angle_deg=bank,
        wind_dir_deg=float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0,
        wind_speed_kt=float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0,
        oat_c=oat_c,
        altimeter_inhg=altimeter_val,
        field_elev_ft=field_elev_ft,
        ac=ac,
        weight_lb=weight,
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

    # Start marker (green)
    start_marker = dl.CircleMarker(
        center=[start["lat"], start["lon"]],
        radius=7,
        color="green",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip("Entry Point"),
    )

    # End marker (red)
    end_marker = dl.CircleMarker(
        center=path[-1],
        radius=7,
        color="red",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip(f"Exit: {hover[-1].get('heading', 0):.0f}° hdg, {hover[-1].get('alt', 0):.0f} ft"),
    )

    elements = [start_marker, end_marker] + path_segments

    # Prepare slider configuration
    num_points = len(hover)
    slider_max = max(0, num_points - 1)
    slider_marks = {0: "Start"}
    if slider_max > 0:
        slider_marks[slider_max] = "End"
        # Add key point markers (45°, 90°, 135°, 180°)
        for i, pt in enumerate(hover):
            progress = pt.get('turn_progress', 0)
            if abs(progress - 45) < 3:
                slider_marks[i] = "45°"
            elif abs(progress - 90) < 3:
                slider_marks[i] = "90°"
            elif abs(progress - 135) < 3:
                slider_marks[i] = "135°"
            elif abs(progress - 180) < 3:
                slider_marks[i] = "180°"

    slider_style = {"display": "block", "marginTop": "10px"}

    # Calculate performance metrics
    wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 0.0
    wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0.0

    if hover:
        gs_values = [pt.get('gs', pt.get('tas', 0)) for pt in hover]
        tas_values = [pt.get('tas', 0) for pt in hover]
        aob_values = [abs(pt.get('aob', 0)) for pt in hover]
        alt_values = [pt.get('alt', altitude_ft) for pt in hover]

        min_gs = min(gs_values) if gs_values else 0
        max_gs = max(gs_values) if gs_values else 0
        avg_tas = sum(tas_values) / len(tas_values) if tas_values else entry_ias
        max_bank = max(aob_values) if aob_values else bank
        total_time = hover[-1].get('time', 0) if hover else 0
        exit_heading = hover[-1].get('heading', 0) if hover else heading
        min_alt = min(alt_values)
        max_alt_val = max(alt_values)
        alt_variation = max_alt_val - min_alt
    else:
        min_gs = max_gs = avg_tas = entry_ias
        max_bank = bank
        total_time = 0
        exit_heading = heading
        min_alt = max_alt_val = altitude_ft
        alt_variation = 0

    # Calculate load factor at max bank
    load_factor = 1 / math.cos(math.radians(float(max_bank))) if max_bank > 0 else 1.0

    # Stall speed calculations
    vs_clean = float(ac.get("stall_speed_clean_kias", 48))
    vs_in_turn = vs_clean * math.sqrt(load_factor)
    min_ias = min([pt.get('ias', pt.get('tas', entry_ias)) for pt in hover]) if hover else entry_ias

    # Build info panel with standardized format
    info_content = dbc.Accordion([
        dbc.AccordionItem([
            html.Div(f"Weight: {weight:.0f} lb | IAS: {entry_ias:.0f} kt | TAS: {avg_tas:.0f} kt | Wind: {wind_dir_val:.0f}°/{wind_speed_val:.0f} kt", style={"fontSize": "11px"}),
            html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
            html.Div(f"AOB: {max_bank:.0f}° | Load: {load_factor:.2f}G | GS: {min_gs:.0f}-{max_gs:.0f} kt", style={"fontSize": "11px"}),
            html.Div(f"Alt: {min_alt:.0f}-{max_alt_val:.0f} ft (±{alt_variation/2:.0f}) | {first_turn_direction.title()}-first", style={"fontSize": "11px"}),
            html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
            html.Div(f"Vs turn: {vs_in_turn:.0f} kt | Margin: {min_ias - vs_in_turn:.0f} kt | Time: {total_time:.0f}s", style={"fontSize": "11px"}),
            html.Div([
                html.Span("Color: ", style={"fontSize": "10px"}),
                html.Span("■ Low", style={"color": "#ff0000", "fontSize": "10px", "marginRight": "6px"}),
                html.Span("■ Mid", style={"color": "#804080", "fontSize": "10px", "marginRight": "6px"}),
                html.Span("■ High", style={"color": "#0000ff", "fontSize": "10px"}),
            ], style={"marginTop": "4px"}),
        ], title="Simulation Results", style={"fontSize": "12px"}),
    ], start_collapsed=False, style={"marginTop": "8px"})

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


# === Steep Spiral Rendering Callback ===
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
    weight_lb
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
    )

    if not path or not hover:
        raise PreventUpdate

    # Get entry point from warnings (calculated by simulation)
    entry_pt = warnings.get('entry_point', {})

    # Single red path for consistency
    path_line = dl.Polyline(positions=path, color="red", weight=3)

    # Reference point marker (blue target)
    ref_marker = dl.CircleMarker(
        center=[ref_point["lat"], ref_point["lon"]],
        radius=10,
        color="blue",
        fill=True,
        fillOpacity=0.5,
        children=dl.Tooltip(f"Reference Point (Spiral Center)\nRadius: {warnings.get('orbit_radius_ft', 0):.0f} ft"),
    )

    # Entry marker (green) - calculated position
    entry_marker = dl.CircleMarker(
        center=[entry_pt.get('lat', path[0][0]), entry_pt.get('lon', path[0][1])],
        radius=7,
        color="green",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip(f"Entry: {altitude_ft:.0f} ft AGL\nHeading: {warnings.get('entry_heading', 0):.0f}°"),
    )

    # End marker
    end_marker = dl.CircleMarker(
        center=path[-1],
        radius=7,
        color="red",
        fill=True,
        fillOpacity=1.0,
        children=dl.Tooltip(f"Exit: {warnings.get('final_altitude_agl', 0):.0f} ft AGL"),
    )

    elements = [ref_marker, entry_marker, end_marker, path_line]

    # Build warnings display
    warning_elements = []

    # Ground impact warning (critical)
    if warnings.get('ground_impact'):
        warning_elements.append(
            html.Div([
                html.Strong("⚠️ GROUND IMPACT: "),
                html.Span("Aircraft would impact terrain before completing the maneuver. "),
                html.Span(f"Suggested minimum start altitude: {warnings.get('suggested_min_start_alt', 0):.0f} ft AGL"),
            ], style={"color": "white", "backgroundColor": "#dc3545", "padding": "8px", "borderRadius": "4px", "marginBottom": "5px"})
        )

    # Below minimum warning
    elif warnings.get('below_minimum'):
        warning_elements.append(
            html.Div([
                html.Strong("⚠️ BELOW MINIMUM: "),
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
            ], title="Simulation Results", style={"fontSize": "12px"}),
        ], start_collapsed=False, style={"marginTop": "8px"})
    )

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


from dash import no_update

from dash import callback, Input, Output, State, ctx
from dash.exceptions import PreventUpdate


# === S-Turn Reference Line Bearing Calculation ===
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

        # Create the preview line
        preview_line = dl.Polyline(
            id='sturn-ref-line-preview',
            positions=[
                [pt_backward.latitude, pt_backward.longitude],
                [ref_lat, ref_lon],
                [pt_forward.latitude, pt_forward.longitude]
            ],
            color="#ff6600",
            weight=3,
            dashArray="10, 5",
            children=dl.Tooltip(f"Reference Line: {calculated_bearing:.0f}°")
        )
        layer_children.append(preview_line)

        # Add markers for the two click points
        ref_marker = dl.CircleMarker(
            center=[ref_lat, ref_lon],
            radius=8,
            color="#ff6600",
            fill=True,
            fillColor="#ff6600",
            fillOpacity=0.8,
            children=dl.Tooltip("Maneuver Start")
        )
        bearing_marker = dl.CircleMarker(
            center=[bearing_lat, bearing_lon],
            radius=6,
            color="#ff9900",
            fill=True,
            fillColor="#ff9900",
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
            color="#ff6600",
            fill=True,
            fillColor="#ff6600",
            fillOpacity=0.8,
            children=dl.Tooltip("Reference Point (click 2nd point to set bearing)")
        )
        layer_children.append(ref_marker)
        return no_update, layer_children


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


# === S-Turn Rendering Callback ===
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

    # Single red path for consistency
    path_line = dl.Polyline(positions=path, color="red", weight=3)

    # Reference point marker
    ref_marker = dl.CircleMarker(
        center=[ref_point["lat"], ref_point["lon"]],
        radius=8,
        color="blue",
        fill=True,
        fillOpacity=0.7,
        children=dl.Tooltip("Maneuver Start"),
    )

    # Draw the reference line from maneuver start point to exit point
    if path and len(path) >= 2:
        reference_line = dl.Polyline(
            positions=[
                [ref_point["lat"], ref_point["lon"]],
                path[-1]  # Exit point
            ],
            color="#c0c0c0",  # Light gray for satellite visibility
            weight=3,
            dashArray="10, 5",
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
            color="#c0c0c0",
            weight=3,
            dashArray="10, 5",
            children=dl.Tooltip(f"Reference Line ({line_bearing:.0f}°)"),
        )

    # Entry marker
    if path:
        entry_marker = dl.CircleMarker(
            center=path[0],
            radius=7,
            color="green",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(f"Entry: {altitude:.0f} ft AGL"),
        )
    else:
        entry_marker = None

    # End marker
    if path:
        end_marker = dl.CircleMarker(
            center=path[-1],
            radius=7,
            color="red",
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


# === Helper function to create airplane marker for time scrubbers ===
def create_airplane_marker(pos, heading, tooltip_content, bank_angle=0, crab_angle=0, crab_exaggeration=3.0):
    """
    Create an airplane marker that points in the direction of flight.
    Uses an F-18 Super Hornet style fighter jet icon.

    Args:
        pos: [lat, lon] position
        heading: Aircraft heading in degrees (0=North, 90=East, etc.)
        tooltip_content: List of html elements for the tooltip
        bank_angle: Bank angle for visual tilt effect (optional)
        crab_angle: Actual crab angle in degrees (positive = crab right, negative = crab left)
        crab_exaggeration: Multiplier to exaggerate crab angle visually (default 3x)

    Returns:
        dl.Marker with rotated airplane icon
    """
    import base64
    import math

    # Exaggerate crab angle for visual effect only
    # The actual crab angle is still shown correctly in the tooltip
    if crab_angle and crab_exaggeration > 1.0:
        exaggerated_crab = crab_angle * crab_exaggeration
        # Calculate visual heading: start from track (heading - crab) and add exaggerated crab
        track = heading - crab_angle
        visual_heading = track + exaggerated_crab
    else:
        visual_heading = heading

    # Calculate wing scale factors based on bank angle
    # Positive bank = right turn (right wing down, appears shorter from above)
    # Negative bank = left turn (left wing down, appears shorter from above)
    bank_rad = math.radians(abs(bank_angle)) if bank_angle else 0

    # The "down" wing appears shorter due to perspective (cosine of bank angle)
    # At 45° bank, the down wing appears ~70% length
    down_scale = math.cos(bank_rad)
    up_scale = 1.0  # Up wing stays full length

    # Determine which wing is down based on bank direction
    if bank_angle and bank_angle > 0:  # Right bank - right wing down
        left_scale = up_scale
        right_scale = down_scale
    elif bank_angle and bank_angle < 0:  # Left bank - left wing down
        left_scale = down_scale
        right_scale = up_scale
    else:  # Wings level
        left_scale = 1.0
        right_scale = 1.0

    # Calculate scaled wing positions
    # Left wing: from x=46 extends to x=12 (34 pixels), tip at 8
    left_wing_end = 50 - (38 * left_scale)  # Main wing end
    left_wing_tip = 50 - (42 * left_scale)  # Wing tip
    left_stab_end = 50 - (22 * left_scale)  # Stabilizer end
    left_lex_end = 50 - (15 * left_scale)   # LEX end

    # Right wing: from x=54 extends to x=88 (34 pixels), tip at 92
    right_wing_end = 50 + (38 * right_scale)
    right_wing_tip = 50 + (42 * right_scale)
    right_stab_end = 50 + (22 * right_scale)
    right_lex_end = 50 + (15 * right_scale)

    # F-18 Super Hornet style SVG with bank-adjusted wings
    svg_airplane = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="36" height="36">
        <g transform="rotate({visual_heading}, 50, 50)">
            <!-- Main fuselage -->
            <path d="M50,8 L54,25 L54,75 L50,88 L46,75 L46,25 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1.5"/>

            <!-- Nose cone -->
            <path d="M50,8 L53,20 L47,20 Z" fill="#e8e8e8" stroke="#333333" stroke-width="1"/>

            <!-- Cockpit canopy -->
            <ellipse cx="50" cy="26" rx="3.5" ry="7" fill="#74b9ff" stroke="#0984e3" stroke-width="1"/>

            <!-- Leading Edge Extensions (LEX) -->
            <path d="M46,30 L{left_lex_end:.1f},48 L46,45 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>
            <path d="M54,30 L{right_lex_end:.1f},48 L54,45 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>

            <!-- Main wings (swept delta style) - scaled by bank -->
            <path d="M46,42 L{left_wing_end:.1f},62 L{left_wing_end + 2:.1f},66 L46,55 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1.2"/>
            <path d="M54,42 L{right_wing_end:.1f},62 L{right_wing_end - 2:.1f},66 L54,55 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1.2"/>

            <!-- Wing tips -->
            <path d="M{left_wing_end:.1f},62 L{left_wing_tip:.1f},64 L{left_wing_end + 2:.1f},66 Z" fill="#e8e8e8" stroke="#333333" stroke-width="0.8"/>
            <path d="M{right_wing_end:.1f},62 L{right_wing_tip:.1f},64 L{right_wing_end - 2:.1f},66 Z" fill="#e8e8e8" stroke="#333333" stroke-width="0.8"/>

            <!-- Horizontal stabilizers -->
            <path d="M46,72 L{left_stab_end:.1f},82 L{left_stab_end + 2:.1f},85 L46,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>
            <path d="M54,72 L{right_stab_end:.1f},82 L{right_stab_end - 2:.1f},85 L54,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>

            <!-- Twin vertical tails (canted outward like F-18) -->
            <path d="M44,65 L38,62 L40,78 L46,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>
            <path d="M56,65 L62,62 L60,78 L54,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>

            <!-- Engine exhausts -->
            <ellipse cx="47" cy="86" rx="2.5" ry="3" fill="#fd79a8" stroke="#e84393" stroke-width="0.8"/>
            <ellipse cx="53" cy="86" rx="2.5" ry="3" fill="#fd79a8" stroke="#e84393" stroke-width="0.8"/>

            <!-- Afterburner glow -->
            <ellipse cx="47" cy="89" rx="1.5" ry="2" fill="#ffeaa7" opacity="0.8"/>
            <ellipse cx="53" cy="89" rx="1.5" ry="2" fill="#ffeaa7" opacity="0.8"/>
        </g>
    </svg>'''

    # Encode SVG as base64 data URL
    svg_base64 = base64.b64encode(svg_airplane.encode('utf-8')).decode('utf-8')
    icon_url = f"data:image/svg+xml;base64,{svg_base64}"

    # Create custom icon
    airplane_icon = {
        "iconUrl": icon_url,
        "iconSize": [36, 36],
        "iconAnchor": [18, 18],  # Center of the icon
    }

    marker = dl.Marker(
        position=pos,
        icon=airplane_icon,
        children=dl.Tooltip(
            tooltip_content,
            permanent=True,
            direction="right",
            offset=[22, 0],
            className="scrubber-tooltip"
        ),
    )

    return marker


# === Engine-Out Time Scrubber Callback ===
@app.callback(
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("engineout-time-slider", "value"),
    State("engineout-hover-store", "data"),
    State("engineout-path-store", "data"),
    prevent_initial_call=True
)
def update_engineout_scrubber(slider_value, hover_data, path_data):
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

    phase = pt.get('phase', 'glide')
    slip_pct = pt.get('slip_pct', 0)
    bucket = pt.get('bucket', '')

    tooltip_content = [
        html.Div(f"{phase.replace('_', ' ').title()}" + (f" → {bucket}" if bucket else ""), style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
        html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
        html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
        html.Div(f"TAS: {pt.get('tas', 0):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
        html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
        html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
        html.Div(f"Slip: {slip_pct:.0f}%", style={"color": "#fd7e14" if slip_pct > 0 else "#666", "fontWeight": "bold" if slip_pct > 0 else "normal"}),
    ]

    # Add debug info for ABEAM bucket capture
    if pt.get('dist_to_abeam', 0) > 0 or pt.get('bucket_chain', ''):
        tooltip_content.append(html.Div("─── Bucket Debug ───", style={"borderTop": "1px solid #ccc", "marginTop": "3px", "paddingTop": "3px", "fontSize": "10px"}))
        tooltip_content.append(html.Div(f"Chain: {pt.get('bucket_chain', '')}"))
        tooltip_content.append(html.Div(f"Idx: {pt.get('bucket_idx', 0)} | Side: {pt.get('pattern_side', '')}"))
        abeam_bkt = pt.get('abeam_bucket', '')
        if abeam_bkt:
            tooltip_content.append(html.Div(f"{abeam_bkt}", style={"fontSize": "9px"}))
        if pt.get('dist_to_abeam', 0) > 0:
            tooltip_content.append(html.Div(f"Dist to ABEAM: {pt.get('dist_to_abeam', 0):.0f} ft"))
            tooltip_content.append(html.Div(f"Xtrack: {pt.get('xtrack_abeam', 0):.0f} | Along: {pt.get('along_abeam', 0):.0f}"))
            in_x = pt.get('in_xtrack', '')
            in_a = pt.get('in_along', '')
            in_alt = pt.get('in_alt', '')
            in_hdg = pt.get('in_hdg', '')
            tooltip_content.append(html.Div(f"X:{in_x} | A:{in_a} | Alt:{in_alt}"))
            if in_hdg:
                tooltip_content.append(html.Div(f"Hdg:{in_hdg}"))
            alt_range = pt.get('alt_range', '')
            if alt_range:
                tooltip_content.append(html.Div(f"ABEAM alt: {alt_range} ft"))
        # Show what the transition code is ACTUALLY checking
        trans_bucket = pt.get('trans_bucket', '')
        if trans_bucket:
            tooltip_content.append(html.Div("─── Transition Check ───", style={"borderTop": "1px solid #f00", "marginTop": "3px", "paddingTop": "3px", "fontSize": "10px", "color": "#f00"}))
            tooltip_content.append(html.Div(f"Checking: {trans_bucket} ({pt.get('trans_alt', '')} ft)"))
            tooltip_content.append(html.Div(f"Result: {pt.get('trans_check', '')}"))
        # Spiral planning info (during spiral phase)
        spiral_n = pt.get('spiral_n', 0)
        if spiral_n > 0:
            tooltip_content.append(html.Div("─── Spiral Plan ───", style={"borderTop": "1px solid #06c", "marginTop": "3px", "paddingTop": "3px", "fontSize": "10px", "color": "#06c"}))
            tooltip_content.append(html.Div(f"Spirals: {spiral_n} | Radius: {pt.get('spiral_r', 0):.0f} ft"))
            tooltip_content.append(html.Div(f"Alt to lose: {pt.get('spiral_alt_lose', 0):.0f} ft"))

    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
    return [marker]


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


# === Power-Off 180 Time Scrubber Callback ===
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


# === Steep Turn Time Scrubber Callback ===
@app.callback(
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("steepturn-time-slider", "value"),
    State("steepturn-hover-store", "data"),
    State("steepturn-path-store", "data"),
    prevent_initial_call=True
)
def update_steep_turn_scrubber(slider_value, hover_data, path_data):
    """Update the scrubber marker and tooltip based on slider position."""
    if not hover_data or not path_data or slider_value is None:
        return []

    idx = int(slider_value)
    if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
        return []

    pt = hover_data[idx]
    pos = path_data[idx]

    segment = pt.get('segment', 'turn')

    tooltip_content = [
        html.Div(f"{segment.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
        html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
        html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
        html.Div(f"TAS: {pt.get('tas', 0):.0f} kt | GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
        html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}°"),
        html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Crab: {'R ' if pt.get('drift', 0) < 0 else ('L ' if pt.get('drift', 0) > 0 else '')}{abs(pt.get('drift', 0)):.1f}°"),
    ]

    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
    return [marker]


# === Chandelle Time Scrubber Callback ===
@app.callback(
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("chandelle-time-slider", "value"),
    State("chandelle-hover-store", "data"),
    State("chandelle-path-store", "data"),
    prevent_initial_call=True
)
def update_chandelle_scrubber(slider_value, hover_data, path_data):
    """Update the scrubber marker and tooltip based on slider position."""
    if not hover_data or not path_data or slider_value is None:
        return []

    idx = int(slider_value)
    if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
        return []

    pt = hover_data[idx]
    pos = path_data[idx]

    segment = pt.get('segment', 'climb')

    tooltip_content = [
        html.Div(f"{segment.replace('_', ' ').title()}", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
        html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
        html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
        html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
        html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}° | Pitch: {pt.get('pitch', 0):.1f}°"),
        html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
        html.Div(f"Stall Margin: +{pt.get('speed_margin', 0):.0f} kt"),
    ]

    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
    return [marker]


# === Lazy Eight Time Scrubber Callback ===
@app.callback(
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("lazy8-time-slider", "value"),
    State("lazy8-hover-store", "data"),
    State("lazy8-path-store", "data"),
    prevent_initial_call=True
)
def update_lazy8_scrubber(slider_value, hover_data, path_data):
    """Update the scrubber marker and tooltip based on slider position."""
    if not hover_data or not path_data or slider_value is None:
        return []

    idx = int(slider_value)
    if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
        return []

    pt = hover_data[idx]
    pos = path_data[idx]

    segment = pt.get('segment', 'turn')

    tooltip_content = [
        html.Div(f"{segment.replace('_', ' ').title()} - {pt.get('turn_progress', 0):.0f}°", style={"fontWeight": "bold", "borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "3px"}),
        html.Div(f"Altitude: {pt.get('alt', 0):.0f} ft AGL"),
        html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
        html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | TAS: {pt.get('tas', 0):.0f} kt"),
        html.Div(f"AOB: {'L ' if pt.get('aob', 0) < 0 else ('R ' if pt.get('aob', 0) > 0 else '')}{abs(pt.get('aob', 0)):.1f}° | Pitch: {pt.get('pitch', 0):.1f}°"),
        html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
        html.Div(f"Stall Margin: +{pt.get('speed_margin', 0):.0f} kt"),
    ]

    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    crab = -pt.get('drift', 0)  # Negate: crab is opposite of drift (point into wind)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank, crab)
    return [marker]


# === S-Turn Time Scrubber Callback ===
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


# === Turns Around a Point Draw Callback ===
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

    # Single red path for consistency
    path_line = dl.Polyline(positions=path, color="red", weight=3)

    # Center point marker (the reference point)
    center_marker = dl.CircleMarker(
        center=[center_point["lat"], center_point["lon"]],
        radius=8,
        color="red",
        fill=True,
        fillOpacity=0.8,
        children=dl.Tooltip("Reference Point (center)"),
    )

    # Draw the ideal orbit circle
    import math
    orbit_radius_ft = radius_nm * 6076.12
    orbit_circle_points = []
    for angle_deg in range(0, 361, 5):
        angle_rad = math.radians(angle_deg)
        n_offset = orbit_radius_ft * math.cos(angle_rad)
        e_offset = orbit_radius_ft * math.sin(angle_rad)
        lat = center_point["lat"] + (n_offset / 364567.2)
        lon = center_point["lon"] + (e_offset / (364567.2 * math.cos(math.radians(center_point["lat"]))))
        orbit_circle_points.append([lat, lon])

    orbit_circle = dl.Polyline(
        positions=orbit_circle_points,
        color="gray",
        weight=1,
        dashArray="5, 5",
        opacity=0.5,
        children=dl.Tooltip(f"Target orbit: {radius_nm:.2f} nm ({orbit_radius_ft:.0f} ft)"),
    )

    # Entry marker
    if path:
        entry_marker = dl.CircleMarker(
            center=path[0],
            radius=7,
            color="green",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(f"Entry: {altitude:.0f} ft AGL, Hdg {sim_warnings.get('entry_heading', 0):.0f}°"),
        )
    else:
        entry_marker = None

    # Exit marker
    if path:
        exit_marker = dl.CircleMarker(
            center=path[-1],
            radius=7,
            color="darkred",
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


# === Turns Around a Point Time Scrubber Callback ===
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


# === Eights on Pylons Draw Callback ===
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
    Input("pylons-draw-btn", "n_clicks"),
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
    State("selected-airport-id", "data"),
    State("runtime-total-weight-lb", "data"),
    State("power-setting", "value"),
    State("cg-slider", "value"),
    State("layer", "children"),
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
    selected_airport_id,
    runtime_weight,
    power_setting,
    cg_position,
    layer_children,
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
        power_setting=float(power_setting) if power_setting not in [None, "", "null"] else 0.65,
        cg_position=float(cg_position) if cg_position not in [None, "", "null"] else 0.5,
        bank_angle_deg=bank_deg,
        entry_direction=entry_dir,
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
    if sim_warnings.get("airspeed_warning"):
        warning_elements.append(html.Div(f"Warning: {sim_warnings['airspeed_warning']}", style={"color": "#c0392b", "fontWeight": "bold"}))
    if sim_warnings.get("bank_limited"):
        warning_elements.append(html.Div("AOB limited to 40° (ACS maximum)", style={"color": "#e67e22"}))
    if sim_warnings.get("stall_margin_warning"):
        warning_elements.append(html.Div("Warning: Stall margin below 1.2", style={"color": "#c0392b"}))
    # ACS compliance warnings
    if sim_warnings.get("pylon_distance_warning"):
        warning_elements.append(html.Div(f"⚠ {sim_warnings['pylon_distance_warning']}", style={"color": "#e67e22"}))
    if sim_warnings.get("transition_time_warning"):
        warning_elements.append(html.Div(f"ℹ {sim_warnings['transition_time_warning']}", style={"color": "#3498db"}))

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
                html.Div(f"Pylon sep: {sim_warnings.get('pylon_distance_nm', 0):.2f} nm | Trans: {sim_warnings.get('transition_time_avg_sec', 0):.1f}s", style={"fontSize": "11px"}),
                html.Hr(style={"margin": "5px 0", "borderTop": "1px solid #ddd"}),
                html.Div(f"Stall margin: {min_ias_achieved - vs_in_turn:.0f} kt | Time: {sim_warnings.get('total_time_sec', 0):.0f}s | {n_eights} eights", style={"fontSize": "11px"}),
                html.Div([
                    html.Span("Color: ", style={"fontSize": "10px"}),
                    html.Span("■ Low PA", style={"color": "#ff0000", "fontSize": "10px", "marginRight": "6px"}),
                    html.Span("■ Mid", style={"color": "#804080", "fontSize": "10px", "marginRight": "6px"}),
                    html.Span("■ High PA", style={"color": "#0000ff", "fontSize": "10px"}),
                ], style={"marginTop": "4px"}),
            ], title="Simulation Results", style={"fontSize": "12px"}),
        ], start_collapsed=False, style={"marginTop": "8px"})
    )

    info_elements = html.Div(info_children)

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


# === Eights on Pylons Time Scrubber Callback ===
@app.callback(
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("pylons-time-slider", "value"),
    State("pylons-hover-store", "data"),
    State("pylons-path-store", "data"),
    prevent_initial_call=True
)
def update_eights_on_pylons_scrubber(slider_value, hover_data, path_data):
    """Update the scrubber marker and tooltip based on slider position."""
    if not hover_data or not path_data or slider_value is None:
        return []

    idx = int(slider_value)
    if idx < 0 or idx >= len(hover_data) or idx >= len(path_data):
        return []

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


# === Steep Spiral Time Scrubber Callback ===
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
