"""VFR Traffic Pattern overlay shelf — pick an airport, see the pattern.

Geometry / entry methodology per FAA AC 90-66B "Non-Towered Airport
Flight Operations" + AFH Ch. 8 "Traffic Patterns". Default entry is
the FAA-recommended 45° to downwind on the pattern side. Teardrop
is offered as an explicit opt-in because the FAA discourages it for
non-towered fields (entry on the upwind side at 45° + descend to
TPA in the pattern leg is the published alternative).

The actual airport + runway picker lives in the top-bar airport
search (we re-use that signal). This shelf carries the pattern-
specific knobs.
"""

from __future__ import annotations

from dash import dcc, html

from layouts.maneuvers._shared import _field, _results_modal_pair


def pattern_layout(default_elev=None):
    return [
        _field("Entry", dcc.Dropdown(
            id="pattern-entry-method",
            options=[
                {"label": "45° to downwind (FAA recommended)", "value": "45_downwind"},
                {"label": "Midfield crossover", "value": "midfield_crossover"},
                {"label": "Direct downwind (mid-leg)", "value": "direct_downwind"},
                {"label": "Direct crosswind", "value": "direct_crosswind"},
                {"label": "Direct base (when permitted)", "value": "direct_base"},
                {"label": "Straight-in (long final)", "value": "straight_in"},
                {"label": "Teardrop (opt-in, not preferred)", "value": "teardrop"},
            ],
            value="45_downwind",
            clearable=False,
        ), tooltip="Entry method per AC 90-66B. 45° to downwind is the "
                  "FAA-recommended default for non-towered fields. "
                  "Direct downwind / crosswind / base entries — use only "
                  "with ATC instruction (towered) or when traffic and "
                  "geometry support it; ALWAYS yield to aircraft on the "
                  "standard 45° entry. Straight-in for IFR or VFR "
                  "specific cases — call intentions on CTAF 10 NM out. "
                  "Teardrop is the FAA-discouraged alternative."),
        _field("Pattern dir", dcc.Dropdown(
            id="pattern-direction",
            options=[
                {"label": "Auto (left default)", "value": "auto"},
                {"label": "Left", "value": "left"},
                {"label": "Right", "value": "right"},
            ],
            value="auto",
            clearable=False,
        ), tooltip="Standard left-hand patterns unless the airport publishes "
                  "right traffic for the runway in use. Override if you "
                  "know this airport uses right patterns for a specific "
                  "runway."),
        _field("Runway", dcc.Dropdown(
            id="pattern-runway",
            options=[],
            placeholder="Auto (max headwind)",
            clearable=True,
        ), tooltip="Override the auto-picked runway. Default = the runway "
                  "with the strongest headwind component (FAA standard "
                  "wind-favored runway). Populated from the picked "
                  "airport's runway database."),
        _field("TPA (AGL)", dcc.Input(
            id="pattern-tpa-agl", type="number", value=1000, min=600, max=2000, step=50,
        ), tooltip="Traffic pattern altitude AGL. FAA standard is 1000 ft "
                  "AGL for fixed-wing single piston (800 ft for some "
                  "grass strips). Some Class D fields publish a higher "
                  "TPA — verify against the chart supplement."),
        _field("Pattern leg (NM)", dcc.Input(
            id="pattern-leg-nm", type="number", value=0.5, min=0.3, max=1.5, step=0.1,
        ), tooltip="Lateral distance from the runway centerline to the "
                  "downwind leg. 0.5 NM is the typical training "
                  "spacing (≈ wingtip on the runway numbers at TPA)."),

        # Bearing-input shim — pattern doesn't take map clicks itself,
        # the airport picker drives this. Keep the no-op div so the
        # generic click handler doesn't error.
        html.Div(id={"type": "click-status", "m_id": "pattern"}, style={"display": "none"}),

        # Result stores + slider container so the scrubber pattern
        # we already use elsewhere works here too. Empty by default.
        dcc.Store(id="pattern-result-store", data={}),
        html.Div(id="pattern-slider-container",
                 style={"display": "none"},
                 children=[
                     dcc.Slider(id="pattern-time-slider",
                                min=0, max=100, step=1, value=0,
                                marks={0: "Entry", 100: "Touchdown"},
                                tooltip={"placement": "bottom", "always_visible": False}),
                 ]),
        dcc.Store(id="pattern-hover-store", data=[]),
        dcc.Store(id="pattern-path-store", data=[]),
    ]


def pattern_actions():
    return [
        html.Button("Draw Pattern", id={"type": "draw-btn", "m_id": "pattern"},
                    className="shelf-action shelf-action-draw",
                    title="Draw the pattern for the picked airport + selected entry."),
        *_results_modal_pair("pattern", "pattern-info",
                             title="VFR Pattern — Geometry"),
    ]
