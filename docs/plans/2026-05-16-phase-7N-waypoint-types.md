# Phase 7N — Waypoint types beyond airports + click-to-build

**Status:** planned, queued after Phase 7M
**Date:** 2026-05-16
**Branch (when started):** `phase-7N-waypoint-types`

---

## Goal

Today the Route waypoint dropdown only resolves airports. A real
route planner needs:

1. **GPS coordinates** — type or click any lat/lon and use it as a
   waypoint (off-airway loiter point, scenic detour, deliberate
   open-field overflight, etc.)
2. **VORs and other NAVAIDs** — VOR, VOR/DME, VORTAC, NDB. Foundational
   for any IFR-flavored planning, still common as VFR checkpoints.
3. **Intersections / fixes** — named 5-letter waypoints (VARRO, SAKES,
   etc.) that lie on airways or are commonly used as ATC fix points.
4. **Click-to-build** — click anywhere on the map to add a waypoint
   at that point. If the click is near an airport/VOR/fix within a
   user-set snap radius, snap to it; otherwise drop a GPS waypoint at
   the literal lat/lon.

This is the architectural completion of the multi-waypoint route
work. `core/airport_search.resolve_waypoint()` was already designed
as the extension point — it currently tries airports and falls back
to fuzzy match. 7N expands the resolver chain.

## Sub-phases

### 7N-a — GPS coordinate parsing + waypoint type system

New module `core/waypoints.py` introducing a unified waypoint type:

```python
@dataclass
class Waypoint:
    kind: str        # 'airport' | 'vor' | 'ndb' | 'fix' | 'gps'
    ident: str       # display string e.g. 'KDYB' / 'SAV' / 'VARRO' / 'GPS 33.06N 80.28W'
    lat: float
    lon: float
    elevation_ft: float | None = None     # only airports + some NAVAIDs
    name: str = ''                        # 'Summerville Airport', 'Savannah VOR-DME', etc.
    freq_mhz: float | None = None         # NAVAIDs only
    extra: dict = field(default_factory=dict)
```

GPS parser accepts (in priority order):
- `33.0635,-80.2795`     → decimal degrees
- `33.0635, -80.2795`    → spaces tolerated
- `N33.0635 W80.2795`    → hemisphere prefix
- `N33°03.81' W80°16.77'` → degree-decimal-minute (DDM)
- `N33°03'48" W80°16'46"` → degree-minute-second (DMS)
- `N3303.81/W08016.77`   → ARINC 424 / GPS-shorthand format (common
                            on filed IFR routes)
- Output: `Waypoint(kind='gps', ident=f'GPS {lat:.4f}N {lon:.4f}W', ...)`

Existing `resolve_waypoint(airport_data, token)` becomes a thin
shim that calls a new `resolve_any(token, *, airport_data,
navaid_data, fix_data)`. Calling sites in callbacks/route.py pass
all three data tables.

### 7N-b — NASR NAVAID ingestion

```
NEW   scripts/build_navaids.py       # extracts NAV_BASE.csv from NASR
NEW   data/navaids.json              # normalized output
NEW   core/data_loader_navaids.py    # loads at boot
NEW   tests/test_navaid_data.py      # schema + spot-checks
EDIT  core/airport_search.py         # search_navaids + multi-type ranked search
EDIT  core/waypoints.py              # resolve_any() chain
EDIT  callbacks/route.py             # pass navaid_data into resolve + search
```

NASR distribution (download script):
```
https://nfdc.faa.gov/webContent/56DaySub/{cycle}/NASR_Subscription_{cycle}.zip
```

Current cycle dated 2026-01-22; refreshed every 56 days. Script:
1. Downloads + extracts `NAV.zip` from the subscription
2. Parses `NAV_BASE.csv` (~~3000 NAVAIDs in CONUS)
3. Filters to active, non-restricted entries
4. Normalizes to `{ident, name, type, lat, lon, freq_mhz, elevation_ft,
   magnetic_variation_deg, country}` per row
5. Writes `data/navaids.json`

Per-cycle refresh: documented as a manual command for now; later
auto-runs on the 56-day boundary.

Search ranking: NAVAID idents (3-letter) take a tier just below
airport ICAO/IATA. Typing `SAV` matches Savannah airport (IATA) AND
Savannah VOR — both appear, badged.

Display labels with type badge:
- `KSAV · ✈ Savannah Hilton Head Intl — Savannah, GA`
- `SAV ▲ Savannah VOR-DME (115.95) — Savannah, GA`

### 7N-c — NASR FIX ingestion

Same pattern as 7N-b, separate file:

```
NEW   scripts/build_fixes.py
NEW   data/fixes.json
NEW   core/data_loader_fixes.py
EDIT  core/waypoints.py              # add fix branch to resolver
```

Parses `FIX_BASE.csv` (~50k named fixes/intersections). Filter to
ICAO 5-letter names (typical pilot lookup pattern). Schema:
`{ident, lat, lon, type, artcc, country}`. No frequency, no
elevation.

Display label:
- `VARRO ✚ FIX — KFLO area`

### 7N-d — Click-to-build map interaction

UI:
- New toggle pill in shelf: `Click to add` (default OFF). When ON:
  - Map cursor becomes crosshair
  - Each click appends a waypoint to the route
  - Snap radius defaults to 3 NM (configurable inline)
  - Click within snap radius of an airport/VOR/fix → that waypoint
    is added (its ident, not a GPS)
  - Click outside snap radius → GPS waypoint at literal lat/lon
- "Click to add" mode stays on across multiple clicks; toggle off
  to stop adding
- Existing pill removal (× on pills) still works to remove waypoints

Implementation:
```
EDIT  callbacks/route.py
  - new callback: Input("map", "clickData") → modify route-waypoints.value
  - guarded by State("route-click-build-mode", "value")
  - uses spatial KD-tree (scipy.spatial.KDTree) built from
    airport_data + navaid_data + fix_data → fast "nearest" within
    snap radius
EDIT  layouts/maneuvers/route.py
  - new toggle pill + snap-radius mini input
```

Snap data structure (built once at boot, in-memory):
```python
class WaypointIndex:
    """KDTree over (lat, lon) for all snappable waypoints, with
    parallel arrays mapping back to source records."""
    def nearest(lat, lon, max_nm) -> Waypoint | None: ...
```

KDTree handles 100k+ points in microseconds. Snap-or-GPS decision
runs per click in ~50 µs.

### 7N-e — Map markers for VORs and fixes (toggle-on layer)

Render NAVAIDs and fixes as toggleable map overlays so pilots can
SEE them without zooming the sectional chart:

```
EDIT  layouts/desktop.py    # add LayersControl back, with overlay layers
EDIT  callbacks/map_overlays.py    # build dl.LayerGroup for visible VORs/fixes
```

LayersControl returns (the dash-leaflet 1.0.15 instability that bit
us in 7f happens when overlay layers' children update on every
callback — for these layers we render ALL VORs in CONUS once at
boot, then never mutate, so the bug doesn't apply). Two overlay
toggles:

- **VORs** — small `dl.CircleMarker` per VOR with a label. Visible
  at zoom ≥ 7.
- **Fixes** — smaller marker per fix, name only on hover. Visible
  at zoom ≥ 9 (50k fixes would be visual noise at lower zoom).

Click semantics:
- If 7N-d "Click to add" is ON: clicking a VOR/fix marker adds it
  to the route directly (no snap-radius needed — exact match).
- If "Click to add" is OFF: clicking shows a popup with ident + freq
  + name + a "Add to route" button.

### 7N-f — Airways (deferred to Phase 7N+)

V-routes (low-altitude airways) and J-routes (high-altitude jet
routes) are graphs of VOR-VOR or VOR-fix legs. Two integration
points:

1. Parse `AWY.csv` from NASR → `data/airways.json`
2. UI: type "V1.SAV.LFK" or similar to auto-expand into VOR/fix
   sequence
3. Visual: highlight the typed airway on the map for context

Defers because:
- Airway syntax parsing (`V1.SAV.LFK` style) is non-trivial
- Airway data has 56-day churn — refresh logistics matter more
- Real value emerges with airspace overlay (Phase 7f-follow) — they
  feel right together with the sectional chart on

## Schema additions

```
data/navaids.json — list[dict]:
  ident, name, type, lat, lon, freq_mhz, elevation_ft,
  magnetic_variation_deg, country, sources[]

data/fixes.json — list[dict]:
  ident, lat, lon, type, artcc, country, sources[]
```

Both versioned through `shared_data` submodule eventually so EM
Diagram + overlay tool stay in sync. Initial v1 keeps these in the
overlay repo while we settle the schema.

## Tie-in with FAA chart layer (Phase 7f-follow)

When OpenAIP / sectional chart layer is enabled, the chart raster
visually shows VORs and fixes. Without click-to-build, those are
just pretty pictures. **With 7N-d + 7N-e together**:

- Pilot toggles chart on → sees the visual chart
- Toggles VOR/fix markers on (7N-e) → our dots overlay the chart's
  symbols
- Toggles click-to-build on (7N-d) → clicks the VOR symbol they see
  → it snaps to our data → waypoint added
- Corridor + diverts recompute with the new waypoint

This is the moment the tool feels like a real planner instead of a
demo.

## Edge cases

| Case | Behavior |
|---|---|
| User types `33.0635` alone (no comma) | Treat as airport code; no fallback to lat alone |
| User pastes a comma-separated list `KJFK,KORD,KDEN` | Each token resolved separately, pills appear for all three |
| User clicks ocean (no snap target within 3 NM) | GPS waypoint at literal lat/lon. Label "GPS 28.50°N 70.00°W". |
| Two VORs share an ident (international duplicates) | Prefer US first if user is in CONUS; show both ranked by distance to last route point |
| User clicks a fix symbol but the chart has the fix in a different position than NASR | Snap to nearest NASR fix within 3 NM. Mismatch is a chart-version vs data-version artifact; surface a note: "snapped to nearest NASR fix" |
| Click-to-add toggled ON but user double-clicks | Add waypoint on first click; second click adds another (no de-dup). Edge case: rapid double-add can be undone via the pill × |

## Tests

- `core/waypoints.py` GPS parser: 7 input formats × valid + invalid → ~20 tests
- KDTree nearest-within-radius: synthetic 5-point world, snap correct, snap absent
- NASR navaid loader: parse small fixture CSV, schema validates
- NASR fix loader: same
- Multi-type search: `SAV` returns both airport KSAV and SAV VOR;
  airport ranks first, VOR second
- Click handler: synthetic click → snap-or-GPS-or-none paths

Target: ~25 new tests across the three new test files.

## Acceptance criteria

1. Typing `33.0635,-80.2795` in the Route dropdown adds a GPS
   waypoint pill labeled "GPS 33.06N 80.28W".
2. Typing `SAV` shows both `KSAV` (airport) and `SAV VOR` in the
   dropdown menu with type badges.
3. NASR navaid + fix data ingested via scripted build, normalized
   JSONs land in `data/`.
4. With "Click to add" mode ON, clicking on the map adds a GPS
   waypoint (or snaps to airport/NAVAID/fix within 3 NM).
5. VOR + fix marker layers can be toggled on/off in a LayersControl;
   they don't break when route callbacks fire (the regression we hit
   in Phase 7f doesn't recur because these layers don't re-render).
6. Existing airport-only flow continues to work — no regression on
   the 49k airport DB or the search UX.

## Sequencing notes

Where 7N fits:

```
7k  (winds aloft)               → improves all corridors
7L  (terrain conflict)           → improves all corridor presentation
7M  (multi-engine modeling)      → corrects ME corridor math
7N  (waypoint types + click)    ← THIS — completes the planner UX
8   (slope/openness heatmap)     → off-airport survivability
9   (route critique score)       → aggregate verdict
10  (route detour suggester)     → optimizer (depends on 8 + 9)
```

7N is the architectural completion of the multi-waypoint route work.
After 7N the tool can ingest a typed clearance like "KSAV.WAYNE.KDYB"
and resolve every token correctly, OR a pilot can mouse-build a
route from chart symbols. Either way, all downstream phases (winds,
terrain, ME, heatmap, critique, detour) get richer inputs without
further changes.

## Out of scope

- **Departure / arrival procedures (SIDs / STARs)**. These are
  ARINC-encoded procedure designs, much larger data + parsing
  surface. Different feature.
- **User-defined waypoint sets** (saved "my waypoints" list). Easy
  add later once the click-to-build flow exists.
- **GPX / FlightPlan import.** Easy add later — same resolver
  chain, just read from file.
- **Drag-to-reorder pills.** dcc.Dropdown(multi=True) doesn't
  support drag-reorder natively. A custom pill UI could, but it
  bloats this phase.
