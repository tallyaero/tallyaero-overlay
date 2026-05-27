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

from dash import Input, Output, State, html, dcc, ctx, no_update, ALL
import dash
import plotly.graph_objects as go
from dash.exceptions import PreventUpdate
from datetime import datetime
import dash_leaflet as dl

from core.data_loader import aircraft_data, airport_data, navaid_data, fix_data
from core.route import compute_route_segment, magvar_west_positive, haversine_nm
from core.corridor import compute_route_corridor, sample_route_points, FT_PER_M
from core.terrain import (
    elevation_m as _terrain_elevation_m,
    prefetch_corridor, prefetch_bbox,
)
from core.airport_search import (
    search_airports, airport_label, resolve_waypoint,
    search_navaids, search_fixes, navaid_label, fix_label,
)
from core.waypoints import (
    resolve_any, nearest_airport_within, nearest_waypoint_within,
    format_gps_ident, format_gps_display, parse_gps_coordinate,
)
from core.diverts import (
    divert_coverage_along_route_glide, gap_segments, longest_gap_nm,
)
from core.airspace import route_crossings, TYPE_STYLES, _format_alt
from core.atmosphere import density_altitude_ft
from core.flight_profile import (
    compute_flight_profile, altitude_at_distance,
    climb_rate_fpm as _climb_rate_fpm,
    class_baseline_climb_rate,
)
from core.winds_aloft import fetch_winds_aloft
from core.wind_display import (
    wind_barb_svg, wind_components, format_wind_components,
    pick_barb_indices, route_average_wind,
)
from core.terrain_conflict import (
    classify_route_statuses, segment_polyline_by_status,
    max_terrain_in_corridor_strip, suggest_min_cruise_alt,
    build_profile_series,
)
from core.multi_engine import (
    is_multi_engine, has_se_performance_data,
    compute_route_se_corridor,
)
from core.landable_mask import build_landable_mask_overlay
from core.land_cover_osm import (
    fetch_landing_options, WATER_STYLE,
)
from core.route_critique import score_route
from core.airport_freq import frequencies_for as _freqs_for


import math


# ===========================================================================
# Engine-Out Drill helpers (Phase A1)
# ===========================================================================

def _cumulative_route_nm(samples: list) -> float:
    """Total great-circle NM of a sample polyline."""
    from core.route import haversine_nm
    if len(samples) < 2:
        return 0.0
    total = 0.0
    for (a_lat, a_lon), (b_lat, b_lon) in zip(samples[:-1], samples[1:]):
        total += haversine_nm(float(a_lat), float(a_lon),
                              float(b_lat), float(b_lon))
    return total


def _interpolate_route_position(samples: list, alts_msl: list,
                                 nm_along: float) -> tuple[float, float, float, int, float]:
    """Return (lat, lon, alt_msl, segment_index, segment_fraction) at
    `nm_along` NM into the sampled polyline. Linear interpolation
    between adjacent samples. The segment index + fraction are
    returned so callers can interpolate other per-sample arrays
    (e.g. winds) at the same point."""
    from core.route import haversine_nm
    if not samples:
        return 0.0, 0.0, 0.0, 0, 0.0
    if len(samples) == 1:
        return (float(samples[0][0]), float(samples[0][1]),
                float(alts_msl[0] if alts_msl else 0.0), 0, 0.0)
    cum = 0.0
    for i in range(len(samples) - 1):
        a_lat, a_lon = float(samples[i][0]), float(samples[i][1])
        b_lat, b_lon = float(samples[i + 1][0]), float(samples[i + 1][1])
        seg_nm = haversine_nm(a_lat, a_lon, b_lat, b_lon)
        if cum + seg_nm >= nm_along or i == len(samples) - 2:
            f = (nm_along - cum) / seg_nm if seg_nm > 0 else 0.0
            f = max(0.0, min(1.0, f))
            lat = a_lat + f * (b_lat - a_lat)
            lon = a_lon + f * (b_lon - a_lon)
            a_alt = float(alts_msl[i])
            b_alt = float(alts_msl[i + 1])
            alt = a_alt + f * (b_alt - a_alt)
            return lat, lon, alt, i, f
        cum += seg_nm
    # Past the end — return final sample.
    last = len(samples) - 1
    return (float(samples[last][0]), float(samples[last][1]),
            float(alts_msl[last] if alts_msl else 0.0), max(0, last - 1), 1.0)


def _interpolate_wind_at(sample_winds: list, seg_idx: int,
                          seg_frac: float) -> tuple[float, float]:
    """Pick the wind at segment_index / segment_fraction.

    Winds aloft are reported per-station/per-altitude with directions
    on the compass (0-360°), so a naive linear interpolation between
    e.g. 350° and 010° gives 180° (wrong way around). Convert to
    unit-vector components first, lerp, convert back.
    """
    if not sample_winds:
        return 0.0, 0.0
    n = len(sample_winds)
    if n == 1:
        return float(sample_winds[0][0]), float(sample_winds[0][1])
    i = max(0, min(n - 2, seg_idx))
    f = max(0.0, min(1.0, seg_frac))
    d1, s1 = float(sample_winds[i][0]), float(sample_winds[i][1])
    d2, s2 = float(sample_winds[i + 1][0]), float(sample_winds[i + 1][1])
    rad1 = math.radians(d1)
    rad2 = math.radians(d2)
    n1, e1 = s1 * math.cos(rad1), s1 * math.sin(rad1)
    n2, e2 = s2 * math.cos(rad2), s2 * math.sin(rad2)
    n_lerp = n1 + f * (n2 - n1)
    e_lerp = e1 + f * (e2 - e1)
    speed = math.hypot(n_lerp, e_lerp)
    direction = (math.degrees(math.atan2(e_lerp, n_lerp)) + 360.0) % 360.0
    return direction, speed


def _classify_airports_for_drill(envelope_pts, scrubber_lat, scrubber_lon,
                                  alt_agl, drill, ground_elev_ft):
    """Render airport classification markers for the engine-out drill.

    Green: airport is INSIDE the envelope polygon AND has > 500 ft of
    altitude margin to reach it.
    Amber: inside the polygon but margin ≤ 500 ft (borderline — wind
    shift or imperfect technique loses it).
    Gray: outside (rendered for context within a wider bounding box).

    We do a simple straight-line "altitude needed" check:
        alt_needed = distance_nm * 6076 / glide_ratio
    This is the same approximation `compute_glide_envelope` uses
    internally; the polygon is the iso-line where margin = 0.

    Returns (elements, best_target) where best_target is the highest-
    margin green airport (or amber if no green) so the caller can
    auto-plan a glide to it.
    """
    if not envelope_pts or len(envelope_pts) < 3:
        return [], None

    from core.data_loader import airport_data as _airports
    from core.route import haversine_nm

    # Bounding box of the envelope + a 10-NM pad for "outside" context.
    lats = [float(p[0]) for p in envelope_pts]
    lons = [float(p[1]) for p in envelope_pts]
    lat_pad = 10.0 / 60.0   # ~10 NM in degrees
    lon_pad = 10.0 / (60.0 * max(0.2, math.cos(math.radians(scrubber_lat))))
    bb_lat_min = min(lats) - lat_pad
    bb_lat_max = max(lats) + lat_pad
    bb_lon_min = min(lons) - lon_pad
    bb_lon_max = max(lons) + lon_pad

    # Point-in-polygon (ray casting). Envelope is small, convex-ish, so
    # this is fast enough at airport scale.
    def _inside(lat: float, lon: float) -> bool:
        x = lon
        y = lat
        inside = False
        n = len(envelope_pts)
        j = n - 1
        for i in range(n):
            xi = float(envelope_pts[i][1])
            yi = float(envelope_pts[i][0])
            xj = float(envelope_pts[j][1])
            yj = float(envelope_pts[j][0])
            intersect = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
            if intersect:
                inside = not inside
            j = i
        return inside

    glide_ratio = float(drill.get("glide_ratio", 9.0))

    import dash_leaflet as dl
    from dash import html
    elements: list = []
    # Track the highest-margin green target (or amber if none green).
    best_green: dict | None = None
    best_amber: dict | None = None

    for ap in _airports:
        try:
            ap_lat = float(ap.get("lat"))
            ap_lon = float(ap.get("lon"))
        except (TypeError, ValueError):
            continue
        if not (bb_lat_min <= ap_lat <= bb_lat_max and
                bb_lon_min <= ap_lon <= bb_lon_max):
            continue

        dist_nm = haversine_nm(scrubber_lat, scrubber_lon, ap_lat, ap_lon)
        ap_elev = float(ap.get("elevation_ft", ground_elev_ft) or ground_elev_ft)
        alt_needed_agl = (dist_nm * 6076.115 / max(0.1, glide_ratio))
        margin_ft = alt_agl - alt_needed_agl

        inside = _inside(ap_lat, ap_lon)

        if inside and margin_ft > 500:
            color, label = "#16a34a", "in-glide"
            radius = 6
            if best_green is None or margin_ft > best_green["_margin"]:
                best_green = {
                    "id": ap.get("id"), "name": ap.get("name"),
                    "lat": ap_lat, "lon": ap_lon,
                    "elev_ft": ap_elev, "runways": ap.get("runways") or [],
                    "_margin": margin_ft, "_dist_nm": dist_nm,
                }
        elif inside:
            color, label = "#f59e0b", "borderline"
            radius = 6
            if best_amber is None or margin_ft > best_amber["_margin"]:
                best_amber = {
                    "id": ap.get("id"), "name": ap.get("name"),
                    "lat": ap_lat, "lon": ap_lon,
                    "elev_ft": ap_elev, "runways": ap.get("runways") or [],
                    "_margin": margin_ft, "_dist_nm": dist_nm,
                }
        else:
            # Don't render every gray airport — that floods the map.
            # Only render those within 1.3× the envelope reach for
            # context; users see the gradient of options.
            if margin_ft < -1000:
                continue
            color, label = "#94a3b8", "out-of-glide"
            radius = 4

        ap_id = ap.get("id") or ap.get("icao") or "?"
        ap_name = ap.get("name") or ""
        elements.append(dl.CircleMarker(
            center=[ap_lat, ap_lon],
            radius=radius,
            color=color,
            fill=True,
            fillColor=color,
            fillOpacity=0.85,
            children=dl.Tooltip(html.Div([
                html.Div(f"{ap_id} — {ap_name}", style={"fontWeight": "600"}),
                html.Div(f"{label} · {dist_nm:.1f} NM"),
                html.Div(f"Margin: {margin_ft:+.0f} ft AGL"),
            ])),
        ))

    best = best_green or best_amber
    return elements, best


def _pick_offfield_target(*, offfield_centroids, water_centroids,
                           envelope_pts,
                           scrubber_lat, scrubber_lon, alt_agl,
                           glide_ratio, ground_elev_ft) -> dict | None:
    """Pick the best off-airport landing target per FAA AFH Ch. 18
    forced-landing precedence:

        1. Suitable open field   (in glide → green/yellow line)
        2. Water · ditching      (in glide → yellow/red line)
        3. Nearest-of-anything   (outside glide → red line; pilot
                                   needs to know they're committed
                                   to something below minimums)

    Returns a target-shaped dict with `_landing_class` attached so
    the planner caller can color the line + label the tooltip.
    """
    from core.route import haversine_nm

    if not envelope_pts or len(envelope_pts) < 3:
        envelope_pts_safe = []
    else:
        envelope_pts_safe = envelope_pts

    def _inside(lat: float, lon: float) -> bool:
        if not envelope_pts_safe:
            return False
        x, y = lon, lat
        inside = False
        n = len(envelope_pts_safe)
        j = n - 1
        for i in range(n):
            xi = float(envelope_pts_safe[i][1])
            yi = float(envelope_pts_safe[i][0])
            xj = float(envelope_pts_safe[j][1])
            yj = float(envelope_pts_safe[j][0])
            if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    def _closest(centroids, must_be_inside):
        best, best_d = None, 1e9
        for c in centroids or []:
            try:
                lat, lon = float(c[0]), float(c[1])
            except (TypeError, ValueError, IndexError):
                continue
            if must_be_inside and not _inside(lat, lon):
                continue
            d = haversine_nm(scrubber_lat, scrubber_lon, lat, lon)
            if d < best_d:
                best_d, best = d, (lat, lon)
        return best, best_d

    def _make_target(coords, dist_nm, klass):
        lat, lon = coords
        alt_needed_agl = (dist_nm * 6076.115 / max(0.1, glide_ratio))
        margin_ft = alt_agl - alt_needed_agl
        label_for = {
            "field": "field · forced landing",
            "water": "water · ditch",
            "fallback_field": "field (out of glide)",
            "fallback_water": "water (out of glide)",
        }[klass]
        return {
            "id": "OFF-FIELD" if "field" in klass else "DITCHING",
            "name": f"{label_for} @ {lat:.4f}, {lon:.4f}",
            "lat": lat, "lon": lon,
            "elev_ft": ground_elev_ft,
            "runways": [],
            "_margin": margin_ft,
            "_dist_nm": dist_nm,
            "_landing_class": klass,
        }

    # Tier 2: suitable field inside envelope.
    pt, d = _closest(offfield_centroids, must_be_inside=True)
    if pt is not None:
        return _make_target(pt, d, "field")

    # Tier 3: water inside envelope (ditching).
    pt, d = _closest(water_centroids, must_be_inside=True)
    if pt is not None:
        return _make_target(pt, d, "water")

    # Tier 4 fallback — nothing in glide. Pick the closest of EITHER
    # field or water so the line draws (red, below-minimums). This is
    # the case the user complained about — better to show "you'd be
    # ditching here, and you can't make it" than a blank ring.
    field_pt, field_d = _closest(offfield_centroids, must_be_inside=False)
    water_pt, water_d = _closest(water_centroids, must_be_inside=False)
    # Prefer field over water at parity per AFH precedence.
    if field_pt is not None and (water_pt is None or field_d <= water_d * 1.2):
        return _make_target(field_pt, field_d, "fallback_field")
    if water_pt is not None:
        return _make_target(water_pt, water_d, "fallback_water")
    return None


def _plan_glide_for_drill(*, target, pos_lat, pos_lon, alt_agl,
                          seg_idx, samples, wind_dir, wind_speed,
                          wind_profile_data, aircraft_name, engine_name,
                          runtime_weight, oat_f, altimeter_inhg,
                          ground_elev_ft, target_is_off_field=False):
    """Call simulate_engineout_planned with sensible auto-mode defaults
    and return the planned glide-path as map elements.

    This is the A1-4 piece: instead of just showing a reachability
    polygon, we run the SAME planner the standalone engine-out tool
    uses (`simulation/eo_planner.simulate_engineout_planned`) and draw
    the resulting trajectory. No new physics.

    Auto-mode picks:
      - start_heading: direction along the current route segment
      - touchdown_heading: the airport runway end best aligned with
        landing-INTO-the-wind (heading closest to wind FROM dir)
      - aircraft / engine / weight / OAT / altimeter: from sidebar
      - flap / prop config: "clean" / "windmilling" (most conservative)
    """
    import math as _math
    import dash_leaflet as dl
    from dash import html
    from geopy import Point as _GeoPoint

    if not aircraft_name:
        return []
    from core.data_loader import aircraft_data
    ac = aircraft_data.get(aircraft_name)
    if not ac:
        return []

    # ── start_heading: direction along the route segment under scrubber.
    if seg_idx + 1 < len(samples):
        a_lat, a_lon = float(samples[seg_idx][0]), float(samples[seg_idx][1])
        b_lat, b_lon = float(samples[seg_idx + 1][0]), float(samples[seg_idx + 1][1])
        dn = (b_lat - a_lat) * 60.0
        de = (b_lon - a_lon) * 60.0 * _math.cos(_math.radians(a_lat))
        start_heading = (_math.degrees(_math.atan2(de, dn)) + 360.0) % 360.0
    else:
        start_heading = 0.0

    # ── touchdown runway: pick the runway END whose heading is
    # closest to landing-INTO-the-wind. wind_dir is FROM direction,
    # so landing into the wind means the aircraft heads TOWARD
    # wind_dir as it rolls out — runway heading ≈ wind_dir.
    runways = target.get("runways") or []
    td_lat, td_lon = float(target["lat"]), float(target["lon"])
    touchdown_heading = wind_dir if wind_speed > 1 else start_heading

    if runways:
        best_end = None
        best_diff = 9999.0
        for rwy in runways:
            for end in rwy.get("ends") or []:
                end_hdg = end.get("heading")
                if end_hdg is None:
                    continue
                # smallest absolute compass difference
                diff = abs(((float(end_hdg) - wind_dir + 540.0) % 360.0) - 180.0)
                if diff < best_diff:
                    best_diff = diff
                    best_end = end
        if best_end is not None:
            td_lat = float(best_end.get("lat", td_lat))
            td_lon = float(best_end.get("lon", td_lon))
            touchdown_heading = float(best_end.get("heading", touchdown_heading))

    # ── env conversions ──────────────────────────────────────────────
    try:
        oat_c = (float(oat_f) - 32.0) * 5.0 / 9.0
    except (TypeError, ValueError):
        oat_c = 15.0
    try:
        alt_inhg = float(altimeter_inhg)
    except (TypeError, ValueError):
        alt_inhg = 29.92
    try:
        weight_lbs = float(runtime_weight)
        if not weight_lbs:
            weight_lbs = float(ac.get("max_takeoff_weight", ac.get("gross_weight", 2300.0)))
    except (TypeError, ValueError):
        weight_lbs = float(ac.get("max_takeoff_weight", ac.get("gross_weight", 2300.0)))

    # Engine option — use sidebar pick or first available.
    engine_key = engine_name
    if not engine_key:
        opts = ac.get("engine_options") or {}
        if isinstance(opts, dict) and opts:
            engine_key = next(iter(opts))

    # Optional wind profile from the live winds-aloft store.
    wind_profile = None
    if wind_profile_data:
        try:
            from core.winds_aloft import WindProfile
            wind_profile = WindProfile.from_store(wind_profile_data)
        except Exception:
            wind_profile = None

    # ── Plan the glide ──────────────────────────────────────────────
    from simulation.eo_planner import simulate_engineout_planned
    path, hover, meta = simulate_engineout_planned(
        start_point=_GeoPoint(pos_lat, pos_lon),
        start_heading=float(start_heading),
        touchdown_point=_GeoPoint(td_lat, td_lon),
        touchdown_heading=float(touchdown_heading),
        ac=ac,
        engine_option=engine_key,
        weight_lbs=float(weight_lbs),
        flap_config="clean",
        prop_config="windmilling",
        oat_c=float(oat_c),
        altimeter_inhg=float(alt_inhg),
        wind_dir=float(wind_dir),
        wind_speed=float(wind_speed),
        wind_profile=wind_profile,
        altitude_agl=float(alt_agl),
        touchdown_elev_ft=float(target.get("elev_ft", ground_elev_ft)),
        timestep_sec=0.5,
    )

    if not path:
        return []

    # Color the planned line + label by outcome AND FAA precedence
    # tier. The pilot needs to see at a glance: am I landing on a
    # runway (good), in a field (acceptable), or in water (ditching).
    #
    #   GREEN  — runway with margin
    #   YELLOW — runway tight / field with margin / water in glide
    #   RED    — below minimums of any flavor / forced ditching out of glide
    success = bool(meta.get("success", False))
    start_margin = float(target.get("_margin", 0))
    landing_class = target.get("_landing_class")  # only set for off-field

    if not success:
        track_color = "#dc2626"
        outcome_label = "BELOW MINIMUMS · runway out of reach" if not target_is_off_field else "BELOW MINIMUMS"
    elif not target_is_off_field:
        if start_margin < 200:
            track_color = "#f59e0b"
            outcome_label = "MAKES IT · perfect required"
        else:
            track_color = "#16a34a"
            outcome_label = "SUCCESS · runway"
    elif landing_class == "field":
        if start_margin < 300:
            track_color = "#dc2626"
            outcome_label = "FORCED LANDING · field · marginal"
        else:
            track_color = "#f59e0b"
            outcome_label = "FORCED LANDING · field · energy in hand"
    elif landing_class == "water":
        # Ditching is always at minimum yellow per AFH §18-7 — pilot
        # MUST recognize this isn't an airport landing.
        if start_margin < 300:
            track_color = "#dc2626"
            outcome_label = "DITCHING · water · marginal"
        else:
            track_color = "#f59e0b"
            outcome_label = "DITCHING · water"
    elif landing_class == "fallback_field":
        track_color = "#dc2626"
        outcome_label = "OUT OF GLIDE · nearest field"
    elif landing_class == "fallback_water":
        track_color = "#dc2626"
        outcome_label = "OUT OF GLIDE · nearest water (ditch)"
    else:
        track_color = "#f59e0b"
        outcome_label = "OFF-AIRPORT"

    out: list = []
    out.append(dl.Polyline(
        positions=[[float(p[0]), float(p[1])] for p in path],
        color=track_color, weight=4, opacity=0.95,
        children=dl.Tooltip(html.Div([
            html.Div(
                f"Planned glide → {target.get('id', '?')}",
                style={"fontWeight": "600"},
            ),
            html.Div(
                f"{outcome_label} · "
                f"{'OFF-FIELD' if target_is_off_field else f'runway {touchdown_heading:.0f}°'}"
            ),
            html.Div(f"Reach margin at start: {start_margin:+.0f} ft AGL"),
        ])),
    ))
    # Touchdown marker.
    out.append(dl.CircleMarker(
        center=[td_lat, td_lon],
        radius=7, color=track_color, fill=True,
        fillColor=track_color, fillOpacity=1.0,
        children=dl.Tooltip(
            f"{'Off-airport' if target_is_off_field else 'Touchdown'} — "
            f"{target.get('id', '?')}"
        ),
    ))
    return out


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
        leg_rows = []
        for l in legs:
            value_parts = [
                f"{l['distance_nm']:.0f} NM",
                f"{l['magnetic_course_deg']:03.0f}°M",
                f"{l['ete_min']:.0f} min",
            ]
            ws = l.get("wind_summary")
            if ws:
                value_parts.append(ws)
            leg_rows.append(html.Div([
                html.Span(f"{l['origin_id']}→{l['dest_id']}",
                          className="route-leg-label"),
                html.Span(" · ".join(value_parts),
                          className="route-leg-value"),
            ], className="route-leg-row"))
        head = html.Div([head, html.Div(leg_rows, className="route-leg-list")])
    return head


def _empty_clear():
    """Standard return when Clear is pressed: empty banner, empty
    below-strip, empty nav log, empty map layer, no viewport change,
    cleared store."""
    return None, None, None, [], no_update, None


# === FAA-style navigation log ==============================================

def _fmt(v, fmt: str, na: str = "—") -> str:
    """Safe format helper — returns `na` for None/NaN, otherwise formats."""
    if v is None:
        return na
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return na


def _stacked(*lines, sep_class="nav-log-stack-sep"):
    """A single table cell with vertically-stacked sub-values, the way
    the Jeppesen VFR Nav Log packs multiple related fields into one
    column (TC/WCA, TH/Var, MH/Dev, Dist Leg/Rem, etc.)."""
    parts: list = []
    for i, line in enumerate(lines):
        if i:
            parts.append(html.Div(className=sep_class))
        parts.append(html.Div(line, className="nav-log-stack-line"))
    return parts


def _airport_panel(label: str, ap: dict | None) -> object:
    """Right-side Airport & ATIS Advisories panel for one airport
    (Departure or Destination). FAA form has these labelled rows the
    pilot fills in pre-flight from ATIS / AWOS / NOTAMs. We pre-fill
    Field Elev + Runways from our airport JSON and leave the rest
    blank for ink.

    ATIS code / Wind / Altimeter / Ceiling / Visibility would require
    a live METAR feed — listed as a future-phase follow-up.
    """
    fe = (ap.get("elevation_ft") if ap else None)
    name = (ap.get("name") if ap else "") or ""
    icao = (ap.get("id") if ap else "—")
    runways = (ap.get("runways") if ap else None) or []
    freqs = _freqs_for(icao) if icao and icao != "—" else {}

    def row(label_text, value=""):
        return html.Tr([
            html.Td(label_text, className="nav-log-ap-key"),
            html.Td(value, className="nav-log-ap-val"),
        ])

    # Format runways as "17R/35L · 7000 ft · asphalt" stacked.
    rwy_str = ""
    if runways:
        rwy_lines = []
        for r in runways:
            length = r.get("length_ft")
            surf = (r.get("surface") or "").lower()
            rid = r.get("id", "?")
            if length:
                rwy_lines.append(f"{rid} · {length:.0f} ft · {surf}")
            else:
                rwy_lines.append(rid)
        rwy_str = " / ".join(rwy_lines)

    # Pre-fill ATIS row with broadcast frequency. The "Code" itself
    # (e.g. Information Alpha) only comes from a live ATIS pull —
    # pilot still ink-fills that letter pre-flight.
    atis_freq = freqs.get("ATIS", "")
    atis_label = f"freq {atis_freq}" if atis_freq else ""

    return html.Div(className="nav-log-ap-panel", children=[
        html.Div(label, className="nav-log-ap-panel-title"),
        html.Div(f"{icao} · {name}", className="nav-log-ap-subtitle"),
        html.Table(className="nav-log-ap-table", children=[
            html.Tbody([
                row("ATIS Code", atis_label),
                row("Ceiling / Vis"),
                row("Wind"),
                row("Altimeter"),
                row("Approach", freqs.get("APP", "")),
                row("Runways", rwy_str),
                row("Time Check"),
                row("Field Elev", _fmt(fe, "{:.0f} ft")),
            ]),
        ]),
    ])


def _frequencies_panel(label: str, ap: dict | None) -> object:
    """Airport Frequencies panel — pre-filled from OurAirports'
    airport-frequencies CSV (FAA NASR rollup). Each labelled row
    shows the matching frequency when present; empty otherwise so
    the pilot can write in anything we don't have (e.g. an FBO
    frequency on a chart supplement)."""
    icao = (ap.get("id") if ap else "—")
    freqs = _freqs_for(icao) if icao and icao != "—" else {}

    def row(label_text, bucket_key):
        return html.Tr([
            html.Td(label_text, className="nav-log-ap-key"),
            html.Td(freqs.get(bucket_key, ""),
                    className="nav-log-ap-val"),
        ])

    return html.Div(className="nav-log-freq-panel", children=[
        html.Div(f"{label} Frequencies", className="nav-log-ap-panel-title"),
        html.Div(icao, className="nav-log-ap-subtitle"),
        html.Table(className="nav-log-ap-table", children=[
            html.Tbody([
                row("ATIS", "ATIS"),
                row("Ground", "GND"),
                row("Tower", "TWR"),
                row("Approach", "APP"),
                row("Departure", "DEP"),
                row("Clearance", "CLD"),
                row("CTAF", "CTAF"),
                row("UNICOM", "UNICOM"),
                row("FSS", "FSS"),
            ]),
        ]),
    ])


def _da_chip_inner(da_ft, dep_wp):
    """Header chip for density altitude. Color-flags when DA is more
    than 2000 ft above the field, the threshold where takeoff/climb
    performance becomes a planning concern for typical-single GA."""
    if da_ft is None:
        return [
            html.Span("DA  ", className="nav-log-hs-label"),
            html.Span("—", className="nav-log-hs-val"),
        ]
    elev = float(dep_wp.get("elevation_ft") or 0.0)
    delta = da_ft - elev
    style: dict[str, str] = {}
    if delta >= 3000:
        style = {"color": "#b91c1c"}  # red — significant degradation
    elif delta >= 2000:
        style = {"color": "#d97706"}  # amber — keep an eye on it
    return [
        html.Span("DA  ", className="nav-log-hs-label"),
        html.Span(f"{da_ft:.0f} ft",
                  className="nav-log-hs-val", style=style,
                  title=(f"Departure pressure alt: {elev:.0f} ft + ISA dev. "
                         f"Δ = {delta:+.0f} ft vs field.")),
    ]


def _build_nav_log(*, waypoints, legs, totals, cruise_alt, aircraft_name,
                   tas_kt, total_weight, fuel_load_gal, wind_source,
                   critique, corridor_meta, divert_summary,
                   airport_records=None, cas_kt_override=None,
                   profile=None, airspace_crossings=None,
                   density_altitude_ft=None, notams=None,
                   profile_chart=None, checkpoints=None):
    """Render a Jeppesen-style VFR navigation log.

    Layout mirrors the standard FAA/Jeppesen VFR Nav Log form: a multi-
    line-header checkpoint table on the left, with Airport & ATIS
    Advisories + Frequencies panels on the right. Fields the pilot
    fills in by hand (CH dev, ATE, ATA, ATIS code, etc.) are rendered
    as blank cells. TallyAero adds an Engine-Out Analysis block below
    the form as our value-add over the paper version.
    """
    # --- Header strip -------------------------------------------------------
    header_strip = html.Div(className="nav-log-header-strip", children=[
        html.Div("VFR NAVIGATION LOG", className="nav-log-form-title"),
        html.Div([
            html.Span("Aircraft  ", className="nav-log-hs-label"),
            html.Span(aircraft_name or "—", className="nav-log-hs-val"),
        ]),
        html.Div([
            html.Span("Date  ", className="nav-log-hs-label"),
            html.Span(datetime.now().strftime("%Y-%m-%d"),
                      className="nav-log-hs-val"),
        ]),
        html.Div([
            html.Span("Cruise  ", className="nav-log-hs-label"),
            html.Span(_fmt(cruise_alt, "{:.0f} ft MSL"),
                      className="nav-log-hs-val"),
        ]),
        html.Div([
            html.Span("TAS  ", className="nav-log-hs-label"),
            html.Span(_fmt(tas_kt, "{:.0f} kt"),
                      className="nav-log-hs-val"),
        ]),
        html.Div([
            html.Span("Fuel  ", className="nav-log-hs-label"),
            html.Span(_fmt(fuel_load_gal, "{:.0f} gal"),
                      className="nav-log-hs-val"),
        ]),
        # Density altitude — color-flagged when degraded performance kicks in.
        # >2000 ft above field elev is a meaningful signal for a single-engine
        # piston; >3000 ft is "you'll feel it" territory.
        html.Div(_da_chip_inner(density_altitude_ft, waypoints[0]
                                if waypoints else {})),
    ])

    # --- Main checkpoint table (Jeppesen column layout) --------------------
    # Headers use slashes to indicate vertically stacked fields the
    # form packs into one column (TC/WCA, TH/Var, etc.). Cells use
    # _stacked() so the data lines align with the header lines.
    th_cols = [
        ("Check Point",        "nav-log-col-cp"),
        ("VOR\nIdent / Freq",  "nav-log-col-vor"),
        ("Course",             "nav-log-col-course"),
        ("Altitude",           "nav-log-col-alt"),
        ("Wind\nDir/Vel · Temp", "nav-log-col-wind"),
        ("CAS\nTAS",           "nav-log-col-cas"),
        ("TC\n-L/+R WCA",      "nav-log-col-tc"),
        ("TH\n-E/+W Var",      "nav-log-col-th"),
        ("MH\n± Dev",          "nav-log-col-mh"),
        ("CH",                 "nav-log-col-ch"),
        ("Dist\nLeg / Rem",    "nav-log-col-dist"),
        ("GS\nEst / Act",      "nav-log-col-gs"),
        ("Time Off / ETE",     "nav-log-col-time"),
        ("ETA / ATA",          "nav-log-col-time"),
        ("GPH · Fuel / Rem",   "nav-log-col-fuel"),
    ]
    thead = html.Thead(html.Tr([
        html.Th(html.Div([html.Div(part) for part in label.split("\n")]),
                className=cls)
        for label, cls in th_cols
    ]))

    # ─── Expand legs into segments at TOC / TOD inflection points ──────
    # The user's waypoint-to-waypoint legs ignore where the airplane
    # actually reaches cruise (Top of Climb) or starts descending
    # (Top of Descent). A pilot's nav log shows TOC + TOD as
    # explicit fix entries so the climb/cruise/descent phase of each
    # row is unambiguous. We split each input leg into 1-3 segments
    # based on whether d_toc / d_tod fall inside its distance range.
    d_toc = float(profile.get("d_toc_nm")) if profile else None
    d_tod = float(profile.get("d_tod_nm")) if profile else None
    climb_gs = float(profile.get("climb_gs_kt")) if profile else None
    descent_gs = float(profile.get("descent_gs_kt")) if profile else None
    field_dest_ft = float(profile.get("field_dest_ft")) if profile else None
    field_dep_ft = float(profile.get("field_dep_ft")) if profile else None

    segments: list[dict] = []
    _route_cum = 0.0
    for _leg_idx, leg in enumerate(legs):
        leg_dist = float(leg.get("distance_nm") or 0)
        leg_ete = float(leg.get("ete_min") or 0)
        leg_fuel = leg.get("fuel_burn_gal")
        leg_start = _route_cum
        leg_end = _route_cum + leg_dist

        # Collect inflection points inside this leg (strictly between
        # leg_start and leg_end so points at exact leg boundaries
        # don't produce zero-length sub-segments).
        inflections: list[tuple[str, float]] = []
        if d_toc is not None and leg_start < d_toc < leg_end:
            inflections.append(("TOC", d_toc))
        if d_tod is not None and leg_start < d_tod < leg_end:
            inflections.append(("TOD", d_tod))
        # Inject VFR checkpoints for this leg as inflection points
        # so each checkpoint becomes its own row in the Jeppesen
        # table (Fix · TC · Distance · ETE · Fuel) instead of just
        # appearing in a separate block. cumulative_nm follows the
        # bent path so it lines up correctly with the leg ordering.
        if checkpoints:
            for cp in checkpoints:
                if cp.get("leg_idx") != _leg_idx:
                    continue
                cp_pos = float(cp.get("cumulative_nm") or 0)
                if leg_start < cp_pos < leg_end:
                    inflections.append((cp.get("ident") or "?", cp_pos))
        inflections.sort(key=lambda x: x[1])

        cur_origin = leg.get("origin_id", "—")
        cur_pos = leg_start
        for fix_name, fix_pos in inflections:
            sub_dist = fix_pos - cur_pos
            if sub_dist <= 0:
                continue
            frac = sub_dist / max(leg_dist, 0.001)
            segments.append({
                **leg,
                "origin_id": cur_origin,
                "dest_id": fix_name,
                "distance_nm": sub_dist,
                "ete_min": leg_ete * frac,
                "fuel_burn_gal": (leg_fuel * frac) if leg_fuel else None,
                "_is_toc": fix_name == "TOC",
                "_is_tod": fix_name == "TOD",
                # Altitude shown for this sub-segment's endpoint:
                # cruise once we hit TOC, dest field elev at TOD.
                "_endpoint_alt_ft": (cruise_alt if fix_name == "TOC"
                                    else field_dest_ft),
                "_phase": ("climb" if fix_name == "TOC" else "descent"),
            })
            cur_origin = fix_name
            cur_pos = fix_pos

        # Tail segment from the last inflection (or leg start) to the
        # leg's real destination.
        tail_dist = leg_end - cur_pos
        if tail_dist > 0:
            frac = tail_dist / max(leg_dist, 0.001)
            # Phase = cruise if we already crossed TOC, descent if past
            # TOD, else climb.
            if d_tod is not None and cur_pos >= d_tod:
                phase = "descent"
                endpoint_alt = field_dest_ft
            elif d_toc is None or cur_pos >= d_toc:
                phase = "cruise"
                endpoint_alt = cruise_alt
            else:
                phase = "climb"
                endpoint_alt = cruise_alt
            segments.append({
                **leg,
                "origin_id": cur_origin,
                "distance_nm": tail_dist,
                "ete_min": leg_ete * frac,
                "fuel_burn_gal": (leg_fuel * frac) if leg_fuel else None,
                "_is_toc": False,
                "_is_tod": False,
                "_endpoint_alt_ft": endpoint_alt,
                "_phase": phase,
            })

        _route_cum = leg_end

    body_rows = []
    cum_dist = 0.0
    cum_ete = 0.0
    cum_fuel = 0.0
    total_dist = sum(float(s.get("distance_nm") or 0) for s in segments)
    fuel_rem = float(fuel_load_gal or 0)

    for i, leg in enumerate(segments):
        leg_dist = float(leg.get("distance_nm") or 0)
        leg_ete = float(leg.get("ete_min") or 0)
        leg_fuel = leg.get("fuel_burn_gal")
        cum_dist += leg_dist
        cum_ete += leg_ete
        if leg_fuel is not None:
            cum_fuel += float(leg_fuel)
            fuel_rem -= float(leg_fuel)
        dist_rem = total_dist - cum_dist
        gph = (float(leg_fuel) / (leg_ete / 60.0)
               if leg_fuel and leg_ete > 0 else None)
        # Use phase-appropriate GS for TOC/TOD virtual segments. The
        # leg's stored ground_speed_kt is cruise GS; climb/descent are
        # slower (climb at climb_ias, descent at descent_ias).
        phase = leg.get("_phase", "cruise")
        if phase == "climb" and climb_gs:
            seg_gs = climb_gs
        elif phase == "descent" and descent_gs:
            seg_gs = descent_gs
        else:
            seg_gs = leg.get("ground_speed_kt")
        # Endpoint altitude for the Alt column
        seg_alt = leg.get("_endpoint_alt_ft", cruise_alt)

        # WCA: small-angle approximation works for typical XW/TAS ratios.
        xw = leg.get("crosswind_kt") or 0
        wca = math.degrees(math.asin(max(-1, min(1,
            xw / max(1, float(tas_kt or 1))))))
        var = leg.get("magvar_deg") or 0
        tc = leg.get("true_course_deg")
        th = leg.get("true_heading_deg")
        mh = leg.get("magnetic_heading_deg")
        wind_dir = leg.get("wind_dir_deg", 0)
        wind_vel = leg.get("wind_speed_kt", 0)
        # CAS: user override if supplied, else compute from TAS via ISA
        # density ratio. σ = (1 - 6.876e-6 × alt)^4.2561 → CAS = TAS × √σ.
        if cas_kt_override is not None:
            cas = cas_kt_override
        else:
            try:
                sigma = (1.0 - 6.875585e-6 * float(cruise_alt)) ** 4.2561
                sigma = max(0.2, min(1.0, sigma))
                cas = float(tas_kt) * math.sqrt(sigma)
            except (TypeError, ValueError):
                cas = tas_kt
        gs = seg_gs
        # TOC/TOD rows get a tinted row class so they read as
        # inflection points, not normal fixes.
        row_class = ""
        if leg.get("_is_toc"):
            row_class = "nav-log-toc-row"
        elif leg.get("_is_tod"):
            row_class = "nav-log-tod-row"

        body_rows.append(html.Tr(className=row_class, children=[
            # Check Point — show the leg destination waypoint
            html.Td(_stacked(leg.get("dest_id", "—"),
                             leg.get("origin_id", "")
                             if i == 0 else ""),
                    className="nav-log-cell-cp"),
            # VOR: blank both lines (no nav-aid data in our DB yet)
            html.Td(_stacked("", "")),
            # Course (Route): direct great-circle by default
            html.Td(_stacked("Direct", "")),
            # Altitude — endpoint altitude for the phase
            html.Td(_stacked(_fmt(seg_alt, "{:.0f}"), "")),
            # Wind dir/vel + Temp (blank — we don't have temp aloft yet)
            html.Td(_stacked(f"{wind_dir:03.0f} / {wind_vel:.0f}", "")),
            # CAS / TAS
            html.Td(_stacked(_fmt(cas, "{:.0f}"),
                             _fmt(tas_kt, "{:.0f}"))),
            # TC / WCA
            html.Td(_stacked(_fmt(tc, "{:.0f}"),
                             f"{wca:+.0f}")),
            # TH / Var
            html.Td(_stacked(_fmt(th, "{:.0f}"),
                             f"{var:+.0f}")),
            # MH / Dev (pilot fills Dev)
            html.Td(_stacked(_fmt(mh, "{:.0f}"), "")),
            # CH (pilot computes from MH + Dev)
            html.Td(""),
            # Dist Leg / Rem
            html.Td(_stacked(f"{leg_dist:.1f}", f"{dist_rem:.1f}")),
            # GS Est / Act (pilot fills Act)
            html.Td(_stacked(_fmt(gs, "{:.0f}"), "")),
            # Time Off / ETE (pilot fills Time Off; ETE is computed)
            html.Td(_stacked("", f"{leg_ete:.0f}")),
            # ETA / ATA (pilot fills both)
            html.Td(_stacked("", "")),
            # GPH · Fuel / Rem
            html.Td(_stacked(
                _fmt(gph, "{:.1f}"),
                f"{leg_fuel:.1f} / {fuel_rem:.1f}"
                if leg_fuel else "—",
            )),
        ]))

    # Totals row
    body_rows.append(html.Tr(className="nav-log-totals-row", children=[
        html.Td("Totals »", colSpan=10,
                style={"textAlign": "right", "fontWeight": "800"}),
        html.Td(_stacked(f"{cum_dist:.1f}", "")),
        html.Td(""),
        html.Td(_stacked("", f"{cum_ete:.0f}")),
        html.Td(""),
        html.Td(_stacked("",
                         f"{cum_fuel:.1f}" if cum_fuel > 0 else "—")),
    ]))

    legs_table_wrap = html.Div(className="nav-log-table-wrap", children=[
        html.Table(className="nav-log-table", children=[
            thead,
            html.Tbody(body_rows),
        ]),
    ])

    # --- Right-side Airport panels -----------------------------------------
    airport_records = airport_records or {}
    dep_ap = airport_records.get(waypoints[0].get("id"))
    dest_ap = airport_records.get(waypoints[-1].get("id"))
    side_panels = html.Div(className="nav-log-side-panels", children=[
        _airport_panel("Departure ATIS", dep_ap),
        _airport_panel("Destination ATIS", dest_ap),
        _frequencies_panel("Departure", dep_ap),
        _frequencies_panel("Destination", dest_ap),
    ])

    # --- Form body: table on top, airport panels in a horizontal row below.
    # Pilots fill in the airport ATIS / frequency rows from chart
    # supplements pre-flight; putting them under the legs table keeps
    # the checkpoint table full-width (no horizontal scroll) and
    # mirrors the standard FAA form's footer placement.
    form_row = html.Div(className="nav-log-form-stack", children=[
        legs_table_wrap,
        side_panels,
    ])

    # --- Block In/Out + Log Time + Notes ----------------------------------
    foot_strip = html.Div(className="nav-log-foot-strip", children=[
        html.Div(className="nav-log-foot-cell", children=[
            html.Div("Block Out", className="nav-log-foot-label"),
            html.Div("", className="nav-log-foot-input"),
        ]),
        html.Div(className="nav-log-foot-cell", children=[
            html.Div("Block In", className="nav-log-foot-label"),
            html.Div("", className="nav-log-foot-input"),
        ]),
        html.Div(className="nav-log-foot-cell", children=[
            html.Div("Log Time", className="nav-log-foot-label"),
            html.Div("", className="nav-log-foot-input"),
        ]),
        html.Div(className="nav-log-foot-cell nav-log-foot-notes",
                 children=[
            html.Div("Notes", className="nav-log-foot-label"),
            html.Div("", className="nav-log-foot-input nav-log-notes-area"),
        ]),
    ])

    # --- TallyAero Engine-Out Analysis (value-add below FAA form) ---------
    eo_kv_rows = []

    def _eo_row(k, v):
        return html.Tr([
            html.Td(k, className="nav-log-kv-key"),
            html.Td(v, className="nav-log-kv-val"),
        ])

    if corridor_meta:
        eo_kv_rows.append(_eo_row(
            "AGL min / avg / max",
            f"{corridor_meta.get('min_agl_ft', 0):.0f} / "
            f"{corridor_meta.get('agl_ft', 0):.0f} / "
            f"{corridor_meta.get('max_agl_ft', 0):.0f} ft"))
        bts = corridor_meta.get("below_terrain_samples", 0)
        if bts > 0:
            eo_kv_rows.append(_eo_row(
                "Terrain conflict",
                f"{bts} samples below ridge"))
    if divert_summary:
        eo_kv_rows.append(_eo_row(
            "Engine-out diverts",
            f"{divert_summary.get('n_diverts', 0)} airports in glide"))
        gap = divert_summary.get("longest_gap_nm", 0)
        if gap > 0:
            eo_kv_rows.append(_eo_row(
                "Longest no-divert stretch",
                f"{gap:.0f} NM"))
        sug = divert_summary.get("suggested_alt_ft")
        if sug:
            eo_kv_rows.append(_eo_row(
                "Suggested cruise (terrain-clear)",
                f"{sug:.0f} ft MSL"))

    factor_rows = [
        html.Tr([
            html.Td(f"{f.points:+.0f}",
                    className=("nav-log-factor-pts"
                               + (" nav-log-factor-pos"
                                  if f.points > 0 else ""))),
            html.Td(f.label, className="nav-log-factor-label"),
            html.Td(f.detail, className="nav-log-factor-detail"),
        ])
        for f in critique.factors
    ]

    eo_block = html.Div(className="nav-log-section", children=[
        html.H4("Engine-Out Analysis (TallyAero)",
                className="nav-log-section-title"),
        html.Div(className="nav-log-eo-grid", children=[
            html.Table(className="nav-log-meta-table",
                       children=[html.Tbody(eo_kv_rows)])
                if eo_kv_rows else html.Div(),
            html.Div(className="nav-log-factors-block", children=[
                html.Div(f"Survivability {critique.score}/100 — "
                         f"{critique.headline}",
                         className="nav-log-factors-heading",
                         style={"color": critique.color_hex()}),
                html.Table(className="nav-log-factors-table",
                           children=[html.Tbody(factor_rows)])
                if factor_rows else None,
            ]),
        ]),
    ])

    # --- Airspace crossings (Phase 7f-D) ------------------------------
    airspace_block = None
    if airspace_crossings:
        pierces = [x for x in airspace_crossings if x["pierces"]]
        over_under = [x for x in airspace_crossings if not x["pierces"]]

        def _xing_row(x):
            code = x["type_code"]
            style = TYPE_STYLES.get(code, {})
            color = style.get("color", "#666")
            label = style.get("label", code or "?")
            # Pierce + activation cell. A "cold" (inactive) airspace at
            # the planned crossing time is far less of a concern than a
            # hot one, even when the route geometrically pierces it.
            active = x.get("active", True)
            if x["pierces"]:
                verdict = "PIERCE" if active else "PIERCE (cold)"
                verdict_cls = ("nav-log-as-pierce" if active
                               else "nav-log-as-pierce-cold")
            else:
                verdict = "over/under"
                verdict_cls = "nav-log-as-overunder"
            # Times text: schedule summary if known, eff_times otherwise.
            times_text = (x.get("schedule_summary")
                          or x.get("eff_times")
                          or ("active" if active else "inactive"))
            return html.Tr([
                html.Td(verdict, className=verdict_cls),
                html.Td(html.Span(label,
                                  className="nav-log-as-chip",
                                  style={"backgroundColor": color,
                                         "color": "#fff"})),
                html.Td(x["name"], className="nav-log-as-name"),
                html.Td(_format_alt(x.get("floor_ft")),
                        className="nav-log-as-alt"),
                html.Td(_format_alt(x.get("ceiling_ft")),
                        className="nav-log-as-alt"),
                html.Td(times_text,
                        className="nav-log-as-times",
                        title=times_text),
            ])

        body_rows = [_xing_row(x) for x in pierces + over_under]
        airspace_block = html.Div(
            className="nav-log-section",
            children=[
                html.H4(
                    f"Airspace Along Route — {len(pierces)} pierce · "
                    f"{len(over_under)} over/under",
                    className="nav-log-section-title"),
                html.Table(className="nav-log-as-table", children=[
                    html.Thead(html.Tr([
                        html.Th("Vertical"),
                        html.Th("Type"),
                        html.Th("Name"),
                        html.Th("Floor"),
                        html.Th("Ceiling"),
                        html.Th("Times"),
                    ])),
                    html.Tbody(body_rows),
                ]),
            ],
        )

    # --- NOTAMs (Phase A4) -------------------------------------------
    notam_block = None
    if notams:
        from core.notams import category_style

        def _notam_row(n):
            label, color = category_style(n.get("category"))
            return html.Tr([
                html.Td(html.Span(label,
                                  className="nav-log-as-chip",
                                  style={"backgroundColor": color,
                                         "color": "#fff"})),
                html.Td(n.get("id") or "—",
                        className="nav-log-as-name"),
                html.Td(f"{n.get('distance_nm', 0):.1f} nm",
                        className="nav-log-as-alt"),
                html.Td(_format_notam_alt(n),
                        className="nav-log-as-alt"),
                html.Td(_format_notam_window(n),
                        className="nav-log-as-times"),
                html.Td(n.get("text") or "",
                        className="nav-log-notam-text"),
            ])

        notam_block = html.Div(
            className="nav-log-section",
            children=[
                html.H4(f"NOTAMs Along Route — {len(notams)} relevant",
                        className="nav-log-section-title"),
                html.Table(className="nav-log-as-table", children=[
                    html.Thead(html.Tr([
                        html.Th("Type"),
                        html.Th("ID"),
                        html.Th("Dist"),
                        html.Th("Alt Band"),
                        html.Th("Active"),
                        html.Th("Text"),
                    ])),
                    html.Tbody([_notam_row(n) for n in notams]),
                ]),
            ],
        )

    # Altitude profile chart — was previously auto-displayed under the
    # map. Moved into the modal so the below-strip stays minimal.
    profile_block = None
    if profile_chart is not None:
        profile_block = html.Div(
            className="nav-log-profile-block",
            children=[
                html.Div("Altitude Profile",
                         className="nav-log-section-title"),
                profile_chart,
            ],
        )

    # === VFR Checkpoints block (D2-6) ===
    # FAA-style checkpoint table — Fix · Type · Cumulative NM ·
    # Leg NM · MC · ETE · Glide margin · Nearest divert · Notes.
    # Pilot fills in ATE/ATA/Fuel by hand (standard pilotage rote).
    checkpoint_block = None
    if checkpoints:
        cp_header = html.Tr([
            html.Th("#"),
            html.Th("Fix"),
            html.Th("Type"),
            html.Th("Cum NM"),
            html.Th("Leg NM"),
            html.Th("MC"),
            html.Th("ETE"),
            html.Th("Glide"),
            html.Th("Divert"),
            html.Th("Notes"),
        ], className="navlog-cp-header-row")
        cp_rows = [cp_header]
        for i, cp in enumerate(checkpoints, 1):
            margin = cp.get("glide_margin_ft", 0)
            margin_cls = (
                "navlog-cp-glide-good" if margin > 500
                else "navlog-cp-glide-marginal" if margin > 0
                else "navlog-cp-glide-bad"
            )
            cp_rows.append(html.Tr([
                html.Td(str(i)),
                html.Td(cp.get("ident", "?"),
                         className="navlog-cp-ident"),
                html.Td(cp.get("kind", "?").replace("_", " ")),
                html.Td(f"{cp.get('cumulative_nm', 0):.1f}"),
                html.Td(f"{cp.get('leg_dist_nm', 0):.1f}"),
                html.Td(f"{cp.get('magnetic_bearing', 0):03.0f}°"),
                html.Td(f"{cp.get('ete_min', 0):.1f}m"),
                html.Td(f"{margin:+.0f} ft", className=margin_cls),
                html.Td(
                    f"{cp.get('nearest_divert_id', '—')} "
                    f"({cp.get('nearest_divert_nm', 0):.0f} NM)"
                ),
                html.Td(cp.get("notes", ""),
                         className="navlog-cp-notes"),
            ]))
        checkpoint_block = html.Div([
            html.Div("VFR Checkpoints (FAA-H-8083-25B Ch. 16)",
                      className="nav-log-section-title"),
            html.Table(cp_rows, className="navlog-cp-table"),
            html.Div(
                "Per AC 90-66B: announce position on CTAF no less "
                "than 10 NM out. Verify each checkpoint by pilotage "
                "+ time/dist DR.",
                className="nav-log-section-note",
            ),
        ], className="nav-log-section nav-log-checkpoints")

    return html.Div(className="nav-log-document", children=[
        header_strip,
        form_row,
        foot_strip,
        profile_block,
        checkpoint_block,
        airspace_block,
        notam_block,
        eo_block,
        html.Div("Generated by TallyAero Maneuver Overlay · "
                 + datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
                 className="nav-log-footer"),
    ])


def _format_notam_alt(n: dict) -> str:
    """Compact NOTAM altitude string. Falls back to '—' when the
    NOTAM has no altitude info (most obstruction / GEN notams)."""
    floor = n.get("floor_ft")
    ceiling = n.get("ceiling_ft")
    if floor is None and ceiling is None:
        return "—"
    floor_s = _format_alt(floor) if floor is not None else "—"
    ceil_s = _format_alt(ceiling) if ceiling is not None else "—"
    return f"{floor_s} → {ceil_s}"


def _format_notam_window(n: dict) -> str:
    """Active-window summary. 'Continuous' when no end. ISO timestamps
    are shortened to YYYY-MM-DD HH:MM Z for tooltip-tight display."""
    def _short(s: str | None) -> str:
        if not s:
            return "—"
        # Strip seconds + zone marker if present
        s = s.replace("T", " ")
        if s.endswith("Z"):
            s = s[:-1]
        if "+" in s:
            s = s.split("+", 1)[0]
        return s[:16] + "Z"

    start = n.get("start_utc")
    end = n.get("end_utc")
    if start and end:
        return f"{_short(start)} → {_short(end)}"
    if start and not end:
        return f"{_short(start)} → continuous"
    if not start and end:
        return f"until {_short(end)}"
    return "continuous"


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
            # GPS waypoints have value of form "GPS:lat,lon"; render
            # them with a friendly pill label without going through
            # airport_data.
            wp = resolve_any(v, airport_data=airport_data,
                             navaid_data=navaid_data, fix_data=fix_data)
            if wp is not None and wp.kind == "gps":
                kept.append({
                    "label": f"GPS {wp.lat:.2f},{wp.lon:.2f}",
                    "value": wp.ident,
                    "title": wp.name,
                })
                continue
            ap = resolve_waypoint(airport_data, v)
            if ap:
                kept.append({
                    "label": ap.get("id") or v,
                    "value": ap.get("id") or v,
                    "title": airport_label(ap),
                })
                continue
            # NAVAID / FIX fallback — ident lookup against the runtime
            # data. We use NAVAID:/FIX: prefixed values to avoid collision
            # with a same-letter airport (e.g. SAV the IATA vs SAV the VOR).
            if wp is not None and wp.kind in ("vor", "ndb", "fix"):
                prefix = "FIX" if wp.kind == "fix" else "NAV"
                kept.append({
                    "label": f"{prefix} {wp.ident}",
                    "value": v,
                    "title": wp.name or wp.ident,
                })
        # Also try parsing the typed query as a GPS coord — if it
        # parses, surface a "GPS lat,lon" option the user can pick.
        if query and len(query.strip()) >= 4:
            parsed = parse_gps_coordinate(query)
            if parsed is not None:
                lat, lon = parsed
                ident = format_gps_ident(lat, lon)
                if not any(o["value"] == ident for o in kept):
                    kept.append({
                        "label": format_gps_display(lat, lon),
                        "value": ident,
                        "title": f"GPS waypoint at {lat:.4f}, {lon:.4f}",
                    })
        if not query or len(query.strip()) < 2:
            return kept
        # Multi-type search: airports first (highest tier), then NAVAIDs,
        # then fixes. Values are prefixed with NAV:/FIX: for non-airports
        # so the resolver can route them correctly even when an airport
        # shares the same ident.
        hits = search_airports(airport_data, query, limit=12)
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
        for nv in search_navaids(navaid_data, query, limit=8):
            wid = f"NAV:{nv['ident']}"
            if wid not in existing_ids:
                kept.append({
                    "label": navaid_label(nv),
                    "value": wid,
                    "title": navaid_label(nv),
                })
                existing_ids.add(wid)
        for fx in search_fixes(fix_data, query, limit=6):
            wid = f"FIX:{fx['ident']}"
            if wid not in existing_ids:
                kept.append({
                    "label": fix_label(fx),
                    "value": wid,
                    "title": fix_label(fx),
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

    # === Apply suggested altitude (terrain conflict button) ===
    @app.callback(
        Output("route-cruise-alt", "value"),
        Output("compute-route-btn", "n_clicks", allow_duplicate=True),
        Input("route-apply-suggested-alt", "n_clicks"),
        State("route-cruise-alt", "value"),
        State("compute-route-btn", "n_clicks"),
        State("route-result-store", "data"),
        prevent_initial_call=True,
    )
    def apply_suggested_altitude(n_clicks, current_alt, current_compute, store):
        if not n_clicks or not store:
            raise PreventUpdate
        suggested = (store or {}).get("suggested_alt_ft")
        if not suggested:
            raise PreventUpdate
        return suggested, (current_compute or 0) + 1

    # === Click-to-build: map click appends to route-waypoints ===
    @app.callback(
        Output("route-waypoints", "value", allow_duplicate=True),
        Output("route-waypoints", "options", allow_duplicate=True),
        Input("map", "clickData"),
        State("route-click-build-mode", "value"),
        State("route-waypoints", "value"),
        State("route-waypoints", "options"),
        prevent_initial_call=True,
    )
    def click_to_add_waypoint(click_data, click_mode, current_value, current_options):
        # Guard: only act when click-build mode is on AND we have a
        # clickData payload with lat/lng.
        if not click_mode or "on" not in click_mode:
            raise PreventUpdate
        if not click_data or "latlng" not in click_data:
            raise PreventUpdate
        latlng = click_data.get("latlng") or {}
        lat = latlng.get("lat")
        lon = latlng.get("lng")
        if lat is None or lon is None:
            raise PreventUpdate

        # Snap to nearest waypoint within 3 NM. Airports preferred,
        # then NAVAIDs (small tie-break penalty), then fixes; falls
        # through to a GPS waypoint when nothing is close enough.
        hit = nearest_waypoint_within(
            lat=lat, lon=lon, max_nm=3.0,
            airport_data=airport_data,
            navaid_data=navaid_data,
            fix_data=fix_data,
        )
        if hit is not None:
            kind, rec = hit
            if kind == "airport":
                new_value = rec.get("id")
                new_option = {
                    "label": new_value,
                    "value": new_value,
                    "title": airport_label(rec),
                }
            elif kind == "navaid":
                new_value = f"NAV:{rec['ident']}"
                new_option = {
                    "label": f"NAV {rec['ident']}",
                    "value": new_value,
                    "title": navaid_label(rec),
                }
            else:  # fix
                new_value = f"FIX:{rec['ident']}"
                new_option = {
                    "label": f"FIX {rec['ident']}",
                    "value": new_value,
                    "title": fix_label(rec),
                }
        else:
            new_value = format_gps_ident(lat, lon)
            new_option = {
                "label": f"GPS {lat:.2f},{lon:.2f}",
                "value": new_value,
                "title": format_gps_display(lat, lon),
            }

        new_values = list(current_value or [])
        if new_value in new_values:
            # Already in the route — no-op to avoid duplicates
            raise PreventUpdate
        new_values.append(new_value)

        existing_opts = list(current_options or [])
        if not any(o.get("value") == new_value for o in existing_opts):
            existing_opts.append(new_option)

        return new_values, existing_opts

    # === Open / close the Nav Log modal ===
    @app.callback(
        Output("nav-log-modal", "is_open"),
        Input("nav-log-open-btn", "n_clicks"),
        Input("nav-log-close-btn", "n_clicks"),
        State("nav-log-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_nav_log(open_clicks, close_clicks, is_open):
        """Open on real button click only.

        Pre-fix: the modal popped open every time the user pressed
        Compute Route. The "View Nav Log" button lives INSIDE the
        below-strip, which the compute callback re-renders. Dash sees
        a fresh button component each time and fires the callback
        with `n_clicks=0`, which the old `if trigger == "...-open-btn"`
        check would treat as a real click and open the modal.

        Fix: require a TRUTHY n_clicks for the trigger to count —
        a freshly-mounted button starts at 0, which is falsy.
        `prevent_initial_call=True` already handles page load.
        """
        trigger = ctx.triggered_id
        if trigger == "nav-log-open-btn" and open_clicks:
            return True
        if trigger == "nav-log-close-btn" and close_clicks:
            return False
        return is_open

    # === Collapse / expand the below-strip ===
    # Pure clientside — toggles `.collapsed` on the wrapper div and
    # flips the chevron glyph. State persists in
    # `route-below-collapsed-store` so the bar reopens to the user's
    # last preference after route recompute / page reload.
    app.clientside_callback(
        """
        function(n, current) {
            const wrap = document.getElementById('route-below-strip-wrap');
            if (!wrap) return [window.dash_clientside.no_update,
                                window.dash_clientside.no_update];
            const next = !current;
            wrap.classList.toggle('collapsed', next);
            return [next, next ? '▲ Info' : '▼ Info'];
        }
        """,
        Output("route-below-collapsed-store", "data"),
        Output("route-below-collapse-btn", "children"),
        Input("route-below-collapse-btn", "n_clicks"),
        State("route-below-collapsed-store", "data"),
        prevent_initial_call=True,
    )
    # Restore the collapsed class on page load if the user previously
    # collapsed it (state persists in localStorage via the Store).
    app.clientside_callback(
        """
        function(stored) {
            const wrap = document.getElementById('route-below-strip-wrap');
            if (!wrap) return window.dash_clientside.no_update;
            if (stored) {
                wrap.classList.add('collapsed');
                return '▲ Info';
            }
            wrap.classList.remove('collapsed');
            return '▼ Info';
        }
        """,
        Output("route-below-collapse-btn", "children", allow_duplicate=True),
        Input("route-below-collapsed-store", "data"),
        prevent_initial_call="initial_duplicate",
    )

    # === Print the Nav Log (clientside — fires window.print) ===
    # Writes to a sink Store rather than echoing back to n_clicks so
    # the Output graph stays unambiguous. Defer print by one frame so
    # the modal repaints fully before the print dialog locks the page.
    app.clientside_callback(
        """
        function(n) {
            if (n && n > 0) {
                setTimeout(function(){ window.print(); }, 50);
            }
            return Date.now();
        }
        """,
        Output("nav-log-print-sink", "data"),
        Input("nav-log-print-btn", "n_clicks"),
        prevent_initial_call=True,
    )

    # === Pre-compute terrain heads-up on Cruise Alt typing ===
    # Quick check that does NOT run the full pipeline. Samples the
    # great-circle every ~10 NM, looks up DEM elevation, and flags if
    # the typed cruise altitude is within 1000 ft of peak terrain.
    # Debounced via dcc.Input(debounce=True) so it fires on blur/Enter,
    # not on every keystroke.
    @app.callback(
        Output("route-cruise-alt-check", "children"),
        Output("route-cruise-alt-check", "className"),
        Input("route-cruise-alt", "value"),
        Input("route-waypoints", "value"),
        prevent_initial_call=False,
    )
    def quick_terrain_check(cruise_alt, waypoint_ids):
        if (not waypoint_ids or len(waypoint_ids) < 2
                or cruise_alt in (None, "")):
            return "", "shelf-chip-quiet"
        try:
            cruise_ft = float(cruise_alt)
        except (TypeError, ValueError):
            return "", "shelf-chip-quiet"

        points: list[tuple[float, float]] = []
        for wid in waypoint_ids:
            wp = resolve_any(wid, airport_data=airport_data,
                             navaid_data=navaid_data, fix_data=fix_data)
            if wp and wp.lat is not None and wp.lon is not None:
                points.append((wp.lat, wp.lon))
        if len(points) < 2:
            return "", "shelf-chip-quiet"

        samples: list[tuple[float, float]] = []
        for a, b in zip(points[:-1], points[1:]):
            samples.extend(sample_route_points(
                a[0], a[1], b[0], b[1], spacing_nm=10.0,
            ))
        if not samples:
            return "", "shelf-chip-quiet"

        peak_ft = 0.0
        for lat, lon in samples:
            try:
                elev_m = _terrain_elevation_m(lat, lon)
                if elev_m is None or elev_m != elev_m:   # NaN
                    continue
                ft = elev_m * FT_PER_M
                if ft > peak_ft:
                    peak_ft = ft
            except Exception:
                continue

        if peak_ft <= 0:
            return "", "shelf-chip-quiet"

        buffer_ft = 1000.0
        if cruise_ft < peak_ft + buffer_ft:
            return (f"peak {peak_ft:.0f} ft — bump cruise",
                    "shelf-chip-warn")
        margin = cruise_ft - peak_ft
        return (f"{margin:.0f} ft above peak",
                "shelf-chip-ok")

    # === Pre-compute waypoint markers (immediate visual feedback) ===
    @app.callback(
        Output("route-pending-markers", "children"),
        Input("route-waypoints", "value"),
        prevent_initial_call=True,
    )
    def render_pending_waypoint_markers(waypoint_ids):
        """As soon as the route-waypoints list changes (click-to-add,
        typed entry, removed pill), drop dots on the map for each
        current waypoint. These are independent of Compute Route — the
        user sees their work taking shape immediately.

        Cleared by the Compute callback (which redraws fuller markers
        in route-layer) and by Clear."""
        if not waypoint_ids:
            return []
        markers = []
        positions: list[list[float]] = []
        for i, wid in enumerate(waypoint_ids):
            wp = resolve_any(wid, airport_data=airport_data,
                             navaid_data=navaid_data, fix_data=fix_data)
            if wp is None or wp.lat is None or wp.lon is None:
                continue
            positions.append([wp.lat, wp.lon])
            if i == 0:
                color, fill = "#15803d", "#22c55e"   # origin green
            elif i == len(waypoint_ids) - 1:
                color, fill = "#991b1b", "#ef4444"   # dest red
            else:
                color, fill = "#b45309", "#f59e0b"   # mid amber
            tip = (f"{wp.ident}" if wp.kind != "gps"
                   else f"GPS {wp.lat:.4f}, {wp.lon:.4f}")
            markers.append(dl.CircleMarker(
                center=[wp.lat, wp.lon],
                radius=5, weight=2,
                color=color, fillColor=fill, fillOpacity=0.95,
                children=[dl.Tooltip(tip)],
            ))
        # Preview polyline connecting the waypoints in click order.
        # Compute Route replaces this with the full great-circle route
        # rendering in route-layer.
        if len(positions) >= 2:
            markers.insert(0, dl.Polyline(
                positions=positions,
                color="#0d59f2", weight=2, opacity=0.75,
                dashArray="6, 6",
            ))
        return markers

    # === Compute route + render banner + below-strip + nav log + map ===
    @app.callback(
        Output("route-top-banner", "children"),
        Output("route-below-strip", "children"),
        Output("nav-log-content", "children"),
        Output("route-layer", "children"),
        Output("map", "viewport"),
        Output("route-result-store", "data"),
        Input("compute-route-btn", "n_clicks"),
        Input("route-clear-btn", "n_clicks"),
        # Phase 8c-polish: these three pills auto-recompute when
        # toggled (but only after the user has clicked Compute at
        # least once, so we don't fire on initial pageload).
        Input("route-show-corridor", "value"),
        Input("route-use-live-winds", "value"),
        Input("route-show-landable", "value"),
        # Read these as State (not Input) — we want them to influence
        # the destination-arrival rendering, but changes shouldn't
        # trigger a full route rebuild. The pattern callback owns the
        # interactive updates on these.
        State("route-show-destination-pattern", "data"),
        State("route-runway-select", "data"),
        # Checkpoints master toggle: OFF = direct great-circle (no
        # bend, no checkpoint markers, no coverage chip). ON = run the
        # VFR checkpoint picker, bend the polyline through them, and
        # compute the moat coverage metric. INPUT so toggling auto-
        # recomputes the route (consistent with the other pills:
        # Corridor / Live winds / Landable).
        Input("route-show-checkpoints", "data"),
        # User drag-edits to specific checkpoints — Input so dragging
        # a marker auto-recomputes the bent route through the new
        # position.
        Input("route-checkpoint-edits", "data"),
        State("route-waypoints", "value"),
        State("route-cruise-alt", "value"),
        State("route-tas", "value"),
        State("route-cruise-ias", "value"),
        State("route-glide-ratio", "value"),
        State("route-glide-ias", "value"),
        State("route-climb-ias", "value"),
        State("route-engine-out-mode", "value"),
        State("route-slope-threshold", "value"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        State("fuel-load", "value"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        prevent_initial_call=True,
    )
    def compute_and_render(compute_clicks, clear_clicks,
                          corridor_show, use_live_winds, show_landable,
                          show_dest_pattern, runway_override,
                          show_checkpoints, checkpoint_edits,
                          waypoint_ids, cruise_alt, tas, cruise_ias,
                          glide_ratio, glide_ias, climb_ias,
                          engine_out_mode,
                          slope_threshold,
                          wind_dir, wind_speed, aircraft_name,
                          fuel_load_gal,
                          env_oat_c, env_altimeter_inhg):
        trigger = ctx.triggered_id
        if trigger == "route-clear-btn":
            return _empty_clear()

        # Auto-recompute on a pill toggle ONLY if the user has already
        # clicked Compute once (otherwise initial-load pill defaults
        # would fire a no-route compute). The Compute button is still
        # the source of truth for "kick off a route from scratch".
        pill_ids = {"route-show-corridor",
                    "route-use-live-winds",
                    "route-show-landable",
                    "route-show-checkpoints"}
        if trigger in pill_ids:
            if not compute_clicks:
                raise PreventUpdate
            # Fall through to the compute body — same path as Compute.
        elif not compute_clicks:
            raise PreventUpdate

        if not waypoint_ids or len(waypoint_ids) < 2:
            return (html.Div("Add at least two waypoints (origin → destination).",
                             className="route-summary-error"),
                    None, None, no_update, no_update, no_update)

        try:
            cruise_alt = float(cruise_alt) if cruise_alt else 5500.0
            tas = float(tas) if tas else 110.0
            glide_ratio = float(glide_ratio) if glide_ratio else 9.0
            glide_ias = float(glide_ias) if glide_ias else 75.0
            climb_ias = float(climb_ias) if climb_ias else 76.0
        except (TypeError, ValueError):
            return (html.Div("Numeric fields must be numbers.",
                             className="route-summary-error"),
                    None, None, no_update, no_update, no_update)

        # Aircraft-derived inputs for the climb model: Vy + Vno + class
        # baseline climb rate. Falls back to typical-single defaults if
        # the user hasn't selected an aircraft.
        ac = aircraft_data.get(aircraft_name) if aircraft_name else None
        vy_kt = (ac.get("Vy") if ac else None) or 76.0
        vno_kt = (ac.get("Vno") if ac else None) or 129.0
        baseline_climb = class_baseline_climb_rate(ac) if ac else 700.0
        derived_climb_rate = _climb_rate_fpm(
            climb_ias, vy_kt, vno_kt, baseline_climb)

        # Resolve every waypoint. GPS coordinates resolve directly;
        # other tokens go through airport_search. Returned Waypoint is
        # converted to the legacy airport-dict shape downstream code
        # expects (lat / lon / elevation_ft / id / name).
        #
        # GPS click-to-add waypoints have no published elevation, so
        # the dataclass defaults elevation_ft to None → 0. That breaks
        # the flight profile (which uses field_dep_ft / field_dest_ft
        # as climb-from / descend-to anchors) and inflates AGL stats.
        # Look up the terrain elevation via the same DEM the corridor
        # uses so a GPS waypoint carries the same "ground elevation
        # MSL" semantics as an airport waypoint.
        waypoints: list[dict] = []
        for wid in waypoint_ids:
            wp = resolve_any(wid, airport_data=airport_data,
                             navaid_data=navaid_data, fix_data=fix_data)
            if wp is None:
                return (html.Div(f"Waypoint '{wid}' not found.",
                                 className="route-summary-error"),
                        None, None, no_update, no_update, no_update)
            d = wp.to_dict_min()
            if wp.kind == "gps" and (d.get("elevation_ft") in (None, 0, 0.0)):
                try:
                    elev_m = _terrain_elevation_m(wp.lat, wp.lon)
                    if elev_m is not None and not (elev_m != elev_m):  # NaN check
                        d["elevation_ft"] = round(elev_m * FT_PER_M)
                except Exception:
                    pass
            waypoints.append(d)

        # Endpoints must be airports — 99% of GA flying is airport-to-
        # airport, and this constraint avoids the messy "what's the
        # field elevation of a GPS click" question. Intermediate GPS
        # turning points are still fine.
        if waypoints[0].get("kind") != "airport":
            return (html.Div(
                        "Origin must be an airport (ICAO/IATA/name). "
                        "GPS points can only be used as intermediate "
                        "waypoints.",
                        className="route-summary-error"),
                    None, None, no_update, no_update, no_update)
        if waypoints[-1].get("kind") != "airport":
            return (html.Div(
                        "Destination must be an airport (ICAO/IATA/name). "
                        "GPS points can only be used as intermediate "
                        "waypoints.",
                        className="route-summary-error"),
                    None, None, no_update, no_update, no_update)

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

        # ═══════════════════════════════════════════════════════════════
        # D2-5g: Checkpoint generation + BENT-ROUTE SWAP
        # ═══════════════════════════════════════════════════════════════
        # When checkpoints are ON, we want EVERY downstream computation
        # (corridor, landable mask, divert coverage, airspace crossings,
        # NOTAMs, terrain status, engine-out drill) to operate on the
        # ACTUAL flown route — the bent path through the chosen
        # checkpoints — NOT the straight-line great-circle.
        #
        # Strategy: generate checkpoints + build the bent sample list
        # NOW (before the corridor calc runs), then REPLACE all_samples
        # + all_alts with the bent versions. Every subsequent consumer
        # of all_samples picks up the bent path automatically.
        try:
            cp_on_early = bool(show_checkpoints
                                 and "on" in show_checkpoints)
        except (TypeError, ValueError):
            cp_on_early = False

        checkpoints_payload: list[dict] = []
        landmarks_payload: list[dict] = []
        bent_chain: list[dict] = []
        bent_samples_draw: list = []

        if cp_on_early:
            try:
                from core.checkpoints import (
                    suggest_checkpoints as _suggest_checkpoints,
                )
                from core.data_loader import navaid_data as _navaid_data
                from core.data_loader import fix_data as _fix_data
                from core.landmarks_osm import (
                    fetch_populated_places as _fetch_pop,
                    fetch_river_crossings as _fetch_rivers,
                )
                try:
                    slats = [w["lat"] for w in waypoints]
                    slons = [w["lon"] for w in waypoints]
                    pad = 0.25
                    landmarks_payload.extend(_fetch_pop(
                        lat_min=min(slats) - pad, lat_max=max(slats) + pad,
                        lon_min=min(slons) - pad, lon_max=max(slons) + pad,
                        min_population=5000,
                    ))
                    for a_wp, b_wp in zip(waypoints[:-1], waypoints[1:]):
                        la = (float(a_wp["lat"]), float(a_wp["lon"]))
                        lb = (float(b_wp["lat"]), float(b_wp["lon"]))
                        lat_lo, lat_hi = sorted([la[0], lb[0]])
                        lon_lo, lon_hi = sorted([la[1], lb[1]])
                        landmarks_payload.extend(_fetch_rivers(
                            lat_min=lat_lo - 0.05, lat_max=lat_hi + 0.05,
                            lon_min=lon_lo - 0.05, lon_max=lon_hi + 0.05,
                            leg_a=la, leg_b=lb,
                        ))
                except Exception:
                    landmarks_payload = []

                checkpoints_payload = _suggest_checkpoints(
                    waypoints=waypoints,
                    cruise_alt_msl_ft=float(cruise_alt or 5500),
                    tas_kt=float(tas or 110),
                    glide_ratio=float(glide_ratio or 9.0),
                    airports=airport_data,
                    navaids=_navaid_data,
                    fixes=_fix_data,
                    landmarks=landmarks_payload,
                )
                # Apply user click-to-place edits (override matching
                # idents' lat/lon with the user-clicked position).
                if checkpoint_edits and isinstance(checkpoint_edits, dict):
                    for cp in checkpoints_payload:
                        edit = checkpoint_edits.get(cp.get("ident"))
                        if edit:
                            cp["lat"] = float(edit["lat"])
                            cp["lon"] = float(edit["lon"])
                            cp["notes"] = (cp.get("notes", "")
                                            + " · user-positioned")
            except Exception:
                checkpoints_payload = []
                landmarks_payload = []

            # Build bent chain — waypoints interleaved with checkpoints
            # in the leg they belong to. For a 2-waypoint route:
            #     origin → cp1 → cp2 → ... → destination
            try:
                for li in range(len(waypoints) - 1):
                    bent_chain.append({"lat": float(waypoints[li]["lat"]),
                                        "lon": float(waypoints[li]["lon"])})
                    for cp in checkpoints_payload:
                        if cp.get("leg_idx") == li:
                            bent_chain.append({"lat": float(cp["lat"]),
                                                "lon": float(cp["lon"])})
                bent_chain.append({"lat": float(waypoints[-1]["lat"]),
                                    "lon": float(waypoints[-1]["lon"])})

                # Sample each pair at ~2 NM spacing.
                from core.corridor import sample_route_points as _sample_rp
                for a_pt, b_pt in zip(bent_chain[:-1], bent_chain[1:]):
                    seg_samples = _sample_rp(
                        a_pt["lat"], a_pt["lon"],
                        b_pt["lat"], b_pt["lon"], spacing_nm=2.0,
                    )
                    if not bent_samples_draw:
                        bent_samples_draw.extend(seg_samples)
                    else:
                        bent_samples_draw.extend(seg_samples[1:])
            except Exception:
                bent_samples_draw = []

        # === THE SWAP ===
        # When checkpoints are ON AND we have a real bent path (more
        # than just origin+destination), REPLACE all_samples + all_alts
        # AND per_leg_samples so every downstream consumer (corridor /
        # landable / divert / airspace / NOTAMs / terrain status /
        # profile / engine-out drill / coverage chip) operates on the
        # bent route. per_leg_samples is used by the corridor builder
        # and wind-list slicing; we collapse the bent path into a
        # single "leg" since the corridor envelope is a glide-reach
        # union that doesn't care about user-leg boundaries.
        if (cp_on_early and checkpoints_payload
                and bent_samples_draw and len(bent_chain) > 2):
            all_samples = list(bent_samples_draw)
            # Per-sample alts: cruise for all bent samples. The TOC/TOD
            # profile is computed against route distance which differs
            # for bent vs straight; for the corridor + reachability
            # math, cruise alt is what we care about (worst case for
            # divert reach). The profile chart still uses the original
            # all_alts curve since climb/descent timing is unchanged.
            all_alts = [float(cruise_alt or 5500)
                         for _ in bent_samples_draw]
            # Single combined per-leg entry: keeps the wind-slice +
            # corridor builder zip alignment correct (both expect
            # per_leg_samples to be parallel with user-waypoint pairs,
            # and we'll feed a single-pair zip below).
            per_leg_samples = [(list(bent_samples_draw),
                                  list(all_alts), 2.0)]

        # ─── Parallel network fetches (Phase 8c-polish) ─────────────────
        # Cold-cache compute was bottlenecked by three serial network
        # calls — live winds (Open-Meteo), OSM Overpass land cover, and
        # the DEM tile prefetch for the corridor. None depends on the
        # others' results, so we kick them off concurrently and wait
        # for all to land before proceeding. Cuts cold-cache wall time
        # from ~60s to ~25s on a typical 3-leg route.
        from concurrent.futures import ThreadPoolExecutor

        # Sample list for the corridor DEM prefetch — needs to happen
        # in this scope so it's available to the prefetch future.
        _field_elev_pre = max((w.get("elevation_ft") or 0.0) for w in waypoints)
        _max_reach_nm_pre = max(
            2.0, (cruise_alt - _field_elev_pre) * glide_ratio / 6076.115)
        _prefetch_samples: list[tuple[float, float]] = []
        for _a, _b in zip(waypoints[:-1], waypoints[1:]):
            _prefetch_samples.extend(sample_route_points(
                _a["lat"], _a["lon"], _b["lat"], _b["lon"],
                spacing_nm=max(2.0, _max_reach_nm_pre),
            ))

        # Landing-options bbox (only matters if Landable is on).
        want_landable_render = bool(
            show_landable and "on" in show_landable)
        _want_live_winds = bool(use_live_winds and "on" in use_live_winds)

        wind_source = "manual"
        all_winds: list[tuple[float, float]] | None = None
        landing_opts: dict | None = None

        # Landable-mask bbox — also used by the wider DEM prefetch when
        # Landable is on, so the slope grid doesn't sample cold tiles
        # and end up NaN-mostly on the first compute.
        _slats = [w["lat"] for w in waypoints]
        _slons = [w["lon"] for w in waypoints]
        _bbox_pad = 0.1
        _mask_lat_min = min(_slats) - _bbox_pad
        _mask_lat_max = max(_slats) + _bbox_pad
        _mask_lon_min = min(_slons) - _bbox_pad
        _mask_lon_max = max(_slons) + _bbox_pad

        with ThreadPoolExecutor(max_workers=4) as _pool:
            fut_winds = (_pool.submit(fetch_winds_aloft, all_samples, all_alts)
                         if _want_live_winds else None)
            fut_landing = None
            fut_mask_dem = None
            if want_landable_render:
                fut_landing = _pool.submit(
                    fetch_landing_options,
                    _mask_lat_min, _mask_lon_min,
                    _mask_lat_max, _mask_lon_max,
                )
                # Warm DEM tiles for the FULL mask bbox so the slope
                # grid sampled by build_landable_mask_overlay has every
                # tile available. Without this, the first compute saw
                # NaN holes in the slope grid → empty landable mask;
                # second compute had the tiles warm and rendered fine.
                fut_mask_dem = _pool.submit(
                    prefetch_bbox,
                    _mask_lat_min, _mask_lon_min,
                    _mask_lat_max, _mask_lon_max,
                )
            fut_prefetch = _pool.submit(
                prefetch_corridor, _prefetch_samples,
                _max_reach_nm_pre,
            )

            if fut_winds is not None:
                fetched = fut_winds.result()
                if fetched is not None and len(fetched) == len(all_samples):
                    all_winds = fetched
                    wind_source = "live"
                else:
                    wind_source = "live-unavailable"
            if fut_landing is not None:
                landing_opts = fut_landing.result()
            fut_prefetch.result()    # block until corridor DEM warm
            if fut_mask_dem is not None:
                fut_mask_dem.result()   # block until mask bbox DEM warm

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
        for leg_idx, (a, b) in enumerate(zip(waypoints[:-1], waypoints[1:])):
            magvar = magvar_west_positive(a["lat"], a["lon"], cruise_alt)
            r = compute_route_segment(
                origin_lat=a["lat"], origin_lon=a["lon"],
                dest_lat=b["lat"], dest_lon=b["lon"],
                tas_kt=tas, wind_dir_deg=wd, wind_speed_kt=ws,
                magvar_deg=magvar,
            )
            # Leg-mid wind for HW/TW summary: pick the middle sample
            # from per_leg_winds when available, else use the scalar.
            leg_winds = per_leg_winds[leg_idx] if leg_idx < len(per_leg_winds) else None
            if leg_winds:
                mid = leg_winds[len(leg_winds) // 2]
                leg_wind_dir, leg_wind_speed = mid
            else:
                leg_wind_dir, leg_wind_speed = wd, ws
            hw_tw, cross = wind_components(
                r.true_course_deg, leg_wind_dir, leg_wind_speed)
            wind_summary = (
                f"{leg_wind_dir:03.0f}/{leg_wind_speed:.0f}kt · "
                f"{format_wind_components(hw_tw, cross)}"
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
                "wind_dir_deg": round(leg_wind_dir, 0),
                "wind_speed_kt": round(leg_wind_speed, 1),
                "headtail_kt": round(hw_tw, 1),
                "crosswind_kt": round(cross, 1),
                "wind_summary": wind_summary,
            })

        layer: list = []

        # landing_opts and want_landable_render were populated by the
        # parallel fetch block above. corridor DEM is already warm.

        # ─── Multi-leg corridor (under the polyline) ───────────────────
        # The shapely corridor_shape is the master clip mask for every
        # other overlay (slope heatmap, suitable-land polygons), so we
        # always compute it. The visual Polygon render is the only
        # thing the Corridor toggle gates.
        corridor_meta_agg = None
        corridor_shape = None
        corridor_visible = bool(corridor_show and "show" in corridor_show)
        if waypoints and len(waypoints) >= 2:
            # field_elev + max_reach_nm match the values used by the
            # parallel prefetch above; DEM tiles are already warm.
            field_elev = _field_elev_pre
            max_reach_nm = _max_reach_nm_pre

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
                    # D2-5g: pass the bent samples so the corridor
                    # envelope hugs the actual flown path through
                    # checkpoints, not the straight-line between
                    # origin and destination.
                    path_samples=leg_samples,
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

            # Cross-leg union: each leg's compute_route_corridor returns
            # rings that are leg-locally unioned but not unioned across
            # leg boundaries. For short legs (1-5 NM) the per-leg rings
            # look like distinct circles even when they overlap visually.
            # Reconstruct shapely polygons and unary_union them so the
            # final corridor is ONE continuous shape.
            from shapely.geometry import Polygon as _ShPolygon
            from shapely.ops import unary_union as _unary_union
            poly_objs = []
            for ring in agg_rings:
                if len(ring) >= 4:
                    # ring is [[lat, lon], ...]; shapely wants (lon, lat)
                    p = _ShPolygon([(lon, lat) for lat, lon in ring])
                    if not p.is_valid:
                        p = p.buffer(0)
                    if p.is_valid and not p.is_empty:
                        poly_objs.append(p)
            if poly_objs:
                merged = _unary_union(poly_objs)
                corridor_shape = merged   # master clip mask for overlays
                geoms = ([merged] if isinstance(merged, _ShPolygon)
                         else list(merged.geoms))
                agg_rings = []
                for g in geoms:
                    if isinstance(g, _ShPolygon) and not g.is_empty:
                        agg_rings.append(
                            [[lat, lon] for lon, lat in g.exterior.coords])

            # Render glide corridor only when the engine-out mode
            # asks for it (glide or both). For ME aircraft in pure
            # SE mode the glide polygons are suppressed so the user
            # sees only the powered-reach footprint.
            ac_for_me = aircraft_data.get(aircraft_name) if aircraft_name else None
            ac_is_me = ac_for_me is not None and is_multi_engine(ac_for_me)
            mode = (engine_out_mode or "both").lower()
            show_glide = (not ac_is_me) or mode in ("glide", "both")
            if corridor_visible and show_glide:
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

            # ─── Multi-engine: powered SE corridor (purple) ──────────
            # Two corrections vs first cut: (1) the SE reach is capped
            # at 60 min after failure (operational reality — no pilot
            # flies hours single-engine), (2) fuel decreases along the
            # route from the actual loaded amount, using twin-engine
            # cruise burn ≈ 2× SE burn as the depletion rate.
            se_meta = None
            if ac_is_me and has_se_performance_data(ac_for_me):
                show_se = mode in ("se", "both")
                # Actual fuel loaded (from sidebar), capped at tank
                # capacity. fuel-load slider is in gallons (0-50 ish
                # range default; pilot can override).
                fuel_cap = ac_for_me.get("fuel_capacity_gal") or 0.0
                starting_fuel_gal = min(fuel_cap, float(fuel_load_gal or 0))
                if starting_fuel_gal <= 0:
                    # If pilot didn't set fuel, assume full tanks
                    starting_fuel_gal = fuel_cap
                if show_se and starting_fuel_gal > 0:
                    # Per-sample fuel = starting - cumulative twin
                    # cruise burn to this sample. Twin burn ≈ 2×
                    # SE burn. Distance to sample / cruise GS = time.
                    se_fuel_gph = float(
                        ac_for_me["single_engine_limits"]["fuel_burn_gph"])
                    twin_burn_gph = 2.0 * se_fuel_gph
                    cruise_kt = float(
                        ac_for_me["single_engine_limits"]["cruise_kt"])
                    cum_dist = 0.0
                    sample_fuels = [starting_fuel_gal]
                    for i in range(1, len(all_samples)):
                        prev = all_samples[i - 1]
                        cur = all_samples[i]
                        cum_dist += haversine_nm(*prev, *cur)
                        hours = cum_dist / max(50.0, tas)
                        used = hours * twin_burn_gph
                        sample_fuels.append(
                            max(0.0, starting_fuel_gal - used))

                    se_rings, se_meta = compute_route_se_corridor(
                        all_samples, all_alts, ac_for_me,
                        fuel_remaining_gal=starting_fuel_gal,
                        wind_dir_deg=wd, wind_speed_kt=ws,
                        sample_winds=all_winds,
                        n_envelope_points=24,
                        max_minutes_after_failure=60.0,
                        sample_fuel_remaining_gal=sample_fuels,
                    )
                    if corridor_visible:
                        for ring in se_rings:
                            layer.append(dl.Polygon(
                                positions=ring,
                                color="#7e22ce", weight=1,
                                fillColor="#a855f7", fillOpacity=0.15,
                            ))

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
        # Use the FULL sample list between gap start_idx and end_idx
        # so the dashed line follows the bent route through every
        # checkpoint instead of cutting straight across them.
        for g in gaps:
            if g["gap_nm"] < 1.0:
                continue   # skip single-sample blips
            s_idx = g.get("start_idx", 0)
            e_idx = g.get("end_idx", s_idx)
            try:
                gap_positions = [
                    [float(la), float(lo)]
                    for la, lo in all_samples[s_idx:e_idx + 1]
                ]
            except (IndexError, ValueError, TypeError):
                gap_positions = [[g["start_lat"], g["start_lon"]],
                                  [g["end_lat"], g["end_lon"]]]
            if len(gap_positions) < 2:
                continue
            layer.append(dl.Polyline(
                positions=gap_positions,
                color="#dc2626", weight=5, opacity=0.85,
                dashArray="8 6",
                children=[dl.Tooltip(
                    f"No airport within engine-out glide range — "
                    f"{g['gap_nm']:.0f} NM stretch"
                )],
            ))

        # ─── Wind barbs along route (if winds available) ──────────────
        if all_winds is not None and all_samples:
            barb_idxs = pick_barb_indices(len(all_samples), total_route_nm)
            for i in barb_idxs:
                lat, lon = all_samples[i]
                wdir, wsp = all_winds[i]
                svg = wind_barb_svg(wdir, wsp, size_px=40)
                tip = f"{wdir:03.0f}° @ {wsp:.0f} kt at {all_alts[i]:.0f} ft MSL"
                layer.append(dl.DivMarker(
                    position=[lat, lon],
                    iconOptions={
                        "html": svg,
                        "className": "wind-barb-marker",
                        "iconSize": [40, 40],
                        "iconAnchor": [20, 20],
                    },
                    children=[dl.Tooltip(tip)],
                ))

        # ─── Landing-options render (Phase 8b, refined) ──────────────
        # Paints the OSM "where a pilot has options" polygons, but ONLY
        # within the engine-out glide corridor — the corridor is the
        # master constraint, and a green patch 30 NM from the reachable
        # polygon is just noise. Each feature is intersected with
        # corridor_shape before being added.
        #   suitable (farmland/meadow/grass/etc.) → green
        #   water    (lakes/rivers)               → blue (ditching)
        # ─── Combined landable mask (Phase 8c) ────────────────────────
        # ONE pill, three signals AND-ed: slope ≤ threshold AND inside
        # an OSM suitable-land polygon AND inside the glide corridor.
        # Painted as a single green raster so the pilot sees exactly
        # "where could I plant this aircraft" without parsing two
        # stacked greens. Water (AFH §18-7 ditching) is rendered
        # separately in blue inside the corridor.
        land_cover_meta = None
        slope_meta = None      # legacy hook for score wiring below
        if want_landable_render and landing_opts:
            from shapely.geometry import (
                shape as _shp_shape, mapping as _shp_mapping,
            )

            try:
                threshold = float(slope_threshold) if slope_threshold else 3.0
            except (TypeError, ValueError):
                threshold = 3.0

            # Build shapely geoms for the suitable-land features so the
            # mask builder can union + rasterize them.
            suitable_fc = landing_opts.get("suitable", {"features": []})
            water_fc = landing_opts.get("water", {"features": []})
            suitable_geoms = []
            for feat in suitable_fc.get("features", []):
                try:
                    g = _shp_shape(feat["geometry"])
                    if not g.is_valid:
                        g = g.buffer(0)
                    if g.is_valid and not g.is_empty:
                        suitable_geoms.append(g)
                except Exception:
                    continue

            lats = [w["lat"] for w in waypoints]
            lons = [w["lon"] for w in waypoints]
            pad = 0.1
            mask_lat_min = min(lats) - pad
            mask_lat_max = max(lats) + pad
            mask_lon_min = min(lons) - pad
            mask_lon_max = max(lons) + pad

            data_url, mask_meta = build_landable_mask_overlay(
                _terrain_elevation_m, suitable_geoms,
                mask_lat_min, mask_lon_min,
                mask_lat_max, mask_lon_max,
                threshold_deg=threshold,
                grid_size=128,
                fill_opacity=0.55,
                corridor_polygon=corridor_shape,
            )
            layer.append(dl.ImageOverlay(
                url=data_url,
                bounds=[[mask_lat_min, mask_lon_min],
                        [mask_lat_max, mask_lon_max]],
                opacity=1.0,
            ))

            # Water (ditching) — still rendered as separate blue
            # polygons clipped to the corridor. The combined mask
            # excludes water; water is a different decision (AFH
            # §18-7) so we keep it as its own visual channel.
            clipped_water = []
            if corridor_shape is not None:
                for feat in water_fc.get("features", []):
                    try:
                        g = _shp_shape(feat["geometry"])
                        if not g.is_valid:
                            g = g.buffer(0)
                        if not g.is_valid or g.is_empty:
                            continue
                        inter = g.intersection(corridor_shape)
                        if inter.is_empty:
                            continue
                        subs = (list(inter.geoms)
                                if hasattr(inter, "geoms") else [inter])
                        for sub in subs:
                            if (hasattr(sub, "exterior")
                                    and not sub.is_empty):
                                clipped_water.append({
                                    "type": "Feature",
                                    "geometry": _shp_mapping(sub),
                                    "properties": feat.get("properties", {}),
                                })
                    except Exception:
                        continue
            if clipped_water:
                layer.append(dl.GeoJSON(
                    data={"type": "FeatureCollection",
                          "features": clipped_water},
                    options=dict(style=WATER_STYLE),
                ))

            # Feed `pct_slope_alone` into the survivability score's
            # "Steep terrain in corridor" factor — that factor is
            # ABOUT slope, not combined landability. Pre-fix we fed
            # pct_landable_combined, which mixes slope AND land-cover
            # suitability; coastal/over-water routes (KDYB→KMYR has
            # plenty of ocean) got flagged as "steep terrain" when
            # the actual issue was unsuitable land cover (water),
            # which has its own "Little suitable land" factor.
            slope_meta = {
                "pct_landable": mask_meta["pct_slope_alone"],
                "threshold_deg": mask_meta["threshold_deg"],
                "pct_steep": 100.0 - mask_meta["pct_slope_alone"],
                "pct_marginal": 0.0,
                "max_slope_deg": 0.0,
                "mean_slope_deg": 0.0,
            }
            land_cover_meta = {
                "suitable_features": len(suitable_geoms),
                "water_features": len(clipped_water),
                "pct_corridor_suitable": mask_meta["pct_suitable_alone"] / 100.0,
                "pct_landable_combined": mask_meta["pct_landable_combined"],
            }

        # ─── Terrain conflict status per sample ───────────────────────
        # Classify each sample as clear / marginal / conflict based on
        # AGL vs terrain. The samples are along great-circle legs so
        # the resulting status array directly drives a segmented
        # multi-color polyline. Uses the corridor's elevation_fn
        # (warm tiles from the prefetch above).
        sample_status_pairs = classify_route_statuses(
            all_samples, all_alts, _terrain_elevation_m,
        )
        statuses_only = [s for s, _t in sample_status_pairs]
        terrain_at_samples = [t for _s, t in sample_status_pairs]

        # ─── Segmented route polyline by terrain status ───────────────
        STATUS_STYLE = {
            "clear": {"color": "#0d59f2", "weight": 3, "opacity": 0.85},
            "marginal": {"color": "#f59e0b", "weight": 4, "opacity": 0.95},
            "conflict": {"color": "#dc2626", "weight": 5, "opacity": 0.98},
        }
        STATUS_TIP = {
            "clear": "Clear of terrain (AGL ≥ 2000 ft)",
            "marginal": "Marginal terrain clearance (500–2000 ft AGL)",
            "conflict": "Cruise altitude conflicts with terrain",
        }
        # D2-5g: Checkpoint generation + bent-samples swap already ran
        # at line ~2099 (BEFORE corridor calc). So at this point:
        #   - all_samples is the bent path (when cp_on AND checkpoints)
        #     OR the original great-circle (when cp_off OR no checkpoints)
        #   - all_alts, statuses_only, terrain_at_samples, corridor,
        #     landable mask, divert coverage, airspace crossings,
        #     NOTAMs ALL already operate on whatever all_samples is.
        # Just compute coverage_payload + render the polyline now.
        cp_on = cp_on_early
        coverage_payload = None
        try:
            from core.checkpoints import (
                coverage_summary as _coverage_summary_late,
            )
            coverage_payload = _coverage_summary_late(
                samples=all_samples,
                sample_alts_msl_ft=all_alts,
                airports=airport_data,
                glide_ratio=float(glide_ratio or 9.0),
            )
        except Exception:
            coverage_payload = None

        # Render the status-segmented polyline. Since all_samples is
        # already the bent path when checkpoints are ON, this single
        # render path covers both cases.
        segs = segment_polyline_by_status(all_samples, statuses_only)
        for seg in segs:
            style = STATUS_STYLE[seg["status"]]
            tip_text = STATUS_TIP[seg["status"]]
            if cp_on and checkpoints_payload:
                tip_text += (f" · bent route through "
                              f"{len(checkpoints_payload)} checkpoints")
            layer.append(dl.Polyline(
                positions=seg["positions"],
                color=style["color"], weight=style["weight"],
                opacity=style["opacity"],
                children=dl.Tooltip(tip_text),
            ))

        # === Below: removed duplicate checkpoint generation that
        # USED to live here. It's been replaced by the early-swap
        # block. ===
        if False:
          try:
            from core.checkpoints import (
                suggest_checkpoints as _suggest_checkpoints,
                coverage_summary as _coverage_summary,
            )
            from core.data_loader import navaid_data as _navaid_data
            from core.data_loader import fix_data as _fix_data
            from core.landmarks_osm import (
                fetch_populated_places as _fetch_pop,
                fetch_river_crossings as _fetch_rivers,
            )
            try:
                slats = [w["lat"] for w in waypoints]
                slons = [w["lon"] for w in waypoints]
                pad = 0.25
                landmarks_payload.extend(_fetch_pop(
                    lat_min=min(slats) - pad, lat_max=max(slats) + pad,
                    lon_min=min(slons) - pad, lon_max=max(slons) + pad,
                    min_population=5000,
                ))
                for a_wp, b_wp in zip(waypoints[:-1], waypoints[1:]):
                    la = (float(a_wp["lat"]), float(a_wp["lon"]))
                    lb = (float(b_wp["lat"]), float(b_wp["lon"]))
                    lat_lo, lat_hi = sorted([la[0], lb[0]])
                    lon_lo, lon_hi = sorted([la[1], lb[1]])
                    landmarks_payload.extend(_fetch_rivers(
                        lat_min=lat_lo - 0.05, lat_max=lat_hi + 0.05,
                        lon_min=lon_lo - 0.05, lon_max=lon_hi + 0.05,
                        leg_a=la, leg_b=lb,
                    ))
            except Exception:
                landmarks_payload = []

            checkpoints_payload = _suggest_checkpoints(
                waypoints=waypoints,
                cruise_alt_msl_ft=float(cruise_alt or 5500),
                tas_kt=float(tas or 110),
                glide_ratio=float(glide_ratio or 9.0),
                airports=airport_data,
                navaids=_navaid_data,
                fixes=_fix_data,
                landmarks=landmarks_payload,
            )
            # Apply user drag-edits: override matching idents' lat/lon
            # with the dragged position. The ident is what we keyed
            # the edit by, so a checkpoint that got dragged to a new
            # spot keeps its identity. Cumulative_nm / bearing fields
            # are stale-but-okay here; downstream renderers use the
            # lat/lon directly and the bent-chain math regenerates
            # the geometry from them.
            if checkpoint_edits and isinstance(checkpoint_edits, dict):
                for cp in checkpoints_payload:
                    edit = checkpoint_edits.get(cp.get("ident"))
                    if edit:
                        cp["lat"] = float(edit["lat"])
                        cp["lon"] = float(edit["lon"])
                        cp["notes"] = (cp.get("notes", "")
                                        + " · user-positioned")
            # coverage_payload is computed AFTER bent_samples_draw is
            # built (below) — that way we measure glide-coverage along
            # the ACTUAL flown route, not the straight-line.
          except Exception:
            checkpoints_payload = []
            coverage_payload = None
            landmarks_payload = []

        # === D2-5g: Duplicate bent_chain / coverage / polyline render
        # blocks REMOVED — early-swap at line ~2099 already produced
        # bent_chain + bent_samples_draw, the polyline render above
        # consumed the (already-bent) all_samples, and coverage_payload
        # was computed against all_samples (also already bent). ===

        # Waypoint markers on top of the segmented polyline.
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

        # === Destination 45° entry — bends the route into the pattern ===
        # The dest pattern is RENDERED by a separate callback (so the
        # runway dropdown can change it without re-running the route),
        # but the ROUTE polyline's last segment needs to visibly bend
        # into the 45° entry vector so the eye reads it as one
        # continuous flight path: cruise → 10 NM CTAF → 45° approach
        # → downwind. Without this the route just hits the airport
        # icon and the pattern looks like a separate decoration.
        #
        # We compute the entry anchor here (using the runway override
        # from the Store, falls back to wind-favored) and replace the
        # last ~10 NM of the route polyline with the 45° approach
        # segment. Also stamp the anchor into route-result-store so
        # the pattern callback uses the SAME anchor — no drift between
        # the two layers.
        dest_pattern_meta = None
        try:
            want_dest_pattern = bool(
                show_dest_pattern and "on" in show_dest_pattern)
        except (TypeError, ValueError):
            want_dest_pattern = False

        # Pattern entry + route bend math. Compute the entry anchor
        # using the user's runway override (or wind-favored default),
        # then derive the EXTENDED 45° entry vector — projected 10 NM
        # BACK from the entry anchor along the entry-leg bearing. The
        # route's last segment ends at that point so the polyline
        # visibly bends to align with the 45° entry into downwind.
        if want_dest_pattern and waypoints:
            dest = waypoints[-1]
            dest_id = dest.get("id")
            ap_record = next((a for a in airport_data
                               if a.get("id") == dest_id), None)
            if ap_record:
                from callbacks.maneuvers.pattern import (
                    _runway_ends_for, _pick_wind_favored_end,
                    build_pattern_geometry, pattern_dimensions_for,
                )
                ends = _runway_ends_for(ap_record)
                if ends:
                    try:
                        ws_local = float(wind_speed) if wind_speed is not None else 0.0
                        wd_local = float(wind_dir) if wind_dir is not None else 0.0
                    except (TypeError, ValueError):
                        ws_local, wd_local = 0.0, 0.0
                    if all_winds and len(all_winds) > 0:
                        try:
                            wd_local, ws_local = (
                                float(all_winds[-1][0]),
                                float(all_winds[-1][1]),
                            )
                        except Exception:
                            pass

                    chosen_end = None
                    if runway_override:
                        chosen_end = next(
                            (e for e in ends if e.get("id") == runway_override),
                            None,
                        )
                    if chosen_end is None:
                        chosen_end = (_pick_wind_favored_end(ends, wd_local, ws_local)
                                      or ends[0])
                    pub_dir = chosen_end.get("pattern_direction")
                    pat_dir = pub_dir if pub_dir in ("left", "right") else "left"

                    ac_for_pat = aircraft_data.get(aircraft_name) if aircraft_name else None
                    dims = pattern_dimensions_for(ac_for_pat)

                    # === Auto-select entry method by arrival direction ===
                    # Priority (least maneuvering first), per AC 90-66B
                    # + AFH Ch. 8. NOTE: straight-in is NEVER auto-
                    # selected — AC 90-66B §11.10 discourages straight-in
                    # at non-towered fields outside of IFR / practice-
                    # approach contexts because it conflicts with the
                    # standard pattern flow. Pilots can manually opt
                    # into straight-in via the standalone Pattern
                    # maneuver if they specifically need it.
                    #
                    # Auto-selector priority:
                    #   direct_downwind   — inbound aligned with downwind  (|Δ| < 25°)
                    #   direct_base       — inbound aligned with base      (|Δ| < 25°)
                    #   direct_crosswind  — inbound aligned with crosswind (|Δ| < 25°)
                    #   45_downwind       — on pattern side, awkward angle
                    #   midfield_crossover— arriving from opposite side OR
                    #                       from the upwind end (aligned
                    #                       with final approach direction)
                    #
                    # "Aligned with final" arrivals get midfield crossover
                    # — the aircraft is approaching from the upwind end
                    # and would otherwise overfly the runway; cross at
                    # TPA+500 and descend onto downwind on the pattern
                    # side is the FAA-published alternative.
                    entry_method = "45_downwind"
                    if len(waypoints) >= 2:
                        prev = waypoints[-2]
                        in_dn = (float(dest["lat"]) - float(prev["lat"])) * 60.0
                        in_de = ((float(dest["lon"]) - float(prev["lon"])) * 60.0
                                  * math.cos(math.radians(float(dest["lat"]))))
                        inbound_bearing = (math.degrees(math.atan2(in_de, in_dn)) + 360.0) % 360.0
                        final_hdg_v = float(chosen_end.get("heading", 0.0))
                        downwind_hdg_v = (final_hdg_v + 180.0) % 360.0
                        # For LEFT pattern: base = final + 90°,
                        #                   crosswind (arrival) = final - 90°
                        # For RIGHT pattern: base = final - 90°,
                        #                    crosswind (arrival) = final + 90°
                        # Pattern-side bearing: which side of the runway
                        # the downwind sits on.
                        if pat_dir == "right":
                            base_hdg_v = (final_hdg_v - 90.0 + 360.0) % 360.0
                            crosswind_hdg_v = (final_hdg_v + 90.0) % 360.0
                            pattern_side_bearing = (final_hdg_v + 90.0) % 360.0
                        else:
                            base_hdg_v = (final_hdg_v + 90.0) % 360.0
                            crosswind_hdg_v = (final_hdg_v - 90.0 + 360.0) % 360.0
                            pattern_side_bearing = (final_hdg_v - 90.0 + 360.0) % 360.0

                        def _ang(a, b):
                            return abs(((a - b) + 540.0) % 360.0 - 180.0)

                        # For HEADING comparisons (am I flying ALONG
                        # downwind / base / crosswind / final?) — use
                        # the inbound bearing directly.
                        ang_to_final = _ang(inbound_bearing, final_hdg_v)
                        ang_to_downwind = _ang(inbound_bearing, downwind_hdg_v)
                        ang_to_base = _ang(inbound_bearing, base_hdg_v)
                        ang_to_crosswind = _ang(inbound_bearing, crosswind_hdg_v)
                        # For SIDE comparisons (am I COMING FROM the
                        # pattern side?) — use the bearing FROM the
                        # destination back TO the previous waypoint,
                        # i.e. the direction the aircraft is arriving
                        # from. Using inbound_bearing here was the bug:
                        # heading NE means coming FROM SW; the side
                        # check needs the FROM direction.
                        from_dest_bearing = (inbound_bearing + 180.0) % 360.0
                        ang_to_pattern_side = _ang(from_dest_bearing, pattern_side_bearing)

                        # Decision tree, priority order. Straight-in is
                        # intentionally NOT a branch here — FAA AC 90-66B
                        # discourages it at non-towered fields outside
                        # of practice approaches. Pilots wanting
                        # straight-in must opt in via the standalone
                        # Pattern maneuver's entry picker.
                        if ang_to_downwind < 25.0 and ang_to_pattern_side <= 90.0:
                            # Aligned with downwind and on the pattern
                            # side: just descend onto downwind.
                            entry_method = "direct_downwind"
                        elif ang_to_base < 25.0 and ang_to_pattern_side <= 90.0:
                            entry_method = "direct_base"
                        elif ang_to_crosswind < 25.0 and ang_to_pattern_side <= 90.0:
                            entry_method = "direct_crosswind"
                        elif ang_to_final < 25.0:
                            # Aligned with FINAL approach heading →
                            # aircraft is coming from the upwind end
                            # of the runway (would otherwise overfly
                            # the threshold). FAA-recommended path is
                            # midfield crossover at TPA+500, descend
                            # to TPA on the pattern side.
                            entry_method = "midfield_crossover"
                        elif ang_to_pattern_side < 90.0:
                            # Arriving from the pattern side at an
                            # awkward angle — standard 45° intercept.
                            entry_method = "45_downwind"
                        else:
                            # Arriving from the opposite side of the
                            # pattern — midfield crossover.
                            entry_method = "midfield_crossover"

                    field_elev = float(ap_record.get("elevation_ft") or 0.0)
                    geo = build_pattern_geometry(
                        runway_end=chosen_end,
                        pattern_dir=pat_dir,
                        entry_method=entry_method,
                        tpa_agl=1000.0,
                        pattern_leg_nm=dims["pattern_leg_nm"],
                        final_leg_nm=dims["final_leg_nm"],
                        field_elev_ft=field_elev,
                    )

                    # Entry anchor = where the 45° leg meets the
                    # inbound 45° approach. Downwind midpoint = where
                    # the 45° leg meets the downwind. The entry leg
                    # direction is the bearing FROM anchor TO downwind
                    # midpoint; we project BACK from the anchor in the
                    # reverse direction by 10 NM to define the 45°
                    # approach start (where the route bends in).
                    entry_pos = None
                    downwind_first = None
                    for leg_data in geo["legs"]:
                        if leg_data["name"] == "entry" and leg_data["positions"]:
                            entry_pos = leg_data["positions"]
                        elif leg_data["name"] == "downwind" and leg_data["positions"]:
                            downwind_first = leg_data["positions"][0]

                    if entry_pos and downwind_first:
                        anchor_lat, anchor_lon = float(entry_pos[0][0]), float(entry_pos[0][1])
                        dw_lat, dw_lon = float(downwind_first[0]), float(downwind_first[1])
                        # Entry bearing — direction the aircraft flies
                        # DURING the 45° entry (anchor → downwind mid).
                        en_dn = (dw_lat - anchor_lat) * 60.0
                        en_de = ((dw_lon - anchor_lon) * 60.0
                                  * math.cos(math.radians(anchor_lat)))
                        entry_bearing = (math.degrees(math.atan2(en_de, en_dn)) + 360.0) % 360.0
                        # Approach start — 10 NM BACK from the anchor
                        # along the reciprocal of the entry bearing.
                        approach_back_bearing = (entry_bearing + 180.0) % 360.0
                        back_rad = math.radians(approach_back_bearing)
                        dlat_back = (10.0 / 60.0) * math.cos(back_rad)
                        dlon_back = ((10.0 / 60.0) * math.sin(back_rad)
                                      / max(0.2, math.cos(math.radians(anchor_lat))))
                        approach_start = (anchor_lat + dlat_back,
                                           anchor_lon + dlon_back)

                        dest_pattern_meta = {
                            "entry_method": entry_method,
                            "entry_anchor": [anchor_lat, anchor_lon],
                            "downwind_mid": [dw_lat, dw_lon],
                            "entry_bearing": round(entry_bearing, 1),
                            "runway_id": chosen_end.get("id"),
                            "pattern_dir": pat_dir,
                            "pattern_dir_published": pub_dir is not None,
                        }

                        # === Trim all_samples + bend the route ===
                        # Replace the part of `all_samples` past
                        # approach_start with [approach_start,
                        # entry_anchor]. We use a COPY since other
                        # downstream computations (corridor, NOTAMs,
                        # nav log) reference the original samples.
                        # `haversine_nm` is imported at module level
                        # (line 28); DO NOT re-import inside the
                        # function — that would shadow the global and
                        # break earlier uses in the same callback.
                        cut_idx = len(all_samples)
                        for i, (lat, lon) in enumerate(all_samples):
                            d_to_dest = haversine_nm(
                                float(lat), float(lon),
                                float(dest["lat"]), float(dest["lon"]),
                            )
                            d_back_from_anchor = haversine_nm(
                                float(lat), float(lon),
                                approach_start[0], approach_start[1],
                            )
                            # Cut at the first sample that's CLOSER to
                            # the airport than the approach-start
                            # is (i.e. inside the 10 NM bubble around
                            # the airport from the inbound side).
                            d_dest_from_anchor = haversine_nm(
                                approach_start[0], approach_start[1],
                                float(dest["lat"]), float(dest["lon"]),
                            )
                            if d_to_dest < d_dest_from_anchor:
                                cut_idx = i
                                break

                        # NOTE: Previously we surgically swapped the
                        # last sample(s) of the route polyline with
                        # [approach_start, entry_anchor]. That made
                        # the rendered route visually cross the
                        # airfield when the route arrived from the
                        # opposite side of the pattern. The cleaner
                        # approach is to leave the route polyline
                        # going straight to the destination and draw
                        # a solid amber connector (in the pattern
                        # callback) from the 10 NM CTAF point on the
                        # inbound route to the chosen entry anchor.
                        # Auto-selection (next pass) picks the entry
                        # method whose anchor is naturally reachable
                        # from the arrival direction so the connector
                        # never has to cross the field.
                        all_samples_for_draw = all_samples
                        statuses_only_for_draw = statuses_only
                    else:
                        all_samples_for_draw = all_samples
                        statuses_only_for_draw = statuses_only
                else:
                    all_samples_for_draw = all_samples
                    statuses_only_for_draw = statuses_only
            else:
                all_samples_for_draw = all_samples
                statuses_only_for_draw = statuses_only
        else:
            all_samples_for_draw = all_samples
            statuses_only_for_draw = statuses_only

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
            ]
            if corridor_meta_agg["below_terrain_samples"] > 0:
                rows.append(html.Div([
                    html.Span("Terrain conflict",
                              className="route-summary-label"),
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
        # === D2-3 + D2-5e: Glide-divert coverage (the moat) ===
        # Reuse the coverage_payload already computed against the
        # actual flown route (bent samples when checkpoints are ON,
        # straight-line otherwise). Pre-fix this re-ran the
        # computation against all_samples regardless — double-compute
        # AND wrong source when checkpoints were on.
        _cov = locals().get("coverage_payload", None)
        if _cov and _cov.get("n_samples", 0) > 0:
            pct = _cov["pct_in_glide"]
            longest = _cov["longest_gap_nm"]
            if pct >= 90:
                cov_cls = "route-summary-value route-summary-good"
            elif pct >= 70:
                cov_cls = "route-summary-value"
            else:
                cov_cls = "route-summary-value route-summary-warn"
            gap_cls = ("route-summary-value route-summary-warn"
                       if longest > 10 else "route-summary-value")
            divert_rows.append(html.Div([
                html.Span("Glide coverage", className="route-summary-label"),
                html.Span(f"{pct:.0f}% in glide of an airport",
                          className=cov_cls),
            ], className="route-summary-row"))
            if longest > 0:
                divert_rows.append(html.Div([
                    html.Span("Worst exposure", className="route-summary-label"),
                    html.Span(f"{longest:.1f} NM with no airport in glide",
                              className=gap_cls),
                ], className="route-summary-row"))

        divert_block = html.Div(className="route-divert-badge", children=divert_rows)

        # Wind status pill — tells the pilot which wind source the
        # corridor + diverts were computed against AND the actual
        # route-averaged values + dominant headwind/tailwind component
        # along the great-circle from origin to destination.
        if all_winds:
            avg_dir, avg_speed = route_average_wind(all_winds)
            # Component on the overall origin→destination track
            overall_track = legs[0]["true_course_deg"] if legs else 0.0
            avg_hw_tw, _ = wind_components(overall_track, avg_dir, avg_speed)
            comp_str = (f"TW {round(avg_hw_tw)} kt avg"
                        if avg_hw_tw >= 1 else
                        f"HW {abs(round(avg_hw_tw))} kt avg"
                        if avg_hw_tw <= -1 else "calm avg")
        else:
            avg_dir, avg_speed = wd, ws
            comp_str = ""

        if wind_source == "live":
            wind_pill_text = (
                f"Wind (live · forecast): "
                f"{avg_dir:03.0f}° @ {avg_speed:.0f} kt · {comp_str}"
            )
            wind_pill_cls = "route-wind-pill route-wind-live"
        elif wind_source == "live-unavailable":
            wind_pill_text = (
                f"Wind (live unavailable, manual): "
                f"{wd:.0f}° @ {ws:.0f} kt"
            )
            wind_pill_cls = "route-wind-pill route-wind-warn"
        else:
            wind_pill_text = f"Wind (manual): {wd:.0f}° @ {ws:.0f} kt"
            wind_pill_cls = "route-wind-pill route-wind-manual"
        wind_pill = html.Div(wind_pill_text, className=wind_pill_cls)

        # ─── Terrain conflict chip + suggested altitude button ────────
        # Built when any sample is in 'conflict' status. Computes the
        # peak terrain in the corridor strip (perpendicular swath
        # within max_reach), buffers it by 1000 or 2000 ft based on
        # terrain variance, and rounds to next VFR-legal cruise.
        terrain_block = None
        suggested_alt = None
        n_conflict = statuses_only.count("conflict")
        n_marginal = statuses_only.count("marginal")
        if n_conflict > 0:
            # Peak terrain in the strip (5 NM half-width swath)
            peak_ft, peak_lat, peak_lon = max_terrain_in_corridor_strip(
                all_samples, _terrain_elevation_m,
                half_width_nm=5.0, perp_samples=5,
            )
            t_var = max(terrain_at_samples) - min(terrain_at_samples) if terrain_at_samples else 0.0
            mc_courses = [l["magnetic_course_deg"] for l in legs] or [0.0]
            suggested_alt, reason = suggest_min_cruise_alt(
                peak_ft, mc_courses, terrain_variance_ft=t_var)
            terrain_block = html.Div(
                className="route-terrain-conflict", children=[
                    html.Div([
                        html.Span("Terrain conflict",
                                  className="route-summary-label"),
                        html.Span(
                            f"{n_conflict} samples below cruise (peak "
                            f"{peak_ft:.0f} ft near "
                            f"{peak_lat:.2f}°N {abs(peak_lon):.2f}°W)",
                            className="route-summary-value route-summary-warn"),
                    ], className="route-summary-row"),
                    html.Div([
                        html.Span("Suggested cruise",
                                  className="route-summary-label"),
                        html.Span(f"{suggested_alt:.0f} ft",
                                  className="route-summary-value"),
                        html.Button(
                            f"Use {suggested_alt:.0f} ft",
                            id="route-apply-suggested-alt",
                            n_clicks=0,
                            className="route-apply-alt-btn",
                        ),
                    ], className="route-summary-row"),
                ])
        elif n_marginal > 0:
            terrain_block = html.Div(
                className="route-terrain-marginal", children=[
                    html.Div([
                        html.Span("Terrain margin",
                                  className="route-summary-label"),
                        html.Span(
                            f"{n_marginal} samples in 500-2000 ft AGL",
                            className="route-summary-value"),
                    ], className="route-summary-row"),
                ])


        # ─── Altitude profile side-view chart ─────────────────────────
        profile_series = build_profile_series(
            all_samples, all_alts, _terrain_elevation_m)
        # Plotly figure: terrain area + flight profile line + conflict
        # markers. Compact for the overlay panel.
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=profile_series["distance_nm"],
            y=profile_series["terrain_ft"],
            fill="tozeroy",
            fillcolor="rgba(120, 113, 108, 0.45)",
            line=dict(color="#78716c", width=1),
            name="Terrain",
            hovertemplate="%{x:.0f} NM<br>%{y:.0f} ft<extra>terrain</extra>",
        ))
        fig.add_trace(go.Scatter(
            x=profile_series["distance_nm"],
            y=profile_series["flight_alt_ft"],
            line=dict(color="#0d59f2", width=2),
            mode="lines",
            name="Flight profile",
            hovertemplate="%{x:.0f} NM<br>%{y:.0f} ft<extra>flight</extra>",
        ))
        # Mark conflict samples
        cx = [profile_series["distance_nm"][i]
              for i, s in enumerate(profile_series["statuses"]) if s == "conflict"]
        cy = [profile_series["flight_alt_ft"][i]
              for i, s in enumerate(profile_series["statuses"]) if s == "conflict"]
        if cx:
            fig.add_trace(go.Scatter(
                x=cx, y=cy, mode="markers",
                marker=dict(color="#dc2626", size=6, symbol="x"),
                name="Conflict",
                hovertemplate="conflict at %{x:.0f} NM<extra></extra>",
            ))
        # === D3-2: Airspace shelves on the profile chart ===
        # For each piercing/crossing airspace, find the contiguous run
        # of route samples inside its polygon, convert to NM along
        # route, and shade a rectangle [enter_nm, exit_nm] × [floor,
        # ceiling]. The pilot sees instantly whether the cruise
        # altitude line crosses any shaded box (pierces) or passes
        # over/under (the box appears but no penetration).
        try:
            from core.airspace import (
                _point_in_polygon as _pip,
                airspaces_in_bbox as _air_in_bbox,
                _path_bbox as _air_path_bbox,
            )
            asp_bbox = _air_path_bbox(all_samples)
            asp_records = _air_in_bbox(asp_bbox)
            CLASS_COLORS = {
                "B":   ("rgba(37, 99, 235, 0.22)", "#1d4ed8"),
                "C":   ("rgba(168, 85, 247, 0.22)", "#7e22ce"),
                "D":   ("rgba(30, 64, 175, 0.18)", "#1e3a8a"),
                "SUA": ("rgba(245, 158, 11, 0.22)", "#b45309"),
                "TFR": ("rgba(220, 38, 38, 0.30)", "#991b1b"),
            }
            # Filter rules per pilot feedback. The class info lives
            # in `type_code` (NOT `class`) — values like "A", "C",
            # "D", "E", "MOA", "W", "R", "P", "CLA". `kind` is the
            # high-level category: "class" / "sua" / "tfr". Skip the
            # ones that cover huge swaths of the chart with no
            # actionable VFR planning info:
            #   - Class A (above FL180, no VFR)
            #   - Class E (default coverage above 700/1200 AGL —
            #     covers the entire chart and crowds out the
            #     terminal-area shelves you actually care about)
            #   - Class G (uncontrolled, no clearance needed)
            #   - "CLA" / "Other" generic wide-area types
            # KEEP: B/C/D terminal areas + SUA (MOA / R / P / W / A) + TFR.
            SKIP_TYPE_CODES = {"A", "E", "G", "CLA", "OTHER"}
            dist_axis = profile_series["distance_nm"]
            for rec in asp_records:
                # type_code is the actual class/kind identifier.
                # Normalize: uppercase + strip + drop any "CLASS "
                # prefix (some sources emit "CLASS E").
                tc = (rec.get("type_code") or rec.get("class") or "").upper().strip()
                if tc.startswith("CLASS"):
                    tc = tc.replace("CLASS", "").strip()
                if tc in SKIP_TYPE_CODES:
                    continue
                geom = rec.get("geometry")
                if not geom:
                    continue
                # Find sample indices inside the polygon.
                idxs = [i for i, (la, lo) in enumerate(all_samples)
                         if _pip(la, lo, geom)]
                if not idxs:
                    continue
                enter_nm = dist_axis[idxs[0]] if idxs[0] < len(dist_axis) else 0
                exit_nm = dist_axis[idxs[-1]] if idxs[-1] < len(dist_axis) else dist_axis[-1]
                floor = rec.get("floor_ft") or 0
                ceiling = rec.get("ceiling_ft") or 18000
                # Cap ceiling at axis range so it doesn't blow up the
                # y-axis when an airspace tops out at FL600.
                ceiling_disp = min(float(ceiling),
                                    max(float(cruise_alt or 5500) + 2000,
                                        max(profile_series["terrain_ft"] or [0]) + 1500))
                # Use the normalized type_code we computed in the
                # filter block above. Maps to color by class letter
                # (B/C/D) or by kind ("sua"/"tfr") for non-class
                # categories. The MOA/R/P/W codes fall through to
                # the SUA color.
                cls = tc  # already normalized above
                kind_lc = (rec.get("kind") or "").lower()
                color_set = CLASS_COLORS.get(cls)
                if not color_set:
                    if kind_lc == "sua":
                        color_set = CLASS_COLORS["SUA"]
                    elif kind_lc == "tfr":
                        color_set = CLASS_COLORS["TFR"]
                    else:
                        color_set = CLASS_COLORS["D"]
                fill_color, line_color = color_set
                name = rec.get("name") or cls or "Airspace"
                # Render as a filled scatter trace (NOT add_shape)
                # so hover tooltips work. Plotly's add_shape produces
                # static layout shapes that ignore hover events; a
                # closed-path Scatter with `fill="toself"` AND
                # `hoveron="fills"` IS hoverable.
                fig.add_trace(go.Scatter(
                    x=[enter_nm, exit_nm, exit_nm, enter_nm, enter_nm],
                    y=[float(floor), float(floor),
                        float(ceiling_disp), float(ceiling_disp),
                        float(floor)],
                    fill="toself",
                    fillcolor=fill_color,
                    line=dict(color=line_color, width=1),
                    mode="lines",
                    hoveron="fills",
                    hoverinfo="text",
                    hovertext=(
                        f"<b>Class {cls}</b> — {name}<br>"
                        f"Floor: {floor:.0f} ft MSL<br>"
                        f"Ceiling: {ceiling:.0f} ft MSL<br>"
                        f"Route inside: {enter_nm:.0f} - {exit_nm:.0f} NM"
                    ),
                    name=f"{cls} · {name[:18]}",
                    showlegend=False,
                ))
        except Exception:
            # Airspace overlay is best-effort: profile chart still
            # renders without shelves if the bbox query / pip lookup
            # fails for any reason.
            pass

        # Y-axis range — focus on the cruise band so airspace shelves
        # don't squish the terrain profile. Top = max(110% of cruise,
        # terrain peak + 1000 ft). Bottom = 0 (sea level) for context.
        try:
            terrain_max = max(profile_series["terrain_ft"] or [0])
        except Exception:
            terrain_max = 0
        y_top = max(float(cruise_alt or 5500) * 1.10, terrain_max + 1000.0)
        fig.update_layout(
            height=140,
            margin=dict(l=40, r=10, t=10, b=30),
            xaxis_title="Distance (NM)",
            yaxis_title="ft MSL",
            yaxis=dict(range=[0, y_top]),
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(248, 250, 252, 0.7)",
            font=dict(size=9),
        )
        profile_chart = dcc.Graph(
            id="route-profile-chart",
            figure=fig,
            config={
                "displayModeBar": False,
                "staticPlot": False,
                "responsive": True,
            },
            className="route-profile-chart",
            style={"width": "100%", "height": "140px"},
        )

        # ─── Survivability score (Phase 9) ─────────────────────────────
        # Aggregate every per-route signal into one 0-100 verdict so
        # the pilot reads "is this route survivable?" instead of
        # decoding five separate stats. The factor list is sorted
        # worst-first so the row beneath the score names exactly what
        # cost the points.
        n_route_samples = len(all_samples)
        n_terrain_conflict = (corridor_meta_agg.get("below_terrain_samples", 0)
                              if corridor_meta_agg else 0)
        min_agl_for_score = (corridor_meta_agg.get("min_agl_ft", 0.0)
                             if corridor_meta_agg else 0.0)
        pct_landable_arg = (slope_meta.get("pct_landable")
                            if slope_meta else None)
        pct_corridor_suit_arg = (land_cover_meta.get("pct_corridor_suitable")
                                 if land_cover_meta else None)
        critique = score_route(
            n_samples=n_route_samples,
            n_terrain_conflict_samples=n_terrain_conflict,
            n_no_divert_samples=no_cov,
            longest_no_divert_nm=long_gap,
            pct_landable_slope=pct_landable_arg,
            pct_corridor_suitable_land=pct_corridor_suit_arg,
            min_agl_ft=min_agl_for_score,
        )
        # Banner = score chip + route title + condensed factor chips.
        # Full-width, sits above the map. The chip-row turns each
        # critique factor into a one-glance chip so the pilot reads
        # "what cost the points" without leaving the map view.
        factor_chips = [
            html.Div([
                html.Span(f"{f.points:+.0f}",
                          className=("route-critique-points"
                                     + (" route-critique-pos"
                                        if f.points > 0 else ""))),
                html.Span(f.label,
                          className="route-critique-factor-label"),
            ], className="route-critique-chip",
               title=f.detail)
            for f in critique.factors
        ]
        banner = html.Div(
            className=f"route-banner route-banner-{critique.band}",
            style={"borderLeft": f"6px solid {critique.color_hex()}"},
            children=[
                html.Div(className="route-banner-score-wrap", children=[
                    html.Span(f"{critique.score}",
                              className="route-banner-score",
                              style={"color": critique.color_hex()}),
                    html.Span("/100",
                              className="route-banner-score-suffix"),
                ]),
                html.Div(className="route-banner-mid", children=[
                    html.Div(" → ".join(w["id"] for w in waypoints),
                             className="route-banner-route-title"),
                    html.Div(critique.headline,
                             className="route-banner-headline"),
                ]),
                html.Div(className="route-banner-chip-row",
                         children=factor_chips),
            ],
        )

        # Below-strip = View Nav Log button + wind chip + the altitude
        # side-view chart. The whole strip is hide-able via the
        # bottom-right "▼ Info" toggle that sits in the map's corner,
        # so when the pilot wants max map area they collapse it
        # entirely (no floating remnants).
        below_strip = html.Div(
            className="route-below-strip-inner route-strip-compact",
            children=[
                html.Div(className="route-strip-cell route-strip-cell-actions",
                         children=[
                    html.Button("View Nav Log",
                                id="nav-log-open-btn",
                                className="nav-log-open-btn",
                                n_clicks=0),
                    wind_pill,
                ]),
                html.Div(className="route-strip-cell route-strip-cell-chart",
                         children=[profile_chart]),
            ],
        )

        # Build the FAA-style nav log content for the modal.
        totals_for_log = {
            "distance_nm": sum((leg.get("distance_nm") or 0) for leg in legs),
            "ete_min": sum((leg.get("ete_min") or 0) for leg in legs),
            "fuel_burn_gal": sum((leg.get("fuel_burn_gal") or 0) for leg in legs),
        }
        divert_summary_for_log = {
            "n_diverts": n_diverts,
            "longest_gap_nm": long_gap,
            "n_samples_with_no_coverage": no_cov,
            "suggested_alt_ft": float(suggested_alt) if suggested_alt else None,
        }
        # Pull the full airport records for departure + destination so
        # the side panels can show Field Elev + runway list. Other
        # ATIS / freq fields stay blank for the pilot (no METAR client
        # ingested into the overlay tool yet).
        airport_records = {}
        for wp in (waypoints[0], waypoints[-1]):
            ap_id = wp.get("id")
            if ap_id:
                rec = next((a for a in airport_data
                            if a.get("id") == ap_id), None)
                if rec:
                    airport_records[ap_id] = rec

        # If the pilot supplied a Cruise IAS, honor it for the CAS
        # column; otherwise compute_nav_log derives CAS from TAS via
        # density ratio.
        try:
            cruise_ias_val = (float(cruise_ias)
                              if cruise_ias not in (None, "") else None)
        except (TypeError, ValueError):
            cruise_ias_val = None

        # Airspace crossings along the route at planned cruise altitude.
        # Uses the same per-sample lat/lon stream as the corridor + divert
        # passes so the spatial pass is consistent across all overlays.
        try:
            airspace_xings = route_crossings(all_samples, cruise_alt) \
                if all_samples else []
        except Exception:
            airspace_xings = []

        # NOTAM relevance filter — corridor strip + altitude band + time
        # window. Uses the same sample stream so the filter sees the
        # actual flown polyline, not just origin/dest.
        try:
            from core.notams import relevant_notams as _relevant_notams
            ete_total_min = sum((leg.get("ete_min") or 0) for leg in legs)
            notam_hits = _relevant_notams(
                all_samples, cruise_alt,
                departure_utc=None,  # "now" — when we add a planned
                                      # departure-time input, pass it here
                ete_total_min=ete_total_min,
            ) if all_samples else []
        except Exception:
            notam_hits = []

        # Density altitude at the departure field. Tells the pilot how
        # the field is performing today (climb rate / takeoff distance
        # both degrade with DA) before they even taxi. Falls back to
        # field elevation when OAT / altimeter aren't available.
        try:
            dep_elev = float(waypoints[0].get("elevation_ft") or 0.0)
            da_ft = density_altitude_ft(dep_elev, env_altimeter_inhg, env_oat_c)
            pa_ft = pressure_altitude_ft(dep_elev, env_altimeter_inhg)
        except Exception:
            da_ft = None
            pa_ft = None

        nav_log_doc = _build_nav_log(
            waypoints=waypoints,
            legs=legs,
            totals=totals_for_log,
            cruise_alt=cruise_alt,
            aircraft_name=aircraft_name,
            tas_kt=tas,
            cas_kt_override=cruise_ias_val,
            total_weight=None,    # filled in by sidebar weight calc
            fuel_load_gal=fuel_load_gal,
            wind_source=wind_source,
            critique=critique,
            corridor_meta=corridor_meta_agg,
            divert_summary=divert_summary_for_log,
            airport_records=airport_records,
            profile=profile.to_dict() if profile else None,
            airspace_crossings=airspace_xings,
            density_altitude_ft=da_ft,
            notams=notam_hits,
            profile_chart=profile_chart,
            checkpoints=checkpoints_payload,
        )

        # Engine-out-drill payload: enough route state for the
        # standalone scrubber callback to call compute_glide_envelope()
        # at any distance along the route without re-running the route
        # planner. We need (lat, lon) + altitude MSL per sample and the
        # wind/glide parameters. `all_samples` and `all_alts` are
        # already aligned by construction (built together in the
        # per-leg sampling loop above). Cumulative-distance per
        # sample is recomputed in the scrubber callback from the
        # great-circle math.
        try:
            _ws_avg, _wd_avg = ws, wd
            if all_winds:
                _wd_avg, _ws_avg = route_average_wind(all_winds)
        except Exception:
            _wd_avg, _ws_avg = wd, ws

        # Per-sample winds — same source the corridor uses (live winds
        # aloft when available, scalar fallback otherwise). Each entry
        # is (dir_deg, speed_kt) aligned to `all_samples`. Without
        # this, the drill ring uses a single route-averaged wind and
        # ends up shaped DIFFERENTLY than the corridor at the same
        # point, which is confusing.
        if all_winds is not None and len(all_winds) == len(all_samples):
            sample_winds_serialized = [
                [float(d), float(s)] for d, s in all_winds
            ]
        else:
            # No per-sample winds — replicate the scalar so the drill
            # callback can use the same lookup path.
            sample_winds_serialized = [
                [float(_wd_avg), float(_ws_avg)] for _ in all_samples
            ]

        # Off-airport candidate centroids — pulled from the route's
        # `landing_opts`. Separated into FAA precedence tiers (AFH
        # Ch. 18) so the drill picker can always serve up a target:
        #
        #   tier 1: airport runway       (handled separately, via airport_data)
        #   tier 2: open field / suitable (OSM "suitable" polygons)
        #   tier 3: water · ditching      (OSM "water" polygons)
        #
        # When the user toggles Landable, both layers are fetched.
        # Without the toggle, we use whatever's already cached, else
        # the drill falls back to the nearest airport.
        offfield_centroids: list[list[float]] = []
        water_centroids: list[list[float]] = []
        try:
            if landing_opts:
                from shapely.geometry import shape as _shp_shape

                def _collect_centroids(feats, sink):
                    for feat in feats or []:
                        try:
                            g = _shp_shape(feat["geometry"])
                            if not g.is_valid:
                                g = g.buffer(0)
                            if g.is_valid and not g.is_empty:
                                c = g.representative_point()
                                sink.append([float(c.y), float(c.x)])
                        except Exception:
                            continue

                _collect_centroids(
                    landing_opts.get("suitable", {}).get("features", []),
                    offfield_centroids,
                )
                _collect_centroids(
                    landing_opts.get("water", {}).get("features", []),
                    water_centroids,
                )
        except Exception:
            pass

        engineout_drill = {
            "samples": [[float(lat), float(lon)] for lat, lon in all_samples],
            "alts_msl_ft": [float(a) for a in all_alts],
            "sample_winds": sample_winds_serialized,
            "cruise_alt_ft": float(cruise_alt),
            "glide_ratio": float(glide_ratio),
            "tas_kt": float(tas),
            "glide_ias_kt": float(glide_ias) if glide_ias is not None else 75.0,
            # Route-averaged wind kept as a fallback in case per-sample
            # winds are missing for some interpolation index.
            "wind_dir_deg": float(_wd_avg),
            "wind_speed_kt": float(_ws_avg),
            # Field elev — used for AGL conversion in glide-envelope.
            # Take the max airport elev along the route as a
            # conservative ground reference.
            "ground_elev_ft": float(max(
                (w.get("elevation_ft") or 0.0) for w in waypoints
            )),
            "aircraft": aircraft_name,
            "offfield_centroids": offfield_centroids,
            "water_centroids": water_centroids,
        }

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
            "terrain": {
                "n_conflict": n_conflict,
                "n_marginal": n_marginal,
            },
            "suggested_alt_ft": float(suggested_alt) if suggested_alt else None,
            "airspace": {
                "n_pierce": sum(1 for x in airspace_xings if x["pierces"]),
                "n_under_over": sum(1 for x in airspace_xings if not x["pierces"]),
            },
            "engineout_drill": engineout_drill,
            # Pattern anchor used by the route's last-segment bend.
            # `render_destination_pattern` reads this so the pattern
            # legs originate at the SAME entry anchor — no drift
            # between the bent route's end and the pattern's start.
            "dest_pattern_meta": dest_pattern_meta,
        }

        # Checkpoints + coverage were already computed up-front (in
        # the polyline-bend block) so the rendered route could visit
        # them. Just persist into the result store here.
        store["checkpoints"] = locals().get("checkpoints_payload", [])
        store["divert_coverage"] = locals().get("coverage_payload", None)
        store["n_landmarks_fetched"] = len(locals().get("landmarks_payload", []))

        return banner, below_strip, nav_log_doc, layer, viewport, store

    # ===========================================================================
    # Engine-Out Drill (Phase A1) — "if the engine fails here, where do I land?"
    #
    # User flow:
    #   1. Compute a route → result store carries route + glide params.
    #   2. Toggle the "Engine-out drill" pill ON → slider container reveals,
    #      slider's max = total route NM.
    #   3. As the user moves the slider, the active sample (lat/lon/alt MSL)
    #      is fed to `compute_glide_envelope()` to draw the wind-stretched
    #      glide ring at that point. Airports inside the ring are colored
    #      by margin (green = >500 ft, amber = ≤500 ft, gray = outside).
    #
    # The full engine-out plan (run_simulation) is a follow-up (A1-4) —
    # this MVP covers the ring + airport classification only.
    # ===========================================================================

    # === Mirror callbacks: shelf UI ↔ always-present stores ===
    # The pill + slider in the route shelf only exist when Route Planner
    # is the active maneuver. To keep the rendering callback's Inputs
    # valid in EVERY maneuver context, we mirror their values into
    # stores defined in desktop.py. These mirror callbacks only fire
    # when the shelf is mounted (Input present), which is fine.
    @app.callback(
        Output("route-engineout-drill", "data"),
        Input("route-engineout-drill-pill", "value"),
        prevent_initial_call=True,
    )
    def _mirror_engineout_pill(value):
        return value or []

    @app.callback(
        Output("route-engineout-slider", "data"),
        Input("route-engineout-slider-ui", "value"),
        prevent_initial_call=True,
    )
    def _mirror_engineout_slider(value):
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # Mirror the runway-select dropdown into the always-present Store.
    # When the user picks a different runway, the Store change triggers
    # `render_destination_pattern` (not compute_and_render — that would
    # form a dependency cycle: compute writes route-result-store →
    # populates dropdown → mirror updates Store → compute fires again).
    @app.callback(
        Output("route-runway-select", "data"),
        Input("route-runway-select-ui", "value"),
        prevent_initial_call=True,
    )
    def _mirror_runway_select(value):
        return value or None

    # Mirror the dest-pattern pill the same way.
    @app.callback(
        Output("route-show-destination-pattern", "data"),
        Input("route-show-destination-pattern-pill", "value"),
        prevent_initial_call=True,
    )
    def _mirror_show_dest_pattern(value):
        return value or []

    @app.callback(
        Output("route-show-checkpoints", "data"),
        Input("route-show-checkpoints-pill", "value"),
        prevent_initial_call=True,
    )
    def _mirror_show_checkpoints(value):
        return value or []

    # Drop drag-edits when the pilot clicks Clear — the new route
    # won't have the old checkpoint idents, so stale edits would
    # silently leak between routes otherwise.
    @app.callback(
        Output("route-checkpoint-edits", "data", allow_duplicate=True),
        Input("route-clear-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def _clear_checkpoint_edits(n):
        if not n:
            return dash.no_update
        return {}

    # Populate the runway dropdown options after the route is computed.
    # Reads the destination airport from the result store; lists every
    # runway end with its heading + a hint when the chart supplement
    # publishes right-traffic for that end.
    @app.callback(
        Output("route-runway-select-ui", "options"),
        Output("route-runway-select-ui", "value"),
        Input("route-result-store", "data"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        prevent_initial_call=True,
    )
    def populate_dest_runway_options(route_store, wind_dir, wind_speed):
        if not route_store:
            return [], None
        wps = route_store.get("waypoints") or []
        if not wps:
            return [], None
        dest_id = wps[-1]
        from core.data_loader import airport_data as _airports
        ap = next((a for a in _airports if a.get("id") == dest_id), None)
        if not ap:
            return [], None
        from callbacks.maneuvers.pattern import (
            _runway_ends_for, _pick_wind_favored_end,
        )
        ends = _runway_ends_for(ap)
        if not ends:
            return [], None
        try:
            wd = float(wind_dir) if wind_dir is not None else 0.0
        except (TypeError, ValueError):
            wd = 0.0
        try:
            ws = float(wind_speed) if wind_speed is not None else 0.0
        except (TypeError, ValueError):
            ws = 0.0
        preferred = _pick_wind_favored_end(ends, wd, ws)
        preferred_id = preferred.get("id") if preferred else None

        opts = []
        for end in ends:
            h = end.get("heading")
            hw = (ws * math.cos(math.radians(float(h) - wd))
                  if h is not None and ws > 0 else 0.0)
            pd = end.get("pattern_direction")
            pd_tag = "  ⟲R" if pd == "right" else ""
            label = f"{end.get('id', '?')} ({end.get('heading', 0):03.0f}°)"
            if ws > 0:
                label += f"  HW {hw:+.0f}"
            label += pd_tag
            opts.append({"label": label, "value": end.get("id")})

        return opts, preferred_id

    # === Toggle the container + size the slider when route + pill flip ===
    @app.callback(
        Output("route-engineout-drill-container", "style"),
        Output("route-engineout-slider-ui", "min"),
        Output("route-engineout-slider-ui", "max"),
        Output("route-engineout-slider-ui", "value"),
        Output("route-engineout-slider-ui", "marks"),
        Input("route-engineout-drill", "data"),
        Input("route-result-store", "data"),
        State("route-engineout-slider", "data"),
        prevent_initial_call=True,
    )
    def toggle_engineout_drill(drill_toggle, route_store, current_val):
        """Show/hide the slider container; size its range to total route NM."""
        is_on = bool(drill_toggle and "on" in drill_toggle)
        drill = (route_store or {}).get("engineout_drill") or {}
        samples = drill.get("samples") or []
        has_route = len(samples) >= 2

        if not (is_on and has_route):
            return ({"display": "none"},
                    0, 100, 0, {0: "0", 100: "End"})

        # Build cumulative distance per sample to size the slider.
        total_nm = _cumulative_route_nm(samples)
        slider_max = max(1, int(round(total_nm)))
        marks = {
            0: "0",
            slider_max // 2: f"{slider_max // 2}",
            slider_max: f"{slider_max} NM",
        }
        # Default scrubber to mid-route — the most interesting starting
        # point for "what if it fails NOW?" thinking on a long leg.
        default_val = current_val if (current_val and 0 < current_val <= slider_max) else slider_max // 2
        return ({"display": "inline-block", "width": "320px",
                 "marginLeft": "16px", "verticalAlign": "middle"},
                0, slider_max, default_val, marks)

    @app.callback(
        Output("route-engineout-layer", "children"),
        Input("route-engineout-slider", "data"),
        Input("route-engineout-drill", "data"),
        Input("route-result-store", "data"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("runtime-total-weight-lb", "data"),
        State("env-oat", "value"),
        State("env-altimeter", "value"),
        State("wind-profile-store", "data"),
        prevent_initial_call=True,
    )
    def render_engineout_drill(slider_nm, drill_toggle, route_store,
                                aircraft_name, engine_name, runtime_weight,
                                oat_f, altimeter_inhg, wind_profile_data):
        """Render the glide ring + airport classification at the slider's
        position along the route."""
        is_on = bool(drill_toggle and "on" in drill_toggle)
        drill = (route_store or {}).get("engineout_drill") or {}
        samples = drill.get("samples") or []
        alts = drill.get("alts_msl_ft") or []

        if not (is_on and len(samples) >= 2 and len(alts) == len(samples)):
            return []

        try:
            slider_nm = float(slider_nm or 0.0)
        except (TypeError, ValueError):
            slider_nm = 0.0

        # Linear-interpolate the active position + altitude from
        # cumulative-distance bins. Sample spacing is the route's
        # native spacing (2-5 NM), good enough for a 1-NM scrubber tick.
        pos_lat, pos_lon, pos_alt_msl, seg_idx, seg_frac = _interpolate_route_position(
            samples, alts, slider_nm)
        ground_elev_ft = float(drill.get("ground_elev_ft", 0.0))
        alt_agl = max(0.0, pos_alt_msl - ground_elev_ft)

        # Per-sample wind at the scrubber position. Matches the source
        # the corridor uses (live winds when staged, scalar route-avg
        # fallback otherwise). Pre-fix this used a single route-averaged
        # wind, which made the drill ring shape DIFFERENT than the
        # corridor at the same point — visually inconsistent.
        sample_winds = drill.get("sample_winds") or []
        if sample_winds:
            wind_dir_here, wind_speed_here = _interpolate_wind_at(
                sample_winds, seg_idx, seg_frac)
        else:
            wind_dir_here = float(drill.get("wind_dir_deg", 0.0))
            wind_speed_here = float(drill.get("wind_speed_kt", 0.0))

        # Compute glide envelope polygon — pure function, wind-stretched
        # AND terrain-clipped (matches the corridor's behavior). Pre-fix
        # this passed no `elevation_fn`, so the drill ring extended
        # straight through mountains while the corridor (which DID
        # clip) showed a different shape at the same point.
        from simulation.engine_out import compute_glide_envelope
        from core.terrain import elevation_m as _terrain_elevation_m
        from geopy import Point as _GeoPoint
        try:
            envelope_pts = compute_glide_envelope(
                start_point=_GeoPoint(pos_lat, pos_lon),
                altitude_ft=alt_agl,
                glide_ratio=float(drill.get("glide_ratio", 9.0)),
                wind_dir=wind_dir_here,
                wind_speed=wind_speed_here,
                tas_knots=float(drill.get("tas_kt", 110.0)),
                start_elev_ft=ground_elev_ft,
                elevation_fn=_terrain_elevation_m,
            )
        except Exception:
            envelope_pts = []

        elements: list = []

        # The polygon — semi-transparent green fill so you can still
        # see the route + terrain through it.
        if envelope_pts:
            elements.append(dl.Polygon(
                positions=[[float(p[0]), float(p[1])] for p in envelope_pts],
                color="#16a34a",
                weight=2,
                opacity=0.75,
                fill=True,
                fillColor="#16a34a",
                fillOpacity=0.10,
                children=dl.Tooltip(
                    f"Glide envelope from {alt_agl:.0f} ft AGL "
                    f"(GR {drill.get('glide_ratio', 9):.1f})"
                ),
            ))

        # "Engine fails here" marker — visible aircraft icon at the
        # scrubber position so the user has a fix on where the failure
        # is being simulated.
        elements.append(dl.CircleMarker(
            center=[pos_lat, pos_lon],
            radius=8,
            color="#dc2626",
            fill=True,
            fillColor="#dc2626",
            fillOpacity=1.0,
            children=dl.Tooltip(
                f"Engine fails here — {slider_nm:.0f} NM along route, "
                f"{pos_alt_msl:.0f} ft MSL ({alt_agl:.0f} ft AGL) · "
                f"Wind {wind_dir_here:.0f}°/{wind_speed_here:.0f} kt"
            ),
        ))

        # Airport classification — green inside w/ > 500 ft margin,
        # amber inside w/ ≤ 500 ft margin, gray outside (rendered only
        # within a wider bounding box for performance). Also returns the
        # best (highest-margin) green target so we can auto-plan.
        airport_elements, best_target = _classify_airports_for_drill(
            envelope_pts, pos_lat, pos_lon, alt_agl, drill, ground_elev_ft,
        )
        elements.extend(airport_elements)

        # === A1-4 + A1-6: always give a landing option ===
        # First preference: best airport (green > amber) in the ring.
        # If none is available, fall back to the closest landable
        # off-field centroid INSIDE the envelope — pilot at least
        # sees the best off-airport option instead of an empty ring.
        target = best_target
        target_is_off_field = False
        # Even when the envelope can't be drawn (terrain-clipped to
        # nothing), still attempt to find a forced-landing target
        # via the nearest-of-anything fallback. That's the case the
        # user complained about — a scrubber tick with no airport
        # AND no in-ring off-field shouldn't show a blank result.
        if target is None:
            off_target = _pick_offfield_target(
                offfield_centroids=drill.get("offfield_centroids") or [],
                water_centroids=drill.get("water_centroids") or [],
                envelope_pts=envelope_pts,
                scrubber_lat=pos_lat, scrubber_lon=pos_lon,
                alt_agl=alt_agl, glide_ratio=float(drill.get("glide_ratio", 9.0)),
                ground_elev_ft=ground_elev_ft,
            )
            if off_target is not None:
                target = off_target
                target_is_off_field = True

        if target is not None:
            try:
                plan_elements = _plan_glide_for_drill(
                    target=target,
                    target_is_off_field=target_is_off_field,
                    pos_lat=pos_lat, pos_lon=pos_lon,
                    alt_agl=alt_agl,
                    seg_idx=seg_idx, samples=samples,
                    wind_dir=wind_dir_here, wind_speed=wind_speed_here,
                    wind_profile_data=wind_profile_data,
                    aircraft_name=aircraft_name,
                    engine_name=engine_name,
                    runtime_weight=runtime_weight,
                    oat_f=oat_f, altimeter_inhg=altimeter_inhg,
                    ground_elev_ft=ground_elev_ft,
                )
                elements.extend(plan_elements)
            except Exception as e:
                # Don't let a planner failure break the polygon render.
                elements.append(dl.CircleMarker(
                    center=[pos_lat + 0.0001, pos_lon],
                    radius=2, color="#94a3b8", fill=False, opacity=0.0,
                    children=dl.Tooltip(f"Planner failed: {e}"),
                ))

        return elements

    # ===========================================================================
    # Destination VFR pattern — dedicated render callback
    #
    # Why a separate callback (vs putting this back in compute_and_render):
    #   The route runway dropdown's value mirrors into the always-present
    #   `route-runway-select` Store. If THAT Store were an Input to
    #   compute_and_render (which writes route-result-store), changing
    #   the runway would trigger compute, which writes the result store,
    #   which fires populate_dest_runway_options, which sets the dropdown
    #   value, which fires the mirror, which updates the Store —
    #   a 4-step dependency cycle Dash refuses to register.
    #
    # Solution: separate this rendering into its own layer + callback.
    # The pattern updates whenever the route result, the runway choice,
    # or the wind changes — all without touching the route geometry.
    # ===========================================================================
    @app.callback(
        Output("route-dest-pattern-layer", "children"),
        Input("route-result-store", "data"),
        Input("route-runway-select", "data"),
        Input("route-show-destination-pattern", "data"),
        State("env-wind-dir", "value"),
        State("env-wind-speed", "value"),
        State("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def render_destination_pattern(route_store, runway_override,
                                    show_pill, wind_dir, wind_speed,
                                    aircraft_name):
        if not route_store:
            return []
        try:
            want = bool(show_pill and "on" in show_pill)
        except (TypeError, ValueError):
            want = False
        if not want:
            return []

        from core.data_loader import airport_data as _airports
        wps = route_store.get("waypoints") or []
        if len(wps) < 2:
            return []
        dest_id = wps[-1]
        ap = next((a for a in _airports if a.get("id") == dest_id), None)
        if not ap:
            return []

        from callbacks.maneuvers.pattern import (
            _runway_ends_for, _pick_wind_favored_end,
            build_pattern_geometry, pattern_dimensions_for,
        )
        ends = _runway_ends_for(ap)
        if not ends:
            return []

        try:
            wd = float(wind_dir) if wind_dir is not None else 0.0
        except (TypeError, ValueError):
            wd = 0.0
        try:
            ws = float(wind_speed) if wind_speed is not None else 0.0
        except (TypeError, ValueError):
            ws = 0.0

        chosen_end = None
        if runway_override:
            chosen_end = next(
                (e for e in ends if e.get("id") == runway_override), None)
        if chosen_end is None:
            chosen_end = _pick_wind_favored_end(ends, wd, ws) or ends[0]

        pub_dir = chosen_end.get("pattern_direction")
        pat_dir = pub_dir if pub_dir in ("left", "right") else "left"
        pat_dir_label = ("published" if pub_dir
                         else "default LEFT — verify supplement")

        ac_for_pat = aircraft_data.get(aircraft_name) if aircraft_name else None
        dims = pattern_dimensions_for(ac_for_pat)

        # Auto-select entry method based on the inbound route's
        # arrival direction relative to the pattern side. Same
        # decision tree as in compute_and_render — kept in sync via
        # `dest_pattern_meta.entry_method` in the result store.
        # Falls back to recomputing here if metadata is missing.
        dest_meta = route_store.get("dest_pattern_meta") or {}
        entry_method = dest_meta.get("entry_method") or "45_downwind"

        field_elev = float(ap.get("elevation_ft") or 0.0)
        geo = build_pattern_geometry(
            runway_end=chosen_end,
            pattern_dir=pat_dir,
            entry_method=entry_method,
            tpa_agl=1000.0,
            pattern_leg_nm=dims["pattern_leg_nm"],
            final_leg_nm=dims["final_leg_nm"],
            field_elev_ft=field_elev,
        )

        # PRE-LEG-RENDER: when the route's last checkpoint is within
        # 10 NM of the destination, snap the entry leg to start AT
        # that checkpoint instead of the artificial 1.5-NM anchor.
        # The pilot then flies cp → downwind midfield as one clean
        # 45° leg rather than detouring to a fictional point. We
        # mutate geo HERE (before the leg-render loop below) so the
        # rendered entry polyline matches.
        wps_pre = route_store.get("waypoints") or []
        cps_pre = route_store.get("checkpoints") or []
        last_cp_pre = None
        if cps_pre and len(wps_pre) >= 2:
            dest_leg_idx = len(wps_pre) - 2
            cps_in_last_leg = [
                c for c in cps_pre
                if c.get("leg_idx") == dest_leg_idx
            ]
            if cps_in_last_leg:
                last_cp_pre = cps_in_last_leg[-1]
        if last_cp_pre:
            _dlat = float(ap.get("lat"))
            _dlon = float(ap.get("lon"))
            _clat = float(last_cp_pre["lat"])
            _clon = float(last_cp_pre["lon"])
            _dn = (_clat - _dlat) * 60.0
            _de = ((_clon - _dlon) * 60.0
                   * math.cos(math.radians(_dlat)))
            _cp_to_dest = math.hypot(_dn, _de)
            if _cp_to_dest <= 10.0:
                # Find downwind midpoint, then re-anchor the entry
                # leg to start at the last cp.
                _dw_first = None
                for _ld in geo["legs"]:
                    if _ld["name"] == "downwind" and _ld["positions"]:
                        _dw_first = _ld["positions"][0]
                        break
                if _dw_first:
                    for _ld in geo["legs"]:
                        if _ld["name"] == "entry":
                            _ld["positions"] = [
                                [_clat, _clon],
                                [float(_dw_first[0]),
                                 float(_dw_first[1])],
                            ]
                            break

        LEG_COLOR = {"entry": "#0d59f2", "downwind": "#16a34a",
                     "base": "#16a34a", "final": "#16a34a"}
        LEG_DASH = {"entry": "8,8"}

        out: list = []
        for leg_data in geo["legs"]:
            out.append(dl.Polyline(
                positions=leg_data["positions"],
                color=LEG_COLOR.get(leg_data["name"], "#16a34a"),
                weight=3,
                opacity=0.9,
                dashArray=LEG_DASH.get(leg_data["name"]),
                children=dl.Tooltip(
                    f"Dest pattern · {leg_data['name']} · "
                    f"Rwy {chosen_end.get('id')} "
                    f"{pat_dir.upper()} ({pat_dir_label})"
                ),
            ))

        # === 10 NM CTAF point on the inbound route + connector ===
        # CTAF point sits on the LAST LEG of the route at 10 NM from
        # destination — that's the AC 90-66B §11.5 announcement
        # location. From there, draw a SOLID amber connector to the
        # pattern's entry anchor (whichever entry method was chosen).
        # Solid rather than dashed: this IS the planned flight path
        # (vector + descent), not just a procedural hint.
        pat_entry_anchor = None
        pat_downwind_mid = None
        for leg_data in geo["legs"]:
            if leg_data["name"] == "entry" and leg_data["positions"]:
                pat_entry_anchor = leg_data["positions"][0]
            elif leg_data["name"] == "downwind" and leg_data["positions"]:
                pat_downwind_mid = leg_data["positions"][0]

        wps = route_store.get("waypoints") or []
        if pat_entry_anchor and len(wps) >= 2:
            # Pattern transition origin: AC 90-66B §11.5 wants the
            # CTAF call NLT 10 NM out. If the last AUTO-CHECKPOINT
            # is CLOSER than 10 NM to the destination, use that
            # checkpoint as the transition origin instead — the
            # pilot is already there as the last pre-pattern fix.
            # Otherwise use the 10-NM projection along the inbound
            # course from the previous user waypoint (= origin of
            # the last leg in the bent chain).
            dest_lat = float(ap["lat"])
            dest_lon = float(ap["lon"])
            cps_store = route_store.get("checkpoints") or []
            last_cp = None
            if cps_store:
                # Last checkpoint in the destination's leg.
                dest_leg_idx = len(wps) - 2
                cps_in_last_leg = [
                    c for c in cps_store
                    if c.get("leg_idx") == dest_leg_idx
                ]
                if cps_in_last_leg:
                    # The last one (highest cumulative_nm) is closest
                    # to destination.
                    last_cp = cps_in_last_leg[-1]

            if last_cp:
                last_cp_lat = float(last_cp["lat"])
                last_cp_lon = float(last_cp["lon"])
                # Distance from last checkpoint to destination.
                dn = (last_cp_lat - dest_lat) * 60.0
                de = ((last_cp_lon - dest_lon) * 60.0
                      * math.cos(math.radians(dest_lat)))
                cp_to_dest_nm = math.hypot(dn, de)
            else:
                last_cp_lat = None
                last_cp_lon = None
                cp_to_dest_nm = None

            # If the last checkpoint is within 10 NM of destination,
            # the entry leg above has ALREADY been snapped to start
            # at that checkpoint (pre-leg-render block). The CTAF
            # marker just sits at the same point — no separate
            # amber connector needed since the entry leg itself is
            # the transition path from cp to downwind midfield.
            use_cp_as_anchor = (
                last_cp_lat is not None
                and cp_to_dest_nm is not None
                and cp_to_dest_nm <= 10.0
            )
            if use_cp_as_anchor:
                ctaf_lat, ctaf_lon = last_cp_lat, last_cp_lon
                origin_label = f"final cp ({last_cp.get('ident','?')})"
                # Mark this case so the connector polyline below is
                # skipped (the entry leg IS the connector now).
                skip_connector = True
            else:
                skip_connector = False
                # Fall back to 10-NM projection along inbound course
                # from the previous user waypoint.
                prev_id = wps[-2]
                prev_ap = next(
                    (a for a in _airports if a.get("id") == prev_id),
                    None,
                )
                if prev_ap:
                    prev_lat = float(prev_ap["lat"])
                    prev_lon = float(prev_ap["lon"])
                else:
                    prev_lat, prev_lon = dest_lat, dest_lon
                dn = (prev_lat - dest_lat) * 60.0
                de = ((prev_lon - dest_lon) * 60.0
                      * math.cos(math.radians(dest_lat)))
                leg_len_nm = math.hypot(dn, de)
                if leg_len_nm > 0.5:
                    f = min(1.0, 10.0 / leg_len_nm)
                    ctaf_lat = dest_lat + (prev_lat - dest_lat) * f
                    ctaf_lon = dest_lon + (prev_lon - dest_lon) * f
                else:
                    ctaf_lat, ctaf_lon = prev_lat, prev_lon
                origin_label = "10 NM out"

            out.append(dl.CircleMarker(
                center=[ctaf_lat, ctaf_lon],
                radius=7, color="#f59e0b",
                fill=True, fillColor="#fef3c7", fillOpacity=1.0,
                weight=2,
                children=dl.Tooltip(
                    f"Pattern transition origin: {origin_label}. "
                    "AC 90-66B §11.5: announce position + intentions "
                    "on CTAF here; from here, fly the amber "
                    "transition to the pattern entry."),
            ))

            # Skip the amber connector polyline when the entry leg
            # itself already starts at the transition origin (last
            # checkpoint case). Drawing both would just duplicate the
            # line.
            if not skip_connector:
                entry_label = entry_method.replace("_", " ")
                out.append(dl.Polyline(
                    positions=[[ctaf_lat, ctaf_lon], pat_entry_anchor],
                    color="#f59e0b", weight=4, opacity=0.95,
                    children=dl.Tooltip(
                        f"Pattern transition · {entry_label} entry from "
                        f"{origin_label}. "
                        f"Fly this leg descending to TPA (1000 AGL)."),
                ))

        return out

    # ===========================================================================
    # D2-5b: Click-to-place checkpoint editing
    #
    # dash-leaflet 1.0.15's Marker doesn't push the dragged `position`
    # prop back to Dash (verified by grepping the JS bundle — there's
    # no setProps({position:...}) anywhere despite the metadata
    # marking it MUTABLE). So drag-to-move is out.
    #
    # Workaround: two-click UX. Click a checkpoint marker → enters
    # "edit mode" for that ident (Store carries the active ident).
    # Click anywhere on the map → captures the latlng, writes it
    # into route-checkpoint-edits for the active ident, clears the
    # active state. Bent route + nav log auto-recompute via the
    # existing chain (route-checkpoint-edits is an Input to
    # compute_and_render).
    #
    # Click again on the same marker → cancels edit mode.

    @app.callback(
        Output("route-checkpoint-edit-active", "data"),
        Input({"type": "cp-marker", "ident": ALL}, "n_clicks"),
        State({"type": "cp-marker", "ident": ALL}, "id"),
        State("route-checkpoint-edit-active", "data"),
        prevent_initial_call=True,
    )
    def mark_checkpoint_for_edit(n_clicks_list, ids, current_active):
        # Find which marker was just clicked (n_clicks went up).
        # We use ctx.triggered_id which gives us the dict id directly.
        trig = ctx.triggered_id
        if not trig or not isinstance(trig, dict):
            return no_update
        ident = trig.get("ident")
        if not ident:
            return no_update
        # Toggle off if same ident is already active.
        if current_active == ident:
            return None
        return ident

    @app.callback(
        Output("route-checkpoint-edits", "data", allow_duplicate=True),
        Output("route-checkpoint-edit-active", "data", allow_duplicate=True),
        Input("map", "clickData"),
        State("route-checkpoint-edit-active", "data"),
        State("route-checkpoint-edits", "data"),
        prevent_initial_call=True,
    )
    def place_checkpoint_on_map_click(click_data, active_ident,
                                       current_edits):
        # Only consume the click if we have an active checkpoint and
        # the click carried a latlng. Otherwise leave the click for
        # the existing click-to-build-waypoint callback.
        if not active_ident:
            return no_update, no_update
        if not click_data or "latlng" not in click_data:
            return no_update, no_update
        latlng = click_data.get("latlng") or {}
        lat = latlng.get("lat")
        lon = latlng.get("lng")
        if lat is None or lon is None:
            return no_update, no_update
        edits = dict(current_edits or {})
        edits[active_ident] = {"lat": float(lat), "lon": float(lon)}
        return edits, None  # write edit + clear active state

    # ===========================================================================
    # VFR Checkpoints render callback (D2-2)
    # ===========================================================================
    @app.callback(
        Output("route-checkpoints-layer", "children"),
        Input("route-result-store", "data"),
        Input("route-show-checkpoints", "data"),
        Input("route-checkpoint-edit-active", "data"),
        prevent_initial_call=True,
    )
    def render_checkpoints(route_store, show_pill, edit_active_ident):
        if not route_store:
            return []
        try:
            want = bool(show_pill and "on" in show_pill)
        except (TypeError, ValueError):
            want = False
        if not want:
            return []
        checkpoints = route_store.get("checkpoints") or []
        if not checkpoints:
            return []

        KIND_COLOR = {
            "airport": "#1d4ed8",  # deep blue — landable
            "vor":     "#16a34a",  # green — radio nav
            "ndb":     "#15803d",
            "fix":     "#94a3b8",  # gray — IFR-style fix
            "city":    "#b45309",  # amber — visual landmark
            "river":   "#0e7490",
        }
        KIND_LABEL = {
            "airport": "Airport",
            "vor": "VOR",
            "ndb": "NDB",
            "fix": "Fix",
            "city": "Town",
            "river": "River",
        }

        out: list = []
        from dash import html as _html
        for i, cp in enumerate(checkpoints):
            color = KIND_COLOR.get(cp.get("kind"), "#0d59f2")
            label = KIND_LABEL.get(cp.get("kind"), cp.get("kind", "?"))
            ident = cp.get("ident", "?")
            cum_nm = cp.get("cumulative_nm", 0)
            ete = cp.get("ete_min", 0)
            mc = cp.get("magnetic_bearing", 0)
            margin = cp.get("glide_margin_ft", 0)
            divert = cp.get("nearest_divert_id", "")
            divert_nm = cp.get("nearest_divert_nm", 0)

            margin_style = ("color: #16a34a"
                            if margin > 500 else
                            "color: #b45309" if margin > 0 else
                            "color: #dc2626")

            tooltip = _html.Div([
                _html.Div(
                    f"#{i + 1}: {ident}  ({label})",
                    style={"fontWeight": "600", "fontSize": "12px"},
                ),
                _html.Div(cp.get("name", ""), style={"fontSize": "11px",
                                                       "color": "#64748b"}),
                _html.Div(f"{cum_nm:.1f} NM total · MC {mc:03.0f}° · ETE {ete:.1f} min",
                            style={"fontSize": "11px", "marginTop": "4px"}),
                _html.Div(
                    f"Nearest divert: {divert} ({divert_nm:.1f} NM) · "
                    f"margin {margin:+.0f} ft AGL",
                    style={"fontSize": "11px", "marginTop": "2px"},
                ),
                _html.Div(cp.get("notes", ""),
                            style={"fontSize": "10px", "color": "#94a3b8",
                                   "marginTop": "2px"}),
            ])

            # Click-to-place marker. dash-leaflet 1.0.15's Marker
            # doesn't push dragged position back to Dash, so we use
            # n_clicks instead of dragging. Visual cue: when this
            # marker is the active edit target, render it bigger
            # with an animated dashed yellow ring.
            is_active = (edit_active_ident == ident)
            if is_active:
                # Larger, with yellow ring and inner colored core.
                svg = (
                    "<svg xmlns='http://www.w3.org/2000/svg' "
                    "width='26' height='26'>"
                    "<circle cx='13' cy='13' r='12' fill='none' "
                    "stroke='#f59e0b' stroke-width='3' "
                    "stroke-dasharray='4 3'/>"
                    f"<circle cx='13' cy='13' r='7' fill='{color}' "
                    "stroke='#1e293b' stroke-width='2'/>"
                    "</svg>"
                )
                icon_size = [26, 26]
                icon_anchor = [13, 13]
                hover_label = (
                    f"<b>#{i + 1} {ident} — EDIT MODE</b><br>"
                    "Click anywhere on the map to relocate this "
                    "checkpoint. Click the marker again to cancel."
                )
            else:
                svg = (
                    "<svg xmlns='http://www.w3.org/2000/svg' "
                    "width='18' height='18'>"
                    f"<circle cx='9' cy='9' r='7' fill='{color}' "
                    "stroke='#1e293b' stroke-width='2'/>"
                    "</svg>"
                )
                icon_size = [18, 18]
                icon_anchor = [9, 9]
                hover_label = None
            data_uri = ("data:image/svg+xml;utf8," + svg.replace("#", "%23"))

            marker_tooltip = tooltip
            if hover_label:
                marker_tooltip = _html.Div([
                    _html.Div(hover_label, style={
                        "padding": "4px",
                        "color": "#b45309",
                        "fontWeight": "600",
                        "fontSize": "11px",
                        "background": "rgba(254,243,199,0.95)",
                        "borderRadius": "3px",
                    }),
                    tooltip,
                ])

            out.append(dl.Marker(
                id={"type": "cp-marker", "ident": ident},
                position=[cp["lat"], cp["lon"]],
                icon={
                    "iconUrl": data_uri,
                    "iconSize": icon_size,
                    "iconAnchor": icon_anchor,
                    "tooltipAnchor": [icon_size[0] // 2, 0],
                },
                children=dl.Tooltip(marker_tooltip, sticky=True),
            ))
            # Numeric label next to the marker.
            out.append(dl.Marker(
                position=[cp["lat"], cp["lon"]],
                icon={
                    "iconUrl":
                        "data:image/svg+xml;utf8,"
                        "<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/>",
                    "iconSize": [1, 1],
                    "iconAnchor": [0, 0],
                },
                children=dl.Tooltip(
                    f"#{i + 1} {ident}", permanent=True, direction="right",
                    offset=[10, 0],
                    className="route-checkpoint-label",
                ),
            ))

        return out

    # === D3-1b + D3-3: Chart-layer picker ===
    # Five mountable layers, exactly one (or two) visible:
    #   imagery (Esri sat) — base, default
    #   openaip            — transparent aeronautical-data overlay
    #   vfrsec/tac/ifrlow  — self-hosted FAA chart base (replaces imagery)
    # Returns (imagery, openaip, sectional, tac, ifr_low) opacities.
    @app.callback(
        Output("map-tile-imagery", "opacity"),
        Output("map-tile-openaip", "opacity"),
        Output("map-tile-vfrsec", "opacity"),
        Output("map-tile-tac", "opacity"),
        Output("map-tile-ifrlow", "opacity"),
        Input("map-chart-layer", "value"),
        prevent_initial_call=False,
    )
    def switch_chart_layer(choice):
        if choice == "openaip":
            return 1, 1, 0, 0, 0
        if choice == "sectional":
            return 0, 0, 1, 0, 0
        if choice == "tac":
            return 0, 0, 0, 1, 0
        if choice == "ifrlow":
            return 0, 0, 0, 0, 1
        # imagery default
        return 1, 0, 0, 0, 0

    # === Airspace overlay (Phase 7f-C) ===
    #
    # Renders Class B/C/D + SUA + TFR polygons clipped to the current
    # map viewport. Fires whenever the user pans / zooms (map.bounds
    # changes) OR toggles the airspace checklist. Gated on the active
    # maneuver being "route" so the heavy spatial lookup doesn't run
    # while the user is flying a maneuver.
    @app.callback(
        Output("airspace-layer", "children"),
        Input("map", "bounds"),
        Input("map", "zoom"),
        Input("route-show-airspace", "value"),
        Input("maneuver-select", "value"),
        prevent_initial_call=False,
    )
    def render_airspace_overlay(bounds, zoom, show_layers, maneuver):
        # Off when not on the route planner.
        if maneuver != "route":
            return []
        if not show_layers:
            return []
        if not bounds or len(bounds) != 2:
            return []
        # dash-leaflet bounds = [[south, west], [north, east]].
        try:
            (south, west), (north, east) = bounds
            zoom_int = int(zoom or 0)
        except (ValueError, TypeError):
            return []
        # Convert to GeoJSON-order bbox (minlon, minlat, maxlon, maxlat).
        bbox = (float(west), float(south), float(east), float(north))
        # Don't ship the country's-worth-of-airspace when zoomed all
        # the way out — past a continent-scale viewport the polygons
        # blob into solid color and Leaflet's rendering cost spikes.
        if (bbox[2] - bbox[0]) > 25.0 or (bbox[3] - bbox[1]) > 18.0:
            return []
        from core.airspace import (styled_in_bbox, format_alt_band,
                                     schedule_active_at)
        active_layers = list(show_layers)
        # SUA at continental zoom carpets the screen and the schedule-
        # aware dimming only adds noise. Drop it until the user is at
        # least at sectional scale.
        if zoom_int < 6 and "sua" in active_layers:
            active_layers.remove("sua")
        recs = styled_in_bbox(bbox, active_layers)
        # Cap the render so the map stays interactive even when a
        # viewport intersects hundreds of airspaces. Sort by severity
        # so the safety-critical layers (TFR, Prohibited, Restricted,
        # Class B) survive the cap.
        _SEVERITY = {"TFR": 0, "P": 1, "R": 2, "B": 3, "C": 4, "D": 5,
                     "MOA": 6, "W": 7, "D-sua": 8, "A": 9}
        recs.sort(key=lambda x: _SEVERITY.get(x.get("type_code"), 99))
        MAX_POLYS = 200
        if len(recs) > MAX_POLYS:
            recs = recs[:MAX_POLYS]
        # Permanent altitude labels are useful but visually noisy when
        # many airspaces overlap. Gate by both zoom AND count — at
        # zoom < 10 the labels stack on top of each other illegibly;
        # past ~15 polygons in view even at zoom 10 it's too busy.
        # Pilot still gets altitudes on hover via the sticky tooltip.
        show_band_labels = zoom_int >= 10 and len(recs) <= 15
        # Cold-state dimming follows the same zoom threshold — at low
        # zoom the dim/dash interplay looks like flicker; at ≥7 it's
        # a meaningful "this MOA isn't hot" cue.
        dim_inactive = zoom_int >= 7
        # Evaluate "is this airspace hot right now?" once per render.
        # Records without a schedule (Class B 24/7, most P/R, MOAs with
        # only NOTAM activation) are treated as always-active.
        now_utc = datetime.utcnow()
        polygons = []
        for r in recs:
            geom = r["geometry"]
            style = r["style"]
            alt_band = format_alt_band(r)
            sheets = r.get("schedule_sheets") or []
            # Only flag inactive when we have an actual schedule that
            # says so. No schedule → "active" (or unknown — safer to
            # assume hot).
            active = True if not sheets else schedule_active_at(sheets, now_utc)
            label = f"{style['label']} — {r['name']}  {alt_band}"
            if not active:
                label = f"{label}  · COLD"
            # Phase A3-fwup — append schedule summary when the airspace
            # has a known schedule attached.
            if r.get("schedule_summary"):
                label += f"  · {r['schedule_summary']}"
            # Inactive polygons dim down + dash the outline so a cold
            # MOA is visually distinct from a hot MOA without losing
            # type identity (color stays). Only applied at zoom ≥ 7
            # because at wider zoom the dim/dash flicker between
            # different airspaces in different regions reads as noise
            # rather than information.
            poly_color = style["color"]
            poly_weight = style["weight"]
            poly_dash = style.get("dashArray")
            poly_fill = style["fillColor"]
            poly_fill_op = style["fillOpacity"]
            poly_stroke_op = 1.0
            if not active and dim_inactive:
                poly_fill_op = poly_fill_op * 0.4
                poly_stroke_op = 0.55
                # Force a dash even on Prohibited/Class B style solids
                # so the cold-state visual cue is consistent.
                poly_dash = poly_dash or "4,4"
            t = geom.get("type")
            rings_to_draw: list[list] = []
            if t == "Polygon":
                # Outer ring is index 0; holes ignored for visual.
                rings_to_draw.append(geom["coordinates"][0])
            elif t == "MultiPolygon":
                for poly in geom["coordinates"]:
                    if poly:
                        rings_to_draw.append(poly[0])
            for ring in rings_to_draw:
                # GeoJSON is [lon, lat]; Leaflet wants [lat, lon].
                positions = [[pt[1], pt[0]] for pt in ring]
                # Polygon children: hover tooltip + (at zoom ≥ 8) a
                # permanent altitude-band label. Using a permanent
                # Tooltip in centered-direction avoids dl.DivMarker
                # entirely — that component has a known cleanup crash
                # in dash-leaflet 1.0.15 when many markers are removed
                # on viewport pan.
                children: list = [dl.Tooltip(label, sticky=True)]
                if show_band_labels:
                    ceil_s = alt_band.split(" → ")[1]
                    floor_s = alt_band.split(" → ")[0]
                    band_text = f"{ceil_s} / {floor_s}"
                    cls = "asp-band-tooltip"
                    if not active:
                        cls += " asp-band-cold"
                    children.append(dl.Tooltip(
                        band_text,
                        permanent=True,
                        direction="center",
                        className=cls,
                    ))
                polygons.append(dl.Polygon(
                    positions=positions,
                    color=poly_color,
                    weight=poly_weight,
                    opacity=poly_stroke_op,
                    dashArray=poly_dash,
                    fillColor=poly_fill,
                    fillOpacity=poly_fill_op,
                    children=children,
                ))
        return polygons

    # === NAVAID + fix overlay (Phase 7N-e) ===
    #
    # Drops a CircleMarker per NAVAID or fix inside the current
    # viewport. Zoom-gated so 17k fixes don't carpet the map at
    # continent scale: VORs visible at zoom ≥ 7, fixes at zoom ≥ 9.
    # Gated on maneuver-select == 'route' so the heavy bbox filter
    # doesn't run during maneuver work.
    @app.callback(
        Output("waypoints-layer", "children"),
        Input("map", "bounds"),
        Input("map", "zoom"),
        Input("route-show-waypoints", "value"),
        Input("maneuver-select", "value"),
        prevent_initial_call=False,
    )
    def render_waypoints_overlay(bounds, zoom, show_layers, maneuver):
        if maneuver != "route":
            return []
        if not show_layers:
            return []
        if not bounds or len(bounds) != 2:
            return []
        try:
            (south, west), (north, east) = bounds
            zoom_int = int(zoom or 0)
        except (ValueError, TypeError):
            return []
        # Zoom gates: showing 2200 VORs at zoom 4 is a wall of dots.
        show_vors = "vor" in show_layers and zoom_int >= 7
        show_fixes = "fix" in show_layers and zoom_int >= 9
        if not show_vors and not show_fixes:
            return []
        markers: list = []

        def _in_bbox(lat, lon):
            return south <= lat <= north and west <= lon <= east

        if show_vors:
            # Cap at 200 visible markers — even zoomed in, no viewport
            # has > ~50 NAVAIDs in CONUS; cap is a safety net.
            count = 0
            for nv in navaid_data:
                lat = nv.get("lat")
                lon = nv.get("lon")
                if lat is None or lon is None:
                    continue
                if not _in_bbox(lat, lon):
                    continue
                freq = nv.get("freq_mhz")
                freq_str = f"  {freq:.2f}" if isinstance(freq, (int, float)) else ""
                label = f"{nv.get('ident', '?')} {freq_str} — {nv.get('name', '')}"
                markers.append(dl.CircleMarker(
                    center=[lat, lon],
                    radius=5,
                    color="#1d4ed8",
                    weight=2,
                    fillColor="#bfdbfe",
                    fillOpacity=0.85,
                    children=dl.Tooltip(label, sticky=True),
                ))
                count += 1
                if count >= 200:
                    break
        if show_fixes:
            count = 0
            for fx in fix_data:
                lat = fx.get("lat")
                lon = fx.get("lon")
                if lat is None or lon is None:
                    continue
                if not _in_bbox(lat, lon):
                    continue
                ident = fx.get("ident", "?")
                markers.append(dl.CircleMarker(
                    center=[lat, lon],
                    radius=3,
                    color="#7c3aed",
                    weight=1,
                    fillColor="#ddd6fe",
                    fillOpacity=0.85,
                    children=dl.Tooltip(ident, sticky=True),
                ))
                count += 1
                if count >= 400:
                    break
        return markers

    # === Airports overlay (Phase A1 follow-up) ===
    #
    # User wanted a way to declutter the map by toggling airport
    # categories. Renders airport markers visible in the current
    # viewport, gated by the `map-show-airports` checklist (large /
    # medium / small / heliport / seaplane). Zoom-gated for performance
    # — small airports + heliports only appear when zoomed in enough
    # that they wouldn't carpet the map.
    @app.callback(
        Output("airports-layer", "children"),
        Input("map", "bounds"),
        Input("map", "zoom"),
        Input("map-show-airports", "value"),
        prevent_initial_call=False,
    )
    def render_airports_overlay(bounds, zoom, show_types):
        if not show_types or not bounds or len(bounds) != 2:
            return []
        try:
            (south, west), (north, east) = bounds
            zoom_int = int(zoom or 0)
        except (ValueError, TypeError):
            return []

        # Zoom gates per category — large airports show even at
        # CONUS scale, smaller categories only when the user has
        # zoomed in enough to actually use them.
        ZOOM_FOR = {
            "large": 5,
            "medium": 6,
            "small": 8,
            "heliport": 9,
            "seaplane": 9,
        }
        # Map the OpenStreetMap-derived `type` field to our category.
        # `our_airports`-style data uses: large_airport, medium_airport,
        # small_airport, heliport, seaplane_base.
        TYPE_TO_CAT = {
            "large_airport": "large",
            "medium_airport": "medium",
            "small_airport": "small",
            "heliport": "heliport",
            "seaplane_base": "seaplane",
        }
        STYLE_FOR = {
            "large":   {"radius": 5, "color": "#1e3a8a", "fill": "#3b82f6"},
            "medium":  {"radius": 4, "color": "#1e40af", "fill": "#60a5fa"},
            "small":   {"radius": 3, "color": "#374151", "fill": "#9ca3af"},
            "heliport": {"radius": 3, "color": "#7c2d12", "fill": "#fb923c"},
            "seaplane": {"radius": 3, "color": "#0e7490", "fill": "#67e8f9"},
        }
        active_cats = {c for c in show_types
                       if zoom_int >= ZOOM_FOR.get(c, 99)}
        if not active_cats:
            return []

        # Per-airport cap to keep render cost bounded at low zooms.
        CAP = 800
        markers: list = []
        count = 0
        for ap in airport_data:
            try:
                lat = float(ap.get("lat"))
                lon = float(ap.get("lon"))
            except (TypeError, ValueError):
                continue
            if not (south <= lat <= north and west <= lon <= east):
                continue
            cat = TYPE_TO_CAT.get(ap.get("type") or "", None)
            if cat is None or cat not in active_cats:
                continue
            style = STYLE_FOR[cat]
            ap_id = ap.get("id") or ap.get("icao") or "?"
            ap_name = ap.get("name") or ""
            elev = ap.get("elevation_ft")
            label = f"{ap_id} — {ap_name}"
            if isinstance(elev, (int, float)):
                label += f"  ({elev:.0f} ft)"
            markers.append(dl.CircleMarker(
                center=[lat, lon],
                radius=style["radius"],
                color=style["color"],
                weight=1,
                fillColor=style["fill"],
                fillOpacity=0.85,
                children=dl.Tooltip(label, sticky=True),
            ))
            count += 1
            if count >= CAP:
                break
        return markers

    # === Save / Open route (Phase A5) ===
    #
    # Save: serialize all the planning inputs (waypoints + perf inputs +
    # aircraft selection + env) into a JSON file. The pilot keeps the
    # file locally; opening it later re-populates the same form.
    # Wind / weather snapshot is not persisted — it changes hourly and
    # re-pulling live is the right behavior.
    @app.callback(
        Output("route-download", "data"),
        Input("route-save-btn", "n_clicks"),
        State("route-waypoints", "value"),
        State("route-cruise-alt", "value"),
        State("route-tas", "value"),
        State("route-cruise-ias", "value"),
        State("route-glide-ratio", "value"),
        State("route-glide-ias", "value"),
        State("route-climb-ias", "value"),
        State("route-engine-out-mode", "value"),
        State("route-slope-threshold", "value"),
        State("aircraft-select", "value"),
        State("fuel-load", "value"),
        prevent_initial_call=True,
    )
    def save_route(n_clicks, waypoint_ids, cruise_alt, tas, cruise_ias,
                   glide_ratio, glide_ias, climb_ias,
                   engine_out_mode, slope_threshold,
                   aircraft_name, fuel_load_gal):
        if not n_clicks:
            raise PreventUpdate
        if not waypoint_ids:
            raise PreventUpdate
        payload = {
            "schema": "tallyaero.route.v1",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "aircraft": aircraft_name,
            "waypoints": waypoint_ids,
            "perf": {
                "cruise_alt_ft": cruise_alt,
                "tas_kt": tas,
                "cruise_ias_kt": cruise_ias,
                "glide_ratio": glide_ratio,
                "glide_ias_kt": glide_ias,
                "climb_ias_kt": climb_ias,
                "engine_out_mode": engine_out_mode,
                "slope_threshold_deg": slope_threshold,
            },
            "fuel_load_gal": fuel_load_gal,
        }
        # Filename: TYY_origin-dest_YYYYMMDD.json so a pilot can keep
        # a folder of routes and recognize them at a glance.
        wps = "-".join(w.replace("/", "_")[:6] for w in (waypoint_ids[:1]
                                                           + waypoint_ids[-1:]))
        fname = f"tallyaero_{wps}_{datetime.now().strftime('%Y%m%d')}.json"
        import json as _json
        return {"content": _json.dumps(payload, indent=2),
                "filename": fname, "type": "application/json"}

    # Open: parse the uploaded JSON and push waypoints + perf inputs
    # back into their respective controls. Aircraft selection is also
    # restored (the user can override afterward).
    @app.callback(
        Output("route-waypoints", "value", allow_duplicate=True),
        Output("route-cruise-alt", "value", allow_duplicate=True),
        Output("route-tas", "value", allow_duplicate=True),
        Output("route-cruise-ias", "value", allow_duplicate=True),
        Output("route-glide-ratio", "value", allow_duplicate=True),
        Output("route-glide-ias", "value", allow_duplicate=True),
        Output("route-climb-ias", "value", allow_duplicate=True),
        Output("route-engine-out-mode", "value", allow_duplicate=True),
        Output("route-slope-threshold", "value", allow_duplicate=True),
        Output("aircraft-select", "value", allow_duplicate=True),
        Input("route-upload", "contents"),
        State("route-upload", "filename"),
        prevent_initial_call=True,
    )
    def open_route(contents, filename):
        if not contents:
            raise PreventUpdate
        import base64
        import json as _json
        # dcc.Upload returns 'data:application/json;base64,<payload>'
        try:
            _, b64 = contents.split(",", 1)
            data = _json.loads(base64.b64decode(b64).decode("utf-8"))
        except Exception:
            raise PreventUpdate
        if data.get("schema") not in (None, "tallyaero.route.v1"):
            raise PreventUpdate
        perf = data.get("perf") or {}
        return (
            data.get("waypoints") or [],
            perf.get("cruise_alt_ft"),
            perf.get("tas_kt"),
            perf.get("cruise_ias_kt"),
            perf.get("glide_ratio"),
            perf.get("glide_ias_kt"),
            perf.get("climb_ias_kt"),
            perf.get("engine_out_mode"),
            perf.get("slope_threshold_deg"),
            data.get("aircraft"),
        )
