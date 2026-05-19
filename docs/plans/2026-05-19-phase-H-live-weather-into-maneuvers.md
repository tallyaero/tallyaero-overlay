# Phase H · Live winds-aloft + METAR into maneuver sims

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task.

**Goal:** When the user picks an airport, surface METAR auto-fills env-wind /
OAT / altimeter, and the 5 altitude-changing maneuver sims use per-tick
winds-aloft from a column profile (Open-Meteo via the existing
`core/winds_aloft.py`) instead of the single static sidebar value.

**Architecture:**

1. `core/winds_aloft.py` already has `fetch_winds_aloft(latlons, altitudes_ft)`
   that returns column-bracketed, pressure-level-interpolated tuples. New
   helper: `wind_column_at_point(lat, lon, alt_floor_ft, alt_ceiling_ft)`
   → pre-fetches a column (surface + 1500 + 3000 + 6000 + 9000 + 12000 ft as
   needed), returns a `WindProfile` object with `at(alt_ft) -> (dir, kt)`
   that interpolates in memory. One API call per airport pick, then zero
   hits during the sim.
2. New `core/metar.py` — NOAA AWC METAR fetcher (no auth) at
   `https://aviationweather.gov/api/data/metar?ids=KICAO&format=json`.
   Returns surface wind, OAT, altimeter. 5-minute TTL cache.
3. Airport-selection callback (`callbacks/environment.py`) fans out to
   both fetchers, writes:
   - `env-wind-dir.value`, `env-wind-speed.value`, `env-oat.value`,
     `env-altimeter.value` (METAR overrides defaults)
   - `wind-profile-store.data` (column profile JSON used by sims)
4. 5 sim signatures gain an optional `wind_profile: dict | None = None`
   parameter. Per-tick loop replaces the constant wind-component
   computation with a `wind_profile.at(alt_ft)` lookup when provided;
   else falls back to the static `wind_dir_deg`/`wind_speed_kt` args
   (current behavior, preserves tests).
5. Results modal gains a "Winds used (live)" chip showing the layers
   the sim actually consumed: `SFC 250°/15  3000ft 268°/22  6000ft 281°/28`.

**Tech stack:** existing — Open-Meteo (winds aloft, already cached),
NOAA ADDS METAR (new, JSON, no auth), pytest snapshot-friendly fallback
when an env-var or test fixture disables network calls.

**Affected sims (altitude-changing only):**
- `simulation/engine_out.py` — gliding descent 5000ft→SFC. **Highest leverage.**
- `simulation/impossible_turn.py` — climb 50→1000ft, glide back.
- `simulation/chandelle.py` — climb 500-1000ft.
- `simulation/lazy_eight.py` — oscillation ±500ft.
- `simulation/steep_spiral.py` — descent 3500ft over 3 turns.

**Unchanged sims:** steep_turn (level), s_turn / turns_around_point /
rectangular_course / eights_on_pylons (ground-reference, near-constant alt).
Single-layer wind from sidebar is fine for those.

---

## Task H1: METAR fetcher + cache

**Files:**
- Create: `core/metar.py`
- Create: `tests/test_metar.py`

**Step 1: Write the failing test**

```python
# tests/test_metar.py
from unittest.mock import patch
from core.metar import fetch_metar, parse_metar_json

_SAMPLE = {
    "icaoId": "KDYB", "obsTime": "2026-05-19T13:55:00Z",
    "wdir": 250, "wspd": 12, "temp": 22.0, "altim": 30.05,
}

def test_parse_metar_json():
    m = parse_metar_json([_SAMPLE])
    assert m["wind_dir_deg"] == 250
    assert m["wind_speed_kt"] == 12
    assert m["temp_c"] == 22.0
    assert abs(m["altimeter_inhg"] - 30.05) < 0.001

def test_fetch_metar_returns_none_on_empty():
    with patch("core.metar._http_get", return_value=[]):
        assert fetch_metar("KDYB") is None
```

**Step 2: Implement**

```python
# core/metar.py
"""NOAA AWC METAR — surface wind / temp / altimeter for live weather.

Free, no auth. Cached 5 min in-process (the fetch is per-airport-pick
in the UI, not per-callback)."""
from __future__ import annotations
import time
import urllib.parse
import urllib.request
import json
from typing import Optional

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL_SEC = 300.0

def _http_get(icao: str) -> list[dict]:
    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={urllib.parse.quote(icao)}&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "tallyaero-overlay/1"})
    with urllib.request.urlopen(req, timeout=4.0) as r:
        return json.loads(r.read().decode("utf-8")) or []

def parse_metar_json(raw: list[dict]) -> Optional[dict]:
    if not raw:
        return None
    m = raw[0]
    return {
        "icao": m.get("icaoId"),
        "obs_time": m.get("obsTime"),
        "wind_dir_deg": m.get("wdir"),       # None ok (variable)
        "wind_speed_kt": m.get("wspd"),
        "temp_c": m.get("temp"),
        "altimeter_inhg": m.get("altim"),
    }

def fetch_metar(icao: str) -> Optional[dict]:
    if not icao: return None
    icao = icao.upper().strip()
    now = time.time()
    hit = _CACHE.get(icao)
    if hit and now - hit[0] < _TTL_SEC:
        return hit[1]
    try:
        parsed = parse_metar_json(_http_get(icao))
    except Exception:
        return hit[1] if hit else None  # stale-on-error
    if parsed:
        _CACHE[icao] = (now, parsed)
    return parsed
```

**Step 3: Commit**

```bash
git add core/metar.py tests/test_metar.py
git commit -m "feat(core): NOAA AWC METAR fetcher with 5-min in-process cache (H1)"
```

---

## Task H2: WindProfile helper around fetch_winds_aloft

**Files:**
- Modify: `core/winds_aloft.py`
- Test: `tests/test_wind_profile.py`

**Step 1: Add the column-fetch helper.**

```python
# core/winds_aloft.py
class WindProfile:
    """Column of (alt_ft -> (dir_deg, speed_kt)). Linearly interpolates
    between layers. Out-of-range altitudes clamp to the nearest layer."""
    __slots__ = ("_alts", "_dirs", "_kts")

    def __init__(self, layers: list[tuple[float, float, float]]):
        # layers: [(alt_ft, dir_deg, kt), ...] sorted by alt asc
        layers = sorted(layers, key=lambda t: t[0])
        self._alts = [a for a, _, _ in layers]
        self._dirs = [d for _, d, _ in layers]
        self._kts  = [k for _, _, k in layers]

    def at(self, alt_ft: float) -> tuple[float, float]:
        if not self._alts:
            return (0.0, 0.0)
        if alt_ft <= self._alts[0]:
            return (self._dirs[0], self._kts[0])
        if alt_ft >= self._alts[-1]:
            return (self._dirs[-1], self._kts[-1])
        # binary search
        import bisect
        i = bisect.bisect_left(self._alts, alt_ft)
        a0, a1 = self._alts[i-1], self._alts[i]
        d0, d1 = self._dirs[i-1], self._dirs[i]
        k0, k1 = self._kts[i-1], self._kts[i]
        f = (alt_ft - a0) / (a1 - a0)
        # circular interp on direction
        import math
        ang0 = math.radians(d0); ang1 = math.radians(d1)
        x = (1-f)*math.cos(ang0) + f*math.cos(ang1)
        y = (1-f)*math.sin(ang0) + f*math.sin(ang1)
        d = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
        return (d, (1-f)*k0 + f*k1)

    def layers(self) -> list[tuple[float, float, float]]:
        return list(zip(self._alts, self._dirs, self._kts))


_PROFILE_ALTS_FT = [0, 1500, 3000, 6000, 9000, 12000]

def wind_column_at_point(lat: float, lon: float,
                         surface_metar: Optional[dict] = None) -> Optional[WindProfile]:
    """One Open-Meteo call → 6-layer profile from SFC to 12000 ft.
    If `surface_metar` is provided (dict with wind_dir_deg/wind_speed_kt),
    the SFC layer uses that instead of the model's 0-ft estimate."""
    latlons = [(lat, lon)] * len(_PROFILE_ALTS_FT)
    result = fetch_winds_aloft(latlons, _PROFILE_ALTS_FT)
    if not result or len(result) != len(_PROFILE_ALTS_FT):
        return None
    layers = []
    for alt, (d, k) in zip(_PROFILE_ALTS_FT, result):
        if alt == 0 and surface_metar:
            d = surface_metar.get("wind_dir_deg") or d
            k = surface_metar.get("wind_speed_kt") or k
        layers.append((float(alt), float(d), float(k)))
    return WindProfile(layers)
```

**Step 2: Tests**

```python
# tests/test_wind_profile.py
from core.winds_aloft import WindProfile

def test_interpolates_between_layers():
    p = WindProfile([(0, 270, 10), (6000, 290, 30)])
    d, k = p.at(3000)
    assert 275 <= d <= 285
    assert 19 <= k <= 21

def test_clamps_above_ceiling():
    p = WindProfile([(0, 270, 10), (3000, 280, 20)])
    d, k = p.at(9000)
    assert d == 280 and k == 20
```

**Step 3: Commit**

```bash
git add core/winds_aloft.py tests/test_wind_profile.py
git commit -m "feat(core): WindProfile + wind_column_at_point — column fetch + in-mem interp (H2)"
```

---

## Task H3: Airport-pick auto-fill + wind-profile store

**Files:**
- Modify: `callbacks/environment.py`
- Modify: `layouts/desktop.py` (add `dcc.Store(id="wind-profile-store")`)

**Step 1: Add the store**

```python
# layouts/desktop.py — near other dcc.Stores
dcc.Store(id="wind-profile-store", data=None),
dcc.Store(id="active-metar-store", data=None),
```

**Step 2: Extend `handle_airport_pick` outputs**

In `callbacks/environment.py`, after `selected-airport-id` is set, fetch
METAR + wind-column and write:
- `env-wind-dir.value`, `env-wind-speed.value`, `env-oat.value`,
  `env-altimeter.value` (from METAR, but ONLY if the user hasn't
  manually overridden — track via a "live-wind-locked" flag in store)
- `wind-profile-store.data` (serialized as `{"layers": [[alt, dir, kt], ...]}`)
- `active-metar-store.data` (so the UI can display "Last METAR: KDYB
  131355Z 250/12 22°C 30.05" somewhere — e.g., the existing
  `env-airport-agl` div repurposed or a sibling)

Failure mode: if either fetch fails, leave fields alone (user keeps
manual control). Log warning, don't error.

**Step 3: Commit**

```bash
git commit -m "feat(env): airport pick auto-fills METAR + stages winds-aloft column (H3)"
```

---

## Task H4: Plumb wind_profile into the 5 altitude-changing sims

**Files (per maneuver, one commit each):**

H4a — `simulation/engine_out.py` (5000ft → SFC, highest leverage)
H4b — `simulation/impossible_turn.py`
H4c — `simulation/chandelle.py`
H4d — `simulation/lazy_eight.py`
H4e — `simulation/steep_spiral.py`

**Pattern (engine_out as the template):**

```python
def simulate_engineout_glide(..., wind_profile=None, ...):
    ...
    # Per-tick wind lookup. When wind_profile is provided, prefer it;
    # else fall back to the constant wind_dir/wind_speed args (legacy
    # path — keeps tests passing).
    def _wind_at(alt_agl_ft: float) -> tuple[float, float]:
        if wind_profile is None:
            return (wind_dir, wind_speed)
        alt_msl = airport_elev_ft + alt_agl_ft
        return wind_profile.at(alt_msl)

    while not done:
        wd, ws = _wind_at(alt_agl)
        wn_fps, we_fps = _wind_components_from_dir(wd, ws)
        ...
```

The sim returns `wind_layers_used` in its warnings/meta dict so the
modal can show the column actually consumed (max 4 layers typically:
start, midpoint, ground level + the profile's max).

**Callback edits (same 5 callbacks):**

```python
# State("wind-profile-store", "data") added to draw callback inputs.
# Reconstruct WindProfile:
profile = None
if wind_profile_data and wind_profile_data.get("layers"):
    from core.winds_aloft import WindProfile
    profile = WindProfile([(a, d, k) for a, d, k in wind_profile_data["layers"]])
path, hover, meta = simulate_<m>(..., wind_profile=profile)
```

**Commit (per sim):**

```
feat(engineout): per-tick wind lookup from live winds-aloft column (H4a)
feat(impossible_turn): same (H4b)
feat(chandelle): same (H4c)
feat(lazy_eight): same (H4d)
feat(steep_spiral): same (H4e)
```

---

## Task H5: Winds chip in the results modal + smoke

**Files:**
- Modify: 5 maneuver callbacks (the same as H4) — add a winds-used
  row to the info accordion: `"Winds: SFC 250°/15  3000ft 268°/22  6000ft 281°/28"`.
- Manual smoke at `http://localhost:8050`: pick KDYB, choose Engine-
  Out Glide, draw, confirm the chip shows live data; check that
  changing the env-wind-dir field manually OVERRIDES the live profile
  for that draw (sidebar wins when present).

**Commit:** `feat(maneuvers): results modal shows live winds-aloft column used per sim (H5)`

---

## Acceptance

- `make test` passes ≥ 590 tests (current 580 + H1/H2 helper tests).
- App boots, KDYB METAR auto-fills wind 250°/15, OAT 72°F, altim 30.05.
- Engine-Out Glide from 5000 ft uses a 5-layer column profile. The
  reach circle shifts ~½ NM vs. the old single-layer 250°/15 model
  when there's a 25-kt difference between SFC and 6000ft.
- Offline mode (no internet): app boots clean, sidebar shows defaults,
  no error banners, sims fall back to single-layer wind from sidebar.
- Two upstream xfails (Vne/Vno) remain xfail — unrelated.

---

## Risk + tradeoffs

- ADDS / Open-Meteo downtime → both fetchers degrade to None and we
  fall back to manual sidebar values. Already the existing
  `winds_aloft.py` behavior; we extend it to METAR.
- Cache TTL: 5 min for METAR is the FAA's standard refresh; aloft
  forecasts use top-of-hour rounding (Open-Meteo's grid).
- The 5 sims gain one new optional kwarg each — backward compat with
  the 580 existing tests (they don't pass `wind_profile`, so the
  fallback path keeps current snapshot outputs stable).
- Heading-input sources of truth: METAR wind direction is MAGNETIC by
  ICAO Annex 3 — but the sims expect TRUE for geometry. Convert via
  `_mag_to_true(metar_dir, magvar_at_airport)` at the env-wind-dir
  Output. Winds-aloft from Open-Meteo is TRUE already (model native).
