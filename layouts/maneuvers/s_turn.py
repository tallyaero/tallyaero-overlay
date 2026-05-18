"""S-Turns parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def s_turn_layout(default_elev=None):
    return [
        _field("Alt (ft)", dcc.Input(
            id="sturn-altitude", type="number", value=800, min=400, max=1500,
        ), tooltip="Altitude AGL for the S-turns. 600-1000 ft is typical ground-reference training."),
        _field("IAS", dcc.Input(
            id="sturn-ias", type="number", value=100,
        ), tooltip="Indicated airspeed."),
        _field("Bank °", dcc.Input(
            id="sturn-bank-angle", type="number", value=35, min=20, max=45,
        ), tooltip="Peak bank in each semicircle. The sim modulates bank around this to keep equal radii."),
        _field("Turns", dcc.Input(
            id="sturn-num-turns", type="number", value=2, min=1, max=5, step=1,
        ), tooltip="Number of semicircles (one full S = 2 turns)."),
        _field("Entry Side", dcc.RadioItems(
            id="sturn-entry-side",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        ), tooltip="Which side of the reference line you start on."),
        _field("First Turn", dcc.RadioItems(
            id="sturn-first-turn",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="right", inline=True, className="shelf-field-radio",
        ), tooltip="Direction of the first semicircle."),

        html.Div(className="shelf-spacer"),

        html.Button("1. Start",
                    id={"type": "click-button", "m_id": "s_turn", "role": "ref"},
                    className="shelf-action shelf-action-set",
                    title="Click the first point on the reference line (typically a road or section line)."),
        html.Button("2. Ref Pt",
                    id={"type": "click-button", "m_id": "s_turn", "role": "bearing"},
                    className="shelf-action shelf-action-set",
                    title="Click a second point that defines the reference line's bearing. The reference line should be near-perpendicular to wind."),
        html.Button("Draw", id="sturn-draw-btn",
                    className="shelf-action shelf-action-draw",
                    title="Simulate the S-turns. The reference line should be near-perpendicular to wind."),

        dcc.Store(id="sturn-line-bearing", data=90),
        html.Div(id={"type": "click-status", "m_id": "s_turn"}, style={"display": "none"}),
        html.Div(id="sturn-info", style={"display": "none"}),
        html.Div(id="sturn-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="sturn-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="sturn-hover-store", data=[]),
        dcc.Store(id="sturn-path-store", data=[]),
    ]
