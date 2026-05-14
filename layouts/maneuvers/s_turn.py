"""S-Turns Across a Road parameter form.

Ground reference maneuver practicing wind correction while crossing a
linear reference. Bank angle varies to maintain equal semicircles on
each side of the line.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/s_turn.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def s_turn_layout():
    """S-Turns across a reference line - ground reference maneuver."""
    # Temporary coupling — `_reset_buttons_row` still lives in app.py until
    # Phase 1h moves shared layout helpers out. Imported lazily here to
    # avoid a circular import at module load time (app.py imports this
    # function at top level).
    from app import _reset_buttons_row

    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Ground reference maneuver practicing wind correction while crossing a linear reference. ",
                    "Bank angle varies to maintain equal semicircles on each side of the line."
                ], style={"fontSize": "11px", "color": "#666", "margin": "0"}),
                html.Div("• ACS: constant altitude ±100 ft, equal semicircles, wings level over line", style={"fontSize": "11px", "color": "#555", "marginTop": "4px"}),
                html.Div("• Entry perpendicular on downwind | Steepest bank with tailwind, shallowest with headwind", style={"fontSize": "11px", "color": "#555"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

        # Reference Line Selection (interactive two-click)
        html.Label("Reference Line", className="input-label"),
        html.Div([
            html.Div([
                html.Button(
                    "1. Maneuver Start",
                    id={"type": "click-button", "m_id": "s_turn", "role": "ref"},
                    className="green-button",
                    style={"flex": "1"}
                ),
                html.Button(
                    "2. Point Along Reference",
                    id={"type": "click-button", "m_id": "s_turn", "role": "bearing"},
                    className="green-button",
                    style={"flex": "1"}
                ),
            ], style={"display": "flex", "gap": "6px", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw S-Turns", id="sturn-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),

        html.Div(id={"type": "click-status", "m_id": "s_turn"},
                 style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

        # Hidden bearing store (auto-calculated from clicks)
        dcc.Store(id="sturn-line-bearing", data=90),

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
