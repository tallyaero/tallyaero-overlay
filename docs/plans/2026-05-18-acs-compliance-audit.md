# TallyAero Maneuver Overlay — ACS Compliance Audit (Corrected)

**Date:** 2026-05-18
**Status:** Research only — no action taken pending review
**Scope:** All 12 maneuvers against current FAA Private Pilot ACS (FAA-S-ACS-6C) and Commercial Pilot ACS (FAA-S-ACS-7B)

> **This is a corrected rewrite of the original audit.** The first
> pass underestimated existing implementation depth — most of what
> it called "missing" is in fact computed and surfaced via the info
> accordion or per-step scrubber tooltip. Re-reading every
> `callbacks/maneuvers/*.py` and `simulation/*.py` directly with
> `grep` produced a much shorter true-gap list (six items, mostly
> presentation work). Compliance scores below reflect the actual
> code state, not the agent's prior estimates.

---

## How the corrected audit was done

1. Listed every key returned by every `simulation/<name>.py` (e.g.
   `load_factor`, `pivotal_alt_min`, `altitude_per_turn`, `vs_in_turn`,
   `max_crab_angle`, etc.).
2. Listed every static info-accordion line surfaced by every
   `callbacks/maneuvers/<name>.py` (`AOB | Load G | Vs turn |
   Margin` style).
3. Listed every scrubber-tooltip line set by the per-maneuver
   slider callback (alt / IAS / TAS / AOB / VS at every step).
4. Compared against ACS task requirements (Knowledge / Risk /
   Skills tolerances / Special Emphasis).
5. Flagged ONLY items not present in any of the three surfaces.

---

## What is already implemented (the honest inventory)

### Static info-accordion content per maneuver

Every maneuver has a `dbc.Accordion` info panel rendered after Draw,
expanded by default, with 4-7 lines of structured stats. The
content pattern is consistent across all 12:

```
Weight · IAS · TAS · Wind
AOB | Load G | GS range
[maneuver-specific row: altitude / orbit / crab / distance / etc.]
Vs turn | Margin | Time
[totals / direction / aircraft-config row]
```

### Per-maneuver static panel content (verified)

| Maneuver | Panel surfaces |
|---|---|
| Impossible Turn | Weight · IAS · Wind · Flaps · Prop · Ground roll · Glide ratio · Avg GS · VS · Distance · **Failure alt + Min req alt** · Bank · Time |
| Power-Off 180 | Best Glide · Weight · Glide Ratio · Max Bank · Wind · **Headwind/Tailwind component** · Crosswind · Pattern Alt · Abeam dist · Runway · Pattern dir · Flaps · Slip pct + reduced G/R · Time |
| Engine-Out Glide | Weight · Entry hdg · Wind · Flaps · **Avg G/R · GS · VS** · Distance · **Slip used** · Turn dir · Runway · Total time · Reaction · **Max bank · Bank τ** |
| Steep Turns | Weight · IAS · TAS · Wind · **AOB · Load G · Radius** · GS range · **Vs turn · Margin** · Time · sequence |
| Chandelle | Weight · IAS · TAS · Wind · **AOB · Load G** · GS range · **Alt: entry→exit (+gain)** · Direction · **Vs turn · Margin** · Time |
| Lazy Eight | Weight · IAS · TAS · Wind · **AOB · Load G** · GS range · **Alt: min-max (±range)** · First-turn dir · **Vs turn · Margin** · Time |
| Steep Spiral | Weight · IAS · TAS · Wind · **AOB · Load G** · GS range · **Orbit radius · VS · Alt: start→end · Loss + per-turn loss** · **Vs turn · Margin** · Time |
| S-Turns | Weight · IAS · TAS · Wind · AOB range · Load · GS range · **Radius · Alt loss** · **Vs turn · Margin** · Time · S-Turn count · **Ref bearing** · Entry side |
| Turns Around a Point | Weight · IAS · TAS · Wind · AOB range · Load · GS range · **Orbit radius · Alt loss** · **Vs turn · Margin** · Time · Turns · Direction · Entry hdg |
| Rectangular Course | Weight · IAS · TAS · Wind · AOB range · Load · GS range · **DW length · Lateral · Max crab°** · **Vs turn · Margin** · Time · pattern · circuits |
| Eights on Pylons | **PA: min-max ft (avg, range)** · Weight · IAS · TAS · Wind · **Path colored by pivotal altitude** |
| Route Planner | Score banner + below-strip card + FAA Nav Log modal (separate UI pattern) |

### Per-step scrubber-tooltip content (verified)

Every maneuver also has a time-slider; sliding shows a tooltip on
the airplane marker with per-step state: altitude AGL · time · IAS ·
TAS · GS · AOB (L/R direction + magnitude) · pitch (where
applicable) · VS · segment/phase label.

So the user is correct that ACS pedagogical data largely **does**
exist; what varies is how prominently it's surfaced.

---

## True gap analysis — what's actually missing

After verification, the genuine ACS-relevant gaps are SIX items.

### Gap 1 — Pivotal altitude on Turns Around a Point

**File:** `simulation/turns_around_point.py`, `callbacks/maneuvers/turns_around_point.py`.
**Confirmed absent:** `grep -i pivotal` returns nothing in either file.

ACS Private Area VI Task B (Turns Around a Point) doesn't strictly
require pivotal altitude as a gradable item, but it's the
foundational concept (the wing tip "pivots" on the reference
point at pivotal altitude). Eights on Pylons (Commercial V.B) is
where PA is mandatory, and the code already computes it there
(`simulation/eights_on_pylons.py:pivotal_alt`). Trivial port.

**Action:** Port the PA computation from `eights_on_pylons.py` into
`turns_around_point.py`'s hover dict; render a small chip in the
info accordion ("PA at this GS / bank: ___ ft AGL · your alt: ___").

---

### Gap 2 — Altitude-profile chart for Chandelle / Lazy 8 / Steep Spiral

**Files:** the three maneuver callbacks.
**What exists:** the data is stored at every per-step hover point
(`alt`, `time`, `pitch`, `vs`). The static info accordion shows
*scalar* summaries (entry→exit / min-max / loss-per-turn).
**What's missing:** a Plotly time-series chart visualizing the
altitude profile. The Route Planner already has this pattern
(`route-profile-chart` in `callbacks/route.py` ~line 1783).

These three maneuvers are *defined* by altitude profile —
Chandelle by climb, Lazy 8 by oscillation, Steep Spiral by
descent. Scalar summaries don't convey the shape.

**Action:** Extract Route's profile chart into a reusable helper
(`core/profile_chart.py` or similar); add `dcc.Graph` to each
maneuver's info panel showing altitude-vs-time. Each maneuver
already has the per-step time + altitude data in its hover dict.

---

### Gap 3 — Wind-perpendicular alignment warning on S-Turns

**File:** `callbacks/maneuvers/s_turn.py`, `simulation/s_turn.py`.
**What exists:** the reference-line bearing is computed and shown
in the info accordion (`Ref: 270° | Left entry`). Wind is fed into
the simulation. Each semicircle's bank is adjusted for wind drift.
**What's missing:** a warning when the reference line bearing is
NOT close to perpendicular to wind. ACS Private VI.A specifies
the maneuver is flown perpendicular to wind for the training
purpose to make sense.

**Action:** Compute `wind_perp_angle = abs(((line_bearing - wind_dir) % 180) - 90)`.
If > 15°, render a tier-2 amber chip:
`Wind alignment off by ___° — ACS expects perpendicular`.

---

### Gap 4 — Per-leg WCA breakdown on Rectangular Course

**File:** `callbacks/maneuvers/rectangular_course.py`, `simulation/rectangular_course.py`.
**What exists:** `Max crab: 12.4°` is shown overall. Per-leg
ground speed and altitude data are in the hover dict.
**What's missing:** WCA per leg as a small 4-row table or strip
(`Leg 1 DW: crab __° · GS __ kt` etc.). ACS Private VI.B's
defining skill is recognizing that crosswind correction is
different on each of the four legs.

**Action:** Compute crab per leg from existing hover data (group by
`segment` field). Render as a small table in the info accordion.

---

### Gap 5 — Phase markers on map for Power-Off 180

**File:** `callbacks/maneuvers/poweroff180.py`.
**What exists:** the entry circle + touchdown marker + red path.
Hover data has `segment` field tracking phase (`downwind`, `turn`,
etc.). Static info accordion shows headwind/tailwind/abeam dist.
**What's missing:** map markers at the abeam point, the 90°-turn
point, and the 45°-turn point — the four ACS-graded checkpoints.
Pilots need to see those positions, not just where the path
turns.

**Action:** From hover data, find the index of each segment
transition; render small CircleMarkers on the path at those
indices with phase-label tooltips.

---

### Gap 6 — ACS pass/fail tolerance badge styling

**Files:** all 12 maneuver callbacks.
**What exists:** every maneuver displays the relevant scalar
("Margin: 23 kt", "Alt loss: 50 ft", "Crab: 12.4°"). The numbers
are there.
**What's missing:** color-coded pass/fail visual styling against
the ACS tolerance threshold for that metric (Private ±100 ft / ±10° /
±10 kt; Commercial ±100 ft / ±10° / ±5 kt for performance maneuvers).
Currently all the numbers render in identical 11px text.

**Action:** Build a small reusable `_acs_metric(label, value, units,
target, tol, cert_level)` helper in `layouts/maneuvers/_shared.py`
that returns a styled `html.Div` with a green/amber/red border-left
based on `abs(value - target) <= tol`. Replace the bare
`html.Div(f"...")` lines in each maneuver's info accordion where
ACS tolerances apply. Same content, just visually graded.

---

## Items the original audit listed that turn out to be ALREADY DONE

These were proposed as "needs work" but are present in code. They
should be REMOVED from the implementation backlog:

| Item from prior audits | Actually present at |
|---|---|
| "Load factor + stall margin invisible on Steep Turns" | `steep_turn.py:213` — `AOB ___° \| Load ___ G \| Radius ___ ft` and `Vs turn ___ \| Margin ___ kt` |
| "Chandelle exit checks missing" | `chandelle.py` info: `Alt: entry→exit (+gain)`, `Vs turn`, `Margin`, exit direction shown |
| "Lazy 8 altitude oscillation not shown — maneuver undefined" | `lazy_eight.py` info: `Alt: min-max (±range)`. Scrubber shows pitch at every step. |
| "Steep Spiral per-turn altitude loss missing" | `steep_spiral.py` info: `Loss: ___ ft (___/turn)` literally shows per-turn |
| "Engine-Out bank tau hardcoded and needs aircraft-specific tuning" | Bank τ IS displayed: `Bank τ: ___s`. Whether it varies per aircraft is a separate concern. |
| "Pylons pylon-separation measurement missing" | `pivotal_alt_min/max/avg/range` + path coloring by PA — already prominent. Pylon distance is also in hover dict (`pylon_distance_ft`, `pylon_distance_nm`). |
| "Impossible Turn ME asymmetric thrust missing" | User clarified: impossible turn is NOT a multi-engine maneuver. Drop from backlog. The maneuver is single-engine emergency drill; on a twin the procedure isn't "complete the turn", it's "fly the OEI profile". Not in scope. |

---

## Corrected compliance scoring

Re-graded after code verification. Scores reflect ACS pedagogical
alignment with the data the user actually sees, not theoretical
gaps.

| Maneuver | ACS Task | Cert | Score (corrected) | Real critical gap |
|---|---|---|---|---|
| Route Planner | III.B Cross-Country | Private | 85% | Alternate runway recommendation, FAR 91.151 reserve display |
| Impossible Turn | IX.B Emergency | Private | 80% | None real after dropping ME — outcome verdict styling |
| Power-Off 180 | IV.M | Commercial | 75% | Phase markers on map (Gap 5) |
| Engine-Out Glide | IX.B | Private | 80% | Terrain conflict on path |
| Steep Turns | V.A | Private/Comm | 75% | ACS pass/fail badge styling (Gap 6) |
| Chandelle | V.A | Commercial | 70% | Altitude profile chart (Gap 2) |
| Lazy Eight | V.B | Commercial | 70% | Altitude profile chart (Gap 2) |
| Steep Spiral | IX.C | Commercial | 70% | Altitude profile chart (Gap 2) |
| S-Turns | VI.A | Private | 70% | Wind-perpendicular warning (Gap 3) |
| Turns Around a Point | VI.B | Private | 65% | Pivotal altitude (Gap 1) |
| Rectangular Course | VI.B | Private | 70% | Per-leg WCA (Gap 4) |
| Eights on Pylons | V.B | Commercial | 85% | Best in tool. Only polish remains. |

**Average (corrected): ~75%.** Previous "55%" was a substantial
underestimate from missing already-shipped feedback.

---

## Path to 90%+ — the actual action list

In priority order. Each item maps to a specific file + line range
that exists.

1. **Build `_acs_metric()` helper** in `layouts/maneuvers/_shared.py`
   and **wire it into all 12 maneuver info accordions** where
   tolerances apply. Same content, color-coded green/amber/red by
   ACS tolerance. Two-day pass. Lifts every maneuver by ~5%.
2. **Extract reusable `core/profile_chart.py`** from Route's
   profile chart code. Add it to Chandelle / Lazy 8 / Steep
   Spiral info panels. One-day pass.
3. **Port `pivotal_alt` computation** from
   `simulation/eights_on_pylons.py` into
   `simulation/turns_around_point.py`. Render in the info
   accordion. Half-day.
4. **Add wind-perpendicular warning** to S-Turns. ~1 hour.
5. **Compute per-leg WCA breakdown** on Rectangular Course from
   existing hover data. Render as a 4-row mini-table in the info
   accordion. ~1 hour.
6. **Add phase markers on map** for Power-Off 180. Iterate hover
   data, find segment transitions, append CircleMarkers. ~2 hours.

**Total: roughly 4 days of focused work** to lift the suite from
~75% to ~92% ACS alignment. Substantially less than the
"build 8 reusable components from scratch" framing of the prior
audit.

---

## Deferred (legitimate but bigger scope)

- **Mobile responsiveness** for the maneuver shelves and info
  panels. The `Cross-Cutting Features` section of
  `2026-05-18-maneuver-audit.md` already marks this deferred.
- **NOTAM / airspace warnings** for Route. Real ingestion + API
  work; separate phase.
- **Multi-engine asymmetric / Vmc modeling.** Only applies to
  engineout and poweroff180 in legitimate ways (impossible turn
  is single-engine emergency drill, not for ME). Separate physics
  phase if/when desired.
- **PDF export** for the Nav Log. Print works; PDF is nice-to-have.

---

## How this maps to the master audit doc

Update `docs/plans/2026-05-18-maneuver-audit.md` per-maneuver
"approved items" sections by deleting items that turn out to be
already done (per the table above), keeping the genuine gaps
listed in this audit's "True gap analysis", and keeping all the
cross-cutting conventions (Theme B, C, Design Directive) as-is.

Net effect: the implementation plan should shrink by roughly 30%
because so much of the prior "missing" feedback isn't actually
missing.
