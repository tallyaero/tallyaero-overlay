# Maneuver Overlay Tool — Audit + Merge Design

**Status.** Approved 2026-05-13. Live working copy is `OVERLAY_TOOL_EXECUTION_PLAN.md` at repo root; this document is the snapshot of the original design that produced that plan.

**Scope.** Two streams in one project:
1. **Audit + polish** (Phases 0–4) — bring the existing Python/Dash maneuver overlay tool to the same code-quality, test, schema-rigour, and visual standard the EM Diagram archive achieved through its Phases 0–5.
2. **Merge features** (Phases 5–12) — extend the tool with route planning, weather integration, glide-corridor visualisation, landing-zone overlay, divert-field skewing, and slope-based off-field terrain heatmap. Driven by the user's vision of an in-app emergency-aware route-planning tool.

**Working repo.** `~/Desktop/tallyaero_overlay_archives/` (clone of `github.com/tallyaero/tallyaero-overlay`), parallel to `~/Desktop/tallyaero_archives/` which holds the EM Diagram.

---

## Locked decisions

Carried from the EM Diagram archive (already validated through Phase 5 there) and applied verbatim here:

- **D1.** Hybrid data integrity model — every aircraft field tagged verified / partial / estimated with source provenance.
- **D2.** GA + multi-engine + aerobatic only in v1. No airliners or military fighters.
- **D3.** **No telemetry.** Functional network calls to public APIs (NOAA AWC, Open-Meteo) are fine; analytics/tracking are not. `aeroedge_tracker.py` gets removed in Phase 0g.
- **D4.** Visual parity with TallyAero monorepo — `--ta-*` design tokens, the chip/popover top-strip pattern from EM Diagram Phase 5L–O, light mode default.
- **D5.** Tesla / SpaceX / Apple quality bar.
- **D6.** Project-wide `aeroedge` → `tallyaero` rename in Phase 0i.
- **D7.** Full mining of authoritative source data (TCDS, NASR, OurAirports) — no shortcuts.

Overlay-tool-specific decisions added in this design:

- **D8.** Off-field landing-zone polygons are pre-computed at build time per 1°×1° tile. Runtime is read-only — no GDAL on the user's machine.
- **D9.** Winds aloft (NOAA AWC FBW) is the canonical wind input for the glide corridor when available; manual wind input is the fallback for offline use.
- **D10.** TAF valid-time picker uses four discrete options for v1: `Now / +6h / +12h / +24h`. No full timeline scrubber until v2.
- **D11.** Aircraft data is vendored from the EM Diagram archive, not symlinked. A `scripts/sync_check.py` (Phase 12a) reports drift between the two repos.

---

## Feasibility summary

This project is **GO** — every feature is buildable, no architectural blockers.

| Domain | Status | Notes |
|---|---|---|
| Map rendering | Solved | Dash-Leaflet 1.0.15 already in the dependency set. |
| Route math | Trivial port | ~880 LOC of TS in `apps/pilot/src/engine/routeCalculator.ts`; pure trig. Magvar upgrades from a linear-CONUS estimate to real WMM via `pygeomag`. |
| Glide corridor | Trivial | `compute_glide_envelope` already exists in `simulation/engine_out.py:2679`. Corridor = sample-and-union along route. Adds `shapely`. |
| Airport landing zones | Trivial after Phase 3 | After porting the EM Diagram Phase 3 airport rebuild (49k OurAirports+NASR records with runway depth) the filtering is one Shapely call. |
| Off-field landing zones | Feasible with precompute | DEM (SRTM) + landcover (NLCD) → slope + landcover mask → vectorise → GeoJSON per 1° tile, ~50–200 MB shipped. One-time build pipeline. |
| Slope heatmap | Feasible | Pre-baked PNG tiles per region served as Leaflet `TileLayer`. Three threshold levels (3° / 5° / 10°) for MVP. |
| Weather services | Solved on the EM-Diagram side for METAR; rest are new | All five sources (METAR, TAF, FBW winds aloft, AIRSIGMET, PIREP) are free NOAA AWC endpoints, no API key. |
| Tool decomposition | Standard refactor | app.py is 7,784 lines monolith. Same pattern as EM Diagram Phase 1, playbook proven. |
| PyInstaller bundling | Phase-12 concern | DEM/landcover analysis is build-time only, so runtime needs only `shapely` + numpy. |

---

## Phase outline

### Audit + Polish (Phases 0–4)

| Phase | Theme | Rough size |
|---|---|---|
| **0** | Test infra + telemetry removal + dev ergonomics | 1 session, 9 sub-phases |
| **1** | Decompose `app.py` (7,784 lines → ~200) | 2–3 sessions, 9 sub-phases |
| **2** | Aircraft data hardening (port from EM Diagram) | 1 session, 5 sub-phases |
| **3** | Airport data overhaul (port OurAirports+NASR rebuild) | 0.5 session, 4 sub-phases |
| **4** | Maneuver-tool polish + theme system port + UI shell | 3–4 sessions, 8 sub-phases |

### Merge Features (Phases 5–12)

| Phase | Theme | Notes |
|---|---|---|
| **5** | Route Planning Core | Port TS routeCalculator, WMM magvar upgrade, draw direct route. |
| **6** | Weather Services Layer | All five NOAA AWC clients. Winds aloft is the load-bearing piece. |
| **7** | Glide Corridor | Sample + union, AGL-aware, consumes winds-aloft. |
| **8** | Landing Zones Overlay | Airports filter (trivial), off-field GeoJSON pipeline. |
| **9** | Divert Field Skew | Heuristic — gap detect + nearest-airport insert. |
| **10** | Slope Heatmap | Pre-baked tile layer with threshold toggle. |
| **11** | NEXRAD Radar (optional) | Free third-party WMS tile source. |
| **12** | Cross-app Reciprocity + Packaging | sync_check + PyInstaller. |

See `OVERLAY_TOOL_EXECUTION_PLAN.md` for the full sub-phase breakdown, file-touch list per phase, acceptance criteria, and risk register.

---

## Pre-Phase-0 setup (one-time, before audit begins)

The local snapshot at `tallyaero/reference/overlay_tools/` has three small deltas that the GitHub `main` branch is missing:
- `simulation/po180.py` — newer variable-timestep groundspeed logic (~7 line addition)
- `CLAUDE_CONTEXT.md` — repo onboarding doc
- `simulation/engine_out_buckets.md` — engine-out analytics notes

These get ported into the clone as a single `chore:` commit before Phase 0 begins, so the working repo carries all known-good content.

---

## Open items deferred to during-execution decisions

- **Starter slope-tile region.** Default: KAUS Hill Country (5°×5° centred on 30.5N, 97.5W). Adjustable per user's flying area.
- **NEXRAD provider.** NOAA NIDS vs Iowa State Mesonet. Pick at Phase 11.
- **Mobile-vs-desktop responsive strategy.** EM Diagram split desktop/mobile trees; we may try a single responsive grid here. Decide at Phase 4f.

---

## Success criteria (v1 ship)

A pilot can:
1. Pick a departure + destination airport on the map.
2. See a wind-aware glide corridor along the route, computed against the real winds-aloft forecast for the planned cruise altitude.
3. See every airport along the corridor with runway-length information.
4. See divert-recommendation badges where the gap between airports exceeds the configurable threshold.
5. Toggle a slope-based terrain layer for off-field landability context.
6. Save the plan, recall it, export it to PDF.

Plus: every maneuver in the existing tool's library passes the MANEUVER_STANDARD.md compliance audit; the codebase has 100+ tests; the chart looks like it belongs on the same shelf as the EM Diagram.
