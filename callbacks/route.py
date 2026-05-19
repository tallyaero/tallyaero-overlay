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

from dash import Input, Output, State, html, dcc, ctx, no_update
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
from core.airspace import route_crossings, TYPE_STYLES
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
                   density_altitude_ft=None):
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
    for leg in legs:
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
            verdict = "PIERCE" if x["pierces"] else "over/under"
            verdict_cls = ("nav-log-as-pierce" if x["pierces"]
                           else "nav-log-as-overunder")
            return html.Tr([
                html.Td(verdict, className=verdict_cls),
                html.Td(html.Span(label,
                                  className="nav-log-as-chip",
                                  style={"backgroundColor": color,
                                         "color": "#fff"})),
                html.Td(x["name"], className="nav-log-as-name"),
                html.Td(x.get("floor_desc") or "—",
                        className="nav-log-as-alt"),
                html.Td(x.get("ceiling_desc") or "—",
                        className="nav-log-as-alt"),
                html.Td(x.get("eff_times") or "—",
                        className="nav-log-as-times",
                        title=x.get("eff_times") or ""),
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

    return html.Div(className="nav-log-document", children=[
        header_strip,
        form_row,
        foot_strip,
        airspace_block,
        eo_block,
        html.Div("Generated by TallyAero Maneuver Overlay · "
                 + datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
                 className="nav-log-footer"),
    ])


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
        trigger = ctx.triggered_id
        if trigger == "nav-log-open-btn":
            return True
        if trigger == "nav-log-close-btn":
            return False
        return is_open

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
                    "route-show-landable"}
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

            # Feed pct_landable_combined into the survivability score
            # via the slope_meta shape it already consumes.
            slope_meta = {
                "pct_landable": mask_meta["pct_landable_combined"],
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
        segs = segment_polyline_by_status(all_samples, statuses_only)
        for seg in segs:
            style = STATUS_STYLE[seg["status"]]
            layer.append(dl.Polyline(
                positions=seg["positions"],
                color=style["color"], weight=style["weight"],
                opacity=style["opacity"],
                children=[dl.Tooltip(STATUS_TIP[seg["status"]])],
            ))

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
        fig.update_layout(
            height=140,
            margin=dict(l=40, r=10, t=10, b=30),
            xaxis_title="Distance (NM)",
            yaxis_title="ft MSL",
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

        # Below-strip = minimal at-a-glance: profile chart + wind chip
        # + "View Nav Log" button. The full nav log (FAA-style
        # checkpoint table + engine-out analysis) lives in the modal
        # opened by the button.
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
            "terrain": {
                "n_conflict": n_conflict,
                "n_marginal": n_marginal,
            },
            "suggested_alt_ft": float(suggested_alt) if suggested_alt else None,
            "airspace": {
                "n_pierce": sum(1 for x in airspace_xings if x["pierces"]),
                "n_under_over": sum(1 for x in airspace_xings if not x["pierces"]),
            },
        }
        return banner, below_strip, nav_log_doc, layer, viewport, store

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
        Input("route-show-airspace", "value"),
        Input("maneuver-select", "value"),
        prevent_initial_call=False,
    )
    def render_airspace_overlay(bounds, show_layers, maneuver):
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
        except (ValueError, TypeError):
            return []
        # Convert to GeoJSON-order bbox (minlon, minlat, maxlon, maxlat).
        bbox = (float(west), float(south), float(east), float(north))
        # Don't ship the country's-worth-of-airspace when zoomed all
        # the way out — past a continent-scale viewport the polygons
        # blob into solid color and Leaflet's rendering cost spikes.
        if (bbox[2] - bbox[0]) > 25.0 or (bbox[3] - bbox[1]) > 18.0:
            return []
        from core.airspace import styled_in_bbox
        recs = styled_in_bbox(bbox, list(show_layers))
        polygons = []
        for r in recs:
            geom = r["geometry"]
            style = r["style"]
            label = (f"{style['label']} — {r['name']}  "
                     f"{r['floor_desc'] or ''} → {r['ceiling_desc'] or ''}")
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
                polygons.append(dl.Polygon(
                    positions=positions,
                    color=style["color"],
                    weight=style["weight"],
                    dashArray=style.get("dashArray"),
                    fillColor=style["fillColor"],
                    fillOpacity=style["fillOpacity"],
                    children=dl.Tooltip(label, sticky=True),
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
