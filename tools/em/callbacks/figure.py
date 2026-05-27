"""
TallyAero EM Diagram — the sacred chart callback.

`update_graph` is the single Plotly Figure producer for the EM diagram. Per the
non-negotiable rules in `Master prompt and context.md`:

    update_graph() is sacred. All EM diagram plotting must live inside it.
    No plotting logic outside this function. Ever.

Phase 1c relocated the function out of app.py into this module without
splitting it. register(app) wires the original @app.callback decorator.

Inputs (28 in total): see the body of register() below — they mirror the
DOM ids defined in layouts/desktop.py + layouts/mobile.py.

Output: a single Plotly Figure attached to the `em-graph` Output.
"""

from __future__ import annotations

import time

import numpy as np
import plotly.graph_objects as go
import dash
from dash.dependencies import ALL, Input, Output, State
from dash.exceptions import PreventUpdate

from em_core import (
    # Physical constants
    G_FT_S2,
    KTS_TO_FPS,
    FPS_TO_KTS,
    KTS_TO_MPH,
    g,
    # Atmosphere
    compute_air_density,
    compute_density_altitude,
    compute_pressure_altitude,
    # Stall
    interpolate_stall_speed,
    # OEI / multi-engine
    calculate_vmca,
    calculate_dynamic_vyse,
    # Data
    aircraft_data,
    # Logging
    dprint,
)


def update_graph(
    ac_name,
    config,
    engine_name,
    occupants,
    fuel,
    altitude_ft,
    total_weight,
    power_fraction,
    overlay_toggle,
    gear,
    oei_toggle,
    prop_condition,
    cg,
    selected_category,
    unit,
    multi_engine_toggle_options,
    maneuver,
    aob_values,
    ias_values,
    steepturn_standard_values,
    steepturn_ghost_values,
    chandelle_ias_values,
    chandelle_bank_values,
    chandelle_ghost_values,
    lazy8_ias_values,
    lazy8_bank_values,
    lazy8_ghost_values,
    pitch_angle,
    screen_width,
    oat_c,
    altimeter_inhg,
    theme_pref,
    compare_aircraft=None,
    probe=None,
):
    t_start = time.perf_counter()
    import plotly.graph_objects as go  # <== you must ensure this is imported here if not at top of file

    # Phase 5g — resolve the chart palette from the current theme preference.
    # Structural colors (paper bg, foreground lines, gridlines, title,
    # mute-gray contour lines, annotation text) flip between light and dark.
    # Brand/signal colors (stall red, Vyse blue, corner orange) stay stable.
    from em_core import get_chart_palette
    palette = get_chart_palette(theme_pref)
    
    # ---- existing validation, etc. ----
    def _empty_state_figure():
        """Palette-aware empty figure with no axes, just a hint."""
        return go.Figure(layout=dict(
            paper_bgcolor=palette["paper_bg"],
            plot_bgcolor=palette["plot_bg"],
            font=dict(color=palette["text"]),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            margin=dict(l=0, r=0, t=0, b=0),
            annotations=[dict(
                text="Select an aircraft to begin",
                showarrow=False,
                font=dict(size=14, color=palette["muted"]),
                xref="paper", yref="paper", x=0.5, y=0.5,
            )],
        ))

    if not ac_name or ac_name not in aircraft_data:
        return _empty_state_figure()

    # === Resolution tuning based on screen width ===
    if screen_width is None:
        screen_width = 1400  # fallback for server-side calls

    if screen_width < 1200:
        aob_ias_step = 1.0     # 1 kt increments
        aob_tr_step = 1.0      # 1 deg/s increments
    else:
        aob_ias_step = 0.5     # 0.5 kt increments
        aob_tr_step = 0.5      # 0.5 deg/s increments

    # Handle None values for overlay lists
    overlay_toggle = overlay_toggle if overlay_toggle is not None else []
    multi_engine_toggle_options = multi_engine_toggle_options if multi_engine_toggle_options is not None else []

    all_overlays = overlay_toggle + multi_engine_toggle_options

    if not ac_name or ac_name not in aircraft_data:
        return _empty_state_figure()

    if engine_name is None or engine_name not in aircraft_data[ac_name]["engine_options"]:
        raise PreventUpdate

    def convert_display_airspeed(ias_vals, unit):
        return ias_vals * KTS_TO_MPH if unit == "MPH" else ias_vals
    def convert_input_airspeed(ias_vals, unit):
        return ias_vals / KTS_TO_MPH if unit == "MPH" else ias_vals
    
    if not ac_name or ac_name not in aircraft_data:
        raise PreventUpdate
    from dash import ctx
    if oei_toggle is None:
        oei_toggle = []
    if prop_condition is None:
        prop_condition = "feathered"

    oei_active = "enabled" in oei_toggle
    prop_mode = prop_condition if oei_active else None
 

    ac = aircraft_data[ac_name]
    engine_data = ac["engine_options"][engine_name]
    
    # --- Power Derating Based on Altitude ---
    power_curve = engine_data.get("power_curve", {})
    sea_level_max = power_curve.get("sea_level_max", engine_data["horsepower"])
    max_altitude = power_curve.get("max_altitude", 12000)
    derate_per_1000ft = power_curve.get("derate_per_1000ft", 0.03)

    alt_frac = min(altitude_ft / 1000.0, max_altitude / 1000.0)
    alt_derate = max(0.0, 1 - derate_per_1000ft * alt_frac)
    derated_hp = sea_level_max * alt_derate

    hp = derated_hp * power_fraction  # override earlier hp

    g_limit_block = ac.get("G_limits", {}).get(selected_category, {}).get(config, {})

    if isinstance(g_limit_block, dict):
        g_limit = g_limit_block.get("positive", 3.8)
        neg = g_limit_block.get("negative", -1.5)
        g_limit_neg = abs(neg) if isinstance(neg, (int, float)) else 1.5
    elif isinstance(g_limit_block, (int, float)):
        g_limit = g_limit_block
        g_limit_neg = 1.5
    else:
        g_limit = 3.8
        g_limit_neg = 1.5

        # --- Gear Drag & Lift Modifiers ---
    gear_drag_factor = 1.0
    gear_lift_factor = 1.0

    if gear == "down":
        gear_drag_factor = 1.15  # +15% drag when gear down
        gear_lift_factor = 0.98  # -2% CLmax when gear down

    # --- Determine Final Power Based on OEI Toggle ---
    oei_config_key = f"{config}_{gear or 'up'}"
    oei_data = (
        engine_data
        .get("oei_performance", {})
        .get(oei_config_key, {})
        .get(prop_mode, {})
    )
    # If OEI config lookup failed, try defaulting to "clean_up"
    if oei_active and not oei_data:
        oei_data = (
            engine_data.get("oei_performance", {})
            .get("clean_up", {})
            .get(prop_mode, {})
        )

    if oei_active and oei_data:
        hp = sea_level_max * oei_data.get("max_power_fraction", 1.0) * alt_derate
    else:
        hp = derated_hp * power_fraction
        

    # Debug log
    dprint("ENGINE DEBUG:", {
        "ac": ac_name,
        "engine": engine_name,
        "oei_active": oei_active,
        "prop_mode": prop_mode,
        "config_key": oei_config_key,
        "hp": hp,
    })
    
    import re
    import numpy as np
    from math import pi
    import plotly.graph_objects as go

  

    # Continue with existing logic...

    fig = go.Figure()
    weight = total_weight  # passed in directly from dcc.Store
    total_weight = weight  # ensures total_weight is defined

    # Phase 5 cleanup: removed the in-chart logo overlay (broken-image
    # icon — logo2.png was never present in assets/). The header banner
    # carried the logo elsewhere; chart stays clean.

    fig.update_layout(
        paper_bgcolor=palette["paper_bg"],
        plot_bgcolor=palette["plot_bg"],
        font=dict(color=palette["text"]),
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis=dict(showgrid=True, gridcolor=palette["grid"], linecolor=palette["axis_line"], tickcolor=palette["grid"], tickfont=dict(color=palette["tick"])),
        yaxis=dict(showgrid=True, gridcolor=palette["grid"], linecolor=palette["axis_line"], tickcolor=palette["grid"], tickfont=dict(color=palette["tick"])),
        dragmode=False,
        hovermode="closest",
        # Phase 5g: theme-aware hover tooltips so they don't flash white in dark mode.
        hoverlabel=dict(
            bgcolor=palette["annotation_bg"],
            bordercolor=palette["grid"],
            font=dict(color=palette["text"], family="JetBrains Mono, Inter, sans-serif", size=12),
        ),
        # Phase 5Q: smooth re-renders when inputs change — axis range, trace
        # positions, contour shifts all tween instead of snapping.
        transition=dict(duration=320, easing="cubic-in-out"),
        autosize=True,
    )
    
    # --- CG Effects ---
    cl_base = ac["CL_max"][config]
    cg_min_val, cg_max_val = ac["cg_range"]
    cg_span = cg_max_val - cg_min_val
    cg_fraction = (cg - cg_min_val) / cg_span if cg_span else 0.5  # Avoid div by zero

    # Apply simple linear model: more forward = lower CL_max, more drag
    cl_max = cl_base * (1 - 0.05 * (1 - cg_fraction))  # up to 5% penalty at full forward CG
    cl_max *= gear_lift_factor
    cg_drag_factor = 1 + 0.04 * (0.5 - cg_fraction)     # up to 4% added drag for FWD CG

    dprint("CG INFLUENCE:", {
        "cg": cg,
        "cl_base": cl_base,
        "cl_max_adj": cl_max,
        "cg_fraction": cg_fraction,
        "cg_drag_factor": cg_drag_factor
    })


    wing_area = ac["wing_area"]
    # Aircraft drag/lift parameters - used throughout update_graph
    CD0 = ac.get("CD0", 0.025)
    e = ac.get("e", 0.8)
    AR = ac.get("aspect_ratio", 7.5)
    # Phase 2g: optional super-parabolic high-CL drag rise.
    # {"cl_threshold": float, "k_rise": float}. Unset = pure parabolic polar.
    cd_rise = ac.get("cd_rise_above_cl") or None

    # === Environment calculations using OAT and altimeter ===
    # Default values if not provided
    oat_c = oat_c if oat_c is not None else 15
    altimeter_inhg = altimeter_inhg if altimeter_inhg is not None else 29.92

    # Calculate pressure altitude from field elevation and altimeter
    pressure_altitude = compute_pressure_altitude(altitude_ft, altimeter_inhg)

    # Use centralized air density calculation with OAT for accurate density
    rho = compute_air_density(pressure_altitude, oat_c)

    dprint("ENVIRONMENT DEBUG:", {
        "field_elev_ft": altitude_ft,
        "oat_c": oat_c,
        "altimeter_inhg": altimeter_inhg,
        "pressure_altitude": pressure_altitude,
        "density_altitude": compute_density_altitude(pressure_altitude, oat_c),
        "rho": rho
    })

    stall_data = ac.get("stall_speeds", {}).get(config, {})
    # Use weight-interpolated stall speed instead of just minimum
    vs_1g = interpolate_stall_speed(stall_data, weight) if stall_data else 30
    ias_start = max(0, int(vs_1g * 0.7))

    if config == "clean":
        max_speed = ac.get("Vne", 200)
        label = "Vne"
    else:
        max_speed = ac.get("Vfe", {}).get(config, 120)
        label = f"Vfe ({config})"

    max_speed_internal = max_speed  # always in KIAS for physics
    max_speed_display = convert_display_airspeed(max_speed, unit)

    ias_start = max(0, int(vs_1g * 0.8))  # Add dynamic padding (20% below Vs)
    ias_vals = np.arange(ias_start, max_speed + 1, 1)
    ias_vals_display = convert_display_airspeed(ias_vals, unit)
    
    g_curve_x, g_curve_y = [], []
    for ias in ias_vals:
        v = ias * KTS_TO_FPS
        omega = g * ((g_limit**2 - 1) ** 0.5) / v
        tr = omega * 180 / pi
        g_curve_x.append(ias)
        g_curve_y.append(tr)

    stall_x, stall_y = [], []
    # Use finer steps near stall speed for smoother curve, coarser elsewhere
    stall_ias_fine = np.concatenate([
        np.arange(ias_start, vs_1g + 15, 0.5),  # Fine steps near stall
        np.arange(vs_1g + 15, max_speed + 1, 2)  # Coarser steps elsewhere
    ])
    for ias in stall_ias_fine:
        v = ias * KTS_TO_FPS
        n_stall = (0.5 * rho * v**2 * wing_area * cl_max) / weight
        if n_stall >= 1:
            omega = g * ((n_stall**2 - 1) ** 0.5) / v
            tr = omega * 180 / pi
            if not stall_x:
                stall_x.append(ias)
                stall_y.append(0)
            stall_x.append(ias)
            stall_y.append(tr)

    stall_x_display = convert_display_airspeed(np.array(stall_x), unit)
    g_curve_x_display = convert_display_airspeed(np.array(g_curve_x), unit)

    from numpy import interp
    corner_ias, corner_tr = None, None
    min_diff = float("inf")
    for ias in ias_vals:
        stall_tr = interp(ias, stall_x, stall_y)
        g_tr = interp(ias, g_curve_x, g_curve_y)
        diff = abs(stall_tr - g_tr)
        if diff < min_diff:
            min_diff = diff
            corner_ias = ias
            corner_tr = stall_tr
        if diff < 0.5:
            break

    if corner_ias is None:
        corner_ias = ias_vals[0]
        corner_tr = 0

    # Phase 5R-1: force both curves to terminate at the exact corner point
    # so they kiss perfectly. Previously each ended/started at the nearest
    # grid step, leaving a visible 1–2 kt gap at the corner.
    stall_clipped_x = [x for x in stall_x if x < corner_ias] + [corner_ias]
    stall_clipped_y = stall_y[:len(stall_clipped_x) - 1] + [corner_tr]
    g_clipped_x = [corner_ias] + [x for x in g_curve_x if x > corner_ias]
    g_clipped_y = [corner_tr] + g_curve_y[-(len(g_clipped_x) - 1):]

    oei_active = "enabled" in oei_toggle
    prop_mode = prop_condition if oei_active else None

    # === Early DVmc calculation to modify flight envelope ===
    dvmc_active = False
    if "vmca" in all_overlays and ac.get("engine_count", 1) > 1 and oei_active:
        dvmc_active = True
        published_vmca_early = ac.get("single_engine_limits", {}).get("Vmca", 70)
        reference_weight_early = ac.get("max_weight", 3600)
        cg_range_early = ac.get("cg_range", [10, 20])

        # Calculate DVmc curve
        bank_angles_early = np.linspace(5, 90, 150)
        _, vmca_vals_kias_early = calculate_vmca(
            published_vmca=published_vmca_early,
            power_fraction=power_fraction,
            total_weight=weight,
            reference_weight=reference_weight_early,
            cg=cg,
            cg_range=cg_range_early,
            prop_condition=prop_mode,
            pressure_altitude=pressure_altitude,
            oat_c=oat_c,
            bank_angles_deg=bank_angles_early
        )

        # Convert to turn rates
        v_fts_early = vmca_vals_kias_early * KTS_TO_FPS
        bank_rad_early = np.radians(bank_angles_early)
        omega_rad_early = g * np.tan(bank_rad_early) / v_fts_early
        turn_rates_early = np.degrees(omega_rad_early)

        # Modify stall boundary where DVmc is more restrictive
        stall_clipped_x_modified = []
        stall_clipped_y_modified = []

        for ias_stall, tr_stall in zip(stall_clipped_x, stall_clipped_y):
            # Interpolate DVmc speed at this turn rate
            if tr_stall >= min(turn_rates_early) and tr_stall <= max(turn_rates_early):
                dvmc_at_tr = np.interp(tr_stall, turn_rates_early, vmca_vals_kias_early)
                # Use max(stall, dvmc) as the effective boundary
                effective_ias = max(ias_stall, dvmc_at_tr)
            else:
                effective_ias = ias_stall
            stall_clipped_x_modified.append(effective_ias)
            stall_clipped_y_modified.append(tr_stall)

        # Replace stall boundary with modified version
        stall_clipped_x = stall_clipped_x_modified
        stall_clipped_y = stall_clipped_y_modified

    stall_clipped_x_display = convert_display_airspeed(np.array(stall_clipped_x), unit)
    g_clipped_x_display = convert_display_airspeed(np.array(g_clipped_x), unit)
    corner_ias_display = convert_display_airspeed(corner_ias, unit)

    if "negative_g" in overlay_toggle:
        # === Negative Lift Limit Curve ===
        # Use same fine steps near stall as positive boundary for consistency
        neg_stall_x, neg_stall_y = [], []
        for ias in stall_ias_fine:
            v = ias * KTS_TO_FPS
            n_stall = (0.5 * rho * v**2 * wing_area * -cl_max) / weight
            if n_stall <= -1:
                # Compute turn rate, limit to G envelope
                try:
                    tr_limit_neg = g * np.sqrt(abs(g_limit_neg)**2 - 1) / v
                    omega = g * np.sqrt(n_stall**2 - 1) / v
                    tr = -min(omega * 180 / pi, tr_limit_neg * 180 / pi)
                except:
                    continue  # Skip invalid values (e.g. sqrt of negative)
                if not neg_stall_x:
                    neg_stall_x.append(ias)
                    neg_stall_y.append(0)
                neg_stall_x.append(ias)
                neg_stall_y.append(tr)

        neg_corner_idx = np.argmin(np.abs(np.array(neg_stall_y) - (-corner_tr)))
        neg_stall_x_clip = neg_stall_x[:neg_corner_idx + 1]
        neg_stall_y_clip = neg_stall_y[:neg_corner_idx + 1]
        neg_stall_x_display = convert_display_airspeed(np.array(neg_stall_x_clip), unit)

        # === Negative G-Limit Curve ===
        neg_g_x, neg_g_y = [], []
        for ias in ias_vals:
            v = ias * KTS_TO_FPS
            try:
                omega = g * np.sqrt(g_limit_neg**2 - 1) / v
                tr = -omega * 180 / pi
                neg_g_x.append(ias)
                neg_g_y.append(tr)
            except:
                continue

        neg_g_x_clip = [x for x in neg_g_x if x >= neg_stall_x_clip[-1]]
        neg_g_y_clip = neg_g_y[-len(neg_g_x_clip):]
        neg_g_x_display = convert_display_airspeed(np.array(neg_g_x_clip), unit)

        # === Plot Negative G Envelope ===
        fig.add_trace(go.Scatter(
            x=neg_stall_x_display,
            y=neg_stall_y_clip,
            mode="lines",
            name="Neg Lift Limit",
            line=dict(color="red", width=3),
            hoverinfo="skip"
        ))

        fig.add_trace(go.Scatter(
            x=neg_g_x_display,
            y=neg_g_y_clip,
            mode="lines",
            name=f"Neg Load Limit ({g_limit_neg:.1f} G)",
            line=dict(color=palette["fg"], width=3, dash="solid"),
            hoverinfo="skip"
        ))

        vne_y_top = None
        vne_y_bot = None

        # Adjust y_max/y_min to show full envelope
        y_span = max(
            abs(min(neg_g_y_clip)) if neg_g_y_clip else 0,
            max(g_clipped_y) if g_clipped_y else 0
        )
        y_max = y_span * 1.1
        y_min = -y_span * 1.1
    else:
        y_max = max(g_clipped_y) * 1.1 if g_clipped_y else 100
        y_min = 0

    # Lift Limit - color changes when DVmc modifies the boundary
    lift_limit_color = "#DC143C" if dvmc_active else "red"
    lift_limit_name = "Lift Limit (DVmc)" if dvmc_active else "Lift Limit"
    fig.add_trace(go.Scatter(x=stall_clipped_x_display, y=stall_clipped_y,
        mode="lines", name=lift_limit_name, line=dict(color=lift_limit_color, width=3), hoverinfo="skip")),
    fig.add_trace(go.Scatter(x=g_clipped_x_display, y=g_clipped_y,
        mode="lines", name=f"Load Limit ({g_limit:.1f} G)", line=dict(color=palette["fg"], width=3, dash="solid"), hoverinfo="skip")),
    fig.add_trace(go.Scatter(x=[corner_ias_display], y=[corner_tr],
        mode="markers", name=f"Corner Speed ({corner_ias_display:.0f} {unit})", marker=dict(color="orange", size=9, symbol="x"), hoverinfo="skip")),

    # Phase 5R-1: corner speed callout next to the marker, INSIDE the plot
    # area. Previously this rode along the X axis at y=-0.08 paper and
    # overlapped the axis title. Putting it next to the marker is also
    # more intuitive — the value reads with the point it describes.
    fig.add_annotation(
        x=corner_ias_display,
        y=corner_tr,
        text=f"<b>{corner_ias_display:.0f}</b> {unit}",
        showarrow=False,
        xshift=14,
        yshift=10,
        xanchor="left",
        yanchor="bottom",
        font=dict(color="#f27b0d", size=11, family="JetBrains Mono, Inter, sans-serif"),
        bgcolor=palette["annotation_bg"],
        bordercolor="#f27b0d",
        borderpad=3,
        borderwidth=1,
    )

    # Phase 5R-1/5R-2: legacy bottom-of-axis stack retired entirely. The
    # corner speed lives next to its marker (5R-1); each multi-engine speed
    # (Vmca / DVmc / Vyse / Vxse / DVyse) places an annotation at its own
    # line/curve via the v_speed_labels list below. The list is rendered
    # with vertical-stack collision detection once all V-speeds finalise.
    xaxis_speed_markers = []
    v_speed_labels = []

  # --- Interpolate Vne Y-positions (always present) ---
    vne_y_top = np.interp(max_speed, g_clipped_x, g_clipped_y) if g_clipped_x and g_clipped_y else 0
    vne_y_bot = 0  # Default if negative_g not shown

    # If negative G envelope is enabled and valid, interpolate bottom of Vne line
    if "negative_g" in overlay_toggle and 'neg_g_x_clip' in locals() and neg_g_x_clip and neg_g_y_clip:
        vne_y_bot = np.interp(max_speed, neg_g_x_clip, neg_g_y_clip)

    # Convert X for display units
    vne_x_display = convert_display_airspeed(max_speed, unit)

    # --- Plot Vne line
    fig.add_trace(go.Scatter(
        x=[vne_x_display, vne_x_display],
        y=[vne_y_bot, vne_y_top],
        mode="lines",
        name=label,
        line=dict(color=palette["fg"], width=3, dash="dash"),
        hoverinfo="skip"
    ))

    # Phase 5R-1: Vne value label anchored to the top of the line so the
    # number is readable directly from the chart (legend still has the
    # trace name, but the value lives where it matters).
    fig.add_annotation(
        x=vne_x_display,
        y=vne_y_top,
        text=f"<b>Vne</b> {vne_x_display:.0f}",
        showarrow=False,
        xshift=-6,
        yshift=8,
        xanchor="right",
        yanchor="bottom",
        font=dict(color=palette["fg"], size=11, family="JetBrains Mono, Inter, sans-serif"),
        bgcolor=palette["annotation_bg"],
        bordercolor=palette["grid"],
        borderpad=3,
        borderwidth=1,
    )
    
    # Setup for overlays (continue with part 2)
    # --- INTERMEDIATE G CURVES (toggle controlled) ---
    if "g" in overlay_toggle:
        intermediate_gs = [round(g_val, 1) for g_val in np.arange(1.5, g_limit, 0.5)]
        for g_inter in intermediate_gs:
            gx, gy = [], []
            for ias in ias_vals:
                v = ias * KTS_TO_FPS
                stall_v = np.sqrt((2 * weight * g_inter) / (rho * wing_area * cl_max))
                if v < stall_v:
                    continue
                omega = g * np.sqrt(g_inter**2 - 1) / v
                tr = omega * 180 / pi

                # Check DVmc limit when active
                dvmc_ok = True
                if dvmc_active:
                    dvmc_at_tr = np.interp(tr, turn_rates_early, vmca_vals_kias_early)
                    dvmc_ok = ias >= dvmc_at_tr

                if dvmc_ok:
                    gx.append(ias)
                    gy.append(tr)

            if len(gx) > 5:
                gx_display = convert_display_airspeed(np.array(gx), unit)
                fig.add_trace(go.Scatter(
                    x=gx_display, y=gy, mode="lines",
                    line=dict(color="yellow", width=1.2, dash="solid"),
                    showlegend=False, hoverinfo="skip"
                ))
                fig.add_annotation(
                    x=gx_display[-1] + 4, y=gy[-1], text=f"{g_inter:.1f}G",
                    showarrow=False, font=dict(color=palette["fg"], size=10),
                    bgcolor=palette["annotation_bg"], borderpad=1
                )
# === Negative G Lines ===
        
        neg_intermediate_gs = [
            round(g_val, 1)
            for g_val in np.arange(-1.0, g_limit_neg, -0.5)
            if abs(g_val) >= 1.5 and abs(g_val - g_limit_neg) > 0.2
        ]
        for g_inter in neg_intermediate_gs:
            gx, gy = [], []
            for ias in ias_vals:
                v = ias * KTS_TO_FPS
                stall_v = np.sqrt((2 * weight * abs(g_inter)) / (rho * wing_area * cl_max))
                if v < stall_v:
                    continue
                omega = g * np.sqrt(g_inter**2 - 1) / v
                tr = -omega * 180 / pi  # negative turn rate
                gx.append(ias)
                gy.append(tr)
            if len(gx) > 5:
                gx_display = convert_display_airspeed(np.array(gx), unit)
                fig.add_trace(go.Scatter(
                    x=gx_display, y=gy, mode="lines",
                    line=dict(color="yellow", width=1.2, dash="dot"),
                    showlegend=False, hoverinfo="skip"
                ))
                fig.add_annotation(
                    x=gx_display[-1] + 4, y=gy[-1], text=f"{g_inter:.1f}G",
                    showarrow=False, font=dict(color=palette["fg"], size=10),
                    bgcolor=palette["annotation_bg"], borderpad=1
                )

    # --- Ps GRID CALCULATION (only if Ps overlay enabled) ---
    Ps_masked = None
    ias_vals_ps_display = None
    tr_vals_ps = None

    if "ps" in overlay_toggle:
        ias_vals_ps_internal = np.arange(ias_start, max_speed_internal + 1, 1)
        ias_vals_ps_display = convert_display_airspeed(ias_vals_ps_internal, unit)
        CD0 = ac.get("CD0", 0.025)
        e = ac.get("e", 0.8)
        AR = ac.get("aspect_ratio", 7.5)

        # Detect steep turn override
        steep_turn_override = maneuver == "steep_turn" and ias_values and aob_values
        if steep_turn_override:
            aob_deg = aob_values[0]
            aob_rad = np.radians(aob_deg)
            V = ias_vals_ps_internal * KTS_TO_FPS
            TR_fixed = np.degrees(g * np.tan(aob_rad) / V)  # TR as a function of IAS
            TR = np.tile(TR_fixed, (len(ias_vals_ps_internal), 1)).T  # 2D grid shape
            IAS = np.tile(ias_vals_ps_internal, (len(TR), 1))
            tr_vals_ps = TR[:, 0]  # save for mask / plotting
        else:
            tr_vals_ps = np.arange(-100, 100, 1)
            IAS, TR = np.meshgrid(ias_vals_ps_internal, tr_vals_ps)

        V = IAS * KTS_TO_FPS  # convert to ft/s
        omega_rad = TR * (np.pi / 180)
        n = np.sqrt(1 + (V * omega_rad / g) ** 2)

        q = 0.5 * rho * V**2
        CL = weight * n / (q * wing_area)
        CL_clipped = np.minimum(CL, cl_max)
        CD = (CD0 + (CL_clipped**2) / (np.pi * e * AR))
        # Phase 2g: super-parabolic rise at high CL (steep turns near stall)
        if cd_rise:
            cl_th = cd_rise.get("cl_threshold")
            k_r   = cd_rise.get("k_rise", 0.0)
            if cl_th is not None and k_r:
                CD = CD + k_r * np.maximum(0.0, CL_clipped - cl_th) ** 2
        CD = CD * cg_drag_factor * gear_drag_factor
        D = q * wing_area * CD

        # === Propeller Thrust Decay ===
        V_kts = IAS
        V_max_kts = ac.get("prop_thrust_decay", {}).get("V_max_kts", 160)
        T_static = ac.get("prop_thrust_decay", {}).get("T_static_factor", 2.6) * hp
        V_fraction = np.clip(V_kts / V_max_kts, 0, 1)
        T_available = T_static * (1 - V_fraction**2)
        T_available = np.maximum(T_available, 0)

        gamma_rad = np.radians(pitch_angle)

        # Vertical speed term (ft/s); for gamma=0 this is just 0
        V_vertical = V * np.sin(gamma_rad)

        # Ps in knots per second
        Ps = ((T_available - D) * V / weight - V_vertical) * FPS_TO_KTS

        # Envelope mask (vectorized)
        v_fts_env = IAS * KTS_TO_FPS
        omega_rad_env = TR * (np.pi / 180)

        n_env = np.sqrt(1 + (v_fts_env * omega_rad_env / g) ** 2)
        stall_v_fts_env = np.sqrt((2 * weight * n_env) / (rho * wing_area * cl_max))
        stall_ias_env = stall_v_fts_env * FPS_TO_KTS

        tr_limit_pos_env = g * np.sqrt(g_limit**2 - 1) / v_fts_env * 180 / np.pi
        tr_limit_neg_env = g * np.sqrt(g_limit_neg**2 - 1) / v_fts_env * 180 / np.pi

        valid_pos = (TR >= 0) & (TR <= tr_limit_pos_env)
        valid_neg = (TR < 0) & (TR >= -tr_limit_neg_env)  # Negate limit for negative TR region

        # Base envelope mask
        within_env = (
            (IAS >= stall_ias_env) &
            (IAS <= max_speed_internal) &
            (valid_pos | valid_neg)
        )

        # Add DVmc masking when active
        if dvmc_active:
            # For each point, check if IAS >= DVmc at that turn rate
            dvmc_ias_at_tr = np.interp(TR, turn_rates_early, vmca_vals_kias_early)
            dvmc_mask = IAS >= dvmc_ias_at_tr
            within_env = within_env & dvmc_mask

        # Ps_masked = usable Ps; outside envelope = NaN
        Ps_masked = np.where(within_env, Ps, np.nan)

        dprint(f"[Ps DEBUG] ----")
        dprint(f"  Air Density: {rho:.5f} slugs/ft³")
        dprint(f"  CL avg: {np.nanmean(CL):.2f}, CD avg: {np.nanmean(CD):.3f}")
        dprint(f"  Thrust avg: {np.nanmean(T_available):.1f} lbs")
        dprint(f"  Drag avg: {np.nanmean(D):.1f} lbs")
        dprint(f"  Ps min: {np.nanmin(Ps):.2f}, Ps max: {np.nanmax(Ps):.2f} knots/sec")
        dprint(f"  Flight Path Angle (γ): {pitch_angle}°")
        dprint("[THRUST DECAY DEBUG]")
        dprint(f"  V_max_kts: {V_max_kts}")
        dprint(f"  T_static: {T_static:.1f} lbs")
        dprint(f"  T_available avg: {np.nanmean(T_available):.1f} lbs")
        dprint(f"  Drag avg: {np.nanmean(D):.1f} lbs")

   
# --- AOB HEATMAP: 10° to 90°, clipped to envelope ---

    if "aob" in overlay_toggle:
        # --- AOB HEATMAP (Valid Points Only) ---
        IAS_vals = np.arange(ias_start, max_speed + 1, aob_ias_step)
        IAS_vals_display = convert_display_airspeed(IAS_vals, unit)
        ias_vals_display = convert_display_airspeed(ias_vals, unit)
        TR_vals = np.arange(0.1, 100, aob_tr_step)  # Start near 0 for full coverage
        IAS, TR = np.meshgrid(IAS_vals, TR_vals)
        V = IAS * KTS_TO_FPS
        omega_rad = TR * (np.pi / 180)

        # Compute angle of bank at each point
        AOB_rad = np.arctan(omega_rad * V / g)
        AOB_deg = np.degrees(AOB_rad)

        # Mask: only show valid points (stall + G-limit + Vne)
        n = np.sqrt(1 + (V * omega_rad / g) ** 2)
        n = np.maximum(n, 1.001)  # Enforce minimum 1 G load factor

        stall_v = np.sqrt((2 * weight * n) / (rho * wing_area * cl_max))
        stall_IAS = stall_v * FPS_TO_KTS
        tr_limit = g * np.sqrt(g_limit**2 - 1) / V * 180 / pi

        mask = (IAS >= stall_IAS) & (TR <= tr_limit) & (IAS <= max_speed)

        # Add DVmc masking when active
        if dvmc_active:
            dvmc_ias_at_tr = np.interp(TR, turn_rates_early, vmca_vals_kias_early)
            dvmc_mask = IAS >= dvmc_ias_at_tr
            mask = mask & dvmc_mask

        AOB_masked = np.where(mask, AOB_deg, np.nan)

        # Plot AOB heatmap
        fig.add_trace(go.Heatmap(
            x=IAS_vals_display,
            y=TR_vals,
            z=AOB_masked,
            colorscale="Viridis",   # Phase 5Q: colorblind-safe replacement for Turbo
            zmin=0,
            zmax=90,
            opacity=0.5,
            zsmooth="fast",
            hoverinfo="skip",
            colorbar=dict(
                # Phase 5R-7: quieter, typographically aligned colorbar
                title=dict(
                    text="Bank °",
                    font=dict(
                        size=10,
                        color=palette["tick"],
                        family="JetBrains Mono, Inter, sans-serif",
                    ),
                    side="top",
                ),
                tickfont=dict(
                    size=9,
                    color=palette["tick"],
                    family="JetBrains Mono, Inter, sans-serif",
                ),
                tickvals=[0, 30, 45, 60, 75, 90],   # meaningful bank angles only
                x=1.02,
                xanchor="left",
                y=0.5,
                len=0.55,
                thickness=10,
                outlinewidth=0,
            )
        ))
        # --- AOB HEATMAP (Negative Turn Rates) ---
        if "aob" in overlay_toggle and "negative_g" in overlay_toggle:
            TR_vals_neg = np.arange(-100, -0.1, aob_tr_step)  # End near 0 for full coverage
            IAS_vals_neg = np.arange(ias_start, max_speed + 1, aob_ias_step)
            IAS_neg, TR_neg = np.meshgrid(IAS_vals_neg, TR_vals_neg)
            V_neg = IAS_neg * KTS_TO_FPS
            omega_rad_neg = np.abs(TR_neg) * (np.pi / 180)  # use absolute to mirror

            AOB_rad_neg = np.arctan(omega_rad_neg * V_neg / g)
            AOB_deg_neg = np.degrees(AOB_rad_neg)  # keep positive AOB for mirror color scale

            n_neg = np.sqrt(1 + (V_neg * omega_rad_neg / g) ** 2)
            n_neg = np.maximum(n_neg, 1.001)
            stall_v_neg = np.sqrt((2 * weight * n_neg) / (rho * wing_area * cl_max))
            stall_IAS_neg = stall_v_neg * FPS_TO_KTS
            tr_limit_neg = g * np.sqrt(g_limit_neg**2 - 1) / V_neg * 180 / pi

            mask_neg = (IAS_neg >= stall_IAS_neg) & (np.abs(TR_neg) <= tr_limit_neg) & (IAS_neg <= max_speed)
            AOB_masked_neg = np.where(mask_neg, AOB_deg_neg, np.nan)

            fig.add_trace(go.Heatmap(
                x=convert_display_airspeed(IAS_vals_neg, unit),
                y=TR_vals_neg,
                z=AOB_masked_neg,
                colorscale="Viridis",   # Phase 5Q: colorblind-safe replacement for Turbo
                zmin=0,
                zmax=90,
                opacity=0.5,
                zsmooth="fast",
                hoverinfo="skip",
                showscale=False  # share scale with positive AOB
            ))
        

    if "radius" in overlay_toggle:
        ias_range = np.arange(ias_start, max_speed + 1, 2)
        min_radius = None
        max_radius = 0

        # --- Step 1a: Dynamically find smallest valid turn radius inside envelope
        min_radius = None
        for ias in np.arange(ias_start, max_speed + 1, 0.5):  # fine IAS sweep
            v_fts = ias * KTS_TO_FPS
            for tr_candidate in np.arange(60, 1, -0.5):  # from tightest turns down
                omega_rad = tr_candidate * (np.pi / 180)
                r = v_fts / omega_rad

                n = np.sqrt(1 + (v_fts * omega_rad / g) ** 2)
                stall_v_fts = np.sqrt((2 * weight * n) / (rho * wing_area * cl_max))
                stall_ias = stall_v_fts * FPS_TO_KTS
                tr_limit = g * np.sqrt(g_limit**2 - 1) / v_fts * 180 / np.pi

                if ias >= stall_ias and tr_candidate <= tr_limit and ias <= max_speed:
                    if min_radius is None or r < min_radius:
                        min_radius = r * 1.017
                    break  # first valid tightest radius is enough for this IAS

        # --- Step 1b: Compute max radius using 3 deg/sec
        max_radius = 0
        for ias in ias_range:
            v_fts = ias * KTS_TO_FPS
            omega_3deg = 3 * (np.pi / 180)
            r = v_fts / omega_3deg

            n = np.sqrt(1 + (v_fts * omega_3deg / g) ** 2)
            stall_v_fts = np.sqrt((2 * weight * n) / (rho * wing_area * cl_max))
            stall_ias = stall_v_fts * FPS_TO_KTS
            tr_limit = g * np.sqrt(g_limit ** 2 - 1) / v_fts * 180 / np.pi

            if ias >= stall_ias and 3 <= tr_limit and ias <= max_speed:
                max_radius = max(max_radius, r)

        span = max_radius - min_radius

        # Step 2: Visually spaced radius levels (5 total)
        mid1 = min_radius + 0.04 * span
        mid2 = min_radius + 0.12 * span
        mid3 = min_radius + 0.3 * span
        r1 = int(round(min_radius / 100.0)) * 100
        r2 = int(round(mid1 / 100.0)) * 100
        r3 = int(round(mid2 / 100.0)) * 100
        r4 = int(round(mid3 / 100.0)) * 100
        r5 = int(round(max_radius / 100.0)) * 100
        radius_levels = sorted(set([r1, r2, r3, r4, r5]))

        # Step 3: Plot radius lines
        for radius in radius_levels:
            valid_x = []
            valid_y = []

            for ias in ias_range:
                v_fts = ias * KTS_TO_FPS
                omega_rad = v_fts / radius
                tr_deg = omega_rad * 180 / pi

                n = np.sqrt(1 + (v_fts * omega_rad / g) ** 2)
                stall_v_fts = np.sqrt((2 * weight * n) / (rho * wing_area * cl_max))
                stall_ias = stall_v_fts * FPS_TO_KTS
                tr_limit = g * np.sqrt(g_limit**2 - 1) / v_fts * 180 / pi

                # Check DVmc limit when active
                dvmc_ok = True
                if dvmc_active:
                    dvmc_at_tr = np.interp(tr_deg, turn_rates_early, vmca_vals_kias_early)
                    dvmc_ok = ias >= dvmc_at_tr

                if ias >= stall_ias and tr_deg <= tr_limit and ias <= max_speed and dvmc_ok:
                    valid_x.append(convert_display_airspeed(ias, unit))
                    valid_y.append(tr_deg)

            if len(valid_x) > 5:
                fig.add_trace(go.Scatter(
                    x=valid_x,
                    y=valid_y,
                    mode="lines",
                    line=dict(color="blue", width=1, dash="dash"),
                    showlegend=False,
                    hoverinfo="skip",
                ))
                # Phase 5R-6: quieter typography. Smaller mono numerals,
                # tighter pill, reduced opacity so the radius reference
                # reads as a guide line rather than a primary callout.
                mid = len(valid_x) // 2
                fig.add_annotation(
                    x=valid_x[mid],
                    y=valid_y[mid],
                    text=f"{radius} ft",
                    showarrow=False,
                    font=dict(
                        color=palette["muted"],
                        size=9,
                        family="JetBrains Mono, Inter, sans-serif",
                    ),
                    bgcolor=palette["annotation_bg"],
                    borderpad=0,
                    opacity=0.85,
                )
        x_min = ias_start
        x_max = max_speed * 1.1
        y_max = (
            max(stall_clipped_y + g_clipped_y) * 1.1
            if stall_clipped_y and g_clipped_y
            else 100
        )
        # --- Add Turn Radius Legend Entry ---
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines",
            name="Turn Radius",
            line=dict(color="blue", width=1, dash="dash"),
            showlegend=True
        ))

        # --- NEGATIVE TURN RADIUS LINES ---
        if "negative_g" in overlay_toggle:
            neg_min_radius = None
            neg_max_radius = 0

            # Step 1a: Find tightest valid negative radius
            for ias in np.arange(ias_start, max_speed + 1, 0.5):
                v_fts = ias * KTS_TO_FPS
                for tr_candidate in np.arange(60, 1, -0.5):
                    omega_rad = tr_candidate * (np.pi / 180)
                    r = v_fts / omega_rad

                    n = np.sqrt(1 + (v_fts * omega_rad / g) ** 2)
                    stall_v_fts = np.sqrt((2 * weight * n) / (rho * wing_area * cl_max))
                    stall_ias = stall_v_fts * FPS_TO_KTS
                    tr_limit = g * np.sqrt(g_limit_neg**2 - 1) / v_fts * 180 / np.pi

                    if ias >= stall_ias and tr_candidate <= tr_limit and ias <= max_speed:
                        neg_min_radius = round(r * 1.017 / 100.0) * 100
                        break
                if neg_min_radius:
                    break

            # Step 1b: Max radius using 3 deg/sec
            for ias in ias_vals:
                v_fts = ias * KTS_TO_FPS
                omega_3deg = 3 * (np.pi / 180)
                r = v_fts / omega_3deg

                n = np.sqrt(1 + (v_fts * omega_3deg / g) ** 2)
                stall_v_fts = np.sqrt((2 * weight * n) / (rho * wing_area * cl_max))
                stall_ias = stall_v_fts * FPS_TO_KTS
                tr_limit = g * np.sqrt(g_limit_neg**2 - 1) / v_fts * 180 / np.pi

                if ias >= stall_ias and 3 <= tr_limit and ias <= max_speed:
                    neg_max_radius = max(neg_max_radius, r)

            neg_max_radius = round(neg_max_radius / 100.0) * 100

            # Step 2: Plot both radii
            for radius in [neg_min_radius, neg_max_radius]:
                if not radius:
                    continue
                neg_valid_x, neg_valid_y = [], []

                for ias in ias_vals:
                    v_fts = ias * KTS_TO_FPS
                    omega_rad = v_fts / radius
                    tr_deg = -omega_rad * 180 / pi

                    n = np.sqrt(1 + (v_fts * omega_rad / g) ** 2)
                    stall_v = np.sqrt((2 * weight * n) / (rho * wing_area * cl_max))
                    stall_ias = stall_v * FPS_TO_KTS
                    tr_limit = g * np.sqrt(g_limit_neg**2 - 1) / v_fts * 180 / pi

                    if ias >= stall_ias and abs(tr_deg) <= tr_limit and ias <= max_speed:
                        neg_valid_x.append(convert_display_airspeed(ias, unit))
                        neg_valid_y.append(tr_deg)

                if len(neg_valid_x) > 5:
                    fig.add_trace(go.Scatter(
                        x=neg_valid_x,
                        y=neg_valid_y,
                        mode="lines",
                        line=dict(color="blue", width=1.5, dash="dot"),
                        showlegend=False,
                        hoverinfo="skip"
                    ))
                    # Phase 5R-6: same quiet treatment as positive radius labels
                    mid = len(neg_valid_x) // 2
                    fig.add_annotation(
                        x=neg_valid_x[mid],
                        y=neg_valid_y[mid],
                        text=f"{radius} ft",
                        showarrow=False,
                        font=dict(
                            color=palette["muted"],
                            size=9,
                            family="JetBrains Mono, Inter, sans-serif",
                        ),
                        bgcolor=palette["annotation_bg"],
                        borderpad=0,
                        opacity=0.85,
                    )
    

    
     # --- Dynamic Vmca Curve (bank angle vs adjusted Vmca + turn rate) ---
    if "vmca" in all_overlays and ac.get("engine_count", 1) > 1 and oei_active:
        published_vmca = ac.get("single_engine_limits", {}).get("Vmca", 70)
        reference_weight = ac.get("max_weight", 3600)
        cg_range = ac.get("cg_range", [10, 20])

        # Sweep bank angle from 5° to 90°
        bank_angles = np.linspace(5, 90, 150)

        _, vmca_vals_kias = calculate_vmca(
            published_vmca=published_vmca,
            power_fraction=power_fraction,
            total_weight=weight,
            reference_weight=reference_weight,
            cg=cg,
            cg_range=cg_range,
            prop_condition=prop_mode,
            pressure_altitude=pressure_altitude,
            oat_c=oat_c,
            bank_angles_deg=bank_angles
        )

        vmca_vals_display_full = convert_display_airspeed(vmca_vals_kias, unit)

        # Convert bank angle to turn rate
        v_fts = vmca_vals_kias * KTS_TO_FPS
        bank_rad = np.radians(bank_angles)
        omega_rad = g * np.tan(bank_rad) / v_fts
        turn_rates_full = np.degrees(omega_rad)

        # Save first point for label (before clipping)
        dvmc_label_value = vmca_vals_display_full[0]
        dvmc_label_tr = turn_rates_full[0]

        # Clip to envelope before plotting - must be within lift limit (stall boundary)
        stall_tr_limit = np.interp(vmca_vals_kias, stall_clipped_x, stall_clipped_y)
        valid_mask = (turn_rates_full >= y_min) & (turn_rates_full <= y_max) & (turn_rates_full <= stall_tr_limit)
        vmca_vals_display = vmca_vals_display_full[valid_mask]
        turn_rates = turn_rates_full[valid_mask]

        # Build hover text with bank angle info
        bank_angles_masked = bank_angles[valid_mask]
        vmca_hover = [
            f"<b>DVmc</b><br>Bank: {bank:.0f}°<br>Vmca: {spd:.0f} {unit}<br>Turn Rate: {tr:.1f}°/s"
            for bank, spd, tr in zip(bank_angles_masked, vmca_vals_display, turn_rates)
        ]

        # Plot DVmc line (clipped portion only)
        if len(vmca_vals_display) > 0:
            fig.add_trace(go.Scatter(
                x=vmca_vals_display,
                y=turn_rates,
                mode="lines",
                name="DVmc",
                line=dict(color="#DC143C", width=2.5, dash="dash"),
                hoverinfo="text",
                hovertext=vmca_hover,
                showlegend=True
            ))

        # Phase 5R-2: DVmc label anchored to the curve's low-bank endpoint
        # (where DVmc most closely tracks published Vmca). Vertical stacking
        # applied at end of function once all V-speeds are collected.
        v_speed_labels.append({
            "x": float(dvmc_label_value),
            "y": float(dvmc_label_tr),
            "text": f"<b>DVmc</b> {dvmc_label_value:.0f}",
            "color": "#DC143C",
            "anchor": "curve-bottom",
        })

    # === Dynamic Vyse Marker and Curve ===
    if "dynamic_vyse" in all_overlays and ac.get("engine_count", 1) > 1 and oei_active:
        vyse_block = ac.get("single_engine_limits", {}).get("Vyse", {})
        if isinstance(vyse_block, dict):
            published_vyse = vyse_block.get("clean_up") or next(iter(vyse_block.values()), 100)
        else:
            published_vyse = vyse_block if isinstance(vyse_block, (int, float)) else 100
        reference_weight = ac.get("max_weight", 3600)

        # --- Sweep bank angle to visualize how Vyse performance changes with AOB
        bank_angles = np.linspace(5, 60, 120)
        vyse_curve = []

        for angle in bank_angles:
            angle_penalty = 1.0 + 0.003 * (angle - 5)
            vyse_val = calculate_dynamic_vyse(
                published_vyse=published_vyse,
                total_weight=weight,
                reference_weight=reference_weight,
                pressure_altitude=pressure_altitude,
                oat_c=oat_c,
                gear_position=gear,
                flap_config=config,
                prop_condition=prop_mode
            )
            vyse_curve.append(vyse_val * angle_penalty)

        vyse_curve = np.clip(vyse_curve, min(g_curve_x), max(g_curve_x))
        vyse_display_curve_full = convert_display_airspeed(np.array(vyse_curve), unit)

        v_fts = np.array(vyse_curve) * KTS_TO_FPS
        bank_rad = np.radians(bank_angles)
        omega_rad = g * np.tan(bank_rad) / v_fts
        turn_rates_full = np.degrees(omega_rad)

        # Save first point for label (before clipping)
        dvyse_label_value = vyse_display_curve_full[0]
        dvyse_label_tr = turn_rates_full[0]

        # Clip to envelope - must be within lift limit (stall boundary)
        vyse_curve_arr = np.array(vyse_curve)
        stall_tr_limit = np.interp(vyse_curve_arr, stall_clipped_x, stall_clipped_y)

        valid_mask = (turn_rates_full >= y_min) & (turn_rates_full <= y_max) & (turn_rates_full <= stall_tr_limit)
        bank_angles_masked = bank_angles[valid_mask]
        vyse_display_curve = vyse_display_curve_full[valid_mask]
        turn_rates = turn_rates_full[valid_mask]

        # Build hover text
        vyse_hover = [
            f"<b>DVyse</b><br>Bank: {bank:.0f}°<br>Vyse: {spd:.0f} {unit}<br>Turn Rate: {tr:.1f}°/s"
            for bank, spd, tr in zip(bank_angles_masked, vyse_display_curve, turn_rates)
        ]

        # --- Plot DVyse line (clipped portion only)
        if len(vyse_display_curve) > 0:
            fig.add_trace(go.Scatter(
                x=vyse_display_curve,
                y=turn_rates,
                mode="lines",
                name="DVyse",
                line=dict(color="#00BFFF", width=2.5, dash="dot"),
                hoverinfo="text",
                hovertext=vyse_hover,
                showlegend=True
            ))

            x_max = max(x_max, vyse_display_curve[0] * 1.05)
            y_max = max(y_max, turn_rates[0] * 1.05)

        # Phase 5R-2: DVyse label at the curve's low-bank endpoint.
        v_speed_labels.append({
            "x": float(dvyse_label_value),
            "y": float(dvyse_label_tr),
            "text": f"<b>DVyse</b> {dvyse_label_value:.0f}",
            "color": "#00BFFF",
            "anchor": "curve-bottom",
        })


    # --- Published Vyse Line (Static Reference) ---
        if oei_active and published_vyse:
            vyse_display = convert_display_airspeed(published_vyse, unit)
            vyse_y_top = np.interp(published_vyse, g_clipped_x, g_clipped_y) if g_clipped_x else 0

            fig.add_trace(go.Scatter(
                x=[vyse_display, vyse_display],
                y=[0, vyse_y_top],
                mode="lines",
                name="Vyse",
                line=dict(color="#87CEEB", width=2, dash="dashdot"),
                hoverinfo="text",
                hovertext=f"<b>Vyse</b><br>{vyse_display:.0f} {unit}<br>(Best rate SE climb)"
            ))

            # Phase 5R-2: Vyse label at the top of its vertical line.
            v_speed_labels.append({
                "x": float(vyse_display),
                "y": float(vyse_y_top),
                "text": f"<b>Vyse</b> {vyse_display:.0f}",
                "color": "#87CEEB",
                "anchor": "line-top",
            })

    # --- Published Vxse Line (Static Reference) ---
        vxse_block = ac.get("single_engine_limits", {}).get("Vxse", {})
        if isinstance(vxse_block, dict):
            published_vxse = vxse_block.get("clean_up") or next(iter(vxse_block.values()), None)
        else:
            published_vxse = vxse_block if isinstance(vxse_block, (int, float)) else None
        if oei_active and published_vxse:
            vxse_display = convert_display_airspeed(published_vxse, unit)
            vxse_y_top = np.interp(published_vxse, g_clipped_x, g_clipped_y) if g_clipped_x else 0

            fig.add_trace(go.Scatter(
                x=[vxse_display, vxse_display],
                y=[0, vxse_y_top],
                mode="lines",
                name="Vxse",
                line=dict(color="#00CC66", width=2, dash="dash"),
                hoverinfo="text",
                hovertext=f"<b>Vxse</b><br>{vxse_display:.0f} {unit}<br>(Best angle SE climb)"
            ))

            # Phase 5R-2: Vxse label at the top of its vertical line.
            v_speed_labels.append({
                "x": float(vxse_display),
                "y": float(vxse_y_top),
                "text": f"<b>Vxse</b> {vxse_display:.0f}",
                "color": "#00CC66",
                "anchor": "line-top",
            })
        
    # --- Enhanced Hover Grid (Always Present) ---
    # Generate hover data grid covering the flight envelope
    hover_ias_step = 5  # IAS increment for hover grid
    hover_tr_step = 2   # Turn rate increment for hover grid

    # Create grid spanning the envelope
    hover_ias_range = np.arange(ias_start, max_speed_internal + 1, hover_ias_step)
    hover_tr_range = np.arange(0, 50, hover_tr_step)  # Positive turn rates

    hover_ias_list = []
    hover_tr_list = []
    hover_data = []  # Will hold [AOB, G, Ps, Radius] for each point

    for ias in hover_ias_range:
        for tr in hover_tr_range:
            v_fps = ias * KTS_TO_FPS
            omega_rad = tr * (np.pi / 180)

            # Calculate AOB from turn rate
            aob_deg = np.degrees(np.arctan(omega_rad * v_fps / g))

            # Calculate load factor (G)
            n = np.sqrt(1 + (v_fps * omega_rad / g) ** 2)

            # Calculate turn radius (ft -> nm for display)
            if omega_rad > 0.001:
                radius_ft = (v_fps ** 2) / (g * np.tan(np.radians(aob_deg))) if aob_deg > 0.5 else float('inf')
                radius_nm = radius_ft / 6076.12 if radius_ft < 1e6 else float('inf')
            else:
                radius_ft = float('inf')
                radius_nm = float('inf')

            # Calculate Ps at this point
            q = 0.5 * rho * v_fps ** 2
            CL_hover = weight * n / (q * wing_area) if q > 0 else 0
            CL_hover = min(CL_hover, cl_max)
            CD_hover = (CD0 + (CL_hover ** 2) / (np.pi * e * AR))
            # Phase 2g: super-parabolic high-CL drag rise (steep turns near stall)
            if cd_rise:
                cl_th = cd_rise.get("cl_threshold")
                k_r   = cd_rise.get("k_rise", 0.0)
                if cl_th is not None and k_r and CL_hover > cl_th:
                    CD_hover += k_r * (CL_hover - cl_th) ** 2
            CD_hover = CD_hover * cg_drag_factor * gear_drag_factor
            D_hover = q * wing_area * CD_hover

            V_max_kts = ac.get("prop_thrust_decay", {}).get("V_max_kts", 160)
            T_static = ac.get("prop_thrust_decay", {}).get("T_static_factor", 2.6) * hp
            V_fraction = np.clip(ias / V_max_kts, 0, 1)
            T_hover = T_static * (1 - V_fraction ** 2)

            Ps_hover = ((T_hover - D_hover) * v_fps / weight) * FPS_TO_KTS

            # Check if point is within envelope (above stall, below G limit)
            stall_n = (0.5 * rho * v_fps**2 * wing_area * cl_max) / weight
            n_limit = g_limit

            if n <= min(stall_n, n_limit) and n >= 1.0 and ias <= max_speed_internal:
                display_ias = convert_display_airspeed(ias, unit)
                hover_ias_list.append(display_ias)
                hover_tr_list.append(tr)
                hover_data.append([aob_deg, n, Ps_hover, radius_nm])

    # Add hover trace with enhanced tooltip
    if hover_ias_list:
        hover_customdata = np.array(hover_data)

        fig.add_trace(go.Scatter(
            x=hover_ias_list,
            y=hover_tr_list,
            customdata=hover_customdata,
            mode="markers",
            marker=dict(size=8, color="rgba(0,0,0,0)"),
            hovertemplate=(
                f"<b>IAS:</b> %{{x:.0f}} {unit}<br>"
                f"<b>Turn Rate:</b> %{{y:.1f}}°/s<br>"
                f"<b>Bank:</b> %{{customdata[0]:.0f}}°<br>"
                f"<b>Load Factor:</b> %{{customdata[1]:.2f}} G<br>"
                f"<b>Ps:</b> %{{customdata[2]:.1f}} kts/s<br>"
                f"<b>Turn Radius:</b> %{{customdata[3]:.2f}} nm"
                f"<extra></extra>"
            ),
            name="",
            showlegend=False
        ))

    # --- Ps Plotting (Toggle Controlled) ---

    if "ps" in overlay_toggle:
        try:
            ps_min = int(np.floor(np.nanmin(Ps_masked) / 10.0)) * 10
            ps_max = int(np.ceil(np.nanmax(Ps_masked) / 10.0)) * 10
            ps_levels = list(range(ps_min, ps_max + 1, 10))
        
            fig.add_trace(go.Contour(
                x=ias_vals_ps_display,
                y=tr_vals_ps,
                z=Ps_masked,
                contours=dict(
                    coloring="none", showlabels=False,
                    start=ps_min, end=ps_max, size=10
                ),
                line=dict(width=1, color=palette["muted"], dash="dot"),
                connectgaps=False,
                showscale=False,
                hoverinfo="skip",
                name="Ps"
            ))

            # Bold Ps = 0 overlay
            if 0 in ps_levels:
                fig.add_trace(go.Contour(
                    x=ias_vals_ps_display,
                    y=tr_vals_ps,
                    z=Ps_masked,
                    contours=dict(
                        coloring="none", showlabels=False,
                        start=0, end=0, size=1
                    ),
                    line=dict(width=3, color=palette["muted"], dash="dot"),
                    connectgaps=False,
                    showscale=False,
                    hoverinfo="skip",
                    showlegend=False
                ))

            # Phase 5R-5: Ps contour labels — quieter typography, smaller
            # footprint, signed values so positive vs negative reads at a
            # glance, anchored along the left edge of each contour where it
            # first becomes valid.
            for level in ps_levels:
                found = False
                for j in range(len(ias_vals_ps_display)):
                    for i in range(len(tr_vals_ps)):
                        ps_val = Ps_masked[i, j]
                        if np.isnan(ps_val):
                            continue
                        if np.isclose(ps_val, level, atol=2):
                            # Signed prefix makes "+10" / "0" / "-20" instantly distinguishable
                            label_text = f"{level:+d}" if level != 0 else "0"
                            fig.add_annotation(
                                x=ias_vals_ps_display[j] + 3,
                                y=tr_vals_ps[i],
                                text=label_text,
                                showarrow=False,
                                font=dict(
                                    color=palette["muted"],
                                    size=9,
                                    family="JetBrains Mono, Inter, sans-serif",
                                ),
                                bgcolor=palette["annotation_bg"],
                                borderpad=0,
                                opacity=0.85,
                            )
                            found = True
                            break
                    if found:
                        break
        except Exception as e:
            dprint(f"[DEBUG] Ps toggle failed: {e}")

    ###---Vmc published line (conditional on OEI, not Ps)----###
    if ac.get("engine_count", 1) > 1 and "enabled" in oei_toggle:
        vmca = ac.get("single_engine_limits", {}).get("Vmca", None)

        # Handle new-style dict Vmca format
        if isinstance(vmca, dict):
            # Choose the config to display (default to "clean_up" if available)
            selected_config = "clean_up" if "clean_up" in vmca else next(iter(vmca), None)
            vmca_value = vmca.get(selected_config)
        else:
            # Fallback if older float-style Vmca
            vmca_value = vmca

        if isinstance(vmca_value, (int, float)):
            vmca_converted = convert_display_airspeed(vmca_value, unit)
            # Clip to envelope top
            vmca_y_top = np.interp(vmca_value, g_clipped_x, g_clipped_y) if g_clipped_x else y_max

            fig.add_trace(go.Scatter(
                x=[vmca_converted, vmca_converted],
                y=[0, vmca_y_top],
                mode="lines",
                name="Published Vmca",
                line=dict(color="#FF6B6B", width=2, dash="dash"),
                hoverinfo="text",
                hovertext=f"<b>Published Vmca</b><br>{vmca_converted:.0f} {unit}<br>(Minimum controllable airspeed)"
            ))

            fig.add_annotation(
                x=vmca_converted,
                y=vmca_y_top,
                text=f"<b>Vmca</b> {vmca_converted:.0f}",
                showarrow=False,
                yshift=12,
                font=dict(size=9, color="#FF6B6B"),
                bgcolor=palette["annotation_bg"],
                xanchor="center"
            )

    # Final layout and return (outside toggle block!)
    x_min = max(0, min(ias_vals_display) - 2)  # two knot padding below ias_start
    x_max = max_speed_display * 1.1

# Final Y-Axis Limits Based on All Plotted TR Values
    turn_rate_values = []
    if stall_clipped_y: turn_rate_values += stall_clipped_y
    if g_clipped_y: turn_rate_values += g_clipped_y
    if "negative_g" in overlay_toggle:
        if 'neg_stall_y_clip' in locals(): turn_rate_values += neg_stall_y_clip
        if 'neg_g_y_clip' in locals(): turn_rate_values += neg_g_y_clip
    if "dynamic_vyse" in all_overlays and 'turn_rates' in locals():
        turn_rate_values += list(turn_rates)

    if turn_rate_values:
        y_max = max(turn_rate_values) * 1.1
        y_min = min(turn_rate_values) * 1.1 if min(turn_rate_values) < 0 else 0
    else:
        y_max = 100
        y_min = 0

    is_mobile = screen_width and screen_width < 768

    legend_font_size = 10 if is_mobile else 12

    # === V-SPEED LABEL PLACEMENT (Phase 5R-2) ===
    # Each label anchors to a sensible point on its own line/curve. When
    # multiple labels cluster within a small X-axis window they stack
    # vertically so none overlap horizontally. The legacy below-axis stack
    # (xaxis_speed_markers + corner + leader lines) is fully retired.
    v_speed_labels.sort(key=lambda l: (l["x"], l["y"]))
    cluster_x_threshold = max(4.0, (x_max - x_min) * 0.025)
    label_font_size = 10 if not is_mobile else 8
    line_height_paper = 0.045   # vertical spacing per stack level (in paper coords)

    for i, lab in enumerate(v_speed_labels):
        # Count overlapping labels with smaller x that are within the threshold
        stack_idx = 0
        for j in range(i):
            if abs(lab["x"] - v_speed_labels[j]["x"]) < cluster_x_threshold:
                stack_idx = max(stack_idx, v_speed_labels[j].get("_stack_idx", 0) + 1)
        lab["_stack_idx"] = stack_idx

        # Anchor-specific offsets. "line-top" sits above the line's top point;
        # "curve-bottom" sits above-right of the curve's low-bank endpoint.
        if lab["anchor"] == "line-top":
            xshift = 0
            yshift_base = 10
            xanchor = "center"
            yanchor = "bottom"
        else:                                # curve-bottom
            xshift = 6
            yshift_base = 10
            xanchor = "left"
            yanchor = "bottom"

        yshift = yshift_base + stack_idx * 18

        fig.add_annotation(
            x=lab["x"],
            y=lab["y"],
            xref="x",
            yref="y",
            text=lab["text"],
            showarrow=False,
            xshift=xshift,
            yshift=yshift,
            xanchor=xanchor,
            yanchor=yanchor,
            font=dict(size=label_font_size, color=lab["color"], family="JetBrains Mono, Inter, sans-serif"),
            bgcolor=palette["annotation_bg"],
            bordercolor=lab["color"],
            borderpad=2,
            borderwidth=1,
        )

        # Format into title (HTML-style for multi-line)
    fig.update_layout(
        title=dict(
            text=f"<b>{ac_name}</b>" if not is_mobile else ac_name,
            font=dict(size=22 if not is_mobile else 14, color=palette["title"]),
            x=0.5,
            y=0.95,
            xanchor="center",
            yanchor="top",
        ),
        xaxis=dict(
            title=f"Indicated Airspeed ({unit})",
            title_font=dict(size=14 if not is_mobile else 10, color=palette["text"]),
            tickfont=dict(size=12 if not is_mobile else 9, color=palette["tick"]),
            dtick=10,
            range=[x_min, x_max],
            showgrid=True,
            gridcolor=palette["grid"],
            linecolor=palette["axis_line"],
            tickcolor=palette["grid"],
            zerolinecolor=palette["grid"],
            showspikes=False,
            spikemode="across",
            spikesnap="cursor",
        ),
        yaxis=dict(
            title="Turn Rate (deg/sec)",
            title_font=dict(size=14 if not is_mobile else 10, color=palette["text"]),
            tickfont=dict(size=12 if not is_mobile else 9, color=palette["tick"]),
            dtick=5,
            range=[y_min, y_max],
            showgrid=True,
            gridcolor=palette["grid"],
            linecolor=palette["axis_line"],
            tickcolor=palette["grid"],
            zerolinecolor=palette["grid"],
            showspikes=False,
            spikemode="across",
            spikesnap="cursor",
        ),
        legend=dict(
            # Phase 5R-7: typographically aligned with the rest of the chart;
            # quieter border, traceorder=normal so envelope traces (lift/load)
            # come first, then overlays, then markers/refs.
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="center",
            x=0.5,
            font=dict(
                size=legend_font_size,
                color=palette["text"],
                family="Inter, system-ui, sans-serif",
            ),
            bgcolor=palette["annotation_bg"],
            bordercolor=palette["grid"],
            borderwidth=1,
            itemsizing="constant",
            itemwidth=30,
            traceorder="normal",
        ),
        margin=dict(
            t=60 if is_mobile else 100,
            b=120 if is_mobile else 105,
            l=40,
            r=40,
        ),
        paper_bgcolor=palette["paper_bg"],
        plot_bgcolor=palette["plot_bg"],
        font=dict(color=palette["text"]),
        hovermode="closest",
        hoverlabel=dict(
            bgcolor=palette["annotation_bg"],
            bordercolor=palette["grid"],
            font=dict(color=palette["text"], family="JetBrains Mono, Inter, sans-serif", size=12),
        ),
    )
    # === STEEP TURN MANEUVER TRACE ===
    if aob_values and ias_values and len(aob_values) > 0 and len(ias_values) > 0:
        aob_input = aob_values[0]
        ias_input = ias_values[0]

        # Guard against None values
        if ias_input is None or aob_input is None:
            ias_input = 110  # default
            aob_input = 45   # default

        v_fts = ias_input * KTS_TO_FPS
        bank_rad = np.radians(aob_input)
        tr_deg = np.degrees(G_FT_S2 * np.tan(bank_rad) / v_fts)

        # --- Energy Rate (Ps) at this point ---
        n = 1 / np.cos(bank_rad)  # load factor for level constant altitude turn
        q = 0.5 * rho * v_fts ** 2
        CL = weight * n / (q * wing_area)
        CL = min(CL, cl_max)  # Clip to CL_max like Ps grid does
        CD = (CD0 + (CL ** 2) / (np.pi * e * AR))
        # Phase 2g: super-parabolic high-CL drag rise (steep turns near stall)
        if cd_rise:
            cl_th = cd_rise.get("cl_threshold")
            k_r   = cd_rise.get("k_rise", 0.0)
            if cl_th is not None and k_r and CL > cl_th:
                CD += k_r * (CL - cl_th) ** 2
        CD = CD * cg_drag_factor * gear_drag_factor
        D = q * wing_area * CD

        # Apply prop thrust model (same as Ps logic)
        V_max_kts = ac.get("prop_thrust_decay", {}).get("V_max_kts", 160)
        T_static = ac.get("prop_thrust_decay", {}).get("T_static_factor", 2.6) * hp
        V_fraction = np.clip(ias_input / V_max_kts, 0, 1)
        T_avail = T_static * (1 - V_fraction**2)

        gamma_rad = np.radians(pitch_angle)
        Ps_steep = ((T_avail - D) * v_fts / weight - v_fts * np.sin(gamma_rad)) * FPS_TO_KTS

        dprint("[STEEP TURN DEBUG]")
        dprint(f"  IAS: {ias_input} KIAS, AOB: {aob_input}°")
        dprint(f"  Turn Rate: {tr_deg:.1f}°/s")
        dprint(f"  Ps: {Ps_steep:.2f} knots/sec")

        # Simplified steep turn trace: vertical line from 0 to operating point
        arc_tr = [0.0, tr_deg]
        arc_ias = [ias_input, ias_input]
        arc_ias_display = [ias * KTS_TO_MPH if unit == "MPH" else ias for ias in arc_ias]

        # Contextual hover text for each point
        steep_hover = [
            f"<b>Roll In (Wings Level)</b><br>AOB: 0°<br>IAS: {arc_ias_display[0]:.0f} {unit}<br>Turn Rate: 0°/s<br>G: 1.00",
            f"<b>Operating Point</b><br>AOB: {aob_input}°<br>IAS: {arc_ias_display[1]:.0f} {unit}<br>Turn Rate: {tr_deg:.1f}°/s<br>G: {n:.2f}<br>Ps: {Ps_steep:.1f} kts/s"
        ]

        fig.add_trace(go.Scatter(
            x=arc_ias_display,
            y=arc_tr,
            mode="lines+markers",
            line=dict(color="darkgreen", width=3),
            marker=dict(size=8, symbol=["circle", "diamond"]),
            name="Steep Turn",
            hoverinfo="text",
            hovertext=steep_hover,
            showlegend=True
        ))

        # Annotation at operating point showing key values
        fig.add_annotation(
            x=arc_ias_display[1],
            y=tr_deg,
            text=f"<b>{aob_input}° AOB</b><br>{n:.1f}G | Ps: {Ps_steep:.1f}",
            showarrow=True,
            arrowhead=2,
            ax=50,
            ay=-25,
            font=dict(size=10, color="darkgreen"),
            bgcolor=palette["annotation_bg"],
            borderpad=3
        )

        # Annotation at wings level
        fig.add_annotation(
            x=arc_ias_display[0],
            y=0,
            text="Wings Level",
            showarrow=False,
            yshift=-15,
            font=dict(size=9, color="darkgreen"),
            bgcolor=palette["annotation_bg"],
            borderpad=2
        )
    #------Ghost Trace------#
# === GHOST TRACE (Ideal AOB based on ACS Standard)
    # Check if ghost trace is enabled and a standard is selected
    # Handle both boolean (from Switch) and list (from Checklist)
    ghost_val = steepturn_ghost_values[0] if steepturn_ghost_values else False
    ghost_enabled = ghost_val is True or (isinstance(ghost_val, list) and "on" in ghost_val)
    standard_selected = steepturn_standard_values and len(steepturn_standard_values[0]) > 0

    if ghost_enabled and standard_selected:
        # Determine AOB based on selected standard(s) - use first selection
        selected_standard = steepturn_standard_values[0][0]  # "private" or "commercial"
        ghost_aob = 45 if selected_standard == "private" else 50
        ghost_ias = ias_values[0] if ias_values else 110  # fallback if none provided

        v_fts = ghost_ias * KTS_TO_FPS
        bank_rad = np.radians(ghost_aob)
        ghost_tr = np.degrees(G_FT_S2 * np.tan(bank_rad) / v_fts)

        ghost_tr_array = [0.0, ghost_tr, ghost_tr, 0.0, 0.0]
        ghost_ias_array = [ghost_ias] * len(ghost_tr_array)
        ghost_ias_display = [ias * KTS_TO_MPH if unit == "MPH" else ias for ias in ghost_ias_array]

        standard_label = "Private" if selected_standard == "private" else "Commercial"
        fig.add_trace(go.Scatter(
            x=ghost_ias_display,
            y=ghost_tr_array,
            mode="lines",
            line=dict(color="white", width=2, dash="dot"),
            name=f"{standard_label} ({ghost_aob}°)",
            hoverinfo="skip",
            showlegend=True
        ))
        fig.add_trace(go.Scatter(
            x=[ghost_ias_display[1]],
            y=[ghost_tr_array[1]],
            mode="markers",
            marker=dict(color="white", size=7, symbol="circle"),
            name="",
            hoverinfo="skip",
            showlegend=False
        ))
        
# === CHANDELLE MANEUVER TRACE ===
    def plot_chandelle(
        fig,
        chandelle_ias_start,
        chandelle_bank,
        stall_ias_kias,
        unit,
        color="darkgreen",
        dash="solid",
        label="Chandelle",
        show_annotations=True
    ):
        from plotly.graph_objects import Scatter
        from math import radians, tan, degrees, cos

        v_start = chandelle_ias_start * KTS_TO_FPS  # ft/s
        v_end = (stall_ias_kias + 5) * KTS_TO_FPS   # ft/s
        delta_v = v_start - v_end

        # Airspeed lost more aggressively with higher AOB
        energy_bias = min(0.8, max(0.5, chandelle_bank / 60))  # realistic range: 0.5–0.8
        v_90 = v_start - (delta_v * energy_bias)

        dt = 0.1
        max_turn_deg = 180.0
        angle = 0.0
        steps = 0
        max_steps = 1000

        airspeeds = []
        turn_rates = []
        aob_list = []
        heading_list = []

        while angle < max_turn_deg and steps < max_steps:
            if angle <= 90:
                # First half: lose 'energy_bias' fraction of Δv by 90°
                v = v_start - ((angle / 90.0) * (delta_v * energy_bias))
                aob_deg = chandelle_bank
            else:
                # Second half: lose remaining Δv after 90°, reduce AOB 1° per 3° turn
                v = v_90 - (((angle - 90) / 90.0) * (delta_v * (1 - energy_bias)))
                aob_deg = max(0, chandelle_bank - ((angle - 90) / 3.0))

            v = max(v, v_end)  # Never dip below final airspeed
            aob_rad = radians(aob_deg)
            omega_rad = G_FT_S2 * tan(aob_rad) / v
            tr = degrees(omega_rad)

            airspeeds.append(v * FPS_TO_KTS)
            turn_rates.append(tr)
            aob_list.append(aob_deg)
            heading_list.append(angle)

            angle += tr * dt
            steps += 1

        if not airspeeds:
            dprint("[WARN] No chandelle points generated.")
            return fig

        airspeeds_display = [ias * KTS_TO_MPH if unit == "MPH" else ias for ias in airspeeds]

        # Build contextual hover text with G load factor and heading progress
        hover_texts = []
        for i, (ias, tr, aob, hdg) in enumerate(zip(airspeeds_display, turn_rates, aob_list, heading_list)):
            g_load = 1 / cos(radians(aob)) if aob > 0 else 1.0
            if i == 0:
                phase = "<b>START</b>"
            elif hdg >= 175:
                phase = "<b>END</b>"
            elif hdg < 90:
                phase = f"First Half ({hdg:.0f}°)"
            else:
                phase = f"Second Half ({hdg:.0f}°)"
            hover_texts.append(
                f"{phase}<br>IAS: {ias:.0f} {unit}<br>Turn Rate: {tr:.1f}°/s<br>AOB: {aob:.0f}°<br>G: {g_load:.2f}<br>Heading: {hdg:.0f}°"
            )

        fig.add_trace(Scatter(
            x=airspeeds_display,
            y=turn_rates,
            mode="lines+markers",
            line=dict(color=color, width=3, dash=dash),
            marker=dict(size=4),
            name=label,
            hoverinfo="text",
            hovertext=hover_texts
        ))

        # Add START and END annotations (only for main trace, not ghost)
        if show_annotations and len(airspeeds_display) > 1:
            # START annotation (right side - high airspeed)
            fig.add_annotation(
                x=airspeeds_display[0],
                y=turn_rates[0],
                text="<b>START</b>",
                showarrow=True,
                arrowhead=2,
                ax=30,
                ay=-20,
                font=dict(size=10, color=color),
                bgcolor=palette["annotation_bg"],
                borderpad=2
            )
            # END annotation (left side - low airspeed)
            fig.add_annotation(
                x=airspeeds_display[-1],
                y=turn_rates[-1],
                text="<b>END</b>",
                showarrow=True,
                arrowhead=2,
                ax=-30,
                ay=-20,
                font=dict(size=10, color=color),
                bgcolor=palette["annotation_bg"],
                borderpad=2
            )
            # Direction indicator in middle
            mid_idx = len(airspeeds_display) // 2
            fig.add_annotation(
                x=airspeeds_display[mid_idx],
                y=turn_rates[mid_idx] + 1.5,
                text="← Energy Flow →",
                showarrow=False,
                font=dict(size=9, color=palette["muted"]),
                bgcolor=palette["annotation_bg"],
                borderpad=2
            )

        return fig

    if maneuver == "chandelle" and chandelle_ias_values and chandelle_bank_values:
        chandelle_ias = chandelle_ias_values[0]
        chandelle_bank = chandelle_bank_values[0]
        # Compute dynamic stall speed at 1G level turn
        v_stall_1g = np.sqrt((2 * weight) / (rho * wing_area * cl_max)) * FPS_TO_KTS
        stall_ias_kias = v_stall_1g

        fig = plot_chandelle(
            fig,
            chandelle_ias_start=chandelle_ias,
            chandelle_bank=chandelle_bank,
            stall_ias_kias=stall_ias_kias,
            unit=unit,
            color="darkgreen",
            dash="solid",
            label="Chandelle"
        )

        # Handle both boolean (from Switch) and list (from Checklist)
        chandelle_ghost_val = chandelle_ghost_values[0] if chandelle_ghost_values else False
        chandelle_ghost_on = chandelle_ghost_val is True or (isinstance(chandelle_ghost_val, list) and "on" in chandelle_ghost_val)
        if chandelle_ghost_on:
            fig = plot_chandelle(
                fig,
                chandelle_ias_start=chandelle_ias,
                chandelle_bank=30,
                stall_ias_kias=stall_ias_kias,
                unit=unit,
                color="white",
                dash="dot",
                label="Chandelle Ghost",
                show_annotations=False
            )

    # === LAZY EIGHT MANEUVER TRACE ===
    # Symmetric figure-8 commercial-ACS maneuver. Modeled as a full 360°
    # heading cycle with sinusoidal IAS / AOB envelopes (apex at 90°/270°,
    # level points at 0°/180°/360°). On the EM chart the trace closes back
    # on itself, but the time progression drives the replay scrubber so the
    # user sees the maneuver evolve from entry → apex → exit.
    def plot_lazy_eight(
        fig,
        entry_ias_kts,
        max_bank_deg,
        stall_ias_kias,
        unit,
        color="#0a47c9",   # brand-blue-dark for legibility on both themes
        dash="solid",
        label="Lazy Eight",
        show_annotations=True,
    ):
        from plotly.graph_objects import Scatter
        from math import radians, tan, degrees, cos, sin, pi

        # Floor the minimum IAS at the apex above stall + buffer
        min_ias = max(stall_ias_kias + 5, entry_ias_kts * 0.6)

        # 80 samples over 360° gives a smooth loop without spamming the trace
        n_steps = 80
        airspeeds = []
        turn_rates = []
        aob_list = []
        heading_list = []
        for i in range(n_steps + 1):
            hdg_deg = (360.0 * i) / n_steps      # 0 → 360
            hdg_rad = radians(hdg_deg)
            envelope = abs(sin(hdg_rad))         # 0 at level pts, 1 at apex/nadir
            ias = entry_ias_kts - (entry_ias_kts - min_ias) * envelope
            aob = max_bank_deg * envelope
            v_fts = ias * KTS_TO_FPS
            if aob > 0.1 and v_fts > 1:
                tr = degrees(G_FT_S2 * tan(radians(aob)) / v_fts)
            else:
                tr = 0.0
            airspeeds.append(ias)
            turn_rates.append(tr)
            aob_list.append(aob)
            heading_list.append(hdg_deg)

        airspeeds_display = [ias * KTS_TO_MPH if unit == "MPH" else ias for ias in airspeeds]

        # Hover text in the same shape as plot_chandelle (so the shared
        # replayManeuver clientside callback can decode it).
        hover_texts = []
        for i, (ias, tr, aob, hdg) in enumerate(zip(airspeeds_display, turn_rates, aob_list, heading_list)):
            g_load = 1 / cos(radians(aob)) if aob > 0.1 else 1.0
            if hdg < 45:
                phase = "<b>ENTRY</b>" if hdg < 5 else f"45° UP ({hdg:.0f}°)"
            elif hdg < 90:
                phase = f"Climb ({hdg:.0f}°)"
            elif hdg < 95:
                phase = "<b>APEX</b>"
            elif hdg < 180:
                phase = f"Descent ({hdg:.0f}°)"
            elif hdg < 270:
                phase = f"Reverse climb ({hdg:.0f}°)"
            elif hdg < 360:
                phase = f"Reverse descent ({hdg:.0f}°)"
            else:
                phase = "<b>EXIT</b>"
            hover_texts.append(
                f"{phase}<br>IAS: {ias:.0f} {unit}<br>Turn Rate: {tr:.1f}°/s<br>AOB: {aob:.0f}°<br>G: {g_load:.2f}<br>Heading: {hdg:.0f}°"
            )

        fig.add_trace(Scatter(
            x=airspeeds_display,
            y=turn_rates,
            mode="lines+markers",
            line=dict(color=color, width=3, dash=dash),
            marker=dict(size=4),
            name=label,
            hoverinfo="text",
            hovertext=hover_texts,
        ))

        if show_annotations and len(airspeeds_display) > 1:
            entry_idx = 0
            apex_idx = n_steps // 4               # heading 90°
            fig.add_annotation(
                x=airspeeds_display[entry_idx],
                y=turn_rates[entry_idx],
                text="<b>ENTRY/EXIT</b>",
                showarrow=True, arrowhead=2, ax=30, ay=-20,
                font=dict(size=10, color=color),
                bgcolor=palette["annotation_bg"], borderpad=2,
            )
            fig.add_annotation(
                x=airspeeds_display[apex_idx],
                y=turn_rates[apex_idx],
                text="<b>APEX</b>",
                showarrow=True, arrowhead=2, ax=-30, ay=-20,
                font=dict(size=10, color=color),
                bgcolor=palette["annotation_bg"], borderpad=2,
            )

        return fig

    if maneuver == "lazy_eight" and lazy8_ias_values and lazy8_bank_values:
        lazy8_ias  = lazy8_ias_values[0]
        lazy8_bank = lazy8_bank_values[0]
        v_stall_1g = np.sqrt((2 * weight) / (rho * wing_area * cl_max)) * FPS_TO_KTS

        fig = plot_lazy_eight(
            fig,
            entry_ias_kts=lazy8_ias,
            max_bank_deg=lazy8_bank,
            stall_ias_kias=v_stall_1g,
            unit=unit,
            color="#0a47c9",
            dash="solid",
            label="Lazy Eight",
        )

        lazy8_ghost_val = lazy8_ghost_values[0] if lazy8_ghost_values else False
        lazy8_ghost_on = lazy8_ghost_val is True or (isinstance(lazy8_ghost_val, list) and "on" in lazy8_ghost_val)
        if lazy8_ghost_on:
            fig = plot_lazy_eight(
                fig,
                entry_ias_kts=lazy8_ias,
                max_bank_deg=30,
                stall_ias_kias=v_stall_1g,
                unit=unit,
                color="white",
                dash="dot",
                label="Lazy Eight Ghost",
                show_annotations=False,
            )

    # ────────────────────────────────────────────────────────────────────
    # Phase 5U — Comparative aircraft overlay
    # When a second aircraft is picked, render JUST its lift limit + load
    # limit + corner on top of the primary chart, using the SAME atmospheric
    # state (rho, weight basis) so the comparison is apples-to-apples. We
    # deliberately skip Ps contours / AOB heatmap / turn radius for the
    # comparison aircraft — two of those overlays make the chart unreadable.
    # ────────────────────────────────────────────────────────────────────
    if compare_aircraft and compare_aircraft in aircraft_data and compare_aircraft != ac_name:
        try:
            ac2 = aircraft_data[compare_aircraft]
            wa2 = ac2.get("wing_area", wing_area)
            cl_max_block2 = ac2.get("CL_max", {})
            cl_max2 = cl_max_block2.get(config) or cl_max_block2.get("clean") or cl_max
            # Same load-factor category as primary, fall back to primary's g_limit
            g_limits2 = (ac2.get("G_limits", {}) or {}).get(selected_category or "normal", {}) \
                          .get(config or "clean", {})
            g_limit2 = g_limits2.get("positive") or g_limit
            # Stall speed in current config — interpolate ac2's own weight table by primary weight
            # (`interpolate_stall_speed` is already imported at module top.)
            stall2_table = (ac2.get("stall_speeds") or {}).get(config) or (ac2.get("stall_speeds") or {}).get("clean")
            try:
                vs2_1g = interpolate_stall_speed(stall2_table or {}, weight) if stall2_table else 50
            except Exception:
                vs2_1g = 50
            vne2 = ac2.get("Vne") or max_speed
            ias2_max = min(vne2, max_speed_kt := max_speed)  # share the primary's plot bounds

            # Stall (lift) curve for ac2
            stall2_x, stall2_y = [], []
            stall2_fine = np.concatenate([
                np.arange(max(ias_start, vs2_1g - 5), vs2_1g + 15, 0.5),
                np.arange(vs2_1g + 15, ias2_max + 1, 2.0),
            ])
            for ias_i in stall2_fine:
                v = ias_i * KTS_TO_FPS
                n_stall = (0.5 * rho * v * v * wa2 * cl_max2) / weight
                if n_stall >= 1:
                    omega = g * ((n_stall ** 2 - 1) ** 0.5) / v
                    tr_i = omega * 180 / pi
                    if not stall2_x:
                        stall2_x.append(ias_i); stall2_y.append(0)
                    stall2_x.append(ias_i); stall2_y.append(tr_i)

            # Load-factor curve for ac2
            g2_x, g2_y = [], []
            for ias_i in np.arange(ias_start, ias2_max + 1, 1.0):
                v = ias_i * KTS_TO_FPS
                omega = g * ((g_limit2 ** 2 - 1) ** 0.5) / v
                g2_x.append(ias_i); g2_y.append(omega * 180 / pi)

            # Corner intersection for ac2
            corner2_ias, corner2_tr = None, float("inf")
            for ias_i in np.arange(ias_start, ias2_max + 1, 1.0):
                if not stall2_x or not g2_x:
                    break
                stall_tr = np.interp(ias_i, stall2_x, stall2_y)
                g_tr = np.interp(ias_i, g2_x, g2_y)
                if abs(stall_tr - g_tr) < abs(corner2_tr - (corner2_tr if corner2_ias else 0)) or corner2_ias is None:
                    if abs(stall_tr - g_tr) < 1.0:
                        corner2_ias = ias_i
                        corner2_tr  = stall_tr
                        break

            if corner2_ias is not None:
                # Clip to corner — same trick as the primary curves (Phase 5R-1)
                stall2_clip_x = [x for x in stall2_x if x < corner2_ias] + [corner2_ias]
                stall2_clip_y = stall2_y[:len(stall2_clip_x) - 1] + [corner2_tr]
                g2_clip_x = [corner2_ias] + [x for x in g2_x if x > corner2_ias]
                g2_clip_y = [corner2_tr] + g2_y[-(len(g2_clip_x) - 1):]
            else:
                stall2_clip_x, stall2_clip_y = stall2_x, stall2_y
                g2_clip_x, g2_clip_y = g2_x, g2_y

            # ── Plot dashed comparison traces ─────────────────────────
            # Comparison palette: brand orange so it pops against the
            # primary's red/black envelope without conflicting with the
            # viridis AOB heatmap underneath.
            CMP_COLOR = "#f27b0d"   # --ta-brand-orange
            CMP_DASH = "dash"
            stall2_disp = convert_display_airspeed(np.array(stall2_clip_x), unit)
            g2_disp     = convert_display_airspeed(np.array(g2_clip_x), unit)

            fig.add_trace(go.Scatter(
                x=stall2_disp, y=stall2_clip_y,
                mode="lines",
                name=f"{compare_aircraft} — Lift",
                line=dict(color=CMP_COLOR, width=2.5, dash=CMP_DASH),
                hoverinfo="text",
                hovertext=f"{compare_aircraft}<br>Lift limit (n=1 stall boundary)",
            ))
            fig.add_trace(go.Scatter(
                x=g2_disp, y=g2_clip_y,
                mode="lines",
                name=f"{compare_aircraft} — Load ({g_limit2:.1f} G)",
                line=dict(color=CMP_COLOR, width=2.5, dash=CMP_DASH),
                hoverinfo="text",
                hovertext=f"{compare_aircraft}<br>Load limit ({g_limit2:.1f} G)",
            ))
            if corner2_ias is not None:
                corner2_disp = convert_display_airspeed(corner2_ias, unit)
                fig.add_trace(go.Scatter(
                    x=[corner2_disp], y=[corner2_tr],
                    mode="markers",
                    name=f"{compare_aircraft} corner",
                    marker=dict(color=CMP_COLOR, size=10, symbol="diamond-open"),
                    hoverinfo="text",
                    hovertext=f"{compare_aircraft}<br>Corner: {corner2_disp:.0f} {unit}",
                ))
                fig.add_annotation(
                    x=corner2_disp, y=corner2_tr,
                    text=f"<b>{corner2_disp:.0f}</b> {unit}",
                    showarrow=False,
                    xshift=14, yshift=-14,
                    xanchor="left", yanchor="top",
                    font=dict(color=CMP_COLOR, size=11, family="JetBrains Mono, Inter, sans-serif"),
                    bgcolor=palette["annotation_bg"],
                    bordercolor=CMP_COLOR,
                    borderpad=3, borderwidth=1,
                )

            # Phase 5U fix — rescale axes so the comparison envelope is fully
            # visible. Without this, an aircraft with higher Vne or higher G
            # limit gets clipped against the primary's axis bounds.
            cmp_x_max_kt = max(
                float(np.max(stall2_disp)) if len(stall2_disp) else 0.0,
                float(np.max(g2_disp))     if len(g2_disp)     else 0.0,
                float(corner2_disp)        if corner2_ias is not None else 0.0,
            )
            cmp_y_max = max(
                max(stall2_clip_y) if stall2_clip_y else 0.0,
                max(g2_clip_y)     if g2_clip_y     else 0.0,
            )
            new_x_max = max(x_max, cmp_x_max_kt * 1.05)
            new_y_max = max(y_max, cmp_y_max     * 1.10)
            fig.update_layout(
                xaxis=dict(range=[x_min, new_x_max]),
                yaxis=dict(range=[y_min, new_y_max]),
            )
        except Exception as exc:
            dprint(f"[5U] comparison render failed: {exc}")

    # ── Phase 5AC: scenario probe marker ──────────────────────────────────
    # User clicked somewhere on the doghouse. Draw a probe marker and
    # annotate the bank angle, G load, and turn radius required to fly
    # at that (V, ω) operating point — coordinated level turn assumed.
    if probe and isinstance(probe, dict):
        try:
            import math as _math
            px = float(probe.get("v_disp", 0))
            py = float(probe.get("omega_dps", 0))
            unit_up = (unit or "KIAS").upper()
            v_kt   = px / KTS_TO_MPH if unit_up == "MPH" else px
            v_fps  = v_kt * KTS_TO_FPS
            omega_dps = py
            omega_rps = _math.radians(omega_dps)
            if v_fps > 1 and abs(omega_rps) > 1e-4:
                tan_theta = abs(omega_rps) * v_fps / g
                theta_deg = _math.degrees(_math.atan(tan_theta))
                n_load    = 1.0 / _math.cos(_math.radians(theta_deg)) if theta_deg < 89 else 99.0
                radius_ft = v_fps / abs(omega_rps)
                probe_label = (f"<b>Probe</b><br>"
                               f"Bank: {theta_deg:.0f}°<br>"
                               f"G: {n_load:.2f}<br>"
                               f"Radius: {radius_ft:.0f} ft")
            else:
                theta_deg = 0
                n_load = 1.0
                radius_ft = 0
                probe_label = f"<b>Probe</b><br>V: {px:.0f} {unit_up}<br>ω: {py:.1f} °/s"

            fig.add_trace(go.Scatter(
                x=[px], y=[py],
                mode="markers",
                marker=dict(color=palette["title"], size=14, symbol="diamond-open",
                            line=dict(color=palette["title"], width=2.5)),
                name="Scenario probe",
                hoverinfo="text",
                hovertext=probe_label,
                showlegend=False,
            ))
            fig.add_annotation(
                x=px, y=py,
                xref="x", yref="y",
                showarrow=True,
                arrowhead=2, arrowsize=1.0, arrowwidth=1.5,
                arrowcolor=palette["title"],
                ax=18, ay=-32, axref="pixel", ayref="pixel",
                text=probe_label,
                font=dict(size=11, color=palette["title"], family="JetBrains Mono, Inter, sans-serif"),
                bgcolor=palette["annotation_bg"],
                bordercolor=palette["title"],
                borderpad=4, borderwidth=1,
                xanchor="left", yanchor="bottom",
            )
        except Exception as exc:
            dprint(f"[5AC] probe render failed: {exc}")

    t_end = time.perf_counter()
    dprint(f"[PERF] update_graph total: {(t_end - t_start):.3f} sec")

    return fig



def register(app):
    """Wire the EM-diagram chart callback to the given Dash app."""
    from dash import callback_context, no_update
    app.callback(
        Output("em-graph", "figure"),
        Input("aircraft-select", "value"),
        Input("config-select", "value"),
        Input("engine-select", "value"),
        Input("occupants-select", "value"),
        Input("fuel-slider", "value"),
        Input("altitude-slider", "value"),
        Input("stored-total-weight", "data"),
        Input("power-setting", "value"),
        Input("overlay-toggle", "data"),
        Input("gear-select", "value"),
        Input("oei-toggle", "value"),
        Input("prop-condition", "data"),
        Input("cg-slider", "value"),
        Input("category-select", "value"),
        Input("unit-select", "data"),
        Input("multi-engine-toggle-options", "data"),
        Input("maneuver-select", "value"),
        Input({"type": "steepturn-aob", "index": ALL}, "value"),
        Input({"type": "steepturn-ias", "index": ALL}, "value"),
        Input({"type": "steepturn-standard", "index": ALL}, "value"),
        Input({"type": "steepturn-ghost", "index": ALL}, "value"),
        Input({"type": "chandelle-ias", "index": ALL}, "value"),
        Input({"type": "chandelle-bank", "index": ALL}, "value"),
        Input({"type": "chandelle-ghost", "index": ALL}, "value"),
        Input({"type": "lazy8-ias", "index": ALL}, "value"),
        Input({"type": "lazy8-bank", "index": ALL}, "value"),
        Input({"type": "lazy8-ghost", "index": ALL}, "value"),
        Input("pitch-angle", "value"),
        Input("screen-width", "data"),
        Input("oat-input", "value"),
        Input("altimeter-input", "value"),
        Input("theme-pref", "data"),
        Input("compare-aircraft", "data"),
        Input("doghouse-probe", "data"),
    )(update_graph)

    # Phase 5AC — click on the doghouse drops a scenario probe at (V, ω).
    # update_graph reads `doghouse-probe.data` and renders the annotation.
    @app.callback(
        Output("doghouse-probe", "data"),
        Input("em-graph", "clickData"),
        Input("clear-doghouse-probe", "n_clicks"),
        Input("aircraft-select", "value"),
        State("chart-tab", "data"),
        prevent_initial_call=True,
    )
    def _set_or_clear_probe(click_data, _clear_n, _ac_changed, chart_tab):
        trig = callback_context.triggered_id
        if trig in ("clear-doghouse-probe", "aircraft-select"):
            return None
        if chart_tab and chart_tab != "maneuver":
            return no_update
        if not click_data or not click_data.get("points"):
            return no_update
        pt = click_data["points"][0]
        if pt.get("hovertext", "").startswith("<b>Probe</b>"):
            return None
        return {"v_disp": float(pt["x"]), "omega_dps": float(pt["y"])}

    # Phase 5AC — show the clear-probe chip only when probe is set AND
    # we're on the doghouse tab (mirrors the h-V clear-target pattern).
    @app.callback(
        Output("clear-doghouse-probe", "style"),
        Input("doghouse-probe", "data"),
        Input("chart-tab",       "data"),
    )
    def _toggle_clear_probe(probe, active_tab):
        if probe and (active_tab == "maneuver" or active_tab is None):
            return {"display": "inline-flex"}
        return {"display": "none"}
