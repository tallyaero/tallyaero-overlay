"""Turns Around a Point parameter form.

Ground reference maneuver maintaining a constant radius around a point
on the ground. Requires continuous bank adjustment to compensate for
wind drift.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/turns_around_point.py (Phase 1c).

Note: filename follows the simulation/ module naming convention
(turns_around_point.py); the exported function name stays
`turns_point_layout` so callers in app.py don't need to change.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def turns_point_layout():
    """Turns Around a Point - ground reference maneuver."""
    # Temporary coupling — `_reset_buttons_row` still lives in app.py until
    # Phase 1h moves shared layout helpers out. Imported lazily here to
    # avoid a circular import at module load time (app.py imports this
    # function at top level).
    from app import _reset_buttons_row

    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Ground reference maneuver maintaining a constant radius around a point on the ground. ",
                    "Requires continuous bank adjustment to compensate for wind drift."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS: constant altitude ±100 ft, constant radius, coordinate bank with GS", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• Steepest bank downwind (fastest GS), shallowest bank upwind (slowest GS)", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

        # Center Point Selection
        html.Label("Center Point (Reference)", className="input-label"),
        html.Div([
            html.Button(
                "Click to Set Center Point",
                id={"type": "click-button", "m_id": "turns_point", "role": "center"},
                className="green-button",
                style={"width": "100%", "marginBottom": "8px"}
            ),
            _reset_buttons_row(),
            html.Button("Draw Turns Around Point", id="turnspoint-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(id={"type": "click-status", "m_id": "turns_point"},
                 style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

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
