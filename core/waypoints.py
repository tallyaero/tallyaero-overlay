"""Waypoint type system + GPS coordinate parser.

The route's waypoint list can now hold more than just airports.
Phase 7N-a introduces:

  - `Waypoint` dataclass — uniform record for any waypoint kind.
  - `parse_gps_coordinate(token)` — accepts 7 common pilot input
    formats and returns decimal (lat, lon).
  - `resolve_any(token, *, airport_data, navaid_data=None,
                 fix_data=None)` — extension of resolve_waypoint
    that tries (in priority order):
      1. GPS coordinate parse (any of the supported formats)
      2. Airport exact-code / fuzzy match (existing)
      3. (future) NASR NAVAID match
      4. (future) NASR FIX/intersection match
    Returns a Waypoint or None.

NAVAID + fix resolution lands when NASR data ingestion ships
(7N-b/c). Today the resolver is GPS + airports; the kwargs are
already in place so callers don't change when the data arrives.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional


# === Waypoint type ==========================================================

@dataclass
class Waypoint:
    """A single waypoint usable by the route planner."""
    kind: str            # 'airport' | 'vor' | 'ndb' | 'fix' | 'gps'
    ident: str           # display id e.g. 'KDYB' / 'SAV' / 'VARRO'
    lat: float
    lon: float
    elevation_ft: Optional[float] = None
    name: str = ""
    freq_mhz: Optional[float] = None
    extra: dict = field(default_factory=dict)

    def to_dict_min(self) -> dict:
        """Minimal dict for downstream callers that expect the
        legacy airport-dict shape (lat/lon/id/elevation_ft/name)."""
        return {
            "id": self.ident,
            "lat": self.lat,
            "lon": self.lon,
            "elevation_ft": self.elevation_ft,
            "name": self.name,
            "kind": self.kind,
        }


# === GPS coordinate parser ==================================================

# Match decimal degrees with optional hemisphere prefix
_DEC = r"[-+]?\d+\.?\d*"
_RE_LATLON_PLAIN = re.compile(
    rf"^\s*({_DEC})\s*[, ]\s*({_DEC})\s*$"
)
# N33.5 W80.5 / N33.5,W80.5
_RE_LATLON_HEMI = re.compile(
    rf"^\s*([NS])\s*({_DEC})\s*[, ]\s*([EW])\s*({_DEC})\s*$",
    re.IGNORECASE,
)
# N33°30.5' W80°15.5'   (deg + decimal min)
_RE_DDM = re.compile(
    r"^\s*([NS])\s*(\d+)\s*[°d]\s*(\d+\.?\d*)\s*['m]?"
    r"\s*[, ]\s*"
    r"([EW])\s*(\d+)\s*[°d]\s*(\d+\.?\d*)\s*['m]?\s*$",
    re.IGNORECASE,
)
# N33°30'15" W80°15'15"  (deg + min + sec)
_RE_DMS = re.compile(
    r"^\s*([NS])\s*(\d+)\s*[°d]\s*(\d+)\s*['m]\s*(\d+\.?\d*)\s*[\"s]?"
    r"\s*[, ]\s*"
    r"([EW])\s*(\d+)\s*[°d]\s*(\d+)\s*['m]\s*(\d+\.?\d*)\s*[\"s]?\s*$",
    re.IGNORECASE,
)
# ARINC 424 / GPS-shorthand: N3303.81/W08016.77
# (deg+min concatenated, decimal min after the 2-digit-deg, slash separator)
_RE_ARINC = re.compile(
    r"^\s*([NS])(\d{2,3})(\d{2}\.?\d*)\s*[/, ]\s*"
    r"([EW])(\d{2,3})(\d{2}\.?\d*)\s*$",
    re.IGNORECASE,
)
# Internal storage format: GPS:33.0635,-80.2795
_RE_GPS_INTERNAL = re.compile(
    rf"^\s*GPS\s*:\s*({_DEC})\s*,\s*({_DEC})\s*$"
)


def _hemi(d: float, hemi: str) -> float:
    h = hemi.upper()
    if h in ("S", "W"):
        return -abs(d)
    return abs(d)


def parse_gps_coordinate(token: str) -> Optional[tuple[float, float]]:
    """Try the 7 supported formats. Returns (lat, lon) in decimal
    degrees or None if no format matches.

    Supported (in order tried):
      1. GPS:33.0635,-80.2795          (internal canonical)
      2. 33.0635,-80.2795              (plain decimal)
      3. N33.5 W80.5                   (hemisphere + decimal)
      4. N33°30'15" W80°15'15"         (DMS)
      5. N33°30.5' W80°15.5'           (DDM, decimal minutes)
      6. N3303.81/W08016.77            (ARINC 424 / GPS shorthand)
    """
    if not token or not isinstance(token, str):
        return None
    t = token.strip()
    if not t:
        return None

    # 1. Internal canonical
    m = _RE_GPS_INTERNAL.match(t)
    if m:
        lat = float(m.group(1))
        lon = float(m.group(2))
        return _validate_latlon(lat, lon)

    # 4. DMS (most specific — must precede DDM)
    m = _RE_DMS.match(t)
    if m:
        lat = int(m.group(2)) + int(m.group(3)) / 60.0 + float(m.group(4)) / 3600.0
        lat = _hemi(lat, m.group(1))
        lon = int(m.group(6)) + int(m.group(7)) / 60.0 + float(m.group(8)) / 3600.0
        lon = _hemi(lon, m.group(5))
        return _validate_latlon(lat, lon)

    # 5. DDM (deg + decimal minute)
    m = _RE_DDM.match(t)
    if m:
        lat = int(m.group(2)) + float(m.group(3)) / 60.0
        lat = _hemi(lat, m.group(1))
        lon = int(m.group(5)) + float(m.group(6)) / 60.0
        lon = _hemi(lon, m.group(4))
        return _validate_latlon(lat, lon)

    # 6. ARINC shorthand
    m = _RE_ARINC.match(t)
    if m:
        # group(2) is 2-3 digit deg; remaining (group 3) is min.frac
        lat = float(m.group(2)) + float(m.group(3)) / 60.0
        lat = _hemi(lat, m.group(1))
        lon = float(m.group(5)) + float(m.group(6)) / 60.0
        lon = _hemi(lon, m.group(4))
        return _validate_latlon(lat, lon)

    # 3. Hemisphere + decimal
    m = _RE_LATLON_HEMI.match(t)
    if m:
        lat = _hemi(float(m.group(2)), m.group(1))
        lon = _hemi(float(m.group(4)), m.group(3))
        return _validate_latlon(lat, lon)

    # 2. Plain decimal (catches "33.5,-80.5")
    m = _RE_LATLON_PLAIN.match(t)
    if m:
        lat = float(m.group(1))
        lon = float(m.group(2))
        # Plain decimal needs at least one to be obviously a coord:
        # reject if both are small integers (probably an airport code
        # that happens to match the regex like "12,34"). A lat outside
        # [-90,90] or lon outside [-180,180] is obviously not a coord.
        if abs(lat) < 0.001 and abs(lon) < 0.001:
            return None
        return _validate_latlon(lat, lon)

    return None


def _validate_latlon(lat: float, lon: float) -> Optional[tuple[float, float]]:
    """Return (lat, lon) if both are in valid ranges, else None."""
    if not (-90.0 <= lat <= 90.0):
        return None
    if not (-180.0 <= lon <= 180.0):
        return None
    return (lat, lon)


# === Canonical GPS ident formatter =========================================

def format_gps_ident(lat: float, lon: float) -> str:
    """Internal canonical string: GPS:lat,lon (4 decimal places).
    Round-trips through parse_gps_coordinate."""
    return f"GPS:{lat:.4f},{lon:.4f}"


def format_gps_display(lat: float, lon: float) -> str:
    """Human-readable display: GPS 33.06°N / 80.28°W."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"GPS {abs(lat):.2f}°{ns} / {abs(lon):.2f}°{ew}"


# === Unified resolver =======================================================

def gps_to_waypoint(token: str) -> Optional[Waypoint]:
    """Return a Waypoint if `token` parses as a GPS coordinate."""
    parsed = parse_gps_coordinate(token)
    if parsed is None:
        return None
    lat, lon = parsed
    return Waypoint(
        kind="gps",
        ident=format_gps_ident(lat, lon),
        lat=lat,
        lon=lon,
        name=format_gps_display(lat, lon),
    )


def airport_to_waypoint(airport: dict) -> Waypoint:
    """Promote an airport_data dict to a Waypoint."""
    return Waypoint(
        kind="airport",
        ident=airport.get("id") or airport.get("icao") or "?",
        lat=airport.get("lat"),
        lon=airport.get("lon"),
        elevation_ft=airport.get("elevation_ft"),
        name=airport.get("name", ""),
    )


def _lookup_navaid(ident: str, navaid_data: list[dict]) -> Optional[Waypoint]:
    """Exact-match ident lookup against the NAVAID table."""
    t_up = ident.strip().upper()
    for nv in navaid_data or ():
        if (nv.get("ident") or "").upper() == t_up:
            kind = "ndb" if (nv.get("type_code") or "").startswith("NDB") else "vor"
            return Waypoint(
                kind=kind,
                ident=nv.get("ident"),
                lat=nv.get("lat"),
                lon=nv.get("lon"),
                name=nv.get("name", ""),
                freq_mhz=nv.get("freq_mhz"),
                elevation_ft=nv.get("elevation_ft"),
            )
    return None


def _lookup_fix(ident: str, fix_data: list[dict]) -> Optional[Waypoint]:
    """Exact-match ident lookup against the FIX table."""
    t_up = ident.strip().upper()
    for fx in fix_data or ():
        if (fx.get("ident") or "").upper() == t_up:
            return Waypoint(
                kind="fix",
                ident=fx.get("ident"),
                lat=fx.get("lat"),
                lon=fx.get("lon"),
            )
    return None


def resolve_any(
    token: str,
    *,
    airport_data: Optional[list[dict]] = None,
    navaid_data: Optional[list[dict]] = None,
    fix_data: Optional[list[dict]] = None,
) -> Optional[Waypoint]:
    """Try resolvers in priority order; return the first hit.

    Order:
      0. Explicit NAV:/FIX: prefix — bypass the airport pass and look
         up directly in the corresponding table. Used by the dropdown
         to distinguish "SAV the airport" (no prefix) from "SAV the VOR"
         (NAV:SAV) when both exist.
      1. GPS coordinate (any supported format)
      2. Airport exact / fuzzy (delegates to existing
         core.airport_search.resolve_waypoint)
      3. NAVAID exact match (when navaid_data is supplied)
      4. FIX exact match (when fix_data is supplied)
    """
    if not token:
        return None

    # 0. Explicit prefix routing — strip and route to the typed table.
    t = token.strip()
    if t.upper().startswith("NAV:") and navaid_data:
        return _lookup_navaid(t[4:], navaid_data)
    if t.upper().startswith("FIX:") and fix_data:
        return _lookup_fix(t[4:], fix_data)

    # 1. GPS coordinate first — most specific patterns
    gps = gps_to_waypoint(token)
    if gps is not None:
        return gps

    # 2. Airport
    if airport_data:
        # Local import to avoid circular dep
        from core.airport_search import resolve_waypoint as _resolve_ap
        ap = _resolve_ap(airport_data, token)
        if ap is not None:
            return airport_to_waypoint(ap)

    # 3. NAVAID
    nv_wp = _lookup_navaid(token, navaid_data) if navaid_data else None
    if nv_wp is not None:
        return nv_wp

    # 4. FIX
    fx_wp = _lookup_fix(token, fix_data) if fix_data else None
    if fx_wp is not None:
        return fx_wp

    return None


# === Nearest-snap (for click-to-build) ======================================

def nearest_airport_within(
    airport_data: list[dict],
    lat: float, lon: float,
    max_nm: float = 3.0,
) -> Optional[dict]:
    """Linear nearest-neighbor search for click-to-build. For ~49k
    airports this runs ~5-10 ms in pure Python — fast enough that we
    don't need a KDTree until VOR/fix layers land alongside."""
    if max_nm <= 0:
        return None

    best = None
    best_d = max_nm

    # Bbox prefilter to avoid haversine on far-away airports
    pad_lat = max_nm / 60.0
    pad_lon = pad_lat / max(0.1, math.cos(math.radians(lat)))
    lat_lo, lat_hi = lat - pad_lat, lat + pad_lat
    lon_lo, lon_hi = lon - pad_lon, lon + pad_lon

    # Lazy import to keep module standalone
    from core.route import haversine_nm

    for ap in airport_data:
        a_lat = ap.get("lat")
        a_lon = ap.get("lon")
        if a_lat is None or a_lon is None:
            continue
        if a_lat < lat_lo or a_lat > lat_hi or a_lon < lon_lo or a_lon > lon_hi:
            continue
        d = haversine_nm(lat, lon, a_lat, a_lon)
        if d < best_d:
            best_d = d
            best = ap
    return best
