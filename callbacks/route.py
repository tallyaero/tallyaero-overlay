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

from core.data_loader import aircraft_data, airport_data
from core.route import compute_route_segment, magvar_west_positive, haversine_nm
from core.corridor import compute_route_corridor, sample_route_points
from core.terrain import elevation_m as _terrain_elevation_m, prefetch_corridor
from core.airport_search import search_airports, airport_label, resolve_waypoint
from core.diverts import (
    divert_coverage_along_route_glide, gap_segments, longest_gap_nm,
)
from core.flight_profile import (
    compute_flight_profile, altitude_at_distance,
    climb_rate_fpm as _climb_rate_fpm,
    class_baseline_climb_rate,
)
from core.winds_aloft import fetch_winds_aloft


import math


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


def _bounds_to_viewport(bounds, map_px=(1100, 700)):
    """Convert SW/NE bounds into a dash-leaflet `viewport` dict
    (center + zoom). In dash-leaflet 1.0.15 the `bounds` prop only
    fits on initial mount; programmatic re-fitting after mount needs
    to set `viewport` instead.

    Zoom is computed from the bounds diagonal using the Web Mercator
    pixel formula: each zoom level halves the pixel scale, and the
    map is 256 px wide at z=0. We pick the smaller of lat/lon zoom
    so the whole bounds fits, and cap at 13 to avoid zooming past
    typical viewport scales.
    """
    (sw_lat, sw_lon), (ne_lat, ne_lon) = bounds
    center_lat = (sw_lat + ne_lat) / 2.0
    center_lon = (sw_lon + ne_lon) / 2.0
    w_px, h_px = map_px

    # World pixel size at zoom z: 256 * 2^z. We need the zoom where
    # the bounds in pixels fits within (w_px, h_px).
    lon_span = max(0.001, ne_lon - sw_lon)
    lat_span = max(0.001, ne_lat - sw_lat)

    # Mercator lat-span pixel correction at the bound's center
    lat_rad = math.radians(center_lat)
    merc = math.log(math.tan(math.pi / 4 + lat_rad / 2))
    lat_rad_n = math.radians(ne_lat)
    lat_rad_s = math.radians(sw_lat)
    merc_span = (math.log(math.tan(math.pi / 4 + lat_rad_n / 2))
                 - math.log(math.tan(math.pi / 4 + lat_rad_s / 2)))
    # Each unit of Mercator y == (256 / 2π) px at z=0
    lat_px_z0 = abs(merc_span) * 256 / (2 * math.pi)
    lon_px_z0 = lon_span / 360.0 * 256

    z_lat = math.log2(h_px / max(0.001, lat_px_z0))
    z_lon = math.log2(w_px / max(0.001, lon_px_z0))
    zoom = max(2, min(13, min(z_lat, z_lon)))
    return {
        "center": [center_lat, center_lon],
        "zoom": zoom,
        "transition": "flyTo",
    }


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

    # === Live climb-rate chip — derives fpm from typed climb IAS ===
    @app.callback(
        Output("route-climb-rate-chip", "children"),
        Input("route-climb-ias", "value"),
        State("aircraft-select", "value"),
        prevent_initial_call=False,
    )
    def update_climb_rate_chip(climb_ias, aircraft_name):
        ac = aircraft_data.get(aircraft_name) if aircraft_name else None
        vy = (ac.get("Vy") if ac else None) or 76.0
        vno = (ac.get("Vno") if ac else None) or 129.0
        baseline = class_baseline_climb_rate(ac) if ac else 700.0
        try:
            ias = float(climb_ias) if climb_ias else vy
        except (TypeError, ValueError):
            ias = vy
        rate = _climb_rate_fpm(ias, vy, vno, baseline)
        return f"≈ {rate:.0f} fpm"

    # === Compute route + render on map + render summary overlay ===
    @app.callback(
        Output("route-summary-overlay", "children"),
        Output("route-layer", "children"),
        Output("map", "viewport"),
        Output("route-result-store", "data"),
        Input("compute-route-btn", "n_clicks"),
        Input("route-clear-btn", "n_clicks"),
        State("route-waypoints", "value"),
        State("route-cruise-alt", "value"),
        State("route-tas", "value"),
        State("route-glide-ratio", "value"),
        State("route-glide-ias", "value"),
        State("route-climb-ias", "value"),
        State("route-show-corridor", "value"),
        State("route-use-live-winds", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def compute_and_render(compute_clicks, clear_clicks,
                          waypoint_ids, cruise_alt, tas,
                          glide_ratio, glide_ias, climb_ias, corridor_show,
                          use_live_winds,
                          wind_dir, wind_speed, aircraft_name):
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
            climb_ias = float(climb_ias) if climb_ias else 76.0
        except (TypeError, ValueError):
            return (html.Div("Numeric fields must be numbers.",
                             className="route-summary-error"),
                    no_update, no_update, no_update)

        # Aircraft-derived inputs for the climb model: Vy + Vno + class
        # baseline climb rate. Falls back to typical-single defaults if
        # the user hasn't selected an aircraft.
        ac = aircraft_data.get(aircraft_name) if aircraft_name else None
        vy_kt = (ac.get("Vy") if ac else None) or 76.0
        vno_kt = (ac.get("Vno") if ac else None) or 129.0
        baseline_climb = class_baseline_climb_rate(ac) if ac else 700.0
        derived_climb_rate = _climb_rate_fpm(
            climb_ias, vy_kt, vno_kt, baseline_climb)

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

        # ─── Flight profile (climb / cruise / descent) ─────────────────
        # Per-sample altitude is no longer the flat cruise slab. Real
        # altitude varies along the route: rising during climb, flat
        # across cruise, descending into the destination. This drives
        # how much glide reach the corridor + diverts see at each
        # sample.
        leg_distances_nm = [
            haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
            for a, b in zip(waypoints[:-1], waypoints[1:])
        ]
        total_route_nm = sum(leg_distances_nm)
        field_dep_ft = waypoints[0].get("elevation_ft") or 0.0
        field_dest_ft = waypoints[-1].get("elevation_ft") or 0.0
        profile = compute_flight_profile(
            field_dep_ft=field_dep_ft,
            field_dest_ft=field_dest_ft,
            cruise_alt_msl_ft=cruise_alt,
            total_route_nm=total_route_nm,
            climb_ias_kt=climb_ias,
            climb_rate_fpm=derived_climb_rate,
            cruise_tas_kt=tas,
        )

        # Per-leg samples + per-sample MSL altitude from the profile.
        # We sample each leg with its own spacing, then compute the
        # GLOBAL distance-from-departure for each sample and look up
        # altitude(d). Both corridor and divert paths consume these.
        leg_offsets_nm = [0.0]
        for d in leg_distances_nm:
            leg_offsets_nm.append(leg_offsets_nm[-1] + d)
        per_leg_samples: list[tuple[list, list[float], float]] = []
        all_samples: list[tuple[float, float]] = []
        all_alts: list[float] = []
        for (a, b), leg_offset, leg_nm in zip(
            zip(waypoints[:-1], waypoints[1:]),
            leg_offsets_nm[:-1], leg_distances_nm,
        ):
            if leg_nm <= 200:
                spacing = 2.0
            elif leg_nm <= 600:
                spacing = max(2.0, leg_nm / 100.0)
            else:
                spacing = max(5.0, leg_nm / 150.0)
            leg_samples = sample_route_points(
                a["lat"], a["lon"], b["lat"], b["lon"], spacing_nm=spacing)
            n = len(leg_samples)
            leg_alts = []
            for i in range(n):
                frac = i / max(1, n - 1)
                d_global = leg_offset + leg_nm * frac
                leg_alts.append(altitude_at_distance(d_global, profile))
            per_leg_samples.append((leg_samples, leg_alts, spacing))
            all_samples.extend(leg_samples)
            all_alts.extend(leg_alts)

        # ─── Live winds aloft (per sample) ─────────────────────────────
        # Default ON. If the toggle is off, or the API errors, we fall
        # back to the manual sidebar wind applied uniformly. The status
        # chip in the overlay reflects which source is in effect.
        wind_source = "manual"        # 'live' | 'manual' | 'live-unavailable'
        all_winds: list[tuple[float, float]] | None = None
        if use_live_winds and "on" in use_live_winds:
            fetched = fetch_winds_aloft(all_samples, all_alts)
            if fetched is not None and len(fetched) == len(all_samples):
                all_winds = fetched
                wind_source = "live"
            else:
                wind_source = "live-unavailable"

        # Per-leg wind lists matched to leg_samples
        per_leg_winds: list[list[tuple[float, float]] | None] = []
        idx = 0
        for leg_samples, _alts, _sp in per_leg_samples:
            if all_winds is not None:
                per_leg_winds.append(all_winds[idx:idx + len(leg_samples)])
            else:
                per_leg_winds.append(None)
            idx += len(leg_samples)

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
            for (a, b), (leg_samples, leg_alts, spacing), leg_winds in zip(
                zip(waypoints[:-1], waypoints[1:]), per_leg_samples,
                per_leg_winds,
            ):
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
                    sample_alts_msl_ft=leg_alts,
                    sample_winds=leg_winds,
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

        # ─── Divert airport reach analysis ─────────────────────────────
        # Per route sample, what airports could the aircraft glide to if
        # the engine quit at that point — accounting for wind on the
        # bearing AND terrain ridges between sample and airport. We
        # pass the per-sample MSL altitude from the flight profile so
        # climb-out / final-descent samples see a smaller divert set
        # than cruise samples.
        divert = divert_coverage_along_route_glide(
            all_samples, airport_data,
            cruise_alt_msl_ft=cruise_alt,
            glide_ratio=glide_ratio,
            glide_ias_kt=glide_ias,
            wind_dir_deg=wd, wind_speed_kt=ws,
            elevation_fn=_terrain_elevation_m,
            terrain_step_nm=0.5,
            sample_alts_msl_ft=all_alts,
            sample_winds=all_winds,
        )
        gaps = gap_segments(all_samples, divert["per_sample"])
        long_gap = longest_gap_nm(gaps)

        # Reachable divert airports — cyan dots so they stand out against
        # the green corridor fill. Cap at 200 so we don't melt the browser
        # on transcontinental routes.
        for entry in divert["unique_diverts"][:200]:
            ap = entry["airport"]
            tip = (f"{ap.get('id')} — {ap.get('name','')} "
                   f"(divert · {entry['min_distance_nm']:.1f} NM nearest)")
            layer.append(dl.CircleMarker(
                center=[ap["lat"], ap["lon"]],
                radius=4, weight=1.5,
                color="#0e7490", fillColor="#22d3ee", fillOpacity=0.95,
                children=[dl.Tooltip(tip)],
            ))
        # Red dashed segments where no airport is in engine-out glide.
        # Tooltip explains the semantic so a pilot doesn't have to guess.
        for g in gaps:
            if g["gap_nm"] < 1.0:
                continue   # skip single-sample blips
            layer.append(dl.Polyline(
                positions=[[g["start_lat"], g["start_lon"]],
                           [g["end_lat"], g["end_lon"]]],
                color="#dc2626", weight=5, opacity=0.85,
                dashArray="8 6",
                children=[dl.Tooltip(
                    f"No airport within engine-out glide range — "
                    f"{g['gap_nm']:.0f} NM stretch"
                )],
            ))

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
        viewport = _bounds_to_viewport(bounds)

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

        # Divert summary block — always shown, even without corridor.
        n_diverts = len(divert["unique_diverts"])
        no_cov = divert["n_samples_with_no_coverage"]
        n_samp = len(all_samples)
        divert_rows = [
            html.Div([html.Span("Engine-out diverts",
                                className="route-summary-label"),
                      html.Span(f"{n_diverts} airports in glide",
                                className="route-summary-value")],
                     className="route-summary-row"),
        ]
        if no_cov == 0:
            divert_rows.append(html.Div([
                html.Span("Coverage", className="route-summary-label"),
                html.Span("Full route within an engine-out glide",
                          className="route-summary-value"),
            ], className="route-summary-row"))
        else:
            # Long gap warning if biggest gap > 10 NM
            gap_cls = "route-summary-value"
            if long_gap > 10:
                gap_cls += " route-summary-warn"
            # Compute how much of the route the gaps span, in NM
            pct = (no_cov / n_samp * 100.0) if n_samp else 0.0
            divert_rows.append(html.Div([
                html.Span("Longest no-divert stretch",
                          className="route-summary-label"),
                html.Span(
                    f"{long_gap:.0f} NM with no airfield in glide "
                    f"({pct:.0f}% of route)",
                    className=gap_cls,
                ),
            ], className="route-summary-row"))
        divert_block = html.Div(className="route-divert-badge", children=divert_rows)

        # Wind status pill — tells the pilot which wind source the
        # corridor + diverts were computed against.
        if wind_source == "live":
            wind_pill_text = "Wind: live forecast (Open-Meteo)"
            wind_pill_cls = "route-wind-pill route-wind-live"
        elif wind_source == "live-unavailable":
            wind_pill_text = f"Wind: live unavailable — manual {wd:.0f}° @ {ws:.0f} kt"
            wind_pill_cls = "route-wind-pill route-wind-warn"
        else:
            wind_pill_text = f"Wind: manual {wd:.0f}° @ {ws:.0f} kt"
            wind_pill_cls = "route-wind-pill route-wind-manual"
        wind_pill = html.Div(wind_pill_text, className=wind_pill_cls)

        overlay = html.Div(
            [
                html.Div(className="route-overlay-header", children=[
                    html.Span(" → ".join(w["id"] for w in waypoints),
                              className="route-overlay-title"),
                ]),
                card,
                extras,
                divert_block,
                wind_pill,
            ],
            className="route-overlay-panel",
        )

        store = {
            "waypoints": [w.get("id") for w in waypoints],
            "legs": legs,
            "corridor": corridor_meta_agg,
            "diverts": {
                "n_unique": n_diverts,
                "longest_gap_nm": long_gap,
                "n_samples_with_no_coverage": no_cov,
                "n_samples": n_samp,
            },
            "wind_source": wind_source,
        }
        return overlay, layer, viewport, store
