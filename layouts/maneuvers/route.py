"""Route Planner inline form — horizontal-native shelf layout.

When the user picks "Route Planner" from the MANEUVER dropdown, the
maneuver-params-container renders these inputs in the shelf row.
Compute Route triggers the route callback (callbacks/route.py).

Glide Ratio + Glide IAS + Climb IAS all default to the selected
aircraft's published numbers (best_glide_ratio, best_glide, Vy).
"""
from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def route_layout(default_glide_ratio: float | None = None,
                 default_glide_ias: float | None = None,
                 default_tas: float | None = None,
                 default_climb_ias: float | None = None,
                 vx_kt: float | None = None,
                 vy_kt: float | None = None,
                 is_multi_engine: bool = False):
    gr = default_glide_ratio if default_glide_ratio else 9.0
    gi = default_glide_ias if default_glide_ias else 75.0
    tas = default_tas if default_tas else 110.0
    ci = default_climb_ias if default_climb_ias else (vy_kt or 76.0)
    # Vy reminder chip text (shown next to Climb IAS for context).
    vy_label = f"Vy {vy_kt:.0f}" if vy_kt else "Vy —"
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
        html.Div(
            [html.Div("Climb IAS", className="shelf-field-label"),
             html.Div(
                [dcc.Input(id="route-climb-ias", type="number",
                           value=ci, min=30, max=400, step=1),
                 html.Span(vy_label, className="shelf-vy-hint"),
                 html.Span(id="route-climb-rate-chip",
                           className="shelf-derived-chip",
                           children="≈ ... fpm")],
                className="shelf-climb-row")],
            className="shelf-field shelf-field-climb",
        ),
        _field("Corridor", dcc.Checklist(
            id="route-show-corridor",
            options=[{"label": " On", "value": "show"}],
            value=["show"],
        )),
        _field("Live winds", dcc.Checklist(
            id="route-use-live-winds",
            options=[{"label": " On", "value": "on"}],
            value=["on"],
        )),
        # Engine-out scenario toggle — only meaningful for ME aircraft
        # but the id must always exist for the callback to bind. We
        # hide via CSS when single-engine.
        html.Div(
            [html.Div("Engine-out", className="shelf-field-label"),
             dcc.RadioItems(
                id="route-engine-out-mode",
                options=[
                    {"label": " SE", "value": "se"},
                    {"label": " Glide", "value": "glide"},
                    {"label": " Both", "value": "both"},
                ],
                value="both" if is_multi_engine else "glide",
                inline=True,
                className="shelf-engine-out-radio",
             )],
            className=("shelf-field shelf-field-engine-out"
                       + ("" if is_multi_engine else " shelf-field-hidden")),
        ),

        _field("Click to add", dcc.Checklist(
            id="route-click-build-mode",
            options=[{"label": " On", "value": "on"}],
            value=[],
        )),
        _field("Slope map", dcc.Checklist(
            id="route-show-slope",
            options=[{"label": " On", "value": "on"}],
            value=[],
        )),
        _field("Suitable land", dcc.Checklist(
            id="route-show-land-cover",
            options=[{"label": " On", "value": "on"}],
            value=[],
        )),
        _field("Clip corridor", html.Span(
            dcc.Checklist(
                id="route-clip-corridor-suitable",
                options=[{"label": " On", "value": "on"}],
                value=[],
            ),
            title=("Intersect the engine-out glide corridor with suitable "
                   "land (OSM farmland/meadow/grass/pasture/grassland). "
                   "Shows only the parts of the corridor where a pilot "
                   "could actually plant the aircraft."),
        )),
        # FAA AFH Chapter 18 names slope as one of three pillars of
        # off-field landing site selection (with wind + obstacles).
        # Default 3° matches operational consensus for "level enough
        # to land without significant uphill/downhill penalty."
        # 3-7° marginal (FAA: land upslope only); >7° steep.
        _field("Max slope °", html.Span(
            dcc.Input(
                id="route-slope-threshold",
                type="number", value=3, min=1, max=20, step=1,
                style={"width": "55px"},
            ),
            title=("Max slope considered 'landable' (FAA AFH §18-4 "
                   "names slope as one off-field landing factor). "
                   "Default 3° matches operational consensus. "
                   "3-7° = 'land upslope only'; >7° = too steep."),
        )),

        html.Div(className="shelf-spacer"),

        html.Button("Compute Route", id="compute-route-btn",
                    className="shelf-action shelf-action-draw"),
        html.Button("Clear", id="route-clear-btn",
                    className="shelf-action shelf-action-set"),
    ]
