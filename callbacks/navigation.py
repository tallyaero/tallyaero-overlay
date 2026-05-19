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

    MANEUVER_INFO = {
        "route": (
            "Route Planner",
            [
                "Great-circle leg between two airports.",
                "Computes distance, true / magnetic course, true / magnetic "
                "heading (wind-corrected), groundspeed, and ETE.",
                "Magnetic variation pulled from the WMM at the origin "
                "coordinates; wind reads from the sidebar Environment row.",
            ],
        ),
        "impossible_turn": (
            "Impossible Turn",
            [
                "Engine failure on takeoff: can you turn back to the runway?",
                "Simulates the trade between altitude and turn radius at "
                "bank-angle limits, with reaction time and descent rate.",
                "If the rollout heading is too far off the runway, the turn "
                "is flagged as unsuccessful regardless of altitude lost.",
            ],
        ),
        "poweroff180": (
            "Power-Off 180",
            [
                "Accuracy approach from downwind abeam the touchdown point.",
                "Energy-based glide path with automatic slip if high.",
                "ACS standard: -0 / +200 ft of the aim point.",
            ],
        ),
        "engineout": (
            "Engine-Out Glide",
            [
                "Best-glide reach to a chosen touchdown spot from a chosen "
                "starting altitude and heading.",
                "Wind-aware: wind-correction angle + drift is included.",
                "Use to evaluate field-selection and approach options.",
            ],
        ),
        "steep_turn": (
            "Steep Turns (45° / 50°)",
            [
                "Constant-altitude turns at a fixed bank.",
                "Load factor = 1 / cos(bank); stall speed scales as sqrt(n).",
                "ACS: ±100 ft alt, ±10 kt IAS, ±10° rollout heading.",
            ],
        ),
        "chandelle": (
            "Chandelle",
            [
                "Maximum-performance 180° climbing turn.",
                "Constant bank in the first 90°, then constant pitch as bank "
                "reduces to wings-level at the 180° point.",
                "Completion near power-on stall, within ±10° of target.",
                "Design power: 100%. Reduced power lowers altitude gained "
                "and can fail to reach the 180° exit at target IAS.",
            ],
        ),
        "lazy8": (
            "Lazy Eight",
            [
                "Symmetrical climbing/descending S — coordination at varying "
                "airspeeds.",
                "Max bank ~30° at the 90° point, max pitch ~10° at 45°.",
                "Mirror entry and exit altitudes within ±100 ft.",
            ],
        ),
        "steep_spiral": (
            "Steep Spiral",
            [
                "Gliding turn around a surface point, constant ground-track "
                "radius, three full 360° turns minimum.",
                "Constant best-glide IAS; bank varies with wind.",
                "Finish no lower than 1500 ft AGL.",
            ],
        ),
        "s_turn": (
            "S-Turns Across a Road",
            [
                "Two equal semicircles on opposite sides of a road, ground-"
                "speed compensation via varying bank.",
                "Wings level momentarily as you cross.",
                "Standard ground-reference maneuver from FAA AFH Ch. 7.",
            ],
        ),
        "turns_point": (
            "Turns Around a Point",
            [
                "Constant-radius ground turns around a chosen point.",
                "Bank varies inversely with groundspeed — steepest downwind, "
                "shallowest upwind.",
                "Standard ground-reference maneuver from FAA AFH Ch. 7.",
            ],
        ),
        "rect_course": (
            "Rectangular Course",
            [
                "Wind-aware pattern around a rectangle on the ground.",
                "Crab angles change leg by leg; pace via groundspeed.",
                "Foundation for traffic-pattern flight.",
            ],
        ),
        "pylons": (
            "Eights on Pylons",
            [
                "Two pylons with a pivotal-altitude geometry — wingtip stays "
                "on each pylon through the turn.",
                "Altitude = (groundspeed_kt)^2 / 11.3 (pivotal).",
                "Commercial pilot ACS.",
            ],
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
            title, bullets = MANEUVER_INFO.get(
                maneuver,
                ("Maneuver Info", ["Pick a maneuver from the dropdown to see its details."]),
            )
            body = html.Ul([html.Li(b) for b in bullets], style={"fontSize": "13px", "lineHeight": "1.5"})
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

    # === Reset-all / reset-clicks: ===
    #
    # Reset Clicks: clears the click-armed state + every dropped point
    # marker, but KEEPS the simulation result (path, scrubber, info,
    # results modal contents). For when the user just wants to re-pick
    # the start/touchdown points without re-running the sim.
    #
    # Reset All: clears EVERYTHING — point stores, the drawn path on
    # the map, all per-maneuver hover/path/result stores, the scrubber
    # slider container visibility, info panels, click-status messages,
    # and the Results button colors. Puts the page back to the same
    # state as a fresh page load. Originally only cleared the same
    # five outputs as Reset Clicks, which left every maneuver's hover
    # store, slider visibility, button color, and info panel stale —
    # the user reported that after Reset All they couldn't drop a new
    # start point because some of that lingering state was interfering.
    #
    # Both buttons go through a single callback that switches behavior
    # on ctx.triggered_id.

    MANEUVER_PREFIXES = (
        "engineout", "poweroff180", "impossibleturn",
        "chandelle", "lazy8", "steepspiral", "steepturn",
        "turnspoint", "sturn", "rectcourse", "pylons",
    )
    SLIDER_DEFAULT_MARKS = {0: "Start", 100: "End"}
    BTN_BASE_CLASS = "shelf-action shelf-action-results"

    # Build per-maneuver Output lists so the callback signature stays
    # readable. Order matters and must match the return tuple.
    _maneuver_outputs = []
    for _p in MANEUVER_PREFIXES:
        _maneuver_outputs.extend([
            Output(f"{_p}-hover-store", "data", allow_duplicate=True),
            Output(f"{_p}-path-store", "data", allow_duplicate=True),
            Output(f"{_p}-info", "children", allow_duplicate=True),
            Output(f"{_p}-slider-container", "style", allow_duplicate=True),
            Output(f"{_p}-time-slider", "value", allow_duplicate=True),
            Output(f"{_p}-time-slider", "max", allow_duplicate=True),
            Output(f"{_p}-time-slider", "marks", allow_duplicate=True),
        ])

    @callback(
        # Shared targets — both Reset buttons write these.
        Output({"type": "point-store", "m_id": ALL, "role": ALL}, "data", allow_duplicate=True),
        Output("active-click-target", "data", allow_duplicate=True),
        Output("layer", "children", allow_duplicate=True),
        Output("map", "bounds", allow_duplicate=True),
        Output("scrubber-layer", "children", allow_duplicate=True),
        Output("last-click-info", "data", allow_duplicate=True),
        # Reset-All-only targets: per-maneuver UI state, results
        # buttons, status messages, plus engineout/impossible-turn
        # /rectcourse one-off readouts.
        Output({"type": "click-status", "m_id": ALL}, "children", allow_duplicate=True),
        Output({"type": "sim-results-btn", "m_id": ALL}, "className", allow_duplicate=True),
        Output("engineout-envelope-store", "data", allow_duplicate=True),
        Output("engineout-min-alt-result", "children", allow_duplicate=True),
        Output("impossibleturn-result", "children", allow_duplicate=True),
        Output("rectcourse-edge-visible-info", "children", allow_duplicate=True),
        *_maneuver_outputs,
        Input("reset-all", "n_clicks"),
        Input("reset-clicks", "n_clicks"),
        State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
        State({"type": "click-status", "m_id": ALL}, "id"),
        State({"type": "sim-results-btn", "m_id": ALL}, "id"),
        prevent_initial_call=True,
    )
    def handle_resets(n_reset_all, n_reset_clicks,
                       store_ids, status_ids, btn_ids):
        trigger = ctx.triggered_id
        if trigger not in ("reset-all", "reset-clicks"):
            raise PreventUpdate

        # ----- Shared cleanup (both buttons) -----
        cleared_points = [None] * len(store_ids)
        cleared_target = None
        cleared_layer: list = []
        cleared_bounds = None
        cleared_scrubber: list = []
        cleared_last_click = None

        shared = (cleared_points, cleared_target, cleared_layer,
                  cleared_bounds, cleared_scrubber, cleared_last_click)

        if trigger == "reset-clicks":
            # Reset Clicks: keep simulation results — feed no_update
            # for every per-maneuver / results-button / status output.
            status_passthrough = [no_update] * len(status_ids)
            btn_passthrough = [no_update] * len(btn_ids)
            maneuver_passthrough = [no_update] * len(_maneuver_outputs)
            return (
                *shared,
                status_passthrough, btn_passthrough,
                no_update,  # engineout-envelope-store
                no_update,  # engineout-min-alt-result
                no_update,  # impossibleturn-result
                no_update,  # rectcourse-edge-visible-info
                *maneuver_passthrough,
            )

        # ----- Reset All: full wipe -----
        status_cleared = [""] * len(status_ids)
        btn_cleared = [BTN_BASE_CLASS] * len(btn_ids)
        maneuver_cleared: list = []
        for _ in MANEUVER_PREFIXES:
            maneuver_cleared.extend([
                [],                              # hover-store
                [],                              # path-store
                "",                              # info
                {"display": "none"},             # slider-container style
                0,                               # time-slider value
                100,                             # time-slider max
                SLIDER_DEFAULT_MARKS,            # time-slider marks
            ])

        return (
            *shared,
            status_cleared, btn_cleared,
            [],   # engineout-envelope-store
            "",   # engineout-min-alt-result
            "",   # impossibleturn-result
            "",   # rectcourse-edge-visible-info
            *maneuver_cleared,
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
