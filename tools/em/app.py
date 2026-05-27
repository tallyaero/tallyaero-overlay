# =============================================================================
# TallyAero EM Diagram — main entry point
# =============================================================================
"""
TallyAero Energy-Maneuverability Diagram Generator.

This module is the thin entry point. All physics lives in `core/`, all
callbacks in `callbacks/`, all layouts in `layouts/`. See
`EM_DIAGRAM_EXECUTION_PLAN.md` for the architectural breakdown.

Run with:
    venv/bin/python app.py [port]    (default port 8051)
"""

import os
import sys
import webbrowser
from pathlib import Path

import dash
from dash import dcc, html, ClientsideFunction
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from flask import send_from_directory

from core import AIRCRAFT_DATA
from layouts import edit_aircraft_layout, em_diagram_layout
from callbacks import register_all


# =============================================================================
# Dash app + Flask server
# =============================================================================
app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)
server = app.server


# =============================================================================
# HTML index template (meta tags, title, favicon)
# =============================================================================
# Phase 6S — expose the build version to the clientside update-check.
try:
    _VERSION = (Path(__file__).parent / "VERSION").read_text().strip()
except Exception:
    _VERSION = "0.0.0"

app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Energy Maneuverability Diagram Generator</title>
        <script>window.__TALLYAERO_VERSION__ = '__VERSION__';</script>""".replace("__VERSION__", _VERSION) + """
        <meta name="description" content="Interactive Energy Maneuverability Diagrams for general aviation, multi-engine, aerobatic, and military aircraft. Analyze Ps contours, Vmc dynamics, Vyse, G-limits, stall margins, and more.">
        <meta name="keywords" content="EM Diagram, Energy Maneuverability, Aircraft Performance, General Aviation, Vmc, Vyse, Vxse, Ps Contours, G-Limits, Stall Speed, Spin Awareness, Stall Awareness, Turn Rate, Flight Envelope, FAA Training, Multi-Engine Safety, Aerobatic Flight, FAA Flight Training, Maneuvering Performance, AOB, Angle of Bank, Aviation Education, Pilot Tools, Military Trainer Aircraft, FAA Checkride Prep, Performance Planning, General Aviation Safety">
        <meta name="robots" content="index, follow">
        <meta name="author" content="TallyAero">
        <meta name="google-site-verification" content="ukKfZyRJS6up-cpev6piffO5YyKPIhS-DdgnRgBUBig" />
        {%favicon%}
        {%css%}
        <script>
        /* Phase 5e — apply persisted theme before paint to prevent FOUC.
           Runs synchronously in <head>. Reads localStorage and sets
           data-theme on <html>. The toggle UI uses the same key. */
        (function() {
          var pref = localStorage.getItem('tallyaero_theme') || 'light';
          var resolved = pref;
          if (pref === 'system') {
            resolved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
          }
          document.documentElement.setAttribute('data-theme', resolved);
          document.documentElement.setAttribute('data-theme-pref', pref);
        })();
        </script>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""



# =============================================================================
# Page layout: top-level Stores + global Modals
# =============================================================================
app.layout = html.Div([
    dcc.Location(id="url"),
    dcc.Store(id="aircraft-data-store", data=AIRCRAFT_DATA),
    dcc.Store(id="last-saved-aircraft"),
    dcc.Store(id="stored-total-weight"),
    dcc.Store(id="screen-width"),
    # Phase 5AB-13: sidebar-collapsed store retired alongside the collapse btn.
    # Phase 5e: theme preference store. The early-paint <script> in
    # index_string seeds data-theme from localStorage; the clientside
    # callback below mirrors any toggle clicks back into both the
    # DOM and the persistent store.
    dcc.Store(id="theme-pref", storage_type="local", data=None),
    # Phase 4: parsed METAR observation for the selected airport, or None.
    # Populated by environment.update_environment_on_airport, consumed by
    # the weather-panel display callback.
    dcc.Store(id="metar-store", data=None),
    # Phase 5T: which aircraft the edit page should auto-load. Set by the
    # "Edit / Create" button on the main page (carries the currently-selected
    # aircraft across the page nav). Session-persistent so a browser refresh
    # mid-edit keeps the context.
    dcc.Store(id="editing-aircraft", storage_type="session", data=None),
    # Phase 5U: the SECOND aircraft to render in comparative-overlay mode,
    # or None when comparison is off. The comparison aircraft borrows the
    # primary's atmospheric inputs but uses its own geometry / g-limit /
    # Vne — Boyd's 1966 chart used the same approach.
    dcc.Store(id="compare-aircraft", data=None),
    # Phase 5Z-2: user-dropped target on the Energy Map (h-V) chart, or
    # None when no target is set. Stored as {"v_disp": float, "h_ft": float}
    # so units match whatever the user's display unit is.
    dcc.Store(id="hv-target-point", data=None),
    # Phase 5AA-click: click-mode flag for the h-V chart. False (default) =
    # clicking moves the current state to the click's altitude (drives the
    # altitude slider). True = clicking drops a target there. Flipped by the
    # "Drop target" chip in the chart-tabs row.
    dcc.Store(id="hv-target-mode", data=False),
    # Phase 5AB-3: reference IAS in knots used by the h-V chart's current-
    # state marker. None = fall back to the aircraft's Vy. Click on the chart
    # (in move-current-state mode) writes this AND the altitude slider so
    # the orange dot drags to the clicked (V, h) — both axes.
    dcc.Store(id="ref-ias-kt", data=None),
    # Phase 5W: reachable-set time horizon (seconds). None = overlay off.
    # Cycled by the REACH chip in the chart-tabs row: OFF → 60 → 120 → 300.
    dcc.Store(id="hv-reach-seconds", data=None),
    # Phase 5X: probabilistic margin bands on the h-V chart. False = hard
    # envelope lines (default). True = stall and ceiling render as shaded
    # bands that reflect 14 CFR 23 stall-warning margin + atmospheric variance.
    dcc.Store(id="hv-margins", data=False),
    # Phase 5AC: doghouse scenario probe. Click on the maneuver doghouse
    # drops a probe at (V, ω); we show required bank, G, and turn radius.
    # Stored as {"v_kt": float, "omega_dps": float} or None when cleared.
    dcc.Store(id="doghouse-probe", data=None),
    # Phase 5AE: chart-tab Store moved here from desktop's chart-tabs row so
    # mobile (which doesn't render those tabs) can still satisfy callbacks
    # that read this id. Values: "maneuver" | "hv".
    dcc.Store(id="chart-tab", data="maneuver"),
    # Phase 5AE: browser-width Store was a latent missing target —
    # callbacks/navigation.py writes to it on every URL change but no
    # Store ever existed. Adding it cleans up the warning surface.
    dcc.Store(id="browser-width"),
    # Phase 6S: update banner — clientside JS fetches a small JSON from
    # tallyaero.com on first load. If the server reports a newer version,
    # the banner becomes visible with a download link.
    html.Div(id="update-banner", style={"display": "none"}, className="update-banner",
             children=[
                 html.Span(id="update-banner-msg", className="update-banner-msg"),
                 html.A("Download", id="update-banner-link",
                        href="https://tallyaero.com/em-diagram",
                        target="_blank",
                        className="update-banner-link"),
                 html.Button("×", id="update-banner-close",
                             className="update-banner-close",
                             **{"aria-label": "Dismiss update banner"}),
             ]),
    html.Div(id="page-content"),
    dcc.Download(id="download-aircraft"),

    # Global Modals (shared between desktop and mobile)
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("TallyAero Disclaimer"), close_button=True),
        dbc.ModalBody([
            html.P("This tool supplements—not replaces—FAA-published documentation.", style={"marginBottom": "8px"}),
            html.P("It is intended for educational and reference use only, and has not been approved or endorsed by the Federal Aviation Administration (FAA).", style={"marginBottom": "8px"}),
            html.P("While TallyAero is aligned with FAA safety principles, it is not an official source of operational data. Users must consult certified instructors and approved aircraft documentation when making flight decisions.", style={"marginBottom": "8px"}),
            html.P("The data presented may be incomplete, inaccurate, outdated, or derived from public or user-submitted sources. No warranties, express or implied, are made regarding its accuracy, completeness, or fitness for purpose.", style={"marginBottom": "8px"}),
            html.P("Instructors and users are encouraged to verify all EM diagram outputs against certified POH/AFM values. This tool is not a substitute for competent flight instruction, or for compliance with applicable regulations, including Airworthiness Directives (ADs), Federal Aviation Regulations (FARs), or Advisory Circulars (ACs).", style={"marginBottom": "8px"}),
            html.P("If any information conflicts with the aircraft's FAA-approved AFM or POH, the official documentation shall govern.", style={"marginBottom": "8px"}),
            html.P("TallyAero disclaims all liability for errors, omissions, injuries, or damages resulting from the use of this application or website. Use of this tool constitutes acceptance of these terms.", style={"marginBottom": "8px"})
        ]),
        dbc.ModalFooter(
            dbc.Button("Close", id="close-disclaimer", className="ms-auto", color="secondary")
        )
    ], id="disclaimer-modal", is_open=False, centered=True, size="lg"),

    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Terms of Use & Privacy Policy"), close_button=True),
        dbc.ModalBody([
            html.H6("Terms of Use", className="mb-2 mt-2"),
            html.P("By accessing or using the TallyAero application and its associated services, you agree to use this tool solely for educational and informational purposes. This tool is not FAA-certified and should not be relied upon for flight planning, aircraft operation, or regulatory compliance.", style={"marginBottom": "8px"}),
            html.P("Users must verify all performance data with the aircraft's official Pilot's Operating Handbook (POH) or Aircraft Flight Manual (AFM). Use of TallyAero is at your own risk. TallyAero disclaims liability for any direct, indirect, incidental, or consequential damages arising from its use.", style={"marginBottom": "8px"}),
            html.H6("Privacy Policy", className="mb-2 mt-4"),
            html.P("TallyAero does not collect, store, or share any personally identifiable information (PII). All use of the application is anonymous. Uploaded aircraft files remain local to your device and are not transmitted or stored on any external servers.", style={"marginBottom": "8px"}),
            html.P("If you submit feedback through linked forms, that information is governed by the terms of Google Forms. TallyAero does not sell or distribute any user-submitted information and uses it only to improve functionality and user experience.", style={"marginBottom": "8px"}),
            html.P("By using this application, you acknowledge and accept these terms.")
        ]),
        dbc.ModalFooter(
            dbc.Button("Close", id="close-terms-policy", className="ms-auto", color="secondary")
        )
    ], id="terms-policy-modal", is_open=False, centered=True, size="lg"),

    # Quick Start Modal
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Quick Start Guide"), close_button=True),
        dbc.ModalBody([
            # ── 1. Intro ────────────────────────────────────────────────
            html.P([
                html.Strong("What is an EM Diagram? "),
                "Energy-Maneuverability — Boyd 1966 — visualizes your aircraft's performance envelope: the relationship between airspeed, altitude, load factor (G), and turn rate at any configuration."
            ], style={"marginBottom": "8px"}),

            # ── 2. The two charts ─────────────────────────────────────
            html.P(html.Strong("Two charts, one aircraft"), style={"marginBottom": "4px"}),
            html.Ul([
                html.Li([
                    html.Strong("MANEUVER Doghouse "), "— Turn rate vs IAS (Boyd 1966). ",
                    html.Em("\"At this airspeed, how hard can I turn before stalling or breaking?\"")
                ]),
                html.Li([
                    html.Strong("ENERGY Map h-V "), "— Altitude vs IAS (Rutowski 1954 / FAA AFH Ch 4). ",
                    html.Em("\"How can I trade altitude for airspeed at constant total energy?\"")
                ]),
            ], style={"paddingLeft": "20px", "marginBottom": "10px", "fontSize": "13px"}),

            html.Hr(style={"margin": "8px 0"}),

            # ── 3. Layout tour ──────────────────────────────────────────
            html.P(html.Strong("Layout"), style={"marginBottom": "4px"}),
            html.Ul([
                html.Li([
                    html.Strong("Top bar "), "— aircraft picker on the left; ",
                    "9 inline state tiles (Weight, Vs1G, Va, Vne, Vno, +G limit, KE, PE, E). ",
                    html.Em("Click any tile"), " to read what that term means and how it's computed."
                ]),
                html.Li([
                    html.Strong("Right rail "), "— three sections: ",
                    html.Strong("Atmosphere"), " (Airport, Altitude, OAT, Altimeter), ",
                    html.Strong("Weight"), " (Occupants, Occ Wt, Fuel), and ",
                    html.Strong("Live Controls"), " (Power, CG, FPA). ",
                    "Picking an airport pulls live METAR and seeds OAT + altimeter."
                ]),
                html.Li([
                    html.Strong("Chart tabs "), "— buttons above the chart cycle features. ",
                    "Compare lives next to the Doghouse (where overlays go); ",
                    "REACH / MARGINS / MODE / Drop target live next to the Energy Map. ",
                    "Chips hide automatically when they don't apply to the active chart."
                ]),
                html.Li([
                    html.Strong("MORE Configure "), "— the drawer at the bottom of the rail. ",
                    "Engine / Category / Flap / Gear configuration, overlay toggles, ",
                    "Edit / Load aircraft. Configure-once items."
                ]),
            ], style={"paddingLeft": "20px", "marginBottom": "10px", "fontSize": "13px"}),

            html.Hr(style={"margin": "8px 0"}),

            # ── 4. Energy Map deep dive ─────────────────────────────────
            html.P(html.Strong("Reading the Energy Map"), style={"marginBottom": "4px"}),
            html.Ul([
                html.Li([
                    html.Strong("Dotted gray hyperbolas "), "= constant-energy curves ",
                    html.Code("E = h + V²/(2g)"),
                    ". Every point on a curve has the ", html.Em("same total energy"),
                    " — sliding along one is a free trade (zoom climb, dive recovery, glide)."
                ]),
                html.Li([
                    html.Strong("Red / green Ps shading"), " = specific excess power at current power setting (right colorbar). ",
                    "Green = climb capability, red = energy bleed. ",
                    html.Strong("Solid blue line"), " is Ps = 0 — sustained ceiling at this power."
                ]),
                html.Li([
                    html.Span("●", style={"color": "#f27b0d", "fontSize": "16px"}),
                    " ", html.Strong("Orange dot"), " = your current operating point. ",
                    "Hover shows altitude, IAS, and total E."
                ]),
            ], style={"paddingLeft": "20px", "marginBottom": "10px", "fontSize": "13px"}),

            html.P(html.Strong("Energy Map chips"), style={"marginBottom": "4px"}),
            html.Ul([
                html.Li([
                    html.Code("MODE Drop target"),
                    " — default OFF: clicks move your current state to the clicked (V, h). ",
                    "Click the chip to flip ON: clicks now drop a ",
                    html.Span("◇", style={"color": "var(--ta-brand-blue)", "fontSize": "14px"}),
                    " target instead. An arrow from current → target labels the energy delta, ",
                    html.Strong("ΔPE / ΔKE split"), ", time-to-target, and ", html.Strong("implied flight path angle"),
                    ". Energy bleeds use idle Ps; climbs use current power."
                ]),
                html.Li([
                    html.Code("REACH"),
                    " — cycles Off → 60 s → 120 s → 300 s. Shades the ",
                    html.Em("reachable-set band"),
                    " — where you could be in N seconds (upper bound = full power climb, lower bound = idle bleed). ",
                    "Drop a target outside the band → 'can't get there in N seconds'."
                ]),
                html.Li([
                    html.Code("MARGINS"),
                    " — toggles probabilistic envelope bands: stall ±5 KIAS (14 CFR 23.207 + CL_max variance), ",
                    "service ceiling ±500 ft (atmosphere variance). Vne stays hard (structural)."
                ]),
                html.Li([
                    html.Strong("Flight Path Angle slider "), "(rail) — moves the ",
                    html.Strong("γ-sustainable contour"),
                    " (orange dashed for climb, green dashed for descent): where you can sustain that γ at current power. ",
                    "If the line vanishes, a notice appears: that γ isn't sustainable anywhere at this power."
                ]),
            ], style={"paddingLeft": "20px", "marginBottom": "10px", "fontSize": "13px"}),

            html.Hr(style={"margin": "8px 0"}),

            # ── 5. Doghouse interactivity ───────────────────────────────
            html.P(html.Strong("Doghouse interactivity"), style={"marginBottom": "4px"}),
            html.Ul([
                html.Li([
                    html.Code("VS Compare"),
                    " — pick a second aircraft to overlay its envelope on yours (Boyd's killer feature). ",
                    "Axes auto-rescale to fit both. Comparison only renders on the doghouse."
                ]),
                html.Li([
                    html.Strong("Click anywhere on the doghouse "),
                    "to drop a scenario probe at that (V, ω). ",
                    "Annotation shows the ", html.Strong("required bank angle"),
                    " (θ = atan(ω·V/g)), ", html.Strong("G load"),
                    " (n = 1/cosθ), and ", html.Strong("turn radius"),
                    " (r = V²/g·tanθ). A ", html.Code("CLEAR Probe"),
                    " chip appears to reset."
                ]),
            ], style={"paddingLeft": "20px", "marginBottom": "10px", "fontSize": "13px"}),

            html.Hr(style={"margin": "8px 0"}),

            # ── 6. Tips ─────────────────────────────────────────────────
            html.P(html.Strong("Tips"), style={"marginBottom": "4px"}),
            html.Ul([
                html.Li([
                    "Keyboard: ", html.Code("d"), " toggles the drawer, ",
                    html.Code("e"), " opens Edit Aircraft, ",
                    html.Code("g"), " toggles Ps contours, ",
                    html.Code("?"), " logs the full list."
                ]),
                html.Li([
                    "Click any state tile in the top bar to read its definition and reg reference. ",
                    "Click the ",
                    html.Span("?", style={"backgroundColor": "var(--ta-brand-blue)", "color": "white", "borderRadius": "50%", "padding": "1px 5px", "fontSize": "10px"}),
                    " icons next to overlay options for deeper explanations."
                ]),
                html.Li([
                    "Picking an airport pulls live METAR from NOAA AWC and updates OAT, altimeter, and ",
                    "altitude minimums automatically. Caches for 10 minutes."
                ]),
                html.Li([
                    "Export the current chart as PNG or PDF from the top-right buttons."
                ]),
            ], style={"paddingLeft": "20px", "marginBottom": "0", "fontSize": "13px"}),
        ]),
        dbc.ModalFooter(
            dbc.Button("Close", id="close-readme", className="ms-auto", color="secondary")
        )
    ], id="readme-modal", is_open=False, centered=True, size="lg"),

    # Help Modal for feature explanations
    dcc.Store(id="help-topic", data=None),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id="help-modal-title"), close_button=True),
        dbc.ModalBody(id="help-modal-body"),
        dbc.ModalFooter(
            dbc.Button("Close", id="close-help-modal", className="ms-auto", color="secondary")
        )
    ], id="help-modal", is_open=False, centered=True, size="lg"),
])



# =============================================================================
# Client-side: detect viewport width on URL change (for mobile/desktop routing)
# Function bodies live in assets/clientside.js; we reference them by namespace.
# =============================================================================
app.clientside_callback(
    ClientsideFunction(namespace="tallyaero", function_name="screenWidth"),
    Output("screen-width", "data"),
    Input("url", "pathname"),
)


# =============================================================================
# Phase 5e — Theme toggle (Auto / Light / Dark).
# Sets data-theme on <html>, persists to localStorage, mirrors a Store + the
# three button classNames so the active state shows.
# =============================================================================
app.clientside_callback(
    ClientsideFunction(namespace="tallyaero", function_name="cycleTheme"),
    Output("theme-pref",       "data"),
    Output("theme-btn-auto",   "className"),
    Output("theme-btn-light",  "className"),
    Output("theme-btn-dark",   "className"),
    Input("theme-btn-auto",    "n_clicks"),
    Input("theme-btn-light",   "n_clicks"),
    Input("theme-btn-dark",    "n_clicks"),
)

# On page load, mirror the localStorage theme into the dcc.Store so the
# initial figure render uses the right palette. Fixes the dark-mode "chart
# vanishes" race where update_graph fired before the persisted Store value
# rehydrated.
app.clientside_callback(
    ClientsideFunction(namespace="tallyaero", function_name="syncThemeFromStorage"),
    Output("theme-pref", "data", allow_duplicate=True),
    Input("url", "pathname"),
    prevent_initial_call="initial_duplicate",
)

# Phase 5P: page-load bootstrap. Installs (a) keyboard shortcuts and (b)
# outside-click dismissal for env-chip + State Panel popovers in a single
# `bindKeyboardShortcuts` invocation (idempotent via window-level flag).
# Output is the screen-width Store as a no-op target.
app.clientside_callback(
    ClientsideFunction(namespace="tallyaero", function_name="bindKeyboardShortcuts"),
    Output("screen-width", "data", allow_duplicate=True),
    Input("url", "pathname"),
    prevent_initial_call="initial_duplicate",
)


# =============================================================================
# Phase 5h — Chandelle replay scrubber.
# Pure clientside. Reads the "Chandelle" trace from the figure, interpolates
# at the slider's percentage, writes a position marker back into the figure
# and updates a readout span. Zero server roundtrip per scrub frame.
# =============================================================================
app.clientside_callback(
    ClientsideFunction(namespace="tallyaero", function_name="replayManeuver"),
    Output("em-graph", "figure", allow_duplicate=True),
    Output("maneuver-replay-readout", "children"),
    Input("maneuver-replay-slider", "value"),
    State("em-graph", "figure"),
    prevent_initial_call=True,
)



# =============================================================================
# Helpers
# =============================================================================
def open_browser():
    """Open the user's default browser on app boot (used by the desktop build)."""
    webbrowser.open(f"http://127.0.0.1:{os.environ.get('TALLYAERO_PORT', 8051)}/")


@app.server.route("/robots.txt")
def serve_robots():
    return send_from_directory(".", "robots.txt")


@app.server.route("/sitemap.xml")
def serve_sitemap():
    return send_from_directory(".", "sitemap.xml")


# =============================================================================
# Wire every callback module to the app
# =============================================================================
register_all(app)


# =============================================================================
# Run
# =============================================================================
if __name__ == "__main__":
    debug_mode = os.environ.get("TALLYAERO_DEBUG", "1") == "1"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8051
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
