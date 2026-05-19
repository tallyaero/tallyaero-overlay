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
#
# Power slider visibility — keep ONLY where the Design Directive
# verdicts (Phase D) actually drive behavior:
#   steep_turn / chandelle / lazy8     — off-design power drifts sim
#   steep_spiral                       — partial-power drill (off-design)
# Hide everywhere else. The engine-out family (impossible_turn, PO180,
# engineout) has definitional power, so the slider is misleading.
# The ground-reference family (s_turn, TAP, rect_course, pylons) is
# IAS-managed — pilots hold a constant IAS and manage track via bank;
# the slider buys nothing there.
#
# CG slider — never moves the rendered polyline. Where it IS read by
# sims (the 4 ground-reference sims) it's just a 2% stall-margin
# advisory factor. Hide globally; weight & balance stays elsewhere
# via Occupants / Occ Wt / Fuel which DO drive runtime weight.
_POWER_HIDDEN = "sidebar-power-section"
_CG_HIDDEN = "sidebar-cg-block"

# Maneuvers that hide BOTH power and CG (the slider audit's "useless"
# set per the Design Directive + the CG-doesn't-render call).
_POWER_AND_CG = {_POWER_HIDDEN, _CG_HIDDEN}
# Maneuvers that keep the Power slider visible (Design Directive
# fires there) but still hide CG.
_CG_ONLY = {_CG_HIDDEN}

HIDE_BY_MANEUVER: dict[str, set[str]] = {
    "route": {
        "sidebar-thermo-row",      # OAT + altimeter — no density alt in route
        "sidebar-agl-wrap",        # AGL of picked airport — irrelevant to route
        _CG_HIDDEN,                # CG — doesn't affect glide ratio
        _POWER_HIDDEN,             # Power — pilot picks cruise IAS instead
        "map-controls-overlay",    # Reset All / Reset Clicks / Undo —
                                    # route planner doesn't use map clicks
                                    # for point-setting maneuvers
    },
    # Engine-out family — full / idle / feathered power is definitional;
    # CG isn't even read by the sim.
    "impossible_turn": set(_POWER_AND_CG),
    "poweroff180":     set(_POWER_AND_CG),
    "engineout":       set(_POWER_AND_CG),
    # Ground-reference family — pilots hold constant IAS, CG's 2% stall
    # factor doesn't change the drawn ground track.
    "s_turn":          set(_POWER_AND_CG),
    "turns_point":     set(_POWER_AND_CG),
    "rect_course":     set(_POWER_AND_CG),
    "pylons":          set(_POWER_AND_CG),
    # Aerobatic / energy maneuvers — Power stays (Design Directive),
    # CG goes (not consumed).
    "steep_turn":      set(_CG_ONLY),
    "chandelle":       set(_CG_ONLY),
    "lazy8":           set(_CG_ONLY),
    "steep_spiral":    set(_CG_ONLY),
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
