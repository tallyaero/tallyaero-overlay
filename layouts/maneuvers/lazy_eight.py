"""Lazy Eight parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def lazy8_layout(default_elev=None):
    return [
        _field("Entry Hdg", dcc.Input(
            id="lazy8-entry-heading", type="number", value=0,
        )),
        _field("Alt (ft)", dcc.Input(
            id="lazy8-entry-altitude", type="number", value=3000,
        )),
        _field("IAS", dcc.Input(
            id="lazy8-ias", type="number", placeholder="Va",
        )),
        _field("Max Bank °", dcc.Input(
            id="lazy8-bank-angle", type="number", value=30, min=20, max=40,
        )),
        _field("First Turn", dcc.RadioItems(
            id="lazy8-direction-sequence",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Set Entry",
                    id={"type": "click-button", "m_id": "lazy8", "role": "start"},
                    className="shelf-action shelf-action-set"),
        html.Button("Draw", id="lazy8-draw-btn",
                    className="shelf-action shelf-action-draw"),

        html.Div(id={"type": "click-status", "m_id": "lazy8"}, style={"display": "none"}),
        html.Div(id="lazy8-info", style={"display": "none"}),
        html.Div(id="lazy8-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="lazy8-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="lazy8-hover-store", data=[]),
        dcc.Store(id="lazy8-path-store", data=[]),
    ]
