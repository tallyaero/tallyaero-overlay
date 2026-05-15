"""Impossible Turn parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def impossible_turn_layout(default_elev=None):
    return [
        _field("Direction", dcc.RadioItems(
            id="impossibleturn-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        )),
        _field("Runway", dcc.Dropdown(
            id="impossibleturn-runway-select",
            placeholder="—", clearable=True, searchable=False,
        )),
        _field("Heading", dcc.Input(
            id="impossibleturn-manual-heading",
            type="number", value=360, min=1, max=360, step=1,
        )),
        _field("Alt (ft)", dcc.Input(
            id="impossibleturn-altitude",
            type="number", value=1000, min=0, step=10,
        )),
        _field("Vy (kt)", dcc.Input(
            id="impossibleturn-climb-speed",
            type="number", value=75, min=40, max=200, step=1,
            persistence=True, persistence_type="local",
        )),
        _field("Reaction (s)", dcc.Input(
            id="impossibleturn-reaction-sec",
            type="number", value=3.0, min=0.0, step=0.5,
        )),
        _field("Flap", dcc.Dropdown(
            id="impossibleturn-flap-config",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean", clearable=False, searchable=False,
        )),
        _field("Prop", dcc.Dropdown(
            id="impossibleturn-prop-config",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"},
            ],
            value="windmilling", clearable=False, searchable=False,
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Set Takeoff",
                    id={"type": "click-button", "m_id": "impossible_turn", "role": "start"},
                    className="shelf-action shelf-action-set"),
        html.Button("Draw", id="impossibleturn-draw-btn",
                    className="shelf-action shelf-action-draw"),

        # Hidden helper containers (existing callbacks reference these)
        html.Div(id="impossibleturn-runway-info", style={"display": "none"}),
        html.Div(id="impossibleturn-manual-heading-div", style={"display": "none"}),
        html.Div(id="impossibleturn-climb-tooltip", style={"display": "none"}),
        html.Div(id={"type": "click-status", "m_id": "impossible_turn"}, style={"display": "none"}),
        html.Div(id="impossibleturn-result", style={"display": "none"}),
        html.Div(id="impossibleturn-info", style={"display": "none"}),
        html.Div(id="impossibleturn-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="impossibleturn-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="impossibleturn-hover-store", data=[]),
        dcc.Store(id="impossibleturn-path-store", data=[]),
    ]
