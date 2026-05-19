"""Route Planner inline form — horizontal-native shelf layout.

When the user picks "Route Planner" from the MANEUVER dropdown, the
maneuver-params-container renders these inputs in the shelf row.
Compute Route triggers the route callback (callbacks/route.py).

Glide Ratio + Glide IAS + Climb IAS all default to the selected
aircraft's published numbers (best_glide_ratio, best_glide, Vy).

Layout order (left → right):

    Route (wide dropdown)
    numeric perf inputs  · Cruise Alt | TAS | Glide Ratio | Glide IAS | Climb IAS
    Engine-out segmented (multi-engine only · SE / Glide / Both)
    Pill toggles         · Corridor · Live winds · Slope map · Max slope · Suitable land · Click to add
    Compute · Clear

Display toggles are rendered as pill buttons via the shelf-pill-toggle
class — the underlying control is still a dcc.Checklist so existing
callback wiring works unchanged; only the visual treatment differs.
"""
from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field


def _pill(checklist_id, label, value=None, default_on=False, tooltip=None):
    """Toggle pill backed by a single-option Checklist.

    The pill IS the option label, so the field name lives inside the
    pill instead of above it — saves a label row in the shelf.
    """
    cl = dcc.Checklist(
        id=checklist_id,
        options=[{"label": f" {label}", "value": value or "on"}],
        value=([value or "on"] if default_on else []),
        className="shelf-pill-toggle",
    )
    if tooltip:
        return html.Span(cl, title=tooltip,
                         className="shelf-pill-tooltip-wrap")
    return cl


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
    vy_label = f"Vy {vy_kt:.0f}" if vy_kt else "Vy —"
    return [
        # === Route (wide dropdown) + Click-to-add pill, paired ===
        # Wrapped together so the pill sits IMMEDIATELY to the right
        # of the Route dropdown — both affect waypoint input, and
        # they should never wrap apart.
        html.Div(
            [
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
                _pill("route-click-build-mode", "Click to add",
                      tooltip=("Click anywhere on the map to add a "
                               "GPS turning point. Origin and "
                               "destination must still be airports.")),
            ],
            className="shelf-route-with-pill",
            style={"display": "flex", "alignItems": "flex-end",
                   "gap": "8px", "minWidth": "0"},
        ),

        # === Numeric performance inputs ===
        html.Div(
            [html.Div("Cruise Alt", className="shelf-field-label"),
             html.Div(
                 [dcc.Input(id="route-cruise-alt", type="number",
                            value=5500, min=0, max=60000, step=500,
                            debounce=True),
                  # Quick terrain-conflict heads-up: lights amber if
                  # peak terrain along the great-circle exceeds the
                  # typed cruise altitude minus a 1000 ft buffer.
                  # Updates on debounce (no spam on every keystroke).
                  html.Span(id="route-cruise-alt-check",
                            className="shelf-chip-quiet")],
                 className="shelf-cruise-row")],
            className="shelf-field",
        ),
        _field("Cruise TAS", dcc.Input(
            id="route-tas", type="number",
            value=tas, min=40, max=600,
            debounce=True,
        )),
        _field("Cruise IAS", html.Span(
            dcc.Input(id="route-cruise-ias", type="number",
                      min=40, max=400, debounce=True),
            title=("Cruise indicated airspeed. Empty = compute "
                   "automatically from Cruise TAS via the ISA density "
                   "ratio at the cruise altitude (TAS = IAS / √σ)."),
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

        # === Engine-out segmented (multi-engine only) ===
        html.Div(
            dcc.RadioItems(
                id="route-engine-out-mode",
                options=[
                    {"label": "SE", "value": "se"},
                    {"label": "Glide", "value": "glide"},
                    {"label": "Both", "value": "both"},
                ],
                value="both" if is_multi_engine else "glide",
                inline=True,
                className="shelf-segmented",
            ),
            className=("shelf-segmented-wrap"
                       + ("" if is_multi_engine else " shelf-field-hidden")),
        ),

        # === Display toggles (pills) — flow naturally left, just a
        # small gap from the Compute/Clear cluster to the right. ===
        html.Div(className="shelf-pill-group", children=[
            _pill("route-show-corridor", "Corridor",
                  value="show", default_on=True,
                  tooltip=("Engine-out glide corridor — every point you "
                           "could reach from cruise with the engine "
                           "failed. Master clip mask for the slope and "
                           "suitable-land overlays.")),
            _pill("route-use-live-winds", "Live winds",
                  default_on=True,
                  tooltip=("Use Open-Meteo per-sample winds aloft "
                           "instead of the manual wind in the sidebar.")),
            _pill("route-show-landable", "Landable",
                  tooltip=("Green raster where slope ≤ Max slope AND "
                           "OSM-tagged suitable land AND inside the "
                           "glide corridor. Blue polygons = AFH §18-7 "
                           "water/ditching option inside the corridor. "
                           "Single combined signal — replaces the old "
                           "Slope map / Suitable land toggles.")),
            # Max slope numeric — only matters when Landable is on,
            # so it lives next to that pill.
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
        ]),

        html.Button("Compute Route", id="compute-route-btn",
                    className="shelf-action shelf-action-draw",
                    style={"marginLeft": "16px"}),
        html.Button("Clear", id="route-clear-btn",
                    className="shelf-action shelf-action-set"),
        # Phase A5 — Save/Open route to JSON. The Download element is
        # always-mounted; the Upload component disguises itself as a
        # plain button via the shelf-action style.
        html.Button("Save Route", id="route-save-btn",
                    className="shelf-action shelf-action-set",
                    title="Download the current route + perf inputs as JSON"),
        dcc.Upload(
            id="route-upload",
            children=html.Span("Open Route",
                                className="shelf-action shelf-action-set"),
            accept=".json",
            multiple=False,
            style={"display": "inline-block"},
        ),
        dcc.Download(id="route-download"),
    ]
