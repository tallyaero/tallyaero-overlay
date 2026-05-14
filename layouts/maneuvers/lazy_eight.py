"""Lazy Eight parameter form.

Symmetrical climbing/descending S-turns across a reference line. Pilot
picks entry heading, altitude, speed, max bank, and first turn direction.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/lazy_eight.py (Phase 1c).

Filename uses `lazy_eight` to match simulation/ naming; the public
function name remains `lazy8_layout` since the Dash component IDs all
use the `lazy8-` prefix.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

from layouts.desktop import _reset_buttons_row


def lazy8_layout():
    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Symmetrical climbing and descending S-turns across a reference line. ",
                    "Combines varying pitch, bank, and airspeed in a continuous, flowing maneuver."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS: 45° points at max pitch (15° up), 90° points at max bank (30°) and level pitch", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• 180° points: wings level, min airspeed, max altitude | Entry altitude ±100 ft", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

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

        # ---- Map Interaction Buttons (grouped) ----
        html.Div([
            html.Button("Set Entry Point", id={"type": "click-button", "m_id": "lazy8", "role": "start"},
                       className="green-button", style={"width": "100%", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw Lazy Eight", id="lazy8-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(id={"type": "click-status", "m_id": "lazy8"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

        # Time slider for scrubbing through hover points
        html.Div(id="lazy8-slider-container", children=[
            html.Label("Time Scrubber", className="input-label", style={"marginTop": "15px"}),
            dcc.Slider(
                id="lazy8-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={0: "Start", 100: "End"},
                tooltip={"placement": "bottom", "always_visible": False},
            ),
        ], style={"display": "none"}),

        # Stores for hover data and path
        dcc.Store(id="lazy8-hover-store", data=[]),
        dcc.Store(id="lazy8-path-store", data=[]),

        # Info display area
        html.Div(id="lazy8-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]
