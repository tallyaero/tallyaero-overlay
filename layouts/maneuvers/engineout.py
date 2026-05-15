"""Engine-Out Glide parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def engineout_layout(default_elev=None):
    return [
        _field("Runway", dcc.Dropdown(
            id="engineout-runway-select",
            placeholder="—", clearable=True, searchable=False,
        )),
        _field("TD Hdg", dcc.Input(
            id="engineout-touchdown-heading",
            type="number", value=360, min=1, max=360, step=1,
        )),
        _field("Flap", dcc.Dropdown(
            id="engineout-flap-setting",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean", clearable=False,
        )),
        _field("Prop", dcc.Dropdown(
            id="engineout-prop-condition",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"},
            ],
            value="idle", clearable=False,
        )),
        _field("TD Elev (ft)", dcc.Input(
            id="engineout-manual-elev", type="number", placeholder="from map",
        )),
        _field("Start Hdg", dcc.Input(
            id="engineout-start-heading", type="number", value=240,
        )),
        _field("Start Alt (ft)", dcc.Input(
            id="engineout-altitude", type="number", value=5000,
        )),
        _field("Reaction (s)", dcc.Input(
            id="engineout-reaction-time", type="number",
            value=2.0, min=0, max=10, step=0.5,
        )),
        _field("Max Bank °", dcc.Input(
            id="engineout-max-bank", type="number",
            value=45, min=15, max=60,
        )),
        _field("Envelope", dcc.Checklist(
            id="engineout-show-envelope",
            options=[{"label": " Ring", "value": "show"}],
            value=[],
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Set Touchdown",
                    id={"type": "click-button", "m_id": "engineout", "role": "touchdown"},
                    className="shelf-action shelf-action-set"),
        html.Button("Set Start",
                    id={"type": "click-button", "m_id": "engineout", "role": "start"},
                    className="shelf-action shelf-action-set"),
        html.Button("Draw", id="engineout-draw-btn",
                    className="shelf-action shelf-action-draw"),

        # Hidden helpers
        dcc.Input(id="engineout-speed-tau", type="hidden", value=4.0),
        dcc.Input(id="engineout-bank-tau", type="hidden", value=1.5),
        html.Div(id="engineout-runway-info", style={"display": "none"}),
        html.Div(id="engineout-manual-heading-div", style={"display": "none"}),
        html.Div(id={"type": "click-status", "m_id": "engineout"}, style={"display": "none"}),
        html.Div(id="engineout-min-alt-result", style={"display": "none"}),
        html.Div(id="engineout-info", style={"display": "none"}),
        html.Div(id="engineout-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="engineout-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Start", 100: "End"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="engineout-hover-store", data=[]),
        dcc.Store(id="engineout-path-store", data=[]),
        dcc.Store(id="engineout-envelope-store", data=[]),
    ]
