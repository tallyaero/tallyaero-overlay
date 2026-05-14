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

# Aircraft + airport data live in core/data_loader.py (Phase 1i-pre) to
# avoid the circular re-import that `import app as app_module` caused
# when app.py was the __main__ entry point. Auto-init runs at import
# time inside the loader module.
from core.data_loader import aircraft_data, available_aircraft, airport_data, init_data

# === Dash App ===
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    prevent_initial_callbacks="initial_duplicate"
)
server = app.server

# Wire callbacks decomposed out of this file during Phase 1.
from callbacks import register_all
register_all(app)

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
