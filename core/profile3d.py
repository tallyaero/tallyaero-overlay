"""Shared 3D track-figure builder for altitude-changing maneuvers.

Returns a Plotly figure with the simulated flight path drawn as a
3D scatter line, colored by phase (when available) or altitude.
The figure ships with Plotly's mouse-drag camera + a few canned
preset views, so the pilot can rotate before flying.

Used by engineout, poweroff180, impossible_turn, chandelle,
lazy_eight, and steep_spiral results modals.

Distance is shown in nautical miles (relative to the start point)
and altitude in feet (AGL or MSL depending on what the caller
passes). Aspect ratio uses Plotly's `data` mode in X/Y so the
ground footprint stays geographically true, with a tunable Z
exaggeration so a 2,000-ft maneuver doesn't pancake.
"""
from __future__ import annotations

import math

import plotly.graph_objects as go

# Match the airspace TYPE_STYLES palette so phase chips read the
# same on every screen of the app.
_PHASE_COLORS = {
    "downwind": "#1d4ed8",
    "base": "#0891b2",
    "final": "#15803d",
    "touchdown": "#16a34a",
    "spiral_entry": "#a855f7",
    "spiral": "#a855f7",
    "opposite_spiral": "#7c3aed",
    "final_spiral": "#7c3aed",
    "on_glidepath": "#15803d",
    "abeam": "#0891b2",
    "departure": "#0050a0",
    "climb": "#0891b2",
    "cruise": "#15803d",
    "descent": "#d97706",
    "approach": "#dc2626",
    "miss": "#dc2626",
    # Engine-out backward-construction planner phases (eo_executor):
    "engine_failure": "#dc2626",
    "entry":          "#0050a0",
    "to_abeam":       "#0050a0",
    "to_high_key":    "#0050a0",
    "to_low_key":     "#1d4ed8",
    "base_turn":      "#0891b2",
    "final_turn":     "#15803d",
    "po180":          "#0891b2",
    "straight_in":    "#0050a0",
    "transit":        "#475569",
}
_DEFAULT_COLOR = "#475569"

# Earth radius in ft / nm.
_FT_PER_NM = 6076.115
_EARTH_NM = 3440.065


def _ll_to_xy_nm(lat: float, lon: float,
                  lat0: float, lon0: float) -> tuple[float, float]:
    """Equirectangular projection to NM offset from (lat0, lon0).
    Good enough for any maneuver — total displacement is <10 NM."""
    cos_lat = math.cos(math.radians(lat0))
    dx = (lon - lon0) * cos_lat * 60.0   # 60 NM per degree of longitude * cos(lat)
    dy = (lat - lat0) * 60.0              # 60 NM per degree of latitude
    return dx, dy


def make_3d_track_figure(*,
                          path_lat: list[float],
                          path_lon: list[float],
                          alts_ft: list[float],
                          phases: list[str] | None = None,
                          phase_markers: list[dict] | None = None,
                          runway: dict | None = None,
                          vertical_features: list[dict] | None = None,
                          title: str | None = None,
                          height: int = 420,
                          z_exaggeration: float = 4.0) -> go.Figure:
    """Build the 3D figure.

    Args:
        path_lat / path_lon / alts_ft: per-step samples (length-matched).
        phases: per-step phase string, used to color the line. If
            omitted, color falls back to a single track color.
        phase_markers: optional list of {label, lat, lon, alt_ft} that
            get rendered as labeled dots (entry/abeam/base/touchdown).
        runway: optional {start_lat, start_lon, end_lat, end_lon,
            elev_ft, width_ft} — draws a rectangle on the ground plane.
        title: figure title.
        height: pixels.
        z_exaggeration: multiplier on the vertical axis so a 1000-ft
            maneuver doesn't read as a thin sliver. Default 4× — the
            tooltip shows real altitude regardless.

    Returns:
        plotly.graph_objects.Figure ready for dcc.Graph.
    """
    if not path_lat or len(path_lat) != len(path_lon) or len(path_lat) != len(alts_ft):
        # Degenerate — return an empty figure so the modal still mounts.
        return go.Figure(layout={"height": height,
                                  "title": title or "No path data"})

    lat0, lon0 = path_lat[0], path_lon[0]
    xs, ys = zip(*(_ll_to_xy_nm(la, lo, lat0, lon0)
                    for la, lo in zip(path_lat, path_lon)))
    zs = list(alts_ft)

    # Build phase-segmented line so each phase gets its own color +
    # appears in the legend. Plotly Scatter3d doesn't accept per-point
    # colors for a `lines` mode, so we split into per-phase traces.
    traces: list = []
    if phases and len(phases) == len(path_lat):
        # Walk runs of identical phase
        i = 0
        n = len(phases)
        # Track which phases we've added to the legend so each phase
        # only shows once.
        legend_seen: set = set()
        while i < n:
            phase = phases[i]
            j = i + 1
            while j < n and phases[j] == phase:
                j += 1
            # Include the next point too so segments connect cleanly.
            end = min(j + 1, n)
            label = (phase or "").replace("_", " ").title() or "Track"
            color = _PHASE_COLORS.get((phase or "").lower(), _DEFAULT_COLOR)
            show_in_legend = label not in legend_seen
            legend_seen.add(label)
            traces.append(go.Scatter3d(
                x=xs[i:end], y=ys[i:end], z=zs[i:end],
                mode="lines",
                line={"color": color, "width": 5},
                name=label,
                showlegend=show_in_legend,
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    "Alt: %{z:.0f} ft<br>"
                    "X: %{x:.2f} NM<br>"
                    "Y: %{y:.2f} NM<extra></extra>"
                ),
            ))
            i = j
    else:
        traces.append(go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="lines",
            line={"color": "#0050a0", "width": 5},
            name="Track",
            hovertemplate=(
                "Alt: %{z:.0f} ft<br>"
                "X: %{x:.2f} NM<br>"
                "Y: %{y:.2f} NM<extra></extra>"
            ),
        ))

    # Phase transition markers
    if phase_markers:
        mxs, mys, mzs, labels = [], [], [], []
        for m in phase_markers:
            mx, my = _ll_to_xy_nm(m["lat"], m["lon"], lat0, lon0)
            mxs.append(mx); mys.append(my)
            mzs.append(m.get("alt_ft", 0.0))
            labels.append(m.get("label", ""))
        traces.append(go.Scatter3d(
            x=mxs, y=mys, z=mzs,
            mode="markers+text",
            marker={"size": 6, "color": "#dc2626",
                    "line": {"color": "#fff", "width": 1}},
            text=labels, textposition="top center",
            textfont={"size": 10, "color": "#1e293b"},
            name="Phase markers",
            showlegend=False,
            hovertemplate="<b>%{text}</b><br>Alt: %{z:.0f} ft<extra></extra>",
        ))

    # Optional vertical features (e.g. eights-on-pylons reference pylons).
    # Each entry: {lat, lon, alt_ft_base, alt_ft_top, label, color}.
    # Renders as a colored vertical pole + a base dot + a label at the top.
    # Used by maneuvers where ground objects need to be visible in the
    # 3D side view to give the pilot spatial context.
    if vertical_features:
        for vf in vertical_features:
            try:
                vx, vy = _ll_to_xy_nm(vf["lat"], vf["lon"], lat0, lon0)
            except (KeyError, TypeError):
                continue
            base = float(vf.get("alt_ft_base", 0.0))
            top = float(vf.get("alt_ft_top", base + 1000.0))
            color = vf.get("color", "#dc2626")
            label = vf.get("label", "")
            # Vertical pole from base to top.
            traces.append(go.Scatter3d(
                x=[vx, vx], y=[vy, vy], z=[base, top],
                mode="lines",
                line={"color": color, "width": 6},
                name=label or "Pylon",
                showlegend=bool(label),
                hovertemplate=(f"<b>{label}</b><br>"
                               "Alt: %{z:.0f} ft<extra></extra>"),
            ))
            # Base marker + label at top.
            traces.append(go.Scatter3d(
                x=[vx, vx], y=[vy, vy], z=[base, top],
                mode="markers+text",
                marker={"size": [8, 6], "color": color,
                        "line": {"color": "#fff", "width": 1}},
                text=["", label],
                textposition="top center",
                textfont={"size": 11, "color": color},
                showlegend=False,
                hoverinfo="skip",
            ))

    # Optional runway rectangle on the ground plane
    if runway and all(k in runway for k in ("start_lat", "start_lon",
                                              "end_lat", "end_lon")):
        rsx, rsy = _ll_to_xy_nm(runway["start_lat"], runway["start_lon"],
                                  lat0, lon0)
        rex, rey = _ll_to_xy_nm(runway["end_lat"], runway["end_lon"],
                                  lat0, lon0)
        elev = runway.get("elev_ft", 0.0)
        # Centerline
        traces.append(go.Scatter3d(
            x=[rsx, rex], y=[rsy, rey], z=[elev, elev],
            mode="lines+markers",
            line={"color": "#1e293b", "width": 6},
            marker={"size": 4, "color": "#1e293b"},
            name="Runway",
            hovertemplate="Runway<br>Elev: %{z:.0f} ft<extra></extra>",
        ))

    fig = go.Figure(data=traces)
    # Equal X/Y aspect; Z exaggerated for readability.
    # Plotly's aspectmode='data' uses true scale; 'manual' with explicit
    # ratios lets us bump Z.
    x_span = max(xs) - min(xs) if xs else 1
    y_span = max(ys) - min(ys) if ys else 1
    z_span_ft = (max(zs) - min(zs)) if zs else 100
    # Convert Z span from ft to NM for ratio calc
    z_span_nm = z_span_ft / _FT_PER_NM
    ground_span = max(x_span, y_span, 0.5)
    z_ratio = max(0.2, (z_span_nm / ground_span) * z_exaggeration)
    fig.update_layout(
        title=title,
        height=height,
        margin={"l": 0, "r": 0, "t": 36 if title else 8, "b": 0},
        scene={
            "xaxis": {"title": "East (NM)", "showgrid": True,
                       "zeroline": False, "showspikes": False},
            "yaxis": {"title": "North (NM)", "showgrid": True,
                       "zeroline": False, "showspikes": False},
            "zaxis": {"title": "Altitude (ft)", "showgrid": True,
                       "zeroline": False, "showspikes": False},
            "aspectmode": "manual",
            "aspectratio": {"x": x_span / ground_span,
                              "y": y_span / ground_span,
                              "z": z_ratio},
            # Slight north-east elevated isometric default.
            "camera": {"eye": {"x": 1.5, "y": -1.5, "z": 1.0}},
        },
        legend={"orientation": "h", "yanchor": "bottom", "y": 0.0,
                  "xanchor": "center", "x": 0.5, "bgcolor": "rgba(0,0,0,0)",
                  "font": {"size": 10}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def build_3d_side_view_block(*,
                              path: list,
                              hover: list,
                              elev_ft: float = 0.0,
                              runway: dict | None = None,
                              phase_markers: list[dict] | None = None,
                              vertical_features: list[dict] | None = None,
                              height: int = 380,
                              alt_key_priority: tuple = ("alt", "alt_agl", "alt_msl"),
                              ):
    """One-shot helper used by every altitude-changing maneuver's
    results modal. Returns a Dash component ready to drop into an
    AccordionItem — either a `dcc.Graph` with the figure or a styled
    fallback `<div>` if the path can't be reconstructed.

    Args:
        path: per-step [lat, lon] pairs (length-matched to hover).
        hover: per-step telemetry dicts. Reads altitude from the first
            present key in `alt_key_priority` and the phase from
            `phase` or `segment`.
        elev_ft: field elevation in MSL feet, ADDED to per-step alt
            when the chosen alt key looks AGL (i.e. key is "alt" or
            "alt_agl"). If the key is "alt_msl" the value is passed
            through unchanged.
        runway: optional {start_lat, start_lon, end_lat, end_lon, elev_ft}
            drawn as a ground centerline.
        phase_markers: optional [{label, lat, lon, alt_ft}, ...].
        height: pixels.
        alt_key_priority: keys to check in order when picking altitude.

    Falls back gracefully if `path` is empty / hover is short / etc. —
    the modal always renders.
    """
    from dash import dcc, html

    try:
        if not path or not hover:
            return html.Div("3D side view unavailable: no path data.",
                            style={"fontSize": "11px", "color": "#94a3b8",
                                   "padding": "12px"})

        # Resolve the altitude PER STEP, not once for the whole stream —
        # impossible_turn's takeoff/climb hover entries use `alt_agl`,
        # but the post-failure glide entries use `alt`. Picking one key
        # globally would zero-out the half that doesn't have it, which
        # collapsed the entire glide-back portion onto the ground in
        # earlier builds.
        agl_keys = {"alt", "alt_agl"}

        def _resolve_alt(h: dict) -> float:
            for k in alt_key_priority:
                v = h.get(k)
                if v is not None:
                    f = float(v)
                    return f + float(elev_ft) if k in agl_keys else f
            return float(elev_ft)

        lat3d = [p[0] for p in path]
        lon3d = [p[1] for p in path]
        alts3d = [_resolve_alt(h) for h in hover]
        phases3d = [h.get("phase") or h.get("segment") or "" for h in hover]

        # Length-align to the shortest stream so off-by-ones don't crash.
        n = min(len(lat3d), len(alts3d), len(phases3d))
        if n < 2:
            return html.Div("3D side view unavailable: path too short.",
                            style={"fontSize": "11px", "color": "#94a3b8",
                                   "padding": "12px"})
        lat3d, lon3d = lat3d[:n], lon3d[:n]
        alts3d, phases3d = alts3d[:n], phases3d[:n]

        fig = make_3d_track_figure(
            path_lat=lat3d, path_lon=lon3d, alts_ft=alts3d,
            phases=phases3d, runway=runway, phase_markers=phase_markers,
            vertical_features=vertical_features,
            height=height,
        )
        return dcc.Graph(figure=fig,
                         config={"displayModeBar": False},
                         style={"width": "100%"})
    except Exception:
        return html.Div("3D side view unavailable for this run.",
                        style={"fontSize": "11px", "color": "#94a3b8",
                               "padding": "12px"})


def side_view_accordion_item(side_view_block, title: str = "3D Side View"):
    """Wraps a 3D block in a `dbc.AccordionItem` with the same
    rotate-zoom hint used by engine-out, so every maneuver picks up
    the affordance for free.
    """
    from dash import html
    import dash_bootstrap_components as dbc
    return dbc.AccordionItem(
        [
            html.Div("Drag to rotate. Scroll to zoom. "
                     "Vertical axis is exaggerated for readability.",
                     style={"fontSize": "10px", "color": "#94a3b8",
                            "marginBottom": "4px"}),
            side_view_block,
        ],
        title=title,
        style={"fontSize": "12px"},
    )
