"""Chandelle parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def chandelle_layout(default_elev=None):
    return [
        _field("Entry Hdg", dcc.Input(
            id="chandelle-entry-heading", type="number", value=0,
        )),
        _field("Bank °", dcc.Input(
            id="chandelle-bank-angle", type="number", value=30, min=15, max=45,
        )),
        _field("Direction", dcc.RadioItems(
            id="chandelle-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="right", inline=True, className="shelf-field-radio",
        )),
        _field("Alt (ft)", dcc.Input(
            id="chandelle-altitude", type="number", value=3000,
        )),
        _field("IAS", dcc.Input(
            id="chandelle-ias", type="number", placeholder="Va",
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Set Entry",
                    id={"type": "click-button", "m_id": "chandelle", "role": "start"},
                    className="shelf-action shelf-action-set"),
        html.Button("Draw", id="chandelle-draw-btn",
                    className="shelf-action shelf-action-draw"),

        html.Div(id={"type": "click-status", "m_id": "chandelle"}, style={"display": "none"}),
        html.Div(id="chandelle-info", style={"display": "none"}),
        html.Div(id="chandelle-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="chandelle-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="chandelle-hover-store", data=[]),
        dcc.Store(id="chandelle-path-store", data=[]),
    ]
