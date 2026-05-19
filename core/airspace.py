"""Airspace data loader + route-crossing math.

Phase 7f-B. Loads the NASR-derived GeoJSON files produced by
data/airspace/build_airspace.py, indexes polygons by bounding box for
fast lookup, and computes which airspaces a given route enters.

The runtime never hits the network — all data is bundled under
data/airspace/. Re-run the build script after each NASR 28-day
cycle to refresh.

Public API:
    load_airspaces() -> dict[str, list[Airspace]]
        Lazy-cached load of all four layers. Keys: class_airspace,
        special_use, tfr, schedule.

    airspaces_in_bbox(bbox, layers=None) -> list[Airspace]
        Quick spatial filter for rendering — returns every airspace
        whose bounding box intersects the requested viewport.

    route_crossings(path, planned_alt_msl_ft, layers=None) -> list[Crossing]
        For each airspace polygon the great-circle path traverses
        AND whose floor/ceiling range overlaps the planned altitude,
        return a Crossing dict (see below) for the Results modal.

Crossing schema (returned by route_crossings):
    {
      "name":        "Charleston Class C",
      "type_code":   "C",      # B/C/D/E for class; SUA: M/P/R/W/A/D
      "kind":        "class" | "sua" | "tfr",
      "floor_ft":    0         # MSL or AGL — see "floor_ref"
      "ceiling_ft":  4000,
      "floor_ref":   "SFC" | "MSL" | "AGL" | "FL",
      "ceiling_ref": ...,
      "floor_desc":  "SFC",    # human-readable from NASR
      "ceiling_desc":"4000 MSL",
      "pierces":     bool,     # True if planned cruise enters the vertical band
      "eff_times":   str | None,  # for SUA — when active
      "controlling_agency": str | None,
    }
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "airspace"

# Color spec — matches sectional chart conventions so the rendered
# map "reads" like a sectional. Keys match the upstream TYPE_CODE /
# CLASS strings exactly (after _classify_feature normalization), so
# the rendering callback can look up styles with O(1) dict access.
TYPE_STYLES = {
    # Class airspaces
    "B":   {"color": "#0050a0", "weight": 2, "dashArray": None,
            "fillColor": "#0050a0", "fillOpacity": 0.04, "label": "Class B"},
    "C":   {"color": "#8b2c8b", "weight": 2, "dashArray": None,
            "fillColor": "#8b2c8b", "fillOpacity": 0.04, "label": "Class C"},
    "D":   {"color": "#0050a0", "weight": 1, "dashArray": "5,3",
            "fillColor": "#0050a0", "fillOpacity": 0.02, "label": "Class D"},
    "E":   {"color": "#8b2c8b", "weight": 1, "dashArray": "1,4",
            "fillColor": "#8b2c8b", "fillOpacity": 0.0,  "label": "Class E"},
    # Special Use (NASR TYPE_CODE is a full word, not a letter)
    "P":   {"color": "#cc0000", "weight": 2, "dashArray": None,
            "fillColor": "#cc0000", "fillOpacity": 0.10, "label": "Prohibited"},
    "R":   {"color": "#cc0000", "weight": 2, "dashArray": "4,4",
            "fillColor": "#cc0000", "fillOpacity": 0.08, "label": "Restricted"},
    "MOA": {"color": "#cc7700", "weight": 1, "dashArray": "6,4",
            "fillColor": "#cc7700", "fillOpacity": 0.04, "label": "MOA"},
    "W":   {"color": "#cc7700", "weight": 1, "dashArray": "4,4",
            "fillColor": "#cc7700", "fillOpacity": 0.04, "label": "Warning"},
    "A":   {"color": "#666666", "weight": 1, "dashArray": "2,4",
            "fillColor": "#666666", "fillOpacity": 0.02, "label": "Alert"},
    "D-sua": {"color": "#cc7700", "weight": 1, "dashArray": "8,2",
              "fillColor": "#cc7700", "fillOpacity": 0.03, "label": "Danger"},
    # TFR — striped red, can't be missed
    "TFR": {"color": "#cc0000", "weight": 3, "dashArray": "8,4",
            "fillColor": "#cc0000", "fillOpacity": 0.15, "label": "TFR"},
}

# Class A is the CONUS-wide cap above FL180; rendering its polygon
# would shade the whole continent. Class E is omnipresent surface-E
# coverage with no chart value at this layer. "Other" is the Mode C
# Veil ring (B-airport identifier). All three are hidden by default.
_CLASS_RENDER_ALLOW = {"B", "C", "D"}
# Likewise for SUA — surface that's interesting to a VFR pilot.
_SUA_RENDER_ALLOW = {"P", "R", "MOA", "W", "A", "D-sua"}


def styled_in_bbox(bbox: tuple[float, float, float, float],
                    layers: list[str]) -> list[dict]:
    """Viewport-clipped + render-filtered list for the map callback.
    `layers` is a list containing any of: 'class', 'sua', 'tfr'.

    Returns records ready to render — each carries its `style` from
    TYPE_STYLES. Records without a known style are dropped.
    """
    want_layers: list[str] = []
    if "class" in layers: want_layers.append("class_airspace")
    if "sua" in layers:   want_layers.append("special_use")
    if "tfr" in layers:   want_layers.append("tfr")
    if not want_layers:
        return []
    raw = airspaces_in_bbox(bbox, layers=want_layers)
    out = []
    for rec in raw:
        kind = rec["kind"]
        code = rec["type_code"]
        if kind == "class" and code not in _CLASS_RENDER_ALLOW:
            continue
        if kind == "sua" and code not in _SUA_RENDER_ALLOW:
            continue
        style = TYPE_STYLES.get(code)
        if style is None:
            continue
        out.append({**rec, "style": style})
    return out


def _coerce_alt(val: Any) -> float | None:
    """NASR LOWER_VAL / UPPER_VAL: -9998 / -9999 = surface,
    99998/99999 = unlimited. Otherwise raw feet."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v < -1000:
        return 0.0  # surface
    if v > 90000:
        return 99999.0  # unlimited
    return v


def _bbox_of_geometry(geom: dict) -> tuple[float, float, float, float] | None:
    """Return (minlon, minlat, maxlon, maxlat). None if empty."""
    if not geom:
        return None
    coords = geom.get("coordinates")
    if not coords:
        return None
    minlon = minlat = float("inf")
    maxlon = maxlat = float("-inf")

    def _walk(c):
        nonlocal minlon, minlat, maxlon, maxlat
        if isinstance(c, (list, tuple)) and len(c) >= 2 and \
                isinstance(c[0], (int, float)):
            lon, lat = c[0], c[1]
            if lon < minlon: minlon = lon
            if lon > maxlon: maxlon = lon
            if lat < minlat: minlat = lat
            if lat > maxlat: maxlat = lat
        else:
            for sub in c:
                _walk(sub)

    _walk(coords)
    if minlon == float("inf"):
        return None
    return (minlon, minlat, maxlon, maxlat)


def _point_in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray-casting. ring is [[lon, lat], ...]."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
                (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lat: float, lon: float, geom: dict) -> bool:
    """Geometry can be Polygon or MultiPolygon."""
    t = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return False
    if t == "Polygon":
        outer = coords[0]
        if not _point_in_ring(lat, lon, outer):
            return False
        for hole in coords[1:]:
            if _point_in_ring(lat, lon, hole):
                return False
        return True
    if t == "MultiPolygon":
        return any(_point_in_polygon(lat, lon, {"type": "Polygon",
                                                  "coordinates": poly})
                    for poly in coords)
    return False


def _classify_feature(layer: str, props: dict) -> tuple[str, str]:
    """Return (kind, type_code) where kind is class/sua/tfr."""
    if layer == "class_airspace":
        return "class", (props.get("CLASS") or "").strip().upper()
    if layer == "tfr":
        return "tfr", "TFR"
    if layer == "special_use":
        code = (props.get("TYPE_CODE") or "").strip().upper()
        # Danger SUA collides with Class D — disambiguate with suffix.
        if code == "D":
            code = "D-sua"
        return "sua", code
    return layer, "?"


def _feature_to_record(layer: str, feat: dict) -> dict | None:
    geom = feat.get("geometry")
    bbox = _bbox_of_geometry(geom)
    if bbox is None:
        return None
    props = feat.get("properties") or {}
    kind, type_code = _classify_feature(layer, props)
    # SUA exposes TIMESOFUSE / CONT_AGENT (not EFF_TIMES / CONTROLLING_AGENCY).
    # Class airspace records have IDENT (the airport identifier) which joins
    # to the schedule table's FAA_ID for hours-of-use lookup.
    eff_times = props.get("TIMESOFUSE") or props.get("EFF_TIMES")
    cont_agent = props.get("CONT_AGENT") or props.get("CONTROLLING_AGENCY")
    return {
        "kind": kind,
        "type_code": type_code,
        "name": props.get("NAME") or props.get("IDENT") or "?",
        "ident": props.get("IDENT") or "",
        "icao_id": props.get("ICAO_ID") or "",
        "city": props.get("CITY") or "",
        "floor_ft": _coerce_alt(props.get("LOWER_VAL")),
        "ceiling_ft": _coerce_alt(props.get("UPPER_VAL")),
        "floor_ref": (props.get("LOWER_UOM") or "").upper() or None,
        "ceiling_ref": (props.get("UPPER_UOM") or "").upper() or None,
        "floor_desc": props.get("LOWER_DESC") or "",
        "ceiling_desc": props.get("UPPER_DESC") or "",
        "eff_times": eff_times,
        "controlling_agency": cont_agent,
        "geometry": geom,
        "bbox": bbox,
    }


@lru_cache(maxsize=1)
def load_airspaces() -> dict[str, list[dict]]:
    """Load airspace polygons from data/airspace/*.geojson and the
    schedule join table from schedule.json.

    Returns dict keyed by layer name (class_airspace / special_use /
    tfr / schedule). The polygon layers are lists of record dicts (see
    _feature_to_record); `schedule` is a dict keyed by FAA_ID. Empty
    layers return empty containers — the loader is tolerant of missing
    files so the app still boots before the ingest script has run.
    """
    out: dict[str, Any] = {
        "class_airspace": [],
        "special_use": [],
        "tfr": [],
        "schedule": {},
    }
    if not _DATA_DIR.is_dir():
        return out
    for layer in ("class_airspace", "special_use", "tfr"):
        path = _DATA_DIR / f"{layer}.geojson"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for feat in data.get("features", []):
            rec = _feature_to_record(layer, feat)
            if rec is not None:
                out[layer].append(rec)
    # Schedule is a non-spatial join table keyed by FAA_ID.
    sched_path = _DATA_DIR / "schedule.json"
    if sched_path.is_file():
        try:
            rows = json.loads(sched_path.read_text())
            out["schedule"] = {r["FAA_ID"]: r for r in rows if r.get("FAA_ID")}
        except Exception:
            pass
    # Join schedule into class records by IDENT — so every downstream
    # consumer (renderer tooltip, route-crossings list) sees the
    # parsed sheets + summary without re-doing the lookup.
    sched = out["schedule"]
    if sched:
        for r in out["class_airspace"]:
            ident = (r.get("ident") or "").strip().upper()
            row = sched.get(ident)
            if not row:
                continue
            applies = row.get("APPLIES") or ""
            sheets = parse_applies(applies)
            if not sheets:
                continue
            r["schedule_sheets"] = sheets
            r["schedule_summary"] = summarize_sheets(sheets)
    return out


def _bbox_intersect(a: tuple, b: tuple) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def airspaces_in_bbox(bbox: tuple[float, float, float, float],
                       layers: list[str] | None = None) -> list[dict]:
    """Return all airspaces whose bounding box intersects `bbox`.

    `bbox` is (minlon, minlat, maxlon, maxlat) — matches GeoJSON
    conventions. Used by the map renderer to filter to viewport so
    we don't ship every Class B in the country to the browser.
    """
    if layers is None:
        layers = ["class_airspace", "special_use", "tfr"]
    data = load_airspaces()
    out = []
    for layer in layers:
        for rec in data.get(layer, []):
            if _bbox_intersect(rec["bbox"], bbox):
                out.append(rec)
    return out


def _path_crosses_polygon(path: list[tuple[float, float]],
                            geom: dict) -> bool:
    """Path is [(lat, lon), ...]. Cheap: sample each segment at a
    handful of intermediate points and run point-in-polygon. Good
    enough for an MVP — accurate for any airspace bigger than a
    couple NM, which all of them are."""
    if len(path) < 2:
        return False
    # First check each waypoint; many crossings will hit here.
    for lat, lon in path:
        if _point_in_polygon(lat, lon, geom):
            return True
    # Then walk each segment with ~5 intermediate samples per pair.
    # Linear interpolation in lat/lon is fine for legs under ~50 NM.
    for i in range(len(path) - 1):
        lat0, lon0 = path[i]
        lat1, lon1 = path[i + 1]
        for k in range(1, 6):
            t = k / 6.0
            lat = lat0 + t * (lat1 - lat0)
            lon = lon0 + t * (lon1 - lon0)
            if _point_in_polygon(lat, lon, geom):
                return True
    return False


def _path_bbox(path: list[tuple[float, float]],
                pad: float = 0.5) -> tuple[float, float, float, float]:
    lats = [p[0] for p in path]
    lons = [p[1] for p in path]
    return (min(lons) - pad, min(lats) - pad,
            max(lons) + pad, max(lats) + pad)


def route_crossings(path: list[tuple[float, float]],
                     planned_alt_msl_ft: float,
                     layers: list[str] | None = None,
                     when_utc: datetime | None = None) -> list[dict]:
    """Return airspaces that the route crosses AND whose vertical
    band overlaps the planned cruise altitude.

    `path` is a list of (lat, lon) tuples — typically the great-
    circle samples produced by core.route.

    `planned_alt_msl_ft` is the planned cruise altitude in MSL feet.
    Airspaces are flagged with `pierces: True` when the planned
    altitude is in [floor, ceiling]; otherwise the route passes
    over or under them (still listed so the pilot is aware).
    """
    if not path:
        return []
    bbox = _path_bbox(path)
    candidates = airspaces_in_bbox(bbox, layers=layers)
    out = []
    alt = float(planned_alt_msl_ft or 0.0)
    if when_utc is None:
        when_utc = datetime.utcnow()
    for rec in candidates:
        if not _path_crosses_polygon(path, rec["geometry"]):
            continue
        floor = rec["floor_ft"] if rec["floor_ft"] is not None else 0.0
        ceiling = (rec["ceiling_ft"] if rec["ceiling_ft"] is not None
                    else 99999.0)
        pierces = floor <= alt <= ceiling
        # Schedule-aware: if the airspace has a parsed schedule, evaluate
        # whether it's active at the planned crossing time. Class B/C/D
        # surface areas have schedules; everything else defaults to
        # "always active" (no schedule attached → assume active).
        sheets = rec.get("schedule_sheets") or []
        if sheets:
            active = schedule_active_at(sheets, when_utc)
        else:
            active = True
        out.append({
            **{k: v for k, v in rec.items() if k != "geometry"},
            "pierces": pierces,
            "active": active,
        })
    # Sort: pierces first, then by floor ascending.
    out.sort(key=lambda r: (not r["pierces"], r["floor_ft"] or 0.0))
    return out


# === Phase A3-followup — Airspace_Schedule APPLIES parser ====================

# Day-of-week tokens FAA uses in the APPLIES XML. ANY = all 7 days.
_DAYS_BY_TOKEN = {
    "ANY": (0, 1, 2, 3, 4, 5, 6),
    "MON": (0,), "TUE": (1,), "WED": (2,), "THU": (3,),
    "FRI": (4,), "SAT": (5,), "SUN": (6,),
    "WD":  (0, 1, 2, 3, 4),   # weekdays
    "WE":  (5, 6),             # weekend
}


def _tz_offset_minutes(token: str) -> int | None:
    """Parse 'UTC-5' → -300 minutes. Returns None on unknown."""
    if not token:
        return None
    m = re.match(r"^UTC([+-]?)(\d+)(?::(\d+))?$", token.strip().upper())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    h = int(m.group(2))
    mm = int(m.group(3) or 0)
    return sign * (h * 60 + mm)


def parse_applies(applies_xml: str) -> list[dict]:
    """Parse an Airspace_Schedule.APPLIES XML string into a list of
    Timesheet dicts. No external XML deps — regex is enough for the
    flat structure this feed uses.

    Each Timesheet dict has:
        days: tuple of weekday ints (Monday=0)
        start_time: (h, m) 24h tuple
        end_time:   (h, m) 24h tuple
        start_date: (month, day) or None
        end_date:   (month, day) or None
        tz_offset_min: int minutes from UTC (negative = west) or None
        dst: bool — whether the source flags DST adjustment
    """
    if not applies_xml:
        return []
    out: list[dict] = []
    for ts in re.findall(r"<Timesheet>(.*?)</Timesheet>", applies_xml, re.S):
        def _g(tag):
            m = re.search(rf"<{tag}>([^<]*)</{tag}>", ts)
            return (m.group(1).strip() if m else "")

        day_token = _g("day").upper() or "ANY"
        days = _DAYS_BY_TOKEN.get(day_token)
        if days is None:
            continue
        start_t = _g("startTime")
        end_t = _g("endTime")

        def _hm(s):
            mm = re.match(r"^(\d{1,2}):(\d{2})$", s)
            if not mm:
                return None
            return int(mm.group(1)), int(mm.group(2))

        s_hm = _hm(start_t)
        e_hm = _hm(end_t)
        if s_hm is None or e_hm is None:
            continue

        def _md(s):
            # NASR uses DD-MM (day-month), e.g. "01-01" or "14-05".
            mm = re.match(r"^(\d{1,2})-(\d{1,2})$", s.strip())
            if not mm:
                return None
            return int(mm.group(2)), int(mm.group(1))  # (month, day)

        out.append({
            "days": tuple(days),
            "start_time": s_hm,
            "end_time": e_hm,
            "start_date": _md(_g("startDate")),
            "end_date": _md(_g("endDate")),
            "tz_offset_min": _tz_offset_minutes(_g("timeReference")),
            "dst": _g("daylightSavingAdjust").upper() == "YES",
        })
    return out


_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def summarize_sheets(sheets: list[dict]) -> str:
    """One-line human summary. Multiple Timesheets are joined with '; '.
    Truncates at 3 sheets to keep it tooltip-friendly."""
    pieces: list[str] = []
    for s in sheets[:3]:
        days = s["days"]
        if days == (0, 1, 2, 3, 4, 5, 6):
            day_s = "Daily"
        elif days == (0, 1, 2, 3, 4):
            day_s = "Mon-Fri"
        elif days == (5, 6):
            day_s = "Sat-Sun"
        elif len(days) == 1:
            day_s = _DAY_NAMES[days[0]]
        else:
            day_s = ",".join(_DAY_NAMES[d] for d in days)
        sh, sm = s["start_time"]
        eh, em = s["end_time"]
        time_s = f"{sh:02d}{sm:02d}-{eh:02d}{em:02d}"
        tz = s["tz_offset_min"]
        if tz is None:
            tz_s = ""
        else:
            sign = "-" if tz < 0 else "+"
            tz_s = f" UTC{sign}{abs(tz)//60}"
        pieces.append(f"{day_s} {time_s}{tz_s}")
    if len(sheets) > 3:
        pieces.append(f"+{len(sheets) - 3} more")
    return "; ".join(pieces)


def _in_date_window(when_local: datetime, start_md, end_md) -> bool:
    """start_md / end_md are (month, day) or None. None means open-ended.
    Handles the wrap-around case (e.g. Nov 15 - Mar 14)."""
    if start_md is None and end_md is None:
        return True
    if start_md is None or end_md is None:
        return True
    s_m, s_d = start_md
    e_m, e_d = end_md
    cur = (when_local.month, when_local.day)
    start = (s_m, s_d)
    end = (e_m, e_d)
    if start <= end:
        return start <= cur <= end
    # Wraps year boundary: e.g. (11, 1) - (2, 28) means Nov 1 → Feb 28
    return cur >= start or cur <= end


def schedule_active_at(sheets: list[dict], when_utc: datetime) -> bool:
    """Is any of these Timesheets active at the given UTC moment?

    DST adjustment is approximated by adding +60 min to the offset
    between the second Sunday in March and the first Sunday in November
    (US rule) when the sheet flags DST. Good enough for VFR planning;
    edge-of-DST flights are not the intended use case.
    """
    if not sheets:
        return False
    for s in sheets:
        tz = s.get("tz_offset_min")
        if tz is None:
            # Without a timezone we can't pin local time — be
            # conservative and say active so the user double-checks.
            return True
        offset = timedelta(minutes=tz)
        if s.get("dst") and _is_us_dst(when_utc + offset):
            offset += timedelta(hours=1)
        local = when_utc + offset
        if not _in_date_window(local, s.get("start_date"), s.get("end_date")):
            continue
        if local.weekday() not in s["days"]:
            continue
        sh, sm = s["start_time"]
        eh, em = s["end_time"]
        cur_min = local.hour * 60 + local.minute
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        if start_min <= end_min:
            if start_min <= cur_min <= end_min:
                return True
        else:
            # Wraps midnight — e.g. 2200-0600
            if cur_min >= start_min or cur_min <= end_min:
                return True
    return False


def _is_us_dst(local_dt: datetime) -> bool:
    """Cheap US DST window: 2nd Sun of March through 1st Sun of Nov."""
    y = local_dt.year
    march_first = datetime(y, 3, 1)
    # Second Sunday of March
    dst_start = march_first + timedelta(days=(6 - march_first.weekday()) % 7 + 7)
    nov_first = datetime(y, 11, 1)
    dst_end = nov_first + timedelta(days=(6 - nov_first.weekday()) % 7)
    return dst_start.replace(hour=2) <= local_dt < dst_end.replace(hour=2)
