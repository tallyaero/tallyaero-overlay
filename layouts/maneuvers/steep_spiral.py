"""Steep Spiral parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def steep_spiral_layout(default_elev=None):
    return [
        _field("Turns", dcc.Input(
            id="steepspiral-turns", type="number", value=3, min=3, max=10, step=1,
        ), tooltip="Number of 360° revolutions. ACS Commercial minimum is 3."),
        _field("Alt (ft)", dcc.Input(
            id="steepspiral-altitude", type="number", value=5000,
        ), tooltip="Entry altitude AGL. Must complete no lower than 1500 ft AGL."),
        _field("Bank °", dcc.Input(
            id="steepspiral-bank-angle", type="number", value=45, min=20, max=60,
        ), tooltip="Reference bank — actual bank modulates with wind to hold the ground-track radius. Peak typically downwind."),
        _field("Entry", dcc.Dropdown(
            id="steepspiral-clock-position",
            options=[
                {"label": "12 o'clock (N)", "value": "12"},
                {"label": "3 o'clock (E)",  "value": "3"},
                {"label": "6 o'clock (S)",  "value": "6"},
                {"label": "9 o'clock (W)",  "value": "9"},
            ],
            value="12", clearable=False,
        ), tooltip="Clock position on the orbit at which you enter (12 = north, 3 = east, etc.)."),
        _field("Direction", dcc.RadioItems(
            id="steepspiral-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        ), tooltip="Spiral direction."),

        html.Div(id={"type": "click-status", "m_id": "steep_spiral"}, style={"display": "none"}),
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


def steep_spiral_actions():
    return [
        html.Button("Set Ref",
                    id={"type": "click-button", "m_id": "steep_spiral", "role": "ref"},
                    className="shelf-action shelf-action-set",
                    title="Click the ground reference point for the spiral center."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "steep_spiral"},
                    className="shelf-action shelf-action-draw",
                    title="Run the descending spiral."),
        *_results_modal_pair("steep_spiral", "steepspiral-warnings",
                             title="Steep Spiral — Simulation Results"),
    ]
