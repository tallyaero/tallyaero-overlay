"""Route planning callbacks — multi-waypoint search + ridge-clipped corridor.

The Route maneuver in the shelf has one searchable multi-select
dropdown ("Route") where waypoints are typed in order. Each typed
token (ICAO, IATA, FAA LID, city, or name) auto-resolves through
core.airport_search. Hitting Compute Route:

  - chains compute_route_segment over each consecutive pair to get
    leg distance / heading / GS / ETE / fuel
  - prefetches the DEM tile strip covering ALL legs at once
  - calls compute_route_corridor per leg and unions the resulting
    polygon rings
  - draws one multi-segment polyline + corridor polygons + waypoint
    markers, and emits an aggregate summary card with a per-leg list.

Future waypoint types (VORs, fixes, lat/lon) plug into
core.airport_search.resolve_waypoint without changing this file.
"""
from __future__ import annotations

from dash import Input, Output, State, html, ctx, no_update
from dash.exceptions import PreventUpdate
import dash_leaflet as dl

from core.data_loader import airport_data
from core.route import compute_route_segment, magvar_west_positive, haversine_nm
from core.corridor import compute_route_corridor, sample_route_points
from core.terrain import elevation_m as _terrain_elevation_m, prefetch_corridor
from core.airport_search import search_airports, airport_label, resolve_waypoint


def _multi_route_bounds(waypoints: list[dict], pad: float = 0.1):
    """[[sw_lat, sw_lon], [ne_lat, ne_lon]] enclosing every waypoint."""
    lats = [w["lat"] for w in waypoints]
    lons = [w["lon"] for w in waypoints]
    lo_lat, hi_lat = min(lats), max(lats)
    lo_lon, hi_lon = min(lons), max(lons)
    lat_pad = max(0.05, (hi_lat - lo_lat) * pad)
    lon_pad = max(0.05, (hi_lon - lo_lon) * pad)
    return [[lo_lat - lat_pad, lo_lon - lon_pad],
            [hi_lat + lat_pad, hi_lon + lon_pad]]


def _summary_card(legs: list[dict], waypoints: list[dict]) -> html.Div:
    """Aggregate summary across all legs + per-leg breakdown."""
    total_dist = sum(l["distance_nm"] for l in legs)
    total_ete = sum(l["ete_min"] for l in legs)
    total_fuel = sum((l.get("fuel_burn_gal") or 0.0) for l in legs)
    rows = [
        ("Origin",       waypoints[0]["id"]),
        ("Destination",  waypoints[-1]["id"]),
        ("Legs",         f"{len(legs)} ({' → '.join(w['id'] for w in waypoints)})"),
        ("Total dist",   f"{total_dist:.0f} NM"),
        ("Total ETE",    f"{total_ete:.0f} min"),
    ]
    if total_fuel > 0:
        rows.append(("Total fuel", f"{total_fuel:.1f} gal"))
    head = html.Div(
        [
            html.Div([html.Span(label, className="route-summary-label"),
                      html.Span(value, className="route-summary-value")],
                     className="route-summary-row")
            for label, value in rows
        ],
        className="route-summary",
    )
    if len(legs) > 1:
        leg_rows = [
            html.Div([
                html.Span(f"{l['origin_id']}→{l['dest_id']}",
                          className="route-leg-label"),
                html.Span(f"{l['distance_nm']:.0f} NM · {l['magnetic_course_deg']:03.0f}°M · "
                          f"{l['ete_min']:.0f} min",
                          className="route-leg-value"),
            ], className="route-leg-row")
            for l in legs
        ]
        head = html.Div([head, html.Div(leg_rows, className="route-leg-list")])
    return head


def _empty_clear():
    """Standard return when Clear is pressed."""
    return None, [], no_update, None


def register(app):
    """Install route-planning callbacks."""

    # === Search-as-you-type: filter airport_data into dropdown options
    @app.callback(
        Output("route-waypoints", "options"),
        Input("route-waypoints", "search_value"),
        State("route-waypoints", "value"),
        prevent_initial_call=True,
    )
    def update_waypoint_options(query, current_value):
        # Two-tier labeling:
        #   - SELECTED items use the short ID as label, so the pill in
        #     the dropdown shows just "KDYB" (clean, identifier-only).
        #   - SEARCH HITS use the rich label "KDYB · Summerville Airport
        #     — Summerville, SC" so the user can disambiguate while
        #     typing.
        # Dash picks the pill text from whichever option matches the
        # selected value, so re-labeling already-selected entries to
        # the short form auto-shortens the pills.
        kept: list[dict] = []
        for v in current_value or []:
            ap = resolve_waypoint(airport_data, v)
            if ap:
                kept.append({
                    "label": ap.get("id") or v,
                    "value": ap.get("id") or v,
                    "title": airport_label(ap),
                })
        if not query or len(query.strip()) < 2:
            return kept
        hits = search_airports(airport_data, query, limit=20)
        existing_ids = {o["value"] for o in kept}
        for ap in hits:
            wid = ap.get("id")
            if wid and wid not in existing_ids:
                kept.append({
                    "label": airport_label(ap),
                    "value": wid,
                    "title": airport_label(ap),
                })
                existing_ids.add(wid)
        return kept

    # === Compute route + render on map + render summary overlay ===
    @app.callback(
        Output("route-summary-overlay", "children"),
        Output("route-layer", "children"),
        Output("map", "bounds"),
        Output("route-result-store", "data"),
        Input("compute-route-btn", "n_clicks"),
        Input("route-clear-btn", "n_clicks"),
        State("route-waypoints", "value"),
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
                          waypoint_ids, cruise_alt, tas,
                          glide_ratio, glide_ias, corridor_show,
                          wind_dir, wind_speed):
        trigger = ctx.triggered_id
        if trigger == "route-clear-btn":
            return _empty_clear()

        if not compute_clicks:
            raise PreventUpdate

        if not waypoint_ids or len(waypoint_ids) < 2:
            return (html.Div("Add at least two waypoints (origin → destination).",
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

        # Resolve every waypoint to a concrete airport dict.
        waypoints: list[dict] = []
        for wid in waypoint_ids:
            ap = resolve_waypoint(airport_data, wid)
            if ap is None:
                return (html.Div(f"Waypoint '{wid}' not found.",
                                 className="route-summary-error"),
                        no_update, no_update, no_update)
            waypoints.append(ap)

        wd = float(wind_dir) if wind_dir not in (None, "", "null") else 0.0
        ws = float(wind_speed) if wind_speed not in (None, "", "null") else 0.0

        # ─── Per-leg route math ────────────────────────────────────────
        legs: list[dict] = []
        for a, b in zip(waypoints[:-1], waypoints[1:]):
            magvar = magvar_west_positive(a["lat"], a["lon"], cruise_alt)
            r = compute_route_segment(
                origin_lat=a["lat"], origin_lon=a["lon"],
                dest_lat=b["lat"], dest_lon=b["lon"],
                tas_kt=tas, wind_dir_deg=wd, wind_speed_kt=ws,
                magvar_deg=magvar,
            )
            legs.append({
                "origin_id": a.get("id"),
                "dest_id": b.get("id"),
                "distance_nm": round(r.distance_nm, 1),
                "true_course_deg": round(r.true_course_deg, 1),
                "magnetic_course_deg": round(r.magnetic_course_deg, 1),
                "true_heading_deg": round(r.true_heading_deg, 1),
                "magnetic_heading_deg": round(r.magnetic_heading_deg, 1),
                "ground_speed_kt": round(r.ground_speed_kt, 1),
                "ete_min": round(r.ete_min, 1),
                "fuel_burn_gal": (round(r.fuel_burn_gal, 2)
                                  if r.fuel_burn_gal is not None else None),
                "magvar_deg": round(magvar, 2),
            })

        layer: list = []

        # ─── Multi-leg corridor (under the polyline) ───────────────────
        corridor_meta_agg = None
        if corridor_show and "show" in corridor_show:
            field_elev = max((w.get("elevation_ft") or 0.0) for w in waypoints)
            max_reach_nm = max(2.0,
                               (cruise_alt - field_elev) * glide_ratio / 6076.115)

            # One prefetch covering every leg, deduped.
            all_prefetch_samples: list[tuple[float, float]] = []
            for a, b in zip(waypoints[:-1], waypoints[1:]):
                all_prefetch_samples.extend(sample_route_points(
                    a["lat"], a["lon"], b["lat"], b["lon"],
                    spacing_nm=max(2.0, max_reach_nm),
                ))
            prefetch_corridor(all_prefetch_samples, reach_nm=max_reach_nm)

            agg_rings: list = []
            agg_n_samples = 0
            agg_ridge_clipped = 0
            agg_below = 0
            agl_min: float | None = None
            agl_max: float | None = None
            agl_weighted_sum = 0.0
            agl_weight = 0
            narrowest = widest = 0.0
            total_area = 0.0
            for a, b in zip(waypoints[:-1], waypoints[1:]):
                leg_nm = haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
                if leg_nm <= 200:
                    spacing = 2.0
                elif leg_nm <= 600:
                    spacing = max(2.0, leg_nm / 100.0)
                else:
                    spacing = max(5.0, leg_nm / 150.0)
                rings, m = compute_route_corridor(
                    origin_lat=a["lat"], origin_lon=a["lon"],
                    dest_lat=b["lat"], dest_lon=b["lon"],
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
                agg_rings.extend(rings)
                agg_n_samples += m["n_samples"]
                agg_ridge_clipped += m["terrain_limited_samples"]
                agg_below += m["below_terrain_samples"]
                if m.get("min_agl_ft", 0) > 0:
                    agl_min = (m["min_agl_ft"] if agl_min is None
                               else min(agl_min, m["min_agl_ft"]))
                    agl_max = (m["max_agl_ft"] if agl_max is None
                               else max(agl_max, m["max_agl_ft"]))
                agl_weighted_sum += m["agl_ft"] * m["n_samples"]
                agl_weight += m["n_samples"]
                narrowest = (m["narrowest_nm"] if narrowest == 0
                             else min(narrowest, m["narrowest_nm"]))
                widest = max(widest, m["widest_nm"])
                total_area += m["area_nm2"]

            for ring in agg_rings:
                layer.append(dl.Polygon(
                    positions=ring,
                    color="#22c55e", weight=1,
                    fillColor="#22c55e", fillOpacity=0.18,
                ))
            corridor_meta_agg = {
                "n_samples": agg_n_samples,
                "terrain_limited_samples": agg_ridge_clipped,
                "below_terrain_samples": agg_below,
                "min_agl_ft": agl_min or 0.0,
                "max_agl_ft": agl_max or 0.0,
                "agl_ft": round(agl_weighted_sum / max(1, agl_weight)),
                "narrowest_nm": narrowest,
                "widest_nm": widest,
                "area_nm2": round(total_area, 1),
                "terrain_used": True,
            }

        # ─── Polyline + waypoint markers on top ────────────────────────
        polyline_positions = [[w["lat"], w["lon"]] for w in waypoints]
        layer.append(dl.Polyline(
            positions=polyline_positions,
            color="#0d59f2", weight=3, opacity=0.85,
        ))
        for i, w in enumerate(waypoints):
            if i == 0:
                color = "#22c55e"; tip = f"{w['id']} (origin)"
            elif i == len(waypoints) - 1:
                color = "#ef4444"; tip = f"{w['id']} (dest)"
            else:
                color = "#f59e0b"; tip = f"{w['id']} (waypoint {i})"
            layer.append(dl.CircleMarker(
                center=[w["lat"], w["lon"]], radius=6,
                color=color, fillOpacity=1.0,
                children=[dl.Tooltip(tip)],
            ))

        bounds = _multi_route_bounds(waypoints)

        card = _summary_card(legs, waypoints)
        extras = None
        if corridor_meta_agg:
            rows = [
                html.Div([html.Span("AGL min/avg/max",
                                    className="route-summary-label"),
                          html.Span(
                              f"{corridor_meta_agg['min_agl_ft']:.0f} / "
                              f"{corridor_meta_agg['agl_ft']:.0f} / "
                              f"{corridor_meta_agg['max_agl_ft']:.0f} ft",
                              className="route-summary-value")],
                         className="route-summary-row"),
                html.Div([html.Span("Narrowest",
                                    className="route-summary-label"),
                          html.Span(f"{corridor_meta_agg['narrowest_nm']:.1f} NM",
                                    className="route-summary-value")],
                         className="route-summary-row"),
                html.Div([html.Span("Widest",
                                    className="route-summary-label"),
                          html.Span(f"{corridor_meta_agg['widest_nm']:.1f} NM",
                                    className="route-summary-value")],
                         className="route-summary-row"),
                html.Div([html.Span("Area",
                                    className="route-summary-label"),
                          html.Span(f"{corridor_meta_agg['area_nm2']:.0f} NM²",
                                    className="route-summary-value")],
                         className="route-summary-row"),
                html.Div([html.Span("Ridge-clipped",
                                    className="route-summary-label"),
                          html.Span(
                              f"{corridor_meta_agg['terrain_limited_samples']} / "
                              f"{corridor_meta_agg['n_samples']} samples",
                              className="route-summary-value")],
                         className="route-summary-row"),
            ]
            if corridor_meta_agg["below_terrain_samples"] > 0:
                rows.append(html.Div([
                    html.Span("Below ridge", className="route-summary-label"),
                    html.Span(f"{corridor_meta_agg['below_terrain_samples']} samples",
                              className="route-summary-value route-summary-warn"),
                ], className="route-summary-row"))
            extras = html.Div(className="route-corridor-badge", children=rows)

        overlay = html.Div(
            [
                html.Div(className="route-overlay-header", children=[
                    html.Span(" → ".join(w["id"] for w in waypoints),
                              className="route-overlay-title"),
                ]),
                card,
                extras,
            ],
            className="route-overlay-panel",
        )

        store = {
            "waypoints": [w.get("id") for w in waypoints],
            "legs": legs,
            "corridor": corridor_meta_agg,
        }
        return overlay, layer, bounds, store
