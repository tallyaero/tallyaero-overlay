# Phase 7L — Terrain Conflict Presentation

**Status:** planned, queued after Phase 7k (winds aloft)
**Date:** 2026-05-16
**Branch (when started):** `phase-7L-terrain-conflict`
**Scope decision:** A + B + B+ + E (visual + suggested altitude + one-click apply + side-view profile)

---

## Goal

Surface terrain that conflicts with the pilot's chosen cruise altitude
in three escalating ways:

1. **See it on the map.** Polyline segments are colored by AGL vs
   terrain — green clear, amber marginal, red conflict.
2. **Get a number to act on.** A suggested minimum-safe cruise altitude
   computed from peak terrain in the corridor strip, rounded up to
   the next VFR-legal cruising altitude per FAR 91.159, with a chip
   showing where the limiting peak is.
3. **Apply it in one click.** A button next to the chip fills the
   cruise alt field and re-Computes the route.
4. **See the whole profile.** A small altitude-vs-distance thumbnail
   in the overlay shows your flight profile (line) against terrain
   along the centerline (filled area below). Profile View pilots
   know from ForeFlight.

What we DON'T do — auto-adjusting cruise altitude silently. Pilot
inputs are sacrosanct. A safe-altitude SUGGESTION is offered; the
pilot decides.

## Two distinct signals (don't conflate)

| Signal | Meaning | Severity | Current UX | New UX |
|---|---|---|---|---|
| `cruise_alt < terrain` | Route flies into a mountain at cruise | **Unflyable** (FAR 91.119) | Single red number "Below ridge: N samples" | Red polyline segments + suggested altitude chip + flashing "Cruise conflicts terrain" header |
| `cruise above terrain, engine-out can't clear` | Glide corridor pinches | **Survivability gap** | Red dashed "no airfield in glide" already working | Unchanged |

## VFR cruise altitude rule (FAR 91.159)

Above 3000 ft AGL but below 18000 ft MSL, magnetic course determines
the valid cruise altitudes:

- **Eastbound** (000°–179° magnetic): odd-thousand + 500 ft (3500, 5500, 7500…)
- **Westbound** (180°–359° magnetic): even-thousand + 500 ft (4500, 6500, 8500…)

The suggested-min-altitude calculation rounds **up** to the next
valid altitude for the route's magnetic course. Multi-leg routes use
the magnetic course of the leg whose terrain peak is limiting.

## Files

```
NEW   core/terrain_conflict.py
NEW   tests/test_terrain_conflict.py
EDIT  callbacks/route.py            (segmented polyline + suggested chip + button)
EDIT  layouts/maneuvers/route.py    (Suggested-alt button + profile chart container)
EDIT  assets/styles.css             (segment color tokens + profile chart styling)
```

## Architecture

### `core/terrain_conflict.py` — new module

```python
def classify_sample_terrain_status(
    sample_msl_ft: float,
    terrain_ft: float,
    marginal_agl_ft: float = 2000.0,
    conflict_agl_ft: float = 500.0,
) -> str:
    """Returns one of: 'clear' | 'marginal' | 'conflict'.
    - clear:    AGL >= 2000 ft
    - marginal: 500 ft <= AGL < 2000 ft
    - conflict: AGL < 500 ft or terrain pierces flight profile
    """

def segment_polyline_by_status(
    samples: list[tuple[float, float]],
    statuses: list[str],
) -> list[dict]:
    """Group consecutive samples with same status into segments.
    Returns [{status, positions: [[lat, lon], ...]}, ...] for
    rendering as multiple dl.Polyline layers."""

def max_terrain_in_corridor_strip(
    samples: list[tuple[float, float]],
    elevation_fn: Callable[[float, float], float],
    half_width_nm: float,
) -> tuple[float, float, float]:
    """Return (max_terrain_ft, peak_lat, peak_lon). Walks a swath of
    perpendicular offsets at each sample to capture terrain not just
    on the centerline."""

def suggest_min_cruise_alt(
    max_terrain_ft: float,
    leg_magnetic_courses: list[float],
    mountainous: bool = None,    # auto-detect from terrain variance if None
) -> tuple[float, str]:
    """Returns (suggested_alt_ft, reason_string). Applies:
      - +1000 ft buffer for non-mountainous, +2000 ft for mountainous
      - Rounds up to next VFR-legal cruise altitude per FAR 91.159
      - Uses the limiting-leg's magnetic course for the rounding rule
    """

def vfr_cruise_round_up(
    altitude_ft: float,
    magnetic_course_deg: float,
) -> float:
    """Round altitude up to the next valid VFR cruise altitude.
    Below 3000 AGL or above 18000 MSL: just round to next 500 ft.
    Eastbound (000–179° M): next of ...3500, 5500, 7500...
    Westbound (180–359° M): next of ...4500, 6500, 8500...
    """
```

### Segmented polyline in `callbacks/route.py`

Replace the single `dl.Polyline(...)` for the route line with N
polylines, one per status segment, each colored:

| Status | Color | Weight | Notes |
|---|---|---|---|
| clear | `#0d59f2` (current blue) | 3 | Default |
| marginal | `#f59e0b` (amber) | 4 | Slightly thicker so it's noticeable |
| conflict | `#dc2626` (red) | 5 | Thicker; tooltip "Cruise altitude X ft below terrain Y ft" |

The existing red-dashed "no-divert gap" polyline is separate and
remains — different semantic, different visual.

### Suggested-altitude chip + button

Overlay summary card gains a row when conflict is detected:

```
⚠ Cruise alt conflicts terrain
  Peak: 6,800 ft near 39.5°N 78.3°W (Mt Whatever)
  Suggested: 8,500 ft (next VFR cruise eastbound)   [ Use 8,500 ]
```

Clicking "Use 8,500" fills `route-cruise-alt` and fires Compute Route
through an existing trigger pathway (or the button itself is a new
Input on the compute callback).

### Altitude profile side-view

New `dcc.Graph(id="route-profile-chart")` inside the overlay card,
rendered only when a route exists. Plotly figure:
- x: distance from departure (NM)
- y: altitude (ft MSL)
- Filled area below: terrain along centerline (sampled every ~1 NM)
- Line above: flight profile from `core.flight_profile` (climb +
  cruise + descent segments visible)
- Annotation arrows + red shading where flight profile dips below
  terrain
- Compact dimensions (~280 × 80 px) so it fits in the overlay panel
  without dominating

Optional secondary trace: shaded band showing the "max terrain in
corridor strip" (not just centerline) — pilots see the worst-case
terrain even if the centerline is clear.

## Edge cases

| Case | Behavior |
|---|---|
| Cruise above terrain peak but corridor strip has higher terrain | "marginal" segments rendered amber, profile chart shows the corridor-strip envelope |
| Route is short — climb meets descent before reaching cruise | `has_cruise=False` from the flight profile; use the actual peak altitude reached for status classification |
| Suggested altitude > aircraft max_altitude | Cap at aircraft max and show warning: "Aircraft service ceiling reached — terrain unavoidable at any flyable altitude. Reroute required." |
| Marginal AGL only (no full conflict) | No chip, no suggestion. Just amber polyline segments + tooltip explaining marginal AGL. |
| Pilot is purposely flying low (e.g. VFR over flat terrain at 1500 AGL) | "marginal" amber kicks in but no chip suggesting climb. Pilot acknowledges by ignoring. |
| Pilot clicks "Use suggested" but aircraft can't reach it before TOC | Flight profile already handles: `actual_cruise_alt` auto-reduces. Recompute shows the reduced cruise. Status may still be conflict — surface a second warning. |

## Tests (target ~10 new)

- `classify_sample_terrain_status` thresholds: clear / marginal /
  conflict boundaries, exact-equal cases.
- `segment_polyline_by_status`: alternating, all-same, single-sample
  segments.
- `vfr_cruise_round_up` eastbound: 5000 → 5500, 5499 → 5500, 5500 →
  5500 (exact match stays), 5501 → 7500.
- `vfr_cruise_round_up` westbound: same, with even-thousand+500.
- `vfr_cruise_round_up` below-3000-AGL: just round to next 500.
- `suggest_min_cruise_alt`: flat terrain (peak + 1000 ft buffer,
  rounded), mountainous terrain (peak + 2000 ft buffer, rounded),
  ceiling-exceeded case.
- `max_terrain_in_corridor_strip`: synthetic ridge perpendicular to
  route → peak found off-centerline.

## Acceptance criteria

1. Polyline visually segments into green / amber / red by AGL vs
   terrain. Hovering each segment shows the AGL value.
2. When `below_terrain_samples > 0`, the overlay shows the suggested
   cruise altitude chip with limiting peak location + a one-click
   button.
3. Clicking the button updates the cruise alt input AND re-triggers
   Compute Route.
4. Profile thumbnail renders in the overlay, showing terrain envelope
   + flight profile + any conflict shading.
5. Suggested altitudes are VFR-legal per FAR 91.159 (eastbound vs
   westbound rules respected).
6. Pilot's typed cruise alt is NEVER silently overwritten. Suggestion
   is always opt-in.
7. ≥10 tests in `tests/test_terrain_conflict.py`, full suite green.

## Out of scope (deferred)

- **D — Route detour suggester.** Reroute around terrain rather than
  climb over it. Phase 10. Needs Phase 8's suitability raster + a
  graph search.
- **IFR MEA / MOCA.** Use IFR enroute chart MEA when available.
  Different data source (FAA NASR airways).
- **Day-of mountain wave / turbulence forecast.** Different feature.

---

## Why A + B + B+ + E together

A (coloring) and B (suggested chip) are tightly coupled — both
depend on the same per-sample terrain classification. B+ (button) is
a 10-line callback on top of B. E (profile chart) is the visual
story for everything else and re-uses the per-sample altitudes the
flight profile already produces. Bundling them ships the full
"pilot understands the terrain situation" story in one merge instead
of three.
