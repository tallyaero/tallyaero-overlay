"""S-Turns parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def s_turn_layout(default_elev=None):
    return [
        _field("Alt (ft)", dcc.Input(
            id="sturn-altitude", type="number", value=800, min=400, max=1500,
        )),
        _field("IAS", dcc.Input(
            id="sturn-ias", type="number", value=100,
        )),
        _field("Bank °", dcc.Input(
            id="sturn-bank-angle", type="number", value=35, min=20, max=45,
        )),
        _field("Turns", dcc.Input(
            id="sturn-num-turns", type="number", value=2, min=1, max=5, step=1,
        )),
        _field("Entry Side", dcc.RadioItems(
            id="sturn-entry-side",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        )),
        _field("First Turn", dcc.RadioItems(
            id="sturn-first-turn",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="right", inline=True, className="shelf-field-radio",
        )),

        html.Div(className="shelf-spacer"),

        html.Button("1. Start",
                    id={"type": "click-button", "m_id": "s_turn", "role": "ref"},
                    className="shelf-action shelf-action-set"),
        html.Button("2. Ref Pt",
                    id={"type": "click-button", "m_id": "s_turn", "role": "bearing"},
                    className="shelf-action shelf-action-set"),
        html.Button("Draw", id="sturn-draw-btn",
                    className="shelf-action shelf-action-draw"),

        dcc.Store(id="sturn-line-bearing", data=90),
        html.Div(id={"type": "click-status", "m_id": "s_turn"}, style={"display": "none"}),
        html.Div(id="sturn-info", style={"display": "none"}),
        html.Div(id="sturn-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="sturn-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="sturn-hover-store", data=[]),
        dcc.Store(id="sturn-path-store", data=[]),
    ]
