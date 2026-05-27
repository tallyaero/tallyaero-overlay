"""
TallyAero EM Diagram — mobile layout.

Phase 5AF rewrite. The previous version was the legacy "everything in a
single collapse" approach which left the user buried under config inputs
before they could even see the chart. This version mirrors the desktop
information hierarchy:

    1. Top bar: brand + aircraft picker + settings button
    2. State tiles strip (horizontal-scroll on overflow)
    3. Chart-tabs row (Doghouse / Energy)
    4. Chart (60vh)
    5. Bottom toolbar (PNG/PDF + legal)
    6. Settings drawer (Offcanvas slides up from bottom)

All component ids align with the desktop layout's callbacks so the same
update_graph / state-panel / figure_hv code paths render correctly on
mobile. Pure function: no callbacks, no side effects.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


# Common graph config + initial figure used by both em-graph and em-graph-hv.
_GRAPH_CONFIG = {
    "staticPlot": False,
    "displaylogo": False,
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": False,
}
_INITIAL_FIGURE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor":  "rgba(0,0,0,0)",
        "autosize": True,
        "hovermode": "closest",
        "dragmode": False,
        "xaxis": {"fixedrange": True},
        "yaxis": {"fixedrange": True},
    }
}


def _top_bar():
    """Slim top header: hamburger on the left opens the settings drawer;
    aircraft picker takes the rest of the row. Brand is sub-rowed below
    so the picker has full horizontal width."""
    return html.Div(
        [
            html.Div([
                html.Button("☰", id="em-mobile-settings-toggle",
                            className="mobile-hamburger",
                            **{"aria-label": "Open settings drawer"}),
                html.Div(
                    dcc.Dropdown(
                        id="em-aircraft-select", options=[],
                        placeholder="Select Aircraft…",
                        className="dropdown",
                        clearable=False,
                    ),
                    className="mobile-aircraft-picker",
                ),
            ], className="mobile-top-row"),
        ],
        className="mobile-top-bar",
    )


def _state_tiles_strip():
    """Horizontal-scrollable strip of state info — populated by the same
    `update_state_panel` callback that drives the desktop top bar."""
    return html.Div(
        html.Div(id="state-panel", className="state-panel state-panel-strip mobile-state-strip"),
        className="mobile-state-tiles-wrap",
    )


def _chart_tabs():
    """Doghouse / Energy tab buttons. Shared callback `_swap_chart_tab` reads
    these clicks; this layout omits the desktop-only chips (Compare, REACH,
    MARGINS, etc.) — those stay as hidden placeholders."""
    return html.Div(
        [
            html.Button(
                [html.Span("MANEUVER", className="chip-prefix"),
                 html.Span("Doghouse", className="chip-label")],
                id="tab-chart-maneuver", n_clicks=0,
                className="env-chip chart-tab chart-tab-active",
                type="button",
            ),
            html.Button(
                [html.Span("ENERGY", className="chip-prefix"),
                 html.Span("Map h-V", className="chip-label")],
                id="tab-chart-hv", n_clicks=0,
                className="env-chip chart-tab",
                type="button",
            ),
        ],
        className="chart-tabs mobile-chart-tabs",
    )


def _chart_area():
    """Container for both em-graph and em-graph-hv. _swap_chart_tab toggles
    display between them."""
    return html.Div(
        [
            dcc.Graph(
                id="em-graph",
                config=_GRAPH_CONFIG,
                figure=_INITIAL_FIGURE,
                className="dash-graph mobile-graph",
                style={"display": "block", "height": "60vh", "width": "100%"},
            ),
            dcc.Graph(
                id="em-graph-hv",
                config=_GRAPH_CONFIG,
                figure=_INITIAL_FIGURE,
                className="dash-graph mobile-graph",
                style={"display": "none", "height": "60vh", "width": "100%"},
            ),
        ],
        className="mobile-graph-container",
    )


def _settings_drawer():
    """Bottom-sliding offcanvas drawer holding all the config inputs.
    Lazier than the desktop drawer (single column, no accordion); the
    user opens, fiddles, closes.

    Phase 5AF-4: Edit/Create + Load action buttons moved to the bottom
    of the drawer — they're configure-once destructive actions that
    shouldn't compete with the live tuning controls for top attention.
    """
    return dbc.Offcanvas(
        [
            # Aircraft Configuration
            html.Div("Aircraft", className="mobile-section-title"),
            html.Div([
                html.Label("Engine", className="input-label-sm"),
                dcc.Dropdown(id="em-engine-select", className="dropdown"),
            ], className="mb-2"),
            html.Div([
                html.Label("Category", className="input-label-sm"),
                dcc.Dropdown(id="category-select", className="dropdown"),
            ], className="mb-2"),
            html.Div([
                html.Label("Flap Configuration", className="input-label-sm"),
                dcc.Dropdown(id="config-select", className="dropdown"),
            ], className="mb-2"),
            html.Div([
                html.Label("Landing Gear", className="input-label-sm"),
                dcc.Dropdown(id="gear-select", className="dropdown"),
            ], id="gear-select-container", className="mb-2", style={"display": "none"}),

            # Weight
            html.Div("Weight", className="mobile-section-title"),
            html.Div([
                html.Label("Occupants", className="input-label-sm"),
                dcc.Dropdown(id="occupants-select", className="dropdown"),
            ], className="mb-2"),
            html.Div([
                html.Label("Occupant Weight (lb)", className="input-label-sm"),
                dcc.Input(id="passenger-weight-input", type="number",
                          value=180, min=50, max=400, step=1,
                          className="input-small w-100"),
            ], className="mb-2"),
            html.Div([
                html.Label("Fuel (gal)", className="input-label-sm"),
                dcc.Slider(id="fuel-slider", min=0, max=50, step=1, value=20, marks={},
                           tooltip={"always_visible": True, "placement": "bottom"}),
            ], className="mb-3"),

            # Atmosphere
            html.Div("Atmosphere", className="mobile-section-title"),
            html.Div([
                html.Label("Airport", className="input-label-sm"),
                dcc.Dropdown(
                    id="airport-select", options=[],
                    placeholder="Type ICAO or city…",
                    searchable=True, clearable=True,
                    className="dropdown",
                ),
                html.Div(id="weather-panel", className="weather-panel weather-panel-mobile"),
            ], className="mb-2"),
            html.Div([
                html.Label("Altitude (ft MSL)", className="input-label-sm"),
                dcc.Slider(id="altitude-slider", min=0, max=35000, step=500, value=0,
                           marks={0: "SL", 10000: "10k", 20000: "20k", 30000: "30k"},
                           tooltip={"always_visible": True, "placement": "bottom"}),
            ], className="mb-3"),
            html.Div([
                html.Label("OAT (°C)", className="input-label-sm"),
                dcc.Slider(id="oat-input", min=-40, max=50, step=1, value=15,
                           marks={-30: "-30", 0: "0", 15: "ISA", 30: "30", 50: "50"},
                           tooltip={"always_visible": True, "placement": "bottom"}),
                # The °F readout target — driven by update_oat_fahrenheit callback
                html.Div([html.Span(id="oat-fahrenheit-display", children="59"),
                          html.Span(" °F", className="oat-f-suffix")],
                         className="oat-f-readout text-end small"),
            ], className="mb-2"),
            html.Div(id="pa-da-display", className="pa-da-box small text-muted mb-3"),
            html.Div([
                html.Label("Altimeter (inHg)", className="input-label-sm"),
                dcc.Slider(id="altimeter-input", min=28.0, max=31.0, step=0.01, value=29.92,
                           marks={28.5: "28.5", 29.92: "STD", 30.5: "30.5"},
                           tooltip={"always_visible": True, "placement": "bottom"}),
            ], className="mb-3"),

            # Live Controls
            html.Div("Live Controls", className="mobile-section-title"),
            html.Div([
                html.Label("Power", className="input-label-sm"),
                dcc.Slider(id="em-power-setting", min=0.05, max=1.0, step=0.05, value=0.50,
                           marks={0.05: "IDLE", 0.5: "50%", 1: "100%"},
                           tooltip={"always_visible": True, "placement": "bottom"}),
            ], className="mb-3"),
            html.Div([
                html.Label("CG (inches)", className="input-label-sm"),
                dcc.Slider(id="em-cg-slider", min=0, max=1, value=0.5, step=0.01),
            ], id="cg-slider-container", className="mb-3"),
            html.Div([
                html.Label("Flight Path Angle", className="input-label-sm"),
                dcc.Slider(id="pitch-angle", min=-15, max=25, step=1, value=0,
                           marks={-15: "-15°", 0: "0°", 25: "25°"},
                           tooltip={"always_visible": True, "placement": "bottom"}),
            ], className="mb-3"),

            # Units + Display
            html.Div("Display", className="mobile-section-title"),
            dbc.RadioItems(id="unit-select",
                           options=[{"label": "KIAS", "value": "KIAS"},
                                    {"label": "MPH",  "value": "MPH"}],
                           value="KIAS", inline=True, className="mb-2"),
            dcc.Checklist(
                id="mobile-overlay-checklist",
                options=[
                    {"label": "Ps Contours",      "value": "ps"},
                    {"label": "G-load Lines",     "value": "g"},
                    {"label": "Turn Radius",      "value": "radius"},
                    {"label": "Angle of Bank",    "value": "aob"},
                    {"label": "Negative G",       "value": "negative_g"},
                    {"label": "Dynamic Vmc",      "value": "vmca"},
                    {"label": "Dynamic Vyse",     "value": "vyse"},
                ],
                value=["g", "radius", "aob"],
                className="mb-2",
            ),
            dcc.Store(id="overlay-toggle", data=["g", "radius", "aob"]),

            # Multi-engine (OEI sim) — shown only for multi-engine aircraft
            html.Div([
                dcc.Checklist(id="oei-toggle",
                              options=[{"label": "Simulate OEI", "value": "enabled"}],
                              value=[], inline=True),
            ], id="oei-container", className="mb-2"),
            html.Div([
                dcc.Checklist(id="multi-engine-toggle-options",
                              options=[{"label": "Dynamic Vmc",  "value": "vmca"},
                                       {"label": "Dynamic Vyse", "value": "vyse"}],
                              value=[], inline=True),
            ], id="multi-engine-toggles", style={"display": "none"}),
            html.Div([
                dcc.RadioItems(id="prop-condition",
                               options=[{"label": "Feathered",   "value": "feathered"},
                                        {"label": "Stationary",  "value": "stationary"},
                                        {"label": "Windmilling", "value": "windmilling"}],
                               value="feathered", inline=True),
            ], id="prop-condition-container", style={"display": "none"}),

            # Maneuver picker
            html.Div("Maneuvers", className="mobile-section-title"),
            html.Div([
                dcc.Dropdown(id="em-maneuver-select",
                             options=[{"label": "Steep Turn", "value": "steep_turn"},
                                      {"label": "Chandelle",  "value": "chandelle"}],
                             placeholder="None"),
            ], className="mb-2"),
            html.Div(id="maneuver-options-container"),

            # ── Aircraft CRUD actions (bottom of drawer per Phase 5AF-4) ──
            html.Hr(style={"margin": "16px 0 12px"}),
            html.Div("Aircraft File", className="mobile-section-title"),
            html.Div([
                dbc.Button("Edit / Create Aircraft", id="edit-aircraft-button",
                           className="w-100 mb-2", size="sm", color="primary"),
                dcc.Upload(id="em-upload-aircraft",
                           children=dbc.Button("Load Aircraft File",
                                               className="w-100", size="sm",
                                               color="secondary"),
                           multiple=False, accept=".json"),
            ]),

            # Total weight (hidden — used as a callback target)
            html.Div(id="em-total-weight-display", style={"display": "none"}),
            html.Div(id="config-details", style={"display": "block"}),
        ],
        id="mobile-settings-drawer",
        title="Settings",
        # Phase 5AF: drawer slides in from the LEFT (matches the desktop
        # rail position) so users have a consistent mental model of
        # "controls live on the left" across breakpoints.
        placement="start",
        is_open=False,
        backdrop=True,
        scrollable=True,
        className="mobile-settings-drawer",
    )


def _hidden_desktop_placeholders():
    """Hidden DOM nodes that satisfy desktop-only callback Output targets
    on the mobile page. None of these affect mobile rendering — they exist
    purely so Dash's layout validator doesn't error on missing-id."""
    return html.Div([
        # Desktop overlay switches (mobile uses checklist instead)
        dbc.Switch(id="toggle-ps",         value=False, style={"display": "none"}),
        dbc.Switch(id="toggle-g",          value=True,  style={"display": "none"}),
        dbc.Switch(id="toggle-radius",     value=True,  style={"display": "none"}),
        dbc.Switch(id="toggle-aob",        value=True,  style={"display": "none"}),
        dbc.Switch(id="toggle-negative-g", value=False, style={"display": "none"}),
        dbc.Switch(id="toggle-vmca",       value=False, style={"display": "none"}),
        dbc.Switch(id="toggle-vyse",       value=False, style={"display": "none"}),

        # Desktop unit buttons (mobile uses RadioItems)
        html.Button("KIAS", id="btn-kias", style={"display": "none"}),
        html.Button("MPH",  id="btn-mph",  style={"display": "none"}),

        # Desktop prop condition buttons (mobile uses RadioItems)
        html.Button("Feathered",   id="btn-feathered",   style={"display": "none"}),
        html.Button("Stationary",  id="btn-stationary",  style={"display": "none"}),
        html.Button("Windmilling", id="btn-windmilling", style={"display": "none"}),

        # Help-bubble icons (desktop popovers)
        *[html.Span(id=hid, style={"display": "none"}) for hid in (
            "help-fpa", "help-ps", "help-g", "help-radius", "help-aob",
            "help-negative-g", "help-dvmc", "help-dvyse", "help-maneuver",
            "help-ghost",
        )],

        # Drawer accordion (desktop drawer's category nav)
        dbc.Accordion(id="sidebar-accordion", style={"display": "none"}),

        # State-card popover triggers (desktop has clickable definition cards)
        *[html.Div(id=f"state-card-{slug}", style={"display": "none"})
          for slug in ("weight", "vs1g", "va", "vne", "vno", "glim", "ke", "pe", "e")],

        # Desktop chart-tabs row chips (mobile has only the two tab buttons)
        html.Button(id="chip-compare",        style={"display": "none"}),
        html.Span  (id="chip-compare-label",  style={"display": "none"}),
        dcc.Dropdown(id="aircraft-compare-select", options=[], style={"display": "none"}),
        html.Button(id="toggle-target-mode",  style={"display": "none"}),
        html.Button(id="toggle-reach",        style={"display": "none"}),
        html.Span  (id="chip-reach-label",    style={"display": "none"}),
        html.Button(id="toggle-margins",      style={"display": "none"}),
        html.Span  (id="chip-margins-label",  style={"display": "none"}),
        html.Button(id="clear-hv-target",     style={"display": "none"}),
        html.Button(id="clear-doghouse-probe", style={"display": "none"}),
        html.Button(id="open-drawer-btn",     style={"display": "none"}),
        dbc.Offcanvas(id="settings-drawer",   is_open=False, style={"display": "none"}),
    ], style={"display": "none"})


def mobile_layout():
    """Top-level mobile entrypoint — assembles the structured layout."""
    return html.Div(
        [
            _top_bar(),
            _state_tiles_strip(),
            _chart_tabs(),
            _chart_area(),

            # Bottom toolbar
            html.Div(
                [
                    html.Button("PNG", id="png-button", className="btn-export-sm"),
                    html.Button("PDF", id="pdf-button", className="btn-export-sm"),
                    dcc.Download(id="png-download"),
                    dcc.Download(id="pdf-download"),
                    html.Span(" ", className="ms-auto"),
                    html.Span("Quick Start", id="open-readme",
                              className="quick-link link-blue mobile-quick"),
                ],
                className="mobile-bottom-bar",
            ),

            # Legal footer
            html.Div(
                [
                    html.Span("Disclaimer", id="em-open-disclaimer", className="legal-link-sm"),
                    html.Span(" · ", style={"color": "var(--ta-text-tertiary, #999)"}),
                    html.Span("Terms", id="em-open-terms-policy", className="legal-link-sm"),
                    html.Span(" · ", style={"color": "var(--ta-text-tertiary, #999)"}),
                    html.A("Contact", href="mailto:info@tallyaero.com",
                           className="legal-link-sm"),
                    html.Span(" · © 2026 TallyAero",
                              style={"color": "var(--ta-text-tertiary, #999)",
                                     "fontSize": "9px"}),
                ],
                className="mobile-legal",
            ),

            _settings_drawer(),
            _hidden_desktop_placeholders(),
        ],
        className="mobile-container",
    )
