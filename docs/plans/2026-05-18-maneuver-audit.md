# TallyAero Maneuver Overlay — Comprehensive Audit
**Date:** 2026-05-18
**Scope:** Every maneuver in the dropdown + sidebar controls
**Status:** Research only — no action taken pending user approval

> Caveats: this audit was produced by an Explore agent reading the
> codebase with sampling. Specific claims (e.g. "Power slider unused
> by turns_point") need code verification before any refactor. The
> Cross-Cutting Quality and Sidebar Usage Matrix sections are
> particularly worth re-checking by tracing actual State→callback
> dependencies.

---

## Cross-Cutting Conventions (Approved 2026-05-18)

These conventions apply to every maneuver. Future production-pass
PRs are bound by them.

### Field label format
- Every numeric/text input label includes its unit in parentheses:
  `Alt (ft)` · `IAS (kt)` · `Bank (°)` · `Distance (NM)` ·
  `ETE (min)` · `Fuel (gal)`.
- Unitless concepts use the bare label: `Direction` · `Sequence` ·
  `Turns`.
- Aircraft-derived defaults stay in **placeholders**, not labels.
  E.g. `IAS (kt)` with placeholder text "Va".

### Button verb pattern
- Map-click prompts → `Set [ROLE]`: `Set Touchdown`, `Set Entry`,
  `Set Center`, `Set Reference`, `Set Pylon 1`.
- Simulation render → `Draw`.
- Heavy multi-step compute → `Compute [Noun]` (e.g. `Compute Route`).
- Drop numbered prefixes (`1. Start`, `2. Ref Pt`) — replace with
  `Set [ROLE]` where the ROLE itself makes ordering obvious.
- Multi-step exceptions: keep numbering only when sequence isn't
  obvious from the role names. Rectangular Course uses
  `Set Downwind Start` then `Set Downwind End`.

### Map color → role mapping
Single source of truth for every maneuver's markers and lines:

| Role | Color | Hex |
|---|---|---|
| Start / entry / takeoff | green-500 | `#22c55e` fill, `#15803d` stroke |
| End / touchdown / exit | red-500 | `#ef4444` fill, `#991b1b` stroke |
| Reference / pivot / center | blue-500 | `#3b82f6` fill, `#1e40af` stroke |
| Intermediate / pylon | amber-500 | `#f59e0b` fill, `#b45309` stroke |
| Active flown path | blue-600 solid | `#0d59f2` weight 3 opacity 0.85 |
| Off-design / failure / conflict | red-600 solid | `#dc2626` weight 5 opacity 0.95 |
| Marginal status | amber-600 solid | `#d97706` weight 4 opacity 0.95 |
| Preview / reference line | brand-blue dashed | `#0d59f2` weight 2 opacity 0.65 dash 6,6 |
| Envelope / corridor outline | lime-500 dashed | `#84cc16` weight 1 opacity 0.55 dash 4,4 |

**Solid vs dashed:** solid = something flown; dashed = reference,
preview, envelope.

**Color-blind mitigation** (red/green is the classic problem pair):
- Markers also carry positional semantic — start is always the
  FIRST clicked point, end is always LAST.
- Path status pairs color with thickness — clear=thin blue,
  marginal=medium amber, conflict=thick red — so weight alone
  communicates status without color perception.
- Small icon overlay on markers — ▶ start, ■ end, ◉ reference —
  doubles the signal.

### Error handling — three tiers
Replace silent `PreventUpdate` everywhere except first-load
no-ops.

1. **Inline shelf error** for missing required inputs
   ("Set the entry point first"). Small red chip near the Draw
   button.
2. **Computed-field warning** for off-design inputs
   ("Chandelle at 50% power may not complete — design is 100%").
   Amber chip, doesn't block.
3. **Maneuver-failed verdict** for genuine sim failures (chandelle
   can't reach 180°, impossible turn doesn't make the runway).
   Red banner with explanation.

Same component pattern, three severity levels.

### Tooltip policy
Every interactive control (`dcc.Input`, `dcc.Dropdown`,
`dcc.RadioItems`, `dcc.Checklist`, `html.Button`) must have a
`title=` (or wrapping `html.Span(title=...)`) explaining what it
does and why a non-default value matters.

Implementation: extend the existing `_field()` helper in
`layouts/maneuvers/_shared.py` to accept an optional `tooltip`
kwarg, and the existing `_pill()` pattern in `route.py`. Acceptance
bar: zero shelf controls without tooltips before a maneuver is
called "production-ready".

---

## Cross-Cutting Features (Approved 2026-05-18)

In-scope items for the production-ready sweep, plus the items
explicitly deferred so future-me doesn't re-litigate.

### C.1 — Quick Start modal coverage  → IN SCOPE
Modal currently covers 6 of 12 (Impossible Turn, Power-Off 180,
Engine-Out Glide, Steep Turns, Chandelle, Lazy Eight). Add a
one-paragraph entry for each missing maneuver — Route Planner
(flagship; currently missing!), Steep Spiral, S-Turns, Turns
Around a Point, Rectangular Course, Eights on Pylons. Same
format as existing entries: what it is · when used · what the
tool computes.

### C.2 — Mobile responsiveness  → DEFERRED
Not part of the production-ready sweep. This tool is primarily
a pre-flight planning surface used at a desk / yoke-mounted
tablet, not a phone. Mobile-first overhaul is its own multi-day
phase. Tracked as future work.

### C.3 — Accessibility basics  → IN SCOPE (limited)
- `aria-label` on every shelf control. Falls out of the Theme B
  tooltip work automatically (tooltip text = aria-label).
- Non-color status cues addressed by Theme B color convention
  (positional + thickness + icon overlays).
- Keyboard map interaction = OUT OF SCOPE (would need numeric
  lat/lon fallback per "Set Point"; target user has a mouse).

### C.4 — Hardcoded constants → per-aircraft JSON  → IN SCOPE (expanded)

Aircraft constants currently hardcoded in simulation code:
- `roll_rate_dps` = 5 (steep_turn) — likely WAY too slow,
  should be 30-120 dps
- `bank_response_tau_s` = 5 (engineout glide)
- `speed_response_tau_s` = 1.5 (engineout glide)
- `takeoff_accel_factor` (impossible_turn)
- `inter_maneuver_pause_s` = 1 (steep_turn)

**Three-tier sourcing strategy** to cover all 110 aircraft, not
just a handful:

**Tier 1 — Class-derived defaults (all 110 aircraft).** Build
`data/scrapers/classify_dynamics.py` mirroring the existing
`classify_thrust_models.py` pattern. Derives from fields already
in the aircraft JSONs:

| Constant | Derivation rule |
|---|---|
| roll_rate_dps | Aerobatic (`G_limits` ≥ 6) = 120 · Aerobatic-trainer = 90 · Trainer (4.4 G) = 45 · Light single = 40 · Light twin = 25 · Complex/retract = 35 |
| bank_response_tau_s | `~1.3 / roll_rate_rad_s` (inverse of roll rate) |
| speed_response_tau_s | First-order longitudinal from `mass / (CD0 × wing_area × ρV)` at cruise condition — all values present in JSON |
| takeoff_accel_factor | `(hp × 550 × 0.85_prop_eff) / (max_weight × Vlof_fps)` → fraction of g. HP from engine_options, weight from max_weight |

**Tier 2 — POH-curated refinements (10-15 reference aircraft):**
C152, C172, C182, Cherokee 140, Warrior, Archer, Arrow, Cirrus
SR20/22, Decathlon, Citabria, Super Decathlon, Bonanza V35,
Seminole, Twin Comanche. POH-sourced values override the
class default. Source citation goes in provenance.

**Tier 3 — Provenance:** Each `performance_dynamics` entry carries
`source: "poh" | "class_derived" | "estimated"`. UI tooltips show
"(POH-sourced)" vs "(class-estimated)" so the pilot knows what
trusts what.

Deliverables: `scripts/classify_dynamics.py`, `core/dynamics.py`
loader + `dynamics_for(aircraft)` helper, all 110 aircraft JSONs
updated, `tests/test_classify_dynamics.py` sanity tests
(Aerobatic > Trainer roll rate, etc).

### C.5 — Multi-engine asymmetric thrust  → DEFERRED
`impossible_turn`, `engineout`, `poweroff180` accept Engine select
but don't model asymmetric thrust / Vmc for twins. Real physics
work; needs per-aircraft Vmc, dead-engine torque, control authority
data. Dedicated phase later.

**Interim mitigation (in-scope):** When ME aircraft selected, show
a small disclaimer chip on those maneuvers: "ME asymmetric thrust
not modeled — treated as single-engine glide". Honest about the
limitation.

### C.6 — Load factor / stall margin on Steep Turns  → IN SCOPE
Add a result chip after Draw:
- Bank angle · Load factor (G) · Stall speed at this load
  (`Vs × √n`) · Margin to your IAS
- Example: `45° · 1.41 G · stall 67 kt · 33 kt margin at 100 kt`
- Warning style if margin < 10 kt

Trivial math, real safety value. Same pattern reusable for any
maneuver with a sustained bank.

### C.7 — Altitude profile on Chandelle / Lazy 8 / Steep Spiral  → IN SCOPE
These three maneuvers are *defined* by altitude profile (Chandelle
= climb; Lazy 8 = oscillation; Steep Spiral = descent). Showing
path without altitude is missing the point. Add a compact Plotly
altitude-vs-time chart in each maneuver's info panel, same pattern
as Route's profile chart.

---

## Design Directive — Power & CG Inputs Must Be Real

**Established 2026-05-18 during audit walkthrough. Locks the design
intent for the production-ready pass.**

**Power slider is NOT dead** — it's consumed by `s_turn`,
`turns_point`, `rect_course`, `pylons` callbacks and declared in
the corresponding simulation functions. The gap is that its
**effect is too small** to be visible to the pilot. Same for CG
slider, which is wired through six maneuvers and computes a
~2% stall-factor adjustment — order of magnitude is realistic.

**Direction:** Make power matter visibly. Each maneuver has a
**design power setting** (what the maneuver is intended to be
flown at). User-set deviations from design produce realistic,
visible consequences in the simulation output and on the rendered
path. Extreme off-design produces a "maneuver failed" verdict.

| Maneuver | Design Power | Off-Design Effect |
|---|---|---|
| Route Planner | cruise (pilot picks via TAS/IAS) | n/a — power slider hidden |
| Impossible Turn | 100% until failure | post-failure: prop dropdown drives windmill/feather |
| Power-Off 180 | idle (definitional) | slider as "partial power left" — may want relabel |
| Engine-Out Glide | idle/windmilling | same as PO180 |
| **Steep Turns** | ~65–75% (45° std) | low → altitude lost; high → gained or excessive G |
| **Chandelle** | **100% (max-performance)** | drop power → less alt gained; <50% = fails 180° |
| **Lazy Eight** | cruise (~60–65%) | off-design = oscillation amplitude drifts |
| **Steep Spiral** | idle (descent maneuver) | excess power = doesn't descend properly |
| **S-Turns** | maneuvering (~55–65%) | high = wider arcs → more bank → G rises; extreme = can't track reference |
| **Turns Around a Point** | maneuvering (~55–65%) | high = wider orbit → more drift correction; extreme = drifts off |
| **Rectangular Course** | maneuvering (~55–65%) | high = drift on each leg magnified |
| **Eights on Pylons** | cruise (~60–65%) | power shifts pivotal altitude (PA = V²/g·tan(φ); power → V) |

**Output presentation when off-design:**
- Result chip: "Design power: 65% · Yours: 90% · Effect: +0.4 G in turn"
- Verdict label: "Maneuver failed — chandelle could not reach 180° at this power"
- Rendered path changes shape — the whole point is the pilot
  sees what their power choice did to the ground track / altitude
  profile.

**CG slider:** keep wired in all maneuvers. Current ~2%
stall-factor effect is realistic and shouldn't grow. The slider
remains visible and is a small-effect realism feature.

---

## Per-Maneuver Approved Items (2026-05-18 walkthrough)

Cross-cutting items from Themes B and C are auto-applied to every
maneuver and not relisted here. Below is only the maneuver-specific
work approved during the walkthrough.

> **Pruned 2026-05-18 after ACS-compliance code verification.**
> Items that turned out to be already in the code are crossed out
> with the file where they live. See
> `docs/plans/2026-05-18-acs-compliance-audit.md` for the
> full corrected inventory.

### Route Planner (`route`)
- Variable climb rate (density alt + weight aware)
- Climb/cruise/descent fuel burn split (×1.5 / ×1.0 / ×0.6)
- Alternate-airport suggestions for destination
- Fuel-on-arrival + FAR 91.151 reserve check
- Score banner visual distinctness pass
- DEFERRED: NOTAM/airspace warnings, PDF export

### Impossible Turn (`impossible_turn`)
- Terrain conflict along return path (reuse `classify_route_statuses`)
- Crosswind runway recommendation (max headwind component)
- Reaction-time slider tooltip with altitude-loss math
- Outcome marker: replace emoji with SVG check ✓ / cross ×
- DEFERRED: Flap-retraction timing during climb
- ~~Multi-engine asymmetric thrust disclaimer chip~~ — N/A,
  impossible turn is single-engine emergency drill, not for ME

### Power-Off 180 (`poweroff180`)
- **Phase markers on map at abeam / 90° / 45° / final**
  (ACS audit Gap 5; from hover `segment` field transitions)
- Go-around verdict when below min-glide-back altitude
- Power slider relabel as "Residual power (partial failure)"
- DEFERRED: Glide-ratio bleed in turn (pair w/ later physics pass)
- ~~Energy-altitude buffer per phase~~ — buffer math implicit in
  phase markers + already-shown altitude profile
- ~~Headwind/tailwind callout~~ — already shown in info panel
  (`poweroff180.py:Headwind/Tailwind ___ kt | Crosswind ___ kt`)

### Engine-Out Glide (`engineout`)
- Terrain conflict along glide path (`classify_route_statuses`)
- TD Elev auto-fill from DEM at clicked touchdown point
- "Fail — divert needed" verdict when touchdown below field elev
- Envelope ring re-styled to canonical lime-500 dashed
- DEFERRED: Fuel-burn-during-glide weight effect

### Steep Turns (`steep_turn`)
- Turn rate (°/s) in result chip alongside G-load
  (genuinely missing — info panel shows AOB/Load/Radius/Vs/Margin
  but not ω)
- Exit heading marker on map (should = entry +360°)
- Roll rate visible in bank-control tooltip from C.4 dynamics
- ~~Load factor + stall margin display~~ — already in info accordion
  (`steep_turn.py:213` shows `AOB | Load G | Radius` and
  `GS | Vs turn | Margin`). ACS pass/fail styling falls under
  Gap 6 cross-cutting.

### Chandelle (`chandelle`)
- Roll-out heading marker on map (entry +180°)
- Off-design power "failed — could not reach 180°" verdict
  (per Design Directive)
- Contextual maneuver-info entry (what is a Chandelle, when to use)
- ~~Max altitude gained annotation~~ — already shown as
  `Alt: entry→exit (+gain)` in info panel
- ~~Stall margin at roll-out~~ — already shown as `Vs turn | Margin`
- ~~Completion time~~ — already shown as `Time: ___s`

### Lazy Eight (`lazy8`)
- Max-bank-at-each-90°-point callout vs user-set target (per-90°
  breakdown; current panel shows overall AOB range only)
- Heading-reversal markers on map
  (45° / 90° / 135° / 180° / 225° / 270° / 315°)
- Roll-out heading marker at exit
- ~~Altitude oscillation range~~ — already shown as
  `Alt: min-max (±range)` in info panel
- ~~Completion time~~ — already shown
- ACS pass/fail styling covered by Gap 6 cross-cutting

### Steep Spiral (`steep_spiral`)  ← Commercial ACS Task IX.C
Sim model: **constant best-glide IAS** (from aircraft JSON, user-override
optional) · **idle power** (slider relabeled "Residual power") · **bank
modulates around the orbit** to maintain constant ground-track radius
under the current wind (peak bank typically downwind).
- Peak-bank > 60° tier-3 ACS limit verdict
- Terrain conflict check on descent (DEM at ref + per-turn alt)
- Exit heading + altitude marker on map (ACS ±10° heading check)
- ~~Per-turn altitude loss display~~ — already shown as
  `Loss: ___ ft (___/turn)` in info panel
- Load-factor variation chart — comes free with the
  bank-modulation sim model rework

### S-Turns (`s_turn`)
- **Wind-perpendicularity warning** when ref line not within ±15°
  of perpendicular to wind (ACS audit Gap 3 — the maneuver's
  pedagogical purpose)
- Crossing-angle readout at each reference-line crossing
  (ACS target: 90°; not in current hover data, needs computation
  from ground track at crossing indices)
- Per-half bank delta breakdown (info panel shows overall AOB
  range; per-half upwind vs downwind missing)
- DEFERRED: Altitude-loss accumulation model
- ACS pass/fail styling covered by Gap 6 cross-cutting

### Turns Around a Point (`turns_point`)
- **Pivotal-altitude chip** ("PA for this config: ___ AGL")
  (ACS audit Gap 1 — port computation from
  `simulation/eights_on_pylons.py`)
- Min turn radius chip from `V²/g·tan(60°)`
- Drift correction angle visualization around the orbit
  (data is in hover as `wind_correction`; not surfaced)
- Auto-entry-heading verify + tooltip (ACS prefers downwind entry)

### Rectangular Course (`rect_course`)
- Rename "Width" → "Leg spacing (NM)" + tooltip
- Turn radius at each of the 4 corners
- **Per-leg WCA breakdown** as a 4-row mini-table in info panel
  (ACS audit Gap 4 — info panel shows overall `Max crab` only)
- Entry heading guidance (downwind entry default)
- ACS pass/fail styling covered by Gap 6 cross-cutting

### Eights on Pylons (`pylons`)  ← Commercial ACS Task V.B
Sim model: **PA varies with ground speed** around the figure-8 —
`PA = GS² / g·tan(φ)`. Downwind PA > upwind PA. **Bank modulates
with position** so pivotal altitude stays at aircraft's current
altitude.
- **True-heading vs ground-track arrow markers** (the key
  pedagogical visualization — nose appears to point at pylon
  throughout; NOT currently rendered)
- Pylon-separation chip in info panel (data is in hover as
  `pylon_distance_ft`/`pylon_distance_nm`; not displayed)
- Min/max safe altitude warning (typically 600-1000 ft AGL)
- ~~PA range display~~ — already shown as
  `PA: min-max ft (avg, range)` in info panel
- ~~Path coloring by pivotal altitude~~ — already rendered
  (red low → blue high)
- Per-segment load factor visualization (data in hover, not
  surfaced — comes free with per-position PA chart if built)

---

## Deferred Follow-up Phases

**Full ACS-vs-maneuver compliance audit.** After this production-
ready sweep ships, do a comprehensive cross-reference of every
maneuver's implementation against the current FAA ACS standard
(Private + Commercial as relevant): tolerances, completion
criteria, judgment criteria, common errors flagged. Steep Spiral
(D.8) and Eights on Pylons (D.12) revisions in this audit are
preview examples of what that pass should look like for every
maneuver.

**Multi-engine asymmetric thrust / Vmc handling.** Required per-
aircraft Vmc, dead-engine torque, control authority data. Affects
impossible_turn / engineout / poweroff180.

**Mobile-first responsive overhaul.** Below 768px untested.
Touch-friendly map interactions.

**NOTAM / airspace warnings on Route.** API ingestion +
shapefile overlay.

**Nav log PDF export.** Beyond browser print.

**Glide-ratio bleed in turns** (Power-Off 180 + similar).
Refined physics pass; pair with broader simulation tuning.

**Flap-retraction timing during climb** (Impossible Turn).
Steady-state today; phase-aware later.

**Mobile-fuel-burn weight effect** during glide
(Engine-Out Glide). Marginal but realistic.

---

## Executive Summary

12 distinct maneuvers, all functional. Route Planner is production-
grade; training maneuvers are working but uneven in feedback depth.
Sidebar carries ~13 controls but only ~6 are consumed by any given
maneuver — significant per-maneuver clutter. Physics is reasonable
but uses simplified models (constant climb rate, no load-factor
display, hardcoded roll-rate, etc.). Live winds work for route only.

---

## Maneuver-by-Maneuver

### 1. Route Planner — `"route"`
- **Layout:** `layouts/maneuvers/route.py`
- **Callback:** `callbacks/route.py`
- **Shelf controls:** Route dropdown · Click-to-add pill · Cruise Alt
  (+ terrain conflict chip) · Cruise TAS · Cruise IAS · Glide Ratio
  · Glide IAS · Climb IAS (+ Vy hint + rate chip) · Engine-out
  segmented (SE/Glide/Both, ME only) · Corridor / Live winds /
  Landable / Max slope° pills · Compute · Clear
- **Math used:** `compute_route_segment`, `compute_route_corridor`,
  `compute_route_se_corridor`, `compute_flight_profile`,
  `build_landable_mask_overlay`, `fetch_landing_options`,
  `fetch_winds_aloft`, `score_route`, `magvar_west_positive`,
  `classify_route_statuses`, terrain DEM via Mapzen tiles
- **Rendering:** Status-segmented polyline, glide corridor polygon,
  optional landable mask, water polygons, divert airport markers,
  wind barbs, pending-route preview line, score banner, FAA nav
  log modal with airport ATIS + frequencies (NASR)
- **Issues:** Climb rate constant (no weight/density-altitude
  variation). Fuel burn = constant gph (no climb/cruise/descent
  split). Slope filter is per-pixel (no contour smoothing).
- **Missing:** Alternate-airport suggestions, fuel-on-arrival,
  NOTAM/airspace warnings, PDF export of nav log.
- **Status:** WORKING — production-grade.

### 2. Impossible Turn — `"impossible_turn"`
- **Shelf:** Direction L/R · Runway dropdown · Heading override ·
  Failure Alt AGL · Vy · Reaction time · Flap · Prop · Set Takeoff
  · Draw
- **Math:** `simulate_impossible_turn` (multi-phase: takeoff →
  climb → reaction → banked turn back → final descent), bank
  optimization for minimum altitude
- **Rendering:** Color-coded path (green takeoff / blue climb / red
  glide), runway polygon with piano keys + captain's bars,
  start/failure/touchdown markers, time scrubber, info accordion
- **Issues:** Takeoff acceleration constant (no density-alt). Glide
  ratio held during turn (real ratio bleeds with bank). No
  multi-engine asymmetric thrust / Vmc.
- **Missing:** Terrain conflict along return path, flap-retraction
  timing, crosswind runway recommendation, multi-engine handling
- **Status:** WORKING — well-modeled for SE; ME asymmetric missing.

### 3. Power-Off 180 — `"poweroff180"`
- **Shelf:** Runway · Heading · Pattern L/R · Flap · Prop ·
  Abeam (0.3-1.5 NM slider) · Pattern Alt AGL · Set Touchdown · Draw
- **Math:** `simulate_power_off_180` (energy-based descent from
  abeam to touchdown), turn radius from IAS + bank
- **Rendering:** Red flight path, entry + touchdown markers, time
  scrubber, info panel
- **Issues:** Glide ratio likely constant through turn. Bank
  transients not modeled. No "altitude buffer at each waypoint"
  feedback the maneuver actually trains.
- **Missing:** Energy-altitude display, go-around threshold,
  headwind/tailwind effect callout, altitude target at abeam
- **Status:** WORKING — basic; needs richer feedback for the
  decision-making this maneuver tests.

### 4. Engine-Out Glide — `"engineout"`
- **Shelf:** Runway · TD heading · Flap · Prop · TD Elev · Start
  heading · Start Alt · Reaction · Max Bank · Envelope checkbox ·
  Set Touchdown · Set Start · Draw
- **Math:** `simulate_engineout_glide` with exponential bank/speed
  bleed, `find_minimum_altitude`, optional `compute_glide_envelope`
- **Rendering:** Red glide path, blue start / red touchdown markers,
  optional dashed envelope ring, time scrubber, info panel
- **Issues:** Bank-tau and speed-tau hardcoded (5s / 1.5s) — should
  be per aircraft. Fuel-burn-during-glide ignored. Multi-engine
  asymmetric path same as SE.
- **Missing:** Terrain conflict along path, ME asymmetric, bailout
  altitude threshold, flap timing
- **Status:** WORKING — best of the energy-management maneuvers.

### 5. Steep Turns — `"steep_turn"`
- **Shelf:** Bank (30°-60° dropdown) · Sequence (L→R / R→L / L /
  R) · Entry Hdg · Alt · IAS (defaults Va) · Set Entry · Draw
- **Math:** `simulate_steep_turn` with wind-corrected ground track,
  ω = g·tan(φ)/V, R = V²/(g·tan(φ))
- **Rendering:** Red spiral, entry/exit markers, time scrubber
- **Issues:** Roll rate hardcoded 5 dps. No load-factor / stall-
  margin display. Altitude held constant (no pitch-for-bank).
- **Missing:** Load-factor n = 1/cos(φ) callout, stall-margin
  indicator, turn-rate display, altitude-loss callout, configurable
  roll rate
- **Status:** WORKING — path correct; missing the safety feedback
  that's the whole point of this maneuver.

### 6. Chandelle — `"chandelle"`
- **Shelf:** Entry Hdg · Bank (15-45) · Direction L/R · Alt · IAS
  (Va default) · Set Entry · Draw
- **Math:** `simulate_chandelle` (180° max-bank with climb)
- **Rendering:** Red spiral path, markers, time scrubber
- **Issues:** Climb rate during turn likely doesn't bleed for
  load factor. Roll-out logic unclear without deep dive into
  the sim module.
- **Missing:** Max altitude gained annotation, load-factor display,
  stall-margin check, completion-time, roll-out heading marker
- **Status:** WORKING — minimal feedback; maneuver-purpose unclear
  in UI (no description of what a chandelle even is).

### 7. Lazy Eight — `"lazy8"`
- **Shelf:** Entry Hdg · Alt · IAS · Max Bank (20-40) · First Turn
  L/R · Set Entry · Draw
- **Math:** `simulate_lazy_eight` (figure-8 with varying bank +
  altitude oscillation)
- **Rendering:** Red figure-8 path, markers, time scrubber
- **Issues:** Bank-transition logic and altitude oscillation
  profile unverified.
- **Missing:** Altitude profile (this is the maneuver's defining
  feature!), max-bank-at-each-turn callout, completion time,
  heading-reversal point markers
- **Status:** WORKING — but a lazy 8 *is* the altitude+heading
  profile; not showing that = not really teaching the maneuver.

### 8. Steep Spiral — `"steep_spiral"`
- **Shelf:** Turns (3-10) · Alt · Bank (20-60) · Entry direction
  (12/3/6/9 o'clock) · Direction L/R · Set Ref · Draw
- **Math:** `simulate_steep_spiral` (descending circles around
  reference, wind-corrected)
- **Rendering:** Red spiral, blue reference / green entry / red
  exit markers, warnings panel
- **Issues:** Altitude loss per turn likely constant (real IAS
  bleeds during turn). Bank held constant (real bank steepens
  as airspeed bleeds).
- **Missing:** Per-turn breakdown of altitude loss, load factor,
  exit heading + altitude, terrain conflict if spiraling toward
  rising terrain
- **Status:** WORKING — adequate.

### 9. S-Turns — `"s_turn"` (NOTE: dropdown value may be `"sturns"`
   per `layouts/desktop.py:88`; agent claim needs verification)
- **Shelf:** Alt · IAS · Bank · Turns (S-pairs 1-5) · Entry Side
  L/R · First Turn L/R · 1. Start · 2. Ref Pt · Draw
- **Math:** `simulate_s_turn` with reference-line bearing from two
  clicks, alternating left/right turns
- **Rendering:** Orange dashed reference line preview, red S-turn
  path, markers, time scrubber
- **Issues:** Reference line not enforced perpendicular to wind
  (the whole point of S-turns). No crossing-angle indicator.
- **Missing:** Wind-perpendicularity warning, crossing-angle
  readout, headwind/tailwind callout at each crossing, altitude
  loss accumulation
- **Status:** WORKING — two-click workflow is good; missing the
  wind-correction training signal.

### 10. Turns Around a Point — `"turns_point"` (value needs check)
- **Shelf:** Alt · IAS · Radius NM (0.1-1.0) · Turns (1-5) ·
  Direction L/R · Entry Hdg (auto) · Set Center · Draw
- **Math:** `simulate_turns_around_point` — wind-corrected orbit,
  GS varies around the circle
- **Rendering:** Red orbit path colored by GS (red slow / blue
  fast), center marker, ideal-orbit dashed circle, time scrubber
- **Issues:** Radius is user-set rather than derived from bank +
  IAS (so doesn't validate "can this aircraft fly this orbit?").
  Power + CG inputs *claimed* used but probably dead.
- **Missing:** Pivotal altitude (key concept!), drift-correction
  angle readout, max-bank limit check, time per orbit
- **Status:** WORKING — GS coloring is excellent; missing pivotal-
  altitude tie-in.

### 11. Rectangular Course — `"rect_course"` (value needs check)
- **Shelf:** Alt · IAS · Width NM · Direction L/R · Circuits (1-3)
  · 1. DW Start · 2. DW End · Draw
- **Math:** `simulate_rectangular_course` — wind-corrected
  rectangle, GS varies on each leg
- **Rendering:** Red dashed downwind preview, red full rectangle
  with GS coloring, markers, time scrubber
- **Issues:** "Width" is leg spacing (could read as turn radius).
  Bank fixed. Same power+CG-may-be-dead concern.
- **Missing:** Turn radius at each corner, min-altitude-to-
  complete check, entry heading for joining downwind
- **Status:** WORKING — two-click pattern setup is elegant.

### 12. Eights on Pylons — `"pylons"` (value needs check)
- **Shelf:** IAS · Bank dropdown (20-40) · Eights (1-3) · Entry
  Downwind/Upwind · Set Pylon 1 · Set Pylon 2 · Draw
- **Math:** `compute_pivotal_altitude` (V²/g·tan(φ) in ft),
  `simulate_eights_on_pylons` with wind-corrected figure-8
- **Rendering:** Red + orange pylon markers, figure-8 path colored
  by pivotal altitude (red low / blue high), time scrubber,
  info panel with min/max PA + load factor
- **Issues:** PA formula assumes zero wind (real PA varies with
  wind). Bank held constant (real maneuver adjusts bank to hold
  PA). PA-coloring approximate.
- **Missing:** True heading vs ground track arrow display,
  pylon-separation measurement, min-safe-altitude check
- **Status:** WORKING — easily the most polished training
  maneuver; the PA-coloring is the right idea.

---

## Sidebar Audit

Sidebar carries ~13 controls; usage per maneuver below. ★ = primary
input, · = used, blank = unused/dead.

| Control | Route | ImpT | PO180 | EO | StpT | Chan | Lzy8 | StpS | S-T | TAP | Rect | Pyl |
|---------|-------|------|-------|----|------|------|------|------|-----|-----|------|-----|
| Aircraft picker | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ |
| Engine select | | ★ | ★ | ★ | | | | | | | | |
| Wind dir | (live) | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ |
| Wind speed | (live) | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ |
| OAT | · | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ |
| Altimeter | · | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ |
| Occupants | | ★ | | ★ | | | | | | | | |
| Occ Weight | | ★ | | ★ | | | | | | | | |
| Fuel Load | ★ | ★ | | ★ | | | | | | | | |
| CG slider | | (?) | | (?) | | | | | | (?) | (?) | (?) |
| Total Weight | ★ | ★ | ★ | ★ | ★ | ★ | ★ | ★ | | ★ | ★ | ★ |
| Power slider | | | | | | | | | | (?) | (?) | (?) |
| AGL display | ★ | | | | | | | | | | | |

**(?)** = claimed used by agent but not verified — could be dead inputs.

**Current hide-by-maneuver** (`callbacks/sidebar.py:21`): only the
route maneuver hides anything (OAT/Altim, AGL, CG, Power, map
controls). Every other maneuver shows everything regardless of
whether the input is consumed.

**Recommendations:**
- Engine select: only show for impossible_turn, poweroff180,
  engineout (the three that use prop/engine config).
- Occupants / Occ Wt / Fuel Load: only show for maneuvers that
  drive a total-weight computation actually used in physics.
- CG slider + Power slider: **verify these are wired to anything
  real** in turns_point / rect_course / pylons before keeping. If
  dead, remove from layout entirely.
- AGL display: already hidden for non-route; correct.

---

## Cross-Cutting Quality Notes

**Wind integration**: all maneuvers integrate wind into ground
track — good. But S-turns + rect course don't *check* wind
alignment (the maneuver's training purpose); pylons PA formula
ignores wind (simplification).

**Aircraft adaptation**: every maneuver pulls aircraft data
(Va, Vy, best-glide, glide ratio). But the multi-engine
maneuvers (impossible_turn, engineout, poweroff180) accept the
engine dropdown without modeling asymmetric thrust — selecting
ME mode in the prop dropdown only affects glide ratio, not Vmc.

**Plotting**: every maneuver gets a red path + green/red endpoint
markers + time scrubber. Only route shows an altitude profile.
None show load factor, stall margin, or g-loading — which is the
*safety* feedback most of these maneuvers exist to teach.

**Unit labels on map**: none. NM/ft are implicit.

**Hardcoded constants** scattered across sim modules:
- Roll rate (5 dps) — steep_turn
- Bank tau (5 s), speed tau (1.5 s) — engineout glide
- Inter-turn pause (1 s) — steep_turn
- Takeoff acceleration constant — impossible_turn

These should be per-aircraft from the aircraft JSON, or
configurable in the shelf.

---

## Prioritized Improvement List

**High value, low effort:**
1. Hide sidebar controls per-maneuver (extend `HIDE_BY_MANEUVER`
   in `callbacks/sidebar.py`). Already established pattern.
2. Verify + remove dead Power + CG inputs from
   turns_point / rect_course / pylons (if confirmed unused).
3. Add load-factor + stall-margin badge to Steep Turns
   (it's literally what the maneuver tests).
4. Add altitude profile chart to Chandelle + Lazy 8 + Steep Spiral
   (currently only Route has this, but these maneuvers are
   altitude-defined).
5. Add wind-perpendicular warning to S-Turns.
6. Add pivotal-altitude tie-in to Turns Around a Point.

**Medium value, medium effort:**
7. Multi-engine asymmetric thrust + Vmc handling for
   impossible_turn / engineout / poweroff180.
8. Terrain conflict detection along all glide paths.
9. Configurable roll rate (per-aircraft in JSON, or shelf input).
10. Bailout/go-around altitude thresholds with visual warning.

**Lower priority:**
11. Real engine performance (MAP/rpm/CHT) — significant scope.
12. Trim + pitch-hold integration.
13. Ground effect during landing.
14. GPX / FF profile export.

---

**No action will be taken on this audit until you've reviewed and
approved a specific subset of items.**
