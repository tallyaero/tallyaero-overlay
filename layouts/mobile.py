"""Mobile layout (< 768px viewport).

Composes a compact, collapsible UI for narrow viewports. Uses the SAME
component ids as desktop_layout so every existing callback continues to
wire up identically; mobile-specific ids (e.g. mobile-settings-toggle)
are additive.

Pure function; no callbacks. The per-maneuver parameter forms in
layouts/maneuvers/ are injected at runtime by the `render_maneuver_layout`
callback (still in app.py for now; Phase 1e will move it).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from core.data_loader import available_aircraft


def _mobile_theme_toggle():
    """Mirrors the desktop theme toggle (Phase 4). Same component IDs so
    the same clientside callback wires both layouts."""
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


def mobile_layout():
    """Mobile layout — Phase 4 Batch 3 mirror.

    Top bar: hamburger (toggle settings) + aircraft picker + theme.
    Slim sub-row holds quick-links. Settings still lives in a
    dbc.Collapse below; Offcanvas migration deferred to Batch 4."""
    return html.Div(className="mobile-container mobile-shell", children=[
        html.Div(className="mobile-top-bar", children=[
            html.Div(className="mobile-top-row", children=[
                html.Button(
                    "Menu",
                    id="mobile-settings-toggle",
                    className="mobile-hamburger",
                    n_clicks=0,
                    title="Toggle settings",
                    **{"aria-label": "Toggle settings"},
                ),
                html.Div(
                    dcc.Dropdown(
                        id="aircraft-select",
                        options=[{"label": name, "value": name} for name in available_aircraft],
                        value="C172" if "C172" in available_aircraft else (available_aircraft[0] if available_aircraft else None),
                        placeholder="Select Aircraft…",
                        className="dropdown",
                        clearable=False,
                        persistence=True,
                        persistence_type="local",
                    ),
                    className="mobile-aircraft-picker",
                ),
                _mobile_theme_toggle(),
            ]),
            html.Div(className="mobile-quicklinks", children=[
                html.A("Quick Start", href="#", id="mobile-open-quickstart", className="quick-link", style={"color": "#E65C00", "fontWeight": "bold"}),
                html.Span(" · ", className="quick-link-sep"),
                html.A("Contact", href="mailto:info@tallyaero.com", className="quick-link"),
            ]),
        ]),

        # Collapsible settings - uses SAME IDs as desktop for callback compatibility
        dbc.Collapse(
            html.Div(className="mobile-settings-content", children=[
                # Action buttons row (50/50 split)
                html.Div(className="action-buttons-row", children=[
                    html.A("Edit/Create Aircraft", href="https://app.flyaeroedge.com/edit-aircraft", target="_blank", className="btn-action-orange"),
                    dcc.Upload(
                        html.Button("Load Aircraft", className="btn-action-orange"),
                        id="upload-aircraft",
                        accept=".json"
                    ),
                ]),

                # Airport Search
                html.Label("Search Airport", className="input-label", style={"marginTop": "8px"}),
                dcc.Input(
                    id="airport-search-input",
                    type="text",
                    placeholder="ICAO or name...",
                    className="mobile-input-full",
                    debounce=False,
                    autoComplete="off",
                    style={"width": "100%", "marginBottom": "4px"}
                ),
                html.Div(id="airport-search-results", className="search-results-box"),
                html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center", "marginBottom": "8px"}, children=[
                    html.Div(id="selected-airport-display", style={"fontSize": "12px", "color": "#28a745", "flex": "1"}),
                    html.Button("Recenter", id="recenter-airport-btn", className="reset-btn-small", style={"fontSize": "10px"}),
                ]),

                # Aircraft Selection — moved to mobile-top-bar in Batch 3

                # Weight & Balance Accordion
                dbc.Accordion([
                    dbc.AccordionItem([
                        html.Label("Engine Option", className="input-label"),
                        dcc.Dropdown(id="engine-select", className="mobile-dropdown", persistence=True, persistence_type="local"),

                        html.Div(style={"display": "flex", "gap": "10px", "marginTop": "8px"}, children=[
                            html.Div([
                                html.Label("Occupants", className="input-label-sm"),
                                dcc.Input(id="occupants", type="number", value=1, min=1, max=4, className="mobile-input-sm", persistence=True, persistence_type="local"),
                            ], style={"flex": "1"}),
                            html.Div([
                                html.Label("Occ. Wt (lb)", className="input-label-sm"),
                                dcc.Input(id="occupant-weight", type="number", value=180, className="mobile-input-sm", persistence=True, persistence_type="local"),
                            ], style={"flex": "1"}),
                        ]),

                        html.Label("Fuel Load (gal)", className="input-label", style={"marginTop": "8px"}),
                        dcc.Slider(id="fuel-load", min=0, max=50, step=1, value=25,
                                   marks={0: "0", 25: "½", 50: "Full"}, tooltip={"always_visible": True}, persistence=True, persistence_type="local"),

                        html.Label("Total Weight", className="input-label", style={"marginTop": "8px"}),
                        dcc.Input(id="total-weight-display", type="text", readOnly=True, className="mobile-input-sm", style={"textAlign": "left"}),

                        html.Label("CG Position", className="input-label", style={"marginTop": "8px"}),
                        dcc.Slider(id="cg-slider", min=0, max=1, step=0.01, value=0.5,
                                   marks={0: "FWD", 0.5: "MID", 1: "AFT"}, tooltip={"always_visible": True}, persistence=True, persistence_type="local"),
                    ], title="Weight & Balance"),
                ], start_collapsed=True, className="sidebar-accordion", style={"marginTop": "8px"}),

                # Environment Accordion
                dbc.Accordion([
                    dbc.AccordionItem([
                        html.Label("Airport Elevation (ft)", className="input-label"),
                        html.Div(id="env-airport-agl", className="weight-box", style={"marginBottom": "8px", "fontSize": "14px"}),

                        html.Div(style={"display": "flex", "gap": "10px"}, children=[
                            html.Div([
                                html.Label("OAT (°F)", className="input-label-sm"),
                                dcc.Input(id="env-oat", type="number", value=52, className="mobile-input-sm", persistence=True, persistence_type="local"),
                            ], style={"flex": "1"}),
                            html.Div([
                                html.Label("Altimeter", className="input-label-sm"),
                                dcc.Input(id="env-altimeter", type="number", value=29.92, step=0.01, className="mobile-input-sm", persistence=True, persistence_type="local"),
                            ], style={"flex": "1"}),
                        ]),
                    ], title="Environment"),
                ], start_collapsed=True, className="sidebar-accordion", style={"marginTop": "4px"}),

                # Wind Row (compact)
                html.Div([
                    html.Span("Wind", style={"fontWeight": "600", "fontSize": "13px", "marginRight": "10px"}),
                    html.Span("Dir", style={"fontSize": "11px", "color": "#666", "marginRight": "4px"}),
                    dcc.Input(id="env-wind-dir", type="number", value=360, min=1, max=360, className="mobile-input-sm", style={"width": "50px", "marginRight": "8px"}, persistence=True, persistence_type="local"),
                    html.Span("Kts", style={"fontSize": "11px", "color": "#666", "marginRight": "4px"}),
                    dcc.Input(id="env-wind-speed", type="number", value=0, min=0, className="mobile-input-sm", style={"width": "45px"}, persistence=True, persistence_type="local"),
                ], className="wind-row", style={"marginTop": "8px"}),

                # Power Accordion
                dbc.Accordion([
                    dbc.AccordionItem([
                        html.Label("Power Setting", className="input-label"),
                        dcc.Slider(id="power-setting", min=0.05, max=1.0, step=0.05, value=0.5,
                                   marks={0.05: "IDLE", 0.5: "50%", 1.0: "100%"}, tooltip={"always_visible": True}, persistence=True, persistence_type="local"),
                    ], title="Power"),
                ], start_collapsed=True, className="sidebar-accordion", style={"marginTop": "4px"}),

                # Maneuver Selection
                html.Label("Maneuver", className="input-label", style={"marginTop": "8px"}),
                dcc.Dropdown(
                    id="maneuver-select",
                    className="mobile-dropdown",
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

                # Maneuver params container
                html.Div(id="maneuver-params-container", style={"marginTop": "8px"}),

                # Click debug
                html.Div(id="click_debug", style={"fontSize": "11px", "color": "#666", "marginTop": "8px"}),
            ]),
            id="mobile-settings-collapse",
            is_open=False,
        ),

        # Map container - uses same IDs as desktop
        html.Div(className="mobile-map-wrapper", children=[
            dl.Map(
                id="map",
                center=[33.0635, -80.2795],
                zoom=12,
                style={"width": "100%", "height": "100%", "minHeight": "70vh"},
                children=[
                    dl.TileLayer(
                        url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                        attribution="Tiles © Esri",
                    ),
                    dl.LayerGroup(id="layer"),
                    dl.LayerGroup(id="scrubber-layer"),
                    dl.ScaleControl(position="bottomleft", imperial=True, metric=False),  # Scale bar
                    # Windsock overlay
                    html.Div(
                        id="windsock-overlay",
                        style={
                            "position": "absolute",
                            "top": "10px",
                            "right": "10px",
                            "zIndex": "1000",
                            "backgroundColor": "rgba(255,255,255,0.9)",
                            "padding": "4px 8px",
                            "borderRadius": "6px",
                            "boxShadow": "0 2px 6px rgba(0,0,0,0.2)",
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "4px",
                            "fontFamily": "'Inter', sans-serif",
                        },
                        children=[html.Span("360° @ 0 kt", style={"fontSize": "11px", "fontWeight": "600"})]
                    ),
                ]
            ),
        ]),

        # Footer
        html.Div("© 2026 TallyAero", className="mobile-footer"),

        # Hidden stores and placeholders needed for callbacks
        html.Div(style={"display": "none"}, children=[
            # Desktop-only UI elements
            dcc.Store(id="sidebar-collapsed-store", data=False),
            html.Button(id="sidebar-collapse-btn"),
            html.Div(id="sidebar-content"),
            html.Div(id="sidebar"),

            # Required stores for callbacks
            dcc.Store(id="runtime-total-weight-lb"),
            dcc.Store(id="selected-airport-id", storage_type="local"),
            dcc.Store(id="active-click-target"),
            dcc.Store(id="last-click-info"),
            dcc.Store(id="airport-highlight-index", data=0),
            dcc.Store(id="airport-search-matches", data=[]),

            # Point stores for all maneuvers
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "poweroff180", "role": "start"}),
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "touchdown"}),
            dcc.Store(id={"type": "point-store", "m_id": "engineout", "role": "start"}),
            dcc.Store(id={"type": "point-store", "m_id": "steep_turn", "role": "start"}),
            dcc.Store(id={"type": "point-store", "m_id": "chandelle", "role": "start"}),
            dcc.Store(id={"type": "point-store", "m_id": "lazy8", "role": "start"}),
            dcc.Store(id={"type": "point-store", "m_id": "steep_spiral", "role": "ref"}),
            dcc.Store(id={"type": "point-store", "m_id": "s_turn", "role": "ref"}),
            dcc.Store(id={"type": "point-store", "m_id": "s_turn", "role": "bearing"}),
            dcc.Store(id="sturn-calculated-bearing"),
            dcc.Store(id={"type": "point-store", "m_id": "turns_point", "role": "center"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "dw_start"}),
            dcc.Store(id={"type": "point-store", "m_id": "rect_course", "role": "dw_end"}),
            dcc.Store(id={"type": "point-store", "m_id": "pylons", "role": "pylon_a"}),
            dcc.Store(id={"type": "point-store", "m_id": "pylons", "role": "pylon_b"}),
            dcc.Store(id="pylons-ias-store", data=100),
            dcc.Store(id="pylons-bank-store", data=30),
            dcc.Store(id={"type": "point-store", "m_id": "impossible_turn", "role": "start"}),
            dcc.Store(id="rectcourse-calculated-edge", data={}),
            html.Div(id="rectcourse-edge-info-display"),
        ]),
    ])
