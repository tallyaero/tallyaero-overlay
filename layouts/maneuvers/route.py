"""Route Planner inline form — horizontal-native shelf layout.

When the user picks "Route Planner" from the MANEUVER dropdown, the
maneuver-params-container renders these inputs in the shelf row.
Compute Route triggers the route callback (callbacks/route.py).
"""
from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def route_layout(default_elev=None):
    return [
        _field("From", dcc.Input(
            id="route-origin-input", type="text",
            placeholder="KJFK",
            style={"textTransform": "uppercase"},
        )),
        _field("To", dcc.Input(
            id="route-dest-input", type="text",
            placeholder="KLAX",
            style={"textTransform": "uppercase"},
        )),
        _field("Cruise Alt", dcc.Input(
            id="route-cruise-alt", type="number",
            value=5500, min=0, max=60000, step=500,
        )),
        _field("TAS", dcc.Input(
            id="route-tas", type="number",
            value=110, min=40, max=600,
        )),
        _field("Glide Ratio", dcc.Input(
            id="route-glide-ratio", type="number",
            value=9.0, min=1, max=40, step=0.5,
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
