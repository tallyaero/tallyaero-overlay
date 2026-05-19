"""Eights on Pylons parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def pylons_layout(default_elev=None):
    return [
        _field("IAS", dcc.Input(
            id="pylons-ias", type="number", value=100, min=60, max=150,
        ), tooltip="Indicated airspeed. Pivotal altitude grows with ground speed (PA = GS² / 11.3)."),
        _field("Bank °", dcc.Dropdown(
            id="pylons-bank-angle",
            options=[
                {"label": "20°", "value": 20},
                {"label": "25°", "value": 25},
                {"label": "30°", "value": 30},
                {"label": "35°", "value": 35},
                {"label": "40°", "value": 40},
            ],
            value=30, clearable=False,
        ), tooltip="Reference bank — actual bank modulates with position to hold pivotal altitude."),
        _field("Eights", dcc.Dropdown(
            id="pylons-num-eights",
            options=[{"label": "1", "value": 1}, {"label": "2", "value": 2}, {"label": "3", "value": 3}],
            value=1, clearable=False,
        ), tooltip="Number of figure-8s."),
        _field("Entry", dcc.Dropdown(
            id="pylons-entry-direction",
            options=[
                {"label": "Downwind", "value": "downwind"},
                {"label": "Upwind", "value": "upwind"},
            ],
            value="downwind", clearable=False,
        ), tooltip="Whether you enter on a downwind or upwind leg."),

        html.Div(className="shelf-spacer"),

        html.Button("Set Pylon 1",
                    id={"type": "click-button", "m_id": "pylons", "role": "pylon_a"},
                    className="shelf-action shelf-action-set",
                    title="Click the first pylon (a visual reference point on the ground)."),
        html.Button("Set Pylon 2",
                    id={"type": "click-button", "m_id": "pylons", "role": "pylon_b"},
                    className="shelf-action shelf-action-set",
                    title="Click the second pylon. Both should be at the same elevation."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "pylons"},
                    className="shelf-action shelf-action-draw",
                    title="Simulate the figure-8 with pivotal-altitude visualization."),
        *_results_modal_pair("pylons", "pylons-info",
                             title="Eights on Pylons — Simulation Results"),

        html.Div(id={"type": "click-status", "m_id": "pylons"}, style={"display": "none"}),
        html.Div(id="pylons-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="pylons-time-slider",
                                min=0, max=100, step=1, value=0, marks={},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="pylons-hover-store", data=[]),
        dcc.Store(id="pylons-path-store", data=[]),
    ]
