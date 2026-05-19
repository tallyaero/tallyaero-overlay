"""Turns Around a Point parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def turns_point_layout(default_elev=None):
    return [
        _field("Alt (ft)", dcc.Input(
            id="turnspoint-altitude", type="number", value=800, min=400, max=1500,
        ), tooltip="Altitude AGL for the orbit. 600-1000 ft is typical."),
        _field("IAS", dcc.Input(
            id="turnspoint-ias", type="number", value=100,
        ), tooltip="Indicated airspeed during the orbit."),
        _field("Radius (NM)", dcc.Input(
            id="turnspoint-radius", type="number",
            value=0.25, min=0.1, max=1.0, step=0.05,
        ), tooltip="Target orbit radius. Sim will modulate bank to hold this radius despite wind."),
        _field("Turns", dcc.Input(
            id="turnspoint-num-turns", type="number",
            value=2, min=1, max=5, step=1,
        ), tooltip="Number of full 360° orbits."),
        _field("Direction", dcc.RadioItems(
            id="turnspoint-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        ), tooltip="Orbit direction."),
        _field("Entry Hdg", dcc.Input(
            id="turnspoint-entry-heading", type="number",
            placeholder="auto = downwind",
        ), tooltip="Entry heading. Leave blank for auto downwind entry (ACS preferred). "
                  "Override only if the prevailing wind isn't representative."),

        html.Div(className="shelf-spacer"),

        html.Button("Set Center",
                    id={"type": "click-button", "m_id": "turns_point", "role": "center"},
                    className="shelf-action shelf-action-set",
                    title="Click the ground reference point to orbit."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "turns_point"},
                    className="shelf-action shelf-action-draw",
                    title="Simulate the constant-radius orbit."),
        *_results_modal_pair("turns_point", "turnspoint-info",
                             title="Turns Around a Point — Simulation Results"),

        html.Div(id={"type": "click-status", "m_id": "turns_point"}, style={"display": "none"}),
        html.Div(id="turnspoint-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="turnspoint-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="turnspoint-hover-store", data=[]),
        dcc.Store(id="turnspoint-path-store", data=[]),
        dcc.Store(id="turnspoint-warnings-store", data={}),
    ]
