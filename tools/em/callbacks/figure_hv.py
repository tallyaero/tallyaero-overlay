"""
Phase 5Z — h-V Energy Map.

Renders the OTHER canonical diagram from Boyd 1966 (and Rutowski 1954): the
altitude-vs-airspeed plane with constant-energy curves and the basic
envelope edges. The Maneuver Doghouse (`callbacks/figure.py`) plots turn-rate
vs IAS — this one plots altitude vs IAS — both share the same physics, just
different free variables.

Why this matters for the GA audience: the FAA Airplane Flying Handbook
Ch 4 "Energy Management" (added in the 2021 revision) uses *exactly* this
chart to teach trading altitude for airspeed. Up to now the AFH presents it
qualitatively; this module renders it quantitatively for any aircraft in
our fleet.

Skipped (deliberately) for the v1 ship:
    - Full Ps contour grid in the (h, V) plane. The constant-energy curves
      alone are the educational killer feature. Ps grid is the natural 5Z-2
      follow-up — same math as the existing Maneuver Doghouse Ps machinery,
      different free variables.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

import math
from core import (
    KTS_TO_FPS, FPS_TO_KTS, KTS_TO_MPH, g,
    aircraft_data,
    get_chart_palette,
    compute_air_density,
    compute_thrust_available,
    interpolate_stall_speed,
)


def _convert_speed(ias_kt: float | np.ndarray, unit: str):
    return ias_kt * KTS_TO_MPH if unit == "MPH" else ias_kt


def register(app):
    """Wire the h-V figure + tab-swap + target-pin callbacks."""
    from dash.dependencies import Input, Output, State
    from dash import callback_context, no_update

    @app.callback(
        Output("em-graph-hv", "figure"),
        Input("aircraft-select",      "value"),
        Input("config-select",        "value"),
        Input("category-select",      "value"),
        Input("stored-total-weight",  "data"),
        Input("altitude-slider",      "value"),
        Input("unit-select",          "data"),
        Input("theme-pref",           "data"),
        Input("hv-target-point",      "data"),
        # Phase 5AB-3: user's chosen reference IAS — drives the current-state
        # dot's X position. None = fall back to Vy.
        Input("ref-ias-kt",           "data"),
        # Phase 5Z-3: physics inputs so the h-V chart honors the same
        # power / atmosphere / engine state as the doghouse.
        Input("power-setting",        "value"),
        Input("prop-condition",       "data"),
        Input("oei-toggle",           "value"),
        Input("oat-input",            "value"),
        Input("altimeter-input",      "value"),
        Input("engine-select",        "value"),
        # Phase 5AB-7: flight path angle for the γ-sustainable contour
        Input("pitch-angle",          "value"),
        # Phase 5W: time horizon for the reachable-set overlay
        Input("hv-reach-seconds",     "data"),
        # Phase 5X: probabilistic margin bands on/off
        Input("hv-margins",           "data"),
    )
    def _render_hv(ac_name, config, category, total_weight, altitude_ft, unit, theme,
                   target_point, ref_ias_kt, power_fraction, prop_condition,
                   oei_toggle, oat_c, altimeter_inhg, engine_name, gamma_deg,
                   reach_seconds, show_margins):
        return build_hv_figure(
            ac_name, config, category, total_weight, altitude_ft, unit, theme,
            target_point,
            ref_ias_kt=ref_ias_kt,
            power_fraction=power_fraction,
            prop_condition=prop_condition,
            oei_active=("enabled" in (oei_toggle or [])),
            oat_c=oat_c,
            altimeter_inhg=altimeter_inhg,
            engine_name=engine_name,
            gamma_deg=gamma_deg,
            reach_seconds=reach_seconds,
            show_margins=bool(show_margins),
        )

    # Phase 5Z-2 + 5AA-click: click on the h-V chart has TWO modes.
    # Default mode (no modifier): drive the altitude slider to the click's
    # Y value — effectively moves the current-state dot to where you clicked
    # along the altitude axis. Shift-modifier (or the target chip) drops a
    # target instead. Click on the orange Current state marker clears target.
    @app.callback(
        Output("hv-target-point", "data"),
        Input("em-graph-hv",    "clickData"),
        Input("clear-hv-target","n_clicks"),
        Input("aircraft-select","value"),
        State("hv-target-mode", "data"),
        prevent_initial_call=True,
    )
    def _set_or_clear_target(click_data, clear_clicks, _ac_changed, target_mode):
        trig = callback_context.triggered_id
        if trig in ("clear-hv-target", "aircraft-select"):
            return None
        if not click_data or not click_data.get("points"):
            return no_update
        # Only drop a target when the user is in target-drop mode. In default
        # ("Move current state") mode the click drives the altitude slider
        # via a separate callback — see `_drive_altitude_from_click` below.
        if not target_mode:
            return no_update
        pt = click_data["points"][0]
        if pt.get("text") == "Current state" or pt.get("hovertext", "").startswith("Current operating"):
            return None
        return {"v_disp": float(pt["x"]), "h_ft": float(pt["y"])}

    # Phase 5AA-click + 5AB-3: default click mode — clicking on the h-V chart
    # writes the click's altitude (Y) into the altitude-slider AND the click's
    # IAS (X) into the ref-ias-kt store. Both axes update so the orange
    # current-state dot drags to the clicked (V, h). Without the IAS half of
    # this, the dot was stuck at Vy regardless of where the user clicked.
    @app.callback(
        Output("altitude-slider", "value", allow_duplicate=True),
        Output("ref-ias-kt",      "data",  allow_duplicate=True),
        Input("em-graph-hv",  "clickData"),
        State("hv-target-mode", "data"),
        State("altitude-slider", "min"),
        State("altitude-slider", "max"),
        State("unit-select",    "data"),
        prevent_initial_call=True,
    )
    def _drive_state_from_click(click_data, target_mode, alt_min, alt_max, unit):
        if target_mode:                       # target-drop mode — other CB handles it
            return no_update, no_update
        if not click_data or not click_data.get("points"):
            return no_update, no_update
        pt = click_data["points"][0]
        # Ignore clicks on the "Current state" marker itself
        if pt.get("hovertext", "").startswith("Current operating"):
            return no_update, no_update
        y = float(pt.get("y", 0))
        x = float(pt.get("x", 0))
        lo = alt_min if alt_min is not None else 0
        hi = alt_max if alt_max is not None else 35000
        snapped_alt = int(round(y / 100.0)) * 100
        snapped_alt = max(lo, min(hi, snapped_alt))
        # X is in display units (KIAS or MPH). Convert back to KIAS for the store.
        unit = (unit or "KIAS").upper()
        ref_ias = x / KTS_TO_MPH if unit == "MPH" else x
        return snapped_alt, round(ref_ias, 1)

    # Phase 5AB-3: clear the reference IAS when the user switches aircraft.
    # Otherwise a click on the previous aircraft's chart leaves a stale IAS
    # that may be outside the new aircraft's stall/Vne band.
    @app.callback(
        Output("ref-ias-kt", "data", allow_duplicate=True),
        Input("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def _reset_ref_ias_on_aircraft_change(_ac):
        return None

    # Phase 5AA-click: toggle target-drop mode via the new chip in chart-tabs.
    @app.callback(
        Output("hv-target-mode", "data"),
        Output("toggle-target-mode", "className"),
        Input("toggle-target-mode", "n_clicks"),
        State("hv-target-mode", "data"),
        prevent_initial_call=True,
    )
    def _toggle_target_mode(_n, current):
        new_mode = not bool(current)
        cls = "env-chip chart-tab" + (" chart-tab-active" if new_mode else "")
        return new_mode, cls

    # Phase 5W: cycle reachable-set time horizon. Off → 60 → 120 → 300 → Off.
    @app.callback(
        Output("hv-reach-seconds",  "data"),
        Output("toggle-reach",      "className"),
        Output("chip-reach-label",  "children"),
        Input("toggle-reach", "n_clicks"),
        State("hv-reach-seconds", "data"),
        prevent_initial_call=True,
    )
    def _cycle_reach(_n, current):
        order = [None, 60, 120, 300]
        idx = order.index(current) if current in order else 0
        nxt = order[(idx + 1) % len(order)]
        label = "Off" if nxt is None else f"{nxt}s"
        cls = "env-chip chart-tab" + ("" if nxt is None else " chart-tab-active")
        return nxt, cls, label

    # Phase 5X: toggle margin bands on/off.
    @app.callback(
        Output("hv-margins",         "data"),
        Output("toggle-margins",     "className"),
        Output("chip-margins-label", "children"),
        Input("toggle-margins", "n_clicks"),
        State("hv-margins", "data"),
        prevent_initial_call=True,
    )
    def _toggle_margins(_n, current):
        new_state = not bool(current)
        cls = "env-chip chart-tab" + (" chart-tab-active" if new_state else "")
        label = "On" if new_state else "Off"
        return new_state, cls, label

    @app.callback(
        Output("clear-hv-target", "style"),
        Input("hv-target-point", "data"),
        Input("chart-tab",        "data"),
    )
    def _toggle_clear_button(target, active_tab):
        if target and active_tab == "hv":
            return {"display": "inline-flex"}
        return {"display": "none"}

    # Phase 5AB-10: chips that only make sense on one chart should hide on the
    # other. Compare is a doghouse-only overlay; REACH / MARGINS / MODE all
    # operate on the energy map. Visibility is chart-tab driven.
    SHOW_CHIP = {"display": "inline-flex"}
    HIDE_CHIP = {"display": "none"}
    @app.callback(
        Output("chip-compare",       "style"),
        Output("toggle-target-mode", "style"),
        Output("toggle-reach",       "style"),
        Output("toggle-margins",     "style"),
        Input("chart-tab", "data"),
    )
    def _filter_chart_chips(active_tab):
        if active_tab == "hv":
            return HIDE_CHIP, SHOW_CHIP, SHOW_CHIP, SHOW_CHIP
        return SHOW_CHIP, HIDE_CHIP, HIDE_CHIP, HIDE_CHIP

    # Phase 5AB-11: rail controls that don't affect the active chart should
    # hide. Audit found CG is the only such control — h-V's render callback
    # never reads `cg-slider.value`. Atmosphere / Weight / Power / FPA all
    # affect both charts so they always stay visible.
    @app.callback(
        Output("cg-slider-container", "style"),
        Input("chart-tab", "data"),
    )
    def _filter_rail_cg(active_tab):
        if active_tab == "hv":
            return {"display": "none"}
        return {"display": "block"}

    SHOW = {"display": "block", "height": "100%", "width": "100%"}
    HIDE = {"display": "none"}

    @app.callback(
        Output("chart-tab",          "data"),
        Output("tab-chart-maneuver", "className"),
        Output("tab-chart-hv",       "className"),
        Output("em-graph",           "style"),
        Output("em-graph-hv",        "style"),
        Input("tab-chart-maneuver",  "n_clicks"),
        Input("tab-chart-hv",        "n_clicks"),
        prevent_initial_call=True,
    )
    def _swap_chart_tab(_n_maneuver, _n_hv):
        trig = callback_context.triggered_id
        if trig == "tab-chart-hv":
            return ("hv",
                    "env-chip chart-tab",
                    "env-chip chart-tab chart-tab-active",
                    HIDE, SHOW)
        # default / maneuver
        return ("maneuver",
                "env-chip chart-tab chart-tab-active",
                "env-chip chart-tab",
                SHOW, HIDE)


def _compute_ps_grid(ac, weight_lb, v_grid_kt, h_grid_ft, oat_c, altimeter_inhg,
                     power_fraction, prop_condition, oei_active, engine_name):
    """Phase 5Z-3 — compute specific excess power Ps over a (V, h) grid for
    LEVEL FLIGHT (n=1, gamma=0). Same physics as the doghouse, evaluated on
    the energy-map's free variables.

    Returns the Ps array (kt/sec), same shape as the (h, V) meshgrid.
    """
    # Aircraft constants
    wing_area = ac.get("wing_area", 175)
    cd0 = ac.get("CD0", 0.03)
    e   = ac.get("e", 0.8)
    ar  = ac.get("aspect_ratio", 7.5)
    cl_max_block = ac.get("CL_max", {})
    cl_max = cl_max_block.get("clean") or 1.4
    # Phase 2g: optional high-CL drag rise (steep turns near stall)
    cd_rise = ac.get("cd_rise_above_cl") or None
    cl_rise_th = cd_rise.get("cl_threshold") if cd_rise else None
    k_rise     = cd_rise.get("k_rise", 0.0) if cd_rise else 0.0

    # Engine + prop
    engines = ac.get("engine_options", {}) or {}
    if engine_name and engine_name in engines:
        eng = engines[engine_name]
    else:
        eng = next(iter(engines.values()), {})
    base_hp = eng.get("horsepower", 160)
    ptd = ac.get("prop_thrust_decay", {}) or {}
    t_static_factor = ptd.get("T_static_factor", 2.2)
    v_max_kts = ptd.get("V_max_kts") or ac.get("Vne") or 200

    # Effective HP — OEI halves it for twins; idle clamps power floor
    n_engines = ac.get("engine_count", 1)
    if oei_active and n_engines >= 2:
        usable_engines = max(1, n_engines - 1)
        net_hp = base_hp * (usable_engines / n_engines) * (power_fraction or 0.5)
    else:
        net_hp = base_hp * (power_fraction or 0.5)

    # Prop-condition drag delta — windmilling > stationary > feathered
    prop_drag_factor = {"feathered": 1.00, "stationary": 1.04, "windmilling": 1.08}.get(
        prop_condition or "feathered", 1.0
    )

    # Build (V, h) mesh
    mesh_v, mesh_h = np.meshgrid(v_grid_kt, h_grid_ft)
    ps_grid = np.zeros_like(mesh_v, dtype=float)

    for j in range(mesh_v.shape[0]):
        for i in range(mesh_v.shape[1]):
            V_kts = float(mesh_v[j, i])
            h     = float(mesh_h[j, i])
            # Density at this altitude using STANDARD atmosphere. Passing the
            # user's OAT here would treat it as the temperature AT every grid
            # altitude — overestimating density altitude and producing false
            # "unreachable" climbs. Standard atmosphere is the right floor.
            rho = compute_air_density(h, None)
            V_fps = V_kts * KTS_TO_FPS
            q = 0.5 * rho * V_fps * V_fps                       # dynamic pressure
            # Lift coefficient at n=1, then induced drag
            cl = min(weight_lb / (q * wing_area), cl_max) if q > 0 else 0
            cd = cd0 + (cl * cl) / (math.pi * ar * e)
            # Phase 2g: super-parabolic rise above CL threshold
            if cl_rise_th is not None and k_rise and cl > cl_rise_th:
                cd += k_rise * (cl - cl_rise_th) ** 2
            cd = cd * prop_drag_factor
            D = q * wing_area * cd
            # Thrust available at this V (engine power scales with density)
            density_ratio = rho / 0.002378
            T = compute_thrust_available(net_hp * density_ratio, V_kts, v_max_kts, t_static_factor)
            ps_fps = (T - D) * V_fps / weight_lb
            ps_grid[j, i] = ps_fps / KTS_TO_FPS  # → knots/sec

    return ps_grid


def build_hv_figure(
    ac_name: str | None,
    config: str | None,
    selected_category: str | None,
    total_weight: float | None,
    altitude_ft: float | None,
    unit: str | None,
    theme_pref: str | None,
    target_point: dict | None = None,
    *,
    ref_ias_kt: float | None = None,
    power_fraction: float | None = None,
    prop_condition: str | None = None,
    oei_active: bool = False,
    oat_c: float | None = None,
    altimeter_inhg: float | None = None,
    engine_name: str | None = None,
    gamma_deg: float | None = None,
    reach_seconds: int | None = None,
    show_margins: bool = False,
):
    """Return a Plotly figure for the h-V energy map.

    Args:
        ac_name: aircraft profile name
        config: flap config key (clean / takeoff / landing)
        selected_category: G-limit category (normal / utility / aerobatic)
        total_weight: current weight in lb
        altitude_ft: current altitude in feet MSL (rendered as a marker)
        unit: "KIAS" or "MPH"
        theme_pref: "light" or "dark"
    """
    palette = get_chart_palette(theme_pref)
    unit = (unit or "KIAS").upper()

    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor=palette["paper_bg"],
        plot_bgcolor=palette["plot_bg"],
        font=dict(color=palette["text"], family="Inter, system-ui, sans-serif"),
        margin=dict(l=50, r=40, t=60, b=80),
        xaxis=dict(
            title=f"Indicated Airspeed ({unit})",
            title_font=dict(size=13, color=palette["text"]),
            tickfont=dict(size=11, color=palette["tick"]),
            showgrid=True, gridcolor=palette["grid"],
            linecolor=palette["axis_line"], zerolinecolor=palette["grid"],
        ),
        yaxis=dict(
            title="Altitude (ft MSL)",
            title_font=dict(size=13, color=palette["text"]),
            tickfont=dict(size=11, color=palette["tick"]),
            showgrid=True, gridcolor=palette["grid"],
            linecolor=palette["axis_line"], zerolinecolor=palette["grid"],
        ),
        dragmode=False,
        hovermode="closest",
        hoverlabel=dict(
            bgcolor=palette["annotation_bg"],
            bordercolor=palette["grid"],
            font=dict(color=palette["text"], family="JetBrains Mono, Inter, sans-serif", size=12),
        ),
        transition=dict(duration=320, easing="cubic-in-out"),
        autosize=True,
        legend=dict(
            orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
            font=dict(size=11, color=palette["text"]),
            bgcolor=palette["annotation_bg"],
            bordercolor=palette["grid"],
            borderwidth=1,
        ),
    )

    # Empty state — no aircraft selected
    if not ac_name or ac_name not in aircraft_data:
        fig.update_layout(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            annotations=[dict(
                text="Select an aircraft to begin",
                showarrow=False,
                font=dict(size=14, color=palette["muted"]),
                xref="paper", yref="paper", x=0.5, y=0.5,
            )],
            margin=dict(l=0, r=0, t=0, b=0),
        )
        fig.update_layout(title=dict(text="", font=dict(size=22)))
        return fig

    ac = aircraft_data[ac_name]
    config = config or "clean"
    selected_category = selected_category or "normal"

    # Pull aircraft parameters
    vne_kt = ac.get("Vne") or 200
    vno_kt = ac.get("Vno") or vne_kt * 0.85
    max_altitude_ft = ac.get("max_altitude") or 25000
    weight_lb = total_weight or ac.get("max_weight") or 2500
    wing_area = ac.get("wing_area") or 175

    # Stall speed in current flap config — interpolated from the stall table
    cl_max_block = ac.get("CL_max", {})
    cl_max = cl_max_block.get(config) or cl_max_block.get("clean") or 1.4
    stall_table = (ac.get("stall_speeds") or {}).get(config) \
                  or (ac.get("stall_speeds") or {}).get("clean")
    try:
        vs1g_sl = interpolate_stall_speed(stall_table or {}, weight_lb) if stall_table else 50
    except Exception:
        vs1g_sl = 50

    # Display-unit conversions
    vne_disp     = _convert_speed(vne_kt, unit)
    vno_disp     = _convert_speed(vno_kt, unit)
    vs1g_sl_disp = _convert_speed(vs1g_sl, unit)

    # ── Stall boundary at altitude ─────────────────────────────────────────
    # Vs (IAS) is mostly constant with altitude (IAS already accounts for
    # density), so the stall line is approximately vertical at vs1g_sl_disp.
    # Phase 5X: when margins are on, render as a ±5 KIAS band reflecting
    # 14 CFR 23.207 stall-warning margin + typical CL_max variance.
    if show_margins:
        # Convert ±5 KIAS to display units
        delta = 5.0 * (KTS_TO_MPH if unit == "MPH" else 1.0)
        x_low  = max(0, vs1g_sl_disp - delta)
        x_high = vs1g_sl_disp + delta
        fig.add_trace(go.Scatter(
            x=[x_low, x_high, x_high, x_low, x_low],
            y=[0, 0, max_altitude_ft, max_altitude_ft, 0],
            mode="lines",
            line=dict(color="#DC143C", width=0),
            fill="toself",
            fillcolor="rgba(220, 20, 60, 0.18)",
            name=f"Vs band (±5 {unit})",
            hoverinfo="text",
            hovertext=(f"Stall margin band<br>"
                       f"published Vs1G ≈ {vs1g_sl_disp:.0f} {unit}<br>"
                       f"±5 {unit} — 14 CFR 23.207 + CL_max variance"),
            showlegend=True,
        ))
    # Always draw the nominal Vs line so it's a clean reference whether the
    # band is on or off.
    fig.add_trace(go.Scatter(
        x=[vs1g_sl_disp, vs1g_sl_disp],
        y=[0, max_altitude_ft],
        mode="lines",
        line=dict(color="#DC143C", width=3),
        name=f"Vs (1G) — {vs1g_sl_disp:.0f} {unit}",
        hoverinfo="text",
        hovertext=f"Stall speed at 1G<br>{vs1g_sl_disp:.0f} {unit}",
    ))

    # ── Vne vertical (right edge) ──────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=[vne_disp, vne_disp],
        y=[0, max_altitude_ft],
        mode="lines",
        line=dict(color=palette["fg"], width=3, dash="dash"),
        name=f"Vne — {vne_disp:.0f} {unit}",
        hoverinfo="text",
        hovertext=f"Never exceed speed<br>{vne_disp:.0f} {unit}",
    ))

    # ── Service ceiling (horizontal at max_altitude) ──────────────────────
    # Phase 5X: when margins on, render as a ±500 ft band reflecting
    # atmospheric-day variance + weight (cold day pushes ceiling up).
    if show_margins:
        band = 500
        fig.add_trace(go.Scatter(
            x=[vs1g_sl_disp, vne_disp, vne_disp, vs1g_sl_disp, vs1g_sl_disp],
            y=[max_altitude_ft - band, max_altitude_ft - band,
               max_altitude_ft + band, max_altitude_ft + band,
               max_altitude_ft - band],
            mode="lines",
            line=dict(color=palette["fg"], width=0),
            fill="toself",
            fillcolor="rgba(100, 116, 139, 0.18)",
            name=f"Ceiling band (±{band} ft)",
            hoverinfo="text",
            hovertext=(f"Service ceiling margin<br>"
                       f"published {max_altitude_ft:,} ft<br>"
                       f"±{band} ft — atmosphere/weight variance"),
            showlegend=True,
        ))
    fig.add_trace(go.Scatter(
        x=[vs1g_sl_disp, vne_disp],
        y=[max_altitude_ft, max_altitude_ft],
        mode="lines",
        line=dict(color=palette["fg"], width=2, dash="dot"),
        name=f"Service ceiling — {max_altitude_ft:,} ft",
        hoverinfo="text",
        hovertext=f"Service ceiling<br>{max_altitude_ft:,} ft",
    ))

    # ── Phase 5Z-3 — Ps contour grid (the physics layer) ─────────────────
    # At each (V, h), compute specific excess power assuming level flight
    # (n=1). Positive Ps = climbing capacity at current power; Ps = 0 line
    # is the sustained ceiling at this power setting; negative = bleeding
    # energy. We render the Ps surface as a Plotly contour with a diverging
    # palette centered on zero.
    ps_v_grid_kt = np.linspace(vs1g_sl, vne_kt, 36)
    ps_h_grid_ft = np.linspace(0, max_altitude_ft, 28)
    try:
        ps_grid = _compute_ps_grid(
            ac, weight_lb, ps_v_grid_kt, ps_h_grid_ft,
            oat_c, altimeter_inhg, power_fraction, prop_condition,
            oei_active, engine_name,
        )
    except Exception:
        ps_grid = None

    if ps_grid is not None:
        # Display-unit X
        ps_v_disp = _convert_speed(ps_v_grid_kt, unit)
        ps_min = float(np.min(ps_grid))
        ps_max = float(np.max(ps_grid))
        # Diverging RdBu-style colorscale centered on Ps=0.
        # Negative = red (energy bleed), zero = transparent, positive = green
        # (energy gain). Phase 5AA: surface the colorbar as the key so users
        # know what the shading represents.
        fig.add_trace(go.Contour(
            x=ps_v_disp,
            y=ps_h_grid_ft,
            z=ps_grid,
            colorscale=[
                [0.0,  "rgba(220, 53, 69, 0.55)"],   # strong negative — red
                [0.5,  "rgba(255, 255, 255, 0.0)"],  # zero — transparent
                [1.0,  "rgba(34, 197, 94, 0.55)"],   # strong positive — green
            ],
            zmid=0,
            zmin=max(-10, ps_min),                   # clip extremes
            zmax=min( 10, ps_max),
            contours=dict(
                coloring="fill",
                showlines=False,
                start=-10, end=10, size=2.0,
            ),
            showscale=True,
            colorbar=dict(
                title=dict(
                    text=f"Ps<br>kt/sec",
                    font=dict(size=10, color=palette["tick"],
                              family="JetBrains Mono, Inter, sans-serif"),
                    side="top",
                ),
                tickfont=dict(size=9, color=palette["tick"],
                              family="JetBrains Mono, Inter, sans-serif"),
                tickvals=[-10, -5, 0, 5, 10],
                ticktext=["−10", "−5", "0 (ceiling)", "+5", "+10"],
                x=1.02, xanchor="left",
                y=0.5, len=0.55, thickness=10,
                outlinewidth=0,
            ),
            hoverinfo="skip",
            name="Ps grid",
            showlegend=False,
        ))

        # ── Ps = 0 line — the sustained ceiling at this power setting ───
        # Bold so it reads as the operational limit it actually is.
        fig.add_trace(go.Contour(
            x=ps_v_disp,
            y=ps_h_grid_ft,
            z=ps_grid,
            contours=dict(
                coloring="none",
                showlines=True,
                showlabels=False,
                start=0, end=0, size=1,
            ),
            line=dict(color="#0a47c9", width=2.5, dash="solid"),
            showscale=False,
            hoverinfo="skip",
            name="Ps = 0 (sustained ceiling)",
            showlegend=True,
        ))

        # ── Phase 5AB-7: γ-sustainable contour ──────────────────────────
        # At sustained flight path angle γ, the aircraft consumes V·sin(γ) of
        # its available specific excess power maintaining the climb (or gains
        # it when descending). So the SUSTAINABLE-γ contour is the set of
        # (V, h) where Ps_available(V, h) = V·sin(γ).
        #
        # Hidden when |γ| < 1° because it would coincide with the Ps=0 line.
        #
        # Implementation: walk each V column, linearly interpolate to find h
        # where Ps_grid(V, h) crosses V·sin(γ). go.Scatter is used (not
        # go.Contour) so the legend entry stays visible even when the curve
        # has no points at the current power — it then reads as "this γ
        # isn't sustainable anywhere at this power."
        gamma = float(gamma_deg or 0)
        if abs(gamma) >= 1.0:
            gamma_rad = math.radians(gamma)
            v_pts: list[float] = []
            h_pts: list[float] = []
            for i, v_kt in enumerate(ps_v_grid_kt):
                target = float(v_kt) * math.sin(gamma_rad)
                col = ps_grid[:, i]
                diff = col - target
                signs = np.sign(diff)
                # find indices where the sign flips between consecutive rows
                changes = np.where(np.diff(signs) != 0)[0]
                for k in changes:
                    d_lo, d_hi = float(diff[k]), float(diff[k + 1])
                    if d_lo == d_hi:
                        continue
                    t = d_lo / (d_lo - d_hi)        # 0..1
                    h_lo = float(ps_h_grid_ft[k])
                    h_hi = float(ps_h_grid_ft[k + 1])
                    h_cross = h_lo + t * (h_hi - h_lo)
                    v_pts.append(float(v_kt))
                    h_pts.append(h_cross)

            verb = "climb" if gamma > 0 else "descent"
            contour_color = "#f97316" if gamma > 0 else "#16a34a"
            v_disp_pts = _convert_speed(np.array(v_pts) if v_pts else np.array([]), unit)

            fig.add_trace(go.Scatter(
                x=list(v_disp_pts),
                y=h_pts,
                mode="lines+markers",
                line=dict(color=contour_color, width=2.2, dash="dash"),
                marker=dict(color=contour_color, size=4, symbol="circle"),
                name=f"Sustain γ = {gamma:+.0f}° {verb}",
                hoverinfo="text",
                hovertext=[(f"Sustainable {verb} at γ = {gamma:+.0f}°<br>"
                            f"V = {_convert_speed(v, unit):.0f} {unit}<br>"
                            f"h = {int(h):,} ft")
                           for v, h in zip(v_pts, h_pts)],
                showlegend=True,
            ))
            # If the curve had no points at all, drop a short note explaining
            # so users don't think the toggle is broken.
            if not v_pts:
                fig.add_annotation(
                    x=0.5, y=1.04, xref="paper", yref="paper",
                    showarrow=False,
                    text=f"γ = {gamma:+.0f}° not sustainable anywhere at this power",
                    font=dict(size=10, color=contour_color,
                              family="JetBrains Mono, Inter, sans-serif"),
                    bgcolor=palette["annotation_bg"],
                    bordercolor=contour_color, borderwidth=1, borderpad=4,
                )

    # ── Constant-energy curves (the educational killer feature) ───────────
    # E = h + V²/(2g) where V is in fps, h in ft. Solving for h at a fixed E:
    #     h = E - V²/(2g)
    # Iso-energy curves are downward-opening parabolas in (V, h) space.
    # We pick a handful of energy levels that span the chart and draw each.
    e_max_ft = max_altitude_ft + (vne_kt * KTS_TO_FPS) ** 2 / (2 * g)
    # Levels evenly spaced from a low value up to e_max
    e_levels = np.linspace(1000, e_max_ft, 8)
    v_grid_kt = np.linspace(vs1g_sl, vne_kt, 80)
    v_grid_fps = v_grid_kt * KTS_TO_FPS
    v_grid_disp = _convert_speed(v_grid_kt, unit)

    for i, e_ft in enumerate(e_levels):
        h_curve = e_ft - (v_grid_fps ** 2) / (2 * g)
        # Mask values outside the chart
        valid = (h_curve >= 0) & (h_curve <= max_altitude_ft)
        if not np.any(valid):
            continue
        fig.add_trace(go.Scatter(
            x=v_grid_disp[valid],
            y=h_curve[valid],
            mode="lines",
            line=dict(color=palette["muted"], width=1.2, dash="dot"),
            name="E contour" if i == 0 else None,
            showlegend=(i == 0),
            hoverinfo="text",
            hovertext=[f"E = {e_ft:,.0f} ft<br>V = {v_disp:.0f} {unit}<br>h = {h:.0f} ft"
                       for v_disp, h in zip(v_grid_disp[valid], h_curve[valid])],
        ))
        # Label each contour near its rightmost visible point
        last_idx = np.where(valid)[0]
        if len(last_idx) > 0:
            li = last_idx[len(last_idx) // 2]
            fig.add_annotation(
                x=v_grid_disp[li],
                y=h_curve[li],
                text=f"{int(e_ft):,} ft",
                showarrow=False,
                font=dict(color=palette["muted"], size=9,
                          family="JetBrains Mono, Inter, sans-serif"),
                bgcolor=palette["annotation_bg"],
                borderpad=0,
                opacity=0.85,
            )

    # ── Current operating point marker ─────────────────────────────────────
    # User-driven altitude + IAS. If `ref_ias_kt` is None we fall back to the
    # aircraft's Vy so the dot still has a sane initial position; clicks on
    # the chart (in move-current-state mode) write `ref-ias-kt` so the dot
    # drags to the clicked (V, h).
    cur_alt = altitude_ft or 0
    fallback_ias = ac.get("Vy") or vno_kt or 100
    ref_ias = float(ref_ias_kt) if ref_ias_kt else fallback_ias
    # Clamp to envelope so a stale click on a previous aircraft can't put
    # the dot outside this aircraft's stall/Vne band.
    ref_ias = max(vs1g_sl, min(vne_kt, ref_ias))
    ref_label = "user" if ref_ias_kt else "at Vy"
    ref_ias_disp = _convert_speed(ref_ias, unit)
    cur_e = cur_alt + (ref_ias * KTS_TO_FPS) ** 2 / (2 * g)
    fig.add_trace(go.Scatter(
        x=[ref_ias_disp], y=[cur_alt],
        mode="markers",
        marker=dict(color="#f27b0d", size=14, symbol="circle",
                    line=dict(color=palette["paper_bg"], width=2)),
        name="Current state",
        hoverinfo="text",
        hovertext=(f"Current operating point<br>"
                   f"h = {int(cur_alt):,} ft (PE)<br>"
                   f"V = {ref_ias_disp:.0f} {unit} ({ref_label})<br>"
                   f"E = {int(cur_e):,} ft total"),
    ))

    # ── Phase 5W: Reachable set (energy-budget interpretation) ────────────
    # Given time horizon T and current state, render the band of (V, h) the
    # pilot could reach by:
    #   upper bound = E_now + Ps_max(full power) × T   (max climb)
    #   lower bound = E_now − |Ps(idle)| × T          (max bleed at idle)
    # These are constant-E parabolas on the (V, h) plane. The band between
    # them is the reachable set, clipped by stall / Vne / service ceiling.
    if reach_seconds and isinstance(reach_seconds, (int, float)) and reach_seconds > 0:
        try:
            ps_full = _compute_ps_grid(
                ac, weight_lb, ps_v_grid_kt, ps_h_grid_ft,
                oat_c, altimeter_inhg,
                1.0, prop_condition, oei_active, engine_name,
            )
            ps_idle_for_reach = _compute_ps_grid(
                ac, weight_lb, ps_v_grid_kt, ps_h_grid_ft,
                oat_c, altimeter_inhg,
                0.05, prop_condition, oei_active, engine_name,
            )
            j_cur = int(np.clip(np.searchsorted(ps_h_grid_ft, cur_alt), 0, len(ps_h_grid_ft) - 1))
            i_cur = int(np.clip(np.searchsorted(ps_v_grid_kt, ref_ias), 0, len(ps_v_grid_kt) - 1))
            ps_full_now = float(ps_full[j_cur, i_cur])      # kt/sec
            ps_idle_now = float(ps_idle_for_reach[j_cur, i_cur])
            # Max gain over T; cap at 0 if even full power can't climb here.
            de_gain = max(0.0, ps_full_now) * reach_seconds * KTS_TO_FPS
            de_loss = max(0.0, -ps_idle_now) * reach_seconds * KTS_TO_FPS
            e_upper = cur_e + de_gain
            e_lower = max(0.0, cur_e - de_loss)

            # Build the two iso-E parabolas across the V grid. h = E - V²/(2g).
            v_reach_grid_kt  = np.linspace(vs1g_sl, vne_kt, 120)
            v_reach_grid_fps = v_reach_grid_kt * KTS_TO_FPS
            v_reach_disp     = _convert_speed(v_reach_grid_kt, unit)

            for e_level, name, color, dash in [
                (e_upper, f"Max climb in {int(reach_seconds)} s",  "#0ea5e9", "solid"),
                (e_lower, f"Max bleed in {int(reach_seconds)} s",  "#0ea5e9", "dot"),
            ]:
                h_curve = e_level - v_reach_grid_fps ** 2 / (2 * g)
                mask    = (h_curve >= 0) & (h_curve <= max_altitude_ft)
                if not np.any(mask):
                    continue
                fig.add_trace(go.Scatter(
                    x=v_reach_disp[mask],
                    y=h_curve[mask],
                    mode="lines",
                    line=dict(color=color, width=2, dash=dash),
                    name=name,
                    hoverinfo="skip",
                    showlegend=True,
                    fill=("tonexty" if dash == "dot" else None),
                    fillcolor="rgba(14, 165, 233, 0.10)",   # very light teal shade
                ))
        except Exception:
            # Reachable-set is a nice-to-have; failure should never break the chart.
            pass

    # ── Phase 5Z-2: Target point + energy-delta arrow ─────────────────────
    # User clicked somewhere on the chart. Draw a target marker (blue diamond)
    # and an arrow from the current state to the target, labeled with the
    # energy delta and a plain-language verdict.
    if target_point and isinstance(target_point, dict):
        tx = float(target_point.get("v_disp", 0))
        ty = float(target_point.get("h_ft", 0))
        # ΔE between target and current. Convert target V back to kt for math.
        tv_kt = tx / KTS_TO_MPH if unit == "MPH" else tx
        target_e = ty + (tv_kt * KTS_TO_FPS) ** 2 / (2 * g)
        delta_e = target_e - cur_e

        # Phase 5AB-9 — energy decomposition + implied flight path geometry.
        # The pilot sees "ΔE -X" but the airspeed is increasing — to make the
        # trade legible we surface the PE/KE split and the implied descent /
        # climb angle from the rough trajectory (straight-line h vs horizontal
        # distance at mean V over the estimated time).
        delta_pe = ty - cur_alt
        delta_ke = (tv_kt * KTS_TO_FPS) ** 2 / (2 * g) - (ref_ias * KTS_TO_FPS) ** 2 / (2 * g)

        if abs(delta_e) < 50:
            verdict = "Energy-neutral — pure trade"
        elif delta_e > 0:
            verdict = f"Powered climb: +{int(delta_e):,} ft of E needed"
        else:
            verdict = f"Energy bleed: {int(delta_e):,} ft of E lost"
        # Always show the PE/KE breakdown so "−626 ft total" alongside
        # "+360 ft KE" makes sense.
        breakdown = f"<br><span style='font-size:9px'>ΔPE {delta_pe:+,.0f} ft · ΔKE {delta_ke:+,.0f} ft</span>"

        # Phase 5AB-8 — time-to-target with 3-point path sampling. The
        # original code sampled Ps only at the start of the path, which
        # under-counted altitude-induced Ps decay on long climbs and
        # over-counted on descents (since at idle, drag does the work, not
        # the engine — so power-on Ps at start over-estimated the speed).
        #
        # New approach:
        #   ΔE > 0 (climb)  → mean(Ps at start, mid, end) using CURRENT power
        #   ΔE < 0 (descent) → recompute Ps with power ~ idle (0.05) and use
        #                      mean along path. Drag is what bleeds energy.
        #
        # `secs = |ΔE| / |Ps_mean·KTS_TO_FPS|`. Verdict is qualified by
        # whether any sample crossed zero in the wrong direction.
        time_str = ""
        if ps_grid is not None and abs(delta_e) >= 50:
            def _ps_at(v_kt, h_ft, grid):
                jj = int(np.clip(np.searchsorted(ps_h_grid_ft, h_ft), 0, len(ps_h_grid_ft) - 1))
                ii = int(np.clip(np.searchsorted(ps_v_grid_kt, v_kt), 0, len(ps_v_grid_kt) - 1))
                return float(grid[jj, ii])

            mid_v = (ref_ias + tv_kt) / 2.0
            mid_h = (cur_alt + ty) / 2.0

            if delta_e > 0:
                # CLIMB — power-on Ps along path
                samples = [
                    _ps_at(ref_ias, cur_alt, ps_grid),
                    _ps_at(mid_v,   mid_h,   ps_grid),
                    _ps_at(tv_kt,   ty,      ps_grid),
                ]
                ps_mean = float(np.mean(samples))
                ps_min  = float(np.min(samples))
                crosses_zero = ps_min < 0
                if ps_mean > 0.05:
                    secs = abs(delta_e) / (ps_mean * KTS_TO_FPS)
                    label = "at current power"
                    if secs < 60:
                        time_str = f"<br><span style='font-size:9px'>≈ {int(secs)} s {label}</span>"
                    elif secs < 3600:
                        time_str = f"<br><span style='font-size:9px'>≈ {secs / 60:.1f} min {label}</span>"
                    else:
                        time_str = f"<br><span style='font-size:9px'>≈ {secs / 3600:.1f} h {label}</span>"
                    if crosses_zero:
                        time_str += "<br><span style='font-size:9px; color:#fd7e14'>Path crosses Ps=0 — slow it down or step-climb</span>"
                elif ps_min < -1.0:
                    time_str = "<br><span style='font-size:9px; color:#dc3545'>Target above sustained ceiling — increase power</span>"
                else:
                    time_str = "<br><span style='font-size:9px; color:#fd7e14'>Marginal climb — try higher power or lower target</span>"
            else:
                # DESCENT — energy bleed. Drag does the work. Recompute Ps at
                # idle so the time estimate isn't shifted by user's power setting.
                try:
                    ps_idle = _compute_ps_grid(
                        ac, weight_lb, ps_v_grid_kt, ps_h_grid_ft,
                        oat_c, altimeter_inhg,
                        0.05,                  # idle throttle
                        prop_condition, oei_active, engine_name,
                    )
                    samples_idle = [
                        _ps_at(ref_ias, cur_alt, ps_idle),
                        _ps_at(mid_v,   mid_h,   ps_idle),
                        _ps_at(tv_kt,   ty,      ps_idle),
                    ]
                    ps_idle_mean = float(np.mean(samples_idle))
                except Exception:
                    ps_idle_mean = 0.0
                if ps_idle_mean < -0.05:
                    secs = abs(delta_e) / (abs(ps_idle_mean) * KTS_TO_FPS)
                    label = "throttle to idle"
                    if secs < 60:
                        time_str = f"<br><span style='font-size:9px'>≈ {int(secs)} s ({label})</span>"
                    elif secs < 3600:
                        time_str = f"<br><span style='font-size:9px'>≈ {secs / 60:.1f} min ({label})</span>"
                    else:
                        time_str = f"<br><span style='font-size:9px'>≈ {secs / 3600:.1f} h ({label})</span>"

        # Phase 5AB-9 — implied flight path angle. If we have a time
        # estimate, compute the straight-line dive/climb angle the airplane
        # would fly to arrive at the target in that time. Surfaces "that's
        # only a 10° descent, not vertical" intuition.
        if time_str and "≈" in time_str:
            # Re-derive seconds from the time_str — cheap and avoids carrying
            # `secs` out of the climb/descent branches.
            import re
            m_s   = re.search(r"≈ (\d+)\s*s",   time_str)
            m_min = re.search(r"≈ ([\d.]+) min", time_str)
            m_h   = re.search(r"≈ ([\d.]+) h",   time_str)
            secs_implied = None
            if m_s:
                secs_implied = float(m_s.group(1))
            elif m_min:
                secs_implied = float(m_min.group(1)) * 60
            elif m_h:
                secs_implied = float(m_h.group(1)) * 3600
            if secs_implied and secs_implied > 0:
                v_mean_kt  = (ref_ias + tv_kt) / 2.0
                v_mean_fps = v_mean_kt * KTS_TO_FPS
                horiz_ft   = v_mean_fps * secs_implied
                if horiz_ft > 1:
                    fpa_deg = math.degrees(math.atan2(delta_pe, horiz_ft))
                    # delta_pe is negative for descent → fpa_deg negative.
                    time_str += (f"<br><span style='font-size:9px'>"
                                 f"implied path ≈ {fpa_deg:+.1f}°"
                                 f"</span>")

        fig.add_trace(go.Scatter(
            x=[tx], y=[ty],
            mode="markers",
            marker=dict(color=palette["title"], size=14, symbol="diamond-open",
                        line=dict(color=palette["title"], width=2.5)),
            name="Target",
            hoverinfo="text",
            hovertext=(f"Target<br>"
                       f"h = {int(ty):,} ft<br>"
                       f"V = {tx:.0f} {unit}<br>"
                       f"E = {int(target_e):,} ft total<br>"
                       f"<b>ΔE from current: {int(delta_e):+,} ft</b>"),
        ))
        # Phase 5Z-2 polish — split the arrow from the label. Previously the
        # text-bearing annotation's box anchor confused the arrow's tail
        # position (the line appeared to start at the label edge rather than
        # the current-state dot). Two separate annotations gives clean
        # geometry: a pure arrow with standoffs, plus a label at the midpoint.
        fig.add_annotation(
            x=tx, y=ty,
            ax=ref_ias_disp, ay=cur_alt,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True,
            arrowhead=2, arrowsize=1.2, arrowwidth=2,
            arrowcolor=palette["title"],
            standoff=8, startstandoff=8,    # gap from markers at both ends
            text="",                         # arrow-only — no text
        )
        # Label at the midpoint, offset perpendicular to the line so it
        # doesn't sit on the arrow itself.
        mid_x = (tx + ref_ias_disp) / 2
        mid_y = (ty + cur_alt) / 2
        fig.add_annotation(
            x=mid_x, y=mid_y,
            xref="x", yref="y",
            showarrow=False,
            text=f"<b>ΔE {int(delta_e):+,} ft</b><br><span style='font-size:9.5px'>{verdict}</span>{breakdown}{time_str}",
            font=dict(size=11, color=palette["title"], family="JetBrains Mono, Inter, sans-serif"),
            bgcolor=palette["annotation_bg"],
            bordercolor=palette["title"],
            borderpad=4, borderwidth=1,
            xshift=12, yshift=22,           # push above the arrow line
            xanchor="center", yanchor="bottom",
        )

    # ── Phase 5Z-2: hover grid — invisible scatter that gives every
    # (V, h) point in the visible plane a tooltip with local E and ΔE
    # from current. 30×25 = 750 points; cheap to render.
    v_grid = np.linspace(vs1g_sl, vne_kt, 30)
    h_grid = np.linspace(0, max_altitude_ft, 25)
    mesh_v, mesh_h = np.meshgrid(v_grid, h_grid)
    e_grid = mesh_h + (mesh_v * KTS_TO_FPS) ** 2 / (2 * g)
    delta_grid = e_grid - cur_e
    mesh_v_disp = _convert_speed(mesh_v, unit)
    # Pre-round in Python so the rendered hover never shows float64 tails like
    # "9523.456789012345 ft" — Plotly's d3-format `.0f` sometimes ignores
    # combined modifiers (`+`, `,`) on customdata indices in older versions.
    customdata = np.stack(
        [np.round(e_grid.flatten()).astype(int),
         np.round(delta_grid.flatten()).astype(int)],
        axis=-1,
    )
    x_disp_rounded = np.round(mesh_v_disp.flatten()).astype(int)
    y_h_rounded    = np.round(mesh_h.flatten()).astype(int)
    fig.add_trace(go.Scatter(
        x=x_disp_rounded,
        y=y_h_rounded,
        customdata=customdata,
        mode="markers",
        marker=dict(size=18, color="rgba(0,0,0,0)"),
        showlegend=False,
        hovertemplate=(
            f"V: %{{x}} {unit}<br>"
            "h: %{y:,} ft<br>"
            "<b>E: %{customdata[0]:,} ft</b><br>"
            "ΔE from current: %{customdata[1]:+,} ft"
            "<br><span style='font-size:10px'>Click: move current state · Drop-target mode: set target</span>"
            "<extra></extra>"
        ),
        name="",
    ))

    fig.update_layout(
        title=dict(
            text=f"<b>{ac_name}</b>  ·  Energy Map (h-V)",
            font=dict(size=18, color=palette["title"]),
            x=0.5, y=0.96, xanchor="center", yanchor="top",
        ),
        xaxis=dict(range=[max(0, vs1g_sl_disp - 5), vne_disp * 1.08]),
        yaxis=dict(range=[0, max_altitude_ft * 1.05]),
    )

    return fig
