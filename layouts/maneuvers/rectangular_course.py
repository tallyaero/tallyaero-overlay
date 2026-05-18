"""Rectangular Course parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def rect_course_layout(default_elev=None):
    return [
        _field("Alt (ft)", dcc.Input(
            id="rectcourse-altitude", type="number", value=800, min=400, max=1500,
        ), tooltip="Altitude AGL for the rectangle (600-1000 ft is typical ground-reference training)."),
        _field("IAS", dcc.Input(
            id="rectcourse-ias", type="number", value=95,
        ), tooltip="Indicated airspeed. Leave at default cruise IAS unless practicing slow flight."),
        _field("Leg spacing (NM)", dcc.Input(
            id="rectcourse-width", type="number",
            value=0.75, min=0.1, max=1.5, step=0.05,
        ), tooltip="Distance between the upwind and downwind legs (the rectangle's short side). NOT the turn radius — that auto-scales with IAS and bank."),
        _field("Direction", dcc.RadioItems(
            id="rectcourse-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        ), tooltip="Pattern direction — L = standard left rectangle."),
        _field("Circuits", dcc.Input(
            id="rectcourse-circuits", type="number",
            value=1, min=1, max=3, step=1,
        ), tooltip="Number of full rectangle loops."),

        html.Div(className="shelf-spacer"),

        html.Button("1. DW Start",
                    id={"type": "click-button", "m_id": "rect_course", "role": "dw_start"},
                    className="shelf-action shelf-action-set",
                    title="Click the first point on the downwind leg (the long leg parallel to wind)."),
        html.Button("2. DW End",
                    id={"type": "click-button", "m_id": "rect_course", "role": "dw_end"},
                    className="shelf-action shelf-action-set",
                    title="Click the second point on the downwind leg to define its length + bearing."),
        html.Button("Draw", id="rectcourse-draw-btn",
                    className="shelf-action shelf-action-draw",
                    title="Simulate the wind-corrected rectangle around the field."),

        html.Div(id="rectcourse-edge-visible-info", style={"display": "none"}),
        html.Div(id={"type": "click-status", "m_id": "rect_course"}, style={"display": "none"}),
        html.Div(id="rectcourse-info", style={"display": "none"}),
        html.Div(id="rectcourse-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="rectcourse-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="rectcourse-hover-store", data=[]),
        dcc.Store(id="rectcourse-path-store", data=[]),
        dcc.Store(id="rectcourse-warnings-store", data={}),
    ]
