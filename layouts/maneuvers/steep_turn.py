"""Steep Turn parameter form.

Visualizes a steep turn ground track with wind correction. Pilot picks
bank angle, turn sequence (left/right/both), entry heading/altitude/speed.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/steep_turn.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def steep_turn_layout():
    # Temporary coupling — `_reset_buttons_row` still lives in app.py until
    # Phase 1h moves shared layout helpers out. Imported lazily here to
    # avoid a circular import at module load time (app.py imports this
    # function at top level).
    from app import _reset_buttons_row

    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Visualizes steep turn ground track with wind correction. ",
                    "Shows how wind affects the circular path and where to expect drift."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS: 45° bank ±5°, ±100 ft altitude, entry heading ±10°", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• Add back pressure to maintain altitude (load factor ~1.4G at 45°)", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

        html.Label("Bank Angle (°)", className="input-label"),
        dcc.Dropdown(
            id="steepturn-bank-angle",
            options=[
                {"label": "30°", "value": 30},
                {"label": "35°", "value": 35},
                {"label": "40°", "value": 40},
                {"label": "45° (Private)", "value": 45},
                {"label": "50° (Commercial)", "value": 50},
                {"label": "55°", "value": 55},
                {"label": "60°", "value": 60},
            ],
            value=45,
            clearable=False,
            style={"width": "180px", "marginBottom": "10px"}
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

        # ---- Map Interaction Buttons (grouped) ----
        html.Div([
            html.Button("Set Entry Point", id={"type": "click-button", "m_id": "steep_turn", "role": "start"},
                       className="green-button", style={"width": "100%", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw Steep Turn", id="steepturn-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(id={"type": "click-status", "m_id": "steep_turn"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

        # Time slider for scrubbing through hover points
        html.Div(id="steepturn-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="steepturn-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="steepturn-hover-store", data=[]),
        dcc.Store(id="steepturn-path-store", data=[]),

        # Info display area
        html.Div(id="steepturn-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]
