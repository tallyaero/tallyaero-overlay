"""
Polyline rendering for map visualization.
Single canonical version of render_hover_polyline (deduplicated from utility.py).
"""
import dash_leaflet as dl
from dash import html


def render_hover_polyline(path, hover_data, color="blue", weight=3):
    """
    Create a Dash Leaflet polyline with hover tooltips.

    Args:
        path: List of [lat, lon] coordinate pairs
        hover_data: List of dicts containing flight data for tooltips
        color: Line color (default "blue")
        weight: Line weight (default 3)

    Returns:
        dl.Polyline component with tooltips
    """
    return dl.Polyline(
        positions=path,
        color=color,
        weight=weight,
        children=[
            dl.Tooltip(
                html.Div([
                    html.Div(f"{pt.get('alt', 0):.0f} ft AGL"),
                    html.Div(f"{pt.get('tas', 0):.0f} kt"),
                    html.Div(f"{pt.get('time', 0):.1f} sec"),
                    html.Div(f"{pt.get('aob', 0):.1f}° AOB"),
                    html.Div(f"{pt.get('vs', 0):.0f} fpm")
                ])
            ) for pt in hover_data[::5]
        ]
    )
