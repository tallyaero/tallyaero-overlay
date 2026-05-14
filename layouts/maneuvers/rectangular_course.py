"""Rectangular Course parameter form.

Ground reference maneuver simulating a traffic pattern around a field.
Develops wind correction skills needed for consistent pattern flying.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/rectangular_course.py (Phase 1c).

Note: filename follows the simulation/ module naming convention
(rectangular_course.py); the exported function name stays
`rect_course_layout` so callers in app.py don't need to change.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def rect_course_layout():
    """Rectangular Course - ground reference maneuver simulating traffic pattern."""
    # Temporary coupling — `_reset_buttons_row` still lives in app.py until
    # Phase 1h moves shared layout helpers out. Imported lazily here to
    # avoid a circular import at module load time (app.py imports this
    # function at top level).
    from app import _reset_buttons_row

    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Ground reference maneuver simulating a traffic pattern around a field. ",
                    "Develops wind correction skills needed for consistent pattern flying."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS: constant altitude ±100 ft, uniform distance from boundaries, coordinated turns", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• Crab into wind on legs, adjust bank angle in turns based on groundspeed", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

        # Two-click downwind leg definition
        html.Label("Define Downwind Leg", className="input-label"),
        html.Div([
            html.Div([
                html.Button(
                    "1. Downwind Start",
                    id={"type": "click-button", "m_id": "rect_course", "role": "dw_start"},
                    className="green-button",
                    style={"flex": "1"}
                ),
                html.Button(
                    "2. Downwind End",
                    id={"type": "click-button", "m_id": "rect_course", "role": "dw_end"},
                    className="green-button",
                    style={"flex": "1"}
                ),
            ], style={"display": "flex", "gap": "6px", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw Rectangular Course", id="rectcourse-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(id="rectcourse-edge-visible-info",
                 style={"marginTop": "10px", "marginBottom": "5px", "fontSize": "13px"},
                 children="Click both points to see downwind leg info"),

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
