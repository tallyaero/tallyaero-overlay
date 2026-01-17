"""
Map marker generation utilities.
"""
import dash_leaflet as dl
from dash import html


def create_circle_marker(lat, lon, radius=7, color="green", tooltip_content=None):
    """
    Create a circle marker for the map.

    Args:
        lat: Latitude
        lon: Longitude
        radius: Marker radius (default 7)
        color: Marker color (default "green")
        tooltip_content: Optional tooltip text

    Returns:
        dl.CircleMarker component
    """
    children = None
    if tooltip_content:
        children = dl.Tooltip(tooltip_content)

    return dl.CircleMarker(
        center=[lat, lon],
        radius=radius,
        color=color,
        fill=True,
        fillOpacity=1.0,
        children=children
    )


def create_hover_markers(path, hover_data, step=5, color="red"):
    """
    Create hover markers along a path.

    Args:
        path: List of [lat, lon] coordinate pairs
        hover_data: List of dicts containing flight data
        step: Step between markers (default 5)
        color: Marker color (default "red")

    Returns:
        List of dl.CircleMarker components
    """
    markers = []

    for i, pt in enumerate(hover_data):
        if i % step != 0 or i >= len(path):
            continue

        tooltip_children = []

        alt = pt.get("alt")
        if alt is not None:
            tooltip_children.append(html.Div(f"{float(alt):.0f} ft AGL"))

        tas = pt.get("tas")
        if tas is not None:
            tooltip_children.append(html.Div(f"TAS: {float(tas):.0f} kt"))

        gs = pt.get("gs")
        if gs is not None:
            tooltip_children.append(html.Div(f"GS: {float(gs):.0f} kt"))

        t_sec = pt.get("time")
        if t_sec is not None:
            tooltip_children.append(html.Div(f"Time: {float(t_sec):.0f} sec"))

        aob = pt.get("aob")
        if aob is not None:
            tooltip_children.append(html.Div(f"AOB: {float(aob):.0f}°"))

        vs = pt.get("vs")
        if vs is not None:
            tooltip_children.append(html.Div(f"VS: {float(vs):.0f} fpm"))

        markers.append(
            dl.CircleMarker(
                center=path[i],
                radius=3,
                color=color,
                fill=True,
                fillOpacity=0.8,
                children=dl.Tooltip(tooltip_children),
            )
        )

    return markers
