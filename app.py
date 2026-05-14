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
