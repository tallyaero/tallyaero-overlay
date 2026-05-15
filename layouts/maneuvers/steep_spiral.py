"""Steep Spiral parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def steep_spiral_layout(default_elev=None):
    return [
        _field("Turns", dcc.Input(
            id="steepspiral-turns", type="number", value=3, min=3, max=10, step=1,
        )),
        _field("Alt (ft)", dcc.Input(
            id="steepspiral-altitude", type="number", value=5000,
        )),
        _field("Bank °", dcc.Input(
            id="steepspiral-bank-angle", type="number", value=45, min=20, max=60,
        )),
        _field("Entry", dcc.Dropdown(
            id="steepspiral-clock-position",
            options=[
                {"label": "12 o'clock (N)", "value": "12"},
                {"label": "3 o'clock (E)",  "value": "3"},
                {"label": "6 o'clock (S)",  "value": "6"},
                {"label": "9 o'clock (W)",  "value": "9"},
            ],
            value="12", clearable=False,
        )),
        _field("Direction", dcc.RadioItems(
            id="steepspiral-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Set Ref",
                    id={"type": "click-button", "m_id": "steep_spiral", "role": "ref"},
                    className="shelf-action shelf-action-set"),
        html.Button("Draw", id="steepspiral-draw-btn",
                    className="shelf-action shelf-action-draw"),

        html.Div(id={"type": "click-status", "m_id": "steep_spiral"}, style={"display": "none"}),
        html.Div(id="steepspiral-warnings", style={"display": "none"}),
        html.Div(id="steepspiral-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="steepspiral-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="steepspiral-hover-store", data=[]),
        dcc.Store(id="steepspiral-path-store", data=[]),
    ]
