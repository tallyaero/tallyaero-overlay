"""URL routing + viewport-width tracking + legal-modal triggers + windsock.

These are layout-shell callbacks that don't fit cleanly in the
domain-specific modules (aircraft/environment/map/maneuvers). They live
together here because each one wires interactivity to a global-shell
component: the URL bar, the modal stack, the windsock corner widget.
"""

from __future__ import annotations

from dash import (
    html, Input, Output, State, ALL, MATCH, ctx, no_update, callback,
)
from dash.exceptions import PreventUpdate

from layouts.desktop import desktop_layout
from layouts.mobile import mobile_layout


def register(app):
    """Install navigation/shell callbacks against the given Dash app."""

    # === Clear all map drawings + route UI when maneuver changes ====
    # Selecting a new maneuver should give the user a clean slate —
    # no leftover glide corridor, route polyline, scrubber path,
    # pending GPS waypoint dots, or route summary banner/strip from
    # whatever they were doing before. Per-maneuver dcc.Store point
    # stores (e.g. engineout touchdown/start) are intentionally NOT
    # cleared so the pilot can toggle back without redoing clicks.
    @app.callback(
        Output("layer", "children", allow_duplicate=True),
        Output("scrubber-layer", "children", allow_duplicate=True),
        Output("route-layer", "children", allow_duplicate=True),
        Output("route-pending-markers", "children", allow_duplicate=True),
        Output("route-top-banner", "children", allow_duplicate=True),
        Output("route-below-strip", "children", allow_duplicate=True),
        Output("nav-log-content", "children", allow_duplicate=True),
        Output("route-result-store", "data", allow_duplicate=True),
        Input("maneuver-select", "value"),
        prevent_initial_call=True,
    )
    def clear_map_on_maneuver_switch(_maneuver):
        return [], [], [], [], None, None, None, None

    # === Clientside: viewport width detector (fires on pathname change) ===
    app.clientside_callback(
        """
        function(_) {
            return window.innerWidth;
        }
        """,
        Output("screen-width", "data"),
        Input("url", "pathname"),
    )

    # === Page router ===
    @app.callback(
        Output("page-content", "children"),
        Input("url", "pathname"),
        Input("screen-width", "data"),
    )
    def display_page(pathname, screen_width):
        if screen_width is None:
            screen_width = 1024  # assume desktop by default

        is_mobile = screen_width < 768  # BREAKPOINT: 768px

        # Route to EM subapp when path starts with /em. App.py exposes
        # the EM layout builders after subtree merge (Phase 3b). Falls
        # through to overlay when EM didn't load or path is /.
        try:
            from app import (
                EM_LOADED,
                em_diagram_layout,
                em_edit_aircraft_layout,
            )
        except ImportError:
            EM_LOADED = False
            em_diagram_layout = None
            em_edit_aircraft_layout = None

        path = (pathname or "/").rstrip("/")
        if EM_LOADED and path.startswith("/em"):
            if path in ("/em-edit-aircraft", "/em/edit-aircraft"):
                return em_edit_aircraft_layout()
            return em_diagram_layout(is_mobile=is_mobile)

        # Default: overlay layout (route planner + maneuvers).
        if is_mobile:
            return mobile_layout()
        else:
            return desktop_layout()

    # === Mobile settings collapse toggle ===
    @app.callback(
        Output("mobile-settings-collapse", "is_open"),
        Output("mobile-settings-toggle", "children"),
        Input("mobile-settings-toggle", "n_clicks"),
        State("mobile-settings-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_mobile_settings(n_clicks, is_open):
        if n_clicks:
            new_state = not is_open
            return new_state, "▲" if new_state else "▼"
        return is_open, "▼"

    # === Maneuver info modal — populated from MANEUVER_INFO dict ===
    #
    # Each entry is (title, {description: [...], controls: [(control, effect), ...]}).
    # The `controls` list documents which inputs actually move this
    # maneuver's result so students iterate intelligently instead of
    # blindly twiddling sliders. The lists were curated during the
    # 2026-05-21 audit — they reflect what the sim ACTUALLY consumes,
    # not the full sidebar's set of widgets. If a control is hidden by
    # `callbacks/sidebar.py` for this maneuver, it's deliberately
    # omitted here too (e.g. power slider for the angular-step ground-
    # reference sims).
    MANEUVER_INFO = {
        "route": (
            "Route Planner",
            {
                "description": [
                    "Multi-leg cross-country planning at the level of detail "
                    "a real flight needs — wind-corrected headings, glide "
                    "corridor, divert coverage, weather, airspace, and a "
                    "live engine-out drill you can scrub along the route.",
                    "It is a TRAINING + PRE-FLIGHT tool, not a substitute for "
                    "filing an actual plan or briefing with a real source.",
                ],
                "capabilities": [
                    ("Routing", [
                        "Great-circle legs between airports, VORs, fixes, or "
                        "GPS-typed points. Type / search / click to add.",
                        "Wind-triangle math per leg — TH, MH, GS, drift, "
                        "headwind/tailwind component, crosswind.",
                        "Magnetic variation pulled from the WMM at the leg "
                        "origin coordinates.",
                        "Density-altitude-aware TAS from your IAS at cruise.",
                    ]),
                    ("Weather", [
                        "METAR + winds-aloft column auto-fetched when you "
                        "pick an airport in the top bar. The 'LIVE' chip on "
                        "the Environment row confirms the source.",
                        "Per-sample live winds along the route (Open-Meteo "
                        "forecast) when the Live winds pill is on — so the "
                        "corridor and engine-out drill use the wind that "
                        "would actually exist at each point.",
                        "Density-altitude chip flags hot/high performance "
                        "degradation at the departure airport.",
                    ]),
                    ("Survivability", [
                        "Engine-out glide corridor along the entire route — "
                        "every point you could reach if the engine quit, "
                        "terrain-clipped against ridges. Shaded green.",
                        "Divert coverage — count of airports in glide + the "
                        "longest 'no-divert stretch' in NM.",
                        "Survivability score (0-100) blending corridor "
                        "coverage, terrain margin, landable terrain, and "
                        "divert availability.",
                        "Landable raster — slope ≤ threshold AND OSM-suitable "
                        "land cover AND inside the corridor. Forced-landing "
                        "options when no airport's available.",
                        "Water polygons inside the corridor (per AFH §18-7 "
                        "ditching guidance) — yes, even water counts.",
                    ]),
                    ("Engine-out drill", [
                        "Scrub a slider anywhere along the route to ask "
                        "\"what if the engine quit HERE?\"",
                        "Wind-stretched, terrain-clipped glide ring at the "
                        "route altitude at that point — identical math to "
                        "the corridor.",
                        "Airports in the ring are color-coded by margin "
                        "(green > 500 ft, amber ≤ 500 ft, gray outside).",
                        "The actual engine-out planner runs from the "
                        "scrubber position → best landing target. The same "
                        "high-key + low-key + pattern math the standalone "
                        "engine-out tool uses.",
                        "Always gives you a landing target — FAA AFH Ch. 18 "
                        "precedence: runway in glide → field in glide → "
                        "water (ditch) in glide → nearest-of-anything "
                        "outside the ring (red). Even with no good options, "
                        "the line tells you what your best is. Use this to "
                        "think through options BEFORE you fly — where am I "
                        "exposed? where's my out?",
                        "Glide-path color codes the outcome — green = "
                        "runway with margin, yellow = makes it but barely / "
                        "field or water with energy, red = below minimums "
                        "or committed to something you can't reach.",
                    ]),
                    ("Airspace + NOTAMs", [
                        "Class B/C/D, SUA, and TFR polygons clipped to the "
                        "current viewport with one-glance under/over/pierce "
                        "tagging.",
                        "NOTAM filter applied to the corridor strip + your "
                        "cruise altitude band + ETE window — only the "
                        "NOTAMs that actually matter to this flight.",
                    ]),
                    ("Nav log", [
                        "FAA Jeppesen-style checkpoint table with TAS, GS, "
                        "ETE, ATE, fuel burn, frequencies, ATIS, and the "
                        "departure/destination airport panels.",
                        "Altitude profile chart inside the modal.",
                        "Engine-out analysis appended (best target per leg, "
                        "min AGL in corridor, divert summary).",
                        "Printable via the Print button — designed to fit "
                        "two sides of letter paper.",
                    ]),
                    ("Save / open", [
                        "Save the route + perf inputs as JSON; reopen later "
                        "to skip retyping the whole setup.",
                    ]),
                ],
                "limits": [
                    "NOT a substitute for filing an actual VFR/IFR flight "
                    "plan or getting a real preflight briefing. Use 1800wxbrief "
                    "or your dispatcher for the real thing.",
                    "No IFR clearances, no instrument approach plates, no "
                    "missed-approach geometry.",
                    "METAR is one-shot at airport pick — not auto-refreshed. "
                    "Re-pick the airport to refresh.",
                    "Live winds aloft are FORECAST (Open-Meteo), not the "
                    "ACARS observation. Forecast skill degrades > 12 hours "
                    "out.",
                    "Off-field landing centroids come from OpenStreetMap "
                    "land-cover tagging — data quality varies regionally. "
                    "ALWAYS verify visually before committing in flight.",
                    "Glide ratio assumes CLEAN configuration with the prop "
                    "windmilling. Feathered or flap-extended performance is "
                    "different.",
                    "Doesn't model partial-power scenarios — sim is either "
                    "cruise (engine running) or engine-out (zero thrust).",
                    "Engine-out drill is geometric — assumes the pilot "
                    "actually flies the plan (reaches high-key on time, "
                    "rolls out within a few degrees). Real-world margins "
                    "are smaller. FAA-P-8740-44 commit altitude (400 ft "
                    "AGL) is the floor below which no turn-back is safe.",
                    "No real-time traffic or ADS-B integration.",
                    "Terrain DEM samples on a grid — narrow ridges or "
                    "towers between samples can be missed. Cross-check "
                    "against a sectional.",
                ],
                "controls": [
                    ("Waypoints (Route field)", "Type ICAO/IATA/name to add. Click 'Click to add' pill then click the map to drop intermediate waypoints. Endpoints must be airports."),
                    ("Cruise Alt", "MSL feet. Drives density-altitude TAS, glide corridor reach, and which airports fall inside the corridor."),
                    ("Cruise TAS / IAS", "TAS auto-fills from the aircraft's published cruise; override if practicing slow flight. IAS optional — derives from TAS if blank."),
                    ("Glide Ratio + Glide IAS", "From the aircraft's POH (best-glide IAS, glide ratio at MGW). Drives corridor width and engine-out reach."),
                    ("Climb IAS", "Vy (or Vx for terrain). Determines climb time-to-cruise leg of the profile."),
                    ("Engine-out mode (multi-engine only)", "SE / Glide / Both. Single-engine performance corridor vs glide corridor vs both layered."),
                    ("Corridor pill", "Master toggle for the glide corridor + landable + slope overlays. Off = clean route map."),
                    ("Live winds pill", "Use Open-Meteo per-sample winds aloft instead of the sidebar's scalar wind. Default ON."),
                    ("Landable pill", "Renders the green landable raster + blue water polygons. Also feeds the engine-out drill's off-field forced-landing options. Default ON."),
                    ("Max slope °", "Threshold for landable raster. 3° = land upslope only is fine; > 7° = too steep."),
                    ("Engine-out drill pill", "Reveals the route-scrubber slider. Drag to ask 'what if it failed here?' — terrain-clipped glide ring + planner output."),
                    ("Wind (dir / speed)", "Manual fallback when no airport is picked. Auto-overridden by METAR when you pick an airport."),
                    ("OAT + altimeter", "Density altitude → TAS conversion for the whole route."),
                    ("Aircraft", "Picks published Vy / Vx / cruise TAS / glide ratio / glide IAS for the planner."),
                    ("Map toggles", "Airports / Class B/C/D / SUA / TFR / VORs / Fixes — independent on/off. Declutter when the map gets busy."),
                ],
            },
        ),
        "impossible_turn": (
            "Impossible Turn",
            {
                "description": [
                    "Engine failure on takeoff: can you turn back to the runway?",
                    "Simulates the trade between altitude and turn radius at "
                    "bank-angle limits, with reaction time and descent rate.",
                    "If the rollout heading is too far off the runway, the turn "
                    "is flagged as unsuccessful regardless of altitude lost.",
                ],
                "controls": [
                    ("Reaction time", "Seconds of straight-ahead flight after failure before the turn begins — every extra second is altitude lost."),
                    ("Bank angle (turn-back)", "Steeper bank → tighter radius and faster heading change, but higher Vs in the turn."),
                    ("Runway / climb profile", "Sets the starting geometry (where the engine fails, distance to the threshold)."),
                    ("Weight (occupants + fuel)", "Heavier → higher Vs and worse glide ratio."),
                    ("Wind", "Crosswind drift through the turn; tailwind on the return leg shortens or lengthens the glide."),
                    ("Engine option", "Selects the variant — drives best-glide IAS and ratio on multi-engine airframes."),
                ],
            },
        ),
        "poweroff180": (
            "Power-Off 180",
            {
                "description": [
                    "Accuracy approach from downwind abeam the touchdown point.",
                    "Energy-based glide path with automatic slip if high.",
                    "ACS standard: -0 / +200 ft of the aim point.",
                ],
                "controls": [
                    ("Abeam distance", "Distance from the runway when the engine fails — wider = harder to make the field."),
                    ("Pattern altitude", "Starting energy. Below ~700 AGL the turn-radius math no longer fits a standard pattern."),
                    ("Touchdown point", "Where you're aiming; the simulator plans the glide to it."),
                    ("Wind", "Tailwind on base shortens the geometry; headwind on final extends the float."),
                    ("Weight", "Drives Vs and the load-factor-adjusted Vs-in-turn used for the safety gate."),
                ],
            },
        ),
        "engineout": (
            "Engine-Out Glide",
            {
                "description": [
                    "Best-glide reach to a chosen touchdown spot from a chosen "
                    "starting altitude and heading.",
                    "Wind-aware: wind-correction angle + drift is included.",
                    "Use to evaluate field-selection and approach options.",
                ],
                "controls": [
                    ("Starting altitude (AGL)", "Total energy available for the glide."),
                    ("Starting heading", "Initial direction — drives whether L or R is the shorter first turn to the field."),
                    ("Touchdown spot", "The chosen ground point. The simulator plans tangent entry to the high-key spiral."),
                    ("Flap / prop setting", "Clean vs flaps; windmilling vs feathered prop — both change glide ratio."),
                    ("Wind", "Bias toward upwind fields; tailwind on the final approach lengthens float."),
                    ("Weight", "Heavier → higher Vs but glide ratio approximately preserved (drag dominated)."),
                ],
            },
        ),
        "steep_turn": (
            "Steep Turns (45° / 50°)",
            {
                "description": [
                    "Constant-altitude turns at a fixed bank.",
                    "Load factor = 1 / cos(bank); stall speed scales as sqrt(n).",
                    "ACS: ±100 ft alt, ±10 kt IAS, ±10° rollout heading.",
                ],
                "controls": [
                    ("Bank angle (45° / 50°)", "Drives load factor and Vs in the turn directly."),
                    ("IAS (entry)", "Determines stall margin at the chosen bank."),
                    ("Power", "At design power (cruise) you maintain altitude; off-design drifts the sim."),
                    ("Sequence (L / R / L-R)", "Whether to do one direction or reverse direction mid-maneuver."),
                    ("Weight", "Higher weight → higher Vs and lower margin."),
                    ("Wind", "Crab through the turn; affects groundspeed but not the maneuver outcome."),
                ],
            },
        ),
        "chandelle": (
            "Chandelle",
            {
                "description": [
                    "Maximum-performance 180° climbing turn.",
                    "Constant bank in the first 90°, then constant pitch as bank "
                    "reduces to wings-level at the 180° point.",
                    "Completion near power-on stall, within ±10° of target.",
                ],
                "controls": [
                    ("Power", "Design power is 100%. Reduced power lowers altitude gained and can fail to reach the 180° exit at target IAS."),
                    ("Entry IAS", "Starts the energy budget — sets the target rollout IAS (just above Vs)."),
                    ("Engine option", "Multi-engine variants — total HP changes climb performance."),
                    ("Weight (occupants + fuel)", "Heavier → less excess thrust → less altitude gained."),
                    ("Density altitude (OAT + altimeter)", "Hot/high reduces engine output and TAS — alters ROC."),
                    ("Wind", "Drift through the climbing turn; doesn't affect the energy result, only ground track."),
                ],
            },
        ),
        "lazy8": (
            "Lazy Eight",
            {
                "description": [
                    "Symmetrical climbing/descending S — coordination at varying "
                    "airspeeds.",
                    "Max bank ~30° at the 90° point, max pitch ~10° at 45°.",
                    "Mirror entry and exit altitudes within ±100 ft.",
                ],
                "controls": [
                    ("Entry IAS", "Sets the energy budget — too low risks stall at the apex."),
                    ("Power", "Design power for level mirror; off-design causes altitude drift between cycles."),
                    ("Number of eights", "How many cycles to fly."),
                    ("Bank target", "The apex bank — POH dynamics determine roll-rate ramp."),
                    ("Weight", "Higher weight → higher Vs at the apex."),
                    ("Wind", "Drift through the figure-8; ground track distorts but altitude profile is preserved."),
                ],
            },
        ),
        "steep_spiral": (
            "Steep Spiral",
            {
                "description": [
                    "Gliding turn around a surface point, constant ground-track "
                    "radius, three full 360° turns minimum.",
                    "Constant best-glide IAS; bank varies with wind.",
                    "Finish no lower than 1500 ft AGL.",
                ],
                "controls": [
                    ("Reference point", "Click the ground point to orbit. Determines geometric center."),
                    ("Entry altitude (AGL)", "Total energy. Below ~5000 ft you may not complete 3 turns above the 1500-ft floor."),
                    ("Bank angle", "Base bank — sim modulates with wind. Steeper = tighter radius but shorter time per turn."),
                    ("Number of turns", "Minimum 3 per FAA. More turns lose more altitude."),
                    ("Power (residual)", "Stock ACS is idle. Above 5% residual is off-design and flagged."),
                    ("Wind", "Sets bank variation around the orbit — steeper downwind, shallower upwind."),
                    ("Weight", "Affects Vs and stall margin in the descending turn."),
                ],
            },
        ),
        "s_turn": (
            "S-Turns Across a Road",
            {
                "description": [
                    "Two equal semicircles on opposite sides of a road, ground-"
                    "speed compensation via varying bank.",
                    "Wings level momentarily as you cross.",
                    "Standard ground-reference maneuver from FAA AFH Ch. 7.",
                ],
                "controls": [
                    ("Reference line (2 clicks)", "Defines the line to cross. Bearing matters — perpendicular to wind is the ACS expectation."),
                    ("Number of S-turns", "Each S = 2 semicircles."),
                    ("Entry side + first turn", "Which side of the line to start on and which way to bank first."),
                    ("Base bank angle", "Reference value; sim caps actual bank at 45° (FAA ACS standard)."),
                    ("IAS", "Held constant. Drives Vs and the wind-corrected groundspeed range."),
                    ("Power", "Sets altitude maintenance during the turns (65% ≈ level; less = lose altitude)."),
                    ("Wind", "The whole point — drives bank variation. Stronger wind → larger bank swings."),
                    ("Weight", "Affects Vs and margin."),
                ],
            },
        ),
        "turns_point": (
            "Turns Around a Point",
            {
                "description": [
                    "Constant-radius ground turns around a chosen point.",
                    "Bank varies inversely with groundspeed — steepest downwind, "
                    "shallowest upwind.",
                    "Standard ground-reference maneuver from FAA AFH Ch. 7.",
                ],
                "controls": [
                    ("Center point", "Click the ground point to orbit."),
                    ("Orbit radius", "Tighter radius needs steeper bank — sim flags when geometry would demand > 45°."),
                    ("Direction (L / R)", "Pattern direction around the point."),
                    ("Entry heading", "Defaults to downwind entry; override for non-standard entries."),
                    ("Number of turns", "How many complete 360°."),
                    ("IAS", "Held constant. With wind, GS varies → bank varies."),
                    ("Wind", "The whole point — bank variation directly reflects wind triangle."),
                    ("Weight", "Affects Vs in the steepest (downwind) part of the orbit."),
                ],
            },
        ),
        "rect_course": (
            "Rectangular Course",
            {
                "description": [
                    "Wind-aware pattern around a rectangle on the ground.",
                    "Crab angles change leg by leg; pace via groundspeed.",
                    "Foundation for traffic-pattern flight.",
                ],
                "controls": [
                    ("4 corner clicks", "Defines the rectangle. Sim snaps to perfect right angles."),
                    ("Downwind edge", "Auto-picked from wind direction; override to fly a specific orientation."),
                    ("Direction (L / R)", "Standard left pattern or right."),
                    ("Number of circuits", "How many full loops."),
                    ("IAS", "Held constant. Drives groundspeed on each leg via the wind triangle."),
                    ("Wind", "Drives the per-leg crab and groundspeed (see the per-leg WCA table in results)."),
                    ("Weight", "Affects Vs and the load-factor-adjusted margin in the corner turns."),
                ],
            },
        ),
        "pylons": (
            "Eights on Pylons",
            {
                "description": [
                    "Two pylons with a pivotal-altitude geometry — wingtip stays "
                    "on each pylon through the turn.",
                    "Altitude = (groundspeed_kt)^2 / 11.3 (pivotal).",
                    "Commercial pilot ACS.",
                ],
                "controls": [
                    ("Pylon positions (2 clicks)", "Pylon spacing must be 3-6× turn radius for a clean figure-8. Sim errors below 2.5×."),
                    ("IAS", "Indirectly sets pivotal altitude via the GS chain (IAS → TAS at density alt → ±wind = GS). PA = GS² / 11.3. Choose IAS to land the resulting PA in the 600-1000 ft AGL band."),
                    ("Wind", "PA = GS² / 11.3 — so PA varies every degree around the orbit as GS changes (max downwind, min upwind). Stronger wind = wider PA range."),
                    ("Density altitude (OAT + altimeter)", "Hot/high → higher TAS for the same IAS → higher GS → higher PA."),
                    ("Bank angle", "Sets turn radius; combined with pylon spacing determines the figure-8 geometry. Doesn't affect PA."),
                    ("Number of eights", "How many figure-8 cycles."),
                    ("Weight", "Affects Vs but not PA (PA depends only on GS)."),
                ],
            },
        ),
    }

    @app.callback(
        Output("maneuver-info-modal", "is_open"),
        Output("maneuver-info-title", "children"),
        Output("maneuver-info-body", "children"),
        Input("open-maneuver-info", "n_clicks"),
        Input("close-maneuver-info", "n_clicks"),
        State("maneuver-select", "value"),
        State("maneuver-info-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_maneuver_info(open_clicks, close_clicks, maneuver, is_open):
        trigger = ctx.triggered_id
        if trigger == "close-maneuver-info":
            return False, no_update, no_update
        if trigger == "open-maneuver-info":
            DEFAULT = (
                "Maneuver Info",
                {
                    "description": ["Pick a maneuver from the dropdown to see its details."],
                    "controls": [],
                },
            )
            title, info = MANEUVER_INFO.get(maneuver, DEFAULT)
            # Backwards-compat: old entries were `(title, [bullets])` tuples.
            if isinstance(info, list):
                info = {"description": info, "controls": []}

            description = info.get("description", []) or []
            capabilities = info.get("capabilities", []) or []
            limits = info.get("limits", []) or []
            controls = info.get("controls", []) or []

            body_children = []
            if description:
                body_children.append(html.Ul(
                    [html.Li(b) for b in description],
                    style={"fontSize": "13px", "lineHeight": "1.55", "marginTop": "4px"},
                ))

            # Capabilities — what the tool actually does, grouped into
            # named sub-sections so the pilot can scan by category.
            # Schema: list of (section_title, [bullet, ...]) pairs.
            if capabilities:
                body_children.append(html.Div(
                    "What it does",
                    style={
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.06em",
                        "color": "var(--ta-text-muted, #6b7280)",
                        "marginTop": "14px",
                        "marginBottom": "6px",
                        "borderTop": "1px solid var(--ta-border, #e5e7eb)",
                        "paddingTop": "10px",
                    },
                ))
                cap_children = []
                for section_title, bullets in capabilities:
                    cap_children.append(html.Div(
                        section_title,
                        style={
                            "fontSize": "12px",
                            "fontWeight": "600",
                            "color": "var(--ta-text, #1e293b)",
                            "marginTop": "8px",
                            "marginBottom": "2px",
                        },
                    ))
                    cap_children.append(html.Ul(
                        [html.Li(b) for b in (bullets or [])],
                        style={
                            "fontSize": "12px",
                            "lineHeight": "1.5",
                            "marginTop": "2px",
                            "marginBottom": "4px",
                            "paddingLeft": "20px",
                        },
                    ))
                body_children.append(html.Div(cap_children))

            # Limits — what the tool DOESN'T do. As important as the
            # capabilities list; explicitly framed so the pilot doesn't
            # mistake this for a substitute for real briefing tools.
            if limits:
                body_children.append(html.Div(
                    "What it doesn't do",
                    style={
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.06em",
                        "color": "var(--acs-marginal, #b45309)",
                        "marginTop": "14px",
                        "marginBottom": "6px",
                        "borderTop": "1px solid var(--ta-border, #e5e7eb)",
                        "paddingTop": "10px",
                    },
                ))
                body_children.append(html.Ul(
                    [html.Li(b) for b in limits],
                    style={
                        "fontSize": "12px",
                        "lineHeight": "1.5",
                        "marginTop": "2px",
                        "color": "var(--ta-text, #1e293b)",
                        "paddingLeft": "20px",
                    },
                ))

            if controls:
                # Heading for the controls section.
                body_children.append(html.Div(
                    "Controls that affect outcome",
                    style={
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.06em",
                        "color": "var(--ta-text-muted, #6b7280)",
                        "marginTop": "12px",
                        "marginBottom": "6px",
                        "borderTop": "1px solid var(--ta-border, #e5e7eb)",
                        "paddingTop": "10px",
                    },
                ))
                # Two-column control + effect grid for scanability.
                body_children.append(html.Div(
                    [
                        html.Div(
                            [
                                html.Div(name, style={
                                    "fontSize": "12px",
                                    "fontWeight": "600",
                                    "color": "var(--ta-text, #1e293b)",
                                    "minWidth": "150px",
                                    "paddingRight": "10px",
                                }),
                                html.Div(effect, style={
                                    "fontSize": "12px",
                                    "color": "var(--ta-text, #1e293b)",
                                    "lineHeight": "1.4",
                                    "flex": "1",
                                }),
                            ],
                            style={
                                "display": "flex",
                                "padding": "5px 0",
                                "borderBottom": "1px solid var(--ta-border-soft, #f1f5f9)",
                            },
                        )
                        for name, effect in controls
                    ],
                    style={"display": "block"},
                ))

            body = html.Div(body_children)
            return True, title, body
        return is_open, no_update, no_update

    # === Pattern-matched: per-maneuver Simulation Results modal toggle.
    # The button + close-button + modal each carry the same m_id so MATCH
    # routes the click to the right modal. Triggered by either button, we
    # just flip is_open; the modal's own close-X button keeps working too.
    @app.callback(
        Output({"type": "sim-results-modal", "m_id": MATCH}, "is_open"),
        Input({"type": "sim-results-btn", "m_id": MATCH}, "n_clicks"),
        Input({"type": "sim-results-close-btn", "m_id": MATCH}, "n_clicks"),
        State({"type": "sim-results-modal", "m_id": MATCH}, "is_open"),
        prevent_initial_call=True,
    )
    def toggle_sim_results_modal(open_clicks, close_clicks, is_open):
        trig = ctx.triggered_id or {}
        if trig.get("type") == "sim-results-btn":
            return True
        if trig.get("type") == "sim-results-close-btn":
            return False
        return is_open

    # === Clientside: sidebar collapse (DOM-class toggle) ===
    app.clientside_callback(
        """
        function(n_clicks, is_collapsed) {
            if (n_clicks === undefined || n_clicks === null) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }

            const sidebar = document.getElementById('sidebar');
            const new_collapsed = !is_collapsed;

            if (new_collapsed) {
                sidebar.classList.add('collapsed');
                return [new_collapsed, '»'];
            } else {
                sidebar.classList.remove('collapsed');
                return [new_collapsed, '«'];
            }
        }
        """,
        Output("sidebar-collapsed-store", "data"),
        Output("sidebar-collapse-btn", "children"),
        Input("sidebar-collapse-btn", "n_clicks"),
        State("sidebar-collapsed-store", "data"),
        prevent_initial_call=True,
    )

    # Append an `overlay-for-<maneuver>` class to the map-controls
    # overlay so CSS can show/hide per-maneuver overlay components
    # (Glide Ring toggle for engineout, etc.) without depending on
    # the per-maneuver layout being mounted.
    @app.callback(
        Output("map-controls-overlay", "className"),
        Input("maneuver-select", "value"),
    )
    def reflect_maneuver_into_overlay_class(maneuver):
        base = "map-controls-overlay"
        if maneuver:
            return f"{base} overlay-for-{maneuver}"
        return base

    # === Reset-all / reset-clicks ===
    #
    # Both buttons clear the SHARED state that's always in the DOM:
    # point stores, the drawn path on the map, the scrubber + envelope
    # layers, the bounds, the active-click-target arming, and the
    # last-click-info store. That's enough to unstick the "set new
    # start does nothing" symptom the user reported (the bug was the
    # active-click-target / layer state holding stale data, not the
    # per-maneuver hover stores).
    #
    # We do NOT clear per-maneuver UI state (hover-stores, info
    # panels, slider visibility, Results button colors, etc.). Those
    # ids only exist in the DOM when their maneuver is the currently-
    # mounted one in maneuver-params-container; the moment the user
    # switches maneuvers, render_maneuver_layout re-renders that
    # maneuver's layout with fresh defaults, so the "stale" state
    # naturally resets. Trying to clear those ids from a single
    # Reset callback caused the Dash renderer to error out with
    # "nonexistent object used in an Output" when the currently
    # mounted maneuver wasn't the one being targeted.
    #
    # Both buttons go through one callback because Dash needs a
    # single source-of-truth for the shared Outputs.
    @callback(
        Output({"type": "point-store", "m_id": ALL, "role": ALL}, "data", allow_duplicate=True),
        Output("active-click-target", "data", allow_duplicate=True),
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("scrubber-layer", "children", allow_duplicate=True),
        Output("envelope-layer", "children", allow_duplicate=True),
        Output("last-click-info", "data", allow_duplicate=True),
        Input("reset-all", "n_clicks"),
        Input("reset-clicks", "n_clicks"),
        State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
        prevent_initial_call=True,
    )
    def handle_resets(n_reset_all, n_reset_clicks, store_ids):
        trigger = ctx.triggered_id
        if trigger not in ("reset-all", "reset-clicks"):
            raise PreventUpdate

        cleared_points = [None] * len(store_ids)
        return (
            cleared_points,
            None,   # active-click-target
            [],     # layer
            None,   # map.bounds
            [],     # scrubber-layer
            [],     # envelope-layer
            None,   # last-click-info
        )

    # === Legal modal stack: disclaimer / terms-policy / quickstart ===
    @app.callback(
        Output("disclaimer-modal", "is_open"),
        Output("terms-policy-modal", "is_open"),
        Output("quickstart-modal", "is_open"),
        Input("open-disclaimer", "n_clicks"),
        Input("close-disclaimer", "n_clicks"),
        Input("open-terms-policy", "n_clicks"),
        Input("close-terms-policy", "n_clicks"),
        Input("open-quickstart", "n_clicks"),
        Input("close-quickstart", "n_clicks"),
        State("disclaimer-modal", "is_open"),
        State("terms-policy-modal", "is_open"),
        State("quickstart-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_legal_modals(open_disc, close_disc, open_terms, close_terms, open_qs, close_qs, disc_open, terms_open, qs_open):
        trigger = ctx.triggered_id

        if trigger == "open-disclaimer":
            return True, False, False
        if trigger == "close-disclaimer":
            return False, terms_open, qs_open
        if trigger == "open-terms-policy":
            return disc_open, True, False
        if trigger == "close-terms-policy":
            return disc_open, False, qs_open
        if trigger == "open-quickstart":
            return False, False, True
        if trigger == "close-quickstart":
            return disc_open, terms_open, False

        return no_update, no_update, no_update

    # === Windsock indicator (corner overlay reflecting env wind dir/speed) ===
    @app.callback(
        Output("windsock-overlay", "children"),
        Input("env-wind-dir", "value"),
        Input("env-wind-speed", "value"),
        Input("url", "pathname"),  # Trigger on page load
    )
    def update_windsock(wind_dir, wind_speed, _pathname):
        """
        Update the windsock indicator based on wind direction and speed.
        Top-down view: length represents how extended the sock is.

        Wind speed indication (FAA standard):
        - Under 3 kt: very short (limp, hanging down)
        - 3 kt: ~20% extended
        - 6 kt: ~40% extended
        - 9 kt: ~60% extended
        - 12 kt: ~80% extended
        - 15+ kt: fully extended
        - 40+ kt: windsock blew away! 
        """
        # Parse values (use same defaults as input fields: dir=360, speed=0)
        wind_dir_val = float(wind_dir) if wind_dir not in [None, "", "null"] else 360
        wind_speed_val = float(wind_speed) if wind_speed not in [None, "", "null"] else 0

        # Easter egg: windsock blew away in extreme wind!
        if wind_speed_val > 40:
            label_text = f"{int(wind_dir_val):03d}° @ {int(wind_speed_val)} kt"
            return [
                html.Div(
                    "",
                    style={"fontSize": "32px", "width": "60px", "height": "60px", "display": "flex", "alignItems": "center", "justifyContent": "center"}
                ),
                html.Span(
                    label_text,
                    style={
                        "fontSize": "12px",
                        "fontWeight": "bold",
                        "color": "#333",
                        "whiteSpace": "nowrap",
                        "marginLeft": "4px"
                    }
                )
            ]

        # Wind FROM direction - windsock points in the direction wind is blowing TO
        sock_rotation = (wind_dir_val + 180) % 360
        # SVG sock points right (east=90°), so rotate accordingly
        svg_rotation = sock_rotation - 90

        # Calculate number of segments to show based on wind speed (FAA: 3 kt per segment, 5 segments)
        # 0 kt = 0 segments, 3 kt = 1, 6 kt = 2, 9 kt = 3, 12 kt = 4, 15+ kt = 5
        if wind_speed_val <= 4:
            num_visible = 0  # Calm wind (4 kts or less) shows limp sock
        else:
            num_visible = min(5, int((wind_speed_val + 2) / 3))  # +2 for rounding up at thresholds

        # SVG dimensions - square for clean rotation
        # Pivot point at center so windsock is always visible regardless of rotation
        svg_size = 60
        pivot_x = 30  # Center of SVG
        pivot_y = 30
        pole_length = 5
        pole_end_x = pivot_x + pole_length

        # Build segments - each segment is a tapered trapezoid
        # Full sock: 5 segments, each 5px wide, tapering from 10px (30% wider base) to 3px height
        segments_svg = ""
        segment_width = 5
        start_height = 10  # 30% wider than original 8px
        end_height = 3

        for i in range(num_visible):
            # Calculate this segment's position and size
            x1 = pole_end_x + i * segment_width
            x2 = x1 + segment_width

            # Taper calculation
            t1 = i / 5
            t2 = (i + 1) / 5
            h1 = start_height - (start_height - end_height) * t1
            h2 = start_height - (start_height - end_height) * t2

            # Trapezoid points (top-left, top-right, bottom-right, bottom-left)
            y1_top = pivot_y - h1 / 2
            y1_bot = pivot_y + h1 / 2
            y2_top = pivot_y - h2 / 2
            y2_bot = pivot_y + h2 / 2

            segments_svg += f'<polygon points="{x1},{y1_top} {x2},{y2_top} {x2},{y2_bot} {x1},{y1_bot}" fill="#FF6600" stroke="#CC5500" stroke-width="0.5"/>'

        # If no wind, show a small circle to indicate limp sock
        if num_visible == 0:
            segments_svg = f'<circle cx="{pole_end_x + 3}" cy="{pivot_y}" r="3" fill="#FF6600" stroke="#CC5500" stroke-width="0.5"/>'

        # Build windsock SVG - pivot point is at center so it's always visible
        windsock_svg = f'''
        <svg width="{svg_size}" height="{svg_size}" viewBox="0 0 {svg_size} {svg_size}"
             style="transform: rotate({svg_rotation}deg); transform-origin: {pivot_x}px {pivot_y}px;">
            <!-- Pole base (pivot point) -->
            <circle cx="{pivot_x}" cy="{pivot_y}" r="2.5" fill="#666"/>
            <!-- Pole arm -->
            <line x1="{pivot_x}" y1="{pivot_y}" x2="{pole_end_x}" y2="{pivot_y}" stroke="#666" stroke-width="2"/>
            <!-- Windsock segments (top-down view, length = extension) -->
            {segments_svg}
        </svg>
        '''

        # Format the label - always show exact values from input fields
        label_text = f"{int(wind_dir_val):03d}° @ {int(wind_speed_val)} kt"

        return [
            html.Div(
                html.Iframe(
                    srcDoc=f'<html><body style="margin:0;padding:0;overflow:hidden;background:transparent;">{windsock_svg}</body></html>',
                    style={"width": f"{svg_size}px", "height": f"{svg_size}px", "border": "none", "overflow": "hidden", "background": "transparent"}
                ),
                style={"width": f"{svg_size}px", "height": f"{svg_size}px", "flexShrink": "0"}
            ),
            html.Span(
                label_text,
                style={
                    "fontSize": "12px",
                    "fontWeight": "600",
                    "color": "#333",
                    "whiteSpace": "nowrap",
                }
            ),
        ]
