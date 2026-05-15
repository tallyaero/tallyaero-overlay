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

from dash import dcc, html
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.data_loader import available_aircraft


def _top_strip():
    """Phase 4 Batch 2b — brand + aircraft picker on the left, quick-links
    + theme toggle on the right. Mirrors EM Diagram's current top-strip
    pattern (env chips live inline in the rail per Phase 5AB-2, not here)."""
    return html.Div(
        [
            html.Div(
                [
                    html.Span("TallyAero Overlay", className="top-strip-brand"),
                    html.Div(
                        dcc.Dropdown(
                            id="aircraft-select",
                            options=[{"label": name, "value": name} for name in available_aircraft],
                            value="C172" if "C172" in available_aircraft else (available_aircraft[0] if available_aircraft else None),
                            placeholder="Select an aircraft…",
                            className="dropdown aircraft-dropdown",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                        ),
                        className="aircraft-picker-wrap",
                    ),
                ],
                className="top-strip-left",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.A("Quick Start", href="#", id="open-quickstart", className="quick-link", style={"color": "#E65C00", "fontWeight": "bold"}),
                            html.Span(" · ", className="quick-link-sep"),
                            html.A("EM Diagram", href="https://app.flyaeroedge.com/", target="_blank", className="quick-link", style={"color": "#28a745", "fontWeight": "bold"}),
                            html.Span(" · ", className="quick-link-sep"),
                            html.A("Report Error", href="https://forms.gle/VX6CA1ugifAtmBM79", target="_blank", className="quick-link", style={"color": "#dc3545"}),
                            html.Span(" · ", className="quick-link-sep"),
                            html.A("Contact", href="https://forms.gle/nDahQbhYDNYh6P129", target="_blank", className="quick-link"),
                        ],
                        className="top-strip-quicklinks",
                    ),
                    html.Button(
                        "Configure",
                        id="open-drawer-btn",
                        className="configure-btn",
                        n_clicks=0,
                        title="Open configuration drawer",
                    ),
                    _theme_toggle(),
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
                            html.Li([html.Strong("Impossible Turn"), " - Engine failure after takeoff: can you make it back?"]),
                            html.Li([html.Strong("Power-Off 180"), " - Accuracy approach from abeam the touchdown point."]),
                            html.Li([html.Strong("Engine-Out Glide"), " - Glide distance and path to a landing spot."]),
                            html.Li([html.Strong("Steep Turns"), " - 45° bank turns with load factor and stall speed changes."]),
                            html.Li([html.Strong("Chandelle"), " - Maximum performance climbing turn."]),
                            html.Li([html.Strong("Lazy Eight"), " - Symmetrical climbing/descending turns."]),
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
        ]
    )


def _reset_buttons_row():
    """Returns the reset buttons row to be included in each maneuver layout."""
    return html.Div([
        html.Button("Reset All", id="reset-all", className="reset-btn-small", style={"flex": "1"}),
        html.Button("Reset Clicks", id="reset-clicks", className="reset-btn-small", style={"flex": "1"}),
        html.Button("Undo Click", id="undo-last-click", className="reset-btn-small", style={"flex": "1", "backgroundColor": "#17a2b8"}),
    ], style={"display": "flex", "gap": "6px", "marginBottom": "10px"})


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


def _settings_drawer():
    """Phase 4 Batch 2d — Offcanvas drawer holding configuration that
    doesn't need to be visible while flying. Mirrors EM Diagram's
    "live controls in rail, config in drawer" pattern (Phase 5AA).

    Contents: action buttons (Edit/Load aircraft) + Weight & Balance
    + Environment + Power. Wind stays in the rail because the user
    typically tunes it in line with map clicks."""
    return dbc.Offcanvas(
        [
            html.Div(className="action-buttons-row", children=[
                html.A("Edit/Create Aircraft", href="https://app.flyaeroedge.com/edit-aircraft", target="_blank", className="btn-action-orange"),
                dcc.Upload(
                    html.Button("Load Aircraft File", className="btn-action-orange"),
                    id="upload-aircraft",
                    accept=".json",
                ),
            ]),

            dbc.Accordion([
                dbc.AccordionItem([
                    html.Label("Engine Option", className="input-label"),
                    dcc.Dropdown(id="engine-select", className="dropdown", persistence=True, persistence_type="local"),

                    html.Label("Occupants", className="input-label"),
                    dcc.Input(id="occupants", type="number", value=1, min=1, max=4, className="input-small", persistence=True, persistence_type="local"),

                    html.Label("Occupant Weight (lbs)", className="input-label"),
                    dcc.Input(id="occupant-weight", type="number", value=180, min=100, max=300, className="input-small", persistence=True, persistence_type="local"),

                    html.Label("Fuel Load (gal)", className="input-label"),
                    dcc.Slider(
                        id="fuel-load",
                        min=0, max=50, step=1, value=0,
                        marks={0: "0", 12: "1/4", 25: "1/2", 37: "3/4", 50: "Full"},
                        tooltip={"always_visible": True},
                        persistence=True, persistence_type="local",
                    ),

                    html.Label("Total Weight (lbs)", className="input-label"),
                    dcc.Input(id="total-weight-display", type="text", value="", readOnly=True, className="input-small"),

                    html.Label("CG Position", className="input-label"),
                    dcc.Slider(
                        id="cg-slider",
                        min=0.0, max=1.0, step=0.01, value=0.5,
                        marks={0.0: "FWD", 0.5: "MID", 1.0: "AFT"},
                        tooltip={"always_visible": True},
                        persistence=True, persistence_type="local",
                    ),
                ], title="Weight & Balance"),

                dbc.AccordionItem([
                    html.Label("Airport Elevation (ft)", className="input-label"),
                    html.Div(id="env-airport-agl", className="weight-box", style={"marginBottom": "10px"}),

                    html.Label("Outside Air Temp (F)", className="input-label"),
                    dcc.Input(id="env-oat", type="number", value=52, className="input-small", persistence=True, persistence_type="local"),

                    html.Label("Altimeter Setting (inHg)", className="input-label", style={"marginTop": "8px"}),
                    dcc.Input(id="env-altimeter", type="number", value=29.92, className="input-small", persistence=True, persistence_type="local"),
                ], title="Environment"),

                dbc.AccordionItem([
                    html.Label("Power Setting", className="input-label"),
                    dcc.Slider(
                        id="power-setting",
                        min=0.05, max=1.0, step=0.05, value=0.5,
                        marks={0.05: "IDLE", 0.2: "20%", 0.4: "40%", 0.6: "60%", 0.8: "80%", 0.99: "100%"},
                        tooltip={"always_visible": True},
                        persistence=True, persistence_type="local",
                    ),
                ], title="Power"),
            ], start_collapsed=False, always_open=True, className="drawer-accordion"),
        ],
        id="settings-drawer",
        title="Configuration",
        placement="start",
        is_open=False,
        backdrop=True,
        scrollable=True,
        className="settings-drawer",
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
        _modals_block(),
        _settings_drawer(),
        # Main 2-column layout (sidebar + map) — wraps in main-grid so
        # the CSS can target it with the new shell rules.
        html.Div(className="main-row main-grid", children=[
            # === Sidebar ===
            html.Div(id="sidebar", className="resizable-sidebar", children=[
                # Header row with title and collapse button
                html.Div(className="sidebar-header", children=[
                    html.Div("Maneuver Overlay Tool", className="sidebar-title"),
                    html.Button(
                        "«",
                        id="sidebar-collapse-btn",
                        className="sidebar-collapse-btn",
                        title="Collapse sidebar"
                    ),
                ]),
                html.Div(id="sidebar-content", children=[

                # --- Action buttons + Weight & Balance + Environment + Power
                # moved to the settings drawer (Phase 4 Batch 2d). Open via
                # the Configure button in the top-strip.

                # --- Airport Search (First - so user can navigate) ---
            html.Label("Search Airport", className="input-label"),
            dcc.Input(
                id="airport-search-input",
                type="text",
                placeholder="ICAO or name...",
                debounce=False,  # Instant results as you type
                className="input-large",
                autoComplete="off",
            ),
            # Hidden stores for keyboard navigation
            dcc.Store(id="airport-highlight-index", data=0),
            dcc.Store(id="airport-search-matches", data=[]),
            html.Div(id="airport-search-results", className="search-results-box"),
            # Selected airport display
            html.Div(
                id="selected-airport-display",
                style={
                    "fontSize": "12px",
                    "color": "#28a745",
                    "fontWeight": "500",
                    "marginTop": "4px",
                    "marginBottom": "4px",
                    "display": "none"  # Hidden until airport selected
                }
            ),

            # Recenter to Airport button
            html.Button("Recenter to Airport", id="recenter-airport-btn", className="reset-btn-small", style={"marginTop": "4px", "marginBottom": "8px", "backgroundColor": "#6c757d"}),

            # --- Aircraft Selection — moved to top-strip in Batch 2b ---
            # --- Engine/Weight/CG/Env/Power — moved to settings drawer in Batch 2d ---

            # --- Wind (Compact single row) — stays in rail; live tuning ---
            html.Div([
                html.Span("Wind", style={"fontWeight": "600", "fontSize": "13px", "marginRight": "12px"}),
                html.Span("Direction", style={"fontSize": "11px", "color": "#666", "marginRight": "4px"}),
                dcc.Input(id="env-wind-dir", type="number", value=360, min=1, max=360, className="input-small", style={"width": "55px", "height": "28px", "marginRight": "10px"}, persistence=True, persistence_type="local"),
                html.Span("Speed (Kts)", style={"fontSize": "11px", "color": "#666", "marginRight": "4px"}),
                dcc.Input(id="env-wind-speed", type="number", value=0, min=0, className="input-small", style={"width": "50px", "height": "28px"}, persistence=True, persistence_type="local"),
            ], className="wind-row"),

            # --- Maneuver Dropdown ---
            html.Label("Maneuver", className="input-label"),
            dcc.Dropdown(
                id="maneuver-select",
                className="dropdown",
                placeholder="Select Maneuver",
                options=[
                    {"label": "Impossible Turn", "value": "impossible_turn"},
                    {"label": "Power-Off 180", "value": "poweroff180"},
                    {"label": "Engine-Out Glide Simulation", "value": "engineout"},
                    {"label": "Steep Turns", "value": "steep_turn"},
                    {"label": "Chandelle", "value": "chandelle"},
                    {"label": "Lazy Eight", "value": "lazy8"},
                    {"label": "Steep Spiral", "value": "steep_spiral"},
                    {"label": "S-Turns", "value": "s_turn"},
                    {"label": "Turns Around a Point", "value": "turns_point"},
                    {"label": "Rectangular Course", "value": "rect_course"},
                    {"label": "Eights on Pylons", "value": "pylons"},
                ],
                persistence=True,
                persistence_type="local"
            ),

            # --- Conditionally Shown Based on Maneuver ---
            html.Div(id="maneuver-params-container", children=[], style={"marginTop": "15px"}),

            # Store for tracking last clicked point (for undo)
            dcc.Store(id="last-click-info", data=None),
            ]),  # End sidebar-content
            # Store for sidebar collapse state
            dcc.Store(id="sidebar-collapsed-store", data=False),
        ]),

        # === Map Column ===
        html.Div(id="engineout-click-status", style={"display": "none"}),
        html.Div(className="graph-column", style={"display": "flex", "flexDirection": "column"}, children=[
            html.Div(
                style={
                    "flexGrow": 1,
                    "height": "calc(100vh - 180px)",
                    "position": "relative"
                },
                children=[
                    dl.Map(
                        id="map",
                        center=[33.0635, -80.2795],
                        zoom=13.5,
                        style={"width": "100%", "height": "100%"},
                        children=[
                            dl.TileLayer(
                                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                                attribution="Tiles &copy; Esri"
                            ),
                            dl.LayerGroup(id="layer"),
                            dl.LayerGroup(id="scrubber-layer"),  # Dedicated layer for time scrubber marker
                            dl.ScaleControl(position="bottomleft", imperial=True, metric=False),  # Scale bar - JS converts to NM
                            # Windsock indicator overlay - default 360@0kt (calm), updated by callback
                            html.Div(
                                id="windsock-overlay",
                                style={
                                    "position": "absolute",
                                    "top": "10px",
                                    "right": "10px",
                                    "zIndex": "1000",
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

            html.Div(id="click_debug", style={
                "padding": "10px 12px",
                "fontStyle": "italic",
                "color": "#555",
                "backgroundColor": "#fff",
                "borderTop": "1px solid #ccc"
            }),

            # ===== Maneuver-scoped point stores (no shared state between maneuvers) =====

            dcc.Store(id="runtime-total-weight-lb"),

            # Power-Off 180 (touchdown only; start is auto-generated but keep for future flexibility)
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "start"}),

            # Engine-Out Glide
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "start"}),

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

            # Rectangular Course (downwind edge points)
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

            html.Div([
                html.Div("© 2026 Nicholas Len, TALLYAERO. All rights reserved.",
                         style={"fontSize": "11px", "color": "#666"}),
                html.Div([
                    html.A("Full Legal Disclaimer", href="#", id="open-disclaimer", className="legal-link", style={"fontSize": "10px"}),
                    html.Span(" | ", style={"color": "#999", "fontSize": "10px"}),
                    html.A("Terms of Use & Privacy Policy", href="#", id="open-terms-policy", className="legal-link", style={"fontSize": "10px"}),
                ], style={"marginTop": "3px"}),
            ], className="footer", style={"paddingBottom": "10px", "textAlign": "center"})
        ])
    ])
])
