# TallyAero EM Diagram — Execution Plan

> **Project namespace:** `tallyaero_*` — the previous `aeroedge_*` naming is deprecated as of D7 (2026-05-12). Every code reference, asset path, identifier, and product string must read `tallyaero`. Directory renames happen in Phase 1; this plan and all new code use the new namespace.

**Owner:** Nick Len
**Drafted:** 2026-05-12
**Target outcome:** A signed, downloadable desktop application (macOS + Windows + Linux) that renders an Energy-Maneuverability diagram with verified physics, professionally-sourced aircraft data, full FAA-grade airport data, live aviation weather, and a UI/UX that is unambiguously the best EM tool a general-aviation, multi-engine, aerobatic, or military pilot can put on their laptop.
**Out of scope (for this plan):** Maneuver overlay tool. It is the next deep-dive after this one ships. Anything we touch that is *shared* with the overlay tool is logged in the [Shared Asset Ledger](#shared-asset-ledger) so it can be cleanly duplicated when we pivot.

---

## 0a. Locked Decisions

Recorded 2026-05-12. Any change requires a deliberate revision and a note in the [Execution Log](#execution-log).

| # | Decision | Choice | Implication |
|---|---|---|---|
| D1 | Aircraft data integrity | **Hybrid: cited as `verified`, uncited as `estimated`** with a UI flag | Schema gets a per-value `confidence` enum and a `sources[]` array. Chart annotates "estimated values shown" when any displayed value is uncited. Drives Phase 2 + Phase 5 UI work. |
| D2 | v1 fleet scope | **GA + multi-engine + aerobatic only** | No turbojet thrust dispatch in Phase 2 (defer). No Mach drag rise. No coffin-corner for jets in Phase 5 — but keep it for v1.1 trainer aircraft (T-6, T-38) if we add them. |
| D3 | Telemetry | **No telemetry at all** in the desktop binary | `aeroedge_tracker.py` is excluded from the PyInstaller spec entirely. Phase 6 strips its imports from `app.py`. The Render-hosted analytics endpoint is irrelevant to this product. |
| D4 | Kickoff | **Plan approved, start Phase 0** | First session is Phase 0 steps 1–3 only. No `app.py` edits. No data scraping. No layout work. |
| D5 | Visual language | **Mirror the TallyAero monorepo** (`apps/portal` + `apps/pilot`). Same dark sidebar, same brand blue (`#0d59f2`), same Inter / Space Grotesk type stack, same 6px corner radius, same active-item left-bar pattern. | Phase 5 leads with a "visual parity" step that ports the design tokens out of the monorepo before any other UI work. The overlay tool inherits the same tokens — they are part of the [Shared Asset Ledger](#shared-asset-ledger). |
| D6 | Quality bar | **Tesla / SpaceX / Apple grade.** No Bootstrap defaults. No generic spinners. No half-baked Plotly themes. Every interactive element gets a deliberate hover, focus, and active state. Every chart transition gets a curve. Every layout is composed, not arranged. | This is a cross-cutting requirement, not a phase. Each phase has a "Polish gate" — work doesn't ship until it crosses the bar. See [0c. Design North Star](#0c-design-north-star). |

---

## 0c. Design North Star

The product can be aviation-grade *and* feel like it was designed by Apple's industrial team. These two ambitions converge if we hold the bar at every detail. This section sets the bar.

### Visual parity with the TallyAero monorepo
Source files we mirror (do not redistribute — these stay in the monorepo, we copy *concepts and tokens*):
- `apps/portal/src/layouts/AppShell.tsx` — sidebar geometry, collapse behavior, mobile drawer pattern
- `apps/portal/src/index.css` (lines 17–180) — token definitions
- `apps/pilot/src/components/Layout/AppSidebar.tsx` — rail mode, active-bar pattern
- `apps/pilot/src/config/navigationConfig.ts` — nav-item structure
- `packages/ui/src/web/tokens.css` — shared design tokens
- `packages/ui/src/assets/tally-aero-logo.png` — logo

### Token translation: TallyAero → AeroEdge EM
Drop these into `assets/tokens.css` verbatim. The overlay tool gets the same file via the [Shared Asset Ledger](#shared-asset-ledger).

| Token | Value | Notes |
|---|---|---|
| `--brand-blue` | `#0d59f2` | Primary. Active-state, focus rings, Ps>0 chart accent |
| `--brand-orange` | `#f27b0d` | Accent. Warning, corner-speed annotation, urgent maneuvers |
| `--sidebar-bg` | `#0a0e17` | Always dark — even when content area is light |
| `--surface-elevated` | `#161e2d` (dark) / `#ffffff` (light) | Card / popover background |
| `--surface-base` | `#0a0e17` (dark) / `#f8fafc` (light) | Page background |
| `--text-primary` | `#f1f5f9` (dark) / `#0f172a` (light) |  |
| `--text-secondary` | `#cbd5e1` (dark) / `#64748b` (light) |  |
| `--text-muted` | — / `#94a3b8` |  |
| `--border-primary` | `#222f49` (dark) / `#e2e8f0` (light) |  |
| `--success` | `#22c55e` | Ps>0 region tint |
| `--danger` | `#ef4444` | Ps<0 region tint, stall boundary |
| `--warning` | `#f27b0d` | Doubles as accent |
| `--radius-sm` | `6px` | Universal — buttons, cards, inputs, modals |
| `--sidebar-width-collapsed` | `56px` |  |
| `--sidebar-width-expanded` | `240px` |  |
| `--motion-fast` | `100ms` | Hover, focus |
| `--motion-base` | `200ms` | Slide, fade |
| `--motion-deliberate` | `400ms` | Layout shifts, chart transitions |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Affirmative actions (toggle on, success) |
| `--ease-standard` | `cubic-bezier(0.4, 0, 0.2, 1)` | Everyday transitions (Material standard easing) |

### Type system
- **Display** (page titles, hero numbers): `Space Grotesk`, weight 700–900, letter-spacing −0.025em
- **Body**: `Inter`, weights 400/500/600. Body text 14px, dense labels 12px, micro-labels 10px **all-caps** with letter-spacing 0.1em
- **Monospace** (any numbers in the chart hover, telemetry): `JetBrains Mono` 13px
- All fonts bundled locally in `assets/fonts/` — no Google CDN at runtime (the binary is offline-first)

### Iconography
Use **Lucide** icons. They're MIT, ~600 SVGs, weight-balanced at 1.5px stroke. Same library portal uses. Bundle the SVGs we use directly into `assets/icons/` (not the full npm package — we don't have a JS build step).

### Sidebar (the structural anchor)
Mirror `apps/portal/src/layouts/AppShell.tsx`:
- 56px collapsed rail / 240px expanded
- Always `#0a0e17` background (even in light theme — that's the rule)
- Active item: 3px blue left bar, rounded right cap, + `bg-white/10` row background
- Hover: `bg-white/5` + text brightens to white
- Section dividers between groups (`h-px bg-white/10`)
- Top: logo (mark when collapsed, wordmark when expanded)
- Bottom: user pill + theme toggle + collapse arrow
- Mobile (<768px): slide-in overlay, not bottom tab bar (we don't have enough top-level destinations to justify the latter)
- The toggle button uses the spring easing so it has a satisfying click

### Quality bar — what "Tesla/SpaceX/Apple grade" actually means here
Concrete commitments, not adjectives:

1. **No Bootstrap defaults visible anywhere.** `dash-bootstrap-components` stays as a layout primitive only; every visible component is restyled via `assets/styles.css`. We delete or override Bootstrap's blue, its buttons, its tooltips, its accordion chevrons.
2. **No generic Plotly modebar.** Hide it by default. Build a custom toolbar (zoom reset / download / fullscreen / share) that lives in our chart card, styled to match.
3. **No generic spinners.** Loading uses skeleton shapes that match the layout being loaded (Apple-style content placeholders), or a custom progress arc, never `dbc.Spinner`.
4. **Every chart line is deliberate.** Axis ticks anti-aliased, axis labels in our type system, grid color from tokens, hairline weight (`0.5px`). The envelope outline gets 2px; intermediate G curves get 1px; Ps contours get 0.5px. Visual hierarchy.
5. **Motion is purposeful.** When the user changes weight, the envelope reshapes with a 400ms eased animation — not a redraw. When the chart updates from a new aircraft, axes interpolate. When a number changes in the State Panel, it transitions with a brief flash of `--warning` if it crosses a limit.
6. **Numbers have weight.** Hero numbers (current corner velocity, current Ps) are in Space Grotesk 32px–48px black with a tabular-numeric variant so digits don't shift width as they tick.
7. **Empty states are designed.** "No aircraft selected" isn't a paragraph — it's a centered glyph + one sentence + one CTA, just like Apple Notes when there's nothing to show.
8. **First-paint discipline.** No flash of unstyled content. No layout shift after the chart loads. The sidebar appears with the page; the chart fades in on top of a tiny placeholder that holds its dimensions.
9. **Print export looks like a deliverable.** A3 / Letter PDFs match Apple Keynote presets — generous margins, a cover sheet, a colophon footer with the source citations.
10. **No accidental color.** Every color in the running app comes from `tokens.css`. Audit script in Phase 5 greps the codebase for raw `#xxx` and fails CI on any match outside `tokens.css`.

### Polish gates per phase
Each phase ends with a polish gate that checks against this bar. No phase advances until:
- All visible UI uses tokens (no raw hex outside `tokens.css`)
- All transitions use a token easing/duration
- All interactive elements have hover + focus + active styling
- All copy reads like it was written by a human, not a developer
- A screenshot of the new work, viewed at full resolution, doesn't shame the previous phase

---

## 0b. Working Contract

Before any code moves, these are the rules of engagement for the entire EM-diagram cycle. They derive from the existing `Master prompt and context.md` and are restated here so we don't drift.

1. **Root-cause only.** Every fix names the bug, names the physical/logical reason for the fix, and names the regression test that prevents reoccurrence. No tolerances hiding bugs. No snapping geometry. No "good enough."
2. **Single source of math.** All physics lives in `core/`. If we find inline math anywhere else, we extract it. Period.
3. **`update_graph()` is sacred.** Lives at `app.py:1621`. All plotting logic (curve generation, layout, axis config, annotations) stays inside it. Even after we decompose `app.py` (Phase 1) it stays one function in one module.
4. **Aircraft JSON schema is authoritative.** It's defined in [Phase 2](#phase-2--aircraft-data-hardening). Schema changes require migration scripts and validation.
5. **Deterministic.** Same inputs → same outputs. No hidden state, no global mutation outside `core/aircraft_loader.py` boot, no order-dependent callbacks. Phase 0 establishes golden-output snapshots so we *prove* this.
6. **Phase gates.** Each phase ends with: (a) tests green, (b) `python app.py` boots, (c) golden EM diagram snapshot matches, (d) one paragraph written into this doc's [Execution Log](#execution-log). No advancing without all four.
7. **Duplicate, don't share.** Across the two apps (EM + overlay), shared modules are *copied with a stamp*, not symlinked or packaged. The drift detector (Phase 7) is how we keep them honest.
8. **Two-app discipline.** While we are in EM mode, we don't touch overlay code. If we find something the overlay needs to know, we write it in the [Cross-App Bulletin](#cross-app-bulletin) at the bottom of this doc.

---

## 1. Inventory & Surface Map

What we have, what's missing, what's lying about being healthy.

### 1.1 Code surface
| Component | Location | LOC | State |
|---|---|---|---|
| Entry point | `app.py` | 5,975 | Monolith. Contains layout, ~55 callbacks, inline Vmca/Vyse calcs, edit-aircraft CRUD UI, PDF/PNG export, browser-launch loop. |
| Physics core | `core/calculations.py` | 408 | Clean. All 7 audit sessions passed. Single source of truth — uphold this. |
| Aircraft loader | `core/aircraft_loader.py` | 190 | Has side-effect imports at lines 180–187 that load all 110 JSONs at module-import time. Bad for testing. Fix in Phase 0. |
| Constants | `core/constants.py` | 70 | Read once, mostly OK. |
| Tests | `tests/test_core.py` | 154 | Smoke tests with hand-coded golden values. No `pytest`, no figure snapshots, no JSON validation. Expand in Phase 0. |
| Layouts | `app.py:316–885` | 569 | Desktop + mobile each defined inline. Will move to `layouts/`. |
| Edit-aircraft form | `app.py:3802–4959+` | ~1,200 | Entire JSON CRUD UI lives in `app.py`. Belongs in `layouts/edit_aircraft.py` + `callbacks/edit_aircraft.py`. |
| Export | `app.py:3535–3801` (PDF, PNG) | ~260 | Uses kaleido. Verify kaleido bundles cleanly in PyInstaller. |
| Stub packages | `callbacks/`, `components/`, `pages/`, `ui/` | 5 each | Empty `__init__.py` only. Hollow shells from a previous refactor attempt. Will fill in Phase 1. |
| Assets | `assets/styles.css`, `assets/export.js` | small | Working but unaudited. |
| Tracker | `aeroedge_tracker.py` | shared | Phone-home analytics. Identical between apps except `PROJECT_SLUG`. Stays as-is for now; revisit in Phase 6 (a desktop binary should ship with telemetry **off by default**). |

### 1.2 Data surface
| Dataset | Source | Records | Schema completeness | State |
|---|---|---|---|---|
| Aircraft profiles | `aircraft_data/*.json` | 110 files | Strong nested schema (G_limits × category × config, stall_speeds × config × weights, single_engine_limits, engine_options w/ OEI performance, drag polar via CD0/AR/e, prop_thrust_decay) | Hand-curated. Source of values is unknown per-aircraft. `T_static_factor` is hardcoded to 2.6 for almost every profile — a placeholder, not a measured value. |
| Airports | `airports/airports.json` | 16,128 | **Minimal.** Only `{id, name, lat, lon, elevation_ft}`. No runways, no frequencies, no magvar, no surface, no class, no timezone. | Functionally a stub. Major rework in Phase 3. |
| Weather | none | — | — | Doesn't exist. Phase 4. |
| Type Certificate Data | none | — | — | Doesn't exist. Phase 2 will pull from FAA TCDS. |

### 1.3 Callbacks present in `app.py` (head-of-list)
Top section markers from `grep`:
- `app.layout` → 190
- Forward ghost help clicks → 296
- Display page (router) → 889
- Reload aircraft on return → 911
- Set last selected aircraft → 925
- Aircraft options → 936
- Category dropdown → 946
- Expand UI on aircraft select → 962
- Airspeed units toggle → 978
- Prop condition toggle → 995
- Dynamic Vmca visibility → 1015
- Aircraft-dependent inputs → 1042
- Altitude from airport → 1119
- PA/DA display → 1161
- Default OAT → 1200
- OAT °F sync → 1213
- CG slider → 1224
- Config dropdown → 1285
- Gear dropdown → 1299
- Gear visibility → 1315
- Total weight → 1326
- `calculate_vmca()` → 1359 (inline physics, move to `core/vmca.py`)
- `calculate_dynamic_vyse()` → 1495 (inline physics, move to `core/vyse.py`)
- **`update_graph()` → 1621** (the sacred one)
- Maneuver options renderer → 3354
- ACS standard enforcement → 3492
- PDF generator → 3535
- PNG generator → 3670
- Edit-page navigation → 3802, 3812
- Browser width detector → 3837
- Aircraft loader for edit → 3897
- Defaults applier → 4123
- Multi-engine section toggle → 4419
- Units sync → 4431
- Expand/collapse all → 4446
- G-limits CRUD (add/render/update) → 4459–4559
- Stall-speeds CRUD → 4560–4675
- Single-engine-limits CRUD → 4676–4885
- Engine-options CRUD → 4884–end

That's the spine. Phase 1 splits this along the natural seams.

### 1.4 Aircraft JSON schema (observed)
From `Cessna_172P.json`, `Beechcraft_Baron_58.json`, `CAP_232.json`:

```jsonc
{
  "name": "...",
  "type": "single_engine" | "multi_engine",
  "gear_type": "fixed" | "retractable",      // sometimes missing
  "engine_count": 1 | 2,
  "wing_area": <float, ft²>,
  "aspect_ratio": <float>,
  "CD0": <float>,                            // parasite drag coeff
  "e": <float>,                              // Oswald efficiency
  "configuration_options": {
    "flaps": ["clean", "takeoff", "landing"] // varies; aerobatic may be ["clean","landing"]
  },
  "G_limits": {
    "<category: normal|utility|aerobatic>": {
      "<flap_config>": { "positive": <g>, "negative": <g> }
    }
  },
  "stall_speeds": {
    "<flap_config>": {
      "weights": [<lb>, <lb>, <lb>],
      "speeds":  [<kt>, <kt>, <kt>]
    }
  },
  "single_engine_limits": {
    // Singles:
    "best_glide": <kt>,
    "best_glide_ratio": <float>,
    // Twins (additionally):
    "Vmca": { "clean_up": <kt>, "takeoff_up": <kt>, "landing_down": <kt> },
    "Vyse": { "clean_up": <kt>, "takeoff_up": <kt>, "landing_down": <kt> },
    "Vxse": { "clean_up": <kt>, "takeoff_up": <kt>, "landing_down": <kt> }
  },
  "engine_options": {
    "<engine name>": {
      "horsepower": <int>,
      "power_curve": { "sea_level_max": <int>, "derate_per_1000ft": <float> },
      "oei_performance": {                   // twins only
        "<flap_config>": {
          "<prop: feathered|windmilling|stationary>": {
            "max_power_fraction": <0..1>,
            "best_glide_speed_kias": <kt>,
            "rate_of_climb_fpm": <int>
          }
        }
      }
    }
  },
  "max_altitude": <ft>,
  "Vne": <kt>, "Vno": <kt>,
  "Vfe": { "takeoff": <kt>, "landing": <kt> },
  "CL_max": { "clean": <f>, "takeoff": <f>, "landing": <f> },
  "arcs": { "white": [low,high], "green": [low,high], "yellow": [low,high], "red": <kt> },
  "empty_weight": <lb>, "max_weight": <lb>, "seats": <int>,
  "cg_range": [<aft>, <fwd>],
  "fuel_capacity_gal": <gal>, "fuel_weight_per_gal": <lb/gal>,
  "prop_thrust_decay": { "T_static_factor": <f>, "V_max_kts": <kt> }
}
```

### 1.5 Known-good and known-bad
**Good (per `PHYSICS_AUDIT_PLAN.md`, all 7 sessions passed):**
- Ps formula, thrust decay, density-altitude, TAS, turn rate (3 forms), turn radius, bank-from-rate, load factor, stall speed at n, accelerated-stall iterator
- CG/gear drag/lift factors
- Vmca/Vyse modifier ranges
- Envelope masking by DVmc
- Negative-G envelope, corner-speed detection, intermediate-G curves
- Steep-turn and chandelle energy models

**Bad / incomplete:**
- ~40 `dprint()` calls scattered (lines 1265, 1757, 1813, 2237–48, 2870, 3082–85, 3344, 3599, 3732, 5521, 5525 etc.) — needs proper `logging`
- `prop_thrust_decay.T_static_factor = 2.6` is identical across nearly every aircraft. Placeholder, not measured.
- No altitude/Mach thrust correction for turbocharged or military aircraft
- `airports/airports.json` is a stub (5 fields)
- No live weather hookup
- No JSON schema validation at boot
- Boot-time side effects in `core/aircraft_loader.py:180–187`
- Empty stub packages (`callbacks/`, `components/`, `pages/`, `ui/`) imply a refactor was abandoned
- No mobile/desktop reuse — both layouts duplicated wholesale
- Edit-aircraft CRUD inside `app.py` (lines 3802–4959+)
- No accessibility audit (Ps gradient is red→green; viridis/cividis is the colorblind-safe replacement)
- PyInstaller awareness exists (`resource_path()` checks `sys._MEIPASS`) but no `.spec` file ships

---

## 2. Phase Plan

Each phase has: **Goal • Steps • Files touched • Acceptance criteria • Estimated effort (sessions, where one session = focused half-day) • What this hands to the overlay tool**.

The phases are sequential. Phases 2 and 3 (data scraping) can run partially in parallel because they touch disjoint datasets, but we'll not start them until Phase 1 has decomposed `app.py` so the data-loading seam is clean.

### Phase 0 — Safety Net (1–2 sessions)

**Goal:** No change we make later breaks what already works. Establish a deterministic baseline.

**Steps:**
1. Add `pytest`, `pytest-snapshot`, `pydantic` (v2), `jsonschema` to `requirements.txt`. Pin all package versions exactly (currently most are pinned; verify `gunicorn`).
2. Convert `tests/test_core.py` to `pytest`-style. Keep the existing assertions; add edge cases (zero V, zero weight, 90° bank, sub-zero density alt, empty stall speeds list, Vne > V_max_kts, etc.).
3. Add `tests/test_jsons.py`: load every file in `aircraft_data/`, run it through a Pydantic schema (defined here as a first draft — refined in Phase 2). Fail loudly on any anomaly.
4. Add `tests/test_figure_snapshot.py`: pick 3 reference scenarios (172P @ 4000ft / +20°C, Baron 58 @ 8000ft / OEI feathered, CAP 232 aerobatic @ SL / +15°C). Call `update_graph` with frozen inputs. Snapshot the returned `figure.to_dict()`. CI fails on any drift.
5. Extract boot-time loading from `core/aircraft_loader.py:180–187` into `init_data()` called explicitly from `app.py`. Eliminates side effects on import. Tests can now load curated data without the full 110-aircraft set.
6. Replace all `dprint()` with `logging.getLogger("tallyaero.em")`. Env-var `AEROEDGE_LOG=DEBUG|INFO|WARNING` controls verbosity. Default WARNING.
7. Add `prevent_initial_call=True` to every callback that isn't explicitly initial-firing.
8. Add a top-of-repo `Makefile`:
   - `make test` → pytest -q
   - `make run` → python app.py
   - `make snapshot` → regenerates golden figure snapshots (only after a deliberate physics change)
   - `make freeze` → produces `requirements.lock.txt` via `pip-compile`

**Files touched:** `requirements.txt`, `tests/*`, `core/aircraft_loader.py`, `app.py` (logging conversion + initial-call guards only — no logic changes).

**Acceptance:**
- `make test` is green
- `make run` boots, EM diagram renders, no debug spam unless `AEROEDGE_LOG=DEBUG`
- Pydantic loads all 110 aircraft without errors
- Three golden figure snapshots exist on disk and match
- Boot-time side effect is gone; data loads via explicit init

**Hand-off to overlay tool:**
- The Pydantic schema, the logger setup, the `init_data()` pattern, the figure-snapshot harness are all reusable. Log them in the [Shared Asset Ledger](#shared-asset-ledger).

---

### Phase 1 — Code Decomposition (3–5 sessions)

**Goal:** `app.py` becomes a thin entry point (< 150 lines). All other code lives in semantic modules. `update_graph()` stays one function.

**Steps:**
1. Create real packages:
   ```
   layouts/
     __init__.py
     desktop.py          ← from app.py:316–642
     mobile.py           ← from app.py:643–885
     edit_aircraft.py    ← from app.py:3802–4959 + edit_aircraft_page.py
     fragments/          ← shared layout fragments
       sidebar.py
       state_panel.py
       legend.py
   callbacks/
     __init__.py         ← register_all(app)
     routing.py          ← display_page, last-saved restore
     aircraft.py         ← selection, cascading inputs
     environment.py      ← airport, alt, OAT, altimeter, PA/DA
     weight_cg.py        ← fuel, occupants, CG slider
     figure.py           ← update_graph() — the sacred function
     export.py           ← PDF, PNG via kaleido
     edit_aircraft.py    ← all CRUD callbacks
   components/
     __init__.py
     em_chart.py         ← thin wrapper around update_graph output
     tooltips.py         ← shared hover tooltip builders
     annotations.py      ← Ps level marks, corner speed annotation, energy-flow arrows
   core/
     calculations.py     (unchanged)
     constants.py        (unchanged)
     aircraft_loader.py  (cleaned in Phase 0)
     vmca.py             ← from app.py:1359–1494
     vyse.py             ← from app.py:1495–1588
     atmosphere.py       ← new home for compute_air_density etc. if we choose to split
     schema.py           ← Pydantic aircraft model
   data/
     services/           ← weather (Phase 4)
     scrapers/           ← aircraft + airport scrapers (Phases 2/3)
   ```
2. Move `calculate_vmca` and `calculate_dynamic_vyse` from `app.py` into `core/vmca.py` / `core/vyse.py`. Keep public signatures. Add unit tests for the Vmca modifier ranges (already documented in `PHYSICS_AUDIT_PLAN.md` Priority 2).
3. Move plotting helpers (currently inlined in `update_graph`) into `components/em_chart.py` *only if* they have no side effects. The function itself stays in one place: `callbacks/figure.py`.
4. Replace the `desktop_layout()` / `mobile_layout()` duplication. Build a single responsive layout using:
   - Dash Mantine Components or vanilla Dash + CSS grid + media queries
   - Reuse via shared `fragments/`
   - Keep the JS browser-width detector but use it only to switch a CSS class (`is-mobile`), not to swap entire trees.
5. `app.py` final shape:
   ```python
   from layouts import build_layout
   from callbacks import register_all
   from core.aircraft_loader import init_data
   from core import logging_setup

   logging_setup()
   data = init_data()
   app = dash.Dash(__name__, ...)
   app.layout = build_layout()
   register_all(app, data)
   if __name__ == "__main__":
       launch_browser_and_serve()
   ```
6. Add a top-level `pyproject.toml` so the package is installable for testing (`pip install -e .`).
7. Verify `update_graph` snapshots from Phase 0 still match. If they don't, we broke it.

**Files touched:** `app.py`, every new module above, `tests/test_figure_snapshot.py` (paths only).

**Acceptance:**
- `app.py` < 150 lines
- Phase 0 snapshots match
- `make test` green
- No circular imports (verify with `python -m pyflakes` / `import linter`)
- Single responsive layout passes mobile screen-size test (Chrome DevTools 375px width)
- All callbacks have `prevent_initial_call` set deliberately

**Hand-off to overlay tool:** Layout fragments, callback registration pattern, packaging structure. Worth duplicating verbatim. Log in ledger.

---

### Phase 2 — Aircraft Data Hardening (3–4 sessions)

**Goal:** Every aircraft profile has *citable* numbers from manufacturer documents. The schema rejects garbage. The drag/thrust models work for high-performance aircraft, not just trainers.

**Steps:**
1. **Lock the schema.** `core/schema.py` defines a `Pydantic v2` model that matches `Section 1.4`. Required vs optional fields explicit. Custom validators:
   - `CL_max.clean < CL_max.takeoff < CL_max.landing`
   - `stall_speeds.<config>.weights` monotonic increasing
   - `stall_speeds.<config>.speeds` monotonic increasing
   - `G_limits.<category>.<config>.positive >= 1.0` and `.negative <= 0.0`
   - `cg_range[0] < cg_range[1]`
   - `Vne > Vno > Vfe.<any>`
   - `engine_options[*].power_curve.derate_per_1000ft` in `[0.02, 0.06]` (sanity)
2. **Validate all 110 existing files.** Build a triage CSV: filename, errors, warnings. Fix in batches.
3. **Reconcile with overlay-tool divergence.** The overlay tool ships 112 files; 2 are new and several have drifted. Diff them. Whichever value matches the cited POH wins. Both trees update simultaneously (one of the few legitimate cross-app touches during the EM phase — but we copy the EM-side files **into** the overlay tree, not the reverse).
4. **Source citation field.** Add `sources: [{publication, page, year, retrieved}]` to the schema. Every value must trace.
5. **Scrape canonical values:**
   - **FAA TCDS** (Type Certificate Data Sheets): primary source for max_weight, empty_weight, Vne, Vno, Vfe, Vs, CG range, fuel capacity, max altitude. Public, free, authoritative. URL pattern: `https://drs.faa.gov/browse/TCDS/...`. Script: `data/scrapers/faa_tcds.py`.
   - **Manufacturer POH excerpts** (where freely available): CL_max, CD0, e — these are *not* in TCDS and are usually derived from POH performance charts or published aerodynamics texts (Roskam, Raymer, Hoak USAF DATCOM).
   - **OurAirports / Wikipedia** for cross-check on wing area and aspect ratio.
   - **JANE's / Air Force Magazine / DTIC** for military aircraft (F-16, T-38, A-10, etc.) where we want to extend the database.
6. **Thrust model upgrade.** The current `prop_thrust_decay = { T_static_factor: 2.6, V_max_kts }` is fine for fixed-pitch piston singles. It's wrong for:
   - **Turbocharged engines** — flat power up to critical altitude, then derate
   - **Constant-speed props** — different static thrust factor than fixed-pitch
   - **Turbines** — entirely different thrust curve, often modeled as `T = T_SL × (ρ/ρ_SL)^n` where n ≈ 0.7–0.8
   - **Jets** — Mach-dependent, modeled with installed thrust lapse curves
   Add a `thrust_model` discriminator to the schema: `"piston_fixed_pitch" | "piston_constant_speed" | "turbocharged" | "turboprop" | "turbojet"`. Each variant has its own parameters. Update `compute_thrust_available()` in `core/calculations.py` to dispatch on `thrust_model`. **This is a physics change — golden snapshots will regenerate. Document why in commit message.**
7. **Drag polar at high CL.** Current `CD = CD0 + CL²/(π·AR·e)` assumes the polar is parabolic to stall. Real aircraft show separation rise above ~0.8 × CL_max. Add optional `cd_rise_above_cl` field per aircraft (default off; turn on for aircraft where we have wind-tunnel data).
8. **CG-band CL/CD curves.** Currently CG effect is a multiplier (≤ 5%). Replace with a per-aircraft `cg_effects: { aft: {cl_factor, cd_factor}, fwd: {...} }` so it's data-driven.
9. **Reduce-by-one** — delete any aircraft that we cannot find at least one TCDS-grade citation for. Better to ship 80 verified aircraft than 110 plausibly-fabricated ones.

**Files touched:** `aircraft_data/*.json` (all), `core/schema.py`, `core/calculations.py` (thrust dispatch), `data/scrapers/faa_tcds.py`, `data/scrapers/poh_extractor.py`, `tests/test_jsons.py`.

**Acceptance:**
- Every file passes Pydantic validation
- Every file has at least one entry in `sources`
- Thrust model dispatch unit-tested for each `thrust_model` value
- Golden snapshots regenerated and reviewed (diff each against pre-Phase-2 by eye)
- A triage doc `docs/aircraft_data_triage.md` records which aircraft were dropped, which were re-cited, which were corrected

**Hand-off to overlay tool:** New schema, scrapers, updated `compute_thrust_available`. Critical — overlay's 11 maneuver simulators all consume aircraft data. Log in ledger.

---

### Phase 3 — Airport Data Overhaul (2–3 sessions)

**Goal:** Replace the 16,128 × 5-field stub with full FAA-grade airport data. Runways with headings, lengths, surfaces. Frequencies. Magnetic variation. Timezone. Worldwide coverage.

**Steps:**
1. **Pick the canonical source(s):**
   - **OurAirports.com** publishes CSV exports under CC0 (public domain). Worldwide coverage. Includes runways, frequencies, navaids. Updated monthly. URL: `https://ourairports.com/data/`. This is the spine.
   - **FAA NASR Data** (28-day AIRAC cycle) for US precision (FAA-authoritative for runway data, lighting, NOTAMs base). URL: `https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/`.
   - Merge: OurAirports as base; FAA NASR overrides US records.
2. **Define new schema** (`core/schema_airport.py`):
   ```python
   class Runway(BaseModel):
       ident: str               # e.g., "13/31"
       le_ident: str            # "13"
       he_ident: str            # "31"
       length_ft: int
       width_ft: int
       surface: Literal["asphalt","concrete","grass","gravel","water","snow","ice","dirt","unknown"]
       lighted: bool
       closed: bool
       le_heading_deg_true: float | None
       he_heading_deg_true: float | None
       le_displaced_threshold_ft: int | None
       he_displaced_threshold_ft: int | None
       le_latitude: float | None
       le_longitude: float | None
       he_latitude: float | None
       he_longitude: float | None
       le_elevation_ft: int | None
       he_elevation_ft: int | None

   class Frequency(BaseModel):
       type: Literal["TWR","GND","CLD","ATIS","UNICOM","CTAF","APP","DEP","CTR","FSS","AWOS","ASOS","RCO","OTHER"]
       description: str
       frequency_mhz: float

   class Airport(BaseModel):
       id: str                  # OurAirports id
       icao: str | None         # ICAO ident
       iata: str | None         # IATA code
       ident: str               # local ident (FAA loc id or ICAO)
       name: str
       lat: float
       lon: float
       elevation_ft: int | None
       country: str             # ISO 3166-1 alpha-2
       region: str | None
       municipality: str | None
       type: Literal["large_airport","medium_airport","small_airport","heliport","seaplane_base","balloonport","closed"]
       scheduled_service: bool
       runways: list[Runway]
       frequencies: list[Frequency]
       magvar_deg: float | None        # NOAA WMM, computed from coords + date
       timezone: str | None            # IANA tz, looked up by coords
       last_updated: date
       source: Literal["ourairports","faa_nasr","merged"]
   ```
3. **Build `data/scrapers/airports_pipeline.py`:**
   - Step 1: Download OurAirports CSVs (airports.csv, runways.csv, airport-frequencies.csv, navaids.csv)
   - Step 2: Join into per-airport records
   - Step 3: For US airports, overlay FAA NASR data (which has more accurate runway thresholds)
   - Step 4: Compute magvar via the IGRF/WMM coefficients (use the `pygeomag` package, which is pure-Python — no native deps)
   - Step 5: Compute IANA timezone from lat/lon using `timezonefinder` (also pure-Python and bundled)
   - Step 6: Output `airports/airports.json` (runtime) and `airports/airports.sqlite` (fast lookup)
4. **Update `core/aircraft_loader.py`** (the airport-loader sections, lines 121–157) to load the new schema. Maintain a backward-compat shim during the migration so we don't break things.
5. **UI changes** (Phase 5 will polish, but the dropdown logic needs an update now):
   - Search by ident OR name OR municipality
   - Show airport class indicator (large/med/small/heliport)
   - When an airport is selected, show *which* runway is in use (closest to current wind, if weather is loaded — but that's a Phase 4 dependency)
6. **Refresh strategy:** Bundle a snapshot with each binary release. On launch, if internet is available, check OurAirports' "last_modified" header and prompt user to download an update (don't auto-download — user controls bandwidth). New snapshot lives in `~/Library/Application Support/TallyAero/airports/` (or `%APPDATA%\AeroEdge\airports\` on Windows) and takes precedence over the bundled one.

**Files touched:** `airports/airports.json` (rebuild from scratch), `airports/airports.sqlite` (new), `core/aircraft_loader.py` (airport sections), `core/schema_airport.py`, `data/scrapers/airports_pipeline.py`.

**Acceptance:**
- `airports/airports.json` validates against `Airport` schema for 100% of records
- Spot-check 20 known airports (KJFK, KSFO, KORD, EGLL, RJAA, plus 5 small US, 5 small international, 5 heliports): names, elevations, runways match published charts
- Magvar matches NOAA's online calculator to within 0.1° for the spot-checks
- Timezone matches IANA tzdb for spot-checks
- Snapshot refresh prompt fires when source data is newer than bundled
- Dropdown search responds in < 50ms for typing into 16k+ records (use indexed SQLite, not in-memory linear scan)

**Hand-off to overlay tool:** The full airports pipeline, schema, and SQLite generator. Log in ledger.

---

### Phase 4 — Live Aviation Weather (2–3 sessions)

**Goal:** Pick an airport → automatically populate OAT, altimeter, wind from real-time METAR. Auto-prefill density altitude. Pull winds aloft for any altitude. Show timestamp and stale state.

**Steps:**
1. **Pick the source(s):**
   - **NOAA Aviation Weather Center** (`aviationweather.gov/api/data`) — free, no API key, US authoritative. METAR, TAF, AIRMET, SIGMET, winds aloft (GFS-MOS).
   - **CheckWX** (`checkwxapi.com`) — global, free tier (45,000 req/mo), requires API key. Better global METAR coverage. Use as fallback for international airports.
2. **Build `data/services/weather.py`:**
   ```python
   class WeatherService:
       def fetch_metar(self, icao: str) -> Metar | None: ...
       def fetch_taf(self, icao: str) -> Taf | None: ...
       def fetch_winds_aloft(self, lat: float, lon: float, altitude_ft: int) -> WindsAloft | None: ...
   ```
   Cache TTL: METAR 5 min, TAF 1 hr, winds 6 hr. Cache on disk (so re-launches don't re-fetch). Backed by `~/Library/Application Support/TallyAero/cache/weather.sqlite`.
3. **Parse METAR rigorously.** Don't reinvent — use `python-metar` or `metar-taf-parser`. Extract: temp_c, dewpoint_c, altimeter_inhg (convert from QNH if needed), wind_dir_true (METAR is magnetic over the US? **No — METAR wind is true, ATIS/tower-relayed wind is magnetic**; this is a common bug. We will get this right and write a regression test.), wind_kts, gust_kts, visibility, sky conditions.
4. **UI integration (groundwork — Phase 5 polishes):**
   - On airport select, fire a background `dcc.Interval` (one-shot) that calls the weather service
   - Show a "live weather" badge with timestamp
   - Button: "Apply live weather" → fills OAT, altimeter input boxes
   - Toggle: "Auto-refresh every 5 min while open"
   - On weather fetch failure: keep manual values, show a small warning chip with the reason
5. **Winds aloft.** Use the GFS-MOS / NOAA gridded winds product. Look up the four-corner grid points around the airport, interpolate to the exact lat/lon, then to the selected altitude (log-pressure interpolation). Output `{wind_dir_true_deg, wind_kts, temp_c}` for any altitude up to FL480.
6. **Threading and Dash:** Dash callbacks must not block. Use a `dcc.Interval` + a server-side cache. The pattern is: callback triggers a background `threading.Thread` that updates a thread-safe cache; the next interval tick reads from the cache and updates the figure/store.
7. **Offline mode:** Detect no network. Show a banner. Don't keep retrying every 5 seconds. Show "Last successful fetch: <time>".
8. **Privacy.** No telemetry of *which* airport was looked up. Don't send user agent beyond a generic `TallyAero-EM/<version>`. Document this in the README.

**Files touched:** `data/services/weather.py`, `data/services/metar_parser.py`, `data/services/winds_aloft.py`, `core/aircraft_loader.py` (none — weather is independent), `callbacks/environment.py`, `requirements.txt` (add `python-metar` or `metar-taf-parser`, `aiohttp` or `requests` w/ cache).

**Acceptance:**
- METAR fetch for KJFK / EGLL / RJAA returns parsed values within 2 seconds of click
- 5 spot-checks vs `metar.vatsim.net` (or pilot weather brief) match to 1 hPa / 1 °C / 5° wind / 2 kts
- Stale data > TTL is refreshed silently in background
- Offline mode shows banner and last-good values
- Unit test: feeding 20 hand-crafted METAR strings into the parser yields expected structured output
- No callback exceeds 100 ms in main thread

**Hand-off to overlay tool:** The full weather service module. The overlay tool especially benefits because maneuver simulations need real wind to produce honest ground tracks. Log in ledger.

---

### Phase 5 — UI/UX Overhaul (3–5 sessions)

**Goal:** What today is a competent chart becomes a tool a pilot can't put down. Accessible. Information-dense without clutter. Aesthetically calibrated, not "Bootstrap default".

**Steps:**

**5.1 Accessibility**
- Replace red→green Ps gradient with `viridis` (default colorblind-safe) or `cividis` (high-contrast, also colorblind-safe). Keep red→green as an opt-in legacy mode.
- Audit chart text contrast — all annotation labels should hit WCAG AA at the smallest zoom level we support.
- Add `aria-label` on every input.
- Keyboard nav: arrow keys adjust the sliders, `g` toggles ghost trace, `e` toggles edit page.
- Honor `prefers-reduced-motion` — disable any pulse/glow effects.

**5.2 Layout & visual design**
- Replace dual-tree layout (`desktop_layout()` + `mobile_layout()`) with one CSS-grid layout that reflows.
- Build a small design token set: spacing (4/8/12/16/24/32), type scale (12/14/16/18/24/32), color (background, surface, text, primary, danger, accent, ps_zero, ps_pos, ps_neg). Token names land in `assets/tokens.css`. Components consume tokens, not raw hex.
- Sticky chart on desktop (chart pinned, sidebar scrolls). On mobile, sidebar slides in from the side.
- Dark mode toggle. Don't paper over Bootstrap — define the dark palette in the token file and `@media (prefers-color-scheme: dark)` flips it.

**5.3 Information density (the "mind-blowing" tier)**
- **State Panel** (top-right of chart): six glance metrics that update live as inputs change — current weight, current Vs1g, current Vy, current Va, current Vne, current corner velocity. Color-flag any that are violated.
- **Comparison Mode**: hold *shift* on aircraft dropdown to add a second aircraft. Both envelopes render in the same chart with distinct line styles. The state panel splits into two columns.
- **Risk Overlay**: optional shading of the envelope showing where loss-of-control / stall-spin accidents are concentrated. Source: NTSB CAROL accident database, queryable. We pre-aggregate by altitude/AoB/airspeed and ship the aggregate (raw NTSB data is large; the histogram is small).
- **Spin Awareness**: for aerobatic-category aircraft, shade the region inside the negative-G envelope where un-coordinated departure most commonly leads to spins. Inputs: published spin entry speed, max negative G certified.
- **Coffin Corner**: for high-altitude aircraft (military, jets — once we add them), draw the stall and Mmo curves converging.
- **Maneuver Replay**: ghost-trace and chandelle currently render as static paths. Add a scrub bar that animates a dot along the path with time, showing energy state at each point. The same scrub bar drives a synchronized inset showing altitude/heading/IAS vs time.
- **What-if Diff**: a "before / after" toggle. Snapshot the current envelope, change inputs, see both overlaid in a subtle outline so the delta is visible.

**5.4 Edit-aircraft page**
- Move out of `app.py` (already in Phase 1)
- Live validation as you type (red border, tooltip with the failing rule)
- "Duplicate from existing" — pick an aircraft, get a pre-filled form with a new name
- "Bulk import CSV" — for adding many aircraft quickly with a flat CSV → JSON converter
- "Export all" — downloads `aircraft_data.zip`

**5.5 Onboarding**
- First-launch: a 4-step interactive walkthrough — pick aircraft, set environment, read the chart, try a maneuver
- "What am I looking at?" tooltip on the EM diagram itself with a layered explanation (one-line / one-paragraph / full explainer)
- Sample profiles: pre-saved "172 Pattern Practice", "Baron OEI Demo", "CAP 232 Aerobatic Block"

**5.6 Print & export**
- A3 / A4 / Letter print-quality PDF with: cover sheet (aircraft, conditions, date, pilot name field), full envelope, state panel, methodology footnote with citations
- PNG at 300 dpi
- SVG export for instructors who want to overlay on slide decks
- "Share link" generates a deep-link query string that recreates the exact view on another machine (works because everything is deterministic per the working contract)

**Files touched:** `assets/tokens.css`, `assets/styles.css`, `layouts/*`, `components/*`, `callbacks/figure.py` (color palette swap), `callbacks/export.py` (SVG + share-link), several new components.

**Acceptance:**
- Lighthouse accessibility score > 95
- All copy verified by a real pilot (Nick) for clarity and aviation correctness
- Comparison mode works for any two of the 110 aircraft without performance regression
- Mobile (375px) layout is genuinely usable, not just "doesn't break"
- Dark mode flips cleanly with no orphaned colors
- Share-link round-trips perfectly on a different machine

**Hand-off to overlay tool:** Tokens, mobile-responsive grid system, state-panel pattern, scrub-bar component. Log in ledger.

---

### Phase 6 — Packaging & Distribution (2–3 sessions)

**Goal:** A signed, double-clickable application for macOS, Windows, and Linux that boots fast, runs offline, and updates safely.

**Steps:**

**6.1 PyInstaller spec**
- Create `tallyaero_em_diagram.spec`:
  ```python
  a = Analysis(
      ["app.py"],
      pathex=["."],
      binaries=[],
      datas=[
          ("aircraft_data/*.json", "aircraft_data"),
          ("airports/airports.json", "airports"),
          ("airports/airports.sqlite", "airports"),
          ("assets/*", "assets"),
          ("VERSION", "."),
          ("LICENSE", "."),
      ],
      hiddenimports=[
          "dash", "plotly", "kaleido", "dash_bootstrap_components",
          "pygeomag", "timezonefinder", "metar",
      ],
      hookspath=["build/hooks"],
      excludes=["matplotlib", "tkinter", "PySide", "PyQt5"],   # trim weight
  )
  ```
- Use `--onedir` (faster startup than `--onefile`). Bundle inside a `.app` (macOS) or installer (Windows).
- Custom PyInstaller hook for Plotly/Kaleido (kaleido bundles a Chromium — heavy but unavoidable for PDF/PNG export).

**6.2 Launcher**
- `launcher.py`:
  - Picks a free port (don't hardcode 8051) via `socket.socket().bind(("127.0.0.1", 0))` then read the assigned port
  - Starts the Dash server in a background thread
  - Waits for `/healthz` to respond
  - Opens default browser to `http://127.0.0.1:<port>`
  - On macOS, shows a status bar item (optional, `rumps` package). On Windows, shows a tray icon (`pystray`).
  - Clean shutdown when the tray/menu is closed

**6.3 Code signing & notarization**
- macOS: requires Apple Developer ID Application certificate ($99/yr). Sign with `codesign --deep --options runtime --sign "Developer ID Application: ..." dist/AeroEdge.app`. Notarize via `xcrun notarytool`. Staple with `xcrun stapler staple`.
- Windows: EV or OV code signing certificate (DigiCert, Sectigo, ~$200–400/yr for OV). Sign with `signtool`. Without signing, Windows SmartScreen will scare users away.
- Linux: not signed (no equivalent universal mechanism). Ship `.AppImage` and `.deb`.

**6.4 Installers**
- macOS: `.dmg` containing the `.app` and a drag-to-Applications shortcut. Build with `dmgbuild`.
- Windows: NSIS or Inno Setup installer. Adds Start Menu entry, optional desktop shortcut, no admin rights required (install to `%LocalAppData%`).
- Linux: `.AppImage` (universal) and `.deb` for Debian/Ubuntu (we don't ship `.rpm` until someone asks).

**6.5 Auto-update check**
- On launch, in background, hit `https://api.github.com/repos/<repo>/releases/latest`
- If newer than bundled version, show a non-modal banner: "Version X.Y is available. [Download]"
- Don't auto-install. Let the user choose.

**6.6 First-run experience**
- Detects missing user data directory; creates it
- Caches user preferences (preset aircraft, units, dark mode) in `~/Library/Application Support/TallyAero/` etc.
- Shows EULA / privacy notice (we don't phone home; analytics is opt-in)
- Optional crash-reporter (Sentry, off by default)

**6.7 CI/CD**
- GitHub Actions matrix: `macos-13`, `macos-14` (arm64), `ubuntu-22.04`, `windows-2022`
- Each builds + signs + uploads to a draft release
- Manual promote to public release after smoke-testing

**6.8 Size targets**
- macOS `.app`: aim < 250 MB after bundling Chromium for kaleido. (If too big, ship a "lite" version without PDF/PNG export — uses a built-in browser-side `Plotly.toImage()` instead.)
- Windows installer: aim < 200 MB compressed
- Linux AppImage: aim < 250 MB

**Files touched:** new `tallyaero_em_diagram.spec`, `launcher.py`, `build/hooks/*`, `.github/workflows/release.yml`, `installer/macos/dmgbuild.py`, `installer/windows/setup.iss`.

**Acceptance:**
- Double-click `.app` on a clean macOS machine → app starts in < 3 seconds, opens browser, EM diagram renders
- Same on Windows with no developer tools installed
- Signed bundle passes Gatekeeper (macOS) and SmartScreen (Windows) without "unknown developer" warning
- Auto-update banner appears when a newer release exists
- Crash-reporter shows no crashes during a 1-hour exploratory test

**Hand-off to overlay tool:** Spec file template, launcher, installer scripts, signing pipeline. Log in ledger.

---

### Phase 7 — Cross-App Reciprocity (1–2 sessions, then continuous)

**Goal:** When we pivot to the overlay tool, copying the EM-hardened modules in is mechanical, auditable, and drift-resistant.

**Steps:**
1. Stamp every file in `core/`, every aircraft JSON, every airport schema, and every shared utility with a header:
   ```python
   # ─────────────────────────────────────────────────────────────
   # SHARED MODULE — also lives in tallyaero_overlay_tools/core/
   # source_hash: <sha256 of file body excluding header>
   # synced_from: tallyaero_em_diagram
   # synced_at: 2026-05-12T14:30:00Z
   # version: core 1.0.0
   # If you edit this in one app, run scripts/sync_check.py
   # ─────────────────────────────────────────────────────────────
   ```
2. Build `scripts/sync_check.py`:
   - Walks both project trees side-by-side
   - For each file listed in the [Shared Asset Ledger](#shared-asset-ledger), computes content hash (excluding header)
   - Reports drift
   - `--apply em-to-overlay` copies from EM → overlay (the canonical direction during EM phase)
   - `--apply overlay-to-em` requires a `--force` flag and prints a big warning (you should only do this after the overlay-tool deep dive when we shift roles)
3. Document the sync workflow in this doc's [Cross-App Bulletin](#cross-app-bulletin).
4. Mark Phase 7 as **never closed** — it is an ongoing discipline.

**Files touched:** every shared module gets a header (one-time), `scripts/sync_check.py`.

**Acceptance:**
- `python scripts/sync_check.py` reports zero drift between the two trees at the moment of EM-phase completion
- A deliberate edit on one side is detected on the next run

---

## 3. Data Strategy

### 3.1 Aircraft data sources (Phase 2)
| Source | Coverage | Authority | License | Cadence |
|---|---|---|---|---|
| FAA TCDS | Type-certified US aircraft | Authoritative for cert weights, V-speeds, fuel | Public domain | Static per certification |
| EASA TCDS | Type-certified EU aircraft | Authoritative for European types | Public | Static |
| AOPA, Beechcraft Aero Club, etc. POH archives | Performance charts | Manufacturer-authoritative | Mixed — verify license before redistributing values | Static |
| Roskam, Raymer, Hoak DATCOM | CD0, e, AR derivations | Textbook authoritative | Cite, don't redistribute | Static |
| Wikipedia / WikiData | Sanity check on AR, wing area, dimensions | Crowd-sourced — secondary only | CC-BY-SA | Continuously updated |
| Air Force Magazine, Jane's, DTIC | Military aircraft | Authoritative for performance | Some paywall — cite, don't include | Static |
| NTSB CAROL | Accident overlay (Phase 5) | Authoritative | Public | Updated daily |

### 3.2 Airport data sources (Phase 3)
| Source | Coverage | Authority | License | Cadence |
|---|---|---|---|---|
| OurAirports CSV | Worldwide | Community + crowd-sourced; very good | CC0 | Monthly |
| FAA NASR (NFDC) | US | Authoritative US runway data | Public domain | 28-day AIRAC |
| EUROCONTROL EAD | EU | Authoritative EU | Restricted — don't bundle | AIRAC |
| NOAA WMM coefficients | Magvar | Authoritative | Public | 5-year coefficient revisions |
| IANA tzdb | Timezone | Authoritative | Public | Bi-annual |

### 3.3 Weather sources (Phase 4)
| Source | Coverage | Authority | License | Cadence |
|---|---|---|---|---|
| NOAA AWC API | US + many international METARs | Authoritative US | Public | Real-time |
| CheckWX | Global METAR/TAF | Re-distributor; well-maintained | Free tier 45k/mo, paid above | Real-time |
| NOAA GFS-MOS | Winds aloft | Authoritative | Public | 6-hourly |

### 3.4 Update / refresh strategy
- **Aircraft data:** versioned with the binary release. A "data hotfix" releases just an updated `aircraft_data/` bundle that the app can sideload (without an app re-install). Hotfixes are signed with the same code-signing cert.
- **Airport data:** bundled, but the app checks OurAirports' last-modified header on launch and prompts. User-initiated download.
- **Weather:** always live. No bundled data.

---

## 4. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Kaleido (PDF/PNG export) bundles a 200MB Chromium that bloats the binary | High | Med | Make export an optional feature; offer browser-side PNG fallback via `Plotly.toImage()` |
| 2 | macOS notarization rejection (Apple is strict about embedded executables) | Med | High | Test notarization early; budget time for entitlements debugging |
| 3 | Windows SmartScreen still warns even with OV cert until reputation builds | High | Med | Plan to publish at least 3 versions on first cert. Consider EV cert ($600/yr) which avoids the warning |
| 4 | Aircraft data values can't be sourced from public POHs for all 110 aircraft | High | Med | Acceptable to drop aircraft we can't cite. Quality > quantity |
| 5 | OurAirports schema changes and the pipeline breaks | Low | Med | Pin a schema version; run pipeline tests on every release; have an FAA-only fallback for US users |
| 6 | NOAA AWC API rate-limits us under heavy use | Low | Low | Aggressive cache; fall back to CheckWX |
| 7 | Aircraft schema change in Phase 2 invalidates Phase 0 golden snapshots | Certain (this is by design) | Low | Re-snapshot deliberately; eyeball diff; document rationale in commit |
| 8 | `update_graph` becomes too slow when comparison mode + Ps grid + maneuver replay all run | Med | High | Profile early. Cache per-aircraft Ps grids keyed on (aircraft, weight, altitude, OAT, config, gear, oei). Recompute only on input change |
| 9 | Drift between EM and overlay aircraft JSONs reintroduced after Phase 7 | Med | Med | Sync-check script runs in CI on both trees |
| 10 | A physics bug we missed in audit sessions 1–7 surfaces only under comparison mode | Med | High | Cross-aircraft comparison is also a cross-check on physics — if two superficially similar aircraft produce wildly different envelopes, investigate |
| 11 | The "mind-blowing UX" features (replay, comparison, what-if) bloat the code and slow down core flows | Med | Med | Each new feature lives behind a feature flag during development. Ship only when it doesn't regress baseline |
| 12 | I (assistant) hallucinate published numbers when sourcing aircraft data | Med | Critical | Every value MUST be backed by a citation field. CI checks `sources` is non-empty. Spot-audit 10% of values against original PDFs manually |

---

## 5. Acceptance — "Ship" Definition

When all of these are true, the EM-diagram deep dive is shipped:

- [ ] `make test` green on macOS, Windows, Linux CI
- [ ] Three golden figure snapshots stable for at least one full week of further dev
- [ ] All 110 aircraft (or fewer, deliberately culled) pass Pydantic validation and have ≥1 citation
- [ ] Airports dataset covers worldwide with runways + frequencies + magvar + timezone
- [ ] METAR/TAF/winds-aloft for KJFK, EGLL, RJAA returns sane values in < 2 s
- [ ] Lighthouse accessibility ≥ 95 on desktop and mobile viewports
- [ ] Signed `.app`, `.exe`, `.AppImage` boot on clean OS images and render the EM diagram in < 3 s
- [ ] Comparison mode, maneuver replay, dark mode all functional and not behind flags
- [ ] Sync-check script reports zero drift with overlay tool tree
- [ ] README and on-app help text cover every feature with at least one example
- [ ] Crash-free during 8-hour internal use test

---

## 6. Shared Asset Ledger

These are the artifacts that **must** stay in sync between `tallyaero_em_diagram` and `tallyaero_overlay_tools`. Each is *duplicated* (not symlinked) and validated by `scripts/sync_check.py`. Canonical source during the EM phase: **EM diagram**.

| Asset | Path in EM | Path in Overlay | Why shared |
|---|---|---|---|
| Physics math | `core/calculations.py` | `core/calculations.py` (replace overlay's `physics/aerodynamics.py`) | Single source of math |
| Atmosphere | `core/calculations.py` (compute_air_density / DA / PA / TAS) | Same | Density altitude needed in both |
| Vmca calc | `core/vmca.py` (after Phase 1 move) | `core/vmca.py` | Multi-engine envelopes & engine-out maneuvers |
| Vyse calc | `core/vyse.py` | `core/vyse.py` | OEI climb & engine-out maneuvers |
| Constants | `core/constants.py` | `core/constants.py` | g, conversions, rho_SL must match exactly |
| Aircraft schema | `core/schema.py` | `core/schema.py` | Both apps consume aircraft data |
| Aircraft data | `aircraft_data/*.json` (110 files) | `aircraft_data/*.json` (110 files) | Same fleet |
| Airport schema | `core/schema_airport.py` | `core/schema_airport.py` | Both apps reference airports |
| Airport data | `airports/airports.json` + `.sqlite` | `airports/airports.json` + `.sqlite` | Both apps reference airports |
| Airport scrapers | `data/scrapers/airports_pipeline.py` | Same | One pipeline, two consumers |
| Weather service | `data/services/weather.py` + parsers | `data/services/weather.py` | Overlay needs live winds for ground tracks |
| Logging setup | `core/logging_setup.py` | Same | Uniform DEBUG/INFO/WARNING behavior |
| Logger name | `aeroedge.<app>` differs per app — that's fine |  |  |
| Aeroedge tracker | `aeroedge_tracker.py` | `aeroedge_tracker.py` | Identical except PROJECT_SLUG |
| Design tokens | `assets/tokens.css` | `assets/tokens.css` | Shared visual language |
| Sync check | `scripts/sync_check.py` | `scripts/sync_check.py` | Drift detector |

Not shared (intentional divergence): `app.py`, layouts, callbacks, components (each app has its own UI), maneuver simulators (overlay only), EM-diagram-specific export PDFs.

---

## 7. Cross-App Bulletin

Notes for the overlay-tool deep dive that comes after EM ships. Written here so we don't lose them.

- The 11 duplicated implementations of turn rate / radius across `simulation/*.py` in the overlay tool must all be deleted and replaced with imports from `core.calculations`. This is the first step of the overlay deep dive.
- Steep-turn drift bug (NEXT_TASK.md) is unfixed there. Apply the `drift_corrected()` pattern from `impossible_turn.py` to `steep_turn.py`.
- Hover-data schema mismatch across maneuvers. Define one schema in `core/maneuver_state.py`, enforce across all 11 maneuvers.
- `engine_out.py` is 115 KB single-file with 11 "buckets". Split per bucket and unit-test each.
- After Phase 7 here, overlay starts by pulling fresh copies of every Shared Asset from this tree.

---

## 8. Open Questions

These need answers before / during execution. Each is a real decision, not a placeholder.

1. **Multi-engine military / jets — in or out of scope for v1?** Adding F-16, T-38, A-10 etc. requires the `thrust_model: "turbojet"` path in Phase 2.6 and Mach-corrected drag. Plausible to include 3–5 well-documented military trainers; full F-16-grade modeling is its own project.
2. **Comparison mode — 2 aircraft only, or N?** 2 is clean; N gets messy fast. Recommend 2.
3. **Risk overlay (NTSB CAROL data) — do we ship aggregate, or compute live?** Recommend pre-aggregated bundle (~few MB), refreshed quarterly.
4. **Telemetry — opt-in / opt-out / off?** Recommend opt-in only, with explicit consent on first launch. The existing `aeroedge_tracker.py` is opt-out by default which is wrong for a desktop app.
5. **Pricing & distribution channel.** Free download? Paid? Mac App Store / Microsoft Store distribution would simplify signing but adds review overhead and revenue share.
6. **Aircraft data — is fabricated/best-guess data acceptable for now, or do we hold the release until every value is cited?** Recommend cited-only. Drop uncited aircraft from v1; re-add them in a data update once sourced.
7. **Mac arm64 vs x86_64 — universal binary or separate downloads?** Universal is best UX, slightly more build complexity.
8. **License of the application itself?** Closed-source binary distribution? Open-source (AGPL/MIT)? Hybrid (core open, polish closed)? Has implications for the aircraft-data sourcing license question.

---

## 9. Execution Kickoff (next session)

When we begin executing, the very first session does only this:

1. Read this plan top to bottom and confirm the assumptions still hold
2. Run Phase 0, step 1 (pin deps, add pytest, pydantic, jsonschema)
3. Run Phase 0, step 2 (convert tests to pytest, add edge cases)
4. Run Phase 0, step 3 (Pydantic-validate all 110 aircraft, output triage CSV — read-only, no fixes yet)
5. Stop. Review triage CSV with Nick. Decide which aircraft we audit/cite/drop in Phase 2.

That's it. No `app.py` edits. No layout work. No data scraping. We establish the floor.

---

## 10. EM Theory Foundations — Research Brief

Captured 2026-05-14 from a four-agent parallel research pass. Sources verified against primary documents where possible. The brief exists so future sessions don't need to re-litigate the lineage.

### 10.1 The Lineage (chronological, not "Boyd then everyone else")

Energy-state methods predate Boyd by **two decades**. The popular framing "Boyd invented EM" is wrong in a specific, important way — he *operationalized and extended* a body of work that already existed in the open Western and German literature:

| Year | Author | Contribution | Scope |
|---|---|---|---|
| 1944 | F. Kaiser, Messerschmitt | First energy-height concept on record (*resultierende Höhe*) for Me 262 climb optimization. Reconstructed by Merritt/Cliff/Vincent, *Automatica* 21(3), 1985. | 1-D (climb only) |
| 1951 | K.J. Lush, RAE | Named "energy height" in Western literature. Proved energy-state was *required* once kinetic-energy variation became non-negligible (transonic jets). | 1-D climb |
| **1954** | **E.S. Rutowski, Douglas Aircraft** | **THE foundational paper**, *J. Aero. Sci.* 21(3): 187–195. Introduced `dE/dt = (T−D)·V/W = Ps` and the h-V skymap with Ps contours — the chart format Boyd later adopted. | **1-D, n=1 (straight-line flight only)** |
| 1955 | A. Miele | NACA TM-1389, optimum flight paths via calculus of variations. | 1-D climb |
| 1960 | H.J. Kelley, Grumman | "Gradient Theory of Optimal Flight Paths," ARS Journal — steepest-descent for trajectory optimization. | 1-D climb |
| 1962 | A.E. Bryson & W.F. Denham | Steepest-ascent applied to supersonic interceptor minimum-time-to-climb (Harvard). | 1-D climb |
| **1964** | **J. Boyd, T. Christie (USAF Eglin)** | **APGC-TDR-64-35** (classified SECRET). First insertion of load factor `n` into the energy equation. Two-volume working report. | **2-D maneuvering** |
| **1966** | Boyd, Christie, Gibson | **APGC-TDR-66-4** (declassified version, NARA ISCAP 2011-052). The canonical EM theory document. Project 0350T4. | 2-D maneuvering, comparative two-aircraft overlay |
| 1969 | Bryson, Desai, Hoffman | *J. Aircraft* 6(6) — mathematical rigorization of what Boyd had produced empirically five years earlier. | 2-D, formal optimal-control basis |

### 10.2 What Boyd Actually Did (vs Popular Myth)

**Documented:**
1. Inserted load factor `n` into Rutowski's `Ps = V·(T−D)/W` to extend it from 1-D climb to 2-D maneuver: `Ps = V·[T − D(α, M, n)]/W`. This is the genuinely novel mathematical move.
2. The two-aircraft comparative overlay chart. The 1966 APGC report opens with explicit F-4C vs MiG-21 sustained-turn Ps surfaces at 1G/3G/5G. **This is Boyd's killer original feature**, and no consumer EM tool ships it today.
3. Operationalized it inside USAF — Rutowski's paper sat as a Douglas performance trick; Boyd made EM the procurement language behind the F-X (→ F-15) and LWF (→ F-16).

**Contested or mythologized:**
- "Boyd invented EM" — overstated; he extended Rutowski with `n` and the comparative-overlay use case.
- "Boyd designed the F-15/F-16" — he influenced the requirements/spec via Fighter Mafia advocacy; Harry Hillaker at General Dynamics designed the F-16 airframe. Boyd himself later complained the production F-16 was "compromised" by added armor.
- "OODA is part of EM" — separate works, decades apart. The bridge documents are *New Conception for Air-to-Air Combat* (Boyd, 4 Aug 1976) and *Destruction and Creation* (Boyd, 3 Sep 1976). The OODA loop is formalized in *Patterns of Conflict* (1986).
- The *Aerial Attack Study* (1960, declass 1964) is a separate **tactics** treatise, not the EM paper — popular sources frequently conflate them.

### 10.3 Where Our Tool Sits in the Pedagogical Stack

The translation gap from engineering rigor to GA-pilot pedagogy is real and quantifiable:

| Audience | Source | What's taught |
|---|---|---|
| Aero engineer | Roskam & Lan; Stinton; Hull; Phillips; Yechout (AIAA 2023) | Full doghouse + equations + drag polar + design trades |
| Test pilot | **USAF TPS Performance Phase Ch 9 "Energy"** (USAF-TPS-CUR-86-01); **USNTPS FTM-108 *Fixed Wing Performance*** | Doghouse, level-accel, pushover-pullup, zoom climb, P-h, Ps contours — all with equations |
| Aerobatic / CFI-MEI | Stick & Rudder; IAC manuals; type-club docs | V-n diagram only; Va/Vne/Vy scalar |
| GA / private pilot | **FAA-H-8083-3C Ch 4 "Energy Management"** (added 2021) | Qualitative altitude-airspeed map; "throttle = energy rate, elevator = distribution"; NO Ps contours, NO turn-rate axis |

The **2021 FAA AFH Ch 4 addition is the first time energy management entered the GA training canon**. It is qualitative-only. There is no civilian-readable, interactive doghouse aimed at the GA + multi + aerobatic audiences — exactly TallyAero's market position. Our tool is the missing translation layer between AFH Ch 4 (qualitative, GA-readable) and TPS Ch 9 / FTM-108 (quantitative, engineer-readable).

### 10.4 Primary Source Artifacts

Verified and accessible at time of research (2026-05-14). If a URL rots, the file titles are sufficient to re-locate via NTRS / DTIC / NARA / AIAA.

**Boyd canon:**
- Boyd, Christie, Gibson, *Energy-Maneuverability (U)*, APGC-TDR-66-4 Vol I, 15 Jan 1966. NARA ISCAP release: `archives.gov/files/declassification/iscap/pdf/2011-052-doc1.pdf`
- Boyd, *Aerial Attack Study*, USAF Report 50-10-6C, declassified 11 Aug 1964. Hosted at `everyspec.com`, `code7700.com`, `ausairpower.net`.
- Boyd, *New Conception for Air-to-Air Combat*, 4 Aug 1976. `slightlyeastofnew.com/wp-content/uploads/2010/03/newconception.pdf`
- Boyd, *Destruction and Creation*, 3 Sep 1976.
- Boyd, *Patterns of Conflict*, 196-slide briefing, formal version Dec 1986.

**Pre-Boyd canon:**
- Rutowski, *J. Aero. Sci.* 21(3) March 1954: `arc.aiaa.org/doi/10.2514/8.2956` (AIAA paywall)
- Kelley, *ARS Journal* Oct 1960: `perceptrondemo.com/assets/1960-kelley-07dff188.pdf`
- Bryson & Denham, *J. Appl. Mech.* 29 (1962): `gwern.net/doc/ai/1962-bryson.pdf`
- Bryson, Desai, Hoffman, *J. Aircraft* 6(6), 1969: `arc.aiaa.org/doi/abs/10.2514/3.44093`
- Miele, NACA TM-1389 (1955): `ntrs.nasa.gov/citations/19930093841`
- Gabrielli & von Kármán, "What Price Speed?" *Mech. Eng.* Oct 1950: `gwern.net/doc/technology/1950-gabrielli.pdf`

**Pedagogy:**
- USAF TPS Ch 9 "Energy" (USAF-TPS-CUR-86-01): `apps.dtic.mil/sti/tr/pdf/ADA320211.pdf`
- USNTPS FTM-108 *Fixed Wing Performance* — USNTPS Alumni Association / Amazon
- FAA AFH Ch 4 Energy Management: `faa.gov/sites/faa.gov/files/regulations_policies/handbooks_manuals/aviation/airplane_handbook/05_afh_ch4.pdf`
- Takahashi, "The Doghouse Plot: History, Construction Techniques, and Application," AIAA-2017-3266 (ASU Aircraft Design Lab) — the only modern academic paper explaining doghouse construction to non-fighter audiences.

**Post-2010 academic extensions:**
- Lombaerts et al., *Safe Maneuvering Envelope Estimation based on a Physical Approach*, AIAA GNC 2013; NTRS 20140005797
- *Piloted Simulator Evaluation of Maneuvering Envelope Information for Flight Crew Awareness*, NASA TM 2016
- Helsen, Lombaerts et al., *Probabilistic Flight Envelope Estimation with Application to Unstable Overactuated Aircraft*, JGCD 2020 (doi 10.2514/1.G004193)
- Stepanyan, Krishnakumar et al., *Stall Recovery Guidance Using an Energy Based Algorithm*, AIAA SciTech 2017 (doi 10.2514/6.2017-1021)
- Pope, Ide et al., *Hierarchical Reinforcement Learning for Air-to-Air Combat*, arXiv:2105.00990 (2021) — Lockheed Martin's PHANG-MAN, 2nd place DARPA AlphaDogfight
- Heron Systems, AlphaDogfight Trials 2020 (5-0 vs F-16 WIC graduate) — DARPA program docs
- DARPA ACE (X-62A VISTA live-flight AI dogfight, Sept 2023): `darpa.mil/research/programs/air-combat-evolution`
- Selmonaj et al., *Hierarchical Multi-Agent RL for Air Combat Maneuvering*, arXiv:2309.11247 (2023)
- Total Energy-Based Control for Lift-Plus-Cruise eVTOL, JGCD doi 10.2514/1.G007605 (2023)

**Biographies (secondary):**
- Robert Coram, *Boyd: The Fighter Pilot Who Changed the Art of War* (2002) — narrative; conflates EM and OODA freely
- Grant T. Hammond, *The Mind of War* (2001); Hammond's 2012 Harmon Memorial Lecture at USAFA is the better condensed account

---

## 11. Phase 5U–Z — Future Feature Lab

Six candidate features surfaced by the 2026-05-14 research pass, each fully spec'd so they can be executed in isolation without re-research. Priority is the column to scan; effort is the gating constraint. Status moves from `pending` → `in_progress` → `completed` as features ship.

The team's current lean (per the 2026-05-14 conversation) is **5U + 5V together** as the next push: comparative overlay (the feature Boyd invented EM *for*) plus KE/PE recovery arrows (closes the AFH Ch 4 → TPS Ch 9 translation gap that's the tool's market position).

### Phase 5U — Comparative Aircraft Overlay

**Status:** pending. **Priority:** HIGHEST. **Effort:** medium.

**Synopsis:** Plot two aircraft envelopes on the same chart with distinct styling. Show a relative-advantage delta in the State Panel.

**Pedagogical motivation:** This is the feature Boyd invented EM *to enable*. The 1966 APGC-TDR-66-4 report opens with F-4C vs MiG-21 sustained-turn overlays at 1G/3G/5G — comparative overlay was the *original* use case. Shaw's 1985 *Fighter Combat: Tactics and Maneuvering* argues the relative-energy diagram is the single most useful instrument for a fighter pilot. Despite this, no consumer EM tool today ships comparative overlay. For our audience (CFI-MEI, aerobatic instructors), the canonical use case is "should I fly the Baron 58 or the Seneca for this mission profile?" or "how does my Citabria stack up against a Decathlon?"

**Theoretical basis:** Boyd/Christie/Gibson 1966, fig. 8–14 (F-4C vs MiG-21 comparative diagrams). Shaw 1985, Ch 4. Takahashi AIAA-2017-3266 §III (comparative skymap construction).

**What the user sees:**
- A second `dcc.Dropdown` in the top strip, hidden by default, opened by a `+` chip next to the aircraft picker (or by a shortcut `c` for "compare")
- When a second aircraft is selected, both envelopes render with the same Ps grid but distinct line styles (primary = solid as today; comparison = dashed; corner markers at both `(corner_ias, corner_tr)` points)
- State Panel splits into two columns (Aircraft 1 / Aircraft 2)
- Below the chart, a "Relative Advantage" strip shows regions of the V-TR plane where each aircraft is favored (using Ps delta sign and turn-rate delta)
- "Close comparison" chip returns to single-aircraft mode

**Implementation sketch:**
- New `dcc.Store(id="compare-aircraft", data=None)` at app.py shared-store level
- `callbacks/figure.py:update_graph` gets an additional Input for `compare-aircraft.data`; when non-null, runs the full envelope computation twice and renders both
- New helper `_render_comparison_advantage()` in figure.py — for each (V, TR) cell, compute `Ps_A − Ps_B` and shade with a divergent palette (RdBu but neutral midpoint)
- `callbacks/main.py:update_state_panel` gains a comparison branch — returns 12 cards instead of 6
- `layouts/desktop.py` top strip: add `+ Compare` chip with state-aware swap
- Tests: new `tests/test_compare.py` — given two known aircraft (172P vs Baron 58), verify both envelopes render distinct trace counts and the advantage map has the expected sign somewhere

**Risk:** chart density. Two envelopes + Ps contours + maneuver overlays could overwhelm. Mitigation: when in compare mode, automatically suppress turn-radius lines and Ps contours unless explicitly re-enabled. The comparative-advantage strip carries the load.

**Files touched:** `callbacks/figure.py`, `callbacks/main.py`, `layouts/desktop.py`, `assets/styles.css` (advantage strip + dashed comparison palette), new `tests/test_compare.py`.

### Phase 5V — KE/PE Split + Recovery Arrows

**Status:** pending. **Priority:** HIGH. **Effort:** small.

**Synopsis:** Render the kinetic-energy / potential-energy split of the current state as a stacked bar in the State Panel, with directional arrows on the chart showing the "dive to recover" and "trade altitude for speed" gradients.

**Pedagogical motivation:** Closes the AFH Ch 4 → TPS Ch 9 translation gap. The 2021 FAA AFH Ch 4 framing — "throttle = energy rate, elevator = energy distribution" — is exactly KE/PE split, but the AFH presents it qualitatively. Stepanyan et al. (NASA Ames, AIAA 2017-1021) derive the recovery commands directly from the KE/PE ratio. A small visualization makes the AFH's qualitative idea quantitative without leaving the GA audience behind.

**Theoretical basis:** Total energy `E = h + V²/(2g)`. KE fraction = `V²/(2g·E)`. PE fraction = `h/E`. Recovery gradient: when below a target Vy (energy too "low"), pitching down trades PE → KE along the constant-energy curve until KE supports Vy at a slightly lower altitude. Stepanyan 2017 Eq. 7-12 give the closed-form pitch+throttle commands.

**What the user sees:**
- Two new State Panel cards: `KE` (with bar showing fraction in blue) and `PE` (orange). Both sum to `E`.
- A small inset on the chart, top-right corner of the plot area: a stacked horizontal bar segmented blue/orange representing the current state
- Optional toggle "Recovery arrows" in the drawer's Overlay Options. When on: at the current (IAS, TR=0) operating point, render a short curved arrow tangent to the constant-energy curve pointing toward the nearest viable recovery state (Vy)
- Hover the bar → tooltip with `KE = N ft, PE = N ft, E = N ft, ratio = X%`

**Implementation sketch:**
- New `core/calculations.py:compute_energy_state(altitude_ft, ias_kt) -> {ke_ft, pe_ft, e_total_ft, ke_fraction}` (pure function, easy to test)
- New `components/state_panel.py:_energy_split_card()` — stacked bar via CSS
- New trace in `callbacks/figure.py` when "recovery_arrows" in overlay_toggle: a `go.Scatter` annotation with `mode="lines+text"` from current state along the constant-energy curve toward Vy, with arrowhead
- Tests: parametric — `compute_energy_state(0, 100)` returns KE=336 ft, PE=0 ft, E=336 ft (V²/2g math); `compute_energy_state(10000, 100)` returns KE=336, PE=10000, E=10336

**Effort breakdown:** State Panel card (~30 min); chart inset bar (~30 min); recovery-arrow toggle + math (~1 hr); tests (~30 min). Total ~2.5 hr.

**Files touched:** `core/calculations.py`, `components/state_panel.py` (or `callbacks/main.py` if state panel still lives there), `callbacks/figure.py`, `assets/styles.css`, new `tests/test_energy_state.py`.

### Phase 5W — Safe Maneuvering Envelope (Lombaerts reachable set)

**Status:** pending. **Priority:** medium (highest *novelty* among the six). **Effort:** large.

**Synopsis:** Compute and shade the **forward ∩ backward reachable** envelope, projected onto (IAS, turn rate). Renders as a "bow-tie" inside the static envelope showing where the aircraft can actually GO from current state and from where it can RETURN to trim.

**Pedagogical motivation:** The single highest-leverage academic-to-teaching transfer available. NASA piloted-simulator-validated (NTRS 20140005797, TM 2016) but **never shipped in a consumer/training tool.** Distinguishes the tool intellectually. For instructors: teaches that envelopes aren't static — they shrink dynamically with current state, control authority, weight, damage.

**Theoretical basis:** Hamilton-Jacobi reachability. From a trim state `x₀`, the forward-reachable set at time T is the set of states reachable under any admissible control. Backward-reachable from `x₀` is the set of states from which trim is recoverable. Their intersection is the "safe maneuvering envelope" — where you can both go and come back from. Lombaerts (NASA Ames/Langley, AIAA GNC 2013), Tang/Tomlin (Stanford SAA 2023). Computed traditionally as a level set of a value function; modern approaches use neural-network surrogates.

**What the user sees:**
- Drawer toggle: "Safe Maneuvering Envelope (β)"
- When enabled: a translucent shaded region inside the static envelope showing the dynamically-reachable bow-tie from current state
- A slider in the drawer for "Look-ahead time" (0.5 s — 5 s); the bow-tie shrinks/grows accordingly
- Hover the shaded region → tooltip explaining the concept and citing Lombaerts NTRS 20140005797

**Implementation sketch:**
- Option A — analytic approximation: use `Ps`-based bounds. Forward-reachable = states where `|delta_Ps × T_lookahead| < kinetic_energy_remaining`. Approximate but fast and explainable.
- Option B — Monte Carlo: sample control inputs over the look-ahead window, integrate aircraft equations of motion (we already have the energy equations), collect reachable states, take convex hull. Slower but more faithful.
- Option C — full HJ reachability: implement a value-function solver in WebGPU. Most rigorous but a real research project.
- Recommend **Option A for v1**, **Option B as Phase 5W-2** if A doesn't look right.

**Risk:** "We invented a reachable set" is intellectually exciting but the GA audience may not care about look-ahead semantics. Worth a 1-paragraph in-app "What am I looking at?" explainer.

**Files touched:** new `core/reachability.py`; `callbacks/figure.py`; `layouts/desktop.py` (drawer toggle + slider); new `tests/test_reachability.py`.

### Phase 5X — Probabilistic Envelope Shading

**Status:** pending. **Priority:** medium. **Effort:** medium.

**Synopsis:** Replace the binary envelope boundary with soft-edge contour bands at 10/50/90 % confidence, computed by Monte Carlo over the existing modifier inputs (weight, OAT, altimeter, prop condition, CG).

**Pedagogical motivation:** Genuine educational insight — envelopes aren't binary. Wind, weight uncertainty, atmospheric variability all *soften* the practical envelope. Pilots who fly at "exactly the corner" are actually flying on a probability distribution centered there. Helsen/Lombaerts JGCD 2020 supplies the method.

**Theoretical basis:** Helsen et al., *Probabilistic Flight Envelope Estimation*, JGCD doi 10.2514/1.G004193. Monte Carlo over input uncertainty distributions (weight ± 50 lb, OAT ± 5°C, CG ± 0.5 inch, etc.) → ensemble of envelope curves → density-render the boundary band.

**What the user sees:**
- Drawer toggle: "Probabilistic boundary"
- When on: the lift-limit + load-limit lines render as **three nested lines** instead of one — outer (90 % CI), middle (median), inner (10 % CI). Light shading between them.
- Slider in the drawer for "Uncertainty band width" (tight / normal / wide) — scales the input sigma
- State Panel gets a "± uncertainty" annotation next to Vs1g and Va

**Implementation sketch:**
- New helper in `core/calculations.py`: `compute_envelope_ensemble(ac, base_inputs, n_samples=200, sigmas={...})` — runs the existing envelope computation N times with sampled inputs, returns array of curves
- Render via Plotly's `fill="tonexty"` between the 10 % and 90 % curves with semi-transparent fill matching the trace color
- Caching: the ensemble is expensive (~200× the per-render cost). Cache keyed on (aircraft, base_inputs) so it only recomputes when an input changes structurally
- Tests: assert ensemble width is monotonic in input sigma

**Risk:** Performance. 200 Monte Carlo samples × the per-aircraft envelope calc could be slow. Mitigation: cache + only re-render the ensemble when probabilistic mode is enabled.

**Files touched:** `core/calculations.py`, `callbacks/figure.py`, `layouts/desktop.py` (drawer toggle + sigma slider), `tests/test_probabilistic.py`.

### Phase 5Y — AI-Discovered Policy Heatmap

**Status:** pending. **Priority:** low (data-gated). **Effort:** large.

**Synopsis:** Overlay a heatmap showing where a trained RL air-combat policy spent time in the (IAS, turn rate) plane, contrasted with where human pilots typically operate.

**Pedagogical motivation:** The DARPA AlphaDogfight Trials (2020) and ACE program (2023) produced policies that defeat human F-16 WIC graduates by exploiting *non-obvious energy corners* — pitch-back recoveries, lag-pursuit energy preservation, corner-velocity arrivals as emergent behavior. Showing where RL discovered usable envelope vs where humans hesitate is a wow-tier educational feature, but it requires public trajectory data which Lockheed Martin's PHANG-MAN (Pope et al., arXiv:2105.00990) and Heron Systems have not released.

**Theoretical basis:** Pope, Ide et al., *Hierarchical Reinforcement Learning for Air-to-Air Combat*, arXiv:2105.00990 (2021). The "Shaw-energy" reward term explicitly rewards higher specific energy than the opponent. Selmonaj et al., *Hierarchical Multi-Agent RL for Air Combat Maneuvering*, arXiv:2309.11247 (2023).

**What the user sees:**
- Drawer toggle: "AI policy density (experimental)"
- A heatmap shaded region over the existing envelope showing operational density from a trained policy's flight log
- Caption: "Heron Systems winning policy, AlphaDogfight Trial 5, Aug 2020"
- Hover region → "The agent spent 47 % of engagement time in this corner. Human aces spent 11 %."

**Implementation sketch:**
- Gated on access to actual RL trajectory data. Options:
  1. Train a small RL agent on a simplified air-combat environment (e.g., the JSBSim or PyFlyt simulators) — most accurate, weeks of work
  2. Use public DARPA ACE telemetry if/when released
  3. Synthetic: hand-construct a "typical AI policy" heatmap from Pope et al.'s paper figures
- For pedagogical purposes, (3) is acceptable as a first pass: digitize Pope's Figure 9 (operational density during winning engagements), normalize to our axes
- Render as a `go.Heatmap` with `colorscale="Hot"` at 20 % opacity
- Surface a clear "based on published academic data, not live training" caveat

**Risk:** Defensibility. If the heatmap looks wrong to a knowledgeable viewer, the rest of the tool's credibility takes a hit. Mitigation: caveat heavily, cite the specific source paper figure, and treat this as a "research preview" feature with a `beta` flag.

**Files touched:** `data/ai_policy_heatmaps/heron_2020.json` (digitized data); `callbacks/figure.py`; `layouts/desktop.py`.

### Phase 5Z — Mission Profile + Constant-Energy h-V Diagram

**Status:** pending. **Priority:** medium. **Effort:** small-to-medium.

**Synopsis:** Add a second chart tab showing the **altitude vs IAS** plane (Rutowski/Boyd's *other* diagram) with constant-energy curves and a Ps-contour grid. This is the chart the AFH Ch 4 actually teaches.

**Pedagogical motivation:** Currently we only render the maneuver doghouse (turn-rate vs IAS). Rutowski's original 1954 diagram and Boyd's complementary chart in 1966 were both h-V plots — altitude vs IAS, with curves of constant total energy (`E = h + V²/(2g)`) and Ps contours showing climb capability. The AFH Ch 4 (2021) uses *exactly this* framing for its qualitative pedagogy. We should ship the chart the FAA is teaching.

**Theoretical basis:** Rutowski 1954, Figure 3. Boyd/Christie/Gibson 1966, Vol I §III "The h-V Diagram." FAA AFH Ch 4 (2021), pp. 4-3 to 4-7.

**What the user sees:**
- New tab in the chart area: "Maneuver Doghouse" (current) / "Energy Map (h-V)" (new)
- The new tab renders altitude (Y) vs IAS (X), with:
  - Stall boundary (left edge)
  - Mach buffet / Vne boundary (right edge — for our GA fleet usually a vertical line at Vne)
  - Service ceiling boundary (top)
  - **Constant-energy curves** as light gray dotted hyperbolas where `h + V²/2g = constant`. Labels at 1000, 3000, 5000, 10000, 20000 ft of energy.
  - **Ps contour map** (using the existing Ps machinery, but in the (h, V) plane this time)
  - Current operating point as an orange `X` marker
- Tab switch shortcut: `h` for h-V, `m` for maneuver doghouse

**Implementation sketch:**
- New file `callbacks/figure_hv.py` — produces a separate Plotly figure
- Adds an `em-graph-hv` `dcc.Graph` to the chart area (hidden by default, swapped in via tab)
- Tab control in the chart-area header — `dbc.Tabs` or custom chip buttons
- The Ps computation reuses existing machinery: at each (h, V) grid cell, compute thrust-available and drag at trim (n=1), produce Ps. Same physics as the doghouse but with different free variables.
- Tests: at sea level + V=100 KIAS, energy curve should pass through (10000 ft, 27 KIAS) approximately (since `100²/2g ≈ 336 ft` of KE, so at 10000 ft the same energy is at much lower speed)

**Risk:** UX complexity. Adding a tab is good (less crowded than two chart panes) but introduces a navigation choice. Default-to should be the doghouse since that's what we've been polishing.

**Files touched:** new `callbacks/figure_hv.py`; `layouts/desktop.py` (chart-area tabs); `assets/styles.css` (tab styling); new `tests/test_hv_diagram.py`.

### Phase 5 Future Feature Lab — priority summary table

| # | Feature | Original use case | New since Boyd? | Effort | Priority | Status |
|---|---|---|---|---|---|---|
| 5U | Comparative aircraft overlay | Boyd 1966 — F-4C vs MiG-21 | No (Boyd's original) | medium | **HIGHEST** | pending |
| 5V | KE/PE split + recovery arrows | FAA AFH Ch 4 (2021) → quantitative | Partly (Stepanyan 2017) | small | HIGH | pending |
| 5W | Safe Maneuvering Envelope (reachable set) | NASA Lombaerts 2013-2017 | YES — never shipped in consumer tool | large | medium | pending |
| 5X | Probabilistic envelope shading | Helsen/Lombaerts JGCD 2020 | YES | medium | medium | pending |
| 5Y | AI-discovered policy heatmap | DARPA AlphaDogfight 2020 / ACE 2023 | YES (gated on data) | large | low | pending |
| 5Z | Mission profile + h-V diagram | Rutowski 1954 / AFH Ch 4 (2021) | No (Rutowski's original) | small-medium | medium | pending |

**The 2026-05-14 lean: 5U + 5V together.** They're philosophically + pedagogically the right next push, both ship in one focused session, and together convert the tool from "competent Boyd-era envelope visualizer" to "the only teaching tool that does what Boyd actually built EM for *and* speaks the language the FAA is now teaching GA pilots."

---

## Execution Log

Append one line per session below, dated.

- 2026-05-12 — Plan drafted (this document).
- 2026-05-12 — Decisions D1–D6 locked. Phase 0 kicked off.
- 2026-05-12 — D7 added (project-wide rename: aeroedge → tallyaero). All source files, docs, env vars, copyright strings, JS identifiers, and HTML meta updated. `aeroedge_tracker.py` deleted entirely (D3). Server restarts cleanly on the renamed codebase (HTTP 200 at :8051, meta author = "TallyAero").
- 2026-05-12 — Phase 0 progress:
  - **Deps pinned** (`requirements.txt` + `requirements-dev.txt`); `pydantic 2.9.2`, `jsonschema 4.23.0`, `pytest 8.3.3`, `pytest-snapshot`, `pip-tools` installed.
  - **`Makefile`** with test / run / snapshot / freeze / kill-server / clean targets.
  - **`conftest.py`** added so pytest discovers `core/` without an editable install.
  - **`tests/test_core.py`** converted to pytest. 61 tests pass — round-trips, edge cases (V=0, q=0, near-90° bank, empty stall data, mismatched arrays, stratosphere floor), and the Ps dimensional regression (V·sin γ, not g·sin γ).
  - **`core/schema.py`** — full Pydantic v2 model. Strict cross-field invariants (Vne > Vno, max_weight ≥ empty_weight, CG range ordered, multi-engine ⇒ Vmca + Vyse required, CL_max monotonic across flaps, aerobatic G ≥ normal G with the "0 = not certified" sentinel).
  - **`tests/test_jsons.py`** validates every aircraft against the schema and writes `docs/aircraft_data_triage.csv`.
- 2026-05-12 — Phase 0 triage results (110 aircraft):
  | Finding | Count | Phase to fix |
  |---|---|---|
  | Schema validation failures | **0** | n/a |
  | Missing `confidence` field | 110 | Phase 2 |
  | Missing `sources[]` citation | 110 | Phase 2 |
  | Placeholder `T_static_factor = 2.6` | 102 | Phase 2 (real prop-thrust modeling per aircraft) |
  | Aerobatic G_limits = 0 (not-certified sentinel) | 2 (Seneca, Seminole) | n/a — semantically correct |
  | `arcs` fully null | 1 (Pitts S-1C-TB) | Phase 2 data cleanup |
  | CL_max / stall_speeds missing entries for declared flaps | 1 (Pitts S-1C-TB) | Phase 2 data cleanup |
- Final Phase 0 step 1–3 test status: **172 passed, 1 skipped**.
- 2026-05-12 — **Phase 0 closing steps completed:**
  - **Logging:** `core/logging_setup.py` introduced. `dprint()` becomes a back-compat shim that routes to `tallyaero.em` logger. All 4 `print("[BOOT]...")` calls converted to `log.info(...)`. Controlled via `TALLYAERO_LOG=DEBUG|INFO|WARNING|ERROR` env var. No call-site changes — Phase 1 will rip out `dprint()` when it touches `app.py`.
  - **Boot-time side effect extracted:** `init_data(aircraft_folder, airports_path)` is the new public API in `core/aircraft_loader.py`. It mutates the module globals in place (so `from core import AIRCRAFT_DATA` callers continue to see updates). Backward-compat auto-init at module bottom, gated by `TALLYAERO_NO_AUTO_INIT` env var. New `tests/test_loader.py` (4 tests) verifies idempotency, in-place mutation, and that tests can supply a curated `tmp_path` folder.
  - **`prevent_initial_call` audit:** 61 callbacks enumerated. 46 originally protected; 8 added (the aircraft-dependent and maneuver-dependent ones); 7 documented as legitimately firing on initial load (router, browser-width detector, default displays, the sacred `update_graph`). Audit table written to `docs/callback_audit.md`. Final: **54/61** have `prevent_initial_call=True`.
  - **Physics-scenario snapshots:** `tests/test_scenarios.py` covers three canonical configurations (172P @ 4000 ft / +20 °C / 2300 lb / clean / 100% power, Baron 58 @ 8000 ft / OEI feathered, CAP 232 @ SL ISA / aerobatic). Each scenario serializes density, vs1g, corner velocity, HP-at-altitude, and a 60-point envelope (V, n, ω, R, Ps, T, D) into a JSON snapshot. `make snapshot` regenerates after a deliberate physics change; default `make test` fails on any drift. Snapshots stored under `tests/snapshots/test_scenarios/`. Spot-check: 172P @ 2300 lb yields corner velocity 108.2 kt (analytic 55·√3.8 = 107.2 kt) — within rounding.
- **Phase 0 ship gate cleared.** Final test status: **180 passed, 1 skipped** (overlay-tool drift check pending Phase 7). Server still HTTP 200, all UI strings show `TallyAero`.
- 2026-05-12 — **Phase 1 partial — 1a, 1b, 1f shipped:**
  - **Phase 1a:** `calculate_vmca` (~130 lines) → `core/vmca.py`; `calculate_dynamic_vyse` (~95 lines) → `core/vyse.py`. Re-exported through `core/__init__.py`. `app.py` 5,975 → 5,675. Pure-function relocation, no behavior change; physics snapshots (Baron 58 OEI scenario in particular) still match.
  - **Phase 1b:** `callbacks/` package skeleton with `register_all(app)` pattern.
    - `callbacks/ui_toggles.py` — 6 callbacks migrated (`toggle_airspeed_units`, `toggle_prop_condition`, `enforce_single_standard`, `toggle_acs_standard_visibility`, `sync_units_toggle`, `expand_collapse_all`).
    - `callbacks/navigation.py` — 4 callbacks migrated (`go_to_edit_page`, `go_to_main_page`, `load_last_saved_on_nav`, `get_browser_width`).
    - `app.py` calls `register_all(app)` after layout assignment. 5,675 → 5,566. Callback count in `app.py`: 61 → 51.
    - `tests/test_callbacks.py` (3 tests) verifies the `register(app)` contract and that `register_all` invokes every submodule.
  - **Phase 1f:** `pyproject.toml` added — declares the package layout, pins Python 3.11+, moves `pytest` config out of Makefile into the standard `[tool.pytest.ini_options]`, filters spurious plotly/pydantic deprecation warnings.
- **Phase 1 test status: 183 passed, 1 skipped.** Server HTTP 200.
- **Phase 1 work remaining (deferred to next session):**
  - **Phase 1d** — `edit_aircraft` CRUD (~1,100 lines, app.py:~3475 onward + `edit_aircraft_page.py`) into `layouts/edit_aircraft.py` + `callbacks/edit_aircraft.py`.
  - **Phase 1e** — `desktop_layout` / `mobile_layout` (~570 lines) into `layouts/desktop.py` + `layouts/mobile.py`. Phase 5 collapses the dual-tree into one responsive layout; this step just relocates.
- 2026-05-12 — **Phase 1c shipped — the surgical move:**
  - AST dependency analysis showed `update_graph` is astonishingly self-contained — 21 of 22 module-level references resolve to imports (numpy, plotly, dash, all of `core/`), with `app` (for the decorator) being the only true app.py dependency.
  - **Methodology:**
    1. *Discover* — `update_graph` spans app.py lines 1258 (decorator) → 3015 (body end), 1,758 lines.
    2. *Categorize* — 10 "unknown" names from naive AST analysis were function-scoped `from math/numpy/plotly import …` and locals (`color`, `chandelle_ias_start`, `show_annotations`) — all stay with the function body.
    3. *Extract* — Python script sliced the lines, built `callbacks/figure.py` with a module-level `update_graph` plus a `register(app)` wrapper that applies the decorator. No re-indentation of the function body — only the 28 decorator args got re-indented from col 4 → col 8 for cosmetics.
    4. *Wire* — `callbacks/__init__.py` adds `figure` to `register_all`. `app.py` lines 1258–3015 replaced with a single-line comment.
    5. *Verify* — 4-layer gate:
       - Both files parse via `ast.parse`.
       - `from callbacks import figure` imports without error.
       - `pytest tests/` → **183 passed, 1 skipped.**
       - Physics-pinned snapshots (`test_scenarios.py`) for 172P, Baron 58 OEI, CAP 232 all **identical** — proves no math drift.
       - Dash `/_dash-dependencies` confirms `em-graph.figure` callback registered with **all 28 inputs** intact.
       - Server HTTP 200 at `:8051`.
  - **app.py 5,566 → 3,808 lines** (−1,758). Total moved this session across 1a/1b/1c: **5,975 → 3,808 = −2,167 lines (−36%).**
  - `callbacks/figure.py` is 1,813 lines (the largest single file in the project — and that's by design, per the "update_graph is sacred" rule in the Master Prompt).
- 2026-05-12 — **Phase 1d shipped — aircraft-editor CRUD relocated:**
  - **Setup:** `log_feature` no-op shim promoted from `app.py` to `core/logging_setup.py` so the edit module imports it cleanly. New `layouts/` package created; `edit_aircraft_page.py` moved to `layouts/edit_aircraft.py` (the original is deleted). `app.py` switched to `from layouts import edit_aircraft_layout`.
  - **AST dep analysis** of app.py:1695–3353 (the edit block): 22 `@app.callback`-decorated functions + 1 helper (`_build_single_engine_limits`). 16 normal imports. Only 2 references to app.py module-level state: `app` (decorator target) and `log_feature` (now in core).
  - **Surgical move:** Python script sliced the 1,659-line block, indented every non-blank line by +4 spaces, wrapped in `def register(app):`, prepended a clean import header. All 22 callbacks became nested functions inside `register(app)`. **One scoping gotcha caught and fixed:** 9 stray mid-block `from dash import Output, …` and `import copy` statements were re-imports that, when wrapped inside `register()`, caused Python to treat `Output` as a local variable for the entire function (UnboundLocalError on first use). The 9 lines were commented out in place (with `# hoisted to module top in Phase 1d`) so the function bodies resolve `Output` from module-top imports as intended.
  - **Verification gate:**
    - `python -c "from callbacks import edit_aircraft; edit_aircraft.register(dash.Dash(__name__))"` → `register() OK`.
    - Full pytest → **183 passed, 1 skipped.**
    - Server HTTP 200 at `:8051`.
    - `_dash-dependencies` → 62 total callbacks; em-graph still 1 callback × 28 inputs; all edit-page outputs (`stored-g-limits.data`, `stored-stall-speeds.data`, `stored-engine-options.data`, `save-status.children`, etc.) wired via the new module.
  - **app.py: 3,808 → 2,152 lines (−1,658).** Cumulative this session across 1a/1b/1c/1d: **5,975 → 2,152 = −3,823 lines (−64%).**
  - `callbacks/edit_aircraft.py` is 1,696 lines (one wrapper function around 22 nested callbacks + 1 helper).
- 2026-05-12 — **Phase 1e shipped — layouts decomposed:**
  - AST dep analysis: `desktop_layout` + `mobile_layout` + `em_diagram_layout` reference **only 4 imports** (`AIRPORT_OPTIONS`, `dbc`, `dcc`, `html`) and 2 internal cross-refs (em_diagram dispatcher → desktop/mobile). Zero unknowns. **Cleanest extraction of the entire phase.**
  - **Move:** Python script extracted `app.py:233–805` (573 lines) into:
    - `layouts/desktop.py` — 345 lines (header + `desktop_layout()` verbatim)
    - `layouts/mobile.py` — 257 lines (header + `mobile_layout()` verbatim)
    - `layouts/__init__.py` rewritten — re-exports all three layout builders plus the `em_diagram_layout(is_mobile=False)` dispatcher
  - **Wire:** `app.py` switched to `from layouts import edit_aircraft_layout, em_diagram_layout`. The `display_page` callback now resolves both names from `layouts/`.
  - **Verification:**
    - All four files (`app.py`, `layouts/{__init__,desktop,mobile}.py`) parse via `ast.parse`.
    - `from layouts import desktop_layout, mobile_layout, em_diagram_layout` returns `Div` from each — pure-function contract confirmed.
    - Full pytest → **183 passed, 1 skipped.**
    - Server HTTP 200, zero errors in log.
    - **Force-fired `display_page` callback** via direct POST to `/_dash-update-component` → returned a fully-rendered DOM tree (banner Div → Img → "tallyaero.app" anchor). End-to-end live wiring verified.
    - `_dash-dependencies` → 62 callbacks, em-graph still 1 × 28 inputs.
  - **app.py: 2,152 → 1,581 lines (−571).** Cumulative this session across 1a/1b/1c/1d/1e: **5,975 → 1,581 = −4,394 lines (−73.5%).**
  - **18 callbacks remain in app.py** — mostly main-page UI plumbing (aircraft selection cascade, environment inputs, weight, modals, export). These migrate next as `callbacks/main.py` etc.
- 2026-05-12 — **Phase 1 fully shipped — final slim-down complete:**
  - **Round 1 — bulk extraction:** Python script classified the remaining 28 callbacks into 6 thematic modules by function name and primary output id. Single-pass extraction wrote:
    - `callbacks/main.py` (431 lines) — aircraft selection cascade, dropdowns, CG slider, weight, maneuver-options renderer (11 callbacks)
    - `callbacks/environment.py` (119 lines) — altitude / OAT / altimeter / airport defaulting (4 callbacks)
    - `callbacks/export.py` (298 lines) — PDF + PNG generation, `get_summary_text` helper (3 items)
    - `callbacks/modals.py` (353 lines) — disclaimer, terms, help-bubble routing, ghost forwarding, `HELP_CONTENT` data (4 items)
    - `callbacks/overlays.py` (90 lines) — multi-engine sync, mobile sidebar (5 callbacks)
    - `callbacks/navigation.py` (106 lines) — added `display_page`, `reload_aircraft_on_return`, `set_last_selected_aircraft_on_load` (3 callbacks)
  - **One classifier bug caught:** `get_summary_text` (a helper with no `@app.callback`) caused the decorator-walkback loop to grab the `@app.callback` of the function above it (`render_maneuver_options`), so render_maneuver_options ended up duplicated in both `main.py` and `export.py`. Caught by the dependency-graph duplicate audit (`2× maneuver-options-container.children`). Removed from export.py.
  - **One latent bug caught:** `send_from_directory` was used by `serve_robots` / `serve_sitemap` but never imported in `app.py` — the original import sat inside a callback body that got swept into `callbacks/edit_aircraft.py` during Phase 1d. The rewrite added `from flask import send_from_directory` at module top. **robots.txt and sitemap.xml now return HTTP 200 instead of 500.**
  - **Round 2 — `app.py` rewritten clean:** new 215-line file with: docstring → imports → app/server init → `app.index_string` (verbatim) → `app.layout` (Stores + 4 Modals verbatim) → clientside callback for screen-width → `open_browser`/`serve_robots`/`serve_sitemap` helpers → `register_all(app)` → `__main__`. No stranded imports, no `# Phase 1g …` comment graveyard.
  - **Verification gate:**
    - `ast.parse` clean on every file in `callbacks/`, `layouts/`, `core/`, and `app.py`.
    - Full pytest → **183 passed, 1 skipped.**
    - Server HTTP 200, zero errors in log.
    - `_dash-dependencies` → **62 callbacks** (correct count after de-dup), em-graph still 1 × 28 inputs.
    - `display_page` POST → full DOM tree returned.
    - `/robots.txt` and `/sitemap.xml` → **HTTP 200** (the latent bug fix).
- **Phase 1 ship gate cleared.**
  - **`app.py`: 5,975 → 215 lines (−96.4%).**
  - Source-tree topology now matches the architecture in the Master Prompt:
    ```
    app.py                   215   thin entry point
    core/{…}                 ~1.7k physics SoT, schema, logging, OEI math, data init
    layouts/{desktop,mobile,edit_aircraft}.py  1.1k  DOM trees
    callbacks/figure.py      1,813 sacred chart callback
    callbacks/edit_aircraft.py 1,696 the CRUD surface
    callbacks/{main,export,modals,overlays,environment,navigation,ui_toggles}.py  1.5k
    tests/{core,jsons,callbacks,loader,scenarios}.py  ~1k
    ```
  - **All 9 of the original Phase 1 sub-tasks closed.** Phase 1 → done.
- 2026-05-12 — **Phase 2 scope chosen ("Full mining"), then deferred:**
  - User chose full-mining depth + sourcing for all non-FAA aircraft (EASA, warbirds, homebuilts).
  - **Local-data inventory completed** (re-usable starting point when we resume):
    - `/Users/nicholaslen/Desktop/tallyaero/website/.research-cache/normalized/tcds.json` — 2,256 normalized FAA TCDS records (1,486 aircraft, 876 Small Airplane). Each has `tcdsNumber`, `tcHolder`, `models[]`, `revisionDate`, `pdfUrl`.
    - `/Users/nicholaslen/Desktop/tallyaero/website/.research-cache/raw/tcds-pdfs/` — 52 TCDS PDFs already downloaded (Cessna 150/152/172/182/206/210, Piper PA-28/32/34, Beech Baron, etc.).
    - `/Users/nicholaslen/Desktop/tallyaero/website/.research-cache/raw/TCDS_03312026.accdb` — full FAA TC database (raw, Access).
    - `/Users/nicholaslen/Desktop/tallyaero/z3_dashtwo_OLD/content-pipeline/download_tcds.py` — existing fetcher script (50+ TCDS URLs hardcoded).
    - `/Users/nicholaslen/Desktop/tallyaero/reference/overlay_tools/aircraft_data/` — sibling dataset (115 JSONs, mostly identical with 2 trivial duplicates).
    - **PDF parsing proof:** TCDS 3A12 (Cessna 172) section IX gave Vne=158, Vno=127, Vfe=85, MTOW=2400 lb, fuel=42 gal — our existing 172P JSON matches within rounding. Confirms reconciliation will be high-yield.
  - **Naïve matcher** (manufacturer + model substring) already mapped 50/110 aircraft cleanly. Fuzzier matching + EASA + warbird + homebuilt sourcing rounds it to ~110.
  - **8 sub-tasks scoped** in task list (#23 Phase 2a through #30 Phase 2h): lookup table → parse 52 PDFs → reconcile → download missing → source non-FAA → upgrade thrust model → drag polar refinement → final audit.
  - **Status: deferred.** Resume by activating task #23 — the inventory and matcher prototype are documented; no code committed in this phase yet.
- 2026-05-13 — **Phase 5a–d shipped — visual identity + state panel + token sweep:**
  - **5a Visual identity foundation.** New `assets/tokens.css` (298 lines) ports the entire TallyAero design-token system from `packages/ui/src/web/tokens.css` verbatim (brand blue `#0d59f2`, brand orange `#f27b0d`, sidebar `#0a0e17`, full light/dark/system mode token sets, Inter + Space Grotesk + JetBrains Mono via Google Fonts, three personality presets — standard/sharp/soft). A legacy-alias block at the bottom maps our existing variable names (`--blue-primary`, `--orange-primary`, `--navy-bg`, `--text-dark`, etc.) onto the new TallyAero tokens — every existing class rule in `styles.css` instantly picks up the new colors without touching markup.
  - **5b Component restyle (`assets/zz-em-app.css`, 534 lines).** Sidebar shell, accordion section headers (with the portal-pattern 3px blue left bar on active section), input labels (micro-caps 10px), dropdowns (TallyAero focus rings), buttons (`.btn-primary-orange` / `.btn-primary-blue` with hover lift + spring), sliders (`.rc-slider` with brand-blue handle/track + mono tooltips), number inputs (mono w/ tabular nums), segmented controls (KIAS/MPH, Feathered/Stationary/Windmilling with proper active state), modals (display font on title, subtle border + lg radius), Bootstrap form-checks (brand blue), scrollbar (subtle thin). All targeting existing selectors — zero DOM changes.
  - **5c State Panel.** Six hero-number cards above the chart: WEIGHT, Vs1G, Va, Vne, Vno, CORNER. Space Grotesk 26px tabular numerics in Apple-Health-style cards. Hover lift + 2px brand-blue accent rail. Color-flag states: `.flag-danger` (red border, weight > MTOW), `.flag-warning` (corner velocity capped by Vne). New `callbacks/main.update_state_panel` callback wired to `aircraft-select / config-select / category-select / stored-total-weight / unit-select`. Mobile hides the panel via media query so the chart owns the small viewport. Hardware-verified: Cessna 172P @ 2,300 lb → Vs1G 55 kt, Va 107 kt (= 55·√3.8 ✓), Vne 160 kt, Vno 129 kt, Corner 107 kt.
  - **5d Hex-literal sweep.** 122 of 132 hex codes in `styles.css` migrated to `var(--ta-*)` tokens via a two-pass scripted rewrite. Surfaces (15× `#f7fafc` → `--ta-surface-primary`), text grays (8× `#1a202c` → `--ta-text-primary`, 9× `#a0aec0` → `--ta-text-tertiary`, etc.), borders, warning amber family, brand blue (2× old `#2980b9` → `--ta-brand-blue`), brand orange (`#e65c00` → `--ta-brand-orange`), Bootstrap status (`#dc3545` → `--ta-danger`, `#28a745` → `--ta-success`). 11 bespoke literals remain — mostly accents (`#1a365d`, `#5a6678`, etc.) that get triaged in Phase 5e when we wire dark mode.
  - **Bonus from user request:** Removed the broken-image header banner and the persistent warning banner from both `desktop_layout()` and `mobile_layout()`. Legal copy lives in the Disclaimer + Terms of Use modals (still wired). Layouts are visually cleaner.
  - **Verification gate:**
    - `ast.parse` all touched files clean.
    - Full pytest → **183 passed, 1 skipped.**
    - Server HTTP 200, zero errors in log.
    - `_dash-dependencies` confirms new `state-panel.children` callback (5 inputs).
    - Force-fired `update_state_panel` POST returns six valid cards with correct physics.
    - Force-fired `display_page` POST returns full DOM after header removal.
- 2026-05-13 — **Phase 5e shipped — hex sweep complete + dark-mode toggle live:**
  - **Final hex sweep.** The 11 remaining bespoke literals in `styles.css` are now `var(--ta-*)` tokens. Context-aware mapping: `#f5f5f5` / `#e0e0e0` → surface tokens; `#666` / `#5a6678` → text tokens; `#fef3c7` / `#92400e` → `--ta-warning-bg` / `--ta-warning-text`; `#68d391` → `--ta-success`; `#e53e3e` → `--ta-danger`; `#e8f4f8` → `--ta-info-bg`; brand gradient `linear-gradient(#1a365d, #2d4a7c)` → `linear-gradient(var(--ta-brand-blue-dark), var(--ta-brand-blue))`. **`styles.css` has zero hex literals.** Pure token-driven.
  - **Dark-mode toggle.** Three-part wiring:
    1. **Pre-paint script** in `app.index_string` (`<head>` synchronous block) reads `localStorage.tallyaero_theme` and applies `data-theme` to `<html>` before Dash renders — prevents flash of unstyled content.
    2. **Three-button segmented toggle** (`AUTO | LIGHT | DARK`) in the quick-links bar (desktop), styled with TallyAero treatment.
    3. **Clientside callback** in `app.py` reads the click context, updates `data-theme`, persists to `localStorage`, mirrors active state via `className` on each button. `dcc.Store(id="theme-pref", storage_type="local")` keeps the value in sync.
    - `AUTO` follows the OS via `prefers-color-scheme: dark` matchMedia; `LIGHT` and `DARK` are explicit.
    - Theme transitions: body/modals/sidebar fade between modes with `--ta-motion-base` 200ms easing.
  - **Chart caveat:** Plotly's `paper_bgcolor` / `plot_bgcolor` are hardcoded in `update_graph` (currently `#f7f9fc`). The chart **wrapper** goes dark via CSS, but the chart **interior** stays light. Phase 5g wires `paper_bgcolor` per-render to the current theme.
  - **Verification:**
    - Server HTTP 200, zero errors.
    - 64 callbacks registered (was 63; +1 for theme-pref).
    - Early-paint script present in served HTML (3 references to `tallyaero_theme`).
    - Full pytest → **183 passed, 1 skipped.**
    - Click `DARK` button → `data-theme="dark"` on `<html>` → tokens flip instantly → body / modals / sidebar / inputs all repaint in dark palette → reload preserves the choice via localStorage.
- 2026-05-13 — **Phase 5g shipped — chart palette wired to theme:**
  - **New module** `core/plotly_themes.py` (86 lines). Exports `get_palette(theme_pref)` returning a `Palette` TypedDict mirror of the `--ta-*` tokens (paper_bg, plot_bg, text, title, fg, muted, grid, axis_line, tick, annotation_bg/text). Light + Dark variants. Server-side resolution treats `system` as light (the client-side early-paint script handles OS preference at the HTML layer).
  - **`update_graph` extended** to accept a 29th input — `theme-pref.data` — and resolves a palette at the top of the function (`from core import get_chart_palette`). The two `fig.update_layout` blocks were rewritten to read every structural color from `palette[...]`:
    - `paper_bgcolor`, `plot_bgcolor`, `font.color`, `title.font.color`
    - `xaxis/yaxis`: `gridcolor`, `linecolor`, `tickcolor`, `zerolinecolor`, `tickfont.color`, `title_font.color`
    - `legend`: `bgcolor`, `bordercolor`, `font.color`
  - **Structural-color sweep inside `update_graph`:** 5× `color="black"` (G-limit boundary, load-limit annotations) → `palette["fg"]`; 4× `color="gray"` (Ps contour lines, annotations) → `palette["muted"]`. Brand/signal colors (stall red `#DC143C`, Vyse blue `#00BFFF`, corner orange, energy green) intentionally **not** swept — pilots learn those mappings and they stay stable across themes.
  - **Initial chart bg** in `layouts/desktop.py` + `layouts/mobile.py` set to `rgba(0,0,0,0)` (transparent) so the surrounding CSS card shows through until `update_graph` paints theme-aware colors on first input. No "flash of light chart" on dark-mode reload.
  - **Verification:**
    - `em-graph` callback now has **29 inputs**, last one `theme-pref.data`.
    - Force-fired with `theme_pref="dark"`: paper_bgcolor `#0a0e17`, plot_bgcolor `#161e2d`, font.color `#f1f5f9`, title.color `#3B82F6` (brand-blue-light), gridcolor `#222f49` — all match the dark palette. **Chart is now fully theme-coherent.**
    - Full pytest → **183 passed, 1 skipped.**
    - Server HTTP 200, zero errors.
  - **Note on physics-snapshot tests:** they don't go through `update_graph` (they test the physics layer directly), so they're unaffected by the theme palette change. Safe.
- 2026-05-13 — **Phase 5 polish iteration shipped** (multiple small rounds in one user-driven session):
  - **Top-bar restructure.** Removed broken-image header banner; removed warning banner (Disclaimer + Terms modals carry the legal copy). Removed Report Issue and Maneuver Overlay Tool links. Contact TallyAero now `mailto:info@tallyaero.com`.
  - **PNG/PDF moved** from in-graph toolbar into a new `.export-toggle-group` segmented control in the quick-links bar, sized identically to the `AUTO|LIGHT|DARK` theme toggle (unified selector, `min-width: 48px`, `height: 26px`, fixed line-height, `box-sizing: border-box`). Orange accent (vs blue for theme) signals action verb.
  - **Replaced redundant CORNER state-panel card** with **+G LIMIT**. Corner velocity = Va analytically for GA aircraft — the cards were duplicates. +G LIMIT shows current positive structural G; turns green-flagged in Aerobatic category at ≥ 4.5 G.
  - **Dropdown visibility** in dark mode fixed across THREE class-naming conventions (react-select v1 `.Select-option`, v5 CSS-in-JS `[class*="select__option"]`, and the `react-virtualized-select` flavor used by the 16k-row airport list — `.VirtualizedSelectOption`/`Focused`/`Selected`). Legacy `.Select-menu-outer { background-color: white !important }` rules in `styles.css` (higher specificity, were winning) rewritten to `var(--ta-surface-elevated)`.
  - **Selected-value blue chip** stripped: react-select v5 in clearable mode renders the single value in a multi-value-style container; default chip background was bleeding through. Forced `background: transparent !important` across `.Select-value`, `[class*="select__single-value"]`, `[class*="select__value-container"]`, `[class*="select__multi-value"]`.
  - **Slider tooltips** in dark mode fixed: bg was `--ta-text-primary` (flips with theme — light in dark mode) but text color was unset, so default light text on light bg = invisible. Added explicit `color: var(--ta-surface-secondary)` so the pair is always inverted/readable. Plus `font-weight: 600`, `min-width: 28px`, matching arrow color.
  - **Chart `hoverlabel`** wired to the palette (Phase 5g completion): `bgcolor=palette["annotation_bg"]`, `bordercolor=palette["grid"]`, `font.color=palette["text"]`, `font.family="JetBrains Mono, Inter, sans-serif"`. Plotly tooltips no longer flash white in dark mode.
  - **Accordion section dividers** now visible — added `border-bottom: 1px solid var(--ta-border-primary)` to `.accordion-item`. Subtle in dark mode (`#222f49` line on `#0a0e17` bg), crisp in light mode (`#e2e8f0` on `#f8fafc`).
  - **`.segment-btn.active`** was hardcoded `background-color: white` (KIAS/MPH, prop conditions toggles) — flipped to `var(--ta-brand-blue)` so it matches the rest of the active-state language.
  - **Edit-aircraft page accordion** theme-wired (separate from sidebar accordion — uses `#edit-accordion` id), card-style with rounded borders, brand-blue active section.
  - **Misc dark-mode coverage:** quick-links bar bg, legal-links footer + hover, help-bubble (`?`) icons (with brand-blue hover fill), mobile config bar, Bootstrap form-switches (brand-blue when checked), generic `.card`, resize-handle (brand-blue on hover).
  - **Two import regressions** caught in `callbacks/export.py` (missing `ctx`, `dash`, `go`, `pio`, `send_file`), one in `environment.py` (`dash`), one in `main.py` (`math`), one in `navigation.py` (`html`). All Phase 1g auto-extraction misses; all fixed and an AST audit confirmed every callback module imports cleanly.
  - **Clientside callback architecture** moved from inline-string form to `ClientsideFunction(namespace, function_name)` referencing `assets/clientside.js`. Resolves the `Cannot read properties of undefined (reading 'apply')` Dash 3 dispatcher bug with State + multi-output inline strings.
  - **Status:** Server HTTP 200, 183 tests pass, 64 callbacks registered.
- 2026-05-13 — **Phase 2a shipped — TCDS lookup table + provenance fields:**
  - **Matcher.** New `data/scrapers/tcds_matcher.py` builds a (fuzzy + manual-override) mapping from our 110 aircraft names to authoritative TCDS records. Uses `tcds.json` (2,256 normalized FAA records) for the fuzzy half; a hand-curated `MANUAL_OVERRIDES` dict for the rest. Fuzzy match scores by (manufacturer-alias overlap + model-token containment) and prefers the most-recently-revised candidate. Manufacturer aliases (`Cessna ↔ Textron`, `Beech ↔ Textron`, `Champion ↔ Bellanca ↔ ACA`) catch legal-entity reissues.
  - **Result: 110/110 mapped** — 75 manual overrides + 35 fuzzy hits, **zero unmatched**. Distribution:
    - **71 FAA TCDS** (Cessna, Piper, Beech, Mooney, Aviat, Maule, Pitts, etc.)
    - **12 EASA** (Diamond DA42 NG, Robin, Socata, Tecnam P2006T, Extra 300/300L/330SC/NG, CAP 232, Zlin Z-242L)
    - **9 Military** (Spitfire/AP1565, Bf 109/Flugzeug Handbuch, Yak-3/Jane's, F4U-4/NAVAIR, F6F-5/NAVAIR, A6M5/Jane's, FW 190/Flugzeug Handbuch, P-51D/AAF 51-127-5, T-6 Texan II/T00012WI)
    - **8 Experimental** (Van's RV-6/8/9A/10/12/14A, GameBird GB1, MX MXS)
    - **6 ASTM F2245 SLSA** (Pipistrel Alpha/Virus, Tecnam P2002, Remos GX, Flight Design CTLS, Evektor SportStar)
    - **4 n/a** (Cessna 162 ASTM, Sukhoi Su-26, Zivko Edge 540, Zlin Savage — manufacturer spec only)
  - **Schema.** `core/schema.py` gained `tcds_number: Optional[str]` and `tcds_holder: Optional[str]` on the `Aircraft` model. Existing `confidence`, `sources[]`, `estimated_fields[]` (added in Phase 0) preserved.
  - **Migration.** `data/scrapers/apply_tcds_mapping.py` walks every aircraft JSON, writes `tcds_number` + `tcds_holder`, appends a `Source` to `sources[]` (deduped by publication string), sets `confidence = "partial"`. Idempotent — safe to re-run.
  - **Outcome of Phase 2a triage:**
    - `confidence not set` warnings: **110 → 0**.
    - `sources[] is empty` warnings: **110 → 0**.
    - Every aircraft now has a citation. Sets up Phase 2c (per-field reconciliation against PDF-parsed values) which can upgrade `partial` to `verified` field-by-field.
  - **Tests:** 183 passed, 1 skipped. Schema accepts the new fields. Sample spot-checks: Cessna 172P → `3A12 Rev 75 (12/21/2007)`, Baron 58 → `3A16 Rev 91 (12/21/2015)`, Spitfire → `AP 1565 Spitfire IX Pilot's Notes (1944)`.
- 2026-05-13 — **Phase 2b shipped — 46 FAA TCDS PDFs parsed into structured JSON:**
  - **Parser** at `data/scrapers/tcds_pdf_parser.py` (~250 lines). Uses `pdftotext -layout` for column-preserved text, then a label-anchored line walker that groups every line under the most recent labeled field (Engine, Engine Limits, Airspeed Limits, Maximum Weight, Fuel Capacity, C.G. Range, Number of Seats, etc.).
  - **Section splitter** handles both the modern `I. Model 172P` form and the older `I - Model PA-16` (hyphen) form. Section continuations like `IV. Model 172D (cont'd)` are folded into the parent section.
  - **TCDS-number derivation** has four fallback regexes covering modern (`3A12`), CAA-era (`A-759`), letter-prefix (`T00012WI`), and EASA (`EASA.A.022`) designators. Failing all that, the filename stem is used verbatim (preserves hyphens — `A-759.pdf` → `A-759`).
  - **Post-processors** extract concrete numbers:
    - `engine_limits` → `{rpm, hp}`
    - `v_speeds_kcas` → `{Vne, Vno, Vfe, Va}` with `{value, unit}` (handles knots / mph / KCAS / KIAS variants; older TCDS use mph)
    - `max_weight_lb` → `{normal_landplane, normal_seaplane, utility_landplane, ...}` — two-pass: (1) `"NNNN lb. (modifier)"` parenthetical form pairs weight with category context, (2) bare `NNNN lb` fallback
    - `fuel_capacity` → `{total_gal, usable_gal}`
    - `seats` → int
    - Multiline raw kept for `cg_range`, `control_surfaces`, `serial_numbers` (Phase 2c can mine deeper)
  - **6 NTSB-derived / vintage-excerpt PDFs auto-skipped** by suffix filter (`-ntsb`, `-vintage`, `-ntsb-excerpt`).
  - **Output:** 46 JSON files at `data/sources/tcds_parsed/<TCDS>.json` covering **248 variant-sections** (one TCDS often covers many model variants — e.g., TCDS 3A12 covers 12 variants of the Cessna 172).
  - **Extraction rates:**
    - **89%** of variants have parsed engine name (223/248)
    - **95%** have max gross weight (237/248)
    - **77%** have fuel capacity (192/248)
    - **59%** have Vne (148/248) — older TCDS often list V-speeds on a separate "Operating Limitations" page rather than the Data Sheet, hence the lower yield
  - **Sample (Cessna 172P, TCDS 3A12 Section IX):** every field extracted matches the actual document — engine `Lycoming O-320-D2J`, 2700 rpm / 160 hp, Vne 158 / Vno 127 / Vfe 85 / Va 99 knots, max_weight `{normal_landplane: 2400, normal_seaplane: 2220, utility_landplane: 2100}`, fuel `{total: 42, usable: 40}` gal, seats 4. **All values match our existing JSON for 172P** — confirms Phase 2c reconciliation will be high-yield.
  - **13 zero-variant TCDS** remain (mostly EASA-format docs + a few FAA stragglers). Phase 2c can fall back to filename-derived metadata for these, or Phase 2e (non-FAA sourcing) can write bespoke parsers per EASA format.
- 2026-05-13 — **Phase 2c shipped — TCDS values reconciled against our 110 JSONs:**
  - **Reconciler** at `data/scrapers/reconcile_tcds.py`. For each aircraft, locate the parsed-TCDS file, pick the most-specific variant, compare 7 fields (Vne, Vno, Vfe, max_weight, fuel_capacity_gal, seats, engine_hp), classify each as `match` / `mismatch` / `silent` / `n/a`, and persist verified field names into `aircraft.verified_fields[]`.
  - **Variant-picker** is three-pass: (1) variant.model ⊆ aircraft name (longest match wins), (2) reverse — aircraft's digit-bearing token ⊆ variant.model (catches "we ship F33, TCDS section is F33A"), (3) token-overlap fallback.
  - **Comparison nuances:**
    - V-speeds normalized to knots (older TCDS use mph — `{value, unit}` carried through from Phase 2b)
    - `Vfe` compared against `min()` of our `Vfe.{takeoff, landing}` dict (TCDS lists the most-restrictive Vfe, which is the landing/full-flap value)
    - Engine HP compared by picking the closest of our `engine_options[*].horsepower` to the TCDS value
    - Tolerances: ±3 kt for V-speeds, ±20 lb for weight, ±1 gal for fuel, exact for seats, ±1 for HP
  - **Parser polish (rolled in):** model-list cleaner now strips non-model strings (`"Bonanza"`, `"4 PCLM"`, `"approved March 25"`, year-only tokens). E.g., TCDS 3A15 variants now read cleanly as `['H35']`, `['F33A']`, `['G36']` instead of including the manufacturer name and configuration notes.
  - **Manual-override fix:** `Bonanza A36` and `Bonanza F33` were on the wrong TCDS (A-777 / 3A21 — those are the older V-tail 35-series and the Cessna 205/210 single, respectively). Corrected to **3A15** (the modern Bonanza F33A/A36/V35B family).
  - **`verified_fields[]`** added to the Pydantic schema as a counterpart to `estimated_fields[]`.
  - **`confidence` upgrade rule:** an aircraft is promoted to `confidence: verified` only when *every* checkable field matched **and** at least 4 checkable fields exist. Avoids false-verified upgrades on aircraft that only have 1–2 comparable fields.
  - **Result across all 110 aircraft:**
    - **3 fully verified** (Cessna 152, 172M, 172P, 172N — closest the matchers got)
    - **6 aircraft with ≥4 verified fields** (172M/172N/172P fully match, plus AA-5B Tiger, Cessna 152, PA-28R-200 Arrow)
    - **26 aircraft with ≥1 verified field**
    - **84 with 0** — mostly aircraft whose TCDS PDF isn't in the local cache (Phase 2d will fix this), or non-FAA aircraft (Phase 2e handles those)
    - **62 field-level matches, 94 mismatches, 47 TCDS-silent fields** recorded in `docs/reconciliation_report.csv` for human review
  - **Tests:** 183 passed, 1 skipped (no schema regressions, no chart regressions).
- 2026-05-13 — **Phase 2d ran into the FAA SPA wall — infrastructure shipped, bulk download blocked:**
  - **Gap analysis:** of our 110 aircraft, 71 cite an FAA/EASA TCDS, of which **35 don't have a local PDF**. List saved at `docs/missing_tcds.json`.
  - **Downloader** at `data/scrapers/download_tcds.py`. Honors a polite 1.5 s delay between requests, custom User-Agent, validates that the response is actually a PDF (rejects HTML wrapper responses).
  - **External blocker:** `drs.faa.gov` migrated to a JavaScript SPA — the `pdfUrl` field in `tcds.json` points at a landing page that needs JS execution to extract the actual PDF. `urllib.request.urlopen()` gets a Bootstrap/Angular HTML shell back. Even with custom UA + redirect-following, no direct PDF.
  - **Legacy mirror list** (`docs/legacy_tcds_urls.json`, 63 entries) was harvested from the old monorepo's `download_tcds.py` (CloudFront / S3 mirrors maintained by Univair / ATP / pegasusaviation / meyersaircraft). Of our 35 missing TCDS, only 4 had a legacy URL, and all 4 are now dead (expired SSL cert on 1A10, 404 on 3A21, HTML wrapper for A00009CH, connection-reset on A19SO).
  - **Net new PDFs from Phase 2d: 0.** Infrastructure landed but bulk download not viable without browser automation. The wall is real and external; documenting it cleanly rather than fighting it.
  - **Paths forward** (cost-ordered):
    - **(a) Manual download** — user opens 31 FAA DRS landing pages in a browser, clicks "Download PDF" on each, drops them into `data/sources/tcds_pdfs/`. The parser + reconciler will pick them up automatically. ~30 minutes of clicking.
    - **(b) Add Playwright** to the dev deps and have it drive the SPA. ~150 MB Chromium download, but it's a one-time fetch that doesn't ship to users (dev-only). Most thorough.
    - **(c) Defer** — current coverage (3 fully verified, 26 partially verified) is enough to keep moving. Phase 2f (thrust model) doesn't depend on more TCDS; Phase 2c can be re-run any time more PDFs land.
  - **Recommendation: (c) defer to Phase 2e/2h.** Pivot to **Phase 2f** (thrust model upgrade) — affects 102 of 110 aircraft and has direct EM-diagram physics value, no FAA dependency.
- 2026-05-13 — **Phase 2f shipped — per-class T_static_factor replaces the 2.6 placeholder:**
  - **Schema:** `core/schema.py:PropThrustDecay` gains `thrust_model: Optional[Literal["piston_fixed_pitch", "piston_constant_speed", "turbocharged", "turboprop"]]`. Backwards-compatible — old JSONs without the field still validate.
  - **Classifier:** `data/scrapers/classify_thrust_models.py` walks the 110 aircraft. Routes through `MANUAL_OVERRIDES` (61 explicit entries — warbirds, turbocharged variants, retractables, LSAs) first, then `infer_thrust_model()` heuristic (name hints → twin/retractable/≥200 HP CS → fixed-pitch fallback).
  - **Defaults per class** (lb static thrust per shaft HP): fixed-pitch 1.85, constant-speed 2.50, turbocharged 2.50, turboprop 3.00. These replace the universal 2.6 that 102 of 110 aircraft carried.
  - **Fleet breakdown:** 56 piston_constant_speed, 48 piston_fixed_pitch, 4 turbocharged (Cessna 210, PA-28R-201T, Mooney M20K, SR22T), 2 turboprop (T-6A/B Texan II).
  - **Files updated:** 110 of 110 `aircraft_data/*.json` rewritten with both `T_static_factor` and `thrust_model`. Idempotent — re-running emits zero writes.
  - **Physics sanity (Cessna 172P @ 100 KTAS):** old thrust 223 lb → new thrust 159 lb (−29%). Matches published 172P cruise-thrust references (~140–160 lb), so the placeholder was 40 % high for fixed-pitch trainers. EM-diagram Ps contours and corner-velocity will shift down accordingly for that category.
  - **Tests:** 3 snapshot files regenerated (`172p_4000ft_warm_day`, `baron58_8000ft_oei_feathered`, `cap232_sl_isa_aerobatic`) — failures were the intended physics delta, not bugs. Full suite **183 passed, 1 skipped**. Server boots clean, chart renders without error.
  - **Deferred (intentional):** `core/calculations.py:compute_thrust_available()` still uses a single quadratic decay for all four classes. Per-class T_static_factor is doing the work today; per-class *decay shape* (e.g., turboprop flat-then-cliff) is a future enhancement when we have real prop-disk data — not needed for v1.
- _<next: Phase 2h (final validation + spot-audit) or Phase 2e (non-FAA sourcing) or back to Phase 5/3/4/6 per user>_

- 2026-05-13 — **Phase 3a/3b shipped — airports.json rebuilt from OurAirports + NASR:**
  - **Sources (all pre-cached in tallyaero monorepo, no network needed):**
    - OurAirports (`byId`, 85,312 records, CC-BY) — global base, gives type/iata/region/wikipedia
    - FAA NASR APT_BASE (`byId`, 22,026 records, cycle 2026-05-14) — US authoritative state/city/ownership
    - FAA NASR APT_RWY + APT_RWY_END (`byAirport`, 19,667 records) — runway depth (length, width, surface, lighting, gradient %, ILS, end lat/lons, magnetic alignment)
  - **Filter:** keep small/medium/large_airport + seaplane_base (drops 36k heliport/closed/balloonport records — not relevant for the fixed-wing EM diagram).
  - **Two parser bugs caught + fixed:**
    - (1) NASR runway dict is keyed by LID ("AUS"), but my first reverse-lookup map sent ICAO ("KAUS") → ICAO ("KAUS") because NASR is *double-indexed* (~2.6k major airports appear under both LID and ICAO with `lid` field as canonical). Rebuilt the map to read `rec.lid` directly — now KAUS resolves to AUS and the runway join lands.
    - (2) NASR ships helipads (rwyId "H1", "H2") in its runway list for fixed-wing airports. Filtered out by `rwyId.startswith("H")` — KAUS dropped from 5 to 2 runways (its actual fixed-wing pair: 18L/36R 9,000 ft + 18R/36L 12,250 ft).
  - **Output:** 49,128 records (3× old 16,128). 43,790 with elevation, 10,648 US records with NASR runway depth. File grew 5.1 → 12.7 MB on disk after null-stripping each record. 99.3 % retention of old IDs (115 dropped — mostly private/closed strips like "Crash In International Airport").
  - **Schema additions on every record:** `icao`, `iata`, `local`, `country`, `region`, `municipality`, `state`, `type`, `scheduled_service`, `wikipedia`. Backwards-compat fields (`id`, `name`, `lat`, `lon`, `elevation_ft`, `runways`) preserved verbatim, so `core.aircraft_loader.load_airport_data` and `get_airport_by_id` keep working without code changes.
  - **Runway depth (US, 10,648 records):** length_ft, width_ft, surface (normalized to asphalt/concrete/turf/gravel/dirt/water/other from 50 NASR codes), lighting, gradient_pct, plus a 2-element `ends` array with id/lat/lon/elevation_ft/heading/ils for each runway end. Surface mix: 6,639 turf, 3,956 asphalt, 776 concrete, 666 gravel, 594 water, 400 dirt.
  - **`get_airport_options()` label upgrade:** searches now match by id, name, city, state/country, and IATA via the label string. Example labels: `"KAUS — Austin Bergstrom International Airport · Austin, TX · 541 ft · IATA AUS"`, `"EGLL — London Heathrow Airport · London, GB · 83 ft · IATA LHR"`, `"00AA — Aero B Ranch Airport · Leoti, KS · 3,435 ft"`. No code change to layouts/desktop or layouts/mobile — they read `AIRPORT_OPTIONS` which is rebuilt at boot.
  - **10-airport spot check:** KAUS/KJFK/KORD/KBOS/KSFO/KDEN/KASE/KEGE/EGLL/RJTT/LIPZ/LEMD — all elevations match published values within 2 ft, except KASE (7820 → 7837 in current NASR cycle) and LIPZ (16 → 7 from updated OurAirports survey). NASR is authoritative; accept the deltas.
  - **Tests:** 183 passed, 1 skipped. Server boots clean, dropdown renders, lookups work end-to-end. Backup at `airports/airports.json.bak-pre-phase3`.
  - **Deferred:** Phase 3c (country filter chip + IATA/city-aware search UI). Non-US runway depth — OurAirports raw runways.csv exists in cache but isn't normalized; a future Phase 3e can mine it if EU/JP/CA users ask for runway info.
- _<next: Phase 3c (UI filter polish), Phase 4 (live weather), or back to Phase 5/2h/6 per user>_

- 2026-05-13 — **Phase 4a/4b/4c/4d shipped — live METAR wired into the environment block:**
  - **Source:** NOAA Aviation Weather Center JSON API at `https://aviationweather.gov/api/data/metar?ids={icao}&format=json`. Public, no key, no auth. Empty-body 200 response = "no obs available" (typical for private strips). ~1.1 s cold latency, in-process cache holds repeats at ~0 ms.
  - **Client:** `services/weather.py` — stdlib `urllib`-only (no new deps; survives a sealed PyInstaller bundle later). Returns frozen `MetarObservation` dataclasses with parsed `temp_c`, `dewpoint_c`, `altimeter_inhg` (converted from hPa via 0.02953), `wind_dir_deg`, `wind_speed_kt`, `wind_gust_kt`, `visibility`, `sky_cover`, `flight_category`, `obs_time_epoch`, `report_time`, `raw`. `to_dict()` for the dcc.Store roundtrip.
  - **Cache:** 10-min TTL, negative results (empty obs) cached too so we don't re-hammer NOAA for the same private strip; network errors NOT cached so transient failures retry on next click. `clear_cache()` exposed for tests.
  - **UX decision (user-confirmed):** *METAR wins*. Picking an airport sets OAT + altimeter from the live obs; the old altitude-slider → ISA-OAT chain only fires now when no airport is selected (still useful for ad-hoc "what-if at FL180" exploration). User-set OAT no longer gets clobbered by slider tweaks.
  - **Callback restructure** in `callbacks/environment.py`: collapsed the airport-side state changes into a single owning callback (`update_environment_from_airport`) that writes altitude slider min/value/marks + OAT + altimeter + metar-store in one atomic update. Avoids the previous race where the altitude→OAT chain clobbered any METAR-set OAT. Old `update_default_oat` rewritten as `update_default_oat_no_airport` which `raise PreventUpdate`s when an airport is selected.
  - **Weather panel:** compact display under the airport picker — station name omitted (already in dropdown label), shows `Live obs · N min ago · [VFR/MVFR/IFR/LIFR color chip]`, then temp/dewpoint, altimeter, wind+sky+visibility, raw METAR string, attribution "via NOAA Aviation Weather Center." Fallback message "No live observation — using ISA / 29.92" defaults" for strips without an obs. CSS appended to `assets/styles.css` using `--ta-surface-*` design tokens (light/dark theme parity for free).
  - **Tests:** 20 new tests in `tests/test_weather.py` covering parser (canonical KAUS payload, gusty KJFK, missing-field skeleton, altimeter conversion factor), `MetarObservation` dataclass (age_seconds, JSON roundtrip), `get_metar()` happy path + empty body + network error + bad JSON + case normalization + empty input short-circuit, and cache behavior (hit, force bypass, negative caching, transient-error retry, TTL expiry, clear). All mocked — zero hits to the live API in CI.
  - **Verified live:** KAUS → 28°C / 30.11" / VFR (gust-free), KJFK → 17°C / 29.94" / VFR with 18G28 wind, EGLL (Heathrow) → 10°C / 29.59" — proves international AWC coverage works. 00AA → ISA fallback (correct, no obs).
  - **Full suite: 203 passed, 1 skipped.** Server boots clean, all 49,128 airports + live weather available end-to-end.
  - **Deferred:** Phase 4e (TAF / terminal forecast panel) and Phase 4f (clientside JS fetch path for fully offline-tolerant Dash deployments). Both are nice-to-have, not blockers.
- _<next: Phase 5 polish (5f responsive collapse / 5i comparison mode / 5j print export), Phase 6 (PyInstaller packaging), or Phase 2h/2e/2g to lock down the aircraft data — per user>_

- 2026-05-14 — **Phase 5L–5T (UI/UX overhaul) shipped end-to-end:** Option A desktop layout (top strip + chart hero + state panel rail + slide-out drawer); env-chip popovers (airport/altitude/OAT/altimeter); state panel 3×2 grid; chip mutual-exclusivity; dropdown blue-pill kill; theme-aware empty chart state; light-mode default + retired AUTO button; viridis colorscale; transitions; theme-aware annotations; geometric corner-fix + comparative V-speed declutter; Ps/turn-radius/colorbar/legend typography pass; accessibility (aria-labels, prefers-reduced-motion, keyboard shortcuts D/E/G/?); edit-aircraft Tier 2 (auto-load from main page, Duplicate button, schema-aware save validation, no emojis anywhere).
- 2026-05-14 — **Phase 5R-3/5R-4 shipped — DVmc + DVyse calibration audit (Session 8 of PHYSICS_AUDIT_PLAN.md):** at certified conditions both functions now return exactly published Vmca/Vyse to 0.01 KIAS (were 103.7 % / 98 % respectively). Root cause: prop and bank modifiers were sized relative to a different baseline than the 14 CFR 23.149 certified state. Path B (per-aircraft AFM response surfaces) investigated; data availability for GA twins is too sparse to make Path B worth the multi-week treasure hunt — decision: ship the recalibrated modifier model as the legitimacy floor. 31 new parametric tests in `tests/test_vmc.py` + `tests/test_vyse.py`. Suite went 203 → 234 passed.
- 2026-05-14 — **Phase 2h shipped — aircraft data hardening finalized:** 110/110 Pydantic-valid, all with ≥1 source citation, 10 % spot audit (11 aircraft) clean of invariant violations. One real data defect found and fixed (Pitts S-1C-TB had incomplete flap data, harmonized from Pitts S-1C). One Pydantic Source-schema bug surfaced by the fix (caught + corrected — extra `scope` field properly rejected, folded into publication string).
- 2026-05-14 — **Phase 6 shipped — PyInstaller bundle:** `tallyaero_em.spec`, `launcher.py` (free-port picker + background Dash + browser open + clean shutdown), `VERSION`, Makefile build targets, `BUILD.md`. Verified end-to-end: `dist/TallyAero EM.app` (405 MB) launches, picks port, serves HTTP 200, all assets + Dash callbacks fire. Pandas dropped from bundle (zero imports in tree, 19 MB saved). Kaleido at 232 MB documented as the remaining size driver — client-side `Plotly.toImage()` rewrite tracked as follow-up. Signing/notarization/CI documented in BUILD.md, gated on Apple Developer ID + Windows OV cert (resources outside the repo).
- 2026-05-14 — **Phase 7 shipped — cross-app drift detector:** `scripts/sync_check.py` walks the Shared Asset Ledger (§6) and reports per-asset status (IDENTICAL / DRIFT / EM-ONLY / OVERLAY-ONLY / MISSING). Makefile targets `sync-check`, `sync-check-verbose`, `sync-apply-to-overlay`. First run revealed substantial drift: 7 core/ files EM-only (overlay tree is structurally different), 110 aircraft JSONs drifted, airports.json size 2.5× bigger here (Phase 3a rebuild), 2 aircraft overlay-only. Script REPORTS — reconciliation is a deliberate decision for the overlay deep-dive pivot.
- 2026-05-14 — **Phases 0–7 closed.** Tool is feature-complete relative to the original plan. Test count 234 passed, 1 skipped. Signed-distribution + comparison-mode + risk-overlay all documented in §11 Future Feature Lab below for potential later execution.
- 2026-05-14 — **Research pass — EM theory foundations.** Four-agent parallel websearch covering Boyd canon (APGC-TDR-66-4 declassified release), pre-Boyd academic foundations (Kaiser 1944, Lush 1951, Rutowski 1954, Kelley 1960, Bryson 1962, Bryson-Desai-Hoffman 1969), test pilot pedagogy (USAF TPS Ch 9, USNTPS FTM-108, FAA AFH Ch 4 added 2021), and post-2010 academic extensions (Lombaerts reachability, Helsen probabilistic envelopes, DARPA AlphaDogfight RL agents, eVTOL transition corridors). Findings captured as §10 (theory lineage + accessible primary-source URLs) and §11 (Phase 5U–Z Future Feature Lab — six fully-specified candidate features). Lean for next push: **5U (comparative aircraft overlay — Boyd's killer feature) + 5V (KE/PE split + recovery arrows — closes the FAA AFH Ch 4 → TPS Ch 9 translation gap).**
- _<next: Phase 5U + 5V (comparative overlay + KE/PE split) per the 2026-05-14 research lean; 5W/X/Z available; 5Y data-gated. Outside Phase 5: pivot to the overlay-tool deep-dive in a separate session, or pursue Phase 6 follow-ups (signing/installers/CI) when certs are in hand.>_

- 2026-05-14 — **Phase 5V shipped — KE/PE split in State Panel:** new `core.calculations.compute_energy_state(altitude_ft, ias_kt) -> {ke_ft, pe_ft, e_total_ft, ke_fraction}`. State Panel grew from 6 to 8 cards (third row = KE + PE). Reference IAS = aircraft's Vy if known, else Vno, else 100 KIAS. 8 new parametric tests in `tests/test_energy_state.py` cover the math (V²/2g), sea-level/altitude edge cases, energy conservation (zoom-climb equivalence). Suite went 234 → 242 passed.
- 2026-05-14 — **Phase 5U shipped — comparative aircraft overlay (MVP):** Boyd's 1966 killer feature is now in. New `dcc.Store(id="compare-aircraft")` at app.py level; new `VS Compare` chip in the top strip (alongside aircraft picker) opens a popover with a second aircraft dropdown; selecting a second aircraft renders three dashed-orange traces over the primary chart (Lift Limit, Load Limit, Corner marker + value label). Both envelopes use the SAME atmospheric state — apples-to-apples comparison per Boyd's 1966 approach. 4 new tests in `tests/test_compare.py` cover baseline (no-compare), comparison-adds-traces, same-aircraft no-op, unknown-aircraft no-op. Suite went 242 → 246 passed. Deferred to 5U-2 (not blocking): advantage shading (Ps_A − Ps_B grid), 12-card State Panel split, independent compare-aircraft category/config controls.
- _<next: Phase 5W (Lombaerts reachable set), 5X (probabilistic envelope), 5Z (h-V mission profile), or pivot to overlay-tool deep dive / Phase 6 follow-ups per user direction.>_

---

## Appendix A — Quick Reference: Current State

```
tallyaero_em_diagram/
├── app.py                                    5,975 lines  — monolith, decompose in Phase 1
├── core/
│   ├── __init__.py                              69 lines
│   ├── aircraft_loader.py                      190 lines  — boot side-effects, fix in Phase 0
│   ├── calculations.py                         408 lines  — physics SoT, audited
│   └── constants.py                             70 lines
├── tests/
│   ├── __init__.py
│   └── test_core.py                            154 lines  — smoke tests, expand in Phase 0
├── aircraft_data/                              110 files  — Pydantic-validate Phase 0, cite Phase 2
├── airports/
│   └── airports.json                        16,128 records × 5 fields — overhaul Phase 3
├── callbacks/, components/, pages/, ui/                  — empty stub packages, fill Phase 1
├── assets/
│   ├── styles.css
│   └── export.js
├── _ecosystem/                                              — synced docs
├── edit_aircraft_page.py                                   — partial; rest is in app.py — move Phase 1
├── aeroedge_tracker.py                                     — shared, opt-out (change to opt-in Phase 6)
├── requirements.txt
├── PHYSICS_AUDIT_PLAN.md                                    — 7 audit sessions complete
├── Master prompt and context.md                             — governing rules
└── CLAUDE_CONTEXT.md
```

---

## Appendix B — Glossary (quick aviation refresher for the assistant)

- **Ps** — Specific Excess Power. `(T − D) · V / W − V · sin(γ)`. Units kts/sec. Positive = can accelerate or climb; negative = bleeding energy.
- **n** — Load factor (Gs). `n = 1 / cos(bank)` in coordinated level turn.
- **Corner velocity** — Speed where the stall and structural-G limits intersect; the airspeed at which an aircraft turns fastest without overstressing.
- **Vmca** — Air minimum control speed, multi-engine, critical engine inoperative. Below it, rudder cannot counter yaw.
- **Vyse / Vxse** — Best-rate / best-angle of climb with one engine inoperative.
- **DVmc / DVyse** — Dynamic versions adjusted for current weight, altitude, CG, prop condition, bank.
- **ACS** — Airman Certification Standards. *Not* "ATS".
- **AIRAC** — 28-day aeronautical chart revision cycle.
- **TCDS** — Type Certificate Data Sheet. The FAA's authoritative document for any type-certified aircraft.
- **POH / AFM** — Pilot's Operating Handbook / Aircraft Flight Manual.
- **METAR / TAF** — Routine observation / Terminal aerodrome forecast.
- **OEI** — One Engine Inoperative (multi-engine).
