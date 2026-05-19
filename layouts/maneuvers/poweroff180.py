"""Power-Off 180 parameter form — horizontal-native shelf layout.

Renders as a single flex row of compact `.shelf-field` columns plus
the Set Touchdown / Draw action buttons on the right. Description
text now lives in the Info modal triggered from the top strip; the
old vertical sidebar form has been retired.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/poweroff180.py.
"""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def poweroff180_layout(default_elev=None):
    return [
        _field("Runway", dcc.Dropdown(
            id="poweroff180-runway-select",
            placeholder="—",
            clearable=True, searchable=False,
        ), tooltip="Target runway for the touchdown. Picks heading automatically."),
        _field("Heading", dcc.Input(
            id="poweroff180-manual-heading",
            type="number", value=360, min=1, max=360, step=1,
        ), tooltip="Manual runway heading override if not in the dropdown."),
        _field("Pattern", html.Div([
            dcc.RadioItems(
                id="poweroff180-pattern",
                options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
                value="left", inline=True, className="shelf-field-radio",
            ),
        ]), tooltip="Traffic pattern direction. L = standard left pattern."),
        _field("Flap", dcc.Dropdown(
            id="poweroff180-flap-setting",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean", clearable=False,
        ), tooltip="Flap configuration during the glide back."),
        _field("Prop", dcc.Dropdown(
            id="poweroff180-prop-condition",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"},
            ],
            value="idle", clearable=False,
        ), tooltip="Propeller condition during the glide. Idle = stock Power-Off 180."),
        _field("Abeam (NM)", dcc.Input(
            id="poweroff180-abeam-distance-nm",
            type="number", value=0.5, min=0.3, max=1.5, step=0.05,
        ), tooltip="Lateral distance to the runway when abeam the touchdown point (0.3-1.5 NM). 0.5 NM is typical pattern width."),
        _field("Resid pwr %", dcc.Input(
            id="poweroff180-residual-power",
            type="number", value=0, min=0, max=30, step=5,
        ), tooltip="Residual partial-power % for a partial-failure drill. Stock Power-Off 180 is 0 (idle, definitional). Above 0 is a deliberate off-design partial-failure scenario."),
        _field("Alt (ft)", dcc.Input(
            id="poweroff180-altitude",
            type="number", value=1000, min=500, max=2000, step=100,
        ), tooltip="Pattern altitude AGL at the abeam position."),

        html.Div(className="shelf-spacer"),

        html.Button("Set Touchdown",
                    id={"type": "click-button", "m_id": "poweroff180", "role": "touchdown"},
                    className="shelf-action shelf-action-set",
                    title="Click the runway threshold (the touchdown spot)."),
        html.Button("Draw",
                    id="poweroff180-draw-btn",
                    className="shelf-action shelf-action-draw",
                    title="Run the glide-back simulation."),

        # Hidden helper containers that existing callbacks still reference.
        html.Div(id="poweroff180-runway-info", style={"display": "none"}),
        html.Div(id="poweroff180-manual-heading-div", style={"display": "none"}),
        html.Div(id={"type": "click-status", "m_id": "poweroff180"}, style={"display": "none"}),

        # Time scrubber lives in a hidden container until Draw runs
        html.Div(id="poweroff180-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(
                         id="poweroff180-time-slider",
                         min=0, max=100, step=1, value=0,
                         marks={0: "Start", 100: "End"},
                         tooltip={"placement": "bottom", "always_visible": False},
                     ),
                 ]),

        # Stores
        dcc.Store(id="poweroff180-hover-store", data=[]),
        dcc.Store(id="poweroff180-path-store", data=[]),
        dcc.Store(id="poweroff180-results-store", data={}),

        html.Div(id="poweroff180-info", className="shelf-info-panel"),
    ]
