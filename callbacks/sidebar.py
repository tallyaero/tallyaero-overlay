"""Sidebar relevance — hide controls that don't affect the current
maneuver so the pilot sees a focused set of inputs.

Route Planner doesn't depend on density altitude (OAT/altimeter),
the picked airport's AGL, the aircraft CG position, or the throttle
setting — those controls are noise when the user is planning a
route. Hide them. Other maneuvers need the full set so we revert to
showing everything.

We toggle `style={"display": "none"}` via a single callback rather
than rebuilding the layout, so the controls retain their state
(persistence-friendly) across maneuver switches.
"""
from __future__ import annotations

from dash import Input, Output


# Per-maneuver irrelevance map. Listing only what to HIDE keeps the
# default behavior (show everything) for any maneuver not enumerated.
HIDE_BY_MANEUVER: dict[str, set[str]] = {
    "route": {
        "sidebar-thermo-row",      # OAT + altimeter — no density alt in route
        "sidebar-agl-wrap",        # AGL of picked airport — irrelevant to route
        "sidebar-cg-block",        # CG slider — doesn't affect glide ratio
        "sidebar-power-section",   # Power setting — pilot picks cruise speed
    },
}

# Every element id the callback can target. Must be the union of all
# values in HIDE_BY_MANEUVER so Dash knows the full Output set up
# front.
ALL_TARGETS: tuple[str, ...] = tuple(sorted(
    {tgt for hides in HIDE_BY_MANEUVER.values() for tgt in hides}
))


def _style_for(target: str, maneuver: str) -> dict:
    hidden = HIDE_BY_MANEUVER.get(maneuver or "", set())
    if target in hidden:
        return {"display": "none"}
    # Return an empty dict (not None) so Dash clears any prior
    # display:none cleanly when switching back to a maneuver that
    # needs the control.
    return {}


def register(app):
    @app.callback(
        [Output(t, "style") for t in ALL_TARGETS],
        Input("maneuver-select", "value"),
    )
    def update_sidebar_visibility(maneuver):
        return [_style_for(t, maneuver) for t in ALL_TARGETS]
