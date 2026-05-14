"""Impossible Turn parameter form.

Engine failure after takeoff scenario. Pilot picks reaction delay, turn
direction, and bank angle; the simulation computes whether the aircraft
can make it back to the runway.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/impossible_turn.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def impossible_turn_layout():
    # Temporary coupling — `_reset_buttons_row` still lives in app.py until
    # Phase 1h moves shared layout helpers out. Imported lazily here to
    # avoid a circular import at module load time (app.py imports this
    # function at top level).
    from app import _reset_buttons_row

    return [

        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Simulates engine failure during climb-out and the turn back to the runway. ",
                    "Model applies pilot reaction delay, transitions to best glide speed, and attempts to intercept the reciprocal runway heading."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div([
                    html.Strong("⚠️ Warning: ", style={"color": "#dc3545", "fontSize": "11px"}),
                    html.Span("This is a planning tool only. Actual performance varies with density altitude, wind shear, pilot technique, and aircraft condition. "
                             "Always maintain a safety margin.", style={"fontSize": "11px", "color": "#666"})
                ], style={"marginTop": "6px", "paddingTop": "6px", "borderTop": "1px solid #ddd"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

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

        html.Label("Select Runway", className="input-label"),
        dcc.Dropdown(
            id="impossibleturn-runway-select",
            placeholder="Select airport first...",
            clearable=True,
            searchable=False,
            style={"marginBottom": "5px"}
        ),
        html.Div(id="impossibleturn-runway-info", style={"fontSize": "11px", "color": "#666", "marginBottom": "10px"}),

        # Manual heading fallback (shown when no runway selected)
        html.Div([
            html.Label("Manual Runway Heading (°)", className="input-label"),
            dcc.Input(
                id="impossibleturn-manual-heading",
                type="number",
                value=360,
                min=1,
                max=360,
                step=1,
                className="input-small",
                placeholder="Enter heading..."
            ),
        ], id="impossibleturn-manual-heading-div"),

        html.Label("Engine Failure Altitude (ft AGL)", className="input-label"),
        dcc.Input(
            id="impossibleturn-altitude",
            type="number",
            value=1000,
            min=0,
            step=10,
            className="input-small"
        ),

        html.Div([
            html.Label("Climb Speed (KIAS)", className="input-label", style={"display": "inline"}),
            html.Span("ⓘ", className="tooltip-icon", id="impossibleturn-climb-tooltip", style={"marginLeft": "4px"}),
            dbc.Tooltip(
                "Auto-filled from aircraft Vy (best rate of climb). Override if using different climb speed.",
                target="impossibleturn-climb-tooltip",
                placement="right"
            ),
        ], className="input-label-with-tooltip"),
        dcc.Input(
            id="impossibleturn-climb-speed",
            type="number",
            value=75,
            min=40,
            max=200,
            step=1,
            className="input-small",
            persistence=True,
            persistence_type="local"
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

        # ---- Map Interaction Buttons (grouped) ----
        html.Div([
            html.Button(
                "Set Takeoff Point (Runway Threshold)",
                id={"type": "click-button", "m_id": "impossible_turn", "role": "start"},
                className="green-button",
                style={"width": "100%", "marginBottom": "8px"}
            ),
            _reset_buttons_row(),
            html.Button(
                "Draw Impossible Turn",
                id="impossibleturn-draw-btn",
                className="blue-button",
                style={"width": "100%", "marginTop": "8px"}
            ),
        ]),

        html.Div(
            id={"type": "click-status", "m_id": "impossible_turn"},
            style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"},
        ),

        html.Div(
            id="impossibleturn-result",
            className="weight-box",
            style={"marginTop": "10px"}
        ),

        # Time slider for scrubbing through hover points
        html.Div(id="impossibleturn-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="impossibleturn-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="impossibleturn-hover-store", data=[]),
        dcc.Store(id="impossibleturn-path-store", data=[]),

        html.Div(id="impossibleturn-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]
