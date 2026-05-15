"""Route math — great-circle distance + initial bearing + wind triangle.

Pure functions, no Dash dependencies. Tests live in tests/test_route.py.

References:
- Haversine distance & initial bearing: classical great-circle formulas
  (https://www.movable-type.co.uk/scripts/latlong.html).
- Wind triangle: VFR pilot dead-reckoning, standard form
  (Aviation Formulary V1.46 §10).
- Magnetic variation: applied to the True Course to derive Magnetic
  Course / Magnetic Heading. The variation value itself comes from
  the WMM lookup (pygeomag, wired in Phase 5b) — this module accepts
  it as a parameter so the math + the data source stay decoupled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

EARTH_RADIUS_NM = 3440.065     # nautical miles
FT_PER_NM = 6076.115


# ── Magnetic variation (WMM) via pygeomag ─────────────────────────────
# Cached at module load so we don't reinitialize the coefficient table
# on every call. pygeomag's `calculate(glat, glon, alt, time)` returns
# a result where `.d` is the declination (east positive, west negative)
# — the geophysics convention. Pilots use W-positive variation, so we
# negate at the boundary.

_GEOMAG = None


def _get_geomag():
    global _GEOMAG
    if _GEOMAG is None:
        from pygeomag import GeoMag
        _GEOMAG = GeoMag()
    return _GEOMAG


def _current_decimal_year() -> float:
    now = datetime.now(timezone.utc)
    year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return now.year + (now - year_start).total_seconds() / (year_end - year_start).total_seconds()


def magvar_west_positive(lat_deg: float, lon_deg: float,
                         alt_ft: float = 0.0,
                         decimal_year: Optional[float] = None) -> float:
    """Magnetic variation at a point, returned with the pilot's
    W-positive sign convention (most of the continental US is positive).

    `decimal_year` defaults to today (UTC). Pass an explicit float for
    deterministic tests."""
    year = _current_decimal_year() if decimal_year is None else decimal_year
    geomag = _get_geomag()
    result = geomag.calculate(
        glat=lat_deg, glon=lon_deg,
        alt=alt_ft / 3280.84,   # ft → km (WMM altitude is in km)
        time=year,
    )
    return -result.d   # pygeomag E+ → pilot W+


def haversine_nm(lat1_deg: float, lon1_deg: float,
                 lat2_deg: float, lon2_deg: float) -> float:
    """Great-circle distance in nautical miles between two lat/lon points."""
    lat1, lat2 = math.radians(lat1_deg), math.radians(lat2_deg)
    dlat = lat2 - lat1
    dlon = math.radians(lon2_deg - lon1_deg)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1_deg: float, lon1_deg: float,
                        lat2_deg: float, lon2_deg: float) -> float:
    """Initial true bearing (deg, 0–360) from point 1 to point 2 on a
    great circle. Equivalent to the True Course at the origin."""
    lat1, lat2 = math.radians(lat1_deg), math.radians(lat2_deg)
    dlon = math.radians(lon2_deg - lon1_deg)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brg = math.degrees(math.atan2(y, x))
    return (brg + 360.0) % 360.0


def wind_triangle(tas_kt: float, true_course_deg: float,
                  wind_dir_deg: float, wind_speed_kt: float) -> tuple[float, float]:
    """Solve the wind triangle for a desired ground track.

    Args:
        tas_kt: True airspeed (kt).
        true_course_deg: Desired ground track (TC, deg).
        wind_dir_deg: Direction wind is coming FROM (deg, met convention).
        wind_speed_kt: Wind speed (kt).

    Returns:
        (true_heading_deg, ground_speed_kt). If wind exceeds TAS so no
        wind-correction solution exists, returns (true_course, max(0, TAS - wind))
        as a fallback.
    """
    if tas_kt <= 0:
        return (true_course_deg % 360.0, 0.0)
    # Standard dead-reckoning form:
    # WCA = asin(WS · sin(WD - TC) / TAS)
    # GS  = TAS · cos(WCA) - WS · cos(WD - TC)
    wd = math.radians(wind_dir_deg)
    tc = math.radians(true_course_deg)
    ws = max(0.0, wind_speed_kt)
    rel = wd - tc
    # The wind term that crabs the airplane:
    swc = (ws / tas_kt) * math.sin(rel)
    if abs(swc) >= 1.0:
        # No valid solution (head/tail wind exceeds TAS); degenerate fallback
        return (true_course_deg % 360.0, max(0.0, tas_kt - ws))
    wca = math.asin(swc)
    th = (true_course_deg + math.degrees(wca)) % 360.0
    gs = tas_kt * math.cos(wca) - ws * math.cos(rel)
    return (th, max(0.0, gs))


def true_to_magnetic(true_deg: float, magvar_deg: float) -> float:
    """Convert a True heading/course to Magnetic.

    Convention: westerly variation is POSITIVE (most of the continental US).
    Pilot mnemonic: "East is least, West is best" — MC = TC + W var = TC - E var.
    The `magvar_deg` parameter follows that convention (W positive).
    """
    return (true_deg + magvar_deg) % 360.0


@dataclass(frozen=True)
class RouteSegmentResult:
    """Computed values for a single origin→destination leg."""
    distance_nm: float           # great-circle distance, NM
    true_course_deg: float       # initial bearing, deg
    magnetic_course_deg: float   # TC + magvar
    true_heading_deg: float      # wind-corrected
    magnetic_heading_deg: float  # MH = TH + magvar
    ground_speed_kt: float
    ete_min: float               # estimated time en route, minutes
    fuel_burn_gal: Optional[float]  # if fuel_burn_gph supplied


def compute_route_segment(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    tas_kt: float,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    magvar_deg: float = 0.0,
    fuel_burn_gph: Optional[float] = None,
) -> RouteSegmentResult:
    """Single great-circle leg with the wind triangle applied at the
    origin's initial true course. Acceptable for legs up to ~200 NM
    where the course doesn't curve much; Phase 7 will sample along the
    arc for longer legs."""
    distance = haversine_nm(origin_lat, origin_lon, dest_lat, dest_lon)
    tc = initial_bearing_deg(origin_lat, origin_lon, dest_lat, dest_lon)
    th, gs = wind_triangle(tas_kt, tc, wind_dir_deg, wind_speed_kt)
    mc = true_to_magnetic(tc, magvar_deg)
    mh = true_to_magnetic(th, magvar_deg)
    ete_hr = distance / gs if gs > 0 else float("inf")
    fuel = (ete_hr * fuel_burn_gph) if fuel_burn_gph else None
    return RouteSegmentResult(
        distance_nm=distance,
        true_course_deg=tc,
        magnetic_course_deg=mc,
        true_heading_deg=th,
        magnetic_heading_deg=mh,
        ground_speed_kt=gs,
        ete_min=ete_hr * 60.0 if math.isfinite(ete_hr) else float("inf"),
        fuel_burn_gal=fuel,
    )
