"""Phase 5 — Route planning callbacks.

Wires the Plan Route modal: takes departure/destination ICAO + cruise
alt + TAS + optional wind, computes the route via core.route, renders
the great-circle leg as a polyline on the map, and populates the
summary card with distance / TC / MC / GS / ETE / fuel.
"""
from __future__ import annotations

from dash import Input, Output, State, html, ctx, no_update
from dash.exceptions import PreventUpdate
import dash_leaflet as dl

from core.data_loader import airport_data
from core.route import compute_route_segment, magvar_west_positive


def _airport_by_id(airport_id: str):
    """Linear lookup against airport_data list. 49k items, ~milliseconds."""
    if not airport_id:
        return None
    target = airport_id.strip().upper()
    for ap in airport_data:
        if (ap.get("id") or "").upper() == target:
            return ap
        if (ap.get("icao") or "").upper() == target:
            return ap
    return None


def _summary_card(result, origin_id, dest_id) -> html.Div:
    """Renders the route summary as a stack of label-value rows."""
    rows = [
        ("Origin",      origin_id),
        ("Destination", dest_id),
        ("Distance",    f"{result.distance_nm:.0f} NM"),
        ("True Course", f"{result.true_course_deg:03.0f}°"),
        ("Mag Course",  f"{result.magnetic_course_deg:03.0f}°"),
        ("True Hdg",    f"{result.true_heading_deg:03.0f}°"),
        ("Mag Hdg",     f"{result.magnetic_heading_deg:03.0f}°"),
        ("Ground Spd",  f"{result.ground_speed_kt:.0f} kt"),
        ("ETE",         f"{result.ete_min:.0f} min"),
    ]
    if result.fuel_burn_gal is not None:
        rows.append(("Fuel",       f"{result.fuel_burn_gal:.1f} gal"))
    return html.Div(
        [
            html.Div([html.Span(label, className="route-summary-label"),
                      html.Span(value, className="route-summary-value")],
                     className="route-summary-row")
            for label, value in rows
        ],
        className="route-summary",
    )


def register(app):
    """Install route-planning callbacks."""

    # === Modal toggle ===
    @app.callback(
        Output("route-modal", "is_open"),
        Input("open-route-btn", "n_clicks"),
        Input("close-route-btn", "n_clicks"),
        Input("compute-route-btn", "n_clicks"),
        State("route-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_route_modal(open_clicks, close_clicks, compute_clicks, is_open):
        trigger = ctx.triggered_id
        if trigger == "open-route-btn":
            return True
        if trigger == "close-route-btn":
            return False
        # compute-route-btn keeps the modal open so the user sees the result
        return is_open

    # === Compute route + render on map + populate summary card ===
    @app.callback(
        Output("route-summary-container", "children"),
        Output("route-layer", "children"),
        Output("route-result-store", "data"),
        Input("compute-route-btn", "n_clicks"),
        State("route-origin-input", "value"),
        State("route-dest-input", "value"),
        State("route-cruise-alt", "value"),
        State("route-tas", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def compute_and_render(n_clicks, origin_id, dest_id, cruise_alt, tas,
                          wind_dir, wind_speed, aircraft_name):
        if not n_clicks:
            raise PreventUpdate

        # Validate inputs
        if not origin_id or not dest_id:
            return (
                html.Div("Set both origin and destination ICAOs.",
                         className="route-summary-error"),
                no_update,
                None,
            )
        try:
            cruise_alt = float(cruise_alt) if cruise_alt else 5500.0
            tas = float(tas) if tas else 110.0
        except (TypeError, ValueError):
            return (
                html.Div("Cruise altitude and TAS must be numbers.",
                         className="route-summary-error"),
                no_update,
                None,
            )

        # Look up airports
        origin = _airport_by_id(origin_id)
        dest = _airport_by_id(dest_id)
        if origin is None:
            return (html.Div(f"Origin '{origin_id}' not found.",
                             className="route-summary-error"),
                    no_update, None)
        if dest is None:
            return (html.Div(f"Destination '{dest_id}' not found.",
                             className="route-summary-error"),
                    no_update, None)

        # Pull magvar from origin's lat/lon (close enough for one leg)
        magvar = magvar_west_positive(origin["lat"], origin["lon"], cruise_alt)

        wd = float(wind_dir) if wind_dir not in (None, "", "null") else 0.0
        ws = float(wind_speed) if wind_speed not in (None, "", "null") else 0.0

        result = compute_route_segment(
            origin_lat=origin["lat"], origin_lon=origin["lon"],
            dest_lat=dest["lat"], dest_lon=dest["lon"],
            tas_kt=tas,
            wind_dir_deg=wd, wind_speed_kt=ws,
            magvar_deg=magvar,
        )

        # Render: polyline + endpoint markers
        layer = [
            dl.Polyline(
                positions=[[origin["lat"], origin["lon"]],
                           [dest["lat"], dest["lon"]]],
                color="#0d59f2",
                weight=3,
                opacity=0.85,
            ),
            dl.CircleMarker(
                center=[origin["lat"], origin["lon"]],
                radius=6, color="#22c55e", fillOpacity=1.0,
                children=[dl.Tooltip(f"{origin.get('id')} (origin)")],
            ),
            dl.CircleMarker(
                center=[dest["lat"], dest["lon"]],
                radius=6, color="#ef4444", fillOpacity=1.0,
                children=[dl.Tooltip(f"{dest.get('id')} (dest)")],
            ),
        ]

        store = {
            "origin_id": origin.get("id"),
            "dest_id": dest.get("id"),
            "distance_nm": round(result.distance_nm, 1),
            "true_course_deg": round(result.true_course_deg, 1),
            "magnetic_course_deg": round(result.magnetic_course_deg, 1),
            "true_heading_deg": round(result.true_heading_deg, 1),
            "magnetic_heading_deg": round(result.magnetic_heading_deg, 1),
            "ground_speed_kt": round(result.ground_speed_kt, 1),
            "ete_min": round(result.ete_min, 1),
            "magvar_deg": round(magvar, 2),
        }

        return _summary_card(result, origin.get("id"), dest.get("id")), layer, store
