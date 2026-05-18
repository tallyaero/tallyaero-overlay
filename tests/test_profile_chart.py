"""Tests for the altitude_profile_chart shared helper.

altitude_profile_chart(times_s, altitudes_ft, *, chart_id, x_title,
y_title, markers, height_px) renders an altitude-vs-time mini-chart for
per-maneuver info panels (Chandelle, Lazy 8, Steep Spiral, and any
future climbing/descending maneuver).

Mirrors Route's existing profile-chart styling (Phase A2 of the
maneuver production-ready plan) so the maneuver suite reads as one
visual family. Route's own chart is intentionally NOT refactored to use
this helper because it overlays terrain + conflict markers that the
maneuver helper does not.
"""
from __future__ import annotations

from dash import dcc
import plotly.graph_objects as go

from layouts.maneuvers._charts import altitude_profile_chart


def test_returns_dcc_graph_with_correct_id():
    g = altitude_profile_chart(
        [0.0, 5.0, 10.0], [1000.0, 1500.0, 2000.0],
        chart_id="chandelle-profile",
    )
    assert isinstance(g, dcc.Graph)
    assert g.id == "chandelle-profile"


def test_display_modebar_disabled():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x",
    )
    assert g.config["displayModeBar"] is False


def test_first_trace_is_lines():
    g = altitude_profile_chart(
        [0.0, 5.0, 10.0], [1000.0, 1500.0, 2000.0], chart_id="x",
    )
    assert isinstance(g.figure.data[0], go.Scatter)
    assert g.figure.data[0].mode == "lines"


def test_layout_matches_route_chart_styling():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x",
    )
    layout = g.figure.layout
    assert layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert layout.plot_bgcolor == "rgba(248, 250, 252, 0.7)"
    assert layout.font.size == 9
    assert layout.margin.l == 40
    assert layout.margin.r == 10
    assert layout.margin.t == 10
    assert layout.margin.b == 30


def test_default_titles():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x",
    )
    assert g.figure.layout.xaxis.title.text == "Time (s)"
    assert g.figure.layout.yaxis.title.text == "Altitude (ft AGL)"


def test_custom_titles():
    g = altitude_profile_chart(
        [0.0, 1.0], [0.0, 100.0],
        chart_id="x", x_title="Distance (NM)", y_title="MSL (ft)",
    )
    assert g.figure.layout.xaxis.title.text == "Distance (NM)"
    assert g.figure.layout.yaxis.title.text == "MSL (ft)"


def test_default_height_140px():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x",
    )
    assert g.figure.layout.height == 140
    assert g.style["height"] == "140px"


def test_custom_height():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x", height_px=200,
    )
    assert g.figure.layout.height == 200
    assert g.style["height"] == "200px"


def test_markers_add_second_trace():
    g = altitude_profile_chart(
        [0.0, 5.0, 10.0], [1000.0, 1500.0, 2000.0],
        chart_id="x",
        markers=[(2.5, "TOC"), (7.5, "TOD")],
    )
    assert len(g.figure.data) == 2
    marker_trace = g.figure.data[1]
    assert isinstance(marker_trace, go.Scatter)
    assert "markers" in marker_trace.mode
    assert list(marker_trace.x) == [2.5, 7.5]
    assert list(marker_trace.text) == ["TOC", "TOD"]


def test_markers_y_interpolated_from_series():
    g = altitude_profile_chart(
        [0.0, 10.0], [1000.0, 2000.0],
        chart_id="x", markers=[(5.0, "halfway")],
    )
    marker_trace = g.figure.data[1]
    assert list(marker_trace.y) == [1500.0]


def test_no_markers_means_single_trace():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x",
    )
    assert len(g.figure.data) == 1


def test_empty_inputs_no_exception():
    g = altitude_profile_chart([], [], chart_id="empty")
    assert isinstance(g, dcc.Graph)
    assert len(g.figure.data) == 0


def test_showlegend_false():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x",
    )
    assert g.figure.layout.showlegend is False


def test_classname_for_css_targeting():
    g = altitude_profile_chart(
        [0.0, 5.0], [1000.0, 1100.0], chart_id="x",
    )
    assert g.className == "maneuver-profile-chart"
