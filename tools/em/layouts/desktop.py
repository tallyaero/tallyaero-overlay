"""
TallyAero EM Diagram — desktop layout (Option A).

Phase 5L restructure: replaced the flex sidebar/chart split with a CSS-grid
skeleton — `top-strip` (56px) above `main-grid` (chart 1fr | right-rail 260px).
The top strip currently holds the legacy quick-links cluster (theme + export
+ links); Phase 5M promotes aircraft + environment picker chips into it.
The right rail holds the existing State Panel + accordion contents until
Phase 5M/5O move them into chips and a drawer respectively.

ALL component IDs are preserved verbatim from the previous flex layout so
every existing callback keeps wiring up without modification.

Pure function: no callbacks, no side effects.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

from em_core import AIRPORT_OPTIONS


def _state_card_popovers():
    """Phase 5V-2 — emit one click-popover per State Panel card. Pulled out
    of callbacks.main so the layout module has the only import dependency
    needed at render time."""
    from callbacks.main import build_state_card_popovers
    return build_state_card_popovers()


def _top_strip():
    """Phase 5M strip. Aircraft picker, environment chips, units, theme, export.

    Phase 5AB-1: now a two-row strip. Row 1 holds aircraft + env chips + page
    actions; row 2 holds the inline state-info tiles (Weight, V-speeds, KE/PE/E)
    that were previously in the right rail. The two rows share the same
    background but each has its own padding so they read as a single header.
    """
    return html.Div(
        [
            # ─── ROW 1 — controls and identity ─────────────────────────────
            html.Div([
            # ─── Left: brand + primary input + env chips ──────────────────
            html.Div(
                [
                    html.Span("TallyAero EM", className="top-strip-brand"),

                    # Aircraft picker — the single most important input
                    html.Div(
                        dcc.Dropdown(
                            id="em-aircraft-select",
                            options=[],
                            placeholder="Select an aircraft…",
                            className="dropdown aircraft-dropdown",
                            clearable=False,
                        ),
                        className="aircraft-picker-wrap",
                    ),

                    # Phase 5AB-5: Compare chip moved to the chart-tabs row
                    # (alongside Doghouse / Energy / Drop target). Top strip
                    # is now: brand + aircraft picker | theme + export.
                    # Phase 5AB-2: env chips removed earlier (now inline rail).
                ],
                className="top-strip-left",
            ),

            # ─── Right: units · theme · export · quick links ───────────────
            html.Div(
                [
                    # Units toggle (moved from accordion)
                    html.Div(
                        [
                            html.Button("KIAS", id="btn-kias", className="segment-btn active", n_clicks=0),
                            html.Button("MPH",  id="btn-mph",  className="segment-btn",         n_clicks=0),
                        ],
                        className="segment-control units-control",
                    ),
                    dcc.Store(id="unit-select", data="KIAS"),

                    # Theme toggle — light/dark only (AUTO retired); a hidden
                    # theme-btn-auto sits in DOM so the existing clientside
                    # callback signature (3 button inputs) keeps wiring.
                    html.Div(
                        [
                            html.Button("Light", id="em-theme-btn-light", className="theme-btn active", title="Light mode"),
                            html.Button("Dark",  id="em-theme-btn-dark",  className="theme-btn",        title="Dark mode"),
                        ],
                        className="theme-toggle-group",
                        **{"data-role": "theme-toggle"},
                    ),
                    html.Button("", id="em-theme-btn-auto", n_clicks=0, style={"display": "none"}),

                    # Export cluster
                    html.Div(
                        [
                            html.Button("PNG", id="png-button", className="export-btn", title="Export chart as PNG"),
                            html.Button("PDF", id="pdf-button", className="export-btn", title="Export chart as PDF"),
                        ],
                        className="export-toggle-group",
                        **{"data-role": "export-toggle"},
                    ),
                    dcc.Download(id="png-download"),
                    dcc.Download(id="pdf-download"),

                    # Quick links pushed to the very end as small tertiary text
                    html.Div(
                        [
                            html.Span("Quick Start", id="open-readme", className="quick-link link-blue", style={"cursor": "pointer"}),
                            html.A("Contact", href="mailto:info@tallyaero.com", className="quick-link link-blue"),
                        ],
                        className="top-strip-quicklinks",
                    ),
                ],
                className="top-strip-right",
            ),
            ], className="top-strip-row top-strip-main-row"),

            # ─── ROW 2 — inline state-info tiles (Phase 5AB-1) ─────────────
            # The 9 tiles (Weight, Vs1G, Va, Vne, Vno, +G LIMIT, KE, PE, E)
            # rendered horizontally as `LABEL value` chips. Same `state-panel`
            # id used by callbacks/main.py — only the visual container changed.
            html.Div(
                [
                    html.Div(id="state-panel", className="state-panel state-panel-strip"),
                ],
                className="top-strip-row top-strip-tiles-row",
            ),

            # ─── Popovers ──────────────────────────────────────────────────
            # Phase 5AB-2: Airport / Altitude / OAT / Altimeter popovers
            # removed. Their inputs now live inline in the right rail's
            # Atmosphere section. Compare popover stays (until 5AB-5).

            # Phase 5U — compare-aircraft popover
            dbc.Popover(
                [
                    dbc.PopoverHeader("Compare against"),
                    dbc.PopoverBody(
                        [
                            dcc.Dropdown(
                                id="aircraft-compare-select",
                                options=[],
                                placeholder="Pick a second aircraft…",
                                searchable=True,
                                clearable=True,
                                style={"fontSize": "12px"},
                            ),
                            html.Div(
                                "Renders the second aircraft's lift limit, load limit, and corner over the same chart. Both envelopes use your current weight / altitude / OAT.",
                                className="weather-msg",
                                style={"fontSize": "11px", "marginTop": "8px"},
                            ),
                        ]
                    ),
                ],
                id="popover-compare",
                target="chip-compare",
                trigger="click",
                placement="bottom-start",
                className="env-popover env-popover-compare",
            ),

        ],
        className="top-strip",
    )


def _settings_accordion():
    """Phase 5O — the accordion contents extracted from the rail so they can
    live inside the slide-out drawer. Unchanged from Phase 5M, just relocated.
    Every component id used by an existing callback is preserved verbatim."""
    return dbc.Accordion(
                [
                    # Aircraft Configuration — `aircraft-select` moved to top
                    # strip (Phase 5M). This item now holds only config details
                    # that appear AFTER an aircraft is picked.
                    dbc.AccordionItem(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label("Engine", className="input-label-sm"),
                                            dcc.Dropdown(id="em-engine-select", className="dropdown"),
                                        ],
                                        className="mb-2",
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Category", className="input-label-sm"),
                                            dcc.Dropdown(id="category-select", className="dropdown"),
                                        ],
                                        className="mb-2",
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Flap Configuration", className="input-label-sm"),
                                            dcc.Dropdown(id="config-select", className="dropdown"),
                                        ],
                                        className="mb-2",
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Landing Gear", className="input-label-sm"),
                                            dcc.Dropdown(id="gear-select", className="dropdown"),
                                        ],
                                        id="gear-select-container",
                                        className="mb-2",
                                        style={"display": "none"},
                                    ),
                                    # Phase 5AB-4: Total Weight / Occupants / Occ Weight / Fuel
                                    # moved out of the drawer and into the right rail's
                                    # `_weight_controls()`. They affect every V-speed and
                                    # Ps calc so they belong alongside the chart.
                                    # Phase 5AA: Power, CG, FPA also moved to the rail.
                                    # Drawer now holds only truly configure-once items:
                                    # Engine, Category, Flap, Gear.
                                ],
                                id="config-details",
                                style={"display": "none"},
                            ),
                        ],
                        title="Aircraft Configuration",
                        item_id="config",
                    ),

                    # Environment moved to top strip (Phase 5M):
                    # airport / altitude / OAT / altimeter all live in chips
                    # with dbc.Popovers in _top_strip(). The Environment
                    # accordion item is removed entirely; PA/DA display sits
                    # in the OAT/altimeter popover.

                    # Overlay Options — units toggle moved to top strip (Phase 5M)
                    dbc.AccordionItem(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span("Ps Contours", className="overlay-label"),
                                                    html.Span("?", id="help-ps", className="help-icon", n_clicks=0),
                                                ],
                                                className="label-group",
                                            ),
                                            dbc.Switch(id="toggle-ps", value=False, className="form-switch"),
                                        ],
                                        className="overlay-row",
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span("Intermediate G Lines", className="overlay-label"),
                                                    html.Span("?", id="help-g", className="help-icon", n_clicks=0),
                                                ],
                                                className="label-group",
                                            ),
                                            dbc.Switch(id="toggle-g", value=True, className="form-switch"),
                                        ],
                                        className="overlay-row",
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span("Turn Radius Lines", className="overlay-label"),
                                                    html.Span("?", id="help-radius", className="help-icon", n_clicks=0),
                                                ],
                                                className="label-group",
                                            ),
                                            dbc.Switch(id="toggle-radius", value=True, className="form-switch"),
                                        ],
                                        className="overlay-row",
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span("Angle of Bank Shading", className="overlay-label"),
                                                    html.Span("?", id="help-aob", className="help-icon", n_clicks=0),
                                                ],
                                                className="label-group",
                                            ),
                                            dbc.Switch(id="toggle-aob", value=True, className="form-switch"),
                                        ],
                                        className="overlay-row",
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span("Negative G Envelope", className="overlay-label"),
                                                    html.Span("?", id="help-negative-g", className="help-icon", n_clicks=0),
                                                ],
                                                className="label-group",
                                            ),
                                            dbc.Switch(id="toggle-negative-g", value=False, className="form-switch"),
                                        ],
                                        className="overlay-row",
                                    ),
                                ],
                                className="mb-2",
                            ),
                            dcc.Store(id="overlay-toggle", data=["g", "radius", "aob"]),
                            html.Div(
                                [
                                    html.Label("Engine Failure Simulation", className="input-label-sm"),
                                    dbc.Checklist(
                                        id="oei-toggle",
                                        options=[{"label": "Simulate One Engine Inoperative", "value": "enabled"}],
                                        value=[],
                                        switch=True,
                                        className="switch-list",
                                    ),
                                ],
                                id="oei-container",
                                className="mb-2",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span("Dynamic Vmc", className="overlay-label"),
                                                    html.Span("?", id="help-dvmc", className="help-icon", n_clicks=0),
                                                ],
                                                className="label-group",
                                            ),
                                            dbc.Switch(id="toggle-vmca", value=False, className="form-switch"),
                                        ],
                                        className="overlay-row",
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span("Dynamic Vyse", className="overlay-label"),
                                                    html.Span("?", id="help-dvyse", className="help-icon", n_clicks=0),
                                                ],
                                                className="label-group",
                                            ),
                                            dbc.Switch(id="toggle-vyse", value=False, className="form-switch"),
                                        ],
                                        className="overlay-row",
                                    ),
                                ],
                                id="multi-engine-toggles",
                                style={"display": "none"},
                                className="mb-2",
                            ),
                            dcc.Store(id="multi-engine-toggle-options", data=[]),
                            html.Div(
                                [
                                    html.Label("Propeller Condition", className="input-label-sm", style={"marginBottom": "6px"}),
                                    dbc.ButtonGroup(
                                        [
                                            dbc.Button("Feathered",  id="btn-feathered",  className="segment-btn active", n_clicks=0),
                                            dbc.Button("Stationary", id="btn-stationary", className="segment-btn", n_clicks=0),
                                            dbc.Button("Windmilling", id="btn-windmilling", className="segment-btn", n_clicks=0),
                                        ],
                                        className="segment-control",
                                    ),
                                    dcc.Store(id="prop-condition", data="feathered"),
                                ],
                                id="prop-condition-container",
                                style={"display": "none"},
                            ),
                        ],
                        title="Overlay Options",
                        item_id="overlays",
                    ),

                    # Maneuver Overlays
                    dbc.AccordionItem(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label("Maneuver", className="input-label-sm"),
                                            html.Span("?", id="help-maneuver", className="help-icon", n_clicks=0),
                                        ],
                                        style={"display": "flex", "alignItems": "center", "marginBottom": "4px"},
                                    ),
                                    dcc.Dropdown(
                                        id="em-maneuver-select",
                                        className="dropdown",
                                        options=[
                                            {"label": "Steep Turn", "value": "steep_turn"},
                                            {"label": "Chandelle", "value": "chandelle"},
                                            {"label": "Lazy Eight", "value": "lazy_eight"},
                                        ],
                                        placeholder="Select a Maneuver",
                                        style={"width": "100%"},
                                    ),
                                ],
                                className="mb-2",
                            ),
                            html.Div(id="maneuver-options-container"),
                            html.Span("?", id="help-ghost", className="help-icon", n_clicks=0, style={"display": "none"}),
                        ],
                        title="Maneuver Overlays",
                        item_id="maneuvers",
                    ),
                ],
        id="sidebar-accordion",
        active_item=["config"],
        always_open=True,
        className="sidebar-accordion drawer-accordion",
    )


def _atmosphere_controls():
    """Phase 5AB-2 — atmosphere inputs inlined in the rail. Airport, altitude,
    OAT, altimeter are now directly editable without a popover round-trip.
    Replaces the old top-strip env chips. All component ids (airport-select,
    altitude-slider, oat-input, oat-fahrenheit-display, pa-da-display,
    altimeter-input, weather-panel) are preserved verbatim so every existing
    environment callback keeps wiring without changes."""
    return html.Div(
        [
            html.Div("Atmosphere", className="rail-section-title rail-live-controls-title"),

            # Airport — searchable dropdown. Phase 5AB-2b: options are loaded
            # lazily by `populate_airport_options` (callbacks/environment.py)
            # based on `search_value`. Initial payload is 0 options — was
            # ~49k options / 5.1 MB JSON shipping on every page load.
            html.Div(
                [
                    html.Label("Airport", className="input-label-sm rail-control-label"),
                    dcc.Dropdown(
                        id="airport-select",
                        options=[],
                        placeholder="Type ICAO or city…",
                        searchable=True,
                        clearable=True,
                        className="dropdown",
                    ),
                    html.Div(id="weather-panel", className="weather-panel"),
                ],
                className="rail-control-row",
            ),

            # Altitude (ft MSL) — slider; compact marks so the right edge fits
            html.Div(
                [
                    html.Label("Altitude (ft MSL)", className="input-label-sm rail-control-label"),
                    dcc.Slider(
                        id="altitude-slider",
                        min=0, max=35000, step=500, value=0,
                        marks={0: "SL", 10000: "10k", 20000: "20k", 30000: "30k"},
                        tooltip={"always_visible": True, "placement": "bottom"},
                    ),
                ],
                className="rail-control-row",
            ),

            # OAT — slider in °C (now matches the rest of the rail). The METAR
            # callback writes °C straight into `oat-input.value` so swapping
            # the component type from dcc.Input to dcc.Slider preserves wiring.
            # °F readout sits beside; PA / DA computed line below.
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("OAT", className="input-label-sm rail-control-label"),
                            html.Span(
                                [
                                    html.Span(id="oat-fahrenheit-display", children="59"),
                                    html.Span(" °F", className="oat-f-suffix"),
                                ],
                                className="oat-f-readout",
                            ),
                        ],
                        className="rail-control-label-row",
                    ),
                    dcc.Slider(
                        id="oat-input",
                        min=-40, max=50, step=1, value=15,
                        marks={-30: "-30", 0: "0", 15: "ISA", 30: "30", 50: "50"},
                        tooltip={"always_visible": True, "placement": "bottom"},
                    ),
                    html.Div(id="pa-da-display", className="pa-da-box mt-1"),
                ],
                className="rail-control-row",
            ),

            # Altimeter (inHg) — slider with STD-sea-level (29.92) anchor
            html.Div(
                [
                    html.Label("Altimeter (inHg)", className="input-label-sm rail-control-label"),
                    dcc.Slider(
                        id="altimeter-input",
                        min=28.0, max=31.0, step=0.01, value=29.92,
                        marks={28.5: "28.5", 29.92: "STD", 30.5: "30.5"},
                        tooltip={"always_visible": True, "placement": "bottom"},
                    ),
                ],
                className="rail-control-row",
            ),
        ],
        className="rail-live-controls rail-atmosphere",
    )


def _weight_controls():
    """Phase 5AB-4 — weight inputs live in the rail (between Atmosphere and
    Live Controls). They drive every derived V-speed and Ps calculation so
    keeping them visible alongside the chart matters. Engine / category /
    flap / gear stay in the drawer because those are truly configure-once.

    Phase 5AB-12: Total Weight display removed from the rail (redundant with
    the WEIGHT state tile in the top bar). A hidden div with id
    `total-weight-display` lives at the end of the rail so the callback
    that targets it still has somewhere to write.
    """
    return html.Div(
        [
            html.Div("Weight", className="rail-section-title rail-live-controls-title"),

            # Occupants + Occ Weight on one row
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Label("Occupants", className="input-label-sm rail-control-label"),
                            dcc.Dropdown(id="occupants-select", className="dropdown-small"),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            html.Label("Occ. Weight", className="input-label-sm rail-control-label"),
                            dcc.Input(
                                id="passenger-weight-input", type="number",
                                value=180, min=50, max=400, step=1,
                                className="input-small",
                                style={"width": "100%"},
                            ),
                        ],
                        width=6,
                    ),
                ],
                className="rail-control-row g-1",
            ),

            # Fuel slider — same id, marks set by callback
            html.Div(
                [
                    html.Label("Fuel (gal)", className="input-label-sm rail-control-label"),
                    dcc.Slider(
                        id="fuel-slider",
                        min=0, max=50, step=1, value=20, marks={},
                        tooltip={"always_visible": True, "placement": "bottom"},
                    ),
                ],
                className="rail-control-row",
            ),

            # Hidden target for the update_state Output("em-total-weight-display").
            # Visible readout moved to the WEIGHT state tile in the top bar.
            html.Div(id="em-total-weight-display", style={"display": "none"}),
        ],
        className="rail-live-controls rail-weight",
    )


def _live_controls():
    """Phase 5AA — live cockpit sliders that belong in the rail because they
    re-render the chart immediately and the user iterates on them constantly:
    Power, CG, Flight Path Angle. Engine / category / flap / gear stay in
    the drawer because those are truly configure-once."""
    return html.Div(
        [
            html.Div("Live Controls", className="rail-section-title rail-live-controls-title"),

            # Power setting
            html.Div(
                [
                    html.Label("Power", className="input-label-sm rail-control-label"),
                    dcc.Slider(
                        id="em-power-setting",
                        min=0.05, max=1.0, step=0.05, value=0.50,
                        marks={0.05: "IDLE", 0.4: "40%", 0.6: "60%", 0.8: "80%", 1: "100%"},
                        tooltip={"always_visible": True, "placement": "bottom"},
                    ),
                ],
                className="rail-control-row",
            ),

            # CG slider — wrapped div so the existing visibility callback still works
            html.Div(
                [
                    html.Label("CG (inches)", className="input-label-sm rail-control-label"),
                    dcc.Slider(id="em-cg-slider", min=0, max=1, value=0.5, step=0.01),
                ],
                id="cg-slider-container",
                className="rail-control-row",
            ),

            # Flight Path Angle
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Flight Path Angle", className="input-label-sm rail-control-label"),
                            html.Span("?", id="help-fpa", className="help-icon", n_clicks=0),
                        ],
                        style={"display": "flex", "alignItems": "center", "gap": "6px"},
                    ),
                    dcc.Slider(
                        id="pitch-angle",
                        min=-15, max=25, step=1, value=0,
                        marks={-15: "-15°", 0: "0°", 10: "10°", 25: "25°"},
                        tooltip={"always_visible": True, "placement": "bottom"},
                    ),
                ],
                className="rail-control-row",
            ),
        ],
        className="rail-live-controls",
    )


def _right_rail():
    """Phase 5O / 5AA — rail holds State Panel + Live Cockpit Controls +
    Configure trigger. Edit / Load aircraft moved into the drawer (CRUD
    operations don't belong in the live cockpit surface)."""
    return html.Div(
        [
            # Phase 5AB-13: rail header ("EM Diagram" title + collapse button)
            # removed. Brand identity already sits in the top strip; collapse
            # was unused given the drawer is the "more configure" home.

            # Phase 5AB-1: State Panel relocated to the top strip's row 2.
            # The div with id="state-panel" now lives in `_top_strip()`. Its
            # callback (callbacks.main.update_state_panel) targets the same id
            # so nothing on the callback side changes — only the host changed.
            # Definition popovers remain in the rail tree; dbc.Popover positions
            # against `target=` id regardless of DOM ancestry.

            # Phase 5V-2: definition popovers, one per state card. Click any
            # card to read what it means + the formula / reg reference.
            *_state_card_popovers(),

            # Phase 5AB-2 — atmosphere inputs (formerly top-strip env chips)
            _atmosphere_controls(),

            # Phase 5AB-4 — weight inputs (formerly drawer accordion)
            _weight_controls(),

            # Phase 5AA — live cockpit controls
            _live_controls(),

            # Drawer trigger — full-width chip styled the same way
            html.Button(
                [
                    html.Span("MORE", className="chip-prefix"),
                    html.Span("Configure", className="chip-label"),
                ],
                id="open-drawer-btn",
                n_clicks=0,
                className="env-chip rail-action-chip rail-drawer-trigger",
                type="button",
                title="Open configuration panel (shortcut: D)",
                **{"aria-label": "Open configuration panel — overlays, maneuvers, aircraft config"},
            ),
        ],
        id="right-rail",
        className="right-rail",
    )


def _settings_drawer():
    """Right-edge slide-out drawer. Phase 5AA: opens with Edit/Load aircraft
    chips at the top (CRUD ops, out of the cockpit surface), then the full
    accordion (Aircraft Configuration / Overlay Options / Maneuver Overlays).
    Toggled by `open-drawer-btn` in the rail; close button + backdrop click
    both dismiss it."""
    return dbc.Offcanvas(
        [
            # Phase 5AA — Aircraft CRUD chips at the top of the drawer.
            dbc.Row(
                [
                    dbc.Col(
                        html.Button(
                            [
                                html.Span("EDIT", className="chip-prefix"),
                                html.Span("Edit / Create", className="chip-label"),
                            ],
                            id="edit-aircraft-button",
                            n_clicks=0,
                            className="env-chip rail-action-chip",
                            type="button",
                            title="Open the aircraft editor",
                        ),
                        width=6,
                    ),
                    dbc.Col(
                        dcc.Upload(
                            id="em-upload-aircraft",
                            children=html.Button(
                                [
                                    html.Span("LOAD", className="chip-prefix"),
                                    html.Span("Aircraft File", className="chip-label"),
                                ],
                                className="env-chip rail-action-chip",
                                type="button",
                                title="Load an aircraft JSON file",
                            ),
                            multiple=False,
                            accept=".json",
                            className="w-100",
                        ),
                        width=6,
                    ),
                ],
                className="mb-3 g-1 drawer-crud-row",
            ),
            _settings_accordion(),
        ],
        id="settings-drawer",
        title="Configuration",
        # Phase 5AD: drawer slides in from the LEFT, same side as its trigger
        # (the MORE Configure button at the bottom of the left rail).
        placement="start",
        is_open=False,
        backdrop=True,
        scrollable=True,
        className="settings-drawer",
    )


def _chart_area():
    """Chart and below-graph legal footer. Chart fills the column.
    Phase 5Z adds a tab strip to swap between the Maneuver Doghouse
    (Boyd 1966) and the Energy Map h-V plane (Rutowski 1954 / AFH Ch 4)."""
    _graph_config = {
        "staticPlot": False,
        "displaylogo": False,
        "displayModeBar": False,
        "responsive": True,
        "scrollZoom": False,
    }
    _initial_figure = {"layout": {"paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)", "autosize": True, "hovermode": "closest"}}
    return html.Div(
        [
            # Phase 5Z — chart tab strip
            html.Div(
                [
                    html.Button(
                        [html.Span("MANEUVER",  className="chip-prefix"),
                         html.Span("Doghouse",  className="chip-label")],
                        id="tab-chart-maneuver",
                        n_clicks=0,
                        className="env-chip chart-tab chart-tab-active",
                        type="button",
                        title="Boyd 1966 maneuver diagram — turn rate vs IAS (shortcut: M)",
                        **{"aria-label": "Show maneuver doghouse chart"},
                    ),
                    # Phase 5AB-5: Compare chip relocated from top strip and
                    # placed adjacent to the Doghouse tab — comparison overlays
                    # render on the doghouse, not the energy map.
                    html.Button(
                        [
                            html.Span("VS", className="chip-prefix"),
                            html.Span("Compare", id="chip-compare-label", className="chip-label"),
                        ],
                        id="chip-compare",
                        n_clicks=0,
                        className="env-chip chart-tab",
                        type="button",
                        title="Compare against another aircraft on the Doghouse (shortcut: C)",
                        **{"aria-label": "Add a second aircraft to compare envelopes"},
                    ),
                    html.Button(
                        [html.Span("ENERGY", className="chip-prefix"),
                         html.Span("Map h-V",  className="chip-label")],
                        id="tab-chart-hv",
                        n_clicks=0,
                        className="env-chip chart-tab",
                        type="button",
                        title="Rutowski 1954 / AFH Ch 4 — altitude vs IAS with constant-energy curves (shortcut: H)",
                        **{"aria-label": "Show energy-map h-V chart"},
                    ),
                    # Phase 5AE: chart-tab Store relocated to app.py so the
                    # mobile layout can reference it without errors.

                    # Phase 5AA-click: Drop-target mode toggle. Default OFF —
                    # clicks on the h-V chart move the current state. When ON,
                    # clicks drop a target instead. Tap the chip to flip.
                    html.Button(
                        [html.Span("MODE", className="chip-prefix"),
                         html.Span("Drop target", className="chip-label")],
                        id="toggle-target-mode",
                        n_clicks=0,
                        className="env-chip chart-tab",
                        type="button",
                        title="Toggle click-mode: move current state (default) ↔ drop target",
                        **{"aria-label": "Toggle h-V click mode between move-current-state and drop-target"},
                    ),

                    # Phase 5W: REACH chip cycles OFF → 60s → 120s → 300s.
                    # When set, the h-V chart shades the (V, h) region you
                    # can reach within that time given current power for the
                    # upper E bound and idle/drag for the lower E bound.
                    html.Button(
                        [html.Span("REACH", className="chip-prefix"),
                         html.Span("Off", id="chip-reach-label", className="chip-label")],
                        id="toggle-reach",
                        n_clicks=0,
                        className="env-chip chart-tab",
                        type="button",
                        title="Energy-budget reachable set: where could I be in N seconds?",
                        **{"aria-label": "Cycle reachable-set time horizon"},
                    ),

                    # Phase 5X: MARGINS chip — swap hard envelope lines for
                    # shaded bands that reflect typical real-world variance
                    # (stall ±5 KIAS, ceiling ±500 ft). Vne stays hard.
                    html.Button(
                        [html.Span("MARGINS", className="chip-prefix"),
                         html.Span("Off", id="chip-margins-label", className="chip-label")],
                        id="toggle-margins",
                        n_clicks=0,
                        className="env-chip chart-tab",
                        type="button",
                        title="Show envelope margins (stall band, ceiling band) — reminds you these limits have real-world variance",
                        **{"aria-label": "Toggle envelope margin bands"},
                    ),

                    # Phase 5Z-2: Clear-target chip, hidden by default. Shows
                    # only when a target point is set on the h-V chart.
                    html.Button(
                        [html.Span("CLEAR", className="chip-prefix"),
                         html.Span("Target", className="chip-label")],
                        id="clear-hv-target",
                        n_clicks=0,
                        className="env-chip chart-tab",
                        type="button",
                        style={"display": "none"},
                        title="Clear the h-V chart's target point",
                        **{"aria-label": "Clear the energy-map target point"},
                    ),

                    # Phase 5AC: Clear-probe chip — hidden by default; visible
                    # only on the doghouse when a probe is set.
                    html.Button(
                        [html.Span("CLEAR", className="chip-prefix"),
                         html.Span("Probe", className="chip-label")],
                        id="clear-doghouse-probe",
                        n_clicks=0,
                        className="env-chip chart-tab",
                        type="button",
                        style={"display": "none"},
                        title="Clear the doghouse scenario probe",
                        **{"aria-label": "Clear the doghouse scenario probe"},
                    ),
                ],
                className="chart-tabs",
            ),
            html.Div(
                [
                    dcc.Graph(
                        id="em-graph",
                        config=_graph_config,
                        figure=_initial_figure,
                        className="dash-graph",
                        style={"display": "block", "height": "100%", "width": "100%"},
                    ),
                    # Phase 5Z — second graph, hidden by default. Tab switch
                    # toggles inline display style which is more reliable
                    # than className swaps for dcc.Graph in Dash 3.
                    dcc.Graph(
                        id="em-graph-hv",
                        config=_graph_config,
                        figure=_initial_figure,
                        className="dash-graph",
                        style={"display": "none"},
                    ),
                ],
                className="graph-panel",
            ),
            html.Div(
                [
                    html.Span("Full Legal Disclaimer", id="em-open-disclaimer", className="legal-link"),
                    html.Span("|", className="separator"),
                    html.Span("Terms of Use & Privacy Policy", id="em-open-terms-policy", className="legal-link"),
                    html.Span("|", className="separator"),
                    html.Span("© 2026 Nicholas Len, TallyAero. All rights reserved.", className="legal-copyright"),
                ],
                className="legal-links",
            ),
        ],
        className="chart-area",
    )


def desktop_layout():
    return html.Div(
        [
            _top_strip(),
            html.Div(
                [
                    # Phase 5AD: rail moved to the LEFT so the set-then-see
                    # reading order aligns with the aircraft picker (top-left)
                    # and chart-tabs (top-left of the chart row). HTML order
                    # leads with rail; CSS grid widths match.
                    _right_rail(),
                    _chart_area(),
                ],
                className="main-grid",
            ),
            _settings_drawer(),
        ],
        className="full-height-container desktop-shell",
    )
