"""Phase 5 — Route planning callbacks.

Wires the Plan Route modal: takes departure/destination ICAO + cruise
alt + TAS + optional wind, computes the route via core.route, renders
the great-circle leg as a polyline on the map, auto-zooms the map to
fit the route, and renders a persistent summary card overlay.
"""
from __future__ import annotations

from dash import Input, Output, State, html, ctx, no_update
from dash.exceptions import PreventUpdate
import dash_leaflet as dl

from core.data_loader import airport_data
from core.route import compute_route_segment, magvar_west_positive, haversine_nm
from core.corridor import compute_route_corridor, sample_route_points
from core.terrain import elevation_m as _terrain_elevation_m, prefetch_corridor


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


def _route_bounds(o_lat, o_lon, d_lat, d_lon, pad: float = 0.1):
    """Bounding box [[sw_lat, sw_lon], [ne_lat, ne_lon]] enclosing
    both endpoints with a small padding so the polyline doesn't hug
    the viewport edge."""
    lats = sorted([o_lat, d_lat])
    lons = sorted([o_lon, d_lon])
    # Pad as a fraction of the leg extent, with a small minimum
    lat_pad = max(0.05, (lats[1] - lats[0]) * pad)
    lon_pad = max(0.05, (lons[1] - lons[0]) * pad)
    return [[lats[0] - lat_pad, lons[0] - lon_pad],
            [lats[1] + lat_pad, lons[1] + lon_pad]]


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

    # === Compute route + render on map + render summary overlay ===
    @app.callback(
        Output("route-summary-overlay", "children"),
        Output("route-layer", "children"),
        Output("map", "bounds"),
        Output("route-result-store", "data"),
        Input("compute-route-btn", "n_clicks"),
        Input("route-clear-btn", "n_clicks"),
        State("route-origin-input", "value"),
        State("route-dest-input", "value"),
        State("route-cruise-alt", "value"),
        State("route-tas", "value"),
        State("route-glide-ratio", "value"),
        State("route-glide-ias", "value"),
        State("route-show-corridor", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        prevent_initial_call=True,
    )
    def compute_and_render(compute_clicks, clear_clicks,
                          origin_id, dest_id, cruise_alt, tas,
                          glide_ratio, glide_ias, corridor_show,
                          wind_dir, wind_speed):
        trigger = ctx.triggered_id
        if trigger == "route-clear-btn":
            return None, [], no_update, None

        if not compute_clicks:
            raise PreventUpdate

        if not origin_id or not dest_id:
            return (html.Div("Set both origin and destination ICAOs.",
                             className="route-summary-error"),
                    no_update, no_update, no_update)
        try:
            cruise_alt = float(cruise_alt) if cruise_alt else 5500.0
            tas = float(tas) if tas else 110.0
            glide_ratio = float(glide_ratio) if glide_ratio else 9.0
            glide_ias = float(glide_ias) if glide_ias else 75.0
        except (TypeError, ValueError):
            return (html.Div("Numeric fields must be numbers.",
                             className="route-summary-error"),
                    no_update, no_update, no_update)

        origin = _airport_by_id(origin_id)
        dest = _airport_by_id(dest_id)
        if origin is None:
            return (html.Div(f"Origin '{origin_id}' not found.",
                             className="route-summary-error"),
                    no_update, no_update, no_update)
        if dest is None:
            return (html.Div(f"Destination '{dest_id}' not found.",
                             className="route-summary-error"),
                    no_update, no_update, no_update)

        magvar = magvar_west_positive(origin["lat"], origin["lon"], cruise_alt)

        wd = float(wind_dir) if wind_dir not in (None, "", "null") else 0.0
        ws = float(wind_speed) if wind_speed not in (None, "", "null") else 0.0

        result = compute_route_segment(
            origin_lat=origin["lat"], origin_lon=origin["lon"],
            dest_lat=dest["lat"], dest_lon=dest["lon"],
            tas_kt=tas, wind_dir_deg=wd, wind_speed_kt=ws,
            magvar_deg=magvar,
        )

        layer = []

        # Glide corridor (under the route line so the line sits on top)
        corridor_meta = None
        if corridor_show and "show" in corridor_show:
            field_elev = max(
                origin.get("elevation_ft") or 0.0,
                dest.get("elevation_ft") or 0.0,
            )

            # Auto-scale spacing so a transcontinental route doesn't
            # generate 1000+ sample envelopes (browser + worker can't
            # handle). Target ~80-120 samples per route.
            route_nm = haversine_nm(origin["lat"], origin["lon"],
                                    dest["lat"], dest["lon"])
            if route_nm <= 200:
                spacing = 2.0
            elif route_nm <= 600:
                spacing = max(2.0, route_nm / 100.0)
            else:
                spacing = max(5.0, route_nm / 150.0)

            # Approximate max envelope reach (still-air NM at cruise AGL).
            max_reach_nm = max(2.0,
                               (cruise_alt - field_elev) * glide_ratio / 6076.115)

            # Concurrent S3 fetch of only the DEM tiles the corridor
            # actually needs — a narrow strip along the route, not the
            # whole bbox. ~10x fewer tiles than bbox for a long route.
            corridor_samples = sample_route_points(
                origin["lat"], origin["lon"],
                dest["lat"], dest["lon"],
                spacing_nm=max(2.0, max_reach_nm),  # coarse pre-fetch grid
            )
            prefetch_corridor(corridor_samples, reach_nm=max_reach_nm)

            rings, corridor_meta = compute_route_corridor(
                origin_lat=origin["lat"], origin_lon=origin["lon"],
                dest_lat=dest["lat"], dest_lon=dest["lon"],
                cruise_alt_msl_ft=cruise_alt,
                field_elev_ft=field_elev,
                glide_ratio=glide_ratio,
                glide_ias_kt=glide_ias,
                wind_dir_deg=wd, wind_speed_kt=ws,
                spacing_nm=spacing,
                elevation_fn=_terrain_elevation_m,
                n_envelope_points=24,
                terrain_step_nm=0.5,
            )
            for ring in rings:
                layer.append(
                    dl.Polygon(
                        positions=ring,
                        color="#22c55e", weight=1,
                        fillColor="#22c55e", fillOpacity=0.18,
                    )
                )

        # Route line + endpoints on top
        layer.extend([
            dl.Polyline(
                positions=[[origin["lat"], origin["lon"]],
                           [dest["lat"], dest["lon"]]],
                color="#0d59f2", weight=3, opacity=0.85,
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
        ])

        bounds = _route_bounds(origin["lat"], origin["lon"],
                               dest["lat"], dest["lon"])

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
            "corridor": corridor_meta,
        }

        card = _summary_card(result, origin.get("id"), dest.get("id"))
        # Append corridor-specific badge to the summary if computed
        if corridor_meta:
            rows = []
            if corridor_meta.get("terrain_used"):
                rows.append(
                    html.Div([html.Span("AGL min/avg/max",
                                        className="route-summary-label"),
                              html.Span(
                                  f"{corridor_meta['min_agl_ft']:.0f} / "
                                  f"{corridor_meta['agl_ft']:.0f} / "
                                  f"{corridor_meta['max_agl_ft']:.0f} ft",
                                  className="route-summary-value")],
                             className="route-summary-row"))
            else:
                rows.append(
                    html.Div([html.Span("AGL", className="route-summary-label"),
                              html.Span(f"{corridor_meta['agl_ft']:.0f} ft",
                                        className="route-summary-value")],
                             className="route-summary-row"))
            rows.extend([
                html.Div([html.Span("Narrowest",
                                    className="route-summary-label"),
                          html.Span(f"{corridor_meta['narrowest_nm']:.1f} NM",
                                    className="route-summary-value")],
                         className="route-summary-row"),
                html.Div([html.Span("Widest",
                                    className="route-summary-label"),
                          html.Span(f"{corridor_meta['widest_nm']:.1f} NM",
                                    className="route-summary-value")],
                         className="route-summary-row"),
                html.Div([html.Span("Area",
                                    className="route-summary-label"),
                          html.Span(f"{corridor_meta['area_nm2']:.0f} NM²",
                                    className="route-summary-value")],
                         className="route-summary-row"),
            ])
            if corridor_meta.get("terrain_used"):
                tlim = corridor_meta.get("terrain_limited_samples", 0)
                below = corridor_meta.get("below_terrain_samples", 0)
                n_samp = corridor_meta.get("n_samples", 1)
                rows.append(
                    html.Div([html.Span("Ridge-clipped",
                                        className="route-summary-label"),
                              html.Span(f"{tlim} / {n_samp} samples",
                                        className="route-summary-value")],
                             className="route-summary-row"))
                if below > 0:
                    rows.append(
                        html.Div([html.Span("Below ridge",
                                            className="route-summary-label"),
                                  html.Span(f"{below} samples",
                                            className="route-summary-value route-summary-warn")],
                                 className="route-summary-row"))
            extras = html.Div(className="route-corridor-badge", children=rows)
        else:
            extras = None

        overlay = html.Div(
            [
                html.Div(className="route-overlay-header", children=[
                    html.Span(f"{origin.get('id')} → {dest.get('id')}",
                              className="route-overlay-title"),
                ]),
                card,
                extras,
            ],
            className="route-overlay-panel",
        )

        return overlay, layer, bounds, store
