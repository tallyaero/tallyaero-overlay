"""Engine-Out Glide parameter form — horizontal-native shelf layout."""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def engineout_layout(default_elev=None):
    """Form fields + hidden helpers + stores. Action buttons are
    returned separately by `engineout_actions()` and rendered in
    the floating overlay panel, not in the shelf."""
    return [
        _field("Runway", dcc.Dropdown(
            id="engineout-runway-select",
            placeholder="—", clearable=True, searchable=False,
        ), tooltip="Target runway for the gliding approach."),
        _field("TD Hdg", dcc.Input(
            id="engineout-touchdown-heading",
            type="number", value=360, min=1, max=360, step=1,
        ), tooltip="Touchdown heading. Auto-set from the runway selection."),
        _field("Flap", dcc.Dropdown(
            id="engineout-flap-setting",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean", clearable=False,
        ), tooltip="Flap configuration during the glide."),
        _field("Prop", dcc.Dropdown(
            id="engineout-prop-condition",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"},
            ],
            value="idle", clearable=False,
        ), tooltip="Propeller condition. Windmilling adds drag, feathered minimizes it (twins only)."),
        _field("TD Elev (ft)", dcc.Input(
            id="engineout-manual-elev", type="number", placeholder="from map",
        ), tooltip="Touchdown elevation (ft MSL). Auto-filled from the airport selection if blank."),
        _field("Start Hdg", dcc.Input(
            id="engineout-start-heading", type="number", value=240,
        ), tooltip="Initial heading at the engine-failure point."),
        _field("Start Alt (ft)", dcc.Input(
            id="engineout-altitude", type="number", value=5000,
        ), tooltip="Altitude AGL at engine failure."),
        _field("Reaction (s)", dcc.Input(
            id="engineout-reaction-time", type="number",
            value=2.0, min=0, max=10, step=0.5,
        ), tooltip="Pilot reaction time before establishing best-glide attitude."),
        _field("Max Bank °", dcc.Input(
            id="engineout-max-bank", type="number",
            value=45, min=15, max=60,
        ), tooltip="Maximum bank used in the glide turns. Steeper = tighter radius but more drag/altitude loss."),
        # NOTE: the Glide Ring toggle (id="engineout-show-envelope")
        # used to live here. It's now a permanent component in the
        # map-controls overlay (layouts/desktop.py) so the
        # render_glide_ring callback can reference it as a string-id
        # Input without failing when a non-engineout maneuver is
        # mounted. CSS hides the toggle when maneuver != engineout.

        # Hidden helpers + stores. These have to exist in the DOM
        # while the maneuver is active so the callbacks can read /
        # write them; their visibility is controlled per-element.
        dcc.Input(id="engineout-speed-tau", type="hidden", value=4.0),
        dcc.Input(id="engineout-bank-tau", type="hidden", value=1.5),
        html.Div(id="engineout-runway-info", style={"display": "none"}),
        html.Div(id="engineout-manual-heading-div", style={"display": "none"}),
        html.Div(id={"type": "click-status", "m_id": "engineout"}, style={"display": "none"}),
        html.Div(id="engineout-min-alt-result", style={"display": "none"}),
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


def engineout_actions():
    """Action buttons + Results modal — rendered into the floating
    overlay panel by `render_maneuver_actions`. Buttons keep their
    existing `shelf-action` classNames so the Results-button
    success/failure colors from Phase I7 + the engineout callback's
    className setter continue to work without changes."""
    return [
        html.Button("Set Touchdown",
                    id={"type": "click-button", "m_id": "engineout", "role": "touchdown"},
                    className="shelf-action shelf-action-set",
                    title="Click the touchdown spot on the map."),
        html.Button("Set Start",
                    id={"type": "click-button", "m_id": "engineout", "role": "start"},
                    className="shelf-action shelf-action-set",
                    title="Click the engine-failure spot on the map."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "engineout"},
                    className="shelf-action shelf-action-draw",
                    title="Run the glide simulation."),
        *_results_modal_pair("engineout", "engineout-info",
                             title="Engine-Out Glide — Simulation Results"),
    ]
