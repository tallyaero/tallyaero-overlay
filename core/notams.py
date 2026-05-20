"""NOTAM relevance filtering for the Route Planner.

Phase A4 from the future-refinements plan. Pilots get hundreds of
NOTAMs per FAA briefing; this module narrows them down to the
~5 that actually affect *your* corridor, *your* altitude, and
*your* time window.

The filtering logic is pure — no network — so the unit tests run
without auth. Live ingestion is a separate concern (data/notams/
build_notams.py wires the FAA NOTAM Search API once a pilot has
their API credentials provisioned).

NOTAM record shape (what relevant_notams() expects):
    {
      "id": str,              # NOTAM number, e.g. "!CHS 05/0234"
      "lat": float,           # location lat (decimal deg)
      "lon": float,           # location lon
      "radius_nm": float,     # effective radius
      "floor_ft": float | None,
      "ceiling_ft": float | None,
      "start_utc": str | None,  # ISO 8601
      "end_utc": str | None,    # ISO 8601 (None = continuous)
      "category": str,        # 'TFR' | 'OBST' | 'RWY' | 'AIRSPACE' | 'NAV' | 'COM' | 'GEN'
      "text": str,            # human-readable body
    }
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "notams"

# Distance helpers — duplicated tiny haversine here so this module
# stays usable without pulling in core/route at import time.
_EARTH_NM = 3440.065


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat = r2 - r1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_NM * math.asin(math.sqrt(a))


def _cross_track_nm(path: list[tuple[float, float]],
                     lat: float, lon: float) -> float:
    """Minimum great-circle distance from a point to the route polyline.
    Cheap: check distance to every segment, return the smallest."""
    if not path:
        return float("inf")
    if len(path) == 1:
        return _haversine_nm(lat, lon, path[0][0], path[0][1])
    best = float("inf")
    for i in range(len(path) - 1):
        a_lat, a_lon = path[i]
        b_lat, b_lon = path[i + 1]
        # Sample 5 intermediate points + the endpoints; good enough
        # for legs under ~50 NM (corridor sampler uses 1-2 NM spacing).
        for k in range(6):
            t = k / 5.0
            slat = a_lat + t * (b_lat - a_lat)
            slon = a_lon + t * (b_lon - a_lon)
            d = _haversine_nm(lat, lon, slat, slon)
            if d < best:
                best = d
    return best


def _parse_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Accept either "2026-05-19T18:00:00Z" or with offset.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


@lru_cache(maxsize=1)
def load_notams() -> list[dict]:
    """Load bundled NOTAMs from data/notams/notams.json. Empty list
    if the file is missing — the rest of the pipeline still works,
    it just won't surface anything."""
    path = _DATA_DIR / "notams.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return data


def relevant_notams(path: list[tuple[float, float]],
                     cruise_alt_msl_ft: float,
                     departure_utc: datetime | None = None,
                     ete_total_min: float = 0.0,
                     corridor_width_nm: float = 5.0,
                     altitude_buffer_ft: float = 1500.0,
                     notams: list[dict] | None = None) -> list[dict]:
    """Filter the NOTAM set down to entries that actually matter for
    this flight.

    Spatial: any NOTAM whose center is within (corridor_width_nm +
    radius_nm) of the route polyline counts as "on corridor".

    Vertical: NOTAM altitude band intersects [cruise_alt - buffer,
    cruise_alt + buffer]. NOTAMs without altitude info (most
    obstruction / GEN) are treated as surface-relevant.

    Temporal: NOTAM active window overlaps [departure_utc, departure_utc
    + ete_total_min]. Open-ended NOTAMs (no end) count as always-active.
    When departure_utc is None, "now" is used and the ETE window is
    treated as 24h going forward (covers same-day planning).

    Returns the matched NOTAMs sorted by category priority (TFR/airspace
    first, then runway, then nav/com, then obstructions, then general).
    Each record carries an added 'distance_nm' field with its closest
    approach to the route — useful for sorting / display.
    """
    if not path:
        return []
    notams = list(notams) if notams is not None else load_notams()
    if not notams:
        return []
    # Departure window
    if departure_utc is None:
        departure_utc = datetime.utcnow()
    if ete_total_min <= 0:
        ete_total_min = 24 * 60  # default 24h forward
    window_end = departure_utc + timedelta(minutes=ete_total_min)

    alt = float(cruise_alt_msl_ft or 0.0)
    alt_lo = alt - altitude_buffer_ft
    alt_hi = alt + altitude_buffer_ft

    out: list[dict] = []
    for n in notams:
        # Spatial filter
        n_lat = n.get("lat")
        n_lon = n.get("lon")
        if n_lat is None or n_lon is None:
            continue
        n_radius = float(n.get("radius_nm") or 0.0)
        d = _cross_track_nm(path, float(n_lat), float(n_lon))
        if d > corridor_width_nm + n_radius:
            continue

        # Vertical filter
        floor = n.get("floor_ft")
        ceiling = n.get("ceiling_ft")
        if floor is not None or ceiling is not None:
            n_lo = float(floor) if floor is not None else 0.0
            n_hi = float(ceiling) if ceiling is not None else 99999.0
            if n_hi < alt_lo or n_lo > alt_hi:
                continue

        # Temporal filter
        n_start = _parse_utc(n.get("start_utc"))
        n_end = _parse_utc(n.get("end_utc"))
        if n_start is not None and n_start > window_end:
            continue
        if n_end is not None and n_end < departure_utc:
            continue

        out.append({**n, "distance_nm": round(d, 1)})

    # Sort by category priority then by distance to route.
    _PRIORITY = {"TFR": 0, "AIRSPACE": 1, "RWY": 2, "NAV": 3,
                 "COM": 4, "OBST": 5, "GEN": 6}
    out.sort(key=lambda n: (_PRIORITY.get((n.get("category") or "GEN").upper(), 9),
                              n.get("distance_nm", 999)))
    return out


_CATEGORY_LABELS = {
    "TFR":      ("TFR",        "#cc0000"),
    "AIRSPACE": ("Airspace",   "#cc0000"),
    "RWY":      ("Runway",     "#d97706"),
    "NAV":      ("Navaid",     "#0050a0"),
    "COM":      ("Comm",       "#0050a0"),
    "OBST":     ("Obstruction","#7c3aed"),
    "GEN":      ("General",    "#475569"),
}


def category_style(cat: str | None) -> tuple[str, str]:
    """(label, color) for the nav-log chip. Unknown categories fall
    through to 'General'."""
    if not cat:
        return _CATEGORY_LABELS["GEN"]
    return _CATEGORY_LABELS.get(cat.strip().upper(), _CATEGORY_LABELS["GEN"])
