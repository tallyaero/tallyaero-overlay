"""Engine-Out glide parameter form.

Pilot-centric engine failure simulation: turn to target, fly direct,
manage altitude, land. Automatically uses slips, S-turns, or 360s when
too high.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/engineout.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

from layouts.desktop import _reset_buttons_row


def engineout_layout():
    return [

        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Pilot-centric engine failure simulation: turn to target, fly direct, manage altitude, land. ",
                    "Automatically uses slips, S-turns, or 360s when too high."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div([
                    html.Strong("Warning: ", style={"color": "#dc3545", "fontSize": "11px"}),
                    html.Span("Actual glide performance varies significantly with density altitude, configuration, and technique. "
                             "Use conservative planning margins.", style={"fontSize": "11px", "color": "#666"})
                ], style={"marginTop": "6px", "paddingTop": "6px", "borderTop": "1px solid #ddd"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

        # ---- Runway Selection (auto-populates heading) ----
        html.Label("Select Runway", className="input-label"),
        dcc.Dropdown(
            id="engineout-runway-select",
            placeholder="Select airport first...",
            clearable=True,
            searchable=False,
            style={"marginBottom": "5px"}
        ),
        html.Div(id="engineout-runway-info", style={"fontSize": "11px", "color": "#666", "marginBottom": "10px"}),

        # Manual heading fallback (shown when no runway selected)
        html.Div([
            html.Label("Manual Landing Heading (°)", className="input-label"),
            dcc.Input(
                id="engineout-touchdown-heading",
                type="number",
                value=360,
                min=1,
                max=360,
                step=1,
                className="input-small",
                placeholder="Enter heading..."
            ),
        ], id="engineout-manual-heading-div"),

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

        html.Label("Touchdown Elevation (ft)", className="input-label"),
        dcc.Input(
            id="engineout-manual-elev",
            type="number",
            placeholder="from airport or map",
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
            value=5000,
            className="input-small"
        ),

        html.Label("Reaction Time (sec)", className="input-label"),
        dcc.Input(
            id="engineout-reaction-time",
            type="number",
            value=2.0,
            min=0,
            max=10,
            step=0.5,
            className="input-small"
        ),

        html.Label("Max Bank Angle (°)", className="input-label", style={"marginTop": "8px"}),
        dcc.Input(
            id="engineout-max-bank",
            type="number",
            value=45,
            min=15,
            max=60,
            className="input-small"
        ),

        # Hidden inputs for removed advanced settings (keep callbacks working)
        dcc.Input(id="engineout-speed-tau", type="hidden", value=4.0),
        dcc.Input(id="engineout-bank-tau", type="hidden", value=1.5),

        # ---- Glide Envelope Toggle ----
        dcc.Checklist(
            id="engineout-show-envelope",
            options=[{"label": " Max glide distance ring", "value": "show"}],
            value=[],
            style={"marginTop": "8px", "marginBottom": "8px", "fontSize": "12px"}
        ),

        html.Hr(),

        # ---- Map Interaction Buttons (grouped and evenly spaced) ----
        html.Div([
            html.Div([
                html.Button(
                    "Set Touchdown Point",
                    id={"type": "click-button", "m_id": "engineout", "role": "touchdown"},
                    className="green-button",
                    style={"flex": "1", "marginRight": "6px"}
                ),
                html.Button(
                    "Set Start Point",
                    id={"type": "click-button", "m_id": "engineout", "role": "start"},
                    className="green-button",
                    style={"flex": "1"}
                ),
            ], style={"display": "flex", "gap": "6px", "marginBottom": "8px"}),

            _reset_buttons_row(),
            html.Button(
                "Draw Engine-Out Glide Path",
                id="engineout-draw-btn",
                className="blue-button",
                style={"width": "100%", "marginTop": "8px"},
            ),
        ]),

        html.Div(
            id={"type": "click-status", "m_id": "engineout"},
            style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"},
        ),

        # Minimum altitude result display
        html.Div(id="engineout-min-alt-result", style={"marginTop": "8px", "fontWeight": "bold", "color": "#007bff"}),

        # Time slider for scrubbing through hover points
        html.Div(id="engineout-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="engineout-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="engineout-hover-store", data=[]),
        dcc.Store(id="engineout-path-store", data=[]),
        dcc.Store(id="engineout-envelope-store", data=[]),

        html.Div(id="engineout-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]
