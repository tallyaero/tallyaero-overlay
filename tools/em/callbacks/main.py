"""TallyAero EM Diagram — main-page callbacks: aircraft selection cascade, dropdowns, CG, weight, maneuver options."""

from __future__ import annotations

import math

import dash
from dash import ctx, dcc, html
import dash_bootstrap_components as dbc
from dash.dependencies import ALL, Input, Output, State
from dash.exceptions import PreventUpdate

from em_core import (
    AIRCRAFT_DATA, AIRPORT_DATA, AIRPORT_OPTIONS, aircraft_data,
    extract_vmca_value, get_airport_by_id,
    dprint, log_feature,
    interpolate_stall_speed,
)


# ──────────────────────────────────────────────────────────────────────────
# Phase 5c — State Panel "hero metric" cards.
# Rendered above the chart. Six at-a-glance values updated on every input
# change. Apple Health–style number cards with Space Grotesk display font.
# ──────────────────────────────────────────────────────────────────────────


def _state_card(label: str, value: str, flag: str | None = None, card_id: str | None = None):
    """Build one hero-number card for the State Panel.

    `card_id` (when given) becomes the element id so a dbc.Popover in the
    layout can target it — click any card to read the term's definition.
    """
    cls = "state-card"
    if flag:
        cls += f" flag-{flag}"
    return html.Div(
        [
            html.Div(label, className="state-label"),
            html.Div(value, className="state-value"),
        ],
        id=card_id,
        className=cls,
        n_clicks=0,
    )


# ──────────────────────────────────────────────────────────────────────────
# Phase 5V-2 — Definitions for each State Panel card.
# Pilot-readable, tied to a regulatory or textbook reference where useful.
# Rendered as click-popovers via `build_state_card_popovers()`, which the
# desktop layout pulls in once. KE/PE/E especially need definition because
# the FAA only put energy management in the GA training canon in 2021.
# ──────────────────────────────────────────────────────────────────────────
STATE_CARD_DEFINITIONS: dict[str, tuple[str, str]] = {
    "state-card-weight": (
        "Total Weight",
        "Aircraft + fuel + occupants right now. Drives stall speed, climb rate, "
        "structural margins, and turn radius. Verified against current weight "
        "table when available.",
    ),
    "state-card-vs1g": (
        "Vs 1G — Stall Speed at 1G",
        "Power-off stall speed in coordinated level flight (load factor n=1), "
        "interpolated from the aircraft's stall table for your current weight + "
        "flap configuration. Bottom of the white/green arc on the airspeed indicator.",
    ),
    "state-card-va": (
        "Va — Maneuvering Speed",
        "Above Va, abrupt full deflection of any single control could exceed the "
        "structural G limit. Va = Vs1G × √(positive G limit) — so it scales with "
        "weight (lighter = lower Va). Per 14 CFR 23.335 / FAA AFH Ch 5.",
    ),
    "state-card-vne": (
        "Vne — Never Exceed",
        "Smooth-air structural redline. Red radial on the airspeed indicator. "
        "Published directly in the POH; not affected by weight, altitude, or "
        "configuration in the schedule shown here.",
    ),
    "state-card-vno": (
        "Vno — Max Structural Cruising",
        "Top of the green arc / bottom of the yellow arc. Operate above Vno "
        "only in smooth air. Published in the POH.",
    ),
    "state-card-glim": (
        "+G Structural Limit",
        "Maximum positive load factor for the current category + flap "
        "configuration. Normal category = +3.8 G; Utility = +4.4 G; Aerobatic "
        "= +6 G or more. Sets where the load-limit line sits on the EM diagram.",
    ),
    "state-card-ke": (
        "KE — Kinetic Energy",
        "Specific kinetic energy expressed in feet of altitude-equivalent: "
        "KE = V²/(2g). At 100 KIAS that's ~443 ft. Tells you how much altitude "
        "you could trade your airspeed for at constant total energy — pull up, "
        "convert KE → PE. Computed at the aircraft's Vy reference.",
    ),
    "state-card-pe": (
        "PE — Potential Energy",
        "Specific potential energy = your current altitude. The other half of the "
        "energy-management equation. Pushing the nose down trades PE → KE along "
        "the constant-energy curve.",
    ),
    "state-card-e": (
        "E — Total Specific Energy",
        "E = KE + PE = h + V²/(2g). The 'energy height' Rutowski (1954) and Boyd "
        "(1966) used as the central performance variable. Throttle adds total E; "
        "elevator redistributes between KE and PE. Bedrock of FAA AFH Ch 4 (2021).",
    ),
}


def build_state_card_popovers():
    """Phase 5V-2 — emit one dbc.Popover per state card. The desktop rail
    layout calls this once and drops the list into the DOM near the panel.
    Cards must carry the matching `card_id` set in `_state_card(...)`."""
    import dash_bootstrap_components as dbc
    pops = []
    for card_id, (title, body) in STATE_CARD_DEFINITIONS.items():
        pops.append(
            dbc.Popover(
                [
                    dbc.PopoverHeader(title),
                    dbc.PopoverBody(body, className="state-card-popover-body"),
                ],
                id=f"popover-{card_id}",
                target=card_id,
                trigger="click",
                placement="left",
                hide_arrow=False,
                className="state-card-popover",
            )
        )
    return pops


def _format_speed(v_kt, unit: str) -> str:
    """Format an airspeed for display. Returns 'XXX kt' or 'XXX mph'."""
    if v_kt is None:
        return "—"
    if unit == "MPH":
        return f"{v_kt * 1.15078:.0f} mph"
    return f"{v_kt:.0f} kt"


def register(app):
    """Install every callback in this module."""

    @app.callback(
        Output("state-panel", "children"),
        Input("aircraft-select", "value"),
        Input("config-select", "value"),
        Input("category-select", "value"),
        Input("stored-total-weight", "data"),
        Input("unit-select", "data"),
        Input("altitude-slider", "value"),
    )
    def update_state_panel(ac_name, config, category, total_weight, unit, altitude_ft):
        """Compute the 6 hero numbers from current selection.

        Outputs:
            WEIGHT, Vs1g, Va, Vne, Vno, +G LIMIT.

        (Corner velocity is intentionally NOT shown — it is analytically
        identical to Va for the same load factor on GA aircraft, so the
        former CORNER card was a duplicate. +G LIMIT shows the structural
        positive G that the EM-diagram envelope is bounded by, which Va is
        derived from.)
        """
        unit = (unit or "KIAS").upper()

        # Empty state — no aircraft selected
        if not ac_name or ac_name not in aircraft_data:
            return [
                _state_card("WEIGHT",  "—", card_id="state-card-weight"),
                _state_card("Vs 1G",   "—", card_id="state-card-vs1g"),
                _state_card("Va",      "—", card_id="state-card-va"),
                _state_card("Vne",     "—", card_id="state-card-vne"),
                _state_card("Vno",     "—", card_id="state-card-vno"),
                _state_card("+G LIMIT", "—", card_id="state-card-glim"),
                _state_card("KE",      "—", card_id="state-card-ke"),
                _state_card("PE",      "—", card_id="state-card-pe"),
                _state_card("E",       "—", card_id="state-card-e"),
            ]

        ac = aircraft_data[ac_name]
        cfg = config or "clean"
        cat = category or "normal"

        # ── Weight ──────────────────────────────────────────────
        weight_lb = total_weight or ac.get("empty_weight", 0)
        max_weight = ac.get("max_weight")
        weight_flag = "danger" if max_weight and weight_lb > max_weight else None

        # ── Vs1g (interpolated by current weight) ───────────────
        stall_table = ac.get("stall_speeds", {}).get(cfg) or ac.get("stall_speeds", {}).get("clean")
        try:
            vs1g_kt = interpolate_stall_speed(stall_table or {}, weight_lb) if stall_table else None
        except Exception:
            vs1g_kt = None

        # ── G limit (positive, current category + flap config) ─
        g_limits = (ac.get("G_limits", {}) or {}).get(cat, {}).get(cfg, {})
        n_pos = g_limits.get("positive")
        # Flag aerobatic if user is in aerobatic category — green accent.
        g_flag = "success" if cat == "aerobatic" and n_pos and n_pos >= 4.5 else None

        # ── Va (maneuvering) = Vs1g · √n_positive ──────────────
        va_kt = vs1g_kt * (n_pos ** 0.5) if (vs1g_kt and n_pos and n_pos > 0) else None

        # ── Vne, Vno (direct from JSON) ────────────────────────
        vne_kt = ac.get("Vne")
        vno_kt = ac.get("Vno")

        # Phase 5V — Energy state at the current cruise reference point.
        # Cruise reference = Vy if known, else Vno, else 100 KIAS; coupled
        # with the current altitude-slider value. The Energy split is a
        # static "where are you on the constant-energy curve" snapshot —
        # the chart hover already shows per-point Ps for dynamic state.
        from em_core import compute_energy_state
        ref_ias_kt = (
            ac.get("Vy") or ac.get("best_glide") or vno_kt or 100
        )
        es = compute_energy_state(altitude_ft or 0, ref_ias_kt)
        ke_str = f"{int(es['ke_ft']):,} ft"
        pe_str = f"{int(es['pe_ft']):,} ft"
        e_str  = f"{int(es['e_total_ft']):,} ft"

        return [
            _state_card("WEIGHT",   f"{int(weight_lb):,} lb" if weight_lb else "—", flag=weight_flag, card_id="state-card-weight"),
            _state_card("Vs 1G",    _format_speed(vs1g_kt, unit),                                       card_id="state-card-vs1g"),
            _state_card("Va",       _format_speed(va_kt, unit),                                         card_id="state-card-va"),
            _state_card("Vne",      _format_speed(vne_kt, unit),                                        card_id="state-card-vne"),
            _state_card("Vno",      _format_speed(vno_kt, unit),                                        card_id="state-card-vno"),
            _state_card("+G LIMIT", f"{n_pos:.1f} G" if n_pos else "—", flag=g_flag,                    card_id="state-card-glim"),
            _state_card("KE",       ke_str,                                                             card_id="state-card-ke"),
            _state_card("PE",       pe_str,                                                             card_id="state-card-pe"),
            _state_card("E",        e_str,                                                              card_id="state-card-e"),
        ]

    @app.callback(
        Output("aircraft-select", "options"),
        Input("aircraft-data-store", "data"),
    )
    def update_aircraft_options(data):
        if not data:
            # No data yet -> no options
            return []
        return [{"label": name, "value": name} for name in sorted(data.keys())]

    # Phase 5U — comparison-aircraft dropdown shares the same option list.
    @app.callback(
        Output("aircraft-compare-select", "options"),
        Input("aircraft-data-store", "data"),
    )
    def update_compare_aircraft_options(data):
        if not data:
            return []
        return [{"label": name, "value": name} for name in sorted(data.keys())]

    # Wire the compare-aircraft Store + chip label so they reflect the selection.
    @app.callback(
        Output("compare-aircraft", "data"),
        Output("chip-compare-label", "children"),
        Input("aircraft-compare-select", "value"),
    )
    def sync_compare_aircraft(value):
        if not value:
            return None, "Compare"
        return value, f"vs {value[:18]}"

    @app.callback(
        Output("category-select", "options"),
        Output("category-select", "value"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def update_category_dropdown(ac_name):
        if not ac_name or ac_name not in aircraft_data:
            raise PreventUpdate

        ac = aircraft_data[ac_name]
        categories = list(ac.get("G_limits", {}).keys())
        options = [{"label": cat.capitalize(), "value": cat} for cat in categories]
        default = options[0]["value"] if options else None
        return options, default

    @app.callback(
        Output("config-details", "style"),
        Output("sidebar-accordion", "active_item"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def expand_ui_on_aircraft_select(ac_name):
        """Show config details and expand all accordions when aircraft is selected."""
        if not ac_name:
            return {"display": "none"}, ["config"]
        return {"display": "block"}, ["config", "environment", "overlays", "maneuvers"]

    @app.callback(
        Output("multi-engine-toggles", "style"),
        Output("prop-condition-container", "style"),
        Input("aircraft-select", "value"),
        Input("oei-toggle", "value"),
        Input("multi-engine-toggle-options", "data"),
        prevent_initial_call=True
    )
    def update_dynamic_vmca_visibility(ac_name, oei_toggle, multi_engine_opts):
        from dash.exceptions import PreventUpdate

        if not ac_name or ac_name not in aircraft_data:
            raise PreventUpdate

        ac = aircraft_data[ac_name]
        is_multi = ac.get("engine_count", 1) >= 2
        oei_enabled = oei_toggle and "enabled" in oei_toggle
        vmca_enabled = "vmca" in (multi_engine_opts or [])

        # Show dynamic overlays only when OEI is active
        show_vmca_block = {"display": "block"} if is_multi and oei_enabled else {"display": "none"}

        # Show prop condition only when Dynamic Vmc is toggled *and* OEI is active
        show_prop_condition = {"display": "block", "marginTop": "5px"} if is_multi and oei_enabled and vmca_enabled else {"display": "none"}

        return show_vmca_block, show_prop_condition

    @app.callback(
        Output("engine-select", "options"),
        Output("engine-select", "value"),
        Output("occupants-select", "options"),
        Output("occupants-select", "value"),
        Output("fuel-slider", "max"),
        Output("fuel-slider", "marks"),
        Output("altitude-slider", "max"),
        Output("altitude-slider", "marks"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def update_aircraft_dependent_inputs(ac_name):
        if not ac_name or ac_name not in aircraft_data:
            raise PreventUpdate

        ac = aircraft_data[ac_name]

        # Engine
        engines = ac["engine_options"]
        engine_opts = [{"label": name, "value": name} for name in engines.keys()]
        engine_val = engine_opts[0]["value"]

        # Occupants
        seat_count = ac["seats"]
        occ_opts = [{"label": str(i), "value": i} for i in range(seat_count + 1)]
        occ_val = min(2, seat_count)

        # Fuel - create intuitive even marks
        fuel_max = ac["fuel_capacity_gal"]

        # Determine a nice step size based on fuel capacity
        if fuel_max <= 20:
            step = 5
        elif fuel_max <= 50:
            step = 10
        elif fuel_max <= 100:
            step = 20
        elif fuel_max <= 200:
            step = 25
        else:
            step = 50

        # Generate marks at even intervals
        fuel_marks = {}
        mark_val = 0
        while mark_val < fuel_max:
            fuel_marks[mark_val] = str(mark_val)
            mark_val += step
        # Always include the max value
        fuel_marks[fuel_max] = str(fuel_max)

        # Altitude — compact marks ("10k" not "10000") so the rightmost label
        # doesn't get clipped at the rail edge.
        ceiling = ac.get("mx_altitude") or ac.get("max_altitude")
        if ceiling is None:
            ceiling = 15000
        alt_marks = {i: f"{i // 1000}k" for i in range(0, ceiling + 1, 5000) if i > 0}
        alt_marks[0] = "SL"
        alt_marks[ceiling] = f"{ceiling // 1000}k"

        return (
            engine_opts,
            engine_val,
            occ_opts,
            occ_val,
            fuel_max,
            fuel_marks,
            ceiling,
            alt_marks,

        )

    @app.callback(
        Output("cg-slider-container", "children"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def render_cg_slider(ac_name):
        if not ac_name or ac_name not in aircraft_data:
            raise PreventUpdate

        ac = aircraft_data[ac_name]
        raw_min, raw_max = ac["cg_range"]
        cg_min = round(float(raw_min), 2)
        cg_max = round(float(raw_max), 2)
        cg_range = cg_max - cg_min

        # Determine step size based on CG range
        if cg_range <= 5:
            step = 0.5
        elif cg_range <= 10:
            step = 1.0
        else:
            step = 2.0

        # Generate marks at even intervals
        import math
        # Start from the first even step value >= cg_min
        first_mark = math.ceil(cg_min / step) * step

        cg_marks = {}
        # Add FWD label at min
        cg_marks[cg_min] = f"FWD"

        # Add intermediate marks
        mark_val = first_mark
        while mark_val < cg_max:
            if mark_val > cg_min:  # Don't duplicate the min
                cg_marks[round(mark_val, 1)] = f"{mark_val:.1f}"
            mark_val += step

        # Add AFT label at max
        cg_marks[cg_max] = f"AFT"

        dprint("CG DEBUG:", {
            "cg_min": cg_min,
            "cg_max": cg_max,
            "step": step,
            "marks": cg_marks
        })

        return html.Div([
            html.Label("CG (inches)", className="input-label-sm rail-control-label"),
            dcc.Slider(
                id="cg-slider",
                min=cg_min,
                max=cg_max,
                value=round((cg_min + cg_max) / 2, 2),
                step=0.1,
                marks=cg_marks,
                tooltip={"always_visible": True, "placement": "bottom"},
            )
        ])

    @app.callback(
        Output("config-select", "options"),
        Output("config-select", "value"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def update_config_dropdown(ac_name):
        if not ac_name or ac_name not in aircraft_data:
            raise PreventUpdate

        flaps = aircraft_data[ac_name]["configuration_options"]["flaps"]
        options = [{"label": flap, "value": flap} for flap in flaps]
        default = options[0]["value"] if options else None
        return options, default

    @app.callback(
        Output("gear-select", "options"),
        Output("gear-select", "value"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def update_gear_dropdown(ac_name):
        if not ac_name or ac_name not in aircraft_data:
            raise PreventUpdate

        ac = aircraft_data[ac_name]
        if ac.get("gear_type") == "retractable":
            options = [{"label": "Up", "value": "up"}, {"label": "Down", "value": "down"}]
            return options, "up"
        else:
            return [], None

    @app.callback(
        Output("gear-select-container", "style"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def toggle_gear_selector_visibility(ac_name):
        if not ac_name or ac_name not in aircraft_data:
            return {"display": "none"}

        gear_type = aircraft_data[ac_name].get("gear_type", "fixed")
        return {"display": "block"} if gear_type == "retractable" else {"display": "none"}

    @app.callback(
        Output("total-weight-display", "children"),
        Output("total-weight-display", "style"),
        Output("stored-total-weight", "data"),
        Input("aircraft-select", "value"),
        Input("fuel-slider", "value"),
        Input("occupants-select", "value"),
        Input("passenger-weight-input", "value"),
    )
    def update_total_weight(ac_name, fuel, occupants, pax_weight):
        if not ac_name or ac_name not in aircraft_data:
            raise PreventUpdate

        ac = aircraft_data[ac_name]
        empty = ac["empty_weight"]
        fuel = fuel if fuel is not None else 0
        fuel_weight = fuel * ac["fuel_weight_per_gal"]
        pax_weight = pax_weight if pax_weight is not None else 180
        occupants = occupants if occupants is not None else 0
        people_weight = occupants * pax_weight
        total = empty + fuel_weight + people_weight
        max_weight = ac["max_weight"]

        color = "darkgreen" if total <= max_weight else "red"

        # Phase 5AB-12: rail readout is now hidden (WEIGHT state tile in the
        # top bar shows the value). Keep computing total + color for the
        # `stored-total-weight` store consumer; style stays display:none so
        # the now-hidden div doesn't leak back into view.
        return (
            f"{int(total)} lbs",
            {"display": "none", "color": color, "fontWeight": "bold", "fontSize": "16px"},
            total
        )

    def _maneuver_replay_scrubber(marks=None):
        """Shared replay-scrubber widget rendered inside every maneuver's
        options panel that has a real time trajectory (chandelle, lazy 8).
        Drives the clientside `tallyaero.replayManeuver` callback which
        positions an orange marker along whichever maneuver trace is
        currently plotted on the EM chart.
        """
        marks = marks if marks is not None else {0: "START", 50: "MID", 100: "END"}
        return html.Div([
            html.Div([
                html.Span("Replay", className="overlay-label"),
                html.Span(
                    id="maneuver-replay-readout",
                    className="replay-readout",
                ),
            ], className="replay-header"),
            dcc.Slider(
                id="maneuver-replay-slider",
                min=0, max=100, step=1, value=0,
                marks=marks,
                tooltip={"placement": "bottom", "always_visible": False},
                included=False,
            ),
        ], className="maneuver-replay")

    @app.callback(
        Output("maneuver-options-container", "children"),
        Input("maneuver-select", "value"),
        prevent_initial_call=True,
    )
    def render_maneuver_options(maneuver):
        if maneuver == "steep_turn":
            return html.Div([
                # Row 1: Airspeed input
                dbc.Row([
                    dbc.Col([
                        html.Label("Airspeed (KIAS)", className="input-label-sm"),
                        dcc.Input(
                            id={"type": "steepturn-ias", "index": 0},
                            type="number",
                            value=110,
                            min=40,
                            max=200,
                            step=1,
                            style={"width": "100px"}
                        )
                    ], width="auto")
                ], className="mb-3"),

                # Row 2: AOB Slider
                dbc.Row([
                    dbc.Col([
                        html.Label("Angle of Bank (°)", className="input-label-sm"),
                        dcc.Slider(
                            id={"type": "steepturn-aob", "index": 0},
                            min=10,
                            max=90,
                            step=5,
                            value=45,
                            marks={i: f"{i}°" for i in range(10, 91, 10)},
                            tooltip={"always_visible": True},
                            included=False,
                        )
                    ])
                ], className="mb-3"),

                # Row 3: Ghost Trace Toggle
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Div([
                                html.Span("Ghost Trace", className="overlay-label"),
                                html.Span("?", id={"type": "ghost-help-trigger", "index": "steep"}, className="help-icon", n_clicks=0)
                            ], className="label-group"),
                            dbc.Switch(
                                id={"type": "steepturn-ghost", "index": 0},
                                value=False,
                                className="form-switch"
                            )
                        ], className="overlay-row")
                    ])
                ], className="mb-2"),

                # Row 4: ACS Standard Selection (only visible when ghost trace is on)
                html.Div(
                    id="acs-standard-container",
                    children=[
                        dbc.Row([
                            dbc.Col([
                                html.Label("ACS Standard", className="input-label-sm", style={"marginLeft": "20px"}),
                                dbc.Checklist(
                                    id={"type": "steepturn-standard", "index": 0},
                                    options=[
                                        {"label": "Private (45°)", "value": "private"},
                                        {"label": "Commercial (50°)", "value": "commercial"},
                                    ],
                                    value=[],
                                    switch=True,
                                    className="switch-list",
                                    style={"marginLeft": "20px"}
                                )
                            ])
                        ])
                    ],
                    style={"display": "none"}  # Hidden by default
                )
            ])
        elif maneuver == "chandelle":
            return html.Div([
                # Row 1: Airspeed input
                dbc.Row([
                    dbc.Col([
                        html.Label("Airspeed (KIAS)", className="input-label-sm"),
                        dcc.Input(
                            id={"type": "chandelle-ias", "index": 0},
                            type="number",
                            value=105,
                            min=40,
                            max=200,
                            step=1,
                            style={"width": "100px"}
                        )
                    ], width="auto")
                ], className="mb-3"),

                # Row 2: AOB Slider
                dbc.Row([
                    dbc.Col([
                        html.Label("Angle of Bank (°)", className="input-label-sm"),
                        dcc.Slider(
                            id={"type": "chandelle-bank", "index": 0},
                            min=10,
                            max=45,
                            step=1,
                            value=30,
                            marks={i: f"{i}°" for i in range(10, 46, 5)},
                            tooltip={"always_visible": True},
                            included=False
                        )
                    ])
                ], className="mb-3"),

                # Row 3: Ghost Trace Toggle
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Div([
                                html.Span("Ghost Trace", className="overlay-label"),
                                html.Span("?", id={"type": "ghost-help-trigger", "index": "chandelle"}, className="help-icon", n_clicks=0)
                            ], className="label-group"),
                            dbc.Switch(
                                id={"type": "chandelle-ghost", "index": 0},
                                value=True,
                                className="form-switch"
                            )
                        ], className="overlay-row")
                    ])
                ], className="mb-3"),

                # Phase 5h — Replay scrubber (shared with all maneuvers).
                _maneuver_replay_scrubber(marks={
                    0: "START", 25: "90°", 50: "180°", 75: "270°", 100: "END",
                }),
            ])

        elif maneuver == "lazy_eight":
            return html.Div([
                # Row 1: Entry airspeed
                dbc.Row([
                    dbc.Col([
                        html.Label("Entry Airspeed (KIAS)", className="input-label-sm"),
                        dcc.Input(
                            id={"type": "lazy8-ias", "index": 0},
                            type="number",
                            value=110,
                            min=40,
                            max=200,
                            step=1,
                            style={"width": "100px"}
                        )
                    ], width="auto")
                ], className="mb-3"),

                # Row 2: Max AOB slider (FAA ACS: ~30°)
                dbc.Row([
                    dbc.Col([
                        html.Label("Max Angle of Bank (°)", className="input-label-sm"),
                        dcc.Slider(
                            id={"type": "lazy8-bank", "index": 0},
                            min=10, max=45, step=1, value=30,
                            marks={i: f"{i}°" for i in range(10, 46, 5)},
                            tooltip={"always_visible": True},
                            included=False,
                        )
                    ])
                ], className="mb-3"),

                # Row 3: Ghost trace toggle
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Div([
                                html.Span("Ghost Trace", className="overlay-label"),
                                html.Span("?", id={"type": "ghost-help-trigger", "index": "lazy_eight"}, className="help-icon", n_clicks=0)
                            ], className="label-group"),
                            dbc.Switch(
                                id={"type": "lazy8-ghost", "index": 0},
                                value=True,
                                className="form-switch"
                            )
                        ], className="overlay-row")
                    ])
                ], className="mb-3"),

                # Phase 5h — Replay scrubber (same widget as chandelle).
                # Marks reference the symmetric figure-8 phases.
                _maneuver_replay_scrubber(marks={
                    0:   "ENTRY",
                    25:  "45° UP",
                    50:  "APEX",
                    75:  "45° DN",
                    100: "EXIT",
                }),
            ])

        # No maneuver selected
        return None

