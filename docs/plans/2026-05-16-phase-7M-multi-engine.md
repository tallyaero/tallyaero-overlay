# Phase 7M — Multi-engine engine-out modeling

**Status:** planned, queued after Phase 7L
**Date:** 2026-05-16
**Branch (when started):** `phase-7M-multi-engine`
**Data approach:** POH research, one-time pass

---

## Why this matters

Our current corridor math assumes engine-out = glider. That's correct
for a Cessna 172. It's catastrophically wrong for a Piper Seneca II
at 12,000 ft, where the actual reach on remaining engine is **roughly
20× larger** than the glide-only number we draw.

Concrete: Seneca II, engine quits at 12,000 ft.
- **Current model (glider)**: `12000 × 9.5 / 6076 ≈ 19 NM` reach
- **Reality**: drift down to SE service ceiling (~13,000 ft → already
  below it, so the airplane just descends 50–200 fpm into level
  flight on remaining engine), then sustain at the SE cruise speed
  using remaining fuel. **Reach = 400+ NM.**

A pilot looking at our corridor thinks engine-out means picking from
a tiny circle of diverts. Real twin pilots have far more options.
Per the "no corners on aircraft data" rule, this is a correctness
gap to close.

## What we have today (audited)

For the 10 multi-engine aircraft in `aircraft_data/`:

| Field | Coverage |
|---|---|
| `engine_count` | 10/10 |
| `single_engine_limits.Vmca` (clean / takeoff / landing) | 10/10 |
| `single_engine_limits.Vyse` | 10/10 |
| `single_engine_limits.Vxse` | 10/10 |
| `single_engine_limits.best_glide` + `best_glide_ratio` | 10/10 |
| `max_altitude` (two-engine ceiling) | 10/10 |

## What's missing

These are the fields the driftdown + powered-reach math needs:

| Field | Purpose | Typical value (piston twin) |
|---|---|---|
| `single_engine_limits.service_ceiling_ft` | Altitude where SE RoC = 50 fpm (FAR 23.65). Above this, the aircraft drifts down. | 7,000 – 14,000 ft |
| `single_engine_limits.rate_of_climb_sl_fpm` | SE RoC at sea level, gross weight. Anchors the driftdown curve. | 150 – 300 fpm |
| `single_engine_limits.cruise_kt` | TAS at SE cruise power. | 100 – 140 kt |
| `single_engine_limits.fuel_burn_gph` | Per-engine fuel burn at SE cruise. | 8 – 14 gph |

40 lookups total (10 aircraft × 4 fields).

## Aircraft to research (POH/AFM)

| Aircraft | TCDS | Source priority |
|---|---|---|
| Beechcraft Baron 58 | 3A16 | Beechcraft POH |
| Cessna 310R | 3A10 | Cessna POH |
| Diamond DA42-L360 | A56CE | Diamond AFM |
| Diamond DA42-NG | A56CE | Diamond AFM |
| Diamond DA62 | A00010NY | Diamond AFM |
| Piper Aztec F | 1A10 | Piper POH |
| Piper PA-30 Twin Comanche | A1EA | Piper POH |
| Piper PA-34 Seneca | A7SO | Piper POH (Seneca II/III/V) |
| Piper PA-44 Seminole | A19SO | Piper POH |
| Tecnam P2006T | EASA.A.185 | Tecnam AFM |

Each entry adds to its aircraft's `sources` array:
```json
{"type": "POH",
 "title": "Piper Seneca II Pilot's Operating Handbook",
 "section": "Section 5 - Performance, p. 5-15",
 "fields_added": ["single_engine_limits.service_ceiling_ft",
                  "single_engine_limits.rate_of_climb_sl_fpm",
                  "single_engine_limits.cruise_kt",
                  "single_engine_limits.fuel_burn_gph"]}
```

## Sub-phases

### 7M-a — Schema + data (the research pass)

```
EDIT  core/schema.py           (extend SingleEngineLimits Pydantic model)
EDIT  10 × aircraft_data/*.json (POH lookups + sources entry per aircraft)
EDIT  tests/test_aircraft_schema.py  (the Pydantic validator now demands
                                      the 4 new fields for ME aircraft)
```

### 7M-b — Math

```
NEW   core/multi_engine.py
NEW   tests/test_multi_engine.py
```

Public API:
```python
def is_multi_engine(aircraft: dict) -> bool: ...

def driftdown_profile(
    aircraft: dict,
    start_alt_msl_ft: float,
    weight_lb: float | None = None,
    wind_along_track_kt: float = 0.0,
) -> dict:
    """Returns: {
      target_alt_msl_ft,        # SE service ceiling (weight-adjusted)
      descent_time_min,
      ground_distance_nm,       # forward distance covered during driftdown
      already_below_ceiling,    # True if start_alt <= service ceiling
    }
    """

def single_engine_powered_reach_nm(
    aircraft: dict,
    current_alt_msl_ft: float,
    fuel_remaining_gal: float,
    bearing_deg: float,
    wind_dir_deg: float,
    wind_speed_kt: float,
    dest_elev_ft: float = 0.0,
    weight_lb: float | None = None,
) -> float:
    """Total ground distance the aircraft can cover on remaining
    engine: driftdown_horizontal + level-flight fuel-range at SE
    cruise + headwind/tailwind correction. Returns the directional
    reach for one bearing — caller iterates n_envelope_points
    bearings to build a polygon (same shape as the glide envelope
    but vastly larger and based on powered flight)."""
```

Math notes:
- Driftdown rate at altitude h: linear interpolation between
  `SE RoC at sea level` (positive at sea level for most twins below
  their SE ceiling, negative i.e. descent rate above ceiling) and
  zero rate at the SE service ceiling.
- Above SE ceiling: descent rate = `(h - SE_ceiling) × k` where k
  reflects how fast power deficit grows with altitude. POH driftdown
  charts give this directly; we approximate with the SE_RoC anchor.
- Below SE ceiling: powered level flight, no driftdown segment.
  Total reach = fuel_remaining / fuel_burn_gph × SE_cruise_kt
  ± wind component.

### 7M-c — Corridor + divert branching, with engine-out-mode toggle

For ME aircraft the corridor can be computed under **two** failure
scenarios, and the pilot can view either or both:

| Mode | Math | Color | Meaning |
|---|---|---|---|
| **SE powered** (default) | `single_engine_powered_reach_nm` — driftdown + level flight on remaining engine + fuel range | Purple `#a855f7` / `#c084fc` 0.18 fill | "If one engine fails, here's where I can go." Realistic for most twin emergencies. |
| **Both engines out** | Existing glide math (same as a single, using `best_glide_ratio`) | Green `#22c55e` 0.18 fill (current corridor color) | "If BOTH engines fail (fuel exhaustion, fuel contamination, dual electrical, etc.), here's my glide." Catastrophic but real. |
| **Show both** | Render both polygons stacked, green underneath, purple on top | Both | Visually compare: the small green glide footprint sits inside the much larger purple powered-reach footprint. The pilot sees the gap in capability. |

```
EDIT  core/corridor.py        (engine_out_mode param: 'se' | 'glide' | 'both')
EDIT  core/diverts.py         (same — divert set differs by mode)
EDIT  tests/test_corridor.py  (ME case both modes)
EDIT  tests/test_diverts.py   (ME case both modes)
```

The corridor's per-direction reach becomes:
```python
def per_direction_reach(aircraft, mode, ...):
    if not is_multi_engine(aircraft) or mode == "glide":
        # glider math (existing)
        return wind_scaled_glide_reach × terrain_intercept
    if mode == "se":
        return min(
            single_engine_powered_reach_nm(aircraft, sample_alt, fuel,
                                            bearing, wind, ...),
            terrain_intercept_nm(...),
        )
    # mode == 'both' is handled by the caller: compute corridor twice
    # (once with 'se', once with 'glide') and stack the polygons in
    # the route layer with the glide layer on top so it stays visible.
```

For diverts under "both" mode: render the SE-reachable airports as
purple dots, and the glide-only-reachable subset (which is the *same*
airport set if the airplane is within glide of them — i.e. close in)
as green dots overlaid. A pilot sees which diverts survive a dual
failure vs. an SE failure.

In "se" mode for an ME, divert filtering uses SE powered reach (much
larger set, dozens to hundreds at cruise). In "glide" mode for an
ME, divert filtering uses the same glide math as a single.

### 7M-d — UI

```
EDIT  layouts/maneuvers/route.py
EDIT  callbacks/route.py        (different default field set per aircraft type +
                                  engine-out-mode toggle handling)
EDIT  callbacks/aircraft.py     (route_layout call branches on engine_count)
EDIT  assets/styles.css         (.route-corridor-poly-me, .engine-out-toggle)
```

**Engine-out mode toggle** (only rendered for ME aircraft):

A new shelf field "Engine-out scenario" with three radio-style pills:
- `SE` — One engine failed (powered, drift down + sustain)
- `Glide` — Both engines failed (glider math, far smaller)
- `Both` — Render both corridors stacked

Default: `Both`. Defaulting to "Both" is the safety-positive choice —
pilots see at a glance that the dual-out case is a much tighter
footprint than the single-out case, and they're never surprised by
which scenario the corridor represents.

For single-engine aircraft the toggle is hidden (only one scenario
makes sense; the existing green glide corridor is the answer).

Shelf field swap when engine_count >= 2:
- Hide: Glide Ratio, Glide IAS (still used as fallback below SE
  ceiling and as the "Glide" mode inputs; pilot doesn't need to set
  them at the surface)
- Show: SE Service Ceiling, SE Cruise, SE Fuel Burn (all
  aircraft-derived defaults, all editable for sanity)
- Show: Engine-out scenario toggle (SE | Glide | Both)

Shelf field swap when engine_count >= 2:
- Hide: Glide Ratio, Glide IAS (still used as fallback below SE
  ceiling but the pilot doesn't need to set them)
- Show: SE Service Ceiling, SE Cruise, SE Fuel Burn (all
  aircraft-derived defaults, all editable for sanity)

Map: corridor polygon for ME aircraft uses
`color="#a855f7", fillColor="#c084fc", fillOpacity=0.18`
(violet/purple) instead of the green glide-reach palette.

Summary card adds:
- "SE service ceiling: 13,000 ft (weight-adjusted)"
- "SE reach from cruise: 412 NM"
- "Driftdown: 8 min, 17 NM forward to ceiling"

## Honest caveats (surface in UI tooltip / footer)

Critical to honest UX:

- SE performance assumes **critical engine failure** (the engine
  whose loss makes the airplane hardest to control — typically the
  left engine on counter-rotating twins or the unfavorable-rotation
  engine on conventional twins).
- Assumes **secured failed engine**: feathered, mixture off, fuel
  selector off, etc. An unfeathered prop adds enormous drag — real
  SE performance with windmilling prop is ~50% of secured numbers.
- **Density altitude degrades SE numbers fast.** A Seneca II's
  published 13,000 ft SE ceiling drops below 10,000 ft on a hot day.
  v1 uses standard-atmosphere; a tooltip surfaces the caveat. Phase
  7M+ adds DA correction.
- **Weight matters.** SE ceiling drops ~500 ft per 100 lb above
  empty. v1 uses gross-weight numbers (conservative); the existing
  weight-and-balance state could feed in for later refinement.
- Real-world ME engine-out at cruise altitude assumes **immediate
  identification + correct procedure** by the pilot. Climbing on
  one engine from the runway is a different trained scenario and
  not what this tool models.

## Tests

`tests/test_multi_engine.py` — target ~12 new:

- `is_multi_engine` returns True/False correctly across the catalog
- `driftdown_profile`:
  - Below SE ceiling → already_below_ceiling=True, zero driftdown
  - Above SE ceiling → positive descent time, positive forward distance
  - 12000 ft start, 13000 ft ceiling → already below ceiling
  - 18000 ft start, 13000 ft ceiling → driftdown
  - Tailwind extends forward distance, headwind shrinks
- `single_engine_powered_reach_nm`:
  - Calm air, full fuel, Seneca II at 8000 ft → ~400 NM
  - Half fuel → ~200 NM
  - Heavy headwind → reach shrinks
  - Tailwind → reach extends
  - Above SE ceiling → driftdown phase + level phase combined
- Corridor uses ME math when engine_count >= 2 (one happy-path test)
- Divert reach uses ME math (one happy-path test)

`tests/test_aircraft_schema.py` — new assertion:

- Every ME aircraft has all 4 new SE fields populated (gate the
  research pass with a test)

## Acceptance criteria

1. All 10 ME aircraft have POH-sourced values for the 4 new fields,
   each with a `sources[]` entry citing the document.
2. Pydantic schema enforces the new fields are present on ME
   aircraft (test fails until research lands).
3. ME aircraft shelf shows an "Engine-out scenario" toggle with
   three options: SE | Glide | Both. Default is Both.
4. In **SE mode**, the Seneca II at 8000 ft cruise draws a purple
   powered-reach polygon covering ~400 NM (vs the ~13 NM glide
   circle we currently show).
5. In **Glide mode**, the same Seneca renders the small green
   glide-only corridor (identical math to a single).
6. In **Both mode**, both polygons are drawn stacked — green glide
   visible on top of the larger purple SE footprint. Pilot sees the
   capability gap at a glance.
7. Diverts in SE mode for a Seneca include airports up to powered
   reach away (dozens to hundreds at cruise); diverts in Glide mode
   match the single's glide range.
8. Shelf shows ME-specific defaults when the aircraft is a twin.
   Hidden when the aircraft is a single.
9. Tooltips on the SE corridor explain critical-engine assumption +
   secured-engine assumption + DA caveat.
10. Singles render exactly as before. No regression on the 100
    single-engine aircraft in the catalog. Toggle is not shown.
11. Full test suite passes.

## Out of scope

- **Density-altitude SE performance correction.** Phase 7M+ once we
  plumb OAT/altimeter into the reach call.
- **Single-engine takeoff abort modeling** (V1/Vr/Vyse splits for
  takeoff). Different feature — engine-out near runway, not cruise.
- **Three+ engine aircraft** (e.g. P-3, jet trijets). Catalog has
  none. Math generalizes if we ever add them — "powered reach with
  N-1 engines."
- **Three-engine-inop training drills for quad aircraft.** N/A.

---

## Sequencing

After 7k (winds aloft) and 7L (terrain conflict). Both feed cleanly
into 7M:

- Winds aloft already plumbs per-sample wind into corridor/divert via
  `sample_winds` — ME powered reach uses the same wind per bearing.
- Terrain conflict's profile chart visualizes the flight altitude vs
  terrain; for ME, it'd visualize the driftdown line too (showing
  whether driftdown clears terrain ahead).

7M can also stage:
- 7M-a (data + schema) → can ship independently as the first PR
- 7M-b + 7M-c + 7M-d (math + integration + UI) → second PR
