"""NOAA AWC METAR — surface wind / temp / altimeter for live weather.

Free, no auth. The AWC API endpoint:
  https://aviationweather.gov/api/data/metar?ids=KICAO&format=json

Returns a list of records; we use the most recent. In-process 5-min
cache so per-airport-pick fans don't hammer the API. Stale-on-error:
if the fetch fails, return the last good payload (until process
restart). Returns None when nothing's been cached for an unknown ICAO.

Conventions worth remembering at the call site:
- `wind_dir_deg` is MAGNETIC by ICAO Annex 3 (matches the runway
  designator semantic — what the pilot reads). The simulations expect
  TRUE for geometry, so the env-wind-dir input MUST be magvar-converted
  before being passed to the sim. Winds aloft from Open-Meteo
  (core/winds_aloft.py) is already TRUE — no double conversion.
- `wind_speed_kt` is just kt. Gusts ignored for now (sims use mean).
- `temp_c`. Convert to °F at the env-oat boundary if needed.
- `altimeter_inhg`. May be Q-coded hPa in some metro reports; the JSON
  endpoint normalizes to inHg.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Optional

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL_SEC = 300.0
_HTTP_TIMEOUT_SEC = 4.0
_USER_AGENT = "tallyaero-overlay/1 (https://tallyaero.com)"


def _http_get(icao: str) -> list[dict]:
    """Hit the AWC JSON endpoint. Raises on network/parse errors so the
    caller's stale-on-error logic can engage."""
    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={urllib.parse.quote(icao)}&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as r:
        payload = r.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        return []
    return data


_HPA_PER_INHG = 33.8639


def parse_metar_json(raw: list[dict]) -> Optional[dict]:
    """Pick the most-recent record and shape it for the env panel.

    Returns None for empty input or when no record has obs_time.

    The AWC JSON `altim` field is returned in hPa (hectopascals) for all
    stations, even US ones whose raw observations are inHg. We detect
    values > 100 as hPa and convert to inHg so the rest of the app can
    treat the field uniformly (sim physics, altimeter input box, etc.).
    """
    if not raw:
        return None
    # Newest first — AWC lists newest first but sort defensively.
    recs = [r for r in raw if isinstance(r, dict)]
    if not recs:
        return None
    recs.sort(key=lambda r: r.get("obsTime") or "", reverse=True)
    m = recs[0]

    altim_raw = m.get("altim")
    altim_inhg = None
    if altim_raw is not None:
        try:
            v = float(altim_raw)
            altim_inhg = v / _HPA_PER_INHG if v > 100.0 else v
        except (TypeError, ValueError):
            altim_inhg = None

    return {
        "icao": m.get("icaoId"),
        "obs_time": m.get("obsTime"),
        "wind_dir_deg": m.get("wdir"),       # may be None (VRB) — caller falls back
        "wind_speed_kt": m.get("wspd"),
        "wind_gust_kt": m.get("wgst"),
        "temp_c": m.get("temp"),
        "dew_c": m.get("dewp"),
        "altimeter_inhg": altim_inhg,
        "raw_ob": m.get("rawOb"),            # original text for displays/tooltips
    }


def fetch_metar(icao: str) -> Optional[dict]:
    """Return the parsed METAR dict for an ICAO. 5-min cache.
    Returns None for unknown ICAOs or persistent network failure with
    no prior cache hit; returns the stale entry on transient failures."""
    if not icao:
        return None
    icao = icao.upper().strip()
    now = time.time()
    hit = _CACHE.get(icao)
    if hit and now - hit[0] < _TTL_SEC:
        return hit[1]
    try:
        parsed = parse_metar_json(_http_get(icao))
    except Exception:
        return hit[1] if hit else None
    if parsed:
        _CACHE[icao] = (now, parsed)
        return parsed
    # Unknown ICAO from the API: return prior cache if any, else None.
    return hit[1] if hit else None
