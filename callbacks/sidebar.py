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
# Power slider visibility — keep wherever the sim actually consumes
# `power_setting` to affect the rendered path. Pre-2026-05-21 audit,
# the ground-reference family was lumped under "hide power" with a
# blanket comment claiming the slider "buys nothing there". The audit
# re-read each sim:
#   - s_turn — power_setting drives the bank-induced altitude-loss
#     model. Wired. Visible.
#   - turns_around_point — angular-step IDEAL-trajectory sim. The
#     position is computed from the perfect circle; `power_setting`
#     is parsed but never consumed (altitude is constant by
#     definition). The pilot sets IAS at setup. Slider hidden.
#   - rect_course / pylons — TODO at next audit; current default is
#     to show since the sims reference power_setting somewhere.
# Engine-out family (impossible_turn, PO180, engineout) has
# definitional power (idle / windmilling / feathered) so the slider
# is genuinely misleading there. Hidden.
#
# CG slider — never moves the rendered polyline. Where it IS read by
# sims it's just a 2% stall-margin advisory factor. Hide globally;
# weight & balance stays elsewhere via Occupants / Occ Wt / Fuel which
# DO drive runtime weight.
_POWER_HIDDEN = "sidebar-power-section"
_CG_HIDDEN = "sidebar-cg-block"

# Maneuvers that hide BOTH power and CG (the engine-out family — power
# is definitional, CG isn't consumed by the sim).
_POWER_AND_CG = {_POWER_HIDDEN, _CG_HIDDEN}
# Maneuvers that keep the Power slider visible (sim actually consumes
# the value) but still hide CG.
_CG_ONLY = {_CG_HIDDEN}

HIDE_BY_MANEUVER: dict[str, set[str]] = {
    "route": {
        # OAT + altimeter feed the route's density-altitude chip now
        # (Phase A2), so keep them visible.
        "sidebar-agl-wrap",        # AGL of picked airport — irrelevant to route
        _CG_HIDDEN,                # CG — doesn't affect glide ratio
        _POWER_HIDDEN,             # Power — pilot picks cruise IAS instead
        # NOTE: do NOT hide map-controls-overlay — Route Planner now uses
        # this container for the airspace + VOR/fix overlay toggles
        # (Phase 7f-follow + 7N-e). The Reset/Undo buttons inside are
        # harmless when no map clicks have happened.
    },
    # Engine-out family — power is definitional, CG isn't consumed.
    "impossible_turn": set(_POWER_AND_CG),
    "poweroff180":     set(_POWER_AND_CG),
    "engineout":       set(_POWER_AND_CG),
    # Ground-reference family — mixed:
    #   s_turn drives altitude loss from power → power VISIBLE
    #   turns_point / rect_course / pylons are ideal-trajectory sims;
    #     the position is computed from the perfect ground track and
    #     the pilot's IAS is held constant — `power_setting` is parsed
    #     but never consumed. Hide the slider so the UI doesn't lie.
    "s_turn":          set(_CG_ONLY),
    "turns_point":     set(_POWER_AND_CG),
    "rect_course":     set(_POWER_AND_CG),
    "pylons":          set(_POWER_AND_CG),
    # Aerobatic / energy maneuvers — Power stays, CG goes.
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
