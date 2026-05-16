"""Live winds aloft along a route — Open-Meteo forecast integration.

For each route sample at the flight profile's altitude, fetch the
forecast wind speed + direction. Caller plumbs the per-sample
(dir, speed) list into corridor + divert via the existing
`sample_winds` parameter (same pattern as `sample_alts_msl_ft`).

Failure modes return `None`. Callers fall back to the manual wind
typed into the sidebar.

Data source: Open-Meteo `/v1/forecast` endpoint.
  - Free, no API key
  - Multi-point batching via comma-separated lat/lon
  - Pressure-level variables `wind_speed_<L>hPa` /
    `wind_direction_<L>hPa` for L in {1000, 975, 950, 925, 900, 850,
    800, 700, 600, 500, 400, 300, 250, 200, 150, 100}
  - Speeds in knots when `wind_speed_unit=kn` query param sent

Caching: an LRU around the actual HTTP call, keyed on
(rounded latlons, level set, forecast hour). Re-Compute on the same
route within the same hour is a cache hit.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT_S = 10.0

# Pressure levels Open-Meteo exposes for upper-air winds. Sorted
# descending so iterating produces low-altitude → high-altitude.
AVAILABLE_LEVELS_HPA = (
    1000, 975, 950, 925, 900, 850, 800, 700, 600,
    500, 400, 300, 250, 200, 150, 100,
)


# === Standard atmosphere ====================================================

def altitude_ft_to_hpa(alt_ft: float) -> float:
    """Convert MSL altitude (ft) to ambient pressure (hPa) using the
    ISA troposphere formula. Valid up to ~36,000 ft (tropopause).
    Above that the formula's lapse-rate assumption breaks; we clamp
    to the lowest available Open-Meteo level (100 hPa ≈ 53,000 ft)."""
    if alt_ft <= 0:
        return 1013.25
    alt_m = alt_ft * 0.3048
    if alt_m >= 11000.0:
        # Stratosphere: isothermal layer, exponential pressure decay
        p_at_11km = 226.32  # hPa
        return p_at_11km * math.exp(-(alt_m - 11000.0) / 6341.62)
    # Troposphere
    return 1013.25 * (1.0 - 0.0065 * alt_m / 288.15) ** 5.2561


def open_meteo_levels_for(pressure_hpa: float) -> tuple[int, int]:
    """Return the two adjacent Open-Meteo pressure levels that
    bracket the requested pressure. If the pressure is at or beyond
    the available range, both returned levels are the same boundary
    level (caller can detect this for a single-level lookup).
    """
    levels = AVAILABLE_LEVELS_HPA
    if pressure_hpa >= levels[0]:
        return levels[0], levels[0]
    if pressure_hpa <= levels[-1]:
        return levels[-1], levels[-1]
    # levels are sorted descending: find first L where L < pressure.
    for i, L in enumerate(levels):
        if L < pressure_hpa:
            return levels[i - 1], L
    return levels[-1], levels[-1]


# === Vector interpolation ===================================================

def _uv_from_dir_speed(dir_deg: float, speed_kt: float) -> tuple[float, float]:
    """Convert meteorological wind (FROM direction) to U/V components.
    U = east-component, V = north-component. Wind FROM 270° is a west
    wind blowing east → U = +speed, V = 0."""
    rad = math.radians(dir_deg)
    # Wind FROM dir means it blows toward (dir + 180); standard
    # convention u = -sin(rad)*speed, v = -cos(rad)*speed.
    u = -math.sin(rad) * speed_kt
    v = -math.cos(rad) * speed_kt
    return u, v


def _dir_speed_from_uv(u: float, v: float) -> tuple[float, float]:
    """Inverse of _uv_from_dir_speed. Returns (dir_FROM_deg, speed_kt)."""
    speed = math.sqrt(u * u + v * v)
    if speed < 1e-6:
        return 0.0, 0.0
    rad = math.atan2(-u, -v)
    deg = math.degrees(rad) % 360.0
    return deg, speed


def interp_wind(
    pressure_hpa: float,
    level_low: int, level_high: int,
    wind_low: tuple[float, float],
    wind_high: tuple[float, float],
) -> tuple[float, float]:
    """Linear interpolation of (dir, speed) wind between two pressure
    levels via U/V components (degree wraparound is unsafe in raw
    angle space — 350° and 10° must blend to ~0°, not 180°).

    `level_low` is the lower-altitude level (HIGHER pressure value),
    `level_high` is the higher-altitude level (LOWER pressure value).
    `pressure_hpa` should fall between them inclusive.
    """
    if level_low == level_high:
        return wind_low
    span = level_low - level_high
    if span == 0:
        return wind_low
    # Fraction of the way from level_low (low altitude) toward
    # level_high (high altitude). pressure_hpa decreases with altitude,
    # so fraction = (level_low - pressure_hpa) / span.
    frac = (level_low - pressure_hpa) / span
    frac = max(0.0, min(1.0, frac))

    u_lo, v_lo = _uv_from_dir_speed(*wind_low)
    u_hi, v_hi = _uv_from_dir_speed(*wind_high)
    u = u_lo + frac * (u_hi - u_lo)
    v = v_lo + frac * (v_hi - v_lo)
    return _dir_speed_from_uv(u, v)


# === HTTP fetch (cached) ====================================================

def _round_latlon(lat: float, lon: float, grid_deg: float = 0.5) -> tuple[float, float]:
    """Quantize a lat/lon to a coarse grid for cache deduplication.
    0.5° ≈ 30 NM at mid-latitudes — close-by samples share a cache
    hit, which is the desired behavior for an hourly forecast."""
    return (round(lat / grid_deg) * grid_deg,
            round(lon / grid_deg) * grid_deg)


@lru_cache(maxsize=16)
def _cached_batch_fetch(
    rounded_latlons_t: tuple[tuple[float, float], ...],
    levels_t: tuple[int, ...],
    hour_iso: str,
) -> tuple | None:
    """LRU-cached fetch. Inputs are hashable tuples so lru_cache works.
    Returns a tuple-of-tuples per-location per-level wind, or None on
    failure. Tuple-of-tuples (rather than dict) keeps the cache value
    hashable and small."""
    if not rounded_latlons_t:
        return None
    lats = ",".join(f"{lat}" for lat, _ in rounded_latlons_t)
    lons = ",".join(f"{lon}" for _, lon in rounded_latlons_t)
    vars_ = []
    for L in levels_t:
        vars_.append(f"wind_speed_{L}hPa")
        vars_.append(f"wind_direction_{L}hPa")
    params = {
        "latitude": lats,
        "longitude": lons,
        "hourly": ",".join(vars_),
        "wind_speed_unit": "kn",
        "forecast_hours": 6,
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params,
                            timeout=HTTP_TIMEOUT_S)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None

    # Open-Meteo returns a single object for one location, or a list
    # for multiple. Normalize to list.
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or len(payload) != len(rounded_latlons_t):
        return None

    # Pull the hour matching hour_iso, then extract per-level wind
    # for each location.
    out_per_loc = []
    for loc in payload:
        hourly = loc.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return None
        # Find the index where time matches hour_iso (or just take 0)
        idx = 0
        for i, t in enumerate(times):
            if t == hour_iso or t.startswith(hour_iso):
                idx = i
                break
        per_level = {}
        for L in levels_t:
            speeds = hourly.get(f"wind_speed_{L}hPa") or []
            dirs = hourly.get(f"wind_direction_{L}hPa") or []
            if idx >= len(speeds) or idx >= len(dirs):
                return None
            sp = speeds[idx]
            dr = dirs[idx]
            if sp is None or dr is None:
                return None
            per_level[L] = (float(dr), float(sp))
        out_per_loc.append(tuple(sorted(per_level.items())))
    return tuple(out_per_loc)


def fetch_winds_aloft(
    latlons: list[tuple[float, float]],
    altitudes_ft: list[float],
    forecast_hour_utc: Optional[datetime] = None,
) -> Optional[list[tuple[float, float]]]:
    """Return per-sample (wind_dir_deg, wind_speed_kt). One tuple per
    input. Returns None if the API call fails or the response is
    unparseable — callers fall back to manual wind.

    `forecast_hour_utc` defaults to the current hour (top of hour,
    UTC). Forecast horizon is 7 days; requesting past that returns
    the last available hour.
    """
    if not latlons or not altitudes_ft:
        return None
    if len(latlons) != len(altitudes_ft):
        return None

    # Round latlons to grid for cache-key stability
    rounded = tuple(_round_latlon(lat, lon) for lat, lon in latlons)
    # Determine the unique set of pressure levels needed across all
    # samples — we want all bracketing levels for any sample.
    needed_levels: set[int] = set()
    pressure_per_sample = []
    for alt_ft in altitudes_ft:
        p = altitude_ft_to_hpa(alt_ft)
        pressure_per_sample.append(p)
        lo, hi = open_meteo_levels_for(p)
        needed_levels.add(lo)
        needed_levels.add(hi)
    levels_t = tuple(sorted(needed_levels, reverse=True))   # descending

    # Hour key
    now = forecast_hour_utc or datetime.now(timezone.utc)
    hour_iso = now.replace(minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:00")

    batch = _cached_batch_fetch(rounded, levels_t, hour_iso)
    if batch is None:
        return None

    # Per sample: pick its two bracketing levels and interpolate.
    out: list[tuple[float, float]] = []
    for i, p in enumerate(pressure_per_sample):
        lo, hi = open_meteo_levels_for(p)
        per_level = dict(batch[i])
        wind_lo = per_level.get(lo)
        wind_hi = per_level.get(hi)
        if wind_lo is None or wind_hi is None:
            return None
        wind = interp_wind(p, lo, hi, wind_lo, wind_hi)
        out.append(wind)
    return out


def clear_cache() -> None:
    """Drop the in-memory LRU. For testing."""
    _cached_batch_fetch.cache_clear()
