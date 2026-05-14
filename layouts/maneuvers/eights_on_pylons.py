"""Eights on Pylons parameter form.

Commercial pilot maneuver with integrated pivotal altitude calculator.
Altitude is automatically calculated based on groundspeed using
PA = GS² / 11.3.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/eights_on_pylons.py (Phase 1c).

Note: filename follows the simulation/ module naming convention
(eights_on_pylons.py); the exported function name stays
`pylons_layout` so callers in app.py don't need to change.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def pylons_layout():
    """Eights on Pylons - commercial pilot maneuver with integrated pivotal altitude calculator."""
    # Temporary coupling — `_reset_buttons_row` still lives in app.py until
    # Phase 1h moves shared layout helpers out. Imported lazily here to
    # avoid a circular import at module load time (app.py imports this
    # function at top level).
    from app import _reset_buttons_row

    return [
        dbc.Accordion([
            dbc.AccordionItem([
                html.P("Altitude is automatically calculated based on groundspeed using PA = GS²/11.3",
                       style={"fontSize": "11px", "color": "#666", "margin": "0"}),
            ], title="Description", item_id="desc"),
        ], active_item="desc", className="sidebar-accordion", style={"marginBottom": "10px"}),

        html.Label("Indicated Airspeed (KIAS)", className="input-label"),
        dcc.Input(id="pylons-ias", type="number", value=100, min=60, max=150, className="input-small"),

        html.Label("Bank Angle (°)", className="input-label"),
        dcc.Dropdown(
            id="pylons-bank-angle",
            className="dropdown",
            options=[
                {"label": "20°", "value": 20},
                {"label": "25°", "value": 25},
                {"label": "30° (typical)", "value": 30},
                {"label": "35°", "value": 35},
                {"label": "40° (ACS max)", "value": 40},
            ],
            value=30,
            clearable=False,
            style={"width": "120px"}
        ),

        html.Label("Number of Figure-8s", className="input-label"),
        dcc.Dropdown(
            id="pylons-num-eights",
            className="dropdown",
            options=[
                {"label": "1", "value": 1},
                {"label": "2", "value": 2},
                {"label": "3", "value": 3},
            ],
            value=1,
            clearable=False,
            style={"width": "80px"}
        ),

        html.Label("Entry Direction", className="input-label"),
        dcc.Dropdown(
            id="pylons-entry-direction",
            className="dropdown",
            options=[
                {"label": "Downwind (recommended)", "value": "downwind"},
                {"label": "Upwind", "value": "upwind"},
            ],
            value="downwind",
            clearable=False,
        ),

        html.Div("Click to set pylon locations (0.5-1.0 NM apart):", style={
            "fontWeight": "bold",
            "marginTop": "12px",
            "marginBottom": "8px"
        }),

        html.Div([
            html.Div([
                html.Button("Set Pylon 1", id={"type": "click-button", "m_id": "pylons", "role": "pylon_a"},
                           className="green-button", style={"flex": "1"}),
                html.Button("Set Pylon 2", id={"type": "click-button", "m_id": "pylons", "role": "pylon_b"},
                           className="green-button", style={"flex": "1"}),
            ], style={"display": "flex", "gap": "6px", "marginBottom": "8px"}),
            _reset_buttons_row(),
            html.Button("Draw Eights on Pylons", id="pylons-draw-btn", className="blue-button", style={"width": "100%", "marginTop": "8px"}),
        ]),
        html.Div(id={"type": "click-status", "m_id": "pylons"}, style={"marginTop": "10px", "fontStyle": "italic", "color": "#555"}),

        # Time scrubber (hidden until path is drawn)
        html.Div(id="pylons-slider-container", style={"display": "none"}, children=[
            html.Label("Time Scrubber", className="input-label"),
            dcc.Slider(
                id="pylons-time-slider",
                min=0,
                max=100,
                step=1,
                value=0,
                marks={},
                tooltip={"placement": "bottom", "always_visible": False}
            ),
        ]),
        dcc.Store(id="pylons-hover-store", data=[]),
        dcc.Store(id="pylons-path-store", data=[]),

        # Info panel
        html.Div(id="pylons-info", style={"marginTop": "10px", "padding": "10px", "borderRadius": "5px"})
    ]
