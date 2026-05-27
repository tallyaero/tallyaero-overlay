"""Desktop layout (>= 768px viewport).

Composes the sidebar + map column for the desktop UI. The per-maneuver
parameter forms in layouts/maneuvers/ are injected at runtime by the
`render_maneuver_layout` callback (which still lives in app.py for now;
Phase 1e will move it to callbacks/aircraft.py).

Pure functions; no callbacks.

Also hosts `_top_strip` / `_modals_block` / `_reset_buttons_row` since those are
layout helpers shared by every per-maneuver form in layouts/maneuvers/.
The deferred imports inside each maneuver layout that used
`from app import _reset_buttons_row` get cleaned up in the same commit
to point at this module instead.
"""

from __future__ import annotations

import os

from dash import dcc, html
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.data_loader import available_aircraft


# OpenAIP aeronautical-overlay tile API key. Read from env at module
# load. When absent, the OpenAIP overlay TileLayer is mounted with
# opacity 0 + a no-op URL, and the chart-layer picker hides the
# OpenAIP option so users don't see broken tiles.
_OPENAIP_KEY = (os.environ.get("TALLYAERO_OPENAIP_KEY") or "").strip()
_OPENAIP_TILE_URL = (
    f"https://api.tiles.openaip.net/api/data/openaip/"
    "{z}/{x}/{y}.png" + (f"?apiKey={_OPENAIP_KEY}" if _OPENAIP_KEY else "")
)
_HAVE_OPENAIP = bool(_OPENAIP_KEY)


# D3-3: Auto-detect self-hosted FAA chart tile pyramids. The app.py
# Flask route serves /tiles/<layer>/<z>/<x>/<y>.png from the repo's
# `tiles/<layer>/` directory. We check at module load whether each
# layer's directory exists + has any tile files, and only expose
# picker options for layers the user has actually generated.
_TILES_BASE = (os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                 + "/tiles")
def _have_layer(layer: str) -> bool:
    layer_dir = os.path.join(_TILES_BASE, layer)
    if not os.path.isdir(layer_dir):
        return False
    # Cheap check: any zoom-level subdir present.
    try:
        for entry in os.listdir(layer_dir):
            if entry.isdigit():
                return True
    except OSError:
        return False
    return False

_HAVE_SECTIONAL = _have_layer("sectional")
_HAVE_TAC = _have_layer("tac")
_HAVE_IFR_LOW = _have_layer("ifrlow")

# 1×1 transparent PNG data URI. Used as the TileLayer URL for chart
# layers the user HASN'T generated yet — Leaflet still creates tile
# DOM elements for mounted TileLayers (opacity is purely cosmetic;
# tiles get fetched regardless), so we point at this no-op to avoid
# 404/500 spam on every pan/zoom for layers with no source data.
_BLANK_TILE_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0"
    "C8AAAAASUVORK5CYII="
)

def _layer_url(layer: str, available: bool) -> str:
    return (f"/tiles/{layer}/" + "{z}/{x}/{y}.png") if available else _BLANK_TILE_DATA_URI


def _top_strip():
    """Phase 4 — single consolidated top bar.

    LEFT  : brand · aircraft picker · MANEUVER picker · ? info button.
    RIGHT : status text · Reset / Undo · Quick Start · Contact · theme.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Span("TallyAero Overlay", className="top-strip-brand"),
                    # Phase 3b: tool-context switcher. Links between
                    # the route-planner (overlay, /) and the EM diagram
                    # (/em). dcc.Link renders without a page reload —
                    # the unified router callback swaps page-content
                    # based on url.pathname.
                    html.Div(
                        [
                            dcc.Link("Overlay", href="/",
                                     className="tool-switcher-link tool-switcher-active"),
                            dcc.Link("EM Diagram", href="/em",
                                     className="tool-switcher-link"),
                        ],
                        className="tool-switcher",
                    ),
                    html.Div(
                        dcc.Dropdown(
                            id="aircraft-select",
                            options=[{"label": name, "value": name} for name in available_aircraft],
                            value="C172" if "C172" in available_aircraft else (available_aircraft[0] if available_aircraft else None),
                            placeholder="Select an aircraft",
                            className="dropdown aircraft-dropdown",
                            clearable=False,
                            persistence=True, persistence_type="local",
                        ),
                        className="aircraft-picker-wrap",
                    ),

                    # Airport — text input + Recenter, floating results below.
                    # The input itself displays the selected airport after pick;
                    # selected-airport-display is kept hidden (callbacks still
                    # write to it but it doesn't render visibly).
                    html.Div([
                        html.Span("APT", className="chip-prefix"),
                        dcc.Input(
                            id="airport-search-input",
                            type="text",
                            value="",
                            placeholder="ICAO / name",
                            debounce=False,
                            className="topbar-airport-input",
                            autoComplete="off",
                        ),
                        html.Button("Recenter", id="recenter-airport-btn",
                                    className="topbar-airport-recenter",
                                    title="Recenter map on airport"),
                        html.Div(id="airport-search-results",
                                 className="search-results-box topbar-airport-results"),
                        html.Div(id="selected-airport-display", style={"display": "none"}),
                    ], className="topbar-airport-wrap"),

                    # Maneuver picker + Info button — moved up from the shelf
                    html.Div([
                        html.Span("MANEUVER", className="chip-prefix"),
                        dcc.Dropdown(
                            id="maneuver-select",
                            className="chip-dropdown",
                            placeholder="Select maneuver",
                            options=[
                                {"label": "Route Planner", "value": "route"},
                                {"label": "Pattern", "value": "pattern"},
                                {"label": "Impossible Turn", "value": "impossible_turn"},
                                {"label": "Power-Off 180", "value": "poweroff180"},
                                {"label": "Engine-Out Glide", "value": "engineout"},
                                {"label": "Steep Turns", "value": "steep_turn"},
                                {"label": "Chandelle", "value": "chandelle"},
                                {"label": "Lazy Eight", "value": "lazy8"},
                                {"label": "Steep Spiral", "value": "steep_spiral"},
                                {"label": "S-Turns", "value": "s_turn"},
                                {"label": "Turns Around a Point", "value": "turns_point"},
                                {"label": "Rectangular Course", "value": "rect_course"},
                                {"label": "Eights on Pylons", "value": "pylons"},
                            ],
                            clearable=False,
                            persistence=True, persistence_type="local",
                        ),
                        html.Button("?", id="open-maneuver-info", n_clicks=0,
                                    className="shelf-info-btn",
                                    title="What is this maneuver?"),
                    ], className="maneuver-shelf-picker"),

                    # Stores the latest computed route for later use
                    dcc.Store(id="route-result-store", data=None),

                    # Maneuver info modal stays mounted (toggled by callback)
                    dbc.Modal(
                        [
                            dbc.ModalHeader(dbc.ModalTitle(id="maneuver-info-title"), close_button=True),
                            dbc.ModalBody(id="maneuver-info-body"),
                            dbc.ModalFooter(dbc.Button("Close", id="close-maneuver-info", className="green-button")),
                        ],
                        id="maneuver-info-modal",
                        is_open=False,
                        centered=True,
                        size="md",
                        dialogClassName="tallyaero-modal",
                    ),
                ],
                className="top-strip-left",
            ),
            html.Div(
                [
                    _top_menu(),
                ],
                className="top-strip-right",
            ),
        ],
        className="top-strip",
    )


def _modals_block():
    """Quick-Start / Disclaimer / Terms modals. Pulled out of the old
    legal_banner_block so the top-strip stays thin. Modals stay in the
    DOM so the existing open-quickstart / disclaimer-modal callbacks
    keep wiring."""
    return html.Div(
        children=[

            # Quick Start Modal
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Maneuver Overlay Tool - Quick Start"), close_button=True),
                    dbc.ModalBody([
                        html.H5("What is this tool?", style={"color": "#E65C00", "marginBottom": "10px"}),
                        html.P("The Maneuver Overlay Tool visualizes aircraft maneuvers on real satellite imagery. "
                               "It calculates flight paths using actual aircraft performance data and physics-based simulations."),

                        html.H5("Who is it for?", style={"color": "#E65C00", "marginTop": "20px", "marginBottom": "10px"}),
                        html.Ul([
                            html.Li([html.Strong("Student Pilots: "), "Visualize maneuvers before flying them. Understand how wind, weight, and configuration affect your flight path."]),
                            html.Li([html.Strong("Flight Instructors: "), "Use as a briefing tool to demonstrate maneuver geometry, energy management, and decision points."]),
                            html.Li([html.Strong("Checkride Prep: "), "Practice planning Power-Off 180s, Steep Turns, Chandelles, and other ACS maneuvers with realistic parameters."]),
                        ], style={"marginBottom": "15px"}),

                        html.H5("How to Use", style={"color": "#E65C00", "marginTop": "20px", "marginBottom": "10px"}),
                        html.Ol([
                            html.Li([html.Strong("Select Aircraft"), " - Choose your aircraft from the dropdown. Performance data is loaded automatically."]),
                            html.Li([html.Strong("Search Airport"), " - Type an ICAO code or name, then click to center the map."]),
                            html.Li([html.Strong("Set Conditions"), " - Adjust weight, wind, and temperature in the sidebar."]),
                            html.Li([html.Strong("Choose Maneuver"), " - Select from Impossible Turn, Power-Off 180, Steep Turns, and more."]),
                            html.Li([html.Strong("Click the Map"), " - Set start/end points as prompted, then click Draw to visualize."]),
                        ], style={"marginBottom": "15px"}),

                        html.H5("Available Maneuvers", style={"color": "#E65C00", "marginTop": "20px", "marginBottom": "10px"}),
                        html.Ul([
                            html.Li([html.Strong("Route Planner"), " - Cross-country leg with terrain conflict, engine-out corridor, and nav log."]),
                            html.Li([html.Strong("Impossible Turn"), " - Engine failure after takeoff: can you make it back?"]),
                            html.Li([html.Strong("Power-Off 180"), " - Accuracy approach from abeam the touchdown point."]),
                            html.Li([html.Strong("Engine-Out Glide"), " - Best-glide reach to a chosen touchdown spot."]),
                            html.Li([html.Strong("Steep Turns"), " - 45°/50° bank turns with load factor and stall margin."]),
                            html.Li([html.Strong("Chandelle"), " - Maximum-performance climbing 180° turn."]),
                            html.Li([html.Strong("Lazy Eight"), " - Symmetrical climbing/descending S with oscillating altitude."]),
                            html.Li([html.Strong("Steep Spiral"), " - Constant-radius descending orbit; idle power; bank modulates with wind."]),
                            html.Li([html.Strong("S-Turns"), " - Equal semicircles across a road, perpendicular to wind."]),
                            html.Li([html.Strong("Turns Around a Point"), " - Constant-radius orbit around a point; bank modulates with GS."]),
                            html.Li([html.Strong("Rectangular Course"), " - Wind-corrected rectangle around a field."]),
                            html.Li([html.Strong("Eights on Pylons"), " - Figure-8 with the wingtip pinned on each pylon at pivotal altitude."]),
                        ], style={"marginBottom": "15px"}),

                        html.Div([
                            html.Strong("Remember: "),
                            "This is an educational tool. Always verify with your aircraft's POH and use good judgment in the aircraft."
                        ], style={"backgroundColor": "#fff3cd", "padding": "10px", "borderRadius": "4px", "marginTop": "15px"}),
                    ]),
                    dbc.ModalFooter(dbc.Button("Got It!", id="close-quickstart", className="green-button")),
                ],
                id="quickstart-modal",
                is_open=False,
                centered=True,
                size="lg",
                dialogClassName="tallyaero-modal",
                scrollable=True,
            ),

            dbc.Modal(
                [
                    dbc.ModalHeader("TallyAero Disclaimer", close_button=True),
                    dbc.ModalBody(
                        [
                            html.P("This tool supplements, not replaces, FAA published documentation."),
                            html.P("It is intended for educational and reference use only and has not been approved or endorsed by the Federal Aviation Administration (FAA)."),
                            html.P("Do not use this tool for flight planning, aircraft operation, or regulatory compliance decisions."),
                            html.P("Outputs may be incomplete, inaccurate, outdated, or derived from public or user-provided inputs. No warranties are made regarding accuracy, completeness, or fitness for purpose."),
                            html.P("If any information conflicts with the aircraft FAA-approved AFM or POH, the official documentation shall govern."),
                            html.P("TallyAero disclaims liability for errors, omissions, injuries, damages, or losses resulting from use of this application."),
                        ]
                    ),
                    dbc.ModalFooter(dbc.Button("Close", id="close-disclaimer", className="green-button")),
                ],
                id="disclaimer-modal",
                is_open=False,
                centered=True,
                size="lg",
                dialogClassName="tallyaero-modal",
                backdrop="static",
                scrollable=True,
            ),

            dbc.Modal(
                [
                    dbc.ModalHeader("Terms of Use & Privacy Policy", close_button=True),
                    dbc.ModalBody(
                        [
                            html.H6("Terms of Use", className="mb-2 mt-2"),
                            html.P("Use is for educational and informational purposes only. This tool is not FAA-certified."),
                            html.P("Verify all performance and procedural information using the POH or AFM and applicable regulations. Use is at your own risk."),
                            html.H6("Privacy Policy", className="mb-2 mt-4"),
                            html.P("No user accounts are required. The app does not intentionally collect personally identifiable information for functionality."),
                            html.P("Hosting providers may log basic operational metadata such as IP address, timestamps, and user agent for security and reliability."),
                        ]
                    ),
                    dbc.ModalFooter(dbc.Button("Close", id="close-terms-policy", className="green-button")),
                ],
                id="terms-policy-modal",
                is_open=False,
                centered=True,
                size="lg",
                dialogClassName="tallyaero-modal",
                backdrop="static",
                scrollable=True,
            ),

            # Print trigger sink — clientside print callback writes
            # a timestamp here so the Input/Output graph is clean
            # (Dash dislikes a clientside callback whose Output equals
            # its Input).
            dcc.Store(id="nav-log-print-sink", data=0),

            # === Navigation Log Modal (Phase 9-polish) ===
            # FAA-style nav log populated by the route compute callback.
            # Designed for screen review and printing — the body uses
            # the standard checkpoint table format pilots fill in
            # during flight planning.
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle("Navigation Log"),
                        close_button=True,
                    ),
                    dbc.ModalBody(
                        id="nav-log-content",
                        className="nav-log-body",
                    ),
                    dbc.ModalFooter([
                        dbc.Button("Print", id="nav-log-print-btn",
                                   className="green-button",
                                   n_clicks=0),
                        dbc.Button("Close", id="nav-log-close-btn",
                                   className="green-button"),
                    ]),
                ],
                id="nav-log-modal",
                size="xl",
                dialogClassName="tallyaero-modal nav-log-modal",
                backdrop=True,
                scrollable=True,
                is_open=False,
            ),
        ]
    )


def _reset_buttons_row():
    """Deprecated — Reset / Undo buttons now live in the top
    maneuver_action_shelf. Returns an empty Div so the existing per-
    maneuver layout call sites stay valid without duplicating the
    button IDs."""
    return html.Div(style={"display": "none"})


def _theme_toggle():
    """3-button theme toggle (Phase 4 mirror of EM Diagram). The hidden
    `theme-btn-auto` stays in the DOM so the cycleTheme clientside
    callback's 3-input signature keeps wiring; user-facing toggle is
    light vs dark only."""
    return html.Div(
        [
            html.Div(
                [
                    html.Button("Light", id="theme-btn-light", className="theme-btn active", title="Light mode"),
                    html.Button("Dark",  id="theme-btn-dark",  className="theme-btn",        title="Dark mode"),
                ],
                className="theme-toggle-group",
                **{"data-role": "theme-toggle"},
            ),
            html.Button("", id="theme-btn-auto", n_clicks=0, style={"display": "none"}),
        ],
        className="theme-toggle-wrap",
    )


def _top_menu():
    """Consolidated top-right dropdown — Edit/Create, Load File, Quick
    Start, Contact, and the Light/Dark theme toggle. Replaces the
    separate links + inline theme buttons that used to live in
    top-strip-right and the Edit/Load buttons that lived in the
    sidebar bottom. All callback-bearing ids (open-quickstart,
    upload-aircraft, theme-btn-*) are preserved so the existing
    callbacks wire without changes."""
    return dbc.DropdownMenu(
        label="Menu",
        align_end=True,
        in_navbar=False,
        toggleClassName="top-menu-toggle",
        className="top-menu",
        direction="down",
        menu_variant=None,
        children=[
            dbc.DropdownMenuItem(
                "Edit / Create",
                href="https://app.flyaeroedge.com/edit-aircraft",
                target="_blank",
                external_link=True,
            ),
            html.Div(
                dcc.Upload(
                    html.Div("Load File…", className="top-menu-upload-label"),
                    id="upload-aircraft",
                    accept=".json",
                    className="top-menu-upload",
                ),
                className="top-menu-upload-wrap",
            ),
            dbc.DropdownMenuItem(divider=True),
            dbc.DropdownMenuItem(
                "Quick Start",
                id="open-quickstart",
                n_clicks=0,
                style={"color": "#E65C00", "fontWeight": "600"},
            ),
            dbc.DropdownMenuItem(
                "Contact",
                href="mailto:info@tallyaero.com",
                external_link=True,
            ),
            dbc.DropdownMenuItem(divider=True),
            html.Div(
                [
                    html.Span("Theme", className="top-menu-section-label"),
                    _theme_toggle(),
                ],
                className="top-menu-theme-row",
            ),
        ],
    )


def _maneuver_action_shelf():
    """Single thin row that only appears when a maneuver is selected —
    holds the per-maneuver params + Set Point / Draw / Erase buttons.
    The picker, info button, reset/undo controls, and status text all
    live in the consolidated top strip above this."""
    return html.Div(
        id="maneuver-params-container",
        className="maneuver-shelf maneuver-shelf-params",
    )


def desktop_layout():
    """Desktop layout — Phase 4 Batch 2a shell.

    full-height-container > top-strip + main-grid + modals. The
    main-grid keeps the existing sidebar + map split intact (Batch 2b
    will promote aircraft picker into top-strip and add env chips;
    Batch 2c moves the rail content into a slide-out drawer).
    """
    return html.Div(className="full-height-container desktop-shell", children=[
        _top_strip(),
        _maneuver_action_shelf(),
        _modals_block(),
        # Main 2-column layout (sidebar + map) — wraps in main-grid so
        # the CSS can target it with the new shell rules.
        html.Div(className="main-row main-grid", children=[
            # === Sidebar ===
            html.Div(id="sidebar", className="resizable-sidebar", children=[
                html.Div(id="sidebar-content", children=[

                # Hidden stores for keyboard navigation (used by airport search)
                dcc.Store(id="airport-highlight-index", data=0),
                dcc.Store(id="airport-search-matches", data=[]),

                # === Aircraft sub-config (picker lives in the top bar) ===
                html.Div(className="sidebar-section", children=[
                    html.Div(className="sidebar-section-header", children=[
                        html.Div("Aircraft", className="sidebar-section-title"),
                        html.Button(
                            "«",
                            id="sidebar-collapse-btn",
                            className="sidebar-collapse-btn",
                            title="Collapse sidebar",
                        ),
                    ]),
                    html.Label("Engine", className="input-label-sm"),
                    dcc.Dropdown(id="engine-select", className="dropdown", persistence=True, persistence_type="local"),
                ]),

                # === Environment section (airport moved to top bar) ===
                html.Div(className="sidebar-section", children=[
                    html.Div([
                        html.Span("Environment", className="sidebar-section-title"),
                        # Live/manual wind-source badge — written by the
                        # `update_wind_source_chip` callback when the
                        # METAR / wind-profile stores change OR the user
                        # edits the wind inputs. Always visible right
                        # next to the section title so the pilot can see
                        # at a glance whether the figures came from a
                        # live METAR pull or were typed by hand.
                        html.Span("MANUAL", id="wind-source-chip",
                                  className="wind-source-chip wind-source-chip-manual"),
                    ], style={"display": "flex", "alignItems": "center",
                              "justifyContent": "space-between", "gap": "6px"}),
                    html.Div(style={"display": "flex", "gap": "8px"}, children=[
                        html.Div([
                            html.Label("Wind °", className="input-label-sm"),
                            dcc.Input(id="env-wind-dir", type="number", value=360, min=1, max=360,
                                      className="input-small", style={"width": "100%"},
                                      persistence=True, persistence_type="local"),
                        ], style={"flex": "1"}),
                        html.Div([
                            html.Label("Speed (kt)", className="input-label-sm"),
                            dcc.Input(id="env-wind-speed", type="number", value=0, min=0,
                                      className="input-small", style={"width": "100%"},
                                      persistence=True, persistence_type="local"),
                        ], style={"flex": "1"}),
                    ]),

                    html.Div(id="sidebar-thermo-row",
                             style={"display": "flex", "gap": "8px", "marginTop": "8px"},
                             children=[
                        html.Div([
                            html.Label("OAT (°F)", className="input-label-sm"),
                            dcc.Input(id="env-oat", type="number", value=52,
                                      className="input-small", style={"width": "100%"},
                                      persistence=True, persistence_type="local"),
                        ], style={"flex": "1"}),
                        html.Div([
                            html.Label("Altim (inHg)", className="input-label-sm"),
                            dcc.Input(id="env-altimeter", type="number", value=29.92, step=0.01,
                                      className="input-small", style={"width": "100%"},
                                      persistence=True, persistence_type="local"),
                        ], style={"flex": "1"}),
                    ]),

                    html.Div(id="sidebar-agl-wrap", children=[
                        html.Div(id="env-airport-agl", className="weight-box",
                                 style={"marginTop": "8px", "fontSize": "11px"}),
                    ]),

                    # Live weather panel (METAR + winds aloft column).
                    # Populated when an airport pick succeeds; empty
                    # otherwise so the section collapses to zero height.
                    html.Div(id="sidebar-live-weather"),
                ]),

                # === Weight & CG section ===
                html.Div(className="sidebar-section", children=[
                    html.Div("Weight & CG", className="sidebar-section-title"),
                    html.Div(style={"display": "flex", "gap": "8px"}, children=[
                        html.Div([
                            html.Label("Occupants", className="input-label-sm"),
                            dcc.Input(id="occupants", type="number", value=1, min=1, max=4,
                                      className="input-small", style={"width": "100%"},
                                      persistence=True, persistence_type="local"),
                        ], style={"flex": "1"}),
                        html.Div([
                            html.Label("Occ. Wt (lb)", className="input-label-sm"),
                            dcc.Input(id="occupant-weight", type="number", value=180, min=100, max=300,
                                      className="input-small", style={"width": "100%"},
                                      persistence=True, persistence_type="local"),
                        ], style={"flex": "1"}),
                    ]),
                    html.Label("Fuel Load (gal)", className="input-label-sm", style={"marginTop": "10px"}),
                    dcc.Slider(
                        id="fuel-load", min=0, max=50, step=1, value=0,
                        marks={0: "0", 12: "1/4", 25: "1/2", 37: "3/4", 50: "Full"},
                        tooltip={"always_visible": True},
                        persistence=True, persistence_type="local",
                    ),
                    html.Div(id="sidebar-cg-block", children=[
                        html.Label("CG Position", className="input-label-sm", style={"marginTop": "10px"}),
                        dcc.Slider(
                            id="cg-slider", min=0.0, max=1.0, step=0.01, value=0.5,
                            marks={0.0: "FWD", 0.5: "MID", 1.0: "AFT"},
                            tooltip={"always_visible": True},
                            persistence=True, persistence_type="local",
                        ),
                    ]),
                    html.Label("Total Weight", className="input-label-sm", style={"marginTop": "10px"}),
                    dcc.Input(id="total-weight-display", type="text", value="", readOnly=True,
                              className="input-small", style={"width": "100%"}),
                ]),

                # === Maneuver picker + params moved to the top shelf ===

                # === Power section ===
                html.Div(id="sidebar-power-section",
                         className="sidebar-section", children=[
                    html.Div("Power", className="sidebar-section-title"),
                    dcc.Slider(
                        id="power-setting",
                        min=0.05, max=1.0, step=0.05, value=0.5,
                        marks={0.05: "IDLE", 0.5: "50%", 0.99: "100%"},
                        tooltip={"always_visible": True},
                        persistence=True, persistence_type="local",
                    ),
                ]),

                # --- Maneuver params moved to the top shelf ---

                # Store for tracking last clicked point (for undo)
                dcc.Store(id="last-click-info", data=None),
            ]),  # End sidebar-content

            # Store for sidebar collapse state
            dcc.Store(id="sidebar-collapsed-store", data=False),
        ]),

        # === Map Column ===
        html.Div(id="engineout-click-status", style={"display": "none"}),

        html.Div(className="graph-column",
                 style={
                     "display": "flex",
                     "flexDirection": "column",
                     # 56px top-strip + ~56px shelf-row + small breathing
                     # room. Was 180px (oversized) which left ~50px of
                     # dead vertical space below the map.
                     "height": "calc(100vh - 120px)",
                 },
                 children=[

            # Route summary banner — full-width, sits ABOVE the map
            # and pushes it down. Carries the score + headline +
            # condensed factor row. Empty until a route is computed.
            # Wrapped in dcc.Loading so the user sees a spinner during
            # the 5-30s compute instead of being left guessing.
            dcc.Loading(
                children=html.Div(id="route-top-banner"),
                type="default",
                color="#0d59f2",
                delay_show=200,
            ),

            # Map wrapper — flex-grows to fill whatever's left between
            # the banner and the below-strip. position:relative keeps
            # the absolute-positioned map-controls-overlay anchored to
            # the visible map area.
            html.Div(
                style={
                    "flex": "1 1 auto",
                    "minHeight": "300px",
                    "position": "relative",
                },
                children=[
                    # Map-overlay controls — Reset/Undo float over the map
                    # top-right, just left of the windsock. Hidden for
                    # Route Planner via callbacks/sidebar.py (no click-
                    # to-set points in routing).
                    html.Div(id="map-controls-overlay",
                             className="map-controls-overlay",
                             children=[
                        # Active-maneuver action buttons (Set X / Draw /
                        # Results) — rendered by `render_maneuver_actions`
                        # based on the current maneuver-select value.
                        # Lives above the Reset row so the user sees the
                        # forward-progress actions first, with the
                        # housekeeping actions below.
                        # Glide Ring toggle lives here permanently so
                        # the engine-out auto-draw callback can use
                        # this id as a stable string-id Input. CSS
                        # hides it when the active maneuver isn't
                        # engineout (see #glide-ring-toggle-wrap
                        # rules in assets/styles.css).
                        html.Div(
                            dcc.Checklist(
                                id="engineout-show-envelope",
                                options=[{"label": "Glide Ring", "value": "show"}],
                                value=[],
                                className="shelf-toggle-chip-checklist",
                            ),
                            id="glide-ring-toggle-wrap",
                            className="shelf-toggle-chip",
                            title="Toggle the reachable-glide envelope ring overlay.",
                        ),
                        # Phase 7f-C — airspace overlay toggle. Permanent
                        # mount; CSS hides it when the active maneuver
                        # isn't 'route' via the .overlay-for-route class
                        # the reflector callback writes onto the parent
                        # map-controls-overlay.
                        html.Div(
                            dcc.Checklist(
                                id="route-show-airspace",
                                options=[
                                    {"label": "Class B/C/D", "value": "class"},
                                    {"label": "SUA", "value": "sua"},
                                    {"label": "TFR", "value": "tfr"},
                                ],
                                value=["class", "sua", "tfr"],
                                className="airspace-toggle-list shelf-toggle-chip-checklist",
                                inline=True,
                            ),
                            id="airspace-toggle-wrap",
                            className="shelf-toggle-chip airspace-toggle-chip",
                            title=("Show NASR airspace polygons on the map "
                                   "(Class B/C/D, SUA, standing TFRs)."),
                        ),
                        # Phase 7N-e — VOR / fix overlay toggle. Same
                        # always-mount + CSS-gated pattern as the
                        # airspace toggle. Both default ON; the zoom
                        # gates inside render_waypoints_overlay keep
                        # the map readable until the user zooms in
                        # (VORs ≥ z7, fixes ≥ z9).
                        html.Div(
                            dcc.Checklist(
                                id="route-show-waypoints",
                                options=[
                                    {"label": "VORs", "value": "vor"},
                                    {"label": "Fixes", "value": "fix"},
                                ],
                                value=["vor", "fix"],
                                className="waypoints-toggle-list "
                                          "shelf-toggle-chip-checklist",
                                inline=True,
                            ),
                            id="waypoints-toggle-wrap",
                            className="shelf-toggle-chip waypoints-toggle-chip",
                            title=("Show NASR NAVAIDs + intersections as map "
                                   "dots (zoom in to see fixes). Click any "
                                   "dot in Click-to-add mode to drop a "
                                   "waypoint there."),
                        ),
                        # Chart layer picker. Picker shows whichever
                        # combinations of (a) OpenAIP key + (b) self-
                        # hosted tile pyramids are available at
                        # startup. Hidden entirely when neither.
                        # "Sat" = imagery only. "+ OpenAIP" = aero
                        # data overlay on top. "Sectional"/"TAC"/
                        # "IFR Lo" = self-hosted FAA chart base
                        # (replaces imagery underneath).
                        html.Div(
                            dcc.RadioItems(
                                id="map-chart-layer",
                                options=[
                                    {"label": "Sat", "value": "imagery"},
                                    *([{"label": "+ OpenAIP",
                                         "value": "openaip"}]
                                      if _HAVE_OPENAIP else []),
                                    *([{"label": "Sectional",
                                         "value": "sectional"}]
                                      if _HAVE_SECTIONAL else []),
                                    *([{"label": "TAC",
                                         "value": "tac"}]
                                      if _HAVE_TAC else []),
                                    *([{"label": "IFR Lo",
                                         "value": "ifrlow"}]
                                      if _HAVE_IFR_LOW else []),
                                ],
                                value="imagery",
                                className="chart-layer-list shelf-toggle-chip-checklist",
                                inline=True,
                            ),
                            id="chart-layer-wrap",
                            className="shelf-toggle-chip chart-layer-chip",
                            style={
                                "display": "inline-flex" if (
                                    _HAVE_OPENAIP or _HAVE_SECTIONAL
                                    or _HAVE_TAC or _HAVE_IFR_LOW
                                ) else "none"
                            },
                            title=("Switch map base. Sat = satellite "
                                   "imagery. + OpenAIP overlays "
                                   "airspaces/airports/navaids. "
                                   "Sectional/TAC/IFR Lo = self-hosted "
                                   "FAA charts (gdal2tiles pyramids "
                                   "under ./tiles/)."),
                        ),
                        # Airports overlay toggle — gives the pilot a
                        # way to declutter when other layers (airspace,
                        # waypoints, glide ring) make the map noisy.
                        # Default ON. Sub-options let the pilot keep
                        # only their preferred airport categories.
                        html.Div(
                            dcc.Checklist(
                                id="map-show-airports",
                                options=[
                                    {"label": "Large", "value": "large"},
                                    {"label": "Med", "value": "medium"},
                                    {"label": "Small", "value": "small"},
                                    {"label": "Seaplane", "value": "seaplane"},
                                ],
                                # Default: only large + medium on at
                                # the global view — small airports
                                # carpet the map until zoomed in.
                                value=["large", "medium", "small"],
                                className="airports-toggle-list shelf-toggle-chip-checklist",
                                inline=True,
                            ),
                            id="airports-toggle-wrap",
                            className="shelf-toggle-chip airports-toggle-chip",
                            title=("Show airport markers on the map by "
                                   "category. Uncheck any category to "
                                   "declutter. Small airports only "
                                   "render at zoom 8+ for performance."),
                        ),
                        html.Div(id="maneuver-actions-container",
                                 className="map-overlay-actions"),
                        html.Div(className="map-overlay-divider"),
                        html.Button("Reset All", id="reset-all", className="map-overlay-btn"),
                        html.Button("Reset Clicks", id="reset-clicks", className="map-overlay-btn"),
                        html.Button("Undo", id="undo-last-click", className="map-overlay-btn map-overlay-btn-undo"),
                    ]),

                    # Bottom-right corner toggle for the below-strip
                    # (View Nav Log button + wind + profile chart).
                    # Sits OUTSIDE the strip so the strip can fully
                    # hide when collapsed — no floating chevron, no
                    # peeking-through artifacts. Always visible
                    # regardless of the strip's state so the pilot
                    # can bring the strip back when they want it.
                    html.Button(
                        "▼ Info",
                        id="route-below-collapse-btn",
                        className="route-below-collapse-corner-btn",
                        title="Collapse / expand the info bar at the bottom of the screen",
                        n_clicks=0,
                    ),

                    dl.Map(
                        id="map",
                        # CONUS overview at boot — geographic center
                        # of the lower 48 is roughly Lebanon, KS
                        # (~39.83°N, 98.58°W). Zoom 4 fits the
                        # continental US comfortably in a 16:9 viewport;
                        # auto-zoom takes over after Compute Route.
                        center=[39.83, -98.58],
                        zoom=4,
                        style={"width": "100%", "height": "100%"},
                        children=[
                            # Single base layer. dash-leaflet 1.0.15's
                            # LayersControl errors out at runtime when sibling
                            # LayerGroups in this same dl.Map are updated by
                            # callbacks (the layer / scrubber-layer / route-layer
                            # children below). When OpenAIP key + sectional tiles
                            # land, the LayersControl wrapper returns with the
                            # known-good child shape.
                            # Base imagery — Esri World Imagery.
                            # Always-on, opacity stays at 1.
                            dl.TileLayer(
                                id="map-tile-imagery",
                                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                                attribution="Tiles &copy; Esri",
                            ),
                            # OpenAIP aeronautical overlay — TRANSPARENT
                            # PNG with airspaces / airports / navaids /
                            # nav fixes / restricted areas drawn over a
                            # null background. Sits on top of imagery
                            # when the user picks "OpenAIP" in the
                            # chart picker; opacity flipped 0/1 by the
                            # switch_chart_layer callback. URL carries
                            # the API key from $TALLYAERO_OPENAIP_KEY;
                            # if the key is missing, the URL still
                            # mounts (just won't return tiles).
                            dl.TileLayer(
                                id="map-tile-openaip",
                                url=_OPENAIP_TILE_URL,
                                attribution=("Aeronautical data &copy; "
                                             "OpenAIP"),
                                opacity=0,
                                maxZoom=14,
                            ),
                            # Self-hosted FAA chart layers (D3-3).
                            # URL points at the Flask tile route in
                            # app.py when tiles exist; otherwise at a
                            # no-op data URI so Leaflet's tile fetcher
                            # doesn't generate 404 spam for layers the
                            # user hasn't generated yet.
                            dl.TileLayer(
                                id="map-tile-vfrsec",
                                url=_layer_url("sectional", _HAVE_SECTIONAL),
                                attribution=("Sectional &copy; FAA — "
                                             "self-hosted"),
                                opacity=0,
                                maxZoom=12,
                            ),
                            dl.TileLayer(
                                id="map-tile-tac",
                                url=_layer_url("tac", _HAVE_TAC),
                                attribution=("TAC &copy; FAA — "
                                             "self-hosted"),
                                opacity=0,
                                maxZoom=13,
                            ),
                            dl.TileLayer(
                                id="map-tile-ifrlow",
                                url=_layer_url("ifrlow", _HAVE_IFR_LOW),
                                attribution=("IFR Low &copy; FAA — "
                                             "self-hosted"),
                                opacity=0,
                                maxZoom=11,
                            ),
                            # Engine-out glide ring lives in its own
                            # layer so the toggle can auto-draw it
                            # without touching the main `layer` that
                            # carries the simulated path + markers.
                            dl.LayerGroup(id="envelope-layer"),
                            # Phase 7f-follow — airspace polygons
                            # (Class B/C/D, SUA, TFRs). Rendered
                            # below the route + path layers so it
                            # acts as a backdrop, not a foreground.
                            dl.LayerGroup(id="airspace-layer"),
                            # Phase 7N-e — NAVAID + fix point markers
                            # (toggle-on layer, zoom-gated). Sits above
                            # airspace but below the active path so a
                            # VOR symbol doesn't get hidden under a
                            # Class B fill.
                            dl.LayerGroup(id="waypoints-layer"),
                            # Airports overlay (always-mounted) — driven
                            # by `map-show-airports` checklist + map
                            # bounds + zoom. Categories: large / medium
                            # / small / heliport / seaplane.
                            dl.LayerGroup(id="airports-layer"),
                            dl.LayerGroup(id="layer"),
                            dl.LayerGroup(id="scrubber-layer"),  # Dedicated layer for time scrubber marker
                            dl.LayerGroup(id="route-layer"),     # Phase 5 — great-circle route
                            dl.LayerGroup(id="route-pending-markers"),  # 7N — pre-Compute waypoint dots
                            # Engine-out drill layer — rendered on top of
                            # route-layer when the user scrubs along the
                            # route in "Engine-out drill" mode. Cleared
                            # when the drill is toggled off or the route
                            # is recomputed.
                            dl.LayerGroup(id="route-engineout-layer"),
                            # Destination VFR pattern — auto-drawn at
                            # the route's destination airport. Rendered
                            # by its own callback (decoupled from the
                            # main route-compute callback) so changing
                            # the runway / pill / wind doesn't trigger
                            # a full route rebuild and doesn't create a
                            # dependency cycle.
                            dl.LayerGroup(id="route-dest-pattern-layer"),
                            # VFR checkpoint diamonds + labels —
                            # rendered by the checkpoint callback.
                            dl.LayerGroup(id="route-checkpoints-layer"),
                            dl.ScaleControl(position="bottomleft", imperial=True, metric=False),  # Scale bar - JS converts to NM
                            # Windsock indicator overlay - default 360@0kt (calm), updated by callback
                            html.Div(
                                id="windsock-overlay",
                                style={
                                    "position": "absolute",
                                    "top": "10px",
                                    "right": "10px",
                                    "zIndex": "1010",
                                    "backgroundColor": "rgba(255,255,255,0.9)",
                                    "padding": "4px 10px",
                                    "borderRadius": "6px",
                                    "boxShadow": "0 2px 6px rgba(0,0,0,0.2)",
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "6px",
                                    "fontFamily": "'Inter', sans-serif",
                                    "minWidth": "130px",
                                    "minHeight": "60px",
                                },
                                children=[
                                    html.Div(
                                        html.Iframe(
                                            srcDoc='''<html><body style="margin:0;padding:0;overflow:hidden;background:transparent;">
                                            <svg width="60" height="60" viewBox="0 0 60 60" style="transform: rotate(-30deg); transform-origin: 30px 30px;">
                                                <circle cx="30" cy="30" r="2.5" fill="#666"/>
                                                <line x1="30" y1="30" x2="35" y2="30" stroke="#666" stroke-width="2"/>
                                                <polygon points="35,26 40,26.6 40,33.4 35,34" fill="#FF6600" stroke="#CC5500" stroke-width="0.5"/>
                                                <polygon points="40,26.6 45,27.2 45,32.8 40,33.4" fill="#FF6600" stroke="#CC5500" stroke-width="0.5"/>
                                                <polygon points="45,27.2 50,27.8 50,32.2 45,32.8" fill="#FF6600" stroke="#CC5500" stroke-width="0.5"/>
                                            </svg>
                                            </body></html>''',
                                            style={"width": "60px", "height": "60px", "border": "none", "overflow": "hidden", "background": "transparent"}
                                        ),
                                        style={"width": "60px", "height": "60px", "flexShrink": "0"}
                                    ),
                                    html.Span(
                                        "360° @ 0 kt",
                                        style={
                                            "fontSize": "12px",
                                            "fontWeight": "600",
                                            "color": "#333",
                                            "whiteSpace": "nowrap",
                                        }
                                    ),
                                ]
                            ),
                        ]
                    )
                ]
            ),

            # Route detail strip — sits BELOW the map. Carries the
            # factor list, divert block, terrain block, wind, profile
            # chart. Populated by the route compute callback; empty
            # until a route is computed.
            #
            # Collapsible — the user wanted maximum map interactive
            # area. Chevron button on the right edge flips
            # `route-below-strip-wrap.className` between expanded and
            # collapsed; CSS does the rest. State persists via the
            # `route-below-collapsed-store` so the bar's state survives
            # recomputes.
            html.Div(
                id="route-below-strip-wrap",
                className="route-below-strip-wrap",
                children=[
                    dcc.Loading(
                        children=html.Div(id="route-below-strip"),
                        type="default",
                        color="#0d59f2",
                        delay_show=200,
                    ),
                ],
            ),
            dcc.Store(id="route-below-collapsed-store", data=False,
                       storage_type="local"),

            html.Div(id="click_debug", style={
                "padding": "10px 12px",
                "fontStyle": "italic",
                "color": "#555",
                "backgroundColor": "#fff",
                "borderTop": "1px solid #ccc"
            }),

            # ===== Maneuver-scoped point stores (no shared state between maneuvers) =====

            dcc.Store(id="runtime-total-weight-lb"),

            # Phase H · live weather staged on airport-pick. Sims read
            # the wind-profile-store to do per-tick wind lookup; the
            # active-metar-store carries the parsed observation so any
            # surface that wants to display it (chip / tooltip) can.
            dcc.Store(id="wind-profile-store", data=None),
            dcc.Store(id="active-metar-store", data=None),

            # Power-Off 180 (touchdown only; start is auto-generated but keep for future flexibility)
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "start"}),

            # Engine-Out Glide
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "start"}),
            # Mirror stores for engine-out form fields. The glide-ring
            # callback needs to react to altitude/flap/prop/td-elev
            # changes, but those components only exist in the DOM while
            # the engine-out maneuver is mounted — so we can't State
            # them directly. A small bridging callback mirrors their
            # values into these always-present stores; the glide-ring
            # callback then States the mirrors.
            dcc.Store(id="engineout-altitude-mirror", data=5000.0),
            dcc.Store(id="engineout-flap-mirror", data="clean"),
            dcc.Store(id="engineout-prop-mirror", data="idle"),
            dcc.Store(id="engineout-td-elev-mirror", data=None),

            # Steep Turns
            dcc.Store(id={"type": "point-store", "m_id": "steep_turn", "role": "start"}),

            # Chandelle
            dcc.Store(id={"type": "point-store", "m_id": "chandelle", "role": "start"}),

            # Lazy Eight
            dcc.Store(id={"type": "point-store", "m_id": "lazy8", "role": "start"}),

            # Steep Spiral (reference point only - entry calculated from aircraft physics)
            dcc.Store(id={"type": "point-store", "m_id": "steep_spiral", "role": "ref"}),

            # S-Turns (ref = reference point on line, bearing = second point to define line direction)
            dcc.Store(id={"type": "point-store", "m_id": "s_turn", "role": "ref"}),
            dcc.Store(id={"type": "point-store", "m_id": "s_turn", "role": "bearing"}),
            dcc.Store(id="sturn-calculated-bearing"),  # Store for calculated bearing value

            # Turns Around a Point (center point)
            dcc.Store(id={"type": "point-store", "m_id": "turns_point", "role": "center"}),

            # Rectangular Course — pilot clicks the 4 corners; the
            # rectcourse-corner-store callback snaps them to a perfect
            # rectangle. Legacy dw_start/dw_end roles kept so an old
            # click pattern still routes (just unused now).
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "c1"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "c2"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "c3"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "c4"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "dw_start"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "dw_end"}),

            # Eights on Pylons (two pylons)
            dcc.Store(id={"type": "point-store", "m_id": "pylons", "role": "pylon_a"}),
            dcc.Store(id={"type": "point-store", "m_id": "pylons", "role": "pylon_b"}),
            # Pylons parameter stores (always present for click handler callback)
            dcc.Store(id="pylons-ias-store", data=100),
            dcc.Store(id="pylons-bank-store", data=30),

            # Impossible Turn (start only)
            dcc.Store(id={"type": "point-store", "m_id": "impossible_turn", "role": "start"}),
            dcc.Store(id="active-click-target"),
            dcc.Store(id="selected-airport-id", storage_type="local"),

            # Rectangular course calculated edge (needs to be in main layout for callback)
            dcc.Store(id="rectcourse-calculated-edge", data={}),
            # Hidden display element for callback (visible version in rect_course_layout)
            html.Div(id="rectcourse-edge-info-display", style={"display": "none"}),
            # Downwind-edge selection store — mirrored from the shelf
            # dropdown (rectcourse-downwind-edge-select) when rect_course
            # is the active maneuver. Lives in the always-present layout
            # so the snap callback can read it from any maneuver context
            # without raising "nonexistent object" errors.
            dcc.Store(id="rectcourse-downwind-edge", data="auto"),
            # Snap-to-rectangle output: written by the 4-corner preview
            # callback whenever any of the corner stores change. Same
            # reason as `rectcourse-downwind-edge` — the snap callback's
            # Inputs are the corner point-stores (always present), so
            # the Output target must also live here to remain valid in
            # every maneuver context.
            dcc.Store(id="rectcourse-snapped-store", data={}),
            # Engine-out drill stores — mirrored from the route shelf's
            # pill + slider (only mounted when Route Planner is active).
            # The drill rendering callback's Inputs are these stores so
            # it stays valid in every maneuver context.
            dcc.Store(id="route-engineout-drill", data=[]),
            dcc.Store(id="route-engineout-slider", data=0),
            # Destination runway override store — mirrored from
            # `route-runway-select-ui` in the route shelf. Same trick
            # as `rectcourse-downwind-edge`: the dropdown only exists
            # when the route shelf is mounted, but the compute callback
            # needs the value as an Input from any context.
            dcc.Store(id="route-runway-select", data=None),
            # Dest-pattern pill state mirror — same pattern. Default
            # "on" matches the pill's default_on=True.
            dcc.Store(id="route-show-destination-pattern", data=["on"]),
            # Checkpoints pill state mirror.
            dcc.Store(id="route-show-checkpoints", data=["on"]),
            # User-drag overrides for individual VFR checkpoints.
            # Shape: {"<original_ident>": {"lat": float, "lon": float}}.
            # Populated by the click-to-place flow when the pilot
            # clicks a checkpoint marker then clicks the map at a
            # new position. compute_and_render reads this and
            # overrides the auto-picked checkpoint position.
            dcc.Store(id="route-checkpoint-edits", data={}, storage_type="memory"),
            # Which checkpoint ident is currently in "click to place"
            # edit mode. None = no edit mode. Set when a marker is
            # clicked; cleared after the next map click writes the
            # new position into route-checkpoint-edits.
            dcc.Store(id="route-checkpoint-edit-active", data=None, storage_type="memory"),

            html.Div(
                [
                    html.Span("Full Legal Disclaimer", id="open-disclaimer", className="legal-link"),
                    html.Span("|", className="separator"),
                    html.Span("Terms of Use & Privacy Policy", id="open-terms-policy", className="legal-link"),
                    html.Span("|", className="separator"),
                    html.Span("© 2026 Nicholas Len, TallyAero. All rights reserved.", className="legal-copyright"),
                ],
                className="legal-links",
            )
        ])
    ])
])
