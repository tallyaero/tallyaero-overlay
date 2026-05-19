"""Lazy Eight parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def lazy8_layout(default_elev=None):
    return [
        _field("Entry Hdg", dcc.Input(
            id="lazy8-entry-heading", type="number", value=0,
        ), tooltip="Entry heading (degrees true)."),
        _field("Alt (ft)", dcc.Input(
            id="lazy8-entry-altitude", type="number", value=3000,
        ), tooltip="Entry altitude AGL."),
        _field("IAS", dcc.Input(
            id="lazy8-ias", type="number", placeholder="Va",
        ), tooltip="Entry IAS. Default Va (maneuvering speed) from the POH."),
        _field("Max Bank °", dcc.Input(
            id="lazy8-bank-angle", type="number", value=30, min=20, max=40,
        ), tooltip="Peak bank at the 90° and 270° points of each half-eight."),
        _field("First Turn", dcc.RadioItems(
            id="lazy8-direction-sequence",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        ), tooltip="Which way the first half-eight rolls."),

        html.Div(id={"type": "click-status", "m_id": "lazy8"}, style={"display": "none"}),
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


def lazy8_actions():
    return [
        html.Button("Set Entry",
                    id={"type": "click-button", "m_id": "lazy8", "role": "start"},
                    className="shelf-action shelf-action-set",
                    title="Click the map to mark the entry point."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "lazy8"},
                    className="shelf-action shelf-action-draw",
                    title="Simulate the figure-8 with oscillating altitude."),
        *_results_modal_pair("lazy8", "lazy8-info",
                             title="Lazy 8 — Simulation Results"),
    ]
