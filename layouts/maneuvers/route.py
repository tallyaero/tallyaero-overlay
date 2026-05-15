"""Route Planner inline form — horizontal-native shelf layout.

When the user picks "Route Planner" from the MANEUVER dropdown, the
maneuver-params-container renders these inputs in the shelf row.
Compute Route triggers the route callback (callbacks/route.py).

Glide Ratio and Glide IAS default to the selected aircraft's
single_engine_limits.best_glide_ratio / best_glide. The user can still
override per-route in the shelf field.
"""
from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def route_layout(default_glide_ratio: float | None = None,
                 default_glide_ias: float | None = None,
                 default_tas: float | None = None):
    gr = default_glide_ratio if default_glide_ratio else 9.0
    gi = default_glide_ias if default_glide_ias else 75.0
    tas = default_tas if default_tas else 110.0
    return [
        html.Div(
            [html.Div("Route", className="shelf-field-label"),
             dcc.Dropdown(
                id="route-waypoints",
                multi=True,
                searchable=True,
                clearable=True,
                placeholder="Type ICAO, city, or name — e.g. KJFK, summerville, savannah",
                options=[],
                value=[],
                className="route-waypoint-dropdown",
             )],
            className="shelf-field shelf-field-route",
        ),
        _field("Cruise Alt", dcc.Input(
            id="route-cruise-alt", type="number",
            value=5500, min=0, max=60000, step=500,
        )),
        _field("TAS", dcc.Input(
            id="route-tas", type="number",
            value=tas, min=40, max=600,
        )),
        _field("Glide Ratio", dcc.Input(
            id="route-glide-ratio", type="number",
            value=gr, min=1, max=40, step=0.1,
        )),
        _field("Glide IAS", dcc.Input(
            id="route-glide-ias", type="number",
            value=gi, min=30, max=300, step=1,
        )),
        _field("Corridor", dcc.Checklist(
            id="route-show-corridor",
            options=[{"label": " On", "value": "show"}],
            value=["show"],
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Compute Route", id="compute-route-btn",
                    className="shelf-action shelf-action-draw"),
        html.Button("Clear", id="route-clear-btn",
                    className="shelf-action shelf-action-set"),
    ]
