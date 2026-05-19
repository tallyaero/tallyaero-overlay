"""Steep Turn parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def steep_turn_layout(default_elev=None):
    return [
        _field("Bank °", dcc.Dropdown(
            id="steepturn-bank-angle",
            options=[
                {"label": "30°", "value": 30},
                {"label": "35°", "value": 35},
                {"label": "40°", "value": 40},
                {"label": "45° Pvt", "value": 45},
                {"label": "50° Comm", "value": 50},
                {"label": "55°", "value": 55},
                {"label": "60°", "value": 60},
            ],
            value=45, clearable=False,
        ), tooltip="Target bank angle. 45° is the Private ACS standard, 50° Commercial. "
                  "Roll rate from the POH determines how fast you reach it "
                  "(~45°/s for trainers, ~120°/s for aerobatic singles)."),
        _field("Sequence", dcc.Dropdown(
            id="steepturn-sequence",
            options=[
                {"label": "L→R", "value": "left-right"},
                {"label": "R→L", "value": "right-left"},
                {"label": "L only", "value": "left"},
                {"label": "R only", "value": "right"},
            ],
            value="left-right", clearable=False,
        ), tooltip="Direction order. L→R does a 360° left then a 360° right back-to-back."),
        _field("Entry Hdg", dcc.Input(
            id="steepturn-entry-heading", type="number", value=0,
        ), tooltip="Entry heading (degrees true)."),
        _field("Alt (ft)", dcc.Input(
            id="steepturn-altitude", type="number", placeholder="opt",
        ), tooltip="Entry altitude. Defaults to the aircraft's default if blank."),
        _field("IAS", dcc.Input(
            id="steepturn-ias", type="number", placeholder="Va",
        ), tooltip="Indicated airspeed. Default is Va (maneuvering speed) from the POH."),

        html.Div(id={"type": "click-status", "m_id": "steep_turn"}, style={"display": "none"}),
        html.Div(id="steepturn-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="steepturn-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="steepturn-hover-store", data=[]),
        dcc.Store(id="steepturn-path-store", data=[]),
    ]


def steep_turn_actions():
    return [
        html.Button("Set Entry",
                    id={"type": "click-button", "m_id": "steep_turn", "role": "start"},
                    className="shelf-action shelf-action-set",
                    title="Click the map to mark the entry point."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "steep_turn"},
                    className="shelf-action shelf-action-draw",
                    title="Simulate the steep turn(s)."),
        *_results_modal_pair("steep_turn", "steepturn-info",
                             title="Steep Turn — Simulation Results"),
    ]
