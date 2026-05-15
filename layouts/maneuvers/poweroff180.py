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


def _field(label, control, slider=False):
    """One labeled mini-column in the shelf."""
    cls = "shelf-field shelf-field-slider" if slider else "shelf-field"
    return html.Div([
        html.Div(label, className="shelf-field-label"),
        control,
    ], className=cls)


def poweroff180_layout(default_elev=None):
    return [
        _field("Runway", dcc.Dropdown(
            id="poweroff180-runway-select",
            placeholder="—",
            clearable=True, searchable=False,
        )),
        _field("Heading", dcc.Input(
            id="poweroff180-manual-heading",
            type="number", value=360, min=1, max=360, step=1,
        )),
        _field("Pattern", html.Div([
            dcc.RadioItems(
                id="poweroff180-pattern",
                options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
                value="left", inline=True, className="shelf-field-radio",
            ),
        ])),
        _field("Flap", dcc.Dropdown(
            id="poweroff180-flap-setting",
            options=[
                {"label": "Clean", "value": "clean"},
                {"label": "Takeoff", "value": "takeoff"},
                {"label": "Landing", "value": "landing"},
            ],
            value="clean", clearable=False,
        )),
        _field("Prop", dcc.Dropdown(
            id="poweroff180-prop-condition",
            options=[
                {"label": "Idle", "value": "idle"},
                {"label": "Windmilling", "value": "windmilling"},
                {"label": "Stopped", "value": "stationary"},
                {"label": "Feathered", "value": "feathered"},
            ],
            value="idle", clearable=False,
        )),
        _field("Abeam (NM)", dcc.Slider(
            id="poweroff180-abeam-distance-nm",
            min=0.3, max=1.5, step=0.05, value=0.5,
            marks={0.3: "0.3", 0.75: "0.75", 1.5: "1.5"},
            tooltip={"always_visible": True},
        ), slider=True),
        _field("Alt (ft)", dcc.Input(
            id="poweroff180-altitude",
            type="number", value=1000, min=500, max=2000, step=100,
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Set Touchdown",
                    id={"type": "click-button", "m_id": "poweroff180", "role": "touchdown"},
                    className="shelf-action shelf-action-set"),
        html.Button("Draw",
                    id="poweroff180-draw-btn",
                    className="shelf-action shelf-action-draw"),

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

        html.Div(id="poweroff180-info", style={"display": "none"}),
    ]
