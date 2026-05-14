"""Steep Spiral parameter form.

Emergency descent maneuver using steep turns around a ground reference
point. Pilot picks number of turns, entry altitude, bank angle, entry
clock position, and turn direction.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/steep_spiral.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

from layouts.desktop import _reset_buttons_row


def steep_spiral_layout():
    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Emergency descent maneuver using steep turns around a ground reference point. ",
                    "Useful for rapid altitude loss while remaining over a single location."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS: 3+ turns, 50-60° bank, constant radius, airspeed ±10 kt", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• Maintain situational awareness - complete above 1,500 ft AGL minimum", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

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

        # ---- Map Interaction Buttons (grouped) ----
        html.Div([
            html.Button("Set Reference Point", id={"type": "click-button", "m_id": "steep_spiral", "role": "ref"},
                       className="green-button", style={"width": "100%", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw Steep Spiral", id="steepspiral-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(id={"type": "click-status", "m_id": "steep_spiral"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

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
