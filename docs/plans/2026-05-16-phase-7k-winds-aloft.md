# Phase 7k — Live Winds Aloft Along Route

**Status:** planned, not yet started
**Date:** 2026-05-16
**Branch (when started):** `phase-7k-winds-aloft`
**Recommended sequence:** before the slope/openness heatmap (Phase 8). Reasoning at bottom.

---

## Goal

Replace the single scalar wind value (currently typed in the left sidebar
and applied uniformly to every sample) with **per-sample winds aloft**
fetched from a live forecast. The glide corridor, divert reach, and
leg ETE / fuel all become wind-aware along the *actual* route at the
*actual* altitude profile.

Headwinds tighten the upwind reach; tailwinds extend the downwind reach;
the corridor and divert dot set respond accordingly. A westbound CONUS
flight in typical jet-stream patterns will show a visibly asymmetric
corridor — bigger to the east on every sample.

## Data source

**Open-Meteo forecast API** (free, no API key).

- Endpoint: `https://api.open-meteo.com/v1/forecast`
- Multi-point batching: comma-separated `latitude=...&longitude=...`
- Pressure-level wind variables:
  `wind_speed_<L>hPa` and `wind_direction_<L>hPa` for
  L ∈ {1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200, 150, 100}
- Units: pass `&wind_speed_unit=kn` → response is in knots
- Hourly forecast horizon: pass `&forecast_hours=N` (1–N upcoming hours)

**Verified live 2026-05-16:** sample request for KDYB+KSAV at 850 hPa
returned 9.4 kn @ 203° (~5000 ft, southerly summer wind), shape
matches docs.

## Standard atmosphere altitude → pressure (ISA)

For looking up the right pressure level given the sample's MSL altitude:

| Altitude (ft) | Pressure (hPa) |
|---|---|
| 0     | 1013 |
| 1500  | 962  |
| 3000  | 908  |
| 5000  | 843  |
| 7000  | 783  |
| 10000 | 697  |
| 14000 | 595  |
| 18000 | 506  |
| 24000 | 396  |
| 30000 | 302  |
| 39000 | 197  |

Approximated by `pressure_hPa = 1013.25 × (1 − 0.0065 × h_m / 288.15)^5.2561`
(troposphere). For each sample we pick the **two** Open-Meteo levels
that bracket its pressure and **linearly interpolate** between them via
U/V components (degree wraparound is unsafe with raw direction).

## Files touched

```
NEW   core/winds_aloft.py
NEW   tests/test_winds_aloft.py
EDIT  core/corridor.py            (sample_winds optional list)
EDIT  core/diverts.py             (sample_winds optional list)
EDIT  callbacks/route.py          (toggle + fetch + plumbing + status chip)
EDIT  layouts/maneuvers/route.py  (Live Winds checkbox)
EDIT  assets/styles.css           (wind status chip)
```

No new heavy dependencies. Uses existing `requests` + `numpy`.

## Architecture

### `core/winds_aloft.py`

```python
def altitude_ft_to_hpa(alt_ft: float) -> float: ...
def open_meteo_levels_for(pressure_hpa: float) -> tuple[int, int]:
    """Return the two bracketing pressure levels available in
    Open-Meteo for the requested pressure."""

def fetch_winds_aloft(
    latlons: list[tuple[float, float]],
    altitudes_ft: list[float],
    forecast_hour_utc: datetime | None = None,
) -> list[tuple[float, float]] | None:
    """Returns [(wind_dir_deg, wind_speed_kt), ...] one per input,
    or None if the API failed. Per-sample interpolation:
      1. Determine the unique set of bracketing pressure levels.
      2. Single batched GET for ALL latlons × all those levels.
      3. Per sample: look up its bracketing levels, interpolate U/V.
    """

@lru_cache(maxsize=8)
def _cached_batch(
    rounded_latlons: tuple[tuple[int, int], ...],   # quantized to 0.5°
    levels: tuple[int, ...],
    hour_iso: str,
) -> dict | None:
    """LRU around the actual HTTP fetch. Cache key intentionally
    coarse so the same region in the same hour reuses."""
```

Failure modes — return `None` (signal: caller falls back):
- Network/timeout
- HTTP non-2xx
- Response shape mismatch (forecast endpoint change)

### `core/corridor.py` change

Add **optional** `sample_winds: list[tuple[float, float]] | None`:
- Length must match internal sample count (silently falls back to the
  scalar `wind_dir_deg`/`wind_speed_kt` if mismatched, matching the
  pattern of `sample_alts_msl_ft`).
- When provided, each per-direction `_wind_scale` call uses the
  sample's own (dir, speed) instead of the scalar.

### `core/diverts.py` change

Same `sample_winds` parameter, same fallback pattern. The
`can_glide_to` ray-march already accepts wind on the bearing; we just
feed it from the per-sample list instead of the scalar.

### `callbacks/route.py` change

```
1. Read State("route-use-live-winds", "value") + State("env-wind-dir"/"env-wind-speed")
2. If toggle ON:
     winds = fetch_winds_aloft(all_samples, all_alts)
     if winds is None:  fall back to scalar  + set status to "Live unavailable"
     else:              use winds            + set status to "Live · <hh:00Z>"
3. Else:
     use scalar from sidebar                 + set status to "Manual"
4. Pass `sample_winds=winds` (when applicable) to corridor + divert calls
5. Render wind-status chip in the route summary overlay
6. Per-leg summary line gains "HW/TW NN kt" derived from leg track + leg-mid wind
```

### `layouts/maneuvers/route.py` change

Add one shelf field:

```python
_field("Live winds", dcc.Checklist(
    id="route-use-live-winds",
    options=[{"label": " On", "value": "on"}],
    value=["on"],
))
```

### `assets/styles.css` change

`.route-wind-status` chip — small pill with state-colored background:
- Live: green-tinted
- Manual: gray
- Unavailable: amber/red

## Edge cases + behavior

| Case | Behavior |
|---|---|
| Open-Meteo down or timeout | Status: "Live unavailable — using manual wind". Use scalar from sidebar. |
| Forecast hour requested is past the 7-day horizon | Clamp to last available hour. Status notes "forecast horizon reached". |
| Sample below 1000 hPa (way below sea level, won't happen with real airports) | Use the 1000 hPa level. |
| Sample above 100 hPa (~53 kft, jets only) | Use the 100 hPa level. |
| Single waypoint → cleared in render | Toggle ignored. |
| User toggles Live OFF mid-session | Re-Compute uses scalar wind. Per-sample list dropped. |

## Tests (target ~8 new)

- `altitude_ft_to_hpa` standard-atmosphere round-trip at canonical altitudes
- `open_meteo_levels_for` brackets correctly across the layer table
- `fetch_winds_aloft` with monkey-patched requests:
  - happy path returns per-sample (dir, speed)
  - empty response → None
  - HTTP 500 → None
  - missing variable in JSON → None
  - direction interpolation handles wraparound (350° + 10° → ~0°, not 180°)
- `corridor.compute_route_corridor` with `sample_winds` shifts the
  envelope vs uniform-wind baseline (tailwind direction has larger
  reach)
- `diverts.divert_coverage_along_route_glide` with `sample_winds` —
  a tailwind-only-reachable airport shows up only when winds aloft
  provides the tailwind, not in calm

## Performance

- One batched HTTP request for the whole route (~50–150 samples × 2
  pressure levels × 2 vars).
- Open-Meteo measured: ~150 ms first call, ~50 ms subsequent.
- LRU cache key on (0.5° grid, level set, forecast hour) — re-Compute
  on the same route within the hour = instant.
- Total added cost vs current path: **+150 ms cold, +0 ms warm**.

## Out of scope (deferred to 7k+)

- **Temperature aloft → density altitude → adjusted climb rate.**
  Open-Meteo exposes `temperature_<L>hPa` on the same call; we'd compute
  DA per sample and degrade climb rate accordingly.
- **METAR-based surface wind for departure/arrival.** Different feature
  (Phase 4 in EM Diagram repo, not ported).
- **Forecast time picker.** v1 uses current forecast hour. UI for
  "depart at 18:00Z tomorrow" comes later.

## Acceptance criteria

1. New shelf checkbox "Live winds" defaulting On.
2. Wind-status chip appears in the route overlay showing source +
   freshness (e.g. "Live · 16:00Z" or "Manual · 360°@0kt").
3. Corridor on a 600 NM E-W route with real winds shows visibly
   asymmetric reach (tailwind side bigger).
4. Per-leg overlay rows gain a "HW/TW N kt" component vs leg track.
5. When the API is unreachable, the route still computes using the
   sidebar's scalar wind. Status reflects that.
6. Cold-cache + Compute on a CONUS route finishes within 3 seconds
   total (existing terrain + the new winds fetch).
7. ≥8 tests in `tests/test_winds_aloft.py`, full suite still green
   (262+ tests).

---

## Sequencing recommendation: 7k before 8 (heatmap)

**Reasons to do winds-aloft FIRST:**

1. Improves outputs that *already exist* on every route compute —
   corridor + diverts + ETE all become more accurate without any new
   visual layers. Compounds with the work just shipped (terrain
   ridge-clip + flight profile).
2. Small surface area (~7 files, mostly additions). ~1–2 sessions.
3. The user explicitly noticed it was missing — momentum + signal.
4. Heatmap design has multiple open decisions still pending
   (which land-cover dataset: ESA WorldCover 10m vs Esri Living
   Atlas 10m; slope threshold UI; how to weight slope vs cover;
   how to display the score raster; whether to also bake an
   "openness distance" raster). Better to make those decisions with
   working winds in the corridor so the heatmap can layer on top of
   a more truthful corridor.

**Reasons heatmap could go first** (kept here for honesty):

- Visual impact of "the map looks finished" — heatmap is the
  big-ticket new visualization.
- Heatmap unlocks Phase 9 route critique (slope + cover + diverts +
  winds → score). But winds is also a Phase 9 input, so 7k feeds 9
  too.

**Net:** 7k is the smaller, higher-compound-value insert. 8 (heatmap)
remains queued right after.
