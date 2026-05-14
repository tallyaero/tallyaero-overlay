# Maneuver Overlay Tool — Execution Plan

Working plan for the Maneuver Overlay Tool's audit + polish + merge-features sprint. Mirrors the structure of the EM Diagram archive's `EM_DIAGRAM_EXECUTION_PLAN.md`. The full design rationale lives in `docs/plans/2026-05-13-audit-and-merge-design.md`.

**Repo.** `~/Desktop/tallyaero_overlay_archives/` (clone of `github.com/tallyaero/tallyaero-overlay`).

**Companion archive.** `~/Desktop/tallyaero_archives/` (EM Diagram).

**Locked decisions.** D1–D11. See design doc.

**Port.** 8050 (vs EM Diagram 8051).

---

## Phase index

| # | Phase | Status | Sub-phases |
|---|---|---|---|
| Setup | Port local-only deltas from `reference/overlay_tools/` snapshot | pending | po180.py, CLAUDE_CONTEXT.md, engine_out_buckets.md |
| **0** | Test infra + telemetry removal + dev ergonomics | pending | 0a–0i |
| **1** | Decompose app.py (7,784 lines → ≤200) | pending | 1a–1i |
| **2** | Aircraft data hardening (port from EM Diagram) | pending | 2a–2e |
| **3** | Airport data overhaul (OurAirports+NASR port) | pending | 3a–3d |
| **4** | Maneuver-tool polish + theme + UI shell | pending | 4a–4h |
| **5** | Route Planning Core | pending | 5a–5g |
| **6** | Weather Services Layer | pending | 6a–6i |
| **7** | Glide Corridor | pending | 7a–7h |
| **8** | Landing Zones Overlay | pending | 8a–8f |
| **9** | Divert Field Skew | pending | 9a–9e |
| **10** | Slope Heatmap | pending | 10a–10d |
| **11** | NEXRAD Radar (optional) | pending | 11a–11b |
| **12** | Cross-app Reciprocity + Packaging | pending | 12a–12d |

---

## Phase 0 — Test infra + telemetry removal + dev ergonomics

**Goal.** Bring the project to "anyone can hack on this without fear" baseline.

- **0a** `pyproject.toml` with pinned deps; convert `requirements.txt` to derived artifact.
- **0b** pytest setup; `tests/test_smoke.py` proves each simulation module imports + runs; `tests/test_physics.py` proves hand-calc against published references for ≥3 maneuvers.
- **0c** Snapshot testing for the most-used maneuvers via `syrupy`.
- **0d** Replace `print` / `dprint` with structured `logging`. Configurable via `TALLYAERO_OVERLAY_LOG` env var.
- **0e** Audit `prevent_initial_call` across all callbacks.
- **0f** Move data loading out of module-import side effects into explicit `init_data()`.
- **0g** **Telemetry removal.** Delete `aeroedge_tracker.py`, strip the heartbeat `<script>` from `app.index_string`. Decision D3 enforcement.
- **0h** `Makefile` — `make run`, `make test`, `make snapshot-update`, `make lint`.
- **0i** Project-wide `aeroedge` → `tallyaero` rename.

**Acceptance.** `make test` passes with ≥30 tests. `make run` boots clean at 8050. `grep -r aeroedge_tracker` returns nothing. No telemetry HTTP calls observable in DevTools.

---

## Phase 1 — Decompose app.py

**Goal.** `app.py` becomes a thin entry that imports layouts + callbacks, registers them, serves. Target ≤200 lines.

- **1a** Set up `callbacks/` package with `register_all(app)` aggregator.
- **1b** Extract maneuver layouts into `layouts/maneuvers/<name>.py` — one file per maneuver.
- **1c** Extract draw / simulate callbacks per maneuver into `callbacks/maneuvers/<name>.py`.
- **1d** Extract environment callbacks (OAT, altim, wind, airport, elevation) into `callbacks/environment.py`.
- **1e** Extract aircraft-config callbacks into `callbacks/aircraft.py`.
- **1f** Extract map-interaction callbacks into `callbacks/map.py`.
- **1g** Extract `edit_aircraft_page.py` modal/route into `layouts/edit_aircraft.py` + `callbacks/edit_aircraft.py`.
- **1h** Extract desktop + mobile layouts into `layouts/desktop.py` + `layouts/mobile.py`.
- **1i** Final `app.py` slim-down — ≤200 lines.

**Acceptance.** `app.py` ≤200 lines. Every component id preserved. `make test` still passes. Boot time same or faster.

**Risk.** Highest of any phase — 47 callbacks to relocate without breaking IDs. Mitigation: one callback at a time, `make test` after each move, commit per sub-phase.

---

## Phase 2 — Aircraft data hardening

- **2a** Establish vendored-copy + sync_check model (D11). Copy `aircraft_data/` from `~/Desktop/tallyaero_archives/`.
- **2b** Port `core/schema.py` Pydantic models from EM Diagram (Aircraft, EngineOption, PropThrustDecay, ThrustModel, source-provenance fields).
- **2c** Port TCDS lookup + reconciliation work (EM Diagram Phases 2a–2c).
- **2d** Per-class T_static_factor classification (1.85 / 2.50 / 2.50 / 3.00).
- **2e** Schema-validation tests; every aircraft file parses cleanly.

---

## Phase 3 — Airport data overhaul

- **3a** Port `data/scrapers/build_airports.py` from EM Diagram; re-run against `tallyaero/website/.research-cache/normalized/`.
- **3b** Update `load_airport_data()` and dropdown consumers for the new schema. Backwards-compat fields preserved.
- **3c** Dropdown labels gain country/IATA/state context.
- **3d** 99 %+ retention of existing IDs; 10-airport spot check; runway-data verification on 5 known airports.

---

## Phase 4 — Maneuver-tool polish

- **4a** Steep-turn fixes from `NEXT_TASK.md` (drift_corrected port, snap-elimination, hover-data alignment).
- **4b** MANEUVER_STANDARD.md compliance audit for each of 11 maneuvers.
- **4c** Design-token system port — `assets/tokens.css`, `--ta-*` everywhere.
- **4d** Dark mode + light-mode default + early-paint script + `data-theme` Store.
- **4e** UI shell rebuild — Option A pattern from EM Diagram (top strip + map-as-hero + right rail state panel + settings drawer).
- **4f** Mobile layout — stacked single-column with sliding settings panel.
- **4g** Export polish — PNG/PDF of map + maneuver + info-panel.
- **4h** Edit-aircraft page polish — chip-style buttons, theme tokens, dropdown overrides.

---

## Phase 5 — Route Planning Core

- **5a** `core/route.py` — port `routeCalculator.ts` math.
- **5b** Real WMM via `pygeomag`.
- **5c** Pydantic `RouteInput` / `RouteResult` schemas.
- **5d** Route picker UI — departure + destination + cruise alt + TAS.
- **5e** Render great-circle line on Leaflet map.
- **5f** Route summary card (NM, TC, MH, GS, ETE, fuel).
- **5g** Save/load route to local JSON.

---

## Phase 6 — Weather Services Layer

- **6a** Port `services/weather.py` METAR client from EM Diagram.
- **6b** `services/taf.py` — TAF client.
- **6c** `services/winds_aloft.py` — NOAA FBW client. **The corridor's #1 input.**
- **6d** `services/airsigmet.py` — SIGMET/AIRMET client.
- **6e** `core/route_weather.py` — port `weatherRouteFilter.ts` line-near-polygon logic.
- **6f** `services/pirep.py` — PIREP client.
- **6g** Weather UI panel — METAR at departure + destination.
- **6h** TAF valid-time picker (Now / +6h / +12h / +24h).
- **6i** Mock-based tests across all five clients (30+ tests).

---

## Phase 7 — Glide Corridor

- **7a** `core/corridor.py` — `compute_route_corridor` samples route at 1 NM intervals, calls `compute_glide_envelope` per sample with local wind from FBW.
- **7b** Add `shapely`; union per-sample envelopes.
- **7c** AGL refinement via Open-Meteo batch elevation along route.
- **7d** Render corridor as semi-transparent green `dl.Polygon`.
- **7e** Corridor info badge — narrowest width, total area, weakest-link AGL.
- **7f** Show/hide toggle.
- **7g** Debounced re-compute on input change.
- **7h** Canonical scenario tests (zero-wind symmetry, headwind narrowing, AGL margin).

---

## Phase 8 — Landing Zones Overlay

- **8a** `core/landing_zones.py` — filter airports by type/runway-length + Shapely contains.
- **8b** Render airport markers (colour by category).
- **8c** Click-to-pin divert candidate.
- **8d** `scripts/build_offfield_zones.py` — SRTM + NLCD precompute pipeline → GeoJSON per 1° tile.
- **8e** Runtime load + intersect with corridor.
- **8f** Performance budget: ~25 tiles for starter region (~50 MB).

---

## Phase 9 — Divert Field Skew

- **9a** `core/divert.py` — scan route, identify gap segments > `max_gap_nm`.
- **9b** For each gap, find airport within `max_deviation_nm` budget.
- **9c** Propose with cost analysis (extra NM, extra fuel).
- **9d** UI gap list with accept/reject per recommendation.
- **9e** Heuristic only for MVP.

---

## Phase 10 — Slope Heatmap

- **10a** `scripts/build_slope_tiles.py` — SRTM → slope raster → 4 bands → PNG tiles zoom 8–12.
- **10b** Leaflet `TileLayer` with bundled tile URL template.
- **10c** Threshold slider (3° / 5° / 10°).
- **10d** Per-region bundle + downloader for additional regions.

---

## Phase 11 — NEXRAD Radar Overlay (optional)

- **11a** Identify tile source (NOAA NIDS vs Iowa State Mesonet).
- **11b** Leaflet `TileLayer` + throttling + tile-age badge.

---

## Phase 12 — Cross-app Reciprocity + Packaging

- **12a** `scripts/sync_check.py` — diff `aircraft_data/` between EM Diagram + Overlay archives.
- **12b** PyInstaller spec for macOS / Windows / Linux.
- **12c** Signed builds via GitHub Actions.
- **12d** README, user docs, screenshots.

---

## Dated execution log

Append-only. One entry per shipped sub-phase or significant decision. Mirrors the EM Diagram pattern.

- 2026-05-13 — **Design approved.** Audit plan (Phases 0–4) + Merge plan (Phases 5–12) approved by user. Working repo at `~/Desktop/tallyaero_overlay_archives/` (clone of `github.com/tallyaero/tallyaero-overlay`). Snapshot of original design archived at `docs/plans/2026-05-13-audit-and-merge-design.md`. Next: pre-Phase-0 setup (port local-only deltas from `reference/overlay_tools/`) then begin Phase 0.
- _<next entries appended here as phases ship>_
