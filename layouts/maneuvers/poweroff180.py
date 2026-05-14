"""Power-Off 180 parameter form.

Accuracy approach from downwind abeam the touchdown point. Pilot picks
runway, pattern direction, flap setting, prop condition, abeam distance,
and pattern altitude; the simulation computes whether the aircraft can
glide to the runway within ACS standards.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/poweroff180.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

from layouts.desktop import _reset_buttons_row


def poweroff180_layout(default_elev=None):
    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Simulates a power-off 180° accuracy approach from downwind abeam the touchdown point. ",
                    "Energy-based model calculates optimal glide path with automatic slip if needed."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS Standard: -0/+200 ft (cannot land short, up to 200 ft beyond)", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• Uses aircraft best glide speed and calculated bank angles", style={"fontSize": "11px", "color": "#555"}),
                html.Div("• Forward slip automatically applied when high on energy", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

        html.Label("Select Runway", className="input-label"),
        dcc.Dropdown(
            id="poweroff180-runway-select",
            placeholder="Select airport first...",
            clearable=True,
            searchable=False,
            style={"marginBottom": "5px"}
        ),
        html.Div(id="poweroff180-runway-info", style={"fontSize": "11px", "color": "#666", "marginBottom": "10px"}),

        # Manual heading fallback (shown when no runway selected)
        html.Div([
            html.Label("Manual Runway Heading (°)", className="input-label"),
            dcc.Input(
                id="poweroff180-manual-heading",
                type="number",
                value=360,
                min=1,
                max=360,
                step=1,
                className="input-small",
                placeholder="Enter heading..."
            ),
        ], id="poweroff180-manual-heading-div"),

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

        html.Label("Abeam Distance (NM)", className="input-label"),
        dcc.Slider(
            id="poweroff180-abeam-distance-nm",
            min=0.3,
            max=1.5,
            step=0.05,
            value=0.5,
            marks={
                0.3: "0.3",
                0.5: "0.5",
                0.75: "0.75",
                1.0: "1.0",
                1.25: "1.25",
                1.5: "1.5",
            },
            tooltip={"always_visible": True}
        ),

        html.Label("Pattern Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="poweroff180-altitude",
            type="number",
            value=1000,
            min=500,
            max=2000,
            step=100,
            className="input-small"
        ),

        html.Hr(),

        # ---- Map Interaction Buttons (grouped) ----
        html.Div([
            html.Button(
                "Set Touchdown Point",
                id={"type": "click-button", "m_id": "poweroff180", "role": "touchdown"},
                className="green-button",
                style={"width": "100%", "marginBottom": "4px"}
            ),
            html.Div("Click on the runway where you intend to touch down",
                     style={"fontSize": "10px", "color": "#666", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw Power-Off 180", id="poweroff180-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(
            id={"type": "click-status", "m_id": "poweroff180"},
            style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}
        ),

        # Time slider for scrubbing through hover points
        html.Div(id="poweroff180-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="poweroff180-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="poweroff180-hover-store", data=[]),
        dcc.Store(id="poweroff180-path-store", data=[]),
        dcc.Store(id="poweroff180-results-store", data={}),

        html.Div(id="poweroff180-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]
