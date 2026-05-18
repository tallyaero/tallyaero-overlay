"""Reusable plotly chart helpers for per-maneuver info panels.

Currently exports `altitude_profile_chart` which is used by the
Chandelle, Lazy 8, Steep Spiral, and Power-Off 180 info panels to
render an altitude-vs-time mini-chart (height ~140px, styled to blend
with the white info panel).

Route's profile chart is intentionally NOT refactored to use this
helper because it overlays terrain + conflict markers that the
maneuver helper does not.
"""
from __future__ import annotations

import plotly.graph_objects as go
from dash import dcc


def _interp(x_target, xs, ys):
    """Linear interpolation of y at x_target given parallel xs/ys lists.

    Used to place marker labels on the altitude line at the marker
    time. Assumes xs is monotonically non-decreasing. Returns the
    bracket endpoint if x_target falls outside the range."""
    if not xs:
        return 0.0
    if x_target <= xs[0]:
        return ys[0]
    if x_target >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if xs[i] >= x_target:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x_target - x0) / (x1 - x0)
    return ys[-1]


def altitude_profile_chart(
    times_s,
    altitudes_ft,
    *,
    chart_id,
    x_title="Time (s)",
    y_title="Altitude (ft AGL)",
    markers=None,
    height_px=140,
):
    """Render an altitude-vs-time mini-chart for a maneuver info panel.

    `times_s` and `altitudes_ft` are parallel lists from the sim's
    hover data. `markers` is an optional list of (time, label) tuples
    used to annotate phase transitions (TOC, TOD, max-bank, abeam,
    etc.); labels render above an amber dot at the linearly-interpolated
    altitude.

    Empty inputs return a `dcc.Graph` with an empty figure rather than
    raising — callers can drop this into a Dash layout unconditionally."""
    fig = go.Figure()
    if times_s and altitudes_ft:
        fig.add_trace(
            go.Scatter(
                x=list(times_s),
                y=list(altitudes_ft),
                mode="lines",
                line=dict(color="#0d59f2", width=2),
                hovertemplate="%{x:.1f} s<br>%{y:.0f} ft<extra></extra>",
            )
        )
    if markers:
        marker_x = [t for t, _ in markers]
        marker_y = [_interp(t, list(times_s), list(altitudes_ft)) for t, _ in markers]
        marker_text = [lbl for _, lbl in markers]
        fig.add_trace(
            go.Scatter(
                x=marker_x,
                y=marker_y,
                mode="markers+text",
                marker=dict(color="#f59e0b", size=8, symbol="circle"),
                text=marker_text,
                textposition="top center",
                hoverinfo="text",
            )
        )
    fig.update_layout(
        height=height_px,
        margin=dict(l=40, r=10, t=10, b=30),
        xaxis_title=x_title,
        yaxis_title=y_title,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248, 250, 252, 0.7)",
        font=dict(size=9),
    )
    return dcc.Graph(
        id=chart_id,
        figure=fig,
        config={
            "displayModeBar": False,
            "staticPlot": False,
            "responsive": True,
        },
        className="maneuver-profile-chart",
        style={"width": "100%", "height": f"{height_px}px"},
    )
