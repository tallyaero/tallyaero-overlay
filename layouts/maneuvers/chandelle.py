"""Chandelle parameter form.

Maximum performance 180° climbing turn combining max climb rate and
heading change. Pilot picks entry heading, bank angle, direction,
entry altitude/speed.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/chandelle.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

from layouts.desktop import _reset_buttons_row


def chandelle_layout():
    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Maximum performance 180° climbing turn combining the maximum climb rate and heading change. ",
                    "Requires smooth coordination of pitch, bank, and power throughout."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS: 180° heading change ±10°, airspeed at/near stall at 180° point", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• First 90°: constant bank, increasing pitch | Last 90°: decreasing bank, constant pitch", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

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

        # ---- Map Interaction Buttons (grouped) ----
        html.Div([
            html.Button("Set Entry Point", id={"type": "click-button", "m_id": "chandelle", "role": "start"},
                       className="green-button", style={"width": "100%", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw Chandelle", id="chandelle-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(id={"type": "click-status", "m_id": "chandelle"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

        # Time slider for scrubbing through hover points
        html.Div(id="chandelle-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="chandelle-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="chandelle-hover-store", data=[]),
        dcc.Store(id="chandelle-path-store", data=[]),

        # Info display area
        html.Div(id="chandelle-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]
