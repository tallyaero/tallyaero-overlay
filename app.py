import requests
import math
import os
import json
import dash
from dash import dcc, html, Input, Output, State, MATCH, ALL, ctx
import dash_bootstrap_components as dbc
import dash_leaflet as dl
from geopy.point import Point as GeoPoint
from geopy.distance import distance as geo_distance
from dash.exceptions import PreventUpdate
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
    simulate_impossible_turn,
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

aircraft_data = load_aircraft_data()
available_aircraft = sorted(aircraft_data.keys())

# === Load airport data ===
def load_airport_data():
    base = os.path.dirname(__file__)
    path = os.path.join(base, "airports", "airports.json")
    with open(path, "r") as f:
        return json.load(f)
airport_data = load_airport_data()

# === Dash App ===
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    prevent_initial_callbacks=True
)
server = app.server

app.title = "Maneuver Overlay Tool | AeroEdge"

def legal_banner_block():
    return html.Div(
        children=[
            html.Div(
                "⚠️ This tool is for educational and training discussion only. It is not FAA-approved and may not reflect actual aircraft capabilities. "
                "Always verify against the aircraft POH or AFM and applicable regulations. ⚠️",
                className="disclaimer-banner",
            ),
            html.Div(
                children=[
                    html.A("Full Legal Disclaimer", href="#", id="open-disclaimer", className="legal-link"),
                    html.Span(" | ", className="legal-separator"),
                    html.A("Terms of Use & Privacy Policy", href="#", id="open-terms-policy", className="legal-link"),
                ],
                className="legal-links-row",
            ),

            dbc.Modal(
                [
                    dbc.ModalHeader("AeroEdge Disclaimer", close_button=True),
                    dbc.ModalBody(
                        [
                            html.P("This tool supplements, not replaces, FAA published documentation."),
                            html.P("It is intended for educational and reference use only and has not been approved or endorsed by the Federal Aviation Administration (FAA)."),
                            html.P("Do not use this tool for flight planning, aircraft operation, or regulatory compliance decisions."),
                            html.P("Outputs may be incomplete, inaccurate, outdated, or derived from public or user-provided inputs. No warranties are made regarding accuracy, completeness, or fitness for purpose."),
                            html.P("If any information conflicts with the aircraft FAA-approved AFM or POH, the official documentation shall govern."),
                            html.P("AeroEdge disclaims liability for errors, omissions, injuries, damages, or losses resulting from use of this application."),
                        ]
                    ),
                    dbc.ModalFooter(dbc.Button("Close", id="close-disclaimer", className="green-button")),
                ],
                id="disclaimer-modal",
                is_open=False,
                centered=True,
                size="lg",
                dialogClassName="aeroedge-modal",
                backdrop="static",
                scrollable=True,
            ),

            dbc.Modal(
                [
                    dbc.ModalHeader("Terms of Use & Privacy Policy", close_button=True),
                    dbc.ModalBody(
                        [
                            html.H6("Terms of Use", className="mb-2 mt-2"),
                            html.P("Use is for educational and informational purposes only. This tool is not FAA-certified."),
                            html.P("Verify all performance and procedural information using the POH or AFM and applicable regulations. Use is at your own risk."),
                            html.H6("Privacy Policy", className="mb-2 mt-4"),
                            html.P("No user accounts are required. The app does not intentionally collect personally identifiable information for functionality."),
                            html.P("Hosting providers may log basic operational metadata such as IP address, timestamps, and user agent for security and reliability."),
                        ]
                    ),
                    dbc.ModalFooter(dbc.Button("Close", id="close-terms-policy", className="green-button")),
                ],
                id="terms-policy-modal",
                is_open=False,
                centered=True,
                size="lg",
                dialogClassName="aeroedge-modal",
                backdrop="static",
                scrollable=True,
            ),
        ]
    )

app.layout = html.Div(className="full-height-container", children=[
    # Header
    html.Div(className="banner-header", children=[
        html.Div(className="banner-inner", children=[
            html.A(
                html.Img(src="/assets/logo.png", className="banner-logo"),
                href="https://www.flyaeroedge.com",
                style={"textDecoration": "none"}
            )
            
        ])
    ]),
    legal_banner_block(),
    # Main 2-column layout
    html.Div(className="main-row", children=[
        # === Sidebar ===
        html.Div(className="resizable-sidebar", children=[
            html.Div("Maneuver Overlay Tool", style={
                "fontWeight": "600",
                "fontSize": "20px",
                "marginBottom": "10px",
                "color": "#1b1e23"
            }),

            # --- Aircraft & Weight Section ---
            html.Label("Aircraft", className="input-label"),
            dcc.Dropdown(
                id="aircraft-select",
                className="dropdown",
                options=[{"label": name, "value": name} for name in available_aircraft],
                value=None,
                placeholder="Select Aircraft"
            ),

            html.Label("Engine Option", className="input-label"),
            dcc.Dropdown(id="engine-select", className="dropdown"),

            html.Label("Occupants", className="input-label"),
            dcc.Input(id="occupants", type="number", value=1, min=1, max=4, className="input-small"),

            html.Label("Occupant Weight (lbs)", className="input-label"),
            dcc.Input(id="occupant-weight", type="number", value=180, min=100, max=300, className="input-small"),

            html.Label("Fuel Load (gal)", className="input-label"),
            dcc.Slider(
                id="fuel-load",
                min=0,
                max=50,
                step=1,
                value=0,
                marks={0: "0", 12: "¼", 25: "½", 37: "¾", 50: "Full"},
                tooltip={"always_visible": True}
            ),

            html.Label("Total Weight (lbs)", className="input-label"),
            dcc.Input(
                id="total-weight-display",
                type="text",
                value="",
                readOnly=True,
                className="input-small",
                
            ),

            html.Label("CG Position", className="input-label"),
            dcc.Slider(
                id="cg-slider",
                min=0.0,
                max=1.0,
                step=0.01,
                value=0.5,
                marks={0.0: "FWD", 0.5: "MID", 1.0: "AFT"},
                tooltip={"always_visible": True}
            ),

            html.Label("Power Setting", className="input-label"),
            dcc.Slider(
                id="power-setting",
                min=0.05, max=1.0, step=0.05, value=0.5,
                marks={0.05: "IDLE", 0.2: "20%", 0.4: "40%", 0.6: "60%", 0.8: "80%", 0.99: "100%"},
                tooltip={"always_visible": True}
            ),

            html.Hr(),

            html.Div([
                html.Div("Environmentals", style={
                    "fontWeight": "600",
                    "fontSize": "16px",
                    "marginBottom": "10px",
                    "color": "#1b1e23"
                }),

                html.Label("Search Airport", className="input-label"),
                dcc.Input(
                    id="airport-search-input",
                    type="text",
                    placeholder="ICAO or name...",
                    debounce=True,
                    className="input-large"
                ),
                html.Div(id="airport-search-results", className="search-results-box"),
                html.Label("Airport Elevation (AGL ft)", className="input-label"),
                html.Div(id="env-airport-agl", className="weight-box", style={"marginBottom": "10px"}),

                html.Label("Outside Air Temp (°F)", className="input-label"),
                dcc.Input(id="env-oat", type="number", value=52, className="input-small"),

                html.Label("Altimeter Setting (inHg)", className="input-label"),
                dcc.Input(id="env-altimeter", type="number", value=29.92, className="input-small"),

                html.Label("Wind Direction (°)", className="input-label"),
                dcc.Input(id="env-wind-dir", type="number", value=360, className="input-small"),

                html.Label("Wind Speed (kt)", className="input-label"),
                dcc.Input(id="env-wind-speed", type="number", value=0, className="input-small"),
            ]),

            html.Hr(),

            # --- Maneuver Dropdown ---
            html.Label("Maneuver", className="input-label"),
            dcc.Dropdown(
                id="maneuver-select",
                className="dropdown",
                placeholder="Select Maneuver",
                options=[
                    {"label": "Impossible Turn", "value": "impossible_turn"},
                    {"label": "Power-Off 180", "value": "poweroff180"},
                    {"label": "Engine-Out Glide Simulation", "value": "engineout"},
                    {"label": "Steep Turns", "value": "steep_turn"},
                    {"label": "Chandelle", "value": "chandelle"},
                    {"label": "Lazy Eight", "value": "lazy8"},
                    {"label": "Steep Spiral", "value": "steep_spiral"},
                    {"label": "S-Turns", "value": "s_turn"},
                    {"label": "Turns Around a Point", "value": "turns_point"},
                    {"label": "Rectangular Course", "value": "rect_course"},
                    {"label": "Eights on Pylons", "value": "pylons"},
                ]
            ),

            # --- Conditionally Shown Based on Maneuver ---
            html.Div(id="maneuver-params-container", children=[], style={"marginTop": "20px"}),

            html.Hr(),

            html.Button("Reset All", id="reset-all", className="green-button"),
            html.Button("Reset Click Points", id="reset-clicks", className="green-button")
        ]),

        # === Map Column ===
        html.Div(id="engineout-click-status", style={"display": "none"}),
        html.Div(className="graph-column", style={"display": "flex", "flexDirection": "column"}, children=[
            html.Div(
                style={
                    "flexGrow": 1,
                    "height": "calc(100vh - 180px)",
                    "position": "relative"
                },
                children=[
                    dl.Map(
                        id="map",
                        center=[33.0635, -80.2795],
                        zoom=13.5,
                        style={"width": "100%", "height": "100%"},
                        children=[
                            dl.TileLayer(),
                            dl.LayerGroup(id="layer"),
                            dl.LayerGroup(id="scrubber-layer"),  # Dedicated layer for time scrubber marker
                        ]
                    )
                ]
            ),

            html.Div(id="click_debug", style={
                "padding": "10px 12px",
                "fontStyle": "italic",
                "color": "#555",
                "backgroundColor": "#fff",
                "borderTop": "1px solid #ccc"
            }),

            # ===== Maneuver-scoped point stores (no shared state between maneuvers) =====

            dcc.Store(id="runtime-total-weight-lb"),

            # Power-Off 180 (touchdown only; start is auto-generated but keep for future flexibility)
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "start"}),

            # Engine-Out Glide
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "start"}),

            # Steep Turns
            dcc.Store(id={"type": "point-store", "m_id": "steep_turn", "role": "start"}),

            # Chandelle
            dcc.Store(id={"type": "point-store", "m_id": "chandelle", "role": "start"}),

            # Lazy Eight
            dcc.Store(id={"type": "point-store", "m_id": "lazy8", "role": "start"}),

            # Steep Spiral (reference point only - entry calculated from aircraft physics)
            dcc.Store(id={"type": "point-store", "m_id": "steep_spiral", "role": "ref"}),

            # S-Turns (ref = reference point on line, bearing = second point to define line direction)
            dcc.Store(id={"type": "point-store", "m_id": "s_turn", "role": "ref"}),
            dcc.Store(id={"type": "point-store", "m_id": "s_turn", "role": "bearing"}),
            dcc.Store(id="sturn-calculated-bearing"),  # Store for calculated bearing value

            # Turns Around a Point (center point)
            dcc.Store(id={"type": "point-store", "m_id": "turns_point", "role": "center"}),

            # Rectangular Course (downwind edge points)
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "dw_start"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "dw_end"}),

            # Eights on Pylons (two pylons)
            dcc.Store(id={"type": "point-store", "m_id": "pylons", "role": "pylon_a"}),
            dcc.Store(id={"type": "point-store", "m_id": "pylons", "role": "pylon_b"}),

            # Impossible Turn (start only)
            dcc.Store(id={"type": "point-store", "m_id": "impossible_turn", "role": "start"}),
            dcc.Store(id="active-click-target"),
            dcc.Store(id="selected-airport-id"),

            # Rectangular course calculated edge (needs to be in main layout for callback)
            dcc.Store(id="rectcourse-calculated-edge", data={}),

            html.Div("© 2025 Nicholas Len, AEROEDGE. All rights reserved.",
                     className="footer", style={"paddingBottom": "10px"})
        ])
    ])
])

# === Maneuver UI Layouts ===
def impossible_turn_layout():
    return [

        html.Div(
            [
                html.Div(
                    "Assumptions: engine fails at the selected point while tracking selected runway heading upwind. "
                    "Model applies reaction delay, transitions toward best glide, and attempts to intercept opposite  "
                    "runway heading.",
                    style={"fontStyle": "italic", "color": "#555"}
                ),

            ],
            style={"marginBottom": "10px"}
        ),

        html.Label("Turn Direction", className="input-label"),
        dcc.RadioItems(
            id="impossibleturn-direction",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"},
            ],
            value="left",
            inline=True,
            className="radio-inline-group"
        ),

        html.Label("Runway Heading (°)", className="input-label"),
        dcc.Input(
            id="impossibleturn-touchdown-heading",
            type="number",
            value=240,
            min=0,
            max=360,
            step=1,
            className="input-small"
        ),

        html.Label("Engine Failure Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="impossibleturn-altitude",
            type="number",
            value=1000,
            min=0,
            step=10,
            className="input-small"
        ),

        html.Label("Entry IAS at Failure (KIAS)", className="input-label"),
        dcc.Input(
            id="impossibleturn-entry-ias",
            type="number",
            value=75,
            min=0,
            step=1,
            className="input-small"
        ),

        html.Label("Reaction Delay (sec)", className="input-label"),
        dcc.Input(
            id="impossibleturn-reaction-sec",
            type="number",
            value=3.0,
            min=0.0,
            step=0.5,
            className="input-small"
        ),

                # Flaps
        html.Label("Flap configuration"),
        dcc.Dropdown(
            id="impossibleturn-flap-config",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean",
            clearable=False,
            searchable=False,
        ),

        # Prop
        html.Label("Prop condition"),
        dcc.Dropdown(
            id="impossibleturn-prop-config",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Prop Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"}
            ],
            value="windmilling",
            clearable=False,
            searchable=False,
        ),

        html.Hr(),

        html.Button(
            "Set Engine Failure Point",
            id={"type": "click-button", "m_id": "impossible_turn", "role": "start"},
            className="green-button"
        ),

        html.Br(),
        html.Br(),

        html.Button(
            "Draw Impossible Turn",
            id="impossibleturn-draw-btn",
            className="blue-button"
        ),

        html.Div(
            id={"type": "click-status", "m_id": "impossible_turn"},
            style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"},
        ),

        html.Div(
            id="impossibleturn-result",
            className="weight-box",
            style={"marginTop": "10px"}
        ),
    ]
def poweroff180_layout(default_elev=None):
    return [
        html.Label("Pattern Direction", className="input-label"),
        dcc.RadioItems(
            id="poweroff180-pattern",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"}
            ],
            value="left",
            inline=True,
            className="radio-inline-group"
        ),

        html.Label("Flap Setting", className="input-label"),
        dcc.Dropdown(
            id="poweroff180-flap-setting",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"}
            ],
            value="clean",
            className="dropdown"
        ),

        html.Label("Prop Condition", className="input-label"),
        dcc.Dropdown(
            id="poweroff180-prop-condition",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Prop Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"}
            ],
            value="idle",
            className="dropdown"
        ),

        html.Label("Touchdown Heading (°)", className="input-label"),
        dcc.Input(
            id="poweroff180-touchdown-heading",
            type="number",
            value=60,
            className="input-small"
        ),

        html.Label("Start Distance From Touchdown (NM)", className="input-label"),
        dcc.Slider(
            id="poweroff180-start-distance-nm",
            min=0.3,
            max=2.5,
            step=0.1,
            value=0.8,
            marks={
                0.5: "0.5",
                1.0: "1.0",
                1.5: "1.5",
                2.0: "2.0",
                2.5: "2.5",
            },
            tooltip={"always_visible": True}
        ),

        html.Label("Start Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="poweroff180-altitude",
            type="number",
            value=1000,
            className="input-small"
        ),

        html.Hr(),

        html.Button(
            "Set Touchdown Point",
            id={"type": "click-button", "m_id": "poweroff180", "role": "touchdown"},
            className="green-button"
        ),
        # NOTE: removed "Set Start Point" – start point is now auto-generated
        html.Div(
            id={"type": "click-status", "m_id": "poweroff180"},
            style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}
        ),
        html.Button("Draw Power-Off 180", id="poweroff180-draw-btn", className="green-button"),
    ]

def engineout_layout():
    return [

        # ---- Configuration Inputs ----
        html.Label("Flap Setting", className="input-label"),
        dcc.Dropdown(
            id="engineout-flap-setting",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean",
            className="dropdown"
        ),

        html.Label("Prop Condition", className="input-label"),
        dcc.Dropdown(
            id="engineout-prop-condition",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Prop Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"},
            ],
            value="idle",
            className="dropdown"
        ),

        html.Label("Touchdown Heading (°)", className="input-label"),
        dcc.Input(
            id="engineout-touchdown-heading",
            type="number",
            value=60,
            className="input-small"
        ),

        # ✅ NEW: Pattern direction toggle
        html.Label("Pattern Direction", className="input-label"),
        dcc.RadioItems(
            id="engineout-pattern-dir",
            options=[
                {"label": "Left Pattern", "value": "left"},
                {"label": "Right Pattern", "value": "right"},
            ],
            value="left",
            labelStyle={"display": "inline-block", "margin-right": "12px"},
            className="radio-items"
        ),

        html.Label("Touchdown Elevation (ft)", className="input-label"),
        dcc.Input(
            id="engineout-manual-elev",
            type="number",
            placeholder="map click",
            className="input-small"
        ),

        html.Label("Start Heading (°)", className="input-label"),
        dcc.Input(
            id="engineout-start-heading",
            type="number",
            value=240,
            className="input-small"
        ),

        html.Label("Start Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="engineout-altitude",
            type="number",
            value=1000,
            className="input-small"
        ),

        html.Hr(),

        # ---- Map Interaction Buttons ----
        html.Button(
            "Set Touchdown Point",
            id={"type": "click-button", "m_id": "engineout", "role": "touchdown"},
            className="green-button"
        ),
        html.Button(
            "Set Start Point",
            id={"type": "click-button", "m_id": "engineout", "role": "start"},
            className="green-button"
        ),

        html.Br(), html.Br(),

        # ---- ★ NEW: DRAW ENGINE-OUT PATH BUTTON ----
        html.Button(
            "Draw Engine-Out Glide Path",
            id="engineout-draw-btn",
            className="blue-button",
            style={"marginTop": "10px"},
        ),

        html.Div(
            id={"type": "click-status", "m_id": "engineout"},
            style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"},
        ),
    ]
def steep_turn_layout():
    return [
        html.Label("Bank Angle (°)", className="input-label"),
        dcc.Input(
            id="steepturn-bank-angle",
            type="number",
            value=45,
            min=30,
            max=60,
            className="input-small"
        ),

        html.Label("Turn Sequence", className="input-label"),
        dcc.RadioItems(
            id="steepturn-sequence",
            options=[
                {"label": "Left → Right", "value": "left-right"},
                {"label": "Right → Left", "value": "right-left"},
                {"label": "Left Only", "value": "left"},
                {"label": "Right Only", "value": "right"}
            ],
            value="left-right",
            inline=True,
            className="radio-inline-group"
        ),

        html.Label("Entry Heading (°)", className="input-label"),
        dcc.Input(
            id="steepturn-entry-heading",
            type="number",
            value=0,
            className="input-small"
        ),

        html.Label("Entry Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="steepturn-altitude",
            type="number",
            placeholder="Optional",
            className="input-small"
        ),

        html.Label("Entry Speed (KIAS)", className="input-label"),
        dcc.Input(
            id="steepturn-ias",
            type="number",
            placeholder="e.g. Va",
            className="input-small"
        ),

        html.Hr(),

        html.Div([
            html.Button("Set Entry Point", id={"type": "click-button", "m_id": "steep_turn", "role": "start"}, className="green-button"),
            html.Button("Draw Steep Turn", id="steepturn-draw-btn", className="blue-button", style={"marginLeft": "10px"})
        ], style={"display": "flex", "alignItems": "center"}),

        html.Div(id={"type": "click-status", "m_id": "steep_turn"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"})
    ]

def chandelle_layout():
    return [
        html.Label("Entry Heading (°)", className="input-label"),
        dcc.Input(
            id="chandelle-entry-heading",
            type="number",
            value=0,
            className="input-small"
        ),

        html.Label("Bank Angle (°)", className="input-label"),
        dcc.Input(
            id="chandelle-bank-angle",
            type="number",
            value=30,
            min=15,
            max=45,
            className="input-small"
        ),

        html.Label("Turn Direction", className="input-label"),
        dcc.RadioItems(
            id="chandelle-direction",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"}
            ],
            value="right",
            inline=True,
            className="radio-inline-group"
        ),

        html.Label("Entry Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="chandelle-altitude",
            type="number",
            value=3000,
            className="input-small"
        ),

        html.Label("Entry Speed (KIAS)", className="input-label"),
        dcc.Input(
            id="chandelle-ias",
            type="number",
            placeholder="e.g. Va",
            className="input-small"
        ),

        html.Hr(),

        html.Div([
            html.Button("Set Entry Point", id={"type": "click-button", "m_id": "chandelle", "role": "start"}, className="green-button"),
            html.Button("Draw Chandelle", id="chandelle-draw-btn", className="blue-button", style={"marginLeft": "10px"})
        ], style={"display": "flex", "alignItems": "center"}),

        html.Div(id={"type": "click-status", "m_id": "chandelle"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"})
    ]

def lazy8_layout():
    return [
        html.Label("Entry Heading (°)", className="input-label"),
        dcc.Input(
            id="lazy8-entry-heading",
            type="number",
            value=0,
            className="input-small"
        ),

        html.Label("Entry Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="lazy8-entry-altitude",
            type="number",
            value=3000,
            className="input-small"
        ),

        html.Label("Entry Speed (KIAS)", className="input-label"),
        dcc.Input(
            id="lazy8-ias",
            type="number",
            placeholder="e.g. Va",
            className="input-small"
        ),

        html.Label("Max Bank Angle (°)", className="input-label"),
        dcc.Input(
            id="lazy8-bank-angle",
            type="number",
            value=30,
            min=20,
            max=40,
            className="input-small"
        ),

        html.Label("First Turn Direction", className="input-label"),
        dcc.RadioItems(
            id="lazy8-direction-sequence",
            options=[
                {"label": "Left first", "value": "left"},
                {"label": "Right first", "value": "right"}
            ],
            value="left",
            inline=True,
            className="radio-inline-group"
        ),

        html.Hr(),

        html.Div([
            html.Button("Set Entry Point", id={"type": "click-button", "m_id": "lazy8", "role": "start"}, className="green-button"),
            html.Button("Draw Lazy Eight", id="lazy8-draw-btn", className="blue-button", style={"marginLeft": "10px"})
        ], style={"display": "flex", "alignItems": "center"}),

        html.Div(id={"type": "click-status", "m_id": "lazy8"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"})
    ]

def steep_spiral_layout():
    return [
        html.Label("Number of Turns (min 3 per FAA)", className="input-label"),
        dcc.Input(
            id="steepspiral-turns",
            type="number",
            value=3,
            min=3,
            max=10,
            step=1,
            className="input-small"
        ),

        html.Label("Entry Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="steepspiral-altitude",
            type="number",
            value=5000,
            className="input-small"
        ),

        html.Label("Bank Angle (°)", className="input-label"),
        dcc.Input(
            id="steepspiral-bank-angle",
            type="number",
            value=45,
            min=20,
            max=60,
            className="input-small"
        ),

        html.Label("Entry Position (clock)", className="input-label"),
        dcc.Dropdown(
            id="steepspiral-clock-position",
            options=[
                {"label": "12 o'clock (North of ref)", "value": "12"},
                {"label": "3 o'clock (East of ref)", "value": "3"},
                {"label": "6 o'clock (South of ref)", "value": "6"},
                {"label": "9 o'clock (West of ref)", "value": "9"},
            ],
            value="12",
            clearable=False,
            className="dropdown-small"
        ),

        html.Label("Turn Direction", className="input-label"),
        dcc.RadioItems(
            id="steepspiral-direction",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"}
            ],
            value="left",
            inline=True,
            className="radio-inline-group"
        ),

        html.Hr(),

        html.Button("Set Reference Point", id={"type": "click-button", "m_id": "steep_spiral", "role": "ref"}, className="green-button"),

        html.Div(id={"type": "click-status", "m_id": "steep_spiral"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

        html.Div([
            html.Button("Draw Steep Spiral", id="steepspiral-draw-btn", className="blue-button", style={"marginTop": "10px"})
        ]),

        # Time slider for scrubbing through hover points
        html.Div(id="steepspiral-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="steepspiral-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),  # Hidden until drawing is complete

        # Stores for hover data and path
        dcc.Store(id="steepspiral-hover-store", data=[]),
        dcc.Store(id="steepspiral-path-store", data=[]),

        # Warnings display area
        html.Div(id="steepspiral-warnings", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]

def s_turn_layout():
    """S-Turns across a reference line - ground reference maneuver."""
    return [
        # Reference Line Selection (interactive two-click)
        html.Label("Reference Line", className="input-label"),
        html.Div([
            html.Button(
                "1. Click Reference Point",
                id={"type": "click-button", "m_id": "s_turn", "role": "ref"},
                className="green-button",
                style={"marginRight": "10px"}
            ),
            html.Button(
                "2. Click Along Line",
                id={"type": "click-button", "m_id": "s_turn", "role": "bearing"},
                className="green-button"
            ),
        ], style={"marginBottom": "5px"}),

        html.Div([
            html.Span("Bearing: ", style={"fontWeight": "bold"}),
            dcc.Input(
                id="sturn-line-bearing",
                type="number",
                value=90,
                min=0,
                max=360,
                className="input-small",
                style={"width": "70px", "display": "inline-block"}
            ),
            html.Span("°", style={"marginLeft": "2px"}),
            html.Span(" (auto-calculated from clicks, or enter manually)",
                      style={"marginLeft": "10px", "fontSize": "11px", "color": "#666"})
        ], style={"marginBottom": "5px"}),

        html.Div(id={"type": "click-status", "m_id": "s_turn"},
                 style={"marginTop": "5px", "marginBottom": "10px", "fontStyle": "italic", "color": "#555"}),

        html.Hr(),

        html.Label("Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="sturn-altitude",
            type="number",
            value=800,
            min=400,
            max=1500,
            className="input-small"
        ),

        html.Label("Airspeed (KIAS)", className="input-label"),
        dcc.Input(
            id="sturn-ias",
            type="number",
            value=100,
            className="input-small"
        ),

        html.Label("Bank Angle (°)", className="input-label"),
        dcc.Input(
            id="sturn-bank-angle",
            type="number",
            value=35,
            min=20,
            max=45,
            className="input-small"
        ),

        html.Label("Number of S-Turns", className="input-label"),
        dcc.Input(
            id="sturn-num-turns",
            type="number",
            value=2,
            min=1,
            max=5,
            step=1,
            className="input-small"
        ),

        html.Label("Entry Side (of line)", className="input-label"),
        dcc.RadioItems(
            id="sturn-entry-side",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"}
            ],
            value="left",
            inline=True,
            className="radio-inline-group"
        ),

        html.Label("First Turn Direction", className="input-label"),
        dcc.RadioItems(
            id="sturn-first-turn",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"}
            ],
            value="right",
            inline=True,
            className="radio-inline-group"
        ),

        html.Hr(),

        html.Div([
            html.Button("Draw S-Turns", id="sturn-draw-btn", className="blue-button")
        ]),

        # Time slider for scrubbing through hover points
        html.Div(id="sturn-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="sturn-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="sturn-hover-store", data=[]),
        dcc.Store(id="sturn-path-store", data=[]),

        # Info display area
        html.Div(id="sturn-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]

def turns_point_layout():
    """Turns Around a Point - ground reference maneuver."""
    return [
        # Center Point Selection
        html.Label("Center Point (Reference)", className="input-label"),
        html.Button(
            "Click to Set Center Point",
            id={"type": "click-button", "m_id": "turns_point", "role": "center"},
            className="green-button",
            style={"marginBottom": "5px"}
        ),
        html.Div(id={"type": "click-status", "m_id": "turns_point"},
                 style={"marginTop": "5px", "marginBottom": "10px", "fontStyle": "italic", "color": "#555"}),

        html.Hr(),

        html.Label("Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="turnspoint-altitude",
            type="number",
            value=800,
            min=400,
            max=1500,
            className="input-small"
        ),

        html.Label("Airspeed (KIAS)", className="input-label"),
        dcc.Input(
            id="turnspoint-ias",
            type="number",
            value=100,
            className="input-small"
        ),

        html.Label("Orbit Radius (nm)", className="input-label"),
        dcc.Input(
            id="turnspoint-radius",
            type="number",
            value=0.25,
            min=0.1,
            max=1.0,
            step=0.05,
            className="input-small"
        ),
        html.Span("~1500 ft typical", style={"marginLeft": "5px", "fontSize": "11px", "color": "#666"}),

        html.Label("Number of Turns", className="input-label"),
        dcc.Input(
            id="turnspoint-num-turns",
            type="number",
            value=2,
            min=1,
            max=5,
            step=1,
            className="input-small"
        ),

        html.Label("Turn Direction", className="input-label"),
        dcc.RadioItems(
            id="turnspoint-direction",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"}
            ],
            value="left",
            inline=True,
            className="radio-inline-group"
        ),

        html.Label("Entry Heading (° - leave blank for downwind)", className="input-label"),
        dcc.Input(
            id="turnspoint-entry-heading",
            type="number",
            placeholder="Auto (downwind)",
            className="input-small"
        ),

        html.Hr(),

        html.Div([
            html.Button("Draw Turns Around Point", id="turnspoint-draw-btn", className="blue-button")
        ]),

        # Time slider for scrubbing through hover points
        html.Div(id="turnspoint-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="turnspoint-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="turnspoint-hover-store", data=[]),
        dcc.Store(id="turnspoint-path-store", data=[]),
        dcc.Store(id="turnspoint-warnings-store", data={}),

        # Info display area
        html.Div(id="turnspoint-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]

def rect_course_layout():
    """Rectangular Course - ground reference maneuver simulating traffic pattern."""
    return [
        # Two-click downwind leg definition
        html.Label("Define Downwind Leg", className="input-label"),
        html.Div([
            html.Button(
                "1. Click Downwind Start",
                id={"type": "click-button", "m_id": "rect_course", "role": "dw_start"},
                className="green-button",
                style={"marginRight": "10px"}
            ),
            html.Button(
                "2. Click Downwind End",
                id={"type": "click-button", "m_id": "rect_course", "role": "dw_end"},
                className="green-button"
            ),
        ], style={"marginBottom": "5px"}),

        html.Div([
            html.Span("Downwind Length: ", style={"fontWeight": "bold"}),
            html.Span(id="rectcourse-edge-length", children="-- nm"),
            html.Span(" | Track: ", style={"fontWeight": "bold", "marginLeft": "15px"}),
            html.Span(id="rectcourse-edge-bearing", children="--°"),
        ], style={"marginTop": "5px", "marginBottom": "5px", "fontSize": "13px"}),

        html.Div(id={"type": "click-status", "m_id": "rect_course"},
                 style={"marginTop": "5px", "marginBottom": "10px", "fontStyle": "italic", "color": "#555"}),

        html.Hr(),

        html.Label("Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="rectcourse-altitude",
            type="number",
            value=800,
            min=400,
            max=1500,
            className="input-small"
        ),

        html.Label("Airspeed (KIAS)", className="input-label"),
        dcc.Input(
            id="rectcourse-ias",
            type="number",
            value=95,
            className="input-small"
        ),

        html.Label("Lateral Offset (nm)", className="input-label"),
        dcc.Input(
            id="rectcourse-width",
            type="number",
            value=0.75,
            min=0.1,
            max=1.5,
            step=0.05,
            className="input-small"
        ),
        html.Span("distance between downwind & upwind legs", style={"marginLeft": "5px", "fontSize": "11px", "color": "#666"}),

        html.Label("Pattern Direction", className="input-label"),
        dcc.RadioItems(
            id="rectcourse-direction",
            options=[
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"}
            ],
            value="left",
            inline=True,
            className="radio-inline-group"
        ),

        html.Label("Number of Circuits", className="input-label"),
        dcc.Input(
            id="rectcourse-circuits",
            type="number",
            value=1,
            min=1,
            max=3,
            step=1,
            className="input-small"
        ),

        html.Hr(),

        html.Div([
            html.Button("Draw Rectangular Course", id="rectcourse-draw-btn", className="blue-button")
        ]),

        # Time slider for scrubbing through hover points
        html.Div(id="rectcourse-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="rectcourse-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data, path, and calculated values
        dcc.Store(id="rectcourse-hover-store", data=[]),
        dcc.Store(id="rectcourse-path-store", data=[]),
        dcc.Store(id="rectcourse-warnings-store", data={}),
        # Note: rectcourse-calculated-edge is in main layout (required for callback)

        # Info display area
        html.Div(id="rectcourse-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]

def pylons_layout():
    """Eights on Pylons - commercial pilot maneuver with integrated pivotal altitude calculator."""
    return [
        # Explanation of the pivotal altitude calculation
        html.Div([
            html.Strong("Pivotal Altitude Calculator"),
            html.P("Altitude is automatically calculated based on groundspeed using PA = GS²/11.3",
                   style={"fontSize": "12px", "color": "#666", "margin": "4px 0 10px 0"}),
        ], style={"backgroundColor": "#e8f4e8", "padding": "8px", "borderRadius": "4px", "marginBottom": "12px"}),

        html.Label("Indicated Airspeed (KIAS)", className="input-label"),
        dcc.Input(id="pylons-ias", type="number", value=100, min=60, max=150, className="input-small"),

        html.Label("Number of Figure-8s", className="input-label"),
        dcc.Dropdown(
            id="pylons-num-eights",
            className="dropdown",
            options=[
                {"label": "1", "value": 1},
                {"label": "2", "value": 2},
                {"label": "3", "value": 3},
            ],
            value=1,
            clearable=False,
            style={"width": "80px"}
        ),

        html.Label("Entry Direction", className="input-label"),
        dcc.Dropdown(
            id="pylons-entry-direction",
            className="dropdown",
            options=[
                {"label": "Downwind (recommended)", "value": "downwind"},
                {"label": "Upwind", "value": "upwind"},
            ],
            value="downwind",
            clearable=False,
        ),

        html.Div("Click to set pylon locations (0.5-1.0 NM apart, perpendicular to wind):", style={
            "fontWeight": "bold",
            "marginTop": "12px"
        }),

        html.Div([
            html.Button("Set Pylon 1", id={"type": "click-button", "m_id": "pylons", "role": "pylon_a"}, className="green-button"),
            html.Button("Set Pylon 2", id={"type": "click-button", "m_id": "pylons", "role": "pylon_b"}, className="green-button", style={"marginLeft": "10px"}),
        ]),
        html.Div(id={"type": "click-status", "m_id": "pylons"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

        html.Div(style={"marginTop": "15px"}),
        html.Button("Draw Eights on Pylons", id="pylons-draw-btn", className="blue-button"),

        # Time scrubber (hidden until path is drawn)
        html.Div(id="pylons-slider-container", style={"display": "none"}, children=[
            html.Label("Time Scrubber", className="input-label"),
            dcc.Slider(
                id="pylons-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={},
                tooltip={"placement": "bottom", "always_visible": False}
            ),
        ]),
        dcc.Store(id="pylons-hover-store", data=[]),
        dcc.Store(id="pylons-path-store", data=[]),

        # Info panel
        html.Div(id="pylons-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]

# === Utility Callbacks ===


from dash import callback, Input, Output

@callback(
    Output("total-weight-display", "value"),
    Output("runtime-total-weight-lb", "data"),
    Input("aircraft-select", "value"),
    Input("occupants", "value"),
    Input("occupant-weight", "value"),
    Input("fuel-load", "value"),
)
def update_total_weight_display(ac_name, occupants, occupant_wt, fuel_gal):
    if not ac_name or ac_name not in aircraft_data:
        return "", None

    ac = aircraft_data[ac_name]
    empty_wt = float(ac.get("empty_weight", 0.0))
    fuel_per_gal = float(ac.get("fuel_weight_per_gal", 6.0))

    occ = float(occupants or 0)
    occ_wt = float(occupant_wt or 0)
    fuel = float(fuel_gal or 0)

    total = empty_wt + (occ * occ_wt) + (fuel * fuel_per_gal)
    total_round = int(round(total))

    return f"{total_round}", total


@app.callback(
    Output("map", "center"),
    Output("env-airport-agl", "children"),
    Output("selected-airport-id", "data"),
    Output("airport-search-input", "value"),
    Input({"type": "airport-result", "index": ALL}, "n_clicks"),
    prevent_initial_call=True
)
def handle_airport_result_click(n_clicks_list):
    if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
        raise PreventUpdate

    airport_id = ctx.triggered_id.get("index")
    ap = next((a for a in airport_data if a.get("id") == airport_id), None)
    if not ap:
        raise PreventUpdate

    lat, lon = ap["lat"], ap["lon"]
    elev = ap.get("elevation_ft", "---")

    # Fill the input with the selected airport ID
    return [lat, lon], f"{elev} ft", airport_id, airport_id

@app.callback(
    Output("airport-search-results", "children"),
    Input("airport-search-input", "value")
)
def search_airport_database(query):
    if not query or len(query.strip()) < 2:
        return []

    q = query.strip().lower()

    # If the input is already an exact airport ID, hide the dropdown.
    exact = next((ap for ap in airport_data if ap.get("id", "").lower() == q), None)
    if exact is not None:
        return []

    matches = []
    for ap in airport_data:
        ap_id = ap.get("id", "").lower()
        ap_name = ap.get("name", "").lower()
        if q in ap_id or q in ap_name:
            matches.append(ap)
        if len(matches) >= 10:
            break

    return [
        html.Div(
            f"{ap['name']} ({ap['id']})",
            className="airport-result",
            id={"type": "airport-result", "index": ap["id"]},
            n_clicks=0
        )
        for ap in matches
    ]



# === Maneuver Dispatcher ===
@app.callback(
    Output("maneuver-params-container", "children"),
    Input("maneuver-select", "value"),
    State("selected-airport-id", "data")
)
def render_maneuver_layout(maneuver, airport_id):
    elev_ft = None
    if airport_id:
        ap = next((a for a in airport_data if a["id"] == airport_id), None)
        elev_ft = ap.get("elevation_ft", None) if ap else None

    if maneuver == "impossible_turn":
        return impossible_turn_layout()
    elif maneuver == "poweroff180":
        return poweroff180_layout(default_elev=elev_ft)
    elif maneuver == "engineout":
        return engineout_layout()
    elif maneuver == "steep_turn":
        return steep_turn_layout()
    elif maneuver == "chandelle":
        return chandelle_layout()
    elif maneuver == "lazy8":
        return lazy8_layout()
    elif maneuver == "steep_spiral":
        return steep_spiral_layout()
    elif maneuver == "s_turn":
        return s_turn_layout()
    elif maneuver == "turns_point":
        return turns_point_layout()
    elif maneuver == "rect_course":
        return rect_course_layout()
    elif maneuver == "pylons":
        return pylons_layout()
    return []

# === Aircraft Fields Update ===
@app.callback(
    Output("engine-select", "options"),
    Output("engine-select", "value"),
    Output("occupants", "value"),
    Output("occupant-weight", "value"),
    Output("fuel-load", "max"),
    Output("fuel-load", "value"),
    Output("fuel-load", "marks"),
    Output("cg-slider", "min"),
    Output("cg-slider", "max"),
    Output("cg-slider", "value"),
    Output("cg-slider", "marks"),
    Input("aircraft-select", "value")
)
def update_aircraft_fields(selected_aircraft):
    if not selected_aircraft or selected_aircraft not in aircraft_data:
        return (
            [], None, 1, 180,
            50, 50,
            {0: "0", 12: "¼", 25: "½", 37: "¾", 50: "Full"},
            0.0, 1.0, 0.5,
            {0.0: "FWD", 0.5: "MID", 1.0: "AFT"}
        )

    ac = aircraft_data[selected_aircraft]
    engine_options = [{"label": k, "value": k} for k in ac.get("engine_options", {}).keys()]
    default_engine = engine_options[0]["value"] if engine_options else None
    seats = ac.get("seats", 2)
    default_occupants = min(seats, 2)
    default_weight = 180
    fuel_cap = ac.get("fuel_capacity_gal", 50)
    fuel_marks = {
        0: "0",
        int(0.25 * fuel_cap): "¼",
        int(0.5 * fuel_cap): "½",
        int(0.75 * fuel_cap): "¾",
        int(fuel_cap): "Full"
    }
    cg_range = ac.get("cg_range", [0.0, 1.0])
    cg_min = cg_range[0]
    cg_max = cg_range[1]
    cg_default = round((cg_min + cg_max) / 2, 2)
    cg_marks = {
        round(cg_min, 2): "FWD",
        round((cg_min + cg_max) / 2, 2): "MID",
        round(cg_max, 2): "AFT"
    }
    return (engine_options, default_engine, default_occupants, default_weight, fuel_cap,
            fuel_cap, fuel_marks, cg_min, cg_max, cg_default, cg_marks)

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
    Input("map", "clickData"),
    State("active-click-target", "data"),
    State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
    State({"type": "point-store", "m_id": ALL, "role": ALL}, "data"),
    State("layer", "children"),
    prevent_initial_call=True
)
def write_point_to_scoped_store(click, target, store_ids, store_data, layer_children):
    if not click or "latlng" not in click or not isinstance(target, dict):
        raise PreventUpdate

    m_id = target.get("m_id")
    role = target.get("role")
    if not m_id or not role:
        raise PreventUpdate

    lat = click["latlng"]["lat"]
    lon = click["latlng"]["lng"]
    elev = get_elevation(lat, lon)

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

    # Clear target after one successful click so extra clicks don’t overwrite
    return updated, None, new_layer

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
        print(f"❌ Open-Meteo elevation lookup failed: {e}")
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


# === Impossible Turn Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output({"type": "click-status", "m_id": "impossible_turn"}, "children", allow_duplicate=True),
    Output("impossibleturn-result", "children", allow_duplicate=True),
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
    State("impossibleturn-touchdown-heading", "value"),
    State("impossibleturn-altitude", "value"),
    State("impossibleturn-reaction-sec", "value"),
    State("impossibleturn-entry-ias", "value"),
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
    runway_heading,
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
        return [], None, "⚠️ Set engine failure point first.", ""

    if not ac_name or not engine_key:
        return [], None, "⚠️ Select aircraft and engine first.", ""

    try:
        states = dash.callback_context.states

        def safe_float(state_key):
            v = states.get(state_key)
            return float(v) if v not in [None, "", "null"] else None

        runway_heading  = safe_float("impossibleturn-touchdown-heading.value")
        failure_alt_agl = safe_float("impossibleturn-altitude.value")
        reaction_sec    = safe_float("impossibleturn-reaction-sec.value")
        entry_ias       = safe_float("impossibleturn-entry-ias.value")
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
            return [], None, "⚠️ Missing or invalid inputs.", ""

        failure_pt = GeoPoint(failure_data["lat"], failure_data["lon"])

        # Aircraft dict copy + stash runtime weight (no JSON changes)
        ac = dict(aircraft_data[ac_name])
        ac["total_weight_lb"] = float(total_wt)

        # Airport elevation reference
        selected_airport = next((a for a in airport_data if a.get("id") == selected_airport_id), None)
        airport_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

        # OAT F -> C
        oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0

        path, hover, meta = simulate_impossible_turn(
            start_point=failure_pt,
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
        )

        if not path:
            return [], None, "⚠️ No path generated. Check inputs.", ""

        # Meta
        meta = meta or {}
        made_it      = bool(meta.get("success", False))
        impact       = meta.get("impact_marker", None)
        reason       = meta.get("reason", "unknown")
        min_required = meta.get("min_feasible_alt_agl", None)
        bank_deg     = meta.get("bank_deg", None)
        # Distance (NM): failure point -> impact (if any) else -> end of path
        dist_nm = None
        try:
            if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
                end_pt = GeoPoint(float(impact[0]), float(impact[1]))
                dist_nm = geo_distance(failure_pt, end_pt).nm
                dist_label = "Failure distance to impact"
            else:
                end_lat, end_lon = path[-1][0], path[-1][1]
                end_pt = GeoPoint(float(end_lat), float(end_lon))
                dist_nm = geo_distance(failure_pt, end_pt).nm
                dist_label = "Failure distance to touchdown"
        except Exception:
            dist_nm = None
            dist_label = "Distance"

        dist_txt = f"{dist_label}: {dist_nm:.2f} NM" if isinstance(dist_nm, (int, float)) else f"{dist_label}: n/a"
        
        # Markers
        start_marker = dl.CircleMarker(
            center=[failure_pt.latitude, failure_pt.longitude],
            radius=7,
            color="green",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip("Engine failure point"),
        )

        elements = [start_marker]

        # ---------- Core visuals: full glide track + hover markers ----------
        arc_line = dl.Polyline(positions=path, color="red", weight=3)

        hover_markers = []
        if hover and isinstance(hover, list):
            for i, pt in enumerate(hover):
                # thin markers (match PO180 pattern). Change 5 -> 1 if you truly want every point.
                if i % 5 != 0 or i >= len(path):
                    continue

                # Safely pull fields
                alt   = pt.get("alt")
                tas   = pt.get("tas")
                gs    = pt.get("gs")
                t_sec = pt.get("time")
                aob   = pt.get("aob")
                vs    = pt.get("vs")
                track = pt.get("track")
                hdg   = pt.get("heading")
                drift = pt.get("drift")

                # Build tooltip: ALL rounded to 0 decimals except time if you want tenths
                tooltip_children = []

                if alt is not None:
                    tooltip_children.append(html.Div(f"{float(alt):.0f} ft AGL"))
                if tas is not None:
                    tooltip_children.append(html.Div(f"TAS: {float(tas):.0f} kt"))
                if gs is not None:
                    tooltip_children.append(html.Div(f"GS: {float(gs):.0f} kt"))

                if t_sec is not None:
                    tooltip_children.append(html.Div(f"Time: {float(t_sec):.0f} sec"))
                if aob is not None:
                    tooltip_children.append(html.Div(f"AOB: {float(aob):.0f}°"))
                if vs is not None:
                    tooltip_children.append(html.Div(f"VS: {float(vs):.0f} fpm"))

                if track is not None:
                    tooltip_children.append(html.Div(f"Track: {float(track):.0f}°"))
                if hdg is not None:
                    tooltip_children.append(html.Div(f"Hdg: {float(hdg):.0f}°"))
                if drift is not None:
                    tooltip_children.append(html.Div(f"Drift: {float(drift):+.0f}°"))

                hover_markers.append(
                    dl.CircleMarker(
                        center=path[i],
                        radius=3,
                        color="red",
                        fill=True,
                        fillOpacity=0.8,
                        children=dl.Tooltip(tooltip_children),
                    )
                )

        # Add to elements
        elements.append(arc_line)
        elements.extend(hover_markers)

        # Impact marker
        if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
            elements.append(
                dl.CircleMarker(
                    center=[impact[0], impact[1]],
                    radius=7,
                    color="black",
                    fill=True,
                    fillOpacity=1.0,
                    children=dl.Tooltip("Impact point"),
                )
            )

        # Bounds
        lats = [p[0] for p in path] + [failure_pt.latitude]
        lons = [p[1] for p in path] + [failure_pt.longitude]
        if impact and isinstance(impact, (list, tuple)) and len(impact) == 2:
            lats.append(impact[0])
            lons.append(impact[1])
        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

        # Status
        if made_it:
            status = "✅ Impossible turn: succesful"
        else:
            status = f"⚠️ Impossible turn: unsuccessful ({reason})."

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

        return elements, bounds, status, result

    except Exception as e:
        print(f"❌ EXCEPTION in draw_impossible_turn(): {e}")
        return [], None, f"⚠️ Error: {str(e)}", ""
    
# === Power-Off 180 Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output({"type": "click-status", "m_id": "poweroff180"}, "children", allow_duplicate=True),
    Input("poweroff180-draw-btn", "n_clicks"),
    State({"type": "point-store", "m_id": "poweroff180", "role": "touchdown"}, "data"),
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
    State("poweroff180-altitude", "value"),
    State("poweroff180-pattern", "value"),
    State("poweroff180-flap-setting", "value"),
    State("poweroff180-prop-condition", "value"),
    State("poweroff180-touchdown-heading", "value"),
    State("poweroff180-start-distance-nm", "value"),
    State("selected-airport-id", "data"),
    State("runtime-total-weight-lb", "data"),
    prevent_initial_call=True
)
def draw_poweroff180(
    n_clicks,
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
    start_alt_agl,
    pattern_dir,
    flap_setting,
    prop_condition,
    touchdown_heading,
    start_distance_nm,
    selected_airport_id,
    runtime_weight
):
    if not n_clicks or not touchdown_data:
        return [], None, "⚠️ Set a touchdown point first."

    if not ac_name or not engine_key:
        return [], None, "⚠️ Select aircraft and engine first."

    try:
        states = dash.callback_context.states

        def safe_float(key):
            val = states.get(key)
            return float(val) if val not in [None, "", "null"] else None

        start_alt_agl      = safe_float("poweroff180-altitude.value")
        touchdown_heading  = safe_float("poweroff180-touchdown-heading.value")
        wind_dir           = safe_float("env-wind-dir.value")
        wind_speed         = safe_float("env-wind-speed.value")
        oat_f              = safe_float("env-oat.value")
        altimeter          = safe_float("env-altimeter.value")
        start_distance_nm  = safe_float("poweroff180-start-distance-nm.value")

        total_wt = safe_float("runtime-total-weight-lb.data")
        if total_wt is None:
            total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None

        required = [
            start_alt_agl, touchdown_heading,
            wind_dir, wind_speed, oat_f, altimeter,
            start_distance_nm, total_wt
        ]
        if any(x is None for x in required):
            return [], None, "⚠️ Missing or invalid input values."

        touchdown = GeoPoint(touchdown_data["lat"], touchdown_data["lon"])

        downwind_heading = (touchdown_heading + 180.0) % 360.0

        if pattern_dir == "left":
            offset_bearing = (touchdown_heading - 90.0) % 360.0
        else:
            offset_bearing = (touchdown_heading + 90.0) % 360.0

        start = point_from(touchdown, offset_bearing, start_distance_nm)
        start_heading = downwind_heading

        ac = dict(aircraft_data[ac_name])
        ac["total_weight_lb"] = float(total_wt)

        selected_airport = next((a for a in airport_data if a["id"] == selected_airport_id), None)
        elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

        oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0

        start_ias_kias = 80.0

        path, hover_data, impact_marker = simulate_glide_path_to_target(
            start_point=start,
            start_heading=start_heading,
            touchdown_point=touchdown,
            touchdown_heading=touchdown_heading,
            ac=ac,
            engine_option=engine_key,
            weight_lbs=float(total_wt),
            flap_config=flap_setting,
            prop_config=prop_condition,
            oat_c=float(oat_c),
            altimeter_inhg=float(altimeter),
            wind_dir=float(wind_dir),
            wind_speed=float(wind_speed),
            start_ias_kias=float(start_ias_kias),
            altitude_agl=float(start_alt_agl),
            pattern_dir=pattern_dir,
            selected_airport_elev_ft=float(elev_ft),
            max_bank_deg=45,
            timestep_sec=0.5,
        )

        if not path or not hover_data:
            return [], None, "⚠️ No glide path generated. Check inputs."

        FT_PER_NM = 6076.12

        dw_ft = hover_data[0].get("downwind_leg_ft", 0.0) or 0.0
        fn_ft = hover_data[0].get("final_leg_ft", 0.0) or 0.0

        final_out_bearing = (touchdown_heading + 180.0) % 360.0

        dw_end = None
        fn_start = None
        if dw_ft > 0.0:
            dw_nm = dw_ft / FT_PER_NM
            p_dw_end = point_from(start, start_heading, dw_nm)
            dw_end = [p_dw_end.latitude, p_dw_end.longitude]
        if fn_ft > 0.0:
            fn_nm = fn_ft / FT_PER_NM
            p_fn_start = point_from(touchdown, final_out_bearing, fn_nm)
            fn_start = [p_fn_start.latitude, p_fn_start.longitude]

        arc_line = dl.Polyline(positions=path, color="red", weight=3)

        hover_markers = []
        for i, pt in enumerate(hover_data):
            if i % 5 != 0 or i >= len(path):
                continue

            gs    = pt.get("gs")
            track = pt.get("track")
            hdg   = pt.get("heading")
            drift = pt.get("drift")

            tooltip_children = [
                html.Div(f"{pt['alt']:.0f} ft AGL"),
                html.Div(f"TAS: {pt['tas']:.0f} kt"),
            ]

            if gs is not None:
                tooltip_children.append(html.Div(f"GS: {gs:.0f} kt"))

            tooltip_children.extend([
                html.Div(f"Time: {pt['time']:.1f} sec"),
                html.Div(f"AOB: {pt['aob']:.1f}°"),
                html.Div(f"VS: {pt['vs']:.0f} fpm"),
            ])

            if track is not None:
                tooltip_children.append(html.Div(f"Track: {track:.0f}°"))
            if hdg is not None:
                tooltip_children.append(html.Div(f"Hdg: {hdg:.0f}°"))
            if drift is not None:
                tooltip_children.append(html.Div(f"Drift: {drift:+.1f}°"))

            if dw_ft > 0.0 and fn_ft > 0.0:
                dw_nm = dw_ft / FT_PER_NM
                fn_nm = fn_ft / FT_PER_NM
                tooltip_children.append(html.Hr())
                tooltip_children.append(html.Div(f"Downwind: {dw_nm:.2f} NM"))
                tooltip_children.append(html.Div(f"Final: {fn_nm:.2f} NM"))

            hover_markers.append(
                dl.CircleMarker(
                    center=path[i],
                    radius=3,
                    color="red",
                    fill=True,
                    fillOpacity=0.8,
                    children=dl.Tooltip(tooltip_children),
                )
            )

        start_marker = dl.CircleMarker(
            center=[start.latitude, start.longitude],
            radius=7,
            color="green",
            fill=True,
            fillOpacity=1.0,
        )
        touchdown_marker = dl.CircleMarker(
            center=[touchdown.latitude, touchdown.longitude],
            radius=7,
            color="red",
            fill=True,
            fillOpacity=1.0,
        )

        downwind_line = None
        final_line = None

        if dw_end is not None:
            downwind_line = dl.Polyline(
                positions=[[start.latitude, start.longitude], dw_end],
                color="orange",
                weight=2,
            )

        if fn_start is not None:
            final_line = dl.Polyline(
                positions=[fn_start, [touchdown.latitude, touchdown.longitude]],
                color="purple",
                weight=2,
            )

        elements = [start_marker, touchdown_marker] + hover_markers + [arc_line]
        if downwind_line:
            elements.append(downwind_line)
        if final_line:
            elements.append(final_line)

        if impact_marker:
            impact_lat, impact_lon = impact_marker
            impact_mark = dl.CircleMarker(
                center=[impact_lat, impact_lon],
                radius=7,
                color="black",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip("☠️Impact point☠️"),
            )
            elements.append(impact_mark)

            msg = (
                "⚠️ Glide path impacted ground before reaching touchdown at "
                f"({impact_lat:.4f}, {impact_lon:.4f}). Path flown to impact point."
            )
        else:
            msg = "✅ Power-Off 180 path flown successfully."

        lats = [pt[0] for pt in path] + [start.latitude, touchdown.latitude]
        lons = [pt[1] for pt in path] + [start.longitude, touchdown.longitude]

        if dw_end is not None:
            lats.append(dw_end[0])
            lons.append(dw_end[1])
        if fn_start is not None:
            lats.append(fn_start[0])
            lons.append(fn_start[1])
        if impact_marker:
            lats.append(impact_marker[0])
            lons.append(impact_marker[1])

        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

        return elements, bounds, msg

    except Exception as e:
        print(f"❌ EXCEPTION in draw_poweroff180(): {e}")
        return [], None, f"⚠️ Error generating path: {str(e)}"

# ============== Engine-Out Glide Rendering Callback ======================#

# === Engine-Out Glide Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("map", "bounds", allow_duplicate=True),
    Output({"type": "click-status", "m_id": "engineout"}, "children", allow_duplicate=True),
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
    State("engineout-touchdown-heading", "value"),
    State("engineout-pattern-dir", "value"),
    State("engineout-manual-elev", "value"),
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
    touchdown_heading,
    engineout_pattern_dir,
    manual_td_elev,
    selected_airport_id,
    runtime_weight
):
    if not n_clicks:
        raise PreventUpdate

    if not start_data or not touchdown_data:
        return [], None, "⚠️ Set start and touchdown points first."

    if not ac_name or not engine_key:
        return [], None, "⚠️ Select aircraft and engine first."

    try:
        states = dash.callback_context.states

        def safe_float(key):
            val = states.get(key)
            return float(val) if val not in [None, "", "null"] else None

        start_heading      = safe_float("engineout-start-heading.value")
        start_alt_agl      = safe_float("engineout-altitude.value")
        touchdown_heading  = safe_float("engineout-touchdown-heading.value")
        manual_td_elev     = safe_float("engineout-manual-elev.value")
        wind_dir           = safe_float("env-wind-dir.value")
        wind_speed         = safe_float("env-wind-speed.value")
        oat_f              = safe_float("env-oat.value")
        altimeter          = safe_float("env-altimeter.value")

        total_wt = safe_float("runtime-total-weight-lb.data")
        if total_wt is None:
            total_wt = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None

        required = [
            start_heading, start_alt_agl, touchdown_heading,
            wind_dir, wind_speed, oat_f, altimeter,
            total_wt
        ]
        if any(x is None for x in required):
            return [], None, "⚠️ Missing or invalid input values."

        start = GeoPoint(start_data["lat"], start_data["lon"])
        touchdown = GeoPoint(touchdown_data["lat"], touchdown_data["lon"])

        ac = dict(aircraft_data[ac_name])
        ac["total_weight_lb"] = float(total_wt)

        selected_airport = next((a for a in airport_data if a["id"] == selected_airport_id), None)
        airport_elev_ft = float(selected_airport.get("elevation_ft", 0.0)) if selected_airport else 0.0

        td_store_elev = touchdown_data.get("elevation_ft") if isinstance(touchdown_data, dict) else None

        if manual_td_elev is not None:
            touchdown_elev_ft = float(manual_td_elev)
        elif td_store_elev is not None:
            touchdown_elev_ft = float(td_store_elev)
        else:
            touchdown_elev_ft = float(airport_elev_ft)

        oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0

        path, hover_data, impact_marker = simulate_engineout_glide(
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
            start_ias_kias=None,
            altitude_agl=float(start_alt_agl),
            touchdown_elev_ft=float(touchdown_elev_ft),
            selected_airport_elev_ft=float(airport_elev_ft),
            max_bank_deg=45,
            timestep_sec=0.5,
            pattern_dir=engineout_pattern_dir,
        )

        if not path or not hover_data:
            return [], None, "⚠️ No glide path generated. Check inputs."

        # ---------- Core visuals: full glide track + hover markers ----------
        arc_line = dl.Polyline(positions=path, color="red", weight=3)

        hover_markers = []
        for i, pt in enumerate(hover_data):
            # Thin markers
            if i % 5 != 0 or i >= len(path):
                continue

            tooltip_children = [
                html.Div(f"{pt['alt']:.0f} ft AGL"),
                html.Div(f"TAS: {pt['tas']:.0f} kt"),
                html.Div(f"GS: {pt.get('gs', pt['tas']):.0f} kt"),
                html.Div(f"Time: {pt['time']:.1f} sec"),
                html.Div(f"AOB: {pt['aob']:.1f}°"),
                html.Div(f"VS: {pt['vs']:.0f} fpm"),
                html.Div(f"Track: {pt.get('track', 0):.0f}°"),
                html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
                html.Div(f"Drift: {pt.get('drift', 0):+.1f}°"),
            ]

            hover_markers.append(
                dl.CircleMarker(
                    center=path[i],
                    radius=3,
                    color="red",
                    fill=True,
                    fillOpacity=0.8,
                    children=dl.Tooltip(tooltip_children),
                )
            )

        # Start / touchdown markers
        start_marker = dl.CircleMarker(
            center=[start.latitude, start.longitude],
            radius=7,
            color="green",
            fill=True,
            fillOpacity=1.0,
        )
        touchdown_marker = dl.CircleMarker(
            center=[touchdown.latitude, touchdown.longitude],
            radius=7,
            color="red",
            fill=True,
            fillOpacity=1.0,
        )

        elements = [start_marker, touchdown_marker] + hover_markers + [arc_line]

        # Impact vs success messaging / marker
        if impact_marker:
            impact_lat, impact_lon = impact_marker
            impact_mark = dl.CircleMarker(
                center=[impact_lat, impact_lon],
                radius=7,
                color="black",
                fill=True,
                fillOpacity=1.0,
                children=dl.Tooltip("☠️Impact point☠️"),
            )
            elements.append(impact_mark)
            msg = (
                "⚠️ Glide path impacted ground before reaching touchdown at "
                f"({impact_lat:.4f}, {impact_lon:.4f}). Path flown to impact point."
            )
        else:
            msg = f"✅ Engine-out glide path flown successfully ({engineout_pattern_dir} pattern)."

        # ---------- Bounds ----------
        lats = [pt[0] for pt in path] + [start.latitude, touchdown.latitude]
        lons = [pt[1] for pt in path] + [start.longitude, touchdown.longitude]
        if impact_marker:
            lats.append(impact_marker[0])
            lons.append(impact_marker[1])

        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

        return elements, bounds, msg

    except Exception as e:
        print(f"❌ EXCEPTION in draw_engineout(): {e}")
        return [], None, f"⚠️ Error generating path: {str(e)}"


# === Steep Turn Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
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

    # Hover markers (every 5th point to avoid clutter)
    hover_markers = []
    for i, pt in enumerate(hover):
        if i % 5 != 0 or i >= len(path):
            continue

        tooltip_children = [
            html.Div(f"{pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"AOB: {pt.get('aob', 0):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Drift: {pt.get('drift', 0):+.1f}°"),
            html.Div(f"Segment: {pt.get('segment', '')}"),
        ]

        hover_markers.append(
            dl.CircleMarker(
                center=path[i],
                radius=3,
                color="red",
                fill=True,
                fillOpacity=0.8,
                children=dl.Tooltip(tooltip_children),
            )
        )

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

    elements = [start_marker, end_marker] + hover_markers + [path_line]

    return elements


# === Chandelle Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
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

    # Build elements matching other maneuvers' style
    path_line = dl.Polyline(positions=path, color="red", weight=3)

    # Hover markers (every 5th point)
    hover_markers = []
    for i, pt in enumerate(hover):
        if i % 5 != 0 or i >= len(path):
            continue

        tooltip_children = [
            html.Div(f"{pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt"),
            html.Div(f"TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"AOB: {pt.get('aob', 0):.1f}°"),
            html.Div(f"Pitch: {pt.get('pitch', 0):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Vs (Pwr On): {pt.get('vs_ref', 0):.0f} kt"),
            html.Div(f"Stall Margin: +{pt.get('speed_margin', 0):.0f} kt"),
            html.Div(f"Power: {pt.get('power', 'N/A')} ({pt.get('hp', 0):.0f} HP)"),
            html.Div(f"Segment: {pt.get('segment', '')}"),
        ]

        hover_markers.append(
            dl.CircleMarker(
                center=path[i],
                radius=3,
                color="red",
                fill=True,
                fillOpacity=0.8,
                children=dl.Tooltip(tooltip_children),
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

    elements = [start_marker, end_marker] + hover_markers + [path_line]

    return elements


# === Lazy Eight Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
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

    # Build elements matching other maneuvers' style
    path_line = dl.Polyline(positions=path, color="red", weight=3)

    # Hover markers (every 5th point)
    hover_markers = []
    for i, pt in enumerate(hover):
        if i % 5 != 0 or i >= len(path):
            continue

        tooltip_children = [
            html.Div(f"{pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt"),
            html.Div(f"TAS: {pt.get('tas', 0):.0f} kt"),
            html.Div(f"GS: {pt.get('gs', pt.get('tas', 0)):.0f} kt"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"AOB: {pt.get('aob', 0):.1f}°"),
            html.Div(f"Pitch: {pt.get('pitch', 0):.1f}°"),
            html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
            html.Div(f"Turn Progress: {pt.get('turn_progress', 0):.0f}°"),
            html.Div(f"Stall Margin: +{pt.get('speed_margin', 0):.0f} kt"),
            html.Div(f"Segment: {pt.get('segment', '')}"),
        ]

        hover_markers.append(
            dl.CircleMarker(
                center=path[i],
                radius=3,
                color="red",
                fill=True,
                fillOpacity=0.8,
                children=dl.Tooltip(tooltip_children),
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

    elements = [start_marker, end_marker] + hover_markers + [path_line]

    return elements


# === Steep Spiral Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
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

    # Color palette for turns (altitude-based gradient: high=green, low=red)
    turn_colors = ["#00aa00", "#66bb00", "#aacc00", "#ddaa00", "#ff8800", "#ff5500", "#ff2200", "#cc0000", "#990000", "#660000"]

    # Build path segments with altitude-based coloring
    # Group points by turn number for distinct coloring
    path_segments = []
    current_turn = 1
    segment_start = 0

    for i, pt in enumerate(hover):
        turn_num = pt.get('turn_number', 1)
        if turn_num != current_turn or i == len(hover) - 1:
            # End of current segment
            end_idx = i if i == len(hover) - 1 else i
            segment_path = path[segment_start:end_idx + 1]
            if len(segment_path) >= 2:
                color_idx = min(current_turn - 1, len(turn_colors) - 1)
                path_segments.append(
                    dl.Polyline(
                        positions=segment_path,
                        color=turn_colors[color_idx],
                        weight=3,
                        children=dl.Tooltip(f"Turn {current_turn}")
                    )
                )
            segment_start = i
            current_turn = turn_num

    # Hover markers with altitude-based coloring (every 8th point)
    hover_markers = []
    for i, pt in enumerate(hover):
        if i % 8 != 0 or i >= len(path):
            continue

        turn_num = pt.get('turn_number', 1)
        color_idx = min(turn_num - 1, len(turn_colors) - 1)

        tooltip_children = [
            html.Div(f"Turn {turn_num} - {pt.get('turn_progress', 0):.0f}°", style={"fontWeight": "bold"}),
            html.Div(f"{pt.get('alt', 0):.0f} ft AGL"),
            html.Div(f"IAS: {pt.get('ias', 0):.0f} kt | GS: {pt.get('gs', 0):.0f} kt"),
            html.Div(f"Time: {pt.get('time', 0):.1f} sec"),
            html.Div(f"AOB: {pt.get('aob', 0):.1f}° | VS: {pt.get('vs', 0):.0f} fpm"),
            html.Div(f"Hdg: {pt.get('heading', 0):.0f}° | Track: {pt.get('track', 0):.0f}°"),
            html.Div(f"Drift: {pt.get('drift', 0):.1f}°"),
        ]

        hover_markers.append(
            dl.CircleMarker(
                center=path[i],
                radius=4,
                color=turn_colors[color_idx],
                fill=True,
                fillOpacity=0.9,
                children=dl.Tooltip(tooltip_children),
            )
        )

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

    elements = [ref_marker, entry_marker, end_marker] + hover_markers + path_segments

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

    # Stats display with turn color legend
    turn_legend = " | ".join([f"Turn {i+1}" for i in range(min(num_turns, len(turn_colors)))])
    warning_elements.append(
        html.Div([
            html.Div(f"Turns completed: {warnings.get('turns_completed', 0)} of {num_turns}"),
            html.Div(f"Orbit radius: {warnings.get('orbit_radius_ft', 0):.0f} ft ({warnings.get('orbit_radius_nm', 0):.2f} nm)"),
            html.Div(f"Final altitude: {warnings.get('final_altitude_agl', 0):.0f} ft AGL"),
            html.Div(f"Altitude loss per turn: ~{warnings.get('altitude_per_turn', 0):.0f} ft"),
            html.Div(f"Suggested min start alt: {warnings.get('suggested_min_start_alt', 0):.0f} ft AGL"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div("Colors: Green (high) → Red (low altitude)", style={"fontSize": "12px", "fontStyle": "italic"}),
            html.Div("Use the Time Scrubber to view flight data at each point", style={"fontSize": "12px", "fontStyle": "italic", "marginTop": "5px"}),
        ], style={"color": "#333", "backgroundColor": "#e9ecef", "padding": "8px", "borderRadius": "4px"})
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

    return (
        elements,
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
            children=dl.Tooltip("Reference Point (on line)")
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
    Output("rectcourse-edge-length", "children"),
    Output("rectcourse-edge-bearing", "children"),
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
        return {}, "-- nm", "--°", layer_children

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

        return edge_data, f"{dist_nm:.2f} nm", f"{bearing:.0f}°", layer_children
    else:
        # Only start point set
        return {}, "-- nm", "--°", layer_children


# === S-Turn Rendering Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
    Output("sturn-info", "children"),
    Output("sturn-hover-store", "data"),
    Output("sturn-path-store", "data"),
    Output("sturn-slider-container", "style"),
    Output("sturn-time-slider", "max"),
    Output("sturn-time-slider", "marks"),
    Output("sturn-time-slider", "value"),
    Input("sturn-draw-btn", "n_clicks"),
    State({"type": "point-store", "m_id": "s_turn", "role": "ref"}, "data"),
    State("sturn-line-bearing", "value"),
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

    # Color palette for semicircles
    semicircle_colors = ["#0066cc", "#cc6600", "#0066cc", "#cc6600", "#0066cc", "#cc6600", "#0066cc", "#cc6600"]

    # Build path segments with segment-based coloring
    path_segments = []
    current_segment = hover[0].get('segment', 'approach') if hover else 'approach'
    segment_start = 0

    for i, pt in enumerate(hover):
        seg = pt.get('segment', 'approach')
        if seg != current_segment or i == len(hover) - 1:
            end_idx = i if i == len(hover) - 1 else i
            segment_path = path[segment_start:end_idx + 1]
            if len(segment_path) >= 2:
                # Determine color based on segment
                if current_segment == 'approach':
                    color = "#888888"
                elif current_segment == 'crossing':
                    color = "#00aa00"
                elif current_segment.startswith('turn_'):
                    try:
                        semi_num = int(current_segment.split('_')[1]) - 1
                        color = semicircle_colors[semi_num % len(semicircle_colors)]
                    except:
                        color = "#0066cc"
                else:
                    color = "#666666"

                path_segments.append(
                    dl.Polyline(
                        positions=segment_path,
                        color=color,
                        weight=3,
                        children=dl.Tooltip(f"{current_segment.replace('_', ' ').title()}")
                    )
                )
            segment_start = i
            current_segment = seg

    # Reference point marker
    ref_marker = dl.CircleMarker(
        center=[ref_point["lat"], ref_point["lon"]],
        radius=8,
        color="blue",
        fill=True,
        fillOpacity=0.7,
        children=dl.Tooltip("Reference Point (on line)"),
    )

    # Draw the reference line through the reference point
    import math
    line_len_nm = 0.5  # Half-mile each direction
    line_bearing_rad = math.radians(line_bearing)

    # Calculate line endpoints
    line_n_offset = line_len_nm * 6076.12 * math.cos(line_bearing_rad)  # feet
    line_e_offset = line_len_nm * 6076.12 * math.sin(line_bearing_rad)

    line_pt1_lat = ref_point["lat"] + (line_n_offset / 364567.2)
    line_pt1_lon = ref_point["lon"] + (line_e_offset / (364567.2 * math.cos(math.radians(ref_point["lat"]))))
    line_pt2_lat = ref_point["lat"] - (line_n_offset / 364567.2)
    line_pt2_lon = ref_point["lon"] - (line_e_offset / (364567.2 * math.cos(math.radians(ref_point["lat"]))))

    reference_line = dl.Polyline(
        positions=[[line_pt1_lat, line_pt1_lon], [line_pt2_lat, line_pt2_lon]],
        color="darkgreen",
        weight=2,
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

    elements = [ref_marker, reference_line]
    if entry_marker:
        elements.append(entry_marker)
    if end_marker:
        elements.append(end_marker)
    elements.extend(path_segments)

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
            warning_items.append(html.Div(f"Bank limited: {sim_warnings.get('original_bank', 0):.0f}° → {sim_warnings.get('effective_bank', 0):.0f}°"))
        if sim_warnings.get("altitude_warning"):
            warning_items.append(html.Div(f"Altitude: {sim_warnings['altitude_warning']}"))

        info_elements.append(
            html.Div(warning_items, style={"color": "#856404", "backgroundColor": "#fff3cd", "padding": "8px", "borderRadius": "4px", "marginBottom": "5px"})
        )

    # Performance data
    info_elements.append(
        html.Div([
            html.Div([
                html.Strong("Maneuver Summary"),
            ], style={"borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "5px"}),
            html.Div(f"S-Turns: {num_turns} | Reference line: {line_bearing:.0f}°"),
            html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb"),
            html.Div(f"Power: {sim_warnings.get('power_setting_pct', 50):.0f}% | CG: {sim_warnings.get('cg_position_pct', 50):.0f}%"),
            html.Div(f"IAS: {ias:.0f} kt | TAS: {sim_warnings.get('tas_knots', 0):.0f} kt"),
            html.Div(f"Density Alt: {sim_warnings.get('density_altitude_ft', 0):.0f} ft"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Turn Performance"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Turn radius: {sim_warnings.get('turn_radius_ft', 0):.0f} ft ({sim_warnings.get('turn_radius_nm', 0):.2f} nm)"),
            html.Div(f"Bank range: {sim_warnings.get('min_bank_achieved', 0):.0f}° - {sim_warnings.get('max_bank_achieved', 0):.0f}°"),
            html.Div(f"GS range: {sim_warnings.get('min_groundspeed', 0):.0f} - {sim_warnings.get('max_groundspeed', 0):.0f} kt"),
            html.Div(f"Load factor: {sim_warnings.get('load_factor', 0):.2f}G"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Altitude"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Entry: {sim_warnings.get('entry_altitude_ft', 0):.0f} ft | Final: {sim_warnings.get('final_altitude_ft', 0):.0f} ft"),
            html.Div(f"Min: {sim_warnings.get('min_altitude_ft', 0):.0f} ft | Loss: {sim_warnings.get('altitude_loss_ft', 0):.0f} ft"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Stall Margins"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Vs (clean): {sim_warnings.get('stall_speed_clean', 0):.0f} kt"),
            html.Div(f"Vs (in turn): {sim_warnings.get('stall_speed_in_turn', 0):.0f} kt"),
            html.Div(f"Total time: {sim_warnings.get('total_time_sec', 0):.0f} sec"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div("Blue = turns on one side, Orange = turns on other side", style={"fontSize": "12px", "fontStyle": "italic"}),
            html.Div("Use the Time Scrubber to view flight data at each point", style={"fontSize": "12px", "fontStyle": "italic", "marginTop": "3px"}),
        ], style={"color": "#333", "backgroundColor": "#e9ecef", "padding": "8px", "borderRadius": "4px"})
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

    return (
        elements,
        info_elements,
        hover,
        path,
        slider_style,
        slider_max,
        slider_marks,
        0,
    )


# === Helper function to create airplane marker for time scrubbers ===
def create_airplane_marker(pos, heading, tooltip_content, bank_angle=0):
    """
    Create an airplane marker that points in the direction of flight.
    Uses an F-18 Super Hornet style fighter jet icon.

    Args:
        pos: [lat, lon] position
        heading: Aircraft heading in degrees (0=North, 90=East, etc.)
        tooltip_content: List of html elements for the tooltip
        bank_angle: Bank angle for visual tilt effect (optional)

    Returns:
        dl.Marker with rotated airplane icon
    """
    import base64

    # F-18 Super Hornet style SVG pointing UP (north/0°)
    svg_airplane = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="36" height="36">
        <g transform="rotate({heading}, 50, 50)">
            <!-- Main fuselage -->
            <path d="M50,8 L54,25 L54,75 L50,88 L46,75 L46,25 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1.5"/>

            <!-- Nose cone -->
            <path d="M50,8 L53,20 L47,20 Z" fill="#636e72" stroke="#dfe6e9" stroke-width="1"/>

            <!-- Cockpit canopy -->
            <ellipse cx="50" cy="26" rx="3.5" ry="7" fill="#74b9ff" stroke="#0984e3" stroke-width="1"/>

            <!-- Leading Edge Extensions (LEX) -->
            <path d="M46,30 L35,48 L46,45 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <path d="M54,30 L65,48 L54,45 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>

            <!-- Main wings (swept delta style) -->
            <path d="M46,42 L12,62 L14,66 L46,55 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1.2"/>
            <path d="M54,42 L88,62 L86,66 L54,55 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1.2"/>

            <!-- Wing tips -->
            <path d="M12,62 L8,64 L14,66 Z" fill="#636e72" stroke="#dfe6e9" stroke-width="0.8"/>
            <path d="M88,62 L92,64 L86,66 Z" fill="#636e72" stroke="#dfe6e9" stroke-width="0.8"/>

            <!-- Horizontal stabilizers -->
            <path d="M46,72 L28,82 L30,85 L46,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <path d="M54,72 L72,82 L70,85 L54,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>

            <!-- Twin vertical tails (canted outward like F-18) -->
            <path d="M44,65 L38,62 L40,78 L46,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <path d="M56,65 L62,62 L60,78 L54,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>

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
        html.Div(f"Bank: {pt.get('aob', 0):.1f}°"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
        html.Div(f"Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Drift: {pt.get('drift', 0):.1f}°"),
    ]

    # Create airplane marker pointing in direction of heading
    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank)

    return [marker]


# === Turns Around a Point Draw Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
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

    # Color palette for turns (alternating per turn)
    turn_colors = ["#0066cc", "#cc6600", "#0066cc", "#cc6600", "#0066cc"]

    # Build path segments with turn-based coloring
    path_segments = []
    current_turn = hover[0].get('turn_number', 1) if hover else 1
    segment_start = 0

    for i, pt in enumerate(hover):
        turn_num = pt.get('turn_number', 1)
        if turn_num != current_turn or i == len(hover) - 1:
            end_idx = i if i == len(hover) - 1 else i
            segment_path = path[segment_start:end_idx + 1]
            if len(segment_path) >= 2:
                color = turn_colors[(current_turn - 1) % len(turn_colors)]
                path_segments.append(
                    dl.Polyline(
                        positions=segment_path,
                        color=color,
                        weight=3,
                        children=dl.Tooltip(f"Turn {current_turn}")
                    )
                )
            segment_start = i
            current_turn = turn_num

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

    elements = [center_marker, orbit_circle]
    if entry_marker:
        elements.append(entry_marker)
    if exit_marker:
        elements.append(exit_marker)
    elements.extend(path_segments)

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

    # Performance data
    info_elements.append(
        html.Div([
            html.Div([
                html.Strong("Turns Around a Point"),
            ], style={"borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "5px"}),
            html.Div(f"Turns: {turns} | Direction: {direction.title()}"),
            html.Div(f"Orbit radius: {sim_warnings.get('orbit_radius_ft', 0):.0f} ft ({sim_warnings.get('orbit_radius_nm', 0):.2f} nm)"),
            html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb"),
            html.Div(f"Power: {sim_warnings.get('power_setting_pct', 50):.0f}% | CG: {sim_warnings.get('cg_position_pct', 50):.0f}%"),
            html.Div(f"IAS: {ias:.0f} kt | TAS: {sim_warnings.get('tas_knots', 0):.0f} kt"),
            html.Div(f"Density Alt: {sim_warnings.get('density_altitude_ft', 0):.0f} ft"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Bank Angle (varies with wind)"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Downwind (max): {sim_warnings.get('max_bank_achieved', 0):.0f}°"),
            html.Div(f"Upwind (min): {sim_warnings.get('min_bank_achieved', 0):.0f}°"),
            html.Div(f"GS range: {sim_warnings.get('min_groundspeed', 0):.0f} - {sim_warnings.get('max_groundspeed', 0):.0f} kt"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Altitude"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Entry: {sim_warnings.get('entry_altitude_ft', 0):.0f} ft | Final: {sim_warnings.get('final_altitude_ft', 0):.0f} ft"),
            html.Div(f"Min: {sim_warnings.get('min_altitude_ft', 0):.0f} ft | Loss: {sim_warnings.get('altitude_loss_ft', 0):.0f} ft"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Stall Margins"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Vs (clean): {sim_warnings.get('stall_speed_clean', 0):.0f} kt"),
            html.Div(f"Total time: {sim_warnings.get('total_time_sec', 0):.0f} sec"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div("Blue = Turn 1, 3, 5... | Orange = Turn 2, 4...", style={"fontSize": "12px", "fontStyle": "italic"}),
            html.Div("Bank steepens downwind (high GS), shallows upwind (low GS)", style={"fontSize": "12px", "fontStyle": "italic", "marginTop": "3px"}),
        ], style={"color": "#333", "backgroundColor": "#e9ecef", "padding": "8px", "borderRadius": "4px"})
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

    return (
        elements,
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
        html.Div(f"Bank: {pt.get('aob', 0):.1f}°"),
        html.Div(f"Load factor: {pt.get('load_factor', 1.0):.2f}G"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
        html.Div(f"Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Drift: {pt.get('drift', 0):.1f}°"),
    ]

    # Create airplane marker pointing in direction of heading
    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank)

    return [marker]


# === Rectangular Course Draw Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
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

    # Color palette for segments
    segment_colors = {
        "entry": "#9933ff",       # Purple for 45° entry
        "downwind": "#cc0000",    # Red
        "base": "#0066cc",        # Blue
        "upwind": "#00aa00",      # Green
        "crosswind": "#cc6600",   # Orange
    }
    turn_color = "#666666"  # Gray for turns

    # Build path segments with segment-based coloring
    path_segments = []
    current_segment = hover[0].get('segment', 'entry') if hover else 'entry'
    segment_start = 0

    for i, pt in enumerate(hover):
        seg = pt.get('segment', 'entry')
        if seg != current_segment or i == len(hover) - 1:
            end_idx = i if i == len(hover) - 1 else i
            segment_path = path[segment_start:end_idx + 1]
            if len(segment_path) >= 2:
                # Determine color
                if current_segment.startswith('turn_'):
                    color = turn_color
                    tooltip_text = current_segment.replace('_', ' ').title()
                else:
                    color = segment_colors.get(current_segment, "#666666")
                    if current_segment == "entry":
                        tooltip_text = "45° Entry"
                    else:
                        tooltip_text = current_segment.title() + " Leg"

                path_segments.append(
                    dl.Polyline(
                        positions=segment_path,
                        color=color,
                        weight=3,
                        children=dl.Tooltip(tooltip_text)
                    )
                )
            segment_start = i
            current_segment = seg

    # Entry/Exit marker (at the intercept point on downwind - path start and end)
    elements = []
    if path:
        entry_marker = dl.CircleMarker(
            center=path[0],
            radius=7,
            color="#9933ff",
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(f"45° Entry/Exit: {altitude:.0f} ft AGL"),
        )
        elements.append(entry_marker)

    elements.extend(path_segments)

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

    # Performance data
    info_elements.append(
        html.Div([
            html.Div([
                html.Strong("Rectangular Course"),
            ], style={"borderBottom": "1px solid #ccc", "paddingBottom": "3px", "marginBottom": "5px"}),
            html.Div(f"Downwind: {dw_length_nm:.2f} nm | Track: {dw_track:.0f}°"),
            html.Div(f"Lateral offset: {lateral_nm:.2f} nm ({lateral_nm * 6076:.0f} ft)"),
            html.Div(f"Pattern: {direction.title()} | Circuits: {circuits}"),
            html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb"),
            html.Div(f"Power: {sim_warnings.get('power_setting_pct', 50):.0f}% | CG: {sim_warnings.get('cg_position_pct', 50):.0f}%"),
            html.Div(f"IAS: {ias:.0f} kt | TAS: {sim_warnings.get('tas_knots', 0):.0f} kt"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Wind Correction"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Wind: {sim_warnings.get('wind_dir', 0):.0f}° at {sim_warnings.get('wind_speed', 0):.0f} kt"),
            html.Div(f"Max crab angle: {sim_warnings.get('max_crab_angle', 0):.1f}°"),
            html.Div(f"GS range: {sim_warnings.get('min_groundspeed', 0):.0f} - {sim_warnings.get('max_groundspeed', 0):.0f} kt"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div([
                html.Strong("Turn Performance"),
            ], style={"marginBottom": "3px"}),
            html.Div(f"Turn radius: {sim_warnings.get('turn_radius_ft', 0):.0f} ft"),
            html.Div(f"Bank range: {sim_warnings.get('min_bank_achieved', 0):.0f}° - {sim_warnings.get('max_bank_achieved', 0):.0f}°"),
            html.Div(f"Vs (clean): {sim_warnings.get('stall_speed_clean', 0):.0f} kt"),
            html.Div(f"Total time: {sim_warnings.get('total_time_sec', 0):.0f} sec"),
            html.Hr(style={"margin": "5px 0"}),
            html.Div("Purple=Entry, Red=Downwind, Blue=Base, Green=Upwind, Orange=Crosswind", style={"fontSize": "12px", "fontStyle": "italic"}),
            html.Div("Bank steeper entering from downwind (high GS)", style={"fontSize": "12px", "fontStyle": "italic", "marginTop": "3px"}),
        ], style={"color": "#333", "backgroundColor": "#e9ecef", "padding": "8px", "borderRadius": "4px"})
    )

    # Slider configuration
    num_points = len(hover)
    slider_max = max(0, num_points - 1)
    slider_marks = {0: "Start"}
    if slider_max > 0:
        slider_marks[slider_max] = "End"
    slider_style = {"display": "block", "marginTop": "10px"}

    # Combine cleaned layer (without preview) with new elements
    final_layer = layer_children + elements

    return (
        final_layer,
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
        html.Div(f"Bank: {pt.get('aob', 0):.1f}°"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
        html.Div(f"Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Crab: {pt.get('crab', '0°')}"),
    ]

    # Create airplane marker pointing in direction of heading
    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank)

    return [marker]


# === Eights on Pylons Draw Callback ===
@app.callback(
    Output("layer", "children", allow_duplicate=True),
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
            html.Div("Please set both pylon locations first.", style={"color": "red"}),
            [], [], {"display": "none"}, 0, {}, 0
        )

    pylon1 = {"lat": pylon_a_data.get("lat"), "lon": pylon_a_data.get("lon")}
    pylon2 = {"lat": pylon_b_data.get("lat"), "lon": pylon_b_data.get("lon")}

    if not pylon1.get("lat") or not pylon2.get("lat"):
        return (
            layer_children or [],
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
        entry_direction=entry_dir,
    )

    if not path:
        return (
            layer_children,
            html.Div("Failed to generate path. Check inputs.", style={"color": "red"}),
            [], [], {"display": "none"}, 0, {}, 0
        )

    # Build polyline with hover data
    from rendering import render_hover_polyline
    polyline = render_hover_polyline(
        path, hover,
        color='#9b59b6',  # Purple
        weight=4
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

    elements = [polyline] + pylon_markers

    # Build warnings if any
    warning_elements = []
    if sim_warnings.get("airspeed_warning"):
        warning_elements.append(html.Div(f"Warning: {sim_warnings['airspeed_warning']}", style={"color": "#c0392b", "fontWeight": "bold"}))
    if sim_warnings.get("bank_limited"):
        warning_elements.append(html.Div("Bank angle limited to 40° (ACS maximum)", style={"color": "#e67e22"}))
    if sim_warnings.get("stall_margin_warning"):
        warning_elements.append(html.Div("Warning: Stall margin below 1.2", style={"color": "#c0392b"}))
    # ACS compliance warnings
    if sim_warnings.get("pylon_distance_warning"):
        warning_elements.append(html.Div(f"⚠ {sim_warnings['pylon_distance_warning']}", style={"color": "#e67e22"}))
    if sim_warnings.get("transition_time_warning"):
        warning_elements.append(html.Div(f"ℹ {sim_warnings['transition_time_warning']}", style={"color": "#3498db"}))

    # Build info panel - prominently featuring pivotal altitude
    info_elements = html.Div([
        html.Div(warning_elements) if warning_elements else None,

        html.Div([
            html.Strong("Pivotal Altitude Calculator Results"),
        ], style={"marginBottom": "8px", "fontSize": "14px", "borderBottom": "2px solid #27ae60", "paddingBottom": "4px"}),

        # The main output - pivotal altitude range
        html.Div([
            html.Div(f"Upwind (min GS): {sim_warnings.get('pivotal_alt_min', 0):.0f} ft AGL", style={"fontSize": "13px"}),
            html.Div(f"Downwind (max GS): {sim_warnings.get('pivotal_alt_max', 0):.0f} ft AGL", style={"fontSize": "13px"}),
            html.Div(f"Average: {sim_warnings.get('pivotal_alt_avg', 0):.0f} ft AGL", style={"fontSize": "13px", "fontWeight": "bold"}),
            html.Div(f"Altitude range: {sim_warnings.get('pivotal_alt_range', 0):.0f} ft", style={"fontSize": "13px", "color": "#e67e22"}),
        ], style={"backgroundColor": "#e8f8e8", "padding": "8px", "borderRadius": "4px", "marginBottom": "10px"}),

        html.Div(f"No-wind pivotal altitude: {sim_warnings.get('pivotal_alt_no_wind', 0):.0f} ft AGL (GS²/11.3)",
                 style={"fontSize": "11px", "color": "#666", "marginBottom": "8px"}),

        html.Hr(style={"margin": "5px 0"}),
        html.Div([
            html.Strong("Groundspeed & Bank"),
        ], style={"marginBottom": "3px"}),
        html.Div(f"GS range: {sim_warnings.get('min_groundspeed', 0):.0f} - {sim_warnings.get('max_groundspeed', 0):.0f} kt"),
        html.Div(f"Bank range: {sim_warnings.get('min_bank_achieved', 0):.0f}° - {sim_warnings.get('max_bank_achieved', 0):.0f}°"),

        html.Hr(style={"margin": "5px 0"}),
        html.Div([
            html.Strong("Geometry & Timing"),
        ], style={"marginBottom": "3px"}),
        html.Div(f"Pylon separation: {sim_warnings.get('pylon_distance_nm', 0):.2f} nm ({sim_warnings.get('pylon_distance_ft', 0):.0f} ft)"),
        html.Div(f"Transition time: {sim_warnings.get('transition_time_avg_sec', 0):.1f} sec (ACS: 3-5 sec)"),
        html.Div(f"Turn arcs: P1={sim_warnings.get('p1_arc_degrees', 180):.0f}° | P2={sim_warnings.get('p2_arc_degrees', 180):.0f}°"),
        html.Div(f"Turn radius: {sim_warnings.get('turn_radius_ft', 0):.0f} ft"),

        html.Hr(style={"margin": "5px 0"}),
        html.Div([
            html.Strong("Aircraft"),
        ], style={"marginBottom": "3px"}),
        html.Div(f"IAS: {sim_warnings.get('ias_knots', 0):.0f} kt | TAS: {sim_warnings.get('tas_knots', 0):.0f} kt"),
        html.Div(f"Weight: {sim_warnings.get('weight_lb', 0):.0f} lb"),
        html.Div(f"Vs (clean): {sim_warnings.get('stall_speed_clean', 0):.0f} kt | Va: {sim_warnings.get('maneuvering_speed', 0):.0f} kt"),
        html.Div(f"Wind: {sim_warnings.get('wind_dir', 0):.0f}° at {sim_warnings.get('wind_speed', 0):.0f} kt"),

        html.Hr(style={"margin": "5px 0"}),
        html.Div(f"Total time: {sim_warnings.get('total_time_sec', 0):.0f} sec | Entry: {entry_dir.title()}",
                 style={"fontSize": "11px", "fontStyle": "italic"}),
        html.Div("Climb with tailwind (higher GS), descend with headwind (lower GS)",
                 style={"fontSize": "11px", "fontStyle": "italic", "color": "#666", "marginTop": "4px"}),
    ], style={"color": "#333", "backgroundColor": "#e9ecef", "padding": "8px", "borderRadius": "4px"})

    # Slider configuration
    num_points = len(hover)
    slider_max = max(0, num_points - 1)
    slider_marks = {0: "Start"}
    if slider_max > 0:
        slider_marks[slider_max] = "End"
    slider_style = {"display": "block", "marginTop": "10px"}

    final_layer = layer_children + elements

    return (
        final_layer,
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
        html.Div(f"Bank: {pt.get('aob', 0):.1f}°"),
        html.Div(f"Load: {pt.get('load_factor', 1.0):.2f}G"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
        html.Div(f"Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Wind corr: {pt.get('wind_correction', 0):.1f}°"),
    ]

    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank)

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
        html.Div(f"Bank: {pt.get('aob', 0):.1f}°"),
        html.Div(f"VS: {pt.get('vs', 0):.0f} fpm"),
        html.Div(f"Heading: {pt.get('heading', 0):.0f}°"),
        html.Div(f"Track: {pt.get('track', 0):.0f}°"),
        html.Div(f"Drift: {pt.get('drift', 0):.1f}°"),
    ]

    # Create airplane marker pointing in direction of heading
    heading = pt.get('heading', 0)
    bank = pt.get('aob', 0)
    marker = create_airplane_marker(pos, heading, tooltip_content, bank)

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
    Input("open-disclaimer", "n_clicks"),
    Input("close-disclaimer", "n_clicks"),
    Input("open-terms-policy", "n_clicks"),
    Input("close-terms-policy", "n_clicks"),
    State("disclaimer-modal", "is_open"),
    State("terms-policy-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_legal_modals(open_disc, close_disc, open_terms, close_terms, disc_open, terms_open):
    trigger = ctx.triggered_id

    if trigger == "open-disclaimer":
        return True, False
    if trigger == "close-disclaimer":
        return False, terms_open
    if trigger == "open-terms-policy":
        return disc_open, True
    if trigger == "close-terms-policy":
        return disc_open, False

    return no_update, no_update

if __name__ == "__main__":
    app.run(debug=True)
