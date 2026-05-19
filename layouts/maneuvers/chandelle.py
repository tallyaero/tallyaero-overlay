"""Chandelle parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def chandelle_layout(default_elev=None):
    return [
        _field("Entry Hdg", dcc.Input(
            id="chandelle-entry-heading", type="number", value=0,
        ), tooltip="Entry heading (degrees true)."),
        _field("Bank °", dcc.Input(
            id="chandelle-bank-angle", type="number", value=30, min=15, max=45,
        ), tooltip="Bank used in the first 90°. 30° is the typical target; 45° is more aggressive."),
        _field("Direction", dcc.RadioItems(
            id="chandelle-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="right", inline=True, className="shelf-field-radio",
        ), tooltip="Which way the climbing turn rolls in."),
        _field("Alt (ft)", dcc.Input(
            id="chandelle-altitude", type="number", value=3000,
        ), tooltip="Entry altitude AGL."),
        _field("IAS", dcc.Input(
            id="chandelle-ias", type="number", placeholder="Va",
        ), tooltip="Entry IAS. Default Va (maneuvering speed) from the POH."),

        html.Div(className="shelf-spacer"),

        html.Button("Set Entry",
                    id={"type": "click-button", "m_id": "chandelle", "role": "start"},
                    className="shelf-action shelf-action-set",
                    title="Click the map to mark the entry point."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "chandelle"},
                    className="shelf-action shelf-action-draw",
                    title="Simulate the climbing 180° turn."),
        *_results_modal_pair("chandelle", "chandelle-info",
                             title="Chandelle — Simulation Results"),

        html.Div(id={"type": "click-status", "m_id": "chandelle"}, style={"display": "none"}),
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
