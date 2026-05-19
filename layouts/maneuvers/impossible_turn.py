"""Impossible Turn parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def impossible_turn_layout(default_elev=None):
    return [
        _field("Direction", dcc.RadioItems(
            id="impossibleturn-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        ), tooltip="Which way you turn back. Choose the side toward the off-runway open area."),
        _field("Runway", dcc.Dropdown(
            id="impossibleturn-runway-select",
            placeholder="—", clearable=True, searchable=False,
        ), tooltip="Departing runway. Picks heading automatically."),
        _field("Heading", dcc.Input(
            id="impossibleturn-manual-heading",
            type="number", value=360, min=1, max=360, step=1,
        ), tooltip="Manual runway heading override if not in the dropdown."),
        _field("Alt (ft)", dcc.Input(
            id="impossibleturn-altitude",
            type="number", value=1000, min=0, step=10,
        ), tooltip="Altitude AGL at engine failure. Lower = less margin to make it back."),
        _field("Vy (kt)", dcc.Input(
            id="impossibleturn-climb-speed",
            type="number", value=75, min=40, max=200, step=1,
            persistence=True, persistence_type="local",
        ), tooltip="Best-rate-of-climb speed (KIAS). From the POH."),
        _field("Reaction (s)", dcc.Input(
            id="impossibleturn-reaction-sec",
            type="number", value=3.0, min=0.0, step=0.5,
        ), tooltip="Pilot reaction time before initiating the turn-back. 2-4 s realistic."),
        _field("Flap", dcc.Dropdown(
            id="impossibleturn-flap-config",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean", clearable=False, searchable=False,
        ), tooltip="Flap configuration at the moment of failure."),
        _field("Prop", dcc.Dropdown(
            id="impossibleturn-prop-config",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"},
            ],
            value="windmilling", clearable=False, searchable=False,
        ), tooltip="Propeller condition after the failure. Windmilling is most common."),

        html.Div(className="shelf-spacer"),

        html.Button("Set Takeoff",
                    id={"type": "click-button", "m_id": "impossible_turn", "role": "start"},
                    className="shelf-action shelf-action-set",
                    title="Click on the runway threshold to mark the departure point."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "impossible_turn"},
                    className="shelf-action shelf-action-draw",
                    title="Run the impossible-turn simulation."),
        *_results_modal_pair("impossible_turn", "impossibleturn-info",
                             title="Impossible Turn — Simulation Results"),

        # Hidden helper containers (existing callbacks reference these)
        html.Div(id="impossibleturn-runway-info", style={"display": "none"}),
        html.Div(id="impossibleturn-manual-heading-div", style={"display": "none"}),
        html.Div(id="impossibleturn-climb-tooltip", style={"display": "none"}),
        html.Div(id={"type": "click-status", "m_id": "impossible_turn"}, style={"display": "none"}),
        html.Div(id="impossibleturn-result", className="shelf-info-panel"),
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
