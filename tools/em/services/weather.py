"""
NOAA Aviation Weather Center (AWC) client — fetch + cache + parse METAR.

The EM-diagram tool uses observations to seed the OAT and altimeter inputs
when the user picks an airport. Network calls are bounded by a short
in-process TTL cache so the same airport never re-fetches inside a session.

Endpoint:
    https://aviationweather.gov/api/data/metar?ids=<ICAO>&format=json

Empty-body 200 responses mean "no observation available" — typical for
small private strips. We normalize that to a None return so the caller
can fall back to ISA.

No external dependencies — stdlib urllib only, so this works in a sealed
PyInstaller bundle.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

AWC_METAR_URL = "https://aviationweather.gov/api/data/metar?ids={ids}&format=json"
USER_AGENT = "TallyAero-EM-Diagram/0.1 (+https://tallyaero.app)"
HTTP_TIMEOUT_S = 6
CACHE_TTL_S = 600   # 10 minutes — METARs update hourly anyway
HPA_TO_INHG = 0.02953

# Process-wide cache: ICAO -> (fetched_at_epoch, MetarObservation | None)
_CACHE: Dict[str, tuple[float, "Optional[MetarObservation]"]] = {}


@dataclass(frozen=True)
class MetarObservation:
    icao: str
    station_name: Optional[str]
    obs_time_epoch: Optional[int]
    report_time: Optional[str]
    temp_c: Optional[float]
    dewpoint_c: Optional[float]
    altimeter_inhg: Optional[float]
    wind_dir_deg: Optional[int]
    wind_speed_kt: Optional[int]
    wind_gust_kt: Optional[int]
    visibility: Optional[str]
    sky_cover: Optional[str]
    flight_category: Optional[str]
    raw: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def age_seconds(self) -> Optional[int]:
        if self.obs_time_epoch is None:
            return None
        return max(0, int(time.time() - self.obs_time_epoch))


def _parse(rec: Dict[str, Any]) -> MetarObservation:
    """Parse one AWC METAR record into our typed shape."""
    altim_hpa = rec.get("altim")
    altim_inhg = round(altim_hpa * HPA_TO_INHG, 2) if isinstance(altim_hpa, (int, float)) else None
    return MetarObservation(
        icao            = rec.get("icaoId") or "",
        station_name    = rec.get("name"),
        obs_time_epoch  = rec.get("obsTime"),
        report_time     = rec.get("reportTime"),
        temp_c          = rec.get("temp"),
        dewpoint_c      = rec.get("dewp"),
        altimeter_inhg  = altim_inhg,
        wind_dir_deg    = rec.get("wdir"),
        wind_speed_kt   = rec.get("wspd"),
        wind_gust_kt    = rec.get("wgst"),
        visibility      = rec.get("visib"),
        sky_cover       = rec.get("cover"),
        flight_category = rec.get("fltCat"),
        raw             = rec.get("rawOb"),
    )


def _fetch_raw(icao: str) -> Optional[list]:
    """Issue one HTTP GET. Returns the decoded JSON list, [] for empty body,
    or None on network error. AWC returns 200 + empty body for stations
    with no observation."""
    url = AWC_METAR_URL.format(ids=icao)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
            body = r.read()
        if not body:
            return []
        return json.loads(body.decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log.warning("METAR fetch network error for %s: %s", icao, e)
        return None
    except json.JSONDecodeError as e:
        log.warning("METAR fetch JSON decode error for %s: %s", icao, e)
        return None


def get_metar(icao: str, *, force: bool = False) -> Optional[MetarObservation]:
    """Return a parsed METAR for an ICAO, or None if unavailable / errored.

    Uses the in-process TTL cache (10 min) — `force=True` bypasses it.
    """
    if not icao:
        return None
    icao = icao.upper().strip()
    now = time.time()

    if not force:
        cached = _CACHE.get(icao)
        if cached and (now - cached[0]) < CACHE_TTL_S:
            return cached[1]

    data = _fetch_raw(icao)
    if data is None:                  # network/parse error — don't cache, retry next call
        return None
    obs = _parse(data[0]) if data else None
    _CACHE[icao] = (now, obs)
    return obs


def clear_cache() -> None:
    """Drop everything in the cache. Used by tests."""
    _CACHE.clear()


if __name__ == "__main__":
    # Smoke test: $ python -m services.weather KAUS KJFK 00AA
    import sys
    icaos = sys.argv[1:] or ["KAUS", "KJFK", "00AA"]
    for code in icaos:
        m = get_metar(code)
        if m is None:
            print(f"\n{code}: no observation (or fetch failed)")
            continue
        print(f"\n{code}: {m.station_name}")
        print(f"  observed: {m.report_time} ({m.age_seconds // 60}m ago)" if m.age_seconds is not None else "")
        print(f"  temp/dew:  {m.temp_c}°C / {m.dewpoint_c}°C")
        print(f"  altimeter: {m.altimeter_inhg} inHg")
        print(f"  wind:      {m.wind_dir_deg:03}/{m.wind_speed_kt}kt" + (f" gust {m.wind_gust_kt}" if m.wind_gust_kt else ""))
        print(f"  category:  {m.flight_category}, sky {m.sky_cover}, vis {m.visibility}")
        print(f"  raw:       {m.raw}")
