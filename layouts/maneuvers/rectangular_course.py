"""Rectangular Course parameter form — horizontal-native shelf layout.

UX (post-2026-05-21 audit):
    Pilot clicks the FOUR corners of the rectangle they want to fly. The
    sim then snaps the four clicks to a perfect rectangle (keeps clicks
    1 and 2 as the first edge — the downwind — and projects clicks 3 and
    4 perpendicular to that edge, averaging their perpendicular offset
    to derive the rectangle's width). Live preview after each click.
"""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def rect_course_layout(default_elev=None):
    return [
        _field("Alt (ft)", dcc.Input(
            id="rectcourse-altitude", type="number", value=800, min=400, max=1500,
        ), tooltip="Altitude AGL for the rectangle (600-1000 ft is typical ground-reference training)."),
        _field("IAS", dcc.Input(
            id="rectcourse-ias", type="number", value=95,
        ), tooltip="Indicated airspeed. Leave at default cruise IAS unless practicing slow flight."),
        _field("Direction", dcc.RadioItems(
            id="rectcourse-direction",
            options=[{"label": "L", "value": "left"}, {"label": "R", "value": "right"}],
            value="left", inline=True, className="shelf-field-radio",
        ), tooltip="Pattern direction — L = standard left rectangle."),
        _field("Downwind", dcc.Dropdown(
            # NOTE: id is `-select` (not `-edge`) so the always-present
            # `rectcourse-downwind-edge` Store in desktop.py can own the
            # canonical value. A mirror callback in the rect_course
            # callbacks module copies this dropdown's value into that
            # Store whenever rect_course is the active maneuver. Switching
            # to another maneuver unmounts this dropdown but the Store
            # remains, so the snap callback's Input stays valid.
            id="rectcourse-downwind-edge-select",
            options=[
                {"label": "Auto (from wind)", "value": "auto"},
                {"label": "Edge 1→2", "value": "0"},
                {"label": "Edge 2→3", "value": "1"},
                {"label": "Edge 3→4", "value": "2"},
                {"label": "Edge 4→1", "value": "3"},
            ],
            value="auto", clearable=False, searchable=False,
            style={"minWidth": "140px"},
        ), tooltip="Which edge of the rectangle is the DOWNWIND leg (flown with the wind). 'Auto' picks the edge whose bearing best matches the wind direction. Override if you want to fly a specific orientation."),
        _field("Circuits", dcc.Input(
            id="rectcourse-circuits", type="number",
            value=1, min=1, max=3, step=1,
        ), tooltip="Number of full rectangle loops."),

        html.Div(id="rectcourse-edge-visible-info", className="shelf-info-panel"),
        html.Div(id={"type": "click-status", "m_id": "rect_course"}, style={"display": "none"}),
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
        # Note: `rectcourse-snapped-store` is defined in desktop.py
        # (always-present section) so the snap-preview callback's Output
        # remains resolvable when the user is on a different maneuver
        # and a corner-store fires.
    ]


def rect_course_actions():
    return [
        html.Button("1. Corner",
                    id={"type": "click-button", "m_id": "rect_course", "role": "c1"},
                    className="shelf-action shelf-action-set",
                    title="Click the first corner of your rectangular course. Clicks 1→2 define the downwind edge orientation."),
        html.Button("2. Corner",
                    id={"type": "click-button", "m_id": "rect_course", "role": "c2"},
                    className="shelf-action shelf-action-set",
                    title="Click the second corner — sets the downwind direction (clicks 1→2)."),
        html.Button("3. Corner",
                    id={"type": "click-button", "m_id": "rect_course", "role": "c3"},
                    className="shelf-action shelf-action-set",
                    title="Click the third corner. This sets the width of the rectangle (perpendicular distance from the 1→2 edge)."),
        html.Button("4. Corner",
                    id={"type": "click-button", "m_id": "rect_course", "role": "c4"},
                    className="shelf-action shelf-action-set",
                    title="Click the fourth corner. The sim averages clicks 3 + 4's perpendicular distance and snaps to a perfect rectangle."),
        html.Button("Draw", id={"type": "draw-btn", "m_id": "rect_course"},
                    className="shelf-action shelf-action-draw",
                    title="Simulate the wind-corrected rectangle around the snapped corners."),
        *_results_modal_pair("rect_course", "rectcourse-info",
                             title="Rectangular Course — Simulation Results"),
    ]
