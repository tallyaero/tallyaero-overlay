# Future Refinement Options

**Status:** captured ideas, not yet committed phases
**Date:** 2026-05-16
**Purpose:** holding pen for refinement / differentiator features identified
during the route-planner brainstorm. We work through the committed phases
(7k → 7L → 7M → 7N → 8 → 9 → 10) first, then revisit this list to pick
the next round.

Each entry has: what it is, why it matters, rough lift, and dependencies.
**No file paths or sub-phase breakdowns yet** — those come when an item is
promoted to a real phase plan.

---

## Group A — Completes the committed plan

These are small extensions that, in retrospect, probably belong inside the
committed phases. Promote them when those phases land.

### A1. Per-leg time-of-day weather

**What:** Instead of using "current" winds for the whole route, compute when
the aircraft will be at each sample (from the flight profile's time
integration) and use the forecast for that future hour. Crossing a frontal
passage at 14:30Z vs 16:00Z is night-and-day different.

**Lift:** Small — extends Phase 7k by ~50 lines. Open-Meteo's hourly endpoint
already returns multi-hour forecasts; we just need to pick the right hour
per sample.

**Depends on:** 7k

### A2. Density altitude correction

**What:** OAT and altimeter setting (already in the sidebar) compute density
altitude per sample. DA degrades single-engine service ceiling for twins
(a Seneca II's 13,000 ft SE ceiling drops below 10,000 ft on a hot day),
climb rate for all aircraft, and takeoff/landing distance.

**Lift:** Small. Standard-atmosphere math, ~30 lines. Already flagged as
deferred in 7M plan.

**Depends on:** 7M

### A3. TFR / SUA time-aware overlay

**What:** Display MOAs, restricted areas, prohibited areas, and TFRs as
polygons on the map. Critically: schedule-aware. A MOA marked "Mon-Fri
0800-1700" is rendered active or inactive based on the user's planned
crossing time. Route segments crossing active SUA are flagged.

**Lift:** Medium. NASR has the SUA polygons + schedules; FAA AWC has
real-time TFRs as GeoJSON. Need to ingest both and overlay.

**Depends on:** 7N (waypoint types) or independent

### A4. NOTAM filter for your route

**What:** FAA's NOTAM API is firehose-style — pilots get hundreds of
irrelevant entries per briefing. Filter to NOTAMs that affect your
corridor strip, at your altitude, during your time window. Default
hides the 95% noise.

**Lift:** Medium. FAA NOTAM API integration + relevance scoring
(corridor-intersect, altitude-range, time-window).

**Depends on:** corridor strip (have it), winds aloft for ETA (7k)

### A5. Save / share / import routes

**What:** JSON export of a full route (waypoints + aircraft + flight
profile + winds snapshot), GPX import, shareable URL hash. Once 7N
ships, any waypoint type round-trips cleanly.

**Lift:** Small. State serialization + a couple endpoints / URL params.

**Depends on:** 7N

---

## Group B — Differentiators (truly novel)

These would put the planner past every EFB on the market for the specific
feature. Each is a real engineering investment; the payoff is product
differentiation that's hard to copy.

### B1. Probabilistic survivability score

**What:** Monte Carlo simulate engine failures at each route sample. For a
given route, return a single headline number plus per-segment breakdown:
"87% chance of survivable landing site reachable, 9% off-field reasonable,
4% catastrophic". Per-sample contributions show pilots WHERE the risk
concentrates.

**Why differentiator:** No EFB shows this. "Is my route safe?" gets a real
answer in one sentence. The math is the same per-sample reach + divert +
suitability we're already computing — we just iterate stochastic
parameters (failure location uniform along route, wind perturbation,
pilot reaction time).

**Lift:** Medium-large. ~1 week. Reuses everything from 7d/7g/7h/8/9.
Needs a clean N-sample loop on top of existing math.

**Depends on:** 7g (diverts), 7h (terrain), 8 (suitability), 9 (critique)

### B2. AI route critique (LLM-driven)

**What:** Natural-language risk briefing for any computed route. Pulls in
corridor metrics, divert gaps, winds, NOTAMs, SUA, terrain conflict,
flight profile, pilot currency. "Your route between 15:15 and 16:00
crosses MOA-1234A which activates at 16:00 Mon-Fri. You'd be over the
Adirondacks at 5500 ft with no airport in glide for 22 NM and 14
minutes. Suggested: bend the route 12 NM south through KGFL to clear
both."

**Why differentiator:** Pilots talk through routes with CFIs and copilots
in natural language. Encoding that conversation is uniquely modern.

**Lift:** Medium. Anthropic API call + prompt engineering + display
panel. The HARD part is keeping the LLM honest — it must *narrate* the
deterministic critique (Phase 9), not invent risk that isn't in the
underlying math. Strict tool-use pattern.

**Depends on:** 9 (route critique) producing structured risk facts the
LLM can read

### B3. In-flight glide-gun mode

**What:** Live, in-flight, real-time. When flying with an ADS-B receiver
(Stratus, iLevil, Sentry, etc.) connected, the planner shows your
*current* position and the *current* nearest divert within glide. Color
turns yellow if margin drops below 20%, red if below 10%. Updates every
1–2 seconds.

**Why differentiator:** ForeFlight has a static glide ring; ours is
dynamic AND terrain-aware. Garmin G3X has a similar "Glide Range Ring"
but only on Garmin glass.

**Lift:** Large. Requires:
- Real-time GPS/ADS-B input (USB or WiFi from device)
- In-flight UI mode (full-screen map, big touch targets)
- Smooth recompute of corridor + divert at 1 Hz (current cold-cache is 1–3s,
  needs to drop to <500 ms via aggressive cache pre-warming around current
  position)

**Depends on:** Pilot-app integration first; standalone overlay tool isn't
the right surface for this.

### B4. Aircraft performance learning

**What:** Log every flight's actual fuel burn, true airspeed, climb rate,
descent rate. Over time, the tool gradually replaces POH numbers with the
specific airframe's measured numbers. The POH is an average; every
airframe diverges with age, mods, and engine condition.

**Why differentiator:** Flywheel — the tool gets more accurate the more
you fly. Locks pilots in (their personalized performance data is
valuable).

**Lift:** Medium. Logbook integration + flight-replay parser + slow rolling
average. Math is simple; the harder problem is UX for "trust the POH" vs
"trust my data" with safety margins.

**Depends on:** Logbook integration (separate feature) or manual flight
entry initially

### B5. Engine-out trainer mode

**What:** On any computed route, simulate an engine failure at any point.
"Engine quits at sample 27. Best response: pitch for Vy 76 KIAS, turn
left 132° magnetic to KDYB at 4.2 NM, expect 800 fpm descent at calm
wind, anticipated arrival 9300 MSL with 1100 ft AGL." Quiz mode randomly
fires failures along the route; pilot has to identify the correct
divert.

**Why differentiator:** CFIs and currency-focused pilots will love this.
No competitor offers it as part of route planning.

**Lift:** Medium. ~3 days. Reuses corridor + divert + terrain math.
Mostly UX work (failure-anywhere control + quiz mode + answer
verification).

**Depends on:** 7g (diverts), 7M (multi-engine variants)

### B6. Crash-survivability scoring for off-field LZs

**What:** Phase 8 scores slope and land cover. This extends to include:
- Distance to nearest highway / paved road (rescue access)
- Cell coverage at that lat/lon (US carrier coverage maps)
- Helicopter EMS service area (response time)
- Forest canopy type (deciduous attenuates better than dense pine)
- Distance to nearest water (drowning risk)

Combined into a "survivability score" alongside the geometric "landable
score".

**Why differentiator:** This is the morbid-but-real layer. Pilots who plan
with this stuff land alive. No EFB does it.

**Lift:** Large. Each data layer is its own ingestion. Some sources are
hard (cell coverage maps are private; FCC license database is a proxy).

**Depends on:** 8 (base suitability raster)

---

## Group C — EFB table-stakes

These don't differentiate but are needed for real-world adoption. The
overlay tool can ship without them; the pilot app eventually needs them.

### C1. Sectional + IFR enroute + approach plate charts

**What:** Display FAA charts (VFR sectional, low/high IFR enroute,
approach plates by airport, airport diagrams) as map overlays.

**Status:** Phase 7f-follow already queued for sectional via OpenAIP.
Approach plates are a different data product (DTPP PDFs from FAA).

**Lift:** Medium for sectionals (one tile source). Large for plates
(per-airport PDF management + IFR procedure rendering).

### C2. METAR / TAF / area forecasts along route

**What:** Display the surface METAR for departure + destination + diverts;
TAF for departure + destination + ETA; route AIRMETs/SIGMETs.

**Status:** EM Diagram repo has METAR ingestion code (Phase 4); needs
porting to overlay repo.

**Lift:** Small (port from sister repo).

### C3. File IFR / VFR flight plans

**What:** One-click flight plan filing through Leidos Flight Service (US)
or EuroControl IFPS (Europe). Auto-fills from the computed route.

**Lift:** Medium. Each filing service has its own API/format.

### C4. Weight + balance calculator

**What:** Real W&B with the aircraft's loading envelope, stations, arm
calculations, CG verification. Visual envelope chart.

**Status:** We have most of the data already (`empty_weight`, `cg_range`,
`max_weight`, `seats`, occupants in sidebar). Need station + arm data
per aircraft.

**Lift:** Medium. Needs aircraft-data additions (stations, arm
references).

### C5. Runway-specific takeoff/landing performance

**What:** Given departure runway (length + surface + slope + wind + DA +
weight), compute takeoff distance and ground roll. Compare to runway
available. Same for landing.

**Status:** We have aircraft V-speeds and stall speeds; need T/O and
landing distance data per aircraft per configuration.

**Lift:** Medium. POH research pass for 110 aircraft. ForeFlight charges
$$ for this as "Performance Plus" — we'd bundle it free.

### C6. Logbook integration

**What:** Pull pilot logbook entries (currency, ratings, total time, type
time) to gate route options. "This IFR route requires a current IPC
within 6 months — your last is 9 months ago, plan a refresher first."

**Lift:** Large. Logbook formats vary (paper, CloudAhoy, ForeFlight,
LogTen Pro). Could start with manual currency entry.

---

## Group D — Brainstormed but lower-priority

Captured here so they don't get lost. Smaller value, more niche, or
duplicative with other items.

### D1. Personal minimums calculator
Each pilot has different comfort zones (max crosswind, ceiling, vis,
terrain elevation, night-mountain). Tool warns if route exceeds them.
Different from FAR mins. Small lift; depends on a settings page.

### D2. Voice route planning
"Plan a route from Summerville to Savannah at 5500." Talks back: "Route
73 NM, 42 min, three diverts in glide..." iPad/iPhone friendly. Medium
lift via Whisper + TTS.

### D3. Multi-pilot collaborative planning
Real-time route sharing; copilots review on their device, comment.
WebSocket layer needed. Medium lift.

### D4. Insurance / regulatory rule engine
Insurance underwriters specify rules ("no more than X NM from a paved
runway", "no overflight of class B at night"). Tool flags violations.
Small lift once a rule DSL exists.

### D5. Photo-evidence handover
After flight: tag a photo + GPS coord. Builds personal landmark database.
"I've used this off-field strip before" boosts its suitability score.
Small lift but UX-heavy.

### D6. CFI route library
CFIs publish canned scenarios (engine-out from KDYB at 3000 AGL, etc.).
Students load them as training routes. Small lift; needs a sharing
infrastructure.

### D7. Higher-resolution terrain for known regions
AWS Terrain Tiles at zoom 11 gives ~75 m/px. Specific canyon routes
might benefit from local higher-res DEMs (USGS 3DEP at 10 m). Per-region
override loader. Medium lift.

### D8. Survival kit recommender
Based on terrain (forest/desert/water/mountain) + season + route. "Your
route crosses 18 NM of pine forest in winter — pack [list]". Small lift;
needs a content library.

### D9. AI-generated pilot brief
Single-page PDF combining weather, NOTAMs, TFRs, route critique, fuel
plan, suitable for hand-off to a CFI or copilot. Medium lift, builds on
B2 (AI critique).

### D10. Comparative aircraft chooser
"What if I flew this in a Cirrus SR22 instead of my Skyhawk?" Side-by-side
metrics. Useful for rental decisions or fleet ops. Small lift — just
re-run the route under each aircraft.

### D11. Mountain-pass / canyon planning
Special handling for terrain-corridor routing (Sierras, Rockies, Apps).
Identify VFR mountain passes, wind-channeling effects. Medium lift.

### D12. Real-time route monitor (in-flight passive mode)
Lighter sibling of B3 — not "what's the nearest divert NOW" but "you're
200 ft below your planned profile, engine-out reach has dropped 5%".
Needs ADS-B input. Medium lift.

### D13. Carbon-offset estimate
Per-flight CO2 calc. Some pilots track this. Optional offset purchase
integration. Small lift.

### D14. Engine-failure rate by airframe hours
Engine reliability degrades with hours since overhaul. Pilots could
enter their airframe's history and get a personalized failure-rate
multiplier feeding into B1 (probabilistic survivability). Small lift.

### D15. Currency-aware divert pre-vetting
"Divert KCEW has a 5300 ft runway with crosswind 14 kt — your last
short-field landing was 3 years ago, recommend KSWS instead with
6500 ft and a headwind." Small-to-medium lift once currency data
exists.

### D16. Sidebar declutter by active maneuver (Phase 8d)
**Status:** task #145, tracked. **Lift:** small.

Left sidebar currently shows every control regardless of which
maneuver is active. Route Planner doesn't use CG slider, power
setting, or occupant weight (gross weight matters but not the
breakdown). Hide controls each maneuver doesn't consume.

Implementation sketch: each maneuver layout module declares
`relevant_sidebar = ('engine', 'wind', 'oat', 'altim', 'fuel')`.
Sidebar groups not in the active list collapse with a "hidden by
maneuver" badge so pilots know nothing is broken — they're just out
of scope.

Per-maneuver relevance:
  - route: engine, wind, OAT, altim, fuel, weight (for SE perf)
  - impossible_turn / poweroff180: weight, CG, power (full envelope)
  - steep_turn / chandelle / lazy8: weight (load factor matters)
  - turns_around_point / s_turn / rect_course: wind primarily
  - eights_on_pylons: weight, IAS  
  - steep_spiral: glide ratio (handled separately)
  - engineout: SE limits — basically all weight + power inputs

---

## How to use this document

When a committed phase (7k / 7L / 7M / 7N / 8 / 9 / 10) is done, revisit
this list and either:
1. Promote an item to a real phase plan (own `docs/plans/...-phase-NN-*.md`)
2. Merge an item into the next committed phase as a refinement
3. Drop it as not-worth-it after the deeper look

The list is intentionally maximal — many of these won't ship, but the
ones that DO ship should be picked from a wider option pool than "what
I happened to think of in the moment."

## Top 3 picks (my read, for when we revisit)

If forced to pick three additions to ship after the committed phases:

1. **B1 Probabilistic survivability** — biggest "is my route safe?"
   payoff in a single number; reuses everything we're already building.
2. **A2 Density altitude correction** — small change, completes the
   honest aircraft-performance story.
3. **B4 Aircraft performance learning** — long-term flywheel that gets
   the tool unique to each pilot's airplane. Hard to copy.

These three together would make the tool feel like a pilot-aware
planning assistant rather than a generic route drawer.
