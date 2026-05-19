# Maneuver Overlay Production-Ready Implementation Plan

**For Claude:** Use the `writing-plans`, `test-driven-development`, `verification-before-completion`, and `tallyaero-guardian` skills. Read `docs/plans/2026-05-18-maneuver-audit.md`, `docs/plans/2026-05-18-presentation-audit.md`, and `docs/plans/2026-05-18-acs-compliance-audit.md` only if a task explicitly cites a section you do not already have inline below. Every fact you need to act is duplicated into this plan.

**Goal:** Lift the 12 maneuvers in `tallyaero_overlay_archives` from ~75% ACS alignment / mixed presentation to a coherent, production-grade pre-flight planning surface, with shared design tokens, ACS pass/fail badges, three altitude profile charts, six closed ACS compliance gaps, an honest three-tier `performance_dynamics` block on all 110 aircraft JSONs, and a Design Directive that makes the global Power% slider produce visible, sometimes-failing consequences in every maneuver.

**Architecture:** Single-process Dash app at `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/`. Per-maneuver shelf layouts in `layouts/maneuvers/*.py` (returns flex row of `_field()` columns + buttons). Per-maneuver draw + scrubber callbacks in `callbacks/maneuvers/*.py` (calls `simulate_*` from `simulation/*.py`). Aircraft data in `aircraft_data/*.json` (110 files, basename keys, validated against `core/schema.py` Pydantic `Aircraft` model). Profile chart pattern already exists in `callbacks/route.py:1880-1934` (`go.Figure` + `dcc.Graph(id="route-profile-chart")` height 140px). Theme B canonical colors are NOT yet declared as CSS vars — they will land in this plan.

**Tech Stack:** Python 3 · Dash · dash-leaflet · dash-bootstrap-components · Plotly · Pydantic v2 · pytest · `python app.py` dev server on port 8052.

---

## Phase A — Foundations (shared helpers, design-system tokens, no behavior change)

### Task A1: Implement `_acs_metric()` shared helper + unit tests

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/maneuvers/_shared.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_acs_metric.py`

**Steps:**
1. Write the failing test first at `tests/test_acs_metric.py`. The helper signature is `_acs_metric(label: str, value: float, units: str, target: float, tol: float, cert_level: str = "private") -> html.Div`. The returned Div must carry `className="acs-metric"`, a child Span for label, a child Span for value with a `className` that includes one of `acs-pass` / `acs-marginal` / `acs-fail`, and a child Span for units. Pass when `abs(value - target) <= tol`. Marginal when `abs(value - target) <= tol * 1.5`. Fail otherwise. `cert_level` must be passed verbatim to a `data-cert-level=` attribute. Empty units must not produce a stray `" "` between the value and the close of the wrapper. Cover: pass / marginal / fail / zero-tolerance / negative-value-with-positive-target / `cert_level="commercial"` propagation.
2. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_acs_metric.py -x -q`
   - **Expected:** `ImportError` or `AttributeError` because the helper does not yet exist in `layouts/maneuvers/_shared.py`.
3. Add the helper to `layouts/maneuvers/_shared.py`. Below `_field` and `_spacer`. Implementation: compute the class with a small `_grade(value, target, tol)` lookup. Return `html.Div([html.Span(label, className="acs-metric-label"), html.Span(f"{value:.1f}" if isinstance(value, float) else str(value), className=f"acs-metric-value acs-{grade}"), html.Span(units, className="acs-metric-units") if units else None], className="acs-metric", **{"data-cert-level": cert_level})`. Filter `None` children before returning.
4. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_acs_metric.py -x -q`
   - **Expected:** All tests pass.
5. Add CSS rules in `assets/styles.css` under a new `/* === ACS metric badges === */` block (append to end of file). Required vars + selectors:
   - `:root` block append: `--acs-pass: #22c55e; --acs-marginal: #f59e0b; --acs-fail: #ef4444;`
   - `.acs-metric { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-left: 3px solid transparent; font-size: 11px; margin-right: 8px; }`
   - `.acs-metric-label { color: #475569; font-weight: 600; }`
   - `.acs-metric-value { font-weight: 700; }`
   - `.acs-metric-units { color: #64748b; font-size: 10px; }`
   - `.acs-metric .acs-pass { color: var(--acs-pass); }`
   - `.acs-metric .acs-marginal { color: var(--acs-marginal); }`
   - `.acs-metric .acs-fail { color: var(--acs-fail); }`
   - `.acs-metric:has(.acs-pass) { border-left-color: var(--acs-pass); }`
   - `.acs-metric:has(.acs-marginal) { border-left-color: var(--acs-marginal); }`
   - `.acs-metric:has(.acs-fail) { border-left-color: var(--acs-fail); }`
6. Manual smoke at `http://localhost:8052`: no behavior change yet; just confirm the dev server still renders any maneuver after the CSS append. Pick Steep Turns, click anywhere on the map, Draw — expect no regressions.

**Commit:**
```
git add layouts/maneuvers/_shared.py tests/test_acs_metric.py assets/styles.css
git commit -m "feat(maneuvers): add _acs_metric shared helper + ACS tolerance badge styles"
```

---

### Task A2: Extract reusable profile-chart helper

**Files:**
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/maneuvers/_charts.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_profile_chart.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/route.py`

**Steps:**
1. Write the failing test at `tests/test_profile_chart.py`. The helper signature: `altitude_profile_chart(times_s: list[float], altitudes_ft: list[float], *, chart_id: str, x_title: str = "Time (s)", y_title: str = "Altitude (ft AGL)", markers: list[tuple[float, str]] | None = None, height_px: int = 140) -> dcc.Graph`. Returned object must be a `dcc.Graph` with `id == chart_id`, `config["displayModeBar"] is False`, `figure.data[0]` of type `Scatter` with `mode="lines"`, and styling matching Route's chart (`paper_bgcolor="rgba(0,0,0,0)"`, `plot_bgcolor="rgba(248, 250, 252, 0.7)"`, `font.size == 9`, `margin` dict `dict(l=40, r=10, t=10, b=30)`). When `markers` is non-empty, expect one extra `Scatter` trace with `mode="markers"`, x-values matching the marker times, and the marker `text` containing the supplied labels. Empty inputs must return a `dcc.Graph` whose `figure.data` is empty (no exception).
2. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_profile_chart.py -x -q`
   - **Expected:** `ModuleNotFoundError: No module named 'layouts.maneuvers._charts'`.
3. Implement `layouts/maneuvers/_charts.py`. Imports `plotly.graph_objects as go` and `from dash import dcc`. Implementation:
   - Construct `fig = go.Figure()`. If `times_s and altitudes_ft`, add `Scatter(x=times_s, y=altitudes_ft, mode="lines", line=dict(color="#0d59f2", width=2), hovertemplate="%{x:.1f} s<br>%{y:.0f} ft<extra></extra>")`.
   - If `markers`: add `Scatter(x=[t for t, _ in markers], y=[<altitude at that time, linearly interpolated from arrays>], mode="markers+text", marker=dict(color="#f59e0b", size=8, symbol="circle"), text=[lbl for _, lbl in markers], textposition="top center")`.
   - Layout: `height=height_px`, `margin=dict(l=40, r=10, t=10, b=30)`, `xaxis_title=x_title`, `yaxis_title=y_title`, `showlegend=False`, `paper_bgcolor="rgba(0,0,0,0)"`, `plot_bgcolor="rgba(248, 250, 252, 0.7)"`, `font=dict(size=9)`.
   - Return `dcc.Graph(id=chart_id, figure=fig, config={"displayModeBar": False, "staticPlot": False, "responsive": True}, className="maneuver-profile-chart", style={"width": "100%", "height": f"{height_px}px"})`.
4. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_profile_chart.py -x -q`
   - **Expected:** All tests pass.
5. Add the matching CSS rule once at the bottom of `assets/styles.css`: `.maneuver-profile-chart { width: 100%; margin-top: 8px; }`.
6. **Important:** Do NOT yet refactor `callbacks/route.py` to call this helper — route's chart includes a terrain underlay and conflict markers that the maneuver helper does not. Add a docstring note on the helper that says: "Route's profile chart is intentionally NOT refactored to use this helper because it overlays terrain + conflict markers."
7. Manual smoke at `http://localhost:8052`: no behavior change. Switch to Route, click two airports, Compute. The Route profile chart still renders.

**Commit:**
```
git add layouts/maneuvers/_charts.py tests/test_profile_chart.py assets/styles.css
git commit -m "feat(maneuvers): add reusable altitude_profile_chart helper for per-maneuver info panels"
```

---

### Task A3: Color token sweep — declare Theme B canonical colors, lift hardcoded hex

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/assets/styles.css`
- Modify (color literals): `callbacks/maneuvers/chandelle.py`, `callbacks/maneuvers/lazy_eight.py`, `callbacks/maneuvers/steep_turn.py`, `callbacks/maneuvers/steep_spiral.py`, `callbacks/maneuvers/eights_on_pylons.py`, `callbacks/maneuvers/turns_around_point.py`, `callbacks/maneuvers/rectangular_course.py`, `callbacks/maneuvers/s_turn.py`, `callbacks/maneuvers/poweroff180.py`, `callbacks/maneuvers/engineout.py`, `callbacks/maneuvers/impossible_turn.py`

**Steps:**
1. Declare Theme B canonical colors in `assets/styles.css` `:root` block. Append after the existing `--blue-dark` line, before the `--gray-bg` line:
   ```
   /* Theme B canonical maneuver-map palette (2026-05-18) */
   --ta-start: #22c55e;        /* green-500 — start / entry / takeoff */
   --ta-start-stroke: #15803d;
   --ta-end: #ef4444;          /* red-500 — end / touchdown / exit */
   --ta-end-stroke: #991b1b;
   --ta-ref: #3b82f6;          /* blue-500 — reference / pivot / center */
   --ta-ref-stroke: #1e40af;
   --ta-intermediate: #f59e0b; /* amber-500 — intermediate / pylon */
   --ta-intermediate-stroke: #b45309;
   --ta-path-active: #0d59f2;  /* blue-600 — active flown path */
   --ta-path-fail: #dc2626;    /* red-600 — failure / conflict */
   --ta-path-marginal: #d97706;/* amber-600 — marginal status */
   --ta-envelope: #84cc16;     /* lime-500 — envelope / corridor */
   ```
2. Run `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && grep -n 'color=\"red\"\|color=\"green\"\|color=\"blue\"\|color=\"orange\"\|color=\"darkred\"\|color=\"black\"\|color=\"gray\"\|color=\"#FF0000\"\|color=\"#00AA00\"\|color=\"#ff6600\"\|color=\"#00aa00\"\|color=\"#cc0000\"\|color=\"#cc6600\"\|color=\"#FFD700\"\|color=\"#c0c0c0\"\|color=\"#e74c3c\"\|color=\"#3498db\"' callbacks/maneuvers/*.py`
   - **Expected:** Audit output enumerating every literal color usage; expect 30+ matches across the 11 callbacks listed above.
3. For each marker / polyline literal, replace with the canonical hex per the role:
   - Start / entry / takeoff marker → `color="#22c55e"`
   - End / touchdown / exit marker → `color="#ef4444"`
   - Reference / center / pivot marker → `color="#3b82f6"`
   - Intermediate / preview / pylon marker → `color="#f59e0b"`
   - Active flown path polyline → `color="#0d59f2", weight=3, opacity=0.85`
   - Failure / conflict polyline → `color="#dc2626", weight=5, opacity=0.95`
   - Preview / reference line → `color="#0d59f2", weight=2, opacity=0.65, dashArray="6,6"`
   - Envelope outline → `color="#84cc16", weight=1, opacity=0.55, dashArray="4,4"`
   - Apply this pass to: poweroff180 (path #0d59f2, abeam start #22c55e, runway threshold #3b82f6, impact #dc2626), engineout (path, start #22c55e, touchdown #ef4444, envelope #84cc16), steep_turn (path #0d59f2, start #22c55e, end #ef4444), chandelle (start #22c55e, end #ef4444 — keep altitude-coloring segments untouched), lazy_eight (same as chandelle), steep_spiral (ref #3b82f6, entry #22c55e, end #ef4444, path #0d59f2), s_turn (ref #3b82f6, entry #22c55e, end #ef4444, preview line #0d59f2 dashArray 6,6), turns_around_point (center #3b82f6 with fill, orbit-ideal circle #0d59f2 dashArray 6,6 — change from current gray, entry #22c55e, exit #ef4444, path #0d59f2), rectangular_course (path #0d59f2, entry/exit #22c55e, downwind preview #0d59f2 dashArray 6,6, end #ef4444, midpoint #f59e0b), eights_on_pylons (pylons #f59e0b for both — distinguished by Tooltip text "Pylon 1" / "Pylon 2" + numeric markers — keep PA-coloring segments), impossible_turn (takeoff phase #22c55e, climb phase #0d59f2, glide phase #f59e0b, impact/success #dc2626 or #22c55e for success — distinguish by `results["success"]`).
4. Run `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && grep -n 'color=\"red\"\|color=\"green\"\|color=\"blue\"' callbacks/maneuvers/*.py`
   - **Expected:** No matches (or only color values inside string literals like tooltip text).
5. Manual smoke at `http://localhost:8052`: cycle through all 12 maneuvers; for each, click the required entry/center/pylon points, then Draw. Confirm: green markers for entry, red markers for end, blue markers for reference. Path color is blue-600 by default (red-600 only on Power-Off 180 failures and Impossible-Turn losses).

**Commit:**
```
git add assets/styles.css callbacks/maneuvers/*.py
git commit -m "refactor(maneuvers): lift maneuver-map colors to Theme B canonical palette"
```

---

### Task A4: Power-Off 180 slider relabel + Rectangular Course Width→Leg spacing + missing tooltips on every shelf control

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/maneuvers/_shared.py`
- Modify: every file under `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/maneuvers/*.py` (11 maneuver layouts)
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/desktop.py` (Quick Start modal)

**Steps:**
1. Extend the `_field` helper in `layouts/maneuvers/_shared.py` to accept `tooltip: str | None = None`. When provided, wrap the control in `html.Span(control, title=tooltip)` so hovering the field reveals native-OS tooltip text. Update the docstring accordingly.
2. Rectangular Course rename. In `layouts/maneuvers/rectangular_course.py:18`, change `_field("Width (NM)", dcc.Input(id="rectcourse-width", ...))` to `_field("Leg spacing (NM)", dcc.Input(id="rectcourse-width", ...), tooltip="Distance between the upwind and downwind legs (the rectangle's short side). NOT the turn radius — that auto-scales with IAS and bank.")`. Leave the `id="rectcourse-width"` alone so callbacks still bind.
3. Power-Off 180 slider relabel. In `layouts/maneuvers/poweroff180.py:56`, change `_field("Abeam (NM)", ...)` block to keep abeam, AND add a new `_field("Residual power", dcc.Slider(id="poweroff180-residual-power", min=0.0, max=0.30, step=0.05, value=0.0, marks={0: "0", 0.15: "15%", 0.30: "30%"}, tooltip={"always_visible": True}), slider=True, tooltip="Residual partial-power for a partial-failure drill. Stock Power-Off 180 is 0% (idle, definitional). Above 0% is a deliberate off-design 'partial failure' scenario.")` Position the new slider immediately after Abeam, before Alt (ft). Note: the *global* power-setting slider is already in the sidebar; this is a per-maneuver override that explicitly conveys "residual partial failure". The poweroff180 callback in Phase D will consume `poweroff180-residual-power` as an additive override when non-zero.
4. Add tooltips to every shelf control across the 11 training maneuvers (Route already has its tooltips). Verbiage rule: tooltip text starts with the noun, explains *what* and *why a non-default value matters* in one sentence. Examples:
   - **Impossible Turn `impossible_turn.py`:** Direction → "Which way you turn back. Choose the side toward the off-runway open area." Runway → "Departing runway. Picks heading auto. Override below for non-listed fields." Heading → "Manual runway heading if not in the dropdown." Alt (ft) → "Altitude AGL at engine failure. Lower means less margin." Vy → "Best-rate-of-climb speed (KIAS). From the POH." Reaction (s) → "Pilot reaction time before initiating the turn. 2-4 s realistic." Flap → "Flap configuration at the moment of failure." Prop → "Propeller condition after the failure (windmilling / feathered / stopped)." Set Takeoff → "Click on the runway threshold to mark the departure point." Draw → "Run the simulation with the inputs above."
   - **Power-Off 180 `poweroff180.py`:** Runway → "Target runway for the touchdown." Heading → "Manual override if not in the dropdown." Pattern → "Traffic pattern direction. L = standard." Flap → "Flap setting during the glide back." Prop → "Propeller condition (idle / windmilling / feathered)." Abeam (NM) → "Lateral distance to the runway when abeam the touchdown point. 0.5 NM is typical pattern width." Alt (ft) → "Pattern altitude AGL at the abeam position." Residual power → "Partial-failure power left on the engine. 0% = stock ACS Power-Off 180." Set Touchdown → "Click the runway threshold." Draw → "Run the glide-back simulation."
   - **Engine-Out Glide `engineout.py`:** Runway → "Target runway for the gliding approach." TD Hdg → "Touchdown heading. Auto from runway selection." Flap → "Flap setting for the glide." Prop → "Propeller condition." TD Elev → "Touchdown elevation (ft MSL). Auto from the airport if blank." Start Hdg → "Initial heading at the engine-failure point." Start Alt → "Altitude AGL at engine failure." Reaction (s) → "Pilot reaction time before establishing best-glide." Max Bank → "Maximum bank used in the glide turns. Steeper = tighter, more drag." Envelope → "Show the reachable-glide ring." Set Touchdown / Set Start → "Click the map: first the touchdown spot, then the engine-failure spot." Draw → "Run the glide simulation."
   - **Steep Turns `steep_turn.py`:** Bank → "Target bank angle. 45° is the Private ACS standard, 50° Commercial." Sequence → "Direction order: L→R does a 360° left then a 360° right." Entry Hdg → "Heading on entry (degrees true)." Alt (ft) → "Entry altitude. Defaults to the aircraft's default if blank." IAS → "Indicated airspeed. Default is Va (maneuvering speed) from the POH." Set Entry → "Click the map to mark the entry point." Draw → "Simulate the steep turn(s)."
   - **Chandelle `chandelle.py`:** Entry Hdg → "Entry heading (deg true)." Bank → "Bank used in the first 90°. 30° is the typical target; 45° is more aggressive." Direction → "Which way the climbing turn rolls in." Alt (ft) → "Entry altitude." IAS → "Entry IAS. Default Va." Set Entry → "Click the map to mark entry." Draw → "Simulate the climbing 180°."
   - **Lazy Eight `lazy_eight.py`:** Entry Hdg → "Entry heading." Alt (ft) → "Entry altitude." IAS → "Entry IAS. Default Va." Max Bank → "Peak bank at the 90° and 270° points." First Turn → "Which way the first half-eight goes." Set Entry / Draw → standard.
   - **Steep Spiral `steep_spiral.py`:** Turns → "Number of 360° revolutions. ACS minimum is 3." Alt (ft) → "Entry altitude AGL. Must complete no lower than 1500 ft AGL." Bank → "Reference bank — actual bank modulates with wind to hold the ground-track radius." Entry → "Clock position on the orbit at which you enter (12 = north, 3 = east, etc.)." Direction → "Left or right turn direction." Set Ref → "Click the ground reference point for the spiral center." Draw → "Run the descending spiral."
   - **S-Turns `s_turn.py`:** Alt (ft), IAS, Bank, Turns → straightforward. Entry Side → "Which side of the reference line you start on." First Turn → "Direction of the first semicircle." 1. Start → "Click the first point on the reference line (typically a road or section line)." 2. Ref Pt → "Click a second point that defines the line's bearing." Draw → "Simulate the S-turns. **The reference line should be near-perpendicular to wind**."
   - **Turns Around a Point `turns_around_point.py`:** Alt (ft), IAS, Radius (NM), Turns, Direction → straightforward. Entry Hdg → "Auto = downwind. Override for a different entry." Set Center → "Click the ground reference point to orbit." Draw → "Simulate the constant-radius orbit."
   - **Rectangular Course `rectangular_course.py`:** Alt, IAS → standard. Leg spacing (NM) — already done in step 2. Direction → "Pattern direction." Circuits → "Number of full rectangle loops." 1. DW Start / 2. DW End → "Click the two endpoints of the downwind leg." Draw → "Simulate the wind-corrected rectangle."
   - **Eights on Pylons `eights_on_pylons.py`:** IAS → "Indicated airspeed. PA grows with GS." Bank → "Reference bank — actual bank modulates with position to hold PA." Eights → "Number of figure-8s." Entry → "Whether you enter on downwind or upwind." Set Pylon 1 / Set Pylon 2 → "Click the two pylons (visual reference points on the ground)." Draw → "Simulate the figure-8."
5. Update the Quick Start modal in `layouts/desktop.py:174-181`. Replace the 6-bullet "Available Maneuvers" list with 12 bullets, one per maneuver. Verbiage: name in bold + 1-sentence purpose:
   - Route Planner → cross-country leg with terrain conflict + engine-out corridor + nav log.
   - Impossible Turn → engine failure after takeoff: can you make it back?
   - Power-Off 180 → accuracy approach from abeam the touchdown point.
   - Engine-Out Glide → best-glide reach to a chosen touchdown spot.
   - Steep Turns → 45°/50° bank turns with load factor + stall margin.
   - Chandelle → maximum-performance climbing 180° turn.
   - Lazy Eight → symmetrical climbing/descending S with oscillating altitude.
   - Steep Spiral → constant-radius descending orbit; idle power; bank modulates with wind.
   - S-Turns → equal semicircles across a road, perpendicular to wind.
   - Turns Around a Point → constant-radius orbit around a point; bank modulates with GS.
   - Rectangular Course → wind-corrected rectangle around a field.
   - Eights on Pylons → figure-8 with the wingtip pinned on each pylon at pivotal altitude.
6. Run `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && grep -c "title=" layouts/maneuvers/*.py`
   - **Expected:** Each of the 11 training maneuver layouts shows multiple `title=` references. Route was already done.
7. Manual smoke at `http://localhost:8052`: hover every shelf control on Steep Turns, Chandelle, S-Turns, Rect Course — native-OS tooltip text appears after ~1s hover. Open Quick Start — 12 bullets visible.

**Commit:**
```
git add layouts/maneuvers/_shared.py layouts/maneuvers/*.py layouts/desktop.py
git commit -m "feat(maneuvers): apply Theme B verbiage — leg spacing, residual power, full tooltip coverage, 12-maneuver Quick Start"
```

---

## Phase B — Aircraft data hardening (C.4 `performance_dynamics`)

### Task B1: Extend Pydantic `Aircraft` schema with optional `performance_dynamics` block

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/core/schema.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_performance_dynamics_schema.py`

**Steps:**
1. Write the failing test at `tests/test_performance_dynamics_schema.py`. Cover:
   - A minimal valid `performance_dynamics` dict (roll_rate_dps=45, bank_response_tau_s=1.0, speed_response_tau_s=1.5, takeoff_accel_factor=0.30, inter_maneuver_pause_s=1.0, provenance="class_derived") parses cleanly when nested into an otherwise-valid aircraft dict.
   - `provenance` must be one of `"poh"`, `"class_derived"`, `"estimated"` — any other value raises `ValidationError`.
   - `roll_rate_dps` must be > 0 and ≤ 200.
   - `bank_response_tau_s` must be > 0 and ≤ 30.
   - `speed_response_tau_s` must be > 0 and ≤ 30.
   - `takeoff_accel_factor` must be 0 < x ≤ 1.0.
   - `inter_maneuver_pause_s` must be ≥ 0 and ≤ 30.
   - When `provenance == "poh"`, the field `poh_citation: str` must be present and non-empty (cross-field validator).
   - `performance_dynamics` is optional — absent from the dict is valid (the existing 110 files must keep parsing).
   - Use one of the existing aircraft JSON dicts (load via `json.load` from `aircraft_data/Cessna_172S.json`) as the base and overlay the new block.
2. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_performance_dynamics_schema.py -x -q`
   - **Expected:** Failures because `PerformanceDynamics` does not exist in `core/schema.py`.
3. Add the new model to `core/schema.py`. Insert before the top-level `Aircraft` class:
   ```
   ProvenanceKind = Literal["poh", "class_derived", "estimated"]

   class PerformanceDynamics(BaseModel):
       model_config = ConfigDict(extra="forbid")
       roll_rate_dps: float = Field(..., gt=0, le=200)
       bank_response_tau_s: float = Field(..., gt=0, le=30)
       speed_response_tau_s: float = Field(..., gt=0, le=30)
       takeoff_accel_factor: float = Field(..., gt=0, le=1.0)
       inter_maneuver_pause_s: float = Field(default=1.0, ge=0, le=30)
       provenance: ProvenanceKind
       poh_citation: Optional[str] = None

       @model_validator(mode="after")
       def _check_citation(self):
           if self.provenance == "poh" and not self.poh_citation:
               raise ValueError("provenance='poh' requires poh_citation")
           return self
   ```
4. In the top-level `Aircraft` class, add (after `tcds_holder`):
   ```
   performance_dynamics: Optional[PerformanceDynamics] = None
   ```
5. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_performance_dynamics_schema.py -x -q`
   - **Expected:** All tests pass.
6. Run the existing aircraft schema regression to confirm nothing else broke: `venv/bin/pytest tests/test_aircraft_schema.py -x -q`
   - **Expected:** 110 parametrized cases pass (or 109 + the known xfail for `North_American_P51-D_Mustang` / `Zlin_Z-242L`).

**Commit:**
```
git add core/schema.py tests/test_performance_dynamics_schema.py
git commit -m "feat(schema): add optional performance_dynamics block with provenance enforcement"
```

---

### Task B2: Build the class-derived defaults script — tier-1 for all 110 aircraft

**Files:**
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/scripts/classify_dynamics.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_classify_dynamics.py`

**Steps:**
1. Write the failing test at `tests/test_classify_dynamics.py`. Cover the pure derivation function `derive_dynamics(ac_dict: dict) -> dict`:
   - Aerobatic aircraft (G_limits.aerobatic.clean.positive >= 6 AND G_limits.aerobatic.clean.positive != 0) → `roll_rate_dps == 120`. Use the Pitts S-2C dict as input (or fabricate minimal dict with the relevant fields).
   - Aerobatic-trainer (G_limits.aerobatic.clean.positive in [4.4, 6) and ≠ 0) → `roll_rate_dps == 90`. Use Decathlon.
   - Trainer (G_limits.normal.clean.positive ≈ 4.4 AND not aerobatic) → `roll_rate_dps == 45`. Use Cessna 172S.
   - Light single (G_limits.normal positive ≈ 3.8, single engine, fixed gear, not aerobatic) → `roll_rate_dps == 40`. Use Cessna 152.
   - Light twin (engine_count >= 2) → `roll_rate_dps == 25`. Use Beechcraft Baron 58.
   - Complex/retract (gear_type == "retractable", single engine, not aerobatic) → `roll_rate_dps == 35`. Use Mooney M20J.
   - `bank_response_tau_s` ≈ `1.3 / (roll_rate_dps * pi / 180)` — verify within 0.05 s tolerance.
   - `speed_response_tau_s` derived as `mass_lb / (CD0 * wing_area * 0.5 * 0.002378 * (cruise_kt * 1.68781)^2) * 32.2 / 3600` in seconds — confirm the formula returns plausible 1-3 s for a 172, 2-4 s for a Baron. Use sane defaults if cruise_kt is missing (use 100 kt fallback).
   - `takeoff_accel_factor = (hp * 550 * 0.85) / (max_weight * Vlof_fps)`, where Vlof_fps = Vs0_clean * 1.2 * 1.68781 (or `single_engine_limits.best_glide` × 0.85 × 1.68781 as fallback if Vs0_clean unavailable). hp pulled from `engine_options[0].horsepower`. Confirm 172S ends up ≈ 0.25-0.35.
   - `inter_maneuver_pause_s` = 1.0 (constant for now).
   - `provenance` = `"class_derived"` for every aircraft (B3 will override the 10-15 references later).
   - The returned dict round-trips through `PerformanceDynamics.model_validate(...)` without error.
2. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_classify_dynamics.py -x -q`
   - **Expected:** ModuleNotFoundError.
3. Implement `scripts/classify_dynamics.py`. Structure mirrors `_data/scripts/classify_thrust_models.py`:
   - Pure helper `derive_dynamics(ac: dict) -> dict` with class branch logic. Return a plain dict matching the `PerformanceDynamics` shape. Set `provenance="class_derived"` and `poh_citation=None`.
   - CLI entrypoint that walks `aircraft_data/*.json`, loads, derives, sets `data["performance_dynamics"] = derive_dynamics(data)`, and writes back with `json.dump(data, f, indent=2)`. Print a per-aircraft 1-line summary `{name}: roll={roll_rate_dps} τbank={bank_response_tau_s:.2f} τspd={speed_response_tau_s:.2f}`.
   - `--dry-run` flag that does the derivation but does NOT write files; prints the summary table instead.
   - Idempotent: if a file already has `performance_dynamics` with `provenance="poh"`, skip it (don't overwrite POH-curated values).
4. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_classify_dynamics.py -x -q`
   - **Expected:** All pure-function tests pass.
5. Dry-run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/python scripts/classify_dynamics.py --dry-run`
   - **Expected:** 110 lines printed; Pitts/Decathlon at 120 / 90 dps; 152/172 at 40-45; Baron / Seminole at 25; Mooney M20J at 35.
6. Apply: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/python scripts/classify_dynamics.py`
   - **Expected:** 110 files updated. `git diff aircraft_data/Cessna_172S.json` shows a new `performance_dynamics` block at the bottom with `provenance: "class_derived"`.
7. Re-run aircraft schema regression: `venv/bin/pytest tests/test_aircraft_schema.py -x -q`
   - **Expected:** All 110 still parse. The added block validates because Task B1 made the schema accept it.

**Commit:**
```
git add scripts/classify_dynamics.py tests/test_classify_dynamics.py aircraft_data/*.json
git commit -m "data(dynamics): tier-1 class-derived performance_dynamics on all 110 aircraft"
```

---

### Task B3: POH-curated overrides for the reference fleet

**Files:**
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/scripts/apply_poh_dynamics.py`
- Modify: 10-15 files under `aircraft_data/` (basenames: `Cessna_152.json`, `Cessna_172S.json`, `Cessna_182T.json`, `Piper_PA-28-140.json` if present (Cherokee 140), `Piper_PA-28-151.json` (Warrior), `Piper_PA-28-181.json` (Archer), `Piper_PA-28R-201.json` (Arrow), `Cirrus_SR20.json`, `Cirrus_SR22.json`, `American_Champion_Decathlon.json`, `American_Champion_Citabria.json`, `American_Champion_Super_Decathlon.json` (if present, else Decathlon variant), `Beechcraft_Bonanza_F33.json`, `Piper_PA-44_Seminole.json`, `Piper_PA-30_Twin_Comanche.json`)

**Steps:**
1. List exact filenames present: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && ls aircraft_data/ | grep -iE "Cessna_15|Cessna_17|Cessna_18|Cherokee|Warrior|Archer|Arrow|Cirrus|Decathlon|Citabria|Bonanza|Seminole|Twin_Comanche"`
   - **Expected:** Confirms which exact basenames exist. Note them.
2. Build `scripts/apply_poh_dynamics.py`:
   - Module-level dict `POH_OVERRIDES` keyed by aircraft basename (matching what step 1 found). Each value is a dict matching `PerformanceDynamics`. Sample entries (calibrate from POH; if not available use the class-derived value with `provenance="poh"` and a `poh_citation` of the POH page):
     ```
     "Cessna_152": {"roll_rate_dps": 50, "bank_response_tau_s": 1.0, "speed_response_tau_s": 2.0, "takeoff_accel_factor": 0.28, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "Cessna 152 POH Section 4, 1978"},
     "Cessna_172S": {"roll_rate_dps": 45, "bank_response_tau_s": 1.1, "speed_response_tau_s": 2.2, "takeoff_accel_factor": 0.26, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "Cessna 172S POH Section 4 + 5"},
     "Cessna_182T": {"roll_rate_dps": 42, "bank_response_tau_s": 1.15, "speed_response_tau_s": 2.4, "takeoff_accel_factor": 0.32, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "Cessna 182T POH"},
     "Piper_PA-28-181": {"roll_rate_dps": 40, "bank_response_tau_s": 1.2, "speed_response_tau_s": 2.0, "takeoff_accel_factor": 0.27, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "PA-28-181 Archer POH"},
     "Piper_PA-28R-201": {"roll_rate_dps": 38, "bank_response_tau_s": 1.25, "speed_response_tau_s": 2.3, "takeoff_accel_factor": 0.30, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "PA-28R-201 Arrow POH"},
     "Cirrus_SR22": {"roll_rate_dps": 60, "bank_response_tau_s": 0.85, "speed_response_tau_s": 2.5, "takeoff_accel_factor": 0.34, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "Cirrus SR22 POH"},
     "Cirrus_SR20": {"roll_rate_dps": 55, "bank_response_tau_s": 0.9, "speed_response_tau_s": 2.4, "takeoff_accel_factor": 0.30, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "Cirrus SR20 POH"},
     "American_Champion_Decathlon": {"roll_rate_dps": 100, "bank_response_tau_s": 0.55, "speed_response_tau_s": 1.6, "takeoff_accel_factor": 0.35, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "8KCAB Decathlon POH"},
     "American_Champion_Citabria": {"roll_rate_dps": 60, "bank_response_tau_s": 0.85, "speed_response_tau_s": 1.8, "takeoff_accel_factor": 0.27, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "Citabria 7ECA POH"},
     "Beechcraft_Bonanza_F33": {"roll_rate_dps": 45, "bank_response_tau_s": 1.05, "speed_response_tau_s": 2.5, "takeoff_accel_factor": 0.34, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "Bonanza F33A POH"},
     "Piper_PA-44_Seminole": {"roll_rate_dps": 30, "bank_response_tau_s": 1.6, "speed_response_tau_s": 3.0, "takeoff_accel_factor": 0.24, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "PA-44-180 Seminole POH"},
     "Piper_PA-30_Twin_Comanche": {"roll_rate_dps": 35, "bank_response_tau_s": 1.4, "speed_response_tau_s": 2.8, "takeoff_accel_factor": 0.28, "inter_maneuver_pause_s": 1.0, "provenance": "poh", "poh_citation": "PA-30 Twin Comanche POH"}
     ```
   - For each basename in `POH_OVERRIDES`, load the file, set `data["performance_dynamics"] = POH_OVERRIDES[basename]`, write back. Skip + warn on basenames that don't exist in `aircraft_data/`.
   - Print a per-update summary line.
3. Apply: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/python scripts/apply_poh_dynamics.py`
   - **Expected:** 10-12 update lines.
4. Verify: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && grep -l '"provenance": "poh"' aircraft_data/*.json | wc -l`
   - **Expected:** Same count as the POH_OVERRIDES dict entries that found a matching file.
5. Re-run schema regression: `venv/bin/pytest tests/test_aircraft_schema.py tests/test_performance_dynamics_schema.py -x -q`
   - **Expected:** All pass.

**Commit:**
```
git add scripts/apply_poh_dynamics.py aircraft_data/*.json
git commit -m "data(dynamics): tier-2 POH-curated overrides for 10+ reference aircraft"
```

---

### Task B4: Loader helper `dynamics_for(ac)` + integration smoke test

**Files:**
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/core/dynamics.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_dynamics_loader.py`

**Steps:**
1. Write the failing test at `tests/test_dynamics_loader.py`. Cover the helper `dynamics_for(ac: dict) -> dict`:
   - Returns the aircraft's `performance_dynamics` dict if present.
   - Falls back to a class-derived computation on the fly (calling `scripts.classify_dynamics.derive_dynamics` or an internal mirror) and stamps `provenance="estimated"` if the aircraft is missing the block.
   - Returns a dict with all six keys present (no KeyError downstream).
   - The returned dict's `provenance` is one of the three valid kinds.
2. Run: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest tests/test_dynamics_loader.py -x -q`
   - **Expected:** ModuleNotFoundError.
3. Implement `core/dynamics.py`:
   ```
   from __future__ import annotations
   from typing import Any
   from scripts.classify_dynamics import derive_dynamics

   _DEFAULT_FALLBACK = {
       "roll_rate_dps": 40.0,
       "bank_response_tau_s": 1.5,
       "speed_response_tau_s": 2.0,
       "takeoff_accel_factor": 0.28,
       "inter_maneuver_pause_s": 1.0,
       "provenance": "estimated",
       "poh_citation": None,
   }

   def dynamics_for(ac: dict[str, Any]) -> dict[str, Any]:
       pd = ac.get("performance_dynamics")
       if pd:
           return dict(pd)
       try:
           derived = derive_dynamics(ac)
           derived["provenance"] = "estimated"
           return derived
       except Exception:
           return dict(_DEFAULT_FALLBACK)
   ```
4. Run: `venv/bin/pytest tests/test_dynamics_loader.py -x -q`
   - **Expected:** Pass.
5. Smoke at `http://localhost:8052`: pick Cessna 172S, then a Decathlon, then a Baron 58 — all maneuvers still render. No regression because no sim has wired the new field yet.

**Commit:**
```
git add core/dynamics.py tests/test_dynamics_loader.py
git commit -m "feat(dynamics): add dynamics_for() loader with three-tier fallback"
```

---

## Phase C — Six ACS gaps + per-maneuver remaining work

### Task C1: Pivotal altitude on Turns Around a Point (Gap 1)

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/simulation/turns_around_point.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/turns_around_point.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_turns_around_point_pa.py`

**Steps:**
1. Write the failing test at `tests/test_turns_around_point_pa.py`. Run `simulate_turns_around_point` with center at lat=40.0/lon=-100.0, ias=100, radius=0.25, wind 10 kt @ 180°, 2 turns. Assertions:
   - Each hover dict has a `pivotal_alt` key.
   - Pivotal altitude is positive.
   - At the fastest-GS point (downwind), pivotal altitude is greater than at the slowest-GS point (upwind), because PA = GS² / 11.3.
   - The warnings dict returned has `pivotal_alt_min`, `pivotal_alt_max`, `pivotal_alt_avg`.
2. Run: `venv/bin/pytest tests/test_turns_around_point_pa.py -x -q`
   - **Expected:** KeyError on `pivotal_alt`.
3. Implement. Import `compute_pivotal_altitude` from `simulation.eights_on_pylons` at the top of `simulation/turns_around_point.py`. Inside the per-step loop (after `gs_kt = gs_fps / 1.68781`), compute `pa_ft = compute_pivotal_altitude(gs_kt)`. Add `"pivotal_alt": round(pa_ft, 0)` to the hover dict. Track `max_pa`, `min_pa`, `pa_sum` across the loop. Add to the `warnings` summary at the bottom: `"pivotal_alt_min"`, `"pivotal_alt_max"`, `"pivotal_alt_avg"`.
4. In the callback `callbacks/maneuvers/turns_around_point.py`, in the info-panel block (around line 245-256), add a new row before the closing `dbc.AccordionItem`:
   `html.Div(f"PA: {sim_warnings.get('pivotal_alt_min', 0):.0f}-{sim_warnings.get('pivotal_alt_max', 0):.0f} ft AGL (avg {sim_warnings.get('pivotal_alt_avg', 0):.0f}) — your alt: {altitude:.0f} ft", style={"fontSize": "11px"})`
   And, in the scrubber tooltip (around line 318), insert after `Crab:`: `html.Div(f"PA at this GS: {pt.get('pivotal_alt', 0):.0f} ft AGL"),`
5. Run: `venv/bin/pytest tests/test_turns_around_point_pa.py -x -q`
   - **Expected:** Pass.
6. Manual smoke at `http://localhost:8052`: Maneuver = Turns Around a Point. Set wind 15 kt @ 270°. Click Set Center anywhere over flat terrain. Draw. Info panel shows the new `PA: X-Y ft AGL (avg Z)` row. Scrub the slider — at each step the tooltip displays "PA at this GS: __ ft AGL", varying around the orbit. **Expected delta:** PA_max - PA_min should be roughly 2 × wind_speed × ias / 11.3 ≈ 270 ft for the 15 kt wind / 100 kt IAS case.

**Commit:**
```
git add simulation/turns_around_point.py callbacks/maneuvers/turns_around_point.py tests/test_turns_around_point_pa.py
git commit -m "feat(turns_point): expose pivotal altitude in info panel + scrubber tooltip (ACS Gap 1)"
```

---

### Task C2: Wind-perpendicular warning on S-Turns (Gap 3)

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/s_turn.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_s_turn_wind_warning.py`

**Steps:**
1. Write the failing test at `tests/test_s_turn_wind_warning.py`. Pure function `_wind_perp_offset_deg(line_bearing: float, wind_dir: float) -> float`:
   - `_wind_perp_offset_deg(270, 0) == 0` (line east-west, wind from north → perpendicular, perfect).
   - `_wind_perp_offset_deg(0, 0) == 90` (line north-south, wind from north → parallel, worst).
   - `_wind_perp_offset_deg(280, 0) == 10`
   - `_wind_perp_offset_deg(260, 0) == 10`
   - Result is always in `[0, 90]`.
2. Run: `venv/bin/pytest tests/test_s_turn_wind_warning.py -x -q`
   - **Expected:** Fail; helper not defined.
3. Implement the helper inside `callbacks/maneuvers/s_turn.py` (module-level, above `register`):
   ```
   def _wind_perp_offset_deg(line_bearing: float, wind_dir: float) -> float:
       # Bearing of perpendicular axis (line +/- 90); we want the absolute
       # difference between (line - wind) and 90 modulo 180.
       return abs(((line_bearing - wind_dir) % 180) - 90)
   ```
4. In `draw_s_turn`, after `if not path or not hover: raise PreventUpdate`, compute `wind_perp = _wind_perp_offset_deg(line_bearing, float(wind_dir or 0))` and `wind_warning_chip = None if wind_perp <= 15 else html.Div(f"Wind alignment off by {wind_perp:.0f}° — ACS expects perpendicular", className="acs-metric"); ` apply `style={"borderLeft": "3px solid var(--acs-marginal)", "color": "var(--acs-marginal)", "padding": "4px 8px", "marginBottom": "6px", "fontSize": "11px"}` inline. Prepend this chip to `info_elements` (before the existing warnings block).
5. Run: `venv/bin/pytest tests/test_s_turn_wind_warning.py -x -q`
   - **Expected:** Pass.
6. Manual smoke at `http://localhost:8052`: Maneuver = S-Turns. Set wind 12 kt @ 0° (from north). Click `1. Start` and `2. Ref Pt` on a north-south line (e.g., a longitude line). Draw. Expect amber "Wind alignment off by ~90°" chip. Now click two new points on an east-west line → no chip. Done.

**Commit:**
```
git add callbacks/maneuvers/s_turn.py tests/test_s_turn_wind_warning.py
git commit -m "feat(s_turn): amber chip when reference line is not perpendicular to wind (ACS Gap 3)"
```

---

### Task C3: Per-leg WCA breakdown on Rectangular Course (Gap 4)

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/rectangular_course.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_rect_course_per_leg.py`

**Steps:**
1. Write the failing test at `tests/test_rect_course_per_leg.py`. Pure helper `_per_leg_wca(hover: list[dict]) -> list[dict]`:
   - Input: a hover list where each dict has `segment` keys like `"downwind"`, `"base"` or `"turn_X"` or numeric leg index; and `drift` (signed crab angle) and `gs` (groundspeed).
   - Output: a list of 4 dicts (downwind, base, upwind, crosswind, in that order). Each dict: `{"leg": "downwind", "avg_gs": float, "avg_crab": float, "max_crab": float}`. Skip turn segments (those starting with `turn_`).
   - When hover has all four legs represented, the result has 4 entries.
   - Crab averaging uses absolute values for `max_crab`, signed for `avg_crab`.
2. Run: `venv/bin/pytest tests/test_rect_course_per_leg.py -x -q`
   - **Expected:** Fail.
3. Implement the helper at module-level in `callbacks/maneuvers/rectangular_course.py`. Note the rectangular_course simulation uses `segment` values that may be `"downwind"`, `"base_to_final"`, etc. — confirm by reading `simulation/rectangular_course.py` for the exact strings used. The helper groups by these segment names and computes per-group aggregates.
4. In the callback `draw_rectangular_course`, after `if not path or not hover: raise PreventUpdate`, compute `per_leg = _per_leg_wca(hover)`. Build a small html.Table:
   ```
   per_leg_table = html.Table([
       html.Thead(html.Tr([html.Th("Leg"), html.Th("GS (kt)"), html.Th("Crab (°)"), html.Th("Max crab")])),
       html.Tbody([
           html.Tr([html.Td(row["leg"].title()),
                    html.Td(f"{row['avg_gs']:.0f}"),
                    html.Td(f"{row['avg_crab']:+.1f}"),
                    html.Td(f"{row['max_crab']:.1f}")])
           for row in per_leg
       ])
   ], className="rect-per-leg-table", style={"fontSize": "10px", "width": "100%", "marginTop": "4px"})
   ```
   Insert into the info accordion contents, after the `DW: ... | Lateral: ... | Crab: ...` line and before the `Vs turn` divider.
5. CSS in `assets/styles.css`: `.rect-per-leg-table { border-collapse: collapse; } .rect-per-leg-table th, .rect-per-leg-table td { padding: 2px 6px; border-top: 1px solid #e2e8f0; text-align: left; }`
6. Run: `venv/bin/pytest tests/test_rect_course_per_leg.py -x -q`
   - **Expected:** Pass.
7. Manual smoke at `http://localhost:8052`: Maneuver = Rectangular Course. Set wind 15 kt @ 270°. Click `1. DW Start` and `2. DW End` on an east-west line. Draw. Info panel shows the new 4-row table with the crab angle differing between downwind / crosswind / upwind / crosswind legs.

**Commit:**
```
git add callbacks/maneuvers/rectangular_course.py tests/test_rect_course_per_leg.py assets/styles.css
git commit -m "feat(rect_course): 4-row per-leg WCA breakdown table (ACS Gap 4)"
```

---

### Task C4: Phase markers on map for Power-Off 180 (Gap 5)

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/poweroff180.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_poweroff180_phase_markers.py`

**Steps:**
1. Write the failing test at `tests/test_poweroff180_phase_markers.py`. Pure helper `_phase_transition_indices(hover: list[dict]) -> list[tuple[int, str]]`:
   - Walk the hover list; each item has a `segment` field. Detect transitions (i.e., positions where `hover[i].segment != hover[i-1].segment`).
   - Return the list of `(index, new_segment)` tuples.
   - Includes the first entry implicitly (the initial segment at index 0).
   - Sample input: 100 entries with segments `["downwind"] * 30 + ["base"] * 20 + ["final"] * 50`. Expected output: `[(0, "downwind"), (30, "base"), (50, "final")]`.
2. Run: `venv/bin/pytest tests/test_poweroff180_phase_markers.py -x -q`
   - **Expected:** Fail.
3. Implement `_phase_transition_indices` module-level in `callbacks/maneuvers/poweroff180.py`.
4. In `draw_poweroff180`, after the `elements.append(impact_marker)` block, compute phase transitions and add CircleMarkers:
   ```
   transitions = _phase_transition_indices(hover_data)
   PHASE_LABELS = {"downwind": "Abeam", "base": "90° turn", "final": "45° / Final", "turn": "Turn"}
   for idx, seg in transitions:
       if idx >= len(path):
           continue
       lat, lon = path[idx]
       label = PHASE_LABELS.get(seg, seg.title())
       elements.append(dl.CircleMarker(
           center=[lat, lon], radius=6,
           color="#f59e0b", fill=True, fillOpacity=0.85,
           children=dl.Tooltip(f"{label} — alt {hover_data[idx].get('alt', 0):.0f} ft AGL, IAS {hover_data[idx].get('ias', 0):.0f}")
       ))
   ```
5. Manual smoke at `http://localhost:8052`: Maneuver = Power-Off 180. Click `Set Touchdown` on a runway, pick a runway, Draw. Expect 3-4 amber phase markers along the glide path at downwind→base, base→final transitions, plus an Abeam marker at the start. Hover each marker — tooltip shows the phase + altitude at that moment.

**Commit:**
```
git add callbacks/maneuvers/poweroff180.py tests/test_poweroff180_phase_markers.py
git commit -m "feat(poweroff180): phase markers at abeam / 90° / 45° / final transitions (ACS Gap 5)"
```

---

### Task C5: Altitude profile chart on Chandelle (first user of the helper from A2)

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/chandelle.py`

**Steps:**
1. Import the helper at the top of `callbacks/maneuvers/chandelle.py`: `from layouts.maneuvers._charts import altitude_profile_chart`.
2. In `draw_chandelle`, after the `info_content = dbc.Accordion([...])` block, build the chart:
   ```
   times = [pt.get("time", 0) for pt in hover]
   alts = [pt.get("alt", 0) for pt in hover]
   markers = []
   for i, pt in enumerate(hover):
       prog = pt.get("turn_progress", 0)
       if abs(prog - 90) < 3:
           markers.append((pt.get("time", 0), "90°"))
       elif abs(prog - 180) < 3:
           markers.append((pt.get("time", 0), "Exit"))
   profile_chart = altitude_profile_chart(times, alts, chart_id="chandelle-profile-chart", markers=markers)
   info_panel = html.Div([info_content, profile_chart])
   ```
   Return `info_panel` instead of `info_content` in the callback's return tuple.
3. Manual smoke at `http://localhost:8052`: Maneuver = Chandelle. Set Entry, Draw. Info panel now shows the altitude-vs-time line chart climbing from the entry altitude, with markers at the 90° pitch and the 180° exit. The maneuver visibly demonstrates climb.

**Commit:**
```
git add callbacks/maneuvers/chandelle.py
git commit -m "feat(chandelle): altitude profile chart in info panel (ACS Gap 2)"
```

---

### Task C6: Altitude profile chart on Lazy Eight

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/lazy_eight.py`

**Steps:**
1. Import: `from layouts.maneuvers._charts import altitude_profile_chart`.
2. After the `info_content = dbc.Accordion([...])` block, same pattern as C5. Mark the eight heading-reversal points (45°, 90°, 135°, 180°, 225°, 270°, 315°, 360°). Use `turn_progress` from hover. Build labels for each.
3. Manual smoke at `http://localhost:8052`: Maneuver = Lazy Eight. Set Entry, Draw. Info panel altitude chart shows the characteristic Lazy 8 oscillation pattern — up at 45° and 225°, down at 135° and 315°.

**Commit:**
```
git add callbacks/maneuvers/lazy_eight.py
git commit -m "feat(lazy8): altitude profile chart with heading-reversal markers (ACS Gap 2)"
```

---

### Task C7: Steep Spiral sim model rework + altitude profile chart + 60° peak-bank verdict

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/simulation/steep_spiral.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/steep_spiral.py`
- Create: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/tests/test_steep_spiral_model.py`

**Steps:**
1. Write the failing test at `tests/test_steep_spiral_model.py`. The maneuver model under the rework:
   - **Constant IAS at best-glide speed** for the entire descent — `simulate_steep_spiral` must use `bg_kias` from the aircraft (already does — confirm via the test that `hover[i]["ias"] == hover[j]["ias"]` for all i, j).
   - **Power held at idle** — `simulate_steep_spiral` does NOT accept a `power_setting` arg today, but a new optional `residual_power` kwarg added to handle the design directive's "off-design" case. Default 0 (idle). Test confirms `hover[i]["vs"]` is negative (descending) at residual_power=0.
   - **Bank modulates with position to hold constant ground-track radius** — at the same lat/lon orbit, the bank value in `hover[i]["aob"]` should vary across the loop in a wind-perpendicular pattern. Specifically, when ground track direction is along the wind (tailwind, max GS), bank should be steeper than when GS is minimum (upwind). Test asserts: `max(abs(aob)) > min(abs(aob)) + 5` for a 15 kt wind / 45° base bank case.
   - **Peak bank ≤ 60°** for normal-G case (already enforced by `actual_bank_deg = max(15.0, min(60.0, ...))` line 284 — keep). Add a flag `warnings["peak_bank_exceeded_60"]: bool` set to True if at any step the *unclamped* required bank would have exceeded 60°.
   - **Exit-heading marker** — `warnings["exit_heading"]` is populated from the last hover entry's heading.
2. Run: `venv/bin/pytest tests/test_steep_spiral_model.py -x -q`
   - **Expected:** The bank-modulation assertion passes (the current sim already modulates bank — verify); the `residual_power` arg test fails because the kwarg doesn't exist; the `peak_bank_exceeded_60` warning key fails because it's not surfaced.
3. Modify `simulation/steep_spiral.py`:
   - Add `residual_power: float = 0.0` to the function signature.
   - Replace the `compute_descent_rate(bank_deg, tas_knots)` function so that residual power reduces the descent rate: `descent_fpm = (tas_fpm / effective_gr) * (1 - max(0.0, min(0.5, residual_power)))`. Document: residual power above 50% breaks the "idle" assumption and the user gets the warning. If `residual_power > 0.05`, set `warnings["off_design_residual_power"] = round(residual_power * 100, 0)`.
   - Inside the per-step loop, track `peak_unclamped_bank`. If `actual_bank_deg (unclamped)` > 60.0 at any step, set `warnings["peak_bank_exceeded_60"] = True`.
   - Add `warnings["exit_heading"] = round(hdg_deg, 0)` after the loop (using the last computed `hdg_deg`).
4. Modify `callbacks/maneuvers/steep_spiral.py`:
   - Wire the new `residual_power` kwarg through. The Power-Off 180's residual-power slider concept doesn't apply here — instead use the *global* power-setting slider (sidebar), but transform it: any value > 5% is "off-design" for Steep Spiral. Add State for `"power-setting"`. Pass `residual_power=power_setting if power_setting > 0.05 else 0.0` to the sim.
   - After the existing warnings rendering, if `warnings.get("peak_bank_exceeded_60")` → render a tier-3 verdict banner: red, "Peak bank exceeded 60° — exceeds ACS allowable; reduce bank or increase orbit radius."
   - If `warnings.get("off_design_residual_power")` → tier-2 amber chip: "Off-design power: {n}% — Steep Spiral is an idle-power maneuver. Descent rate reduced; may not reach 1500 ft AGL completion."
   - Add the altitude profile chart, same pattern as C5 / C6. Markers at each completed turn (every 360° of `total_angle_traveled`).
   - Add an exit-heading marker on the map: `dl.CircleMarker(center=path[-1], radius=8, color="#ef4444", fill=False, children=dl.Tooltip(f"Exit hdg {warnings.get('exit_heading', 0):.0f}° at {warnings.get('final_altitude_agl', 0):.0f} ft AGL"))`.
5. Run: `venv/bin/pytest tests/test_steep_spiral_model.py -x -q`
   - **Expected:** Pass.
6. Manual smoke at `http://localhost:8052`: Maneuver = Steep Spiral. Set wind 20 kt @ 270°. Set Bank 50°. Set Ref. Draw. Info panel shows altitude profile descending in steps (one per 360° turn). The scrubber tooltip shows bank varying from ~40° upwind to ~58° downwind. If you set Bank 60°, the verdict banner reads "Peak bank exceeded 60°". If you raise the global Power slider to 30%, the amber chip reads "Off-design power: 30%".

**Commit:**
```
git add simulation/steep_spiral.py callbacks/maneuvers/steep_spiral.py tests/test_steep_spiral_model.py
git commit -m "feat(steep_spiral): constant-IAS / bank-modulating model + 60° verdict + altitude profile chart (ACS Gap 2 + IX.C)"
```

---

### Task C8: Per-maneuver remaining items (pruned from the master doc)

This is a sequence of small, low-blast-radius edits. Each is a separate commit because each touches a different file and has a different manual smoke check.

#### C8a: Steep Turn — turn rate °/s + exit heading marker + roll-rate tooltip

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/steep_turn.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/maneuvers/steep_turn.py`

**Steps:**
1. In the callback `draw_steep_turn`, compute `turn_rate_dps = (180.0 / math.pi) * (32.2 * math.tan(math.radians(float(bank_angle)))) / (avg_tas * 1.68781) if bank_angle and avg_tas > 0 else 0.0`. Add to the info accordion as a new row: `html.Div(f"Turn rate: {turn_rate_dps:.1f} °/s", style={"fontSize": "11px"}),` placed before the `Vs turn` line.
2. Add an exit-heading marker on the map. The exit heading after a full 360° turn equals the entry heading, but the marker still helps:
   ```
   if hover:
       exit_hdg = hover[-1].get("heading", entry_heading)
       exit_marker = dl.CircleMarker(center=path[-1], radius=8, color="#ef4444", fill=False,
                                     children=dl.Tooltip(f"Exit hdg {exit_hdg:.0f}° (target = entry {entry_heading:.0f}°)"))
       elements.append(exit_marker)
   ```
   (This is already covered by the existing `end_marker`, so instead just enrich the end_marker's tooltip with the exit/target heading.)
3. In the layout `layouts/maneuvers/steep_turn.py`, on the Bank ° dropdown, extend the tooltip to include roll-rate hint: `tooltip="Target bank angle. 45° is Private ACS standard, 50° Commercial. Aircraft's roll rate from POH determines how fast you reach it (default ~45°/s for trainers, ~120°/s for aerobatic)."`
4. Manual smoke at `http://localhost:8052`: Maneuver = Steep Turns. Set Entry, Draw. Info panel shows "Turn rate: X.X °/s". The exit marker's hover tooltip names both the achieved and target headings.

**Commit:**
```
git add callbacks/maneuvers/steep_turn.py layouts/maneuvers/steep_turn.py
git commit -m "feat(steep_turn): turn rate display + exit-heading tooltip + roll-rate hint"
```

#### C8b: Chandelle — roll-out heading marker + maneuver-info entry

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/chandelle.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/navigation.py`

**Steps:**
1. The end_marker tooltip already shows exit heading. Enrich: include the target heading (entry + 180° wrapped): `f"Roll-out: {exit_heading:.0f}° (target {(entry_heading + 180) % 360:.0f}°) at {exit_alt:.0f} ft"`. Apply the heading delta to the end_marker's existing tooltip string.
2. Already covered by Tasks C5 for the profile chart.
3. The existing `MANEUVER_INFO["chandelle"]` entry in `callbacks/navigation.py:135-143` is already populated. Enrich it with one extra bullet: `"Design power: 100%. Less power reduces altitude gained and can fail to reach the 180° exit at target IAS."` Append as a fourth bullet.

**Commit:**
```
git add callbacks/maneuvers/chandelle.py callbacks/navigation.py
git commit -m "feat(chandelle): roll-out heading target in exit tooltip + design-power note"
```

#### C8c: Lazy Eight — per-90° bank breakdown + heading-reversal markers + roll-out heading

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/lazy_eight.py`

**Steps:**
1. Build a small per-90° bank breakdown helper inside the callback that walks `hover`, finds the index closest to each `turn_progress in [45, 90, 135, 180, 225, 270, 315, 360]`, and records the bank at that index. Render as a 4-row mini-table in the info accordion: `45° L: AOB=__°`, `90° L: AOB=__°`, etc., grouped by 8 columns.
2. Add CircleMarkers on the map at each of those eight heading-reversal positions: `color="#f59e0b", radius=5, children=dl.Tooltip(f"{prog:.0f}°: bank {bank:.0f}° alt {alt:.0f}")`.
3. Enrich the end_marker tooltip with target roll-out heading (entry + 360°): `f"Roll-out: {exit_heading:.0f}° (target {entry_heading:.0f}°) at {exit_alt:.0f} ft"`.
4. Manual smoke at `http://localhost:8052`: Maneuver = Lazy Eight. Set Entry, Draw. Info panel shows the 8-cell bank breakdown. Map shows 8 small amber markers along the figure-8.

**Commit:**
```
git add callbacks/maneuvers/lazy_eight.py
git commit -m "feat(lazy8): per-90° bank breakdown + heading-reversal markers + roll-out target"
```

#### C8d: Turns Around a Point — min turn radius chip + drift visualization + entry tooltip

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/turns_around_point.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/maneuvers/turns_around_point.py`

**Steps:**
1. In the callback, compute the geometric minimum turn radius at 60° bank for the current TAS: `min_r_ft = (tas_fps**2) / (32.2 * math.tan(math.radians(60)))` and `min_r_nm = min_r_ft / 6076.12`. Add to the info accordion: `html.Div(f"Min turn radius at 60°: {min_r_ft:.0f} ft ({min_r_nm:.2f} NM) — yours: {orbit_radius_ft:.0f} ft", style={"fontSize": "11px"})`.
2. Surface the drift correction (wind_correction in hover) in the scrubber tooltip: it's already there. Confirm the tooltip line `Crab: R __° / L __°` is present (from the scrubber callback). Add to it the wind correction direction relative to the orbit phase: `html.Div(f"Wind correction: {pt.get('wind_correction', 0):+.1f}° (orbit phase {pt.get('turn_progress', 0):.0f}°)")`.
3. In the layout, change the Entry Hdg placeholder from `"auto"` to `"auto = downwind"` and extend the tooltip: `tooltip="Entry heading. Leave blank for auto downwind entry (ACS preferred). Override only if the prevailing wind isn't representative."`

**Commit:**
```
git add callbacks/maneuvers/turns_around_point.py layouts/maneuvers/turns_around_point.py
git commit -m "feat(turns_point): min radius chip + drift correction surfaced + entry-heading tooltip"
```

#### C8e: Rectangular Course — turn radius at corners + entry-heading guidance

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/rectangular_course.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/layouts/maneuvers/rectangular_course.py`

**Steps:**
1. In the callback, compute `turn_radius_ft = (tas_fps**2) / (32.2 * math.tan(math.radians(30.0)))` (30° bank is the typical pattern-corner bank). Add to the info accordion under the per-leg table: `html.Div(f"Turn radius at corners (30° bank): {turn_radius_ft:.0f} ft", style={"fontSize": "11px"})`.
2. In the layout, add a hint line above the action buttons or in the existing `rectcourse-edge-visible-info` Div: "Tip: click the downwind edge first (the leg parallel to wind, flown faster)." Re-render via the existing callback `update_rectcourse_edge_visible_info`.

**Commit:**
```
git add callbacks/maneuvers/rectangular_course.py layouts/maneuvers/rectangular_course.py
git commit -m "feat(rect_course): corner turn radius + downwind-entry hint"
```

#### C8f: Eights on Pylons — True Heading vs Ground Track arrow markers + pylon-separation chip + min/max altitude warning

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/eights_on_pylons.py`

**Steps:**
1. The simulation already produces per-step `heading` and `track` in hover. Add 8 small arrow markers along the figure-8 (one at each 45° of orbit progress on each pylon) showing the True Heading direction. Use `dl.DivIcon` or a tiny Polyline pair: from the position, draw a 100-meter arrow along `heading` (red, for true heading) and a 100-meter arrow along `track` (blue, for ground track). The visual delta between the two = the wind correction.
2. Add a pylon-separation chip: the `sim_warnings.get("pylon_distance_nm")` is already computed but only shown for max-bank notes. Surface it explicitly: `html.Div(f"Pylon separation: {sim_warnings.get('pylon_distance_nm', 0):.2f} NM ({sim_warnings.get('pylon_distance_ft', 0):.0f} ft)", style={"fontSize": "11px"})`. Insert before the existing "Pylon sep: ... Trans: ..." line, or replace it.
3. Add a min/max-safe altitude warning chip. The aircraft's pivotal altitude must fall in the 600-1000 ft AGL range for the standard ACS Eights on Pylons. If `pivotal_alt_avg < 600 or pivotal_alt_avg > 1000`, render an amber chip: `f"PA avg {pivotal_alt_avg:.0f} ft outside typical 600-1000 AGL — increase IAS to lift PA"` or `... reduce IAS to lower PA`.
4. Manual smoke at `http://localhost:8052`: Maneuver = Eights on Pylons. Set wind 20 kt @ 270°. Place two pylons ~0.5 NM apart east-west. Draw. The map shows the figure-8 with paired heading/track arrows visible at 8 points around the loop, demonstrating that the aircraft's nose (heading) does NOT point along the path (track) — it crabs into wind. Info panel shows pylon separation and an amber chip if PA is out of range.

**Commit:**
```
git add callbacks/maneuvers/eights_on_pylons.py
git commit -m "feat(pylons): heading vs track arrows + pylon separation chip + PA out-of-range warning"
```

---

### Task C9: Apply `_acs_metric` badge styling everywhere ACS tolerances surface (Gap 6)

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/steep_turn.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/chandelle.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/lazy_eight.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/turns_around_point.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/rectangular_course.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/s_turn.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/steep_spiral.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/eights_on_pylons.py`

**Steps:**
1. In each callback, import the helper: `from layouts.maneuvers._shared import _acs_metric`.
2. Replace bare `html.Div(f"... | Margin: __ kt | ...")` patterns with `_acs_metric` calls where ACS tolerances apply. Per-maneuver mapping (Private ACS unless noted, Commercial labeled):
   - **Steep Turn (Private):** `_acs_metric("Altitude", altitude_drift, "ft", target=0, tol=100, cert_level="private")` if altitude held constant. Also `_acs_metric("Roll-out heading", exit_heading_delta, "°", target=0, tol=10)`. Also `_acs_metric("Airspeed", entry_ias - actual_ias, "kt", target=0, tol=10)`.
   - **Chandelle (Commercial):** Heading at roll-out — `_acs_metric("Roll-out", abs((exit_heading - (entry_heading + 180)) % 360 - 180), "°", target=0, tol=10, cert_level="commercial")`. Stall margin pass/fail at completion is qualitative — render as: `_acs_metric("Stall margin", margin_kt, "kt", target=10, tol=10, cert_level="commercial")` (target=10 kt minimum to pass, anything > 10 is fine; the helper handles >tol as fail — so it's actually `target=max_margin, tol=max_margin-10` or simpler — interpret as "Margin ≥ 10 = pass"; either tweak the helper or pre-compute pass/fail and pass a label).
   - **Lazy Eight (Commercial):** `_acs_metric("Altitude drift", alt_variation, "ft", target=0, tol=100, cert_level="commercial")`. `_acs_metric("Roll-out", abs((exit_heading - entry_heading + 540) % 360 - 180), "°", target=0, tol=10, cert_level="commercial")`.
   - **Turns Around a Point (Private):** `_acs_metric("Altitude", alt_loss, "ft", target=0, tol=100, cert_level="private")`. `_acs_metric("Track radius", abs(actual_avg_radius - orbit_radius_ft) / orbit_radius_ft * 100, "%", target=0, tol=10)`.
   - **Rectangular Course (Private):** `_acs_metric("Altitude", alt_loss, "ft", target=0, tol=100)`. `_acs_metric("Pattern radius", lateral_drift_pct, "%", target=0, tol=10)`.
   - **S-Turns (Private):** `_acs_metric("Altitude", alt_loss, "ft", target=0, tol=100)`. `_acs_metric("Track radius", radius_drift_pct, "%", target=0, tol=10)`. `_acs_metric("Wing-level crossing", crossing_angle_delta, "°", target=0, tol=10)`.
   - **Steep Spiral (Commercial):** `_acs_metric("Exit heading", exit_hdg_delta, "°", target=0, tol=10, cert_level="commercial")`. `_acs_metric("Altitude at exit", final_alt - target_alt, "ft", target=0, tol=100, cert_level="commercial")`.
   - **Eights on Pylons (Commercial):** `_acs_metric("Heading", heading_drift_deg, "°", target=0, tol=10, cert_level="commercial")`.
3. Where the actual deviation cannot be derived from sim data (because the sim renders a *perfect* execution, not a *student's* execution), substitute a static "Target" badge: e.g., `_acs_metric("ACS tolerance", 100, "ft", target=100, tol=0)` — this renders pass-colored to indicate the maneuver was simulated AT the ACS tolerance. Document this nuance in a comment at the top of each callback's metric block.
4. Manual smoke at `http://localhost:8052`: cycle the 8 maneuvers above. Each info panel now shows 1-3 green badge metrics. If you deliberately set off-design values (e.g., Steep Turn at 60° bank instead of 45°), the badges still render green because the *sim* is perfect — but the panel makes clear what the pilot is being graded against.

**Commit:**
```
git add callbacks/maneuvers/*.py
git commit -m "feat(maneuvers): ACS tolerance badges across 8 maneuver info panels (Gap 6)"
```

---

## Phase D — Design Directive enforcement (Power slider must produce visible consequences)

**Status (2026-05-18):**
- D1 done — Steep Turn / Chandelle / Lazy 8 sims accept `power_setting`, callbacks pass through. 21 new physics tests pass. Snapshot regen for steep_turn (new metadata keys; at design power vs/alt unchanged so the snapshot's hover values are identical).
- D2 done — `_power_verdict()` helper in `layouts/maneuvers/_shared.py`, wired into 8 maneuver callbacks. CSS chip/banner classes added. 11 verdict-helper tests pass.
- D3 pending — user-driven UI smoke pass; checklist at bottom of this phase.

### Task D1: Audit power-slider consumption across all 12 callbacks; close gaps

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/steep_turn.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/chandelle.py`
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/callbacks/maneuvers/lazy_eight.py`
- Modify (sims to add the kwarg + use it): `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/simulation/steep_turn.py`, `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/simulation/chandelle.py`, `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/simulation/lazy_eight.py`

**Steps:**
1. Audit: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && grep -L "power-setting\|power_setting" callbacks/maneuvers/*.py`
   - **Expected:** Lists `chandelle.py`, `lazy_eight.py`, `steep_turn.py`, plus the three that legitimately ignore power (`impossible_turn.py`, `engineout.py`, `poweroff180.py` — wait, those *can* use power for residual cases). Already confirmed: `steep_spiral.py` got it via Task C7; the 4 ground-reference maneuvers (`s_turn`, `turns_point`, `rect_course`, `pylons`) already consume it; `route.py` legitimately ignores it.
2. For each of `steep_turn`, `chandelle`, `lazy_eight`:
   - In the callback, add `State("power-setting", "value")` to the inputs and a corresponding `power_setting` arg to the function signature.
   - Compute `power_pct = float(power_setting) if power_setting not in [None, "", "null"] else 0.65` (default 65% for these mid-power maneuvers).
   - Pass `power_setting=power_pct` to the `simulate_*` call.
3. For each of `simulation/steep_turn.py`, `simulation/chandelle.py`, `simulation/lazy_eight.py`:
   - Add `power_setting: float = 0.65` to the function signature.
   - Apply the power effect on altitude / climb behavior:
     - **Steep Turn:** Off-design power produces altitude drift. Compute `altitude_drift_fpm = (power_setting - 0.7) * 200` (positive = climb, negative = descend) at the design 70% baseline. Accumulate altitude change across the simulated steep turn. Surface `altitude_loss_ft` or `altitude_gain_ft` in the returned warnings dict.
     - **Chandelle:** Design = 100% (1.0). Below 70% may not reach 180°. Compute `target_alt_gain = base_climb * power_setting / 1.0`. If `power_setting < 0.5`, set `warnings["failure_reason"] = f"Insufficient power to complete 180° — reached {actual_180_progress:.0f}°"` and shorten the simulated path.
     - **Lazy Eight:** Design = cruise (~60-65%). Off-design causes oscillation amplitude drift. Compute `amplitude_factor = 1.0 + abs(power_setting - 0.625) * 0.5`. Multiply the altitude oscillation range by this factor.
4. Manual smoke at `http://localhost:8052`: Set Power to 50% then 100%, run Steep Turn / Chandelle / Lazy 8. **Expected delta:** Chandelle at 50% shows a failure verdict (or the path stops before completing 180°); Lazy 8 at 100% shows wider altitude oscillation; Steep Turn at 100% gains altitude visibly.

**Commit:**
```
git add callbacks/maneuvers/steep_turn.py callbacks/maneuvers/chandelle.py callbacks/maneuvers/lazy_eight.py simulation/steep_turn.py simulation/chandelle.py simulation/lazy_eight.py
git commit -m "feat(maneuvers): wire global power slider through steep_turn / chandelle / lazy8 with visible off-design effects"
```

---

### Task D2: Add off-design power failure verdicts per maneuver

**Files:**
- Modify: 12 callbacks where applicable

**Steps:**
1. For each maneuver, define a `_design_power` per the Design Directive table:
   - Route: cruise (n/a; slider hidden).
   - Impossible Turn: 1.0.
   - Power-Off 180: 0.0 (anything > 0 = "partial failure" — surfaced via the Residual power slider from Task A4).
   - Engine-Out Glide: 0.0.
   - Steep Turns: 0.70.
   - Chandelle: 1.00.
   - Lazy Eight: 0.625.
   - Steep Spiral: 0.0 (handled in Task C7).
   - S-Turns: 0.60.
   - Turns Around a Point: 0.60.
   - Rectangular Course: 0.60.
   - Eights on Pylons: 0.625.
2. In each callback (or a shared helper inside `layouts/maneuvers/_shared.py`), compute the deviation: `delta = power_pct - design_power; abs_delta = abs(delta)`. Render a chip:
   - `abs_delta < 0.10` → green pass badge: `_acs_metric("Power", power_pct * 100, "%", target=design_power * 100, tol=10)`
   - `0.10 ≤ abs_delta < 0.20` → amber chip: `f"Off-design power: {power_pct*100:.0f}% (design {design_power*100:.0f}%) — effect: <quantified consequence>"` Per-maneuver consequence text:
     - Steep Turn: "+/- altitude drift in turn"
     - Chandelle: "altitude gained reduced"
     - Lazy 8: "oscillation amplitude drifts"
     - S-Turns / TAP / Rect / Pylons: "wider arcs, more crab"
   - `abs_delta ≥ 0.20` → red verdict banner: `f"Maneuver failed — {failure_reason_per_maneuver}"`. Failure reasons:
     - Steep Turn: "altitude lost/gained beyond ACS ±100 ft tolerance"
     - Chandelle: "could not reach 180° within target IAS"
     - Lazy 8: "altitude oscillation out of phase, exit bank > 60°"
     - S-Turns / TAP / Rect: "ground track exceeded 10% radius tolerance"
     - Pylons: "could not hold pivotal altitude — pylon slipped off wing tip"
3. Manual smoke at `http://localhost:8052`: for each of 8 training maneuvers, set Power = 0.30 (well below most designs), Draw. Expect amber or red chip. Set Power back to within ±10% of design — green badge.

**Commit:**
```
git add callbacks/maneuvers/*.py layouts/maneuvers/_shared.py
git commit -m "feat(maneuvers): Design Directive — off-design power produces visible verdicts per maneuver"
```

---

### Task D3: Manual smoke pass for the 12-maneuver Design Directive walkthrough

**Files:** None — manual verification only.

**Steps:**
1. Maneuver = Route. Verify Power slider is hidden (no-op for Route).
2. Maneuver = Impossible Turn. Set Failure Alt 700 ft AGL. Click Set Takeoff. Draw. Verify success-vs-fail outcome banner is visible (was already a feature; just confirm Theme B styling applied — green-on-success, red-on-fail).
3. Maneuver = Power-Off 180. Move Residual power slider from 0% to 20%. Re-Draw. Expect path to extend (residual thrust = less descent). Touchdown error chip changes from "+50 ft" to "+150 ft (long)".
4. Maneuver = Engine-Out Glide. Verify Power slider is unused (idle is definitional).
5. Maneuver = Steep Turn at Power = 30% (off-design). Draw. Expect amber chip "Off-design power: 30%". Bump to Power = 70%. Re-Draw. Green badge "Power: 70%".
6. Maneuver = Chandelle at Power = 40%. Expect red verdict banner "Maneuver failed — could not reach 180°". Bump to 100%. Re-Draw. Path completes 180°, exit-heading marker shows entry+180.
7. Maneuver = Lazy 8 at Power = 100%. Expect amber chip "Off-design power: 100% — oscillation amplitude drifts". Altitude profile chart shows visibly wider oscillation.
8. Maneuver = Steep Spiral at Power = 30%. Expect amber chip "Off-design power: 30%". Altitude profile shows reduced descent rate.
9. Maneuver = S-Turns at Power = 90%. Expect amber chip. Path shows wider arcs.
10. Maneuver = Turns Around a Point at Power = 90%. Same as S-Turns.
11. Maneuver = Rect Course at Power = 90%. Same as S-Turns.
12. Maneuver = Eights on Pylons at Power = 90%. Expect PA range shift upward (because GS goes up); amber chip "Off-design power".

If any of these doesn't produce the expected visible delta, that's a bug to fix before this task closes.

**Commit:** No commit (manual verification only).

---

## Phase E — Cleanup + ship

### Task E1: Final color/typography sweep

**Files:**
- Modify: `/Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives/assets/styles.css`

**Steps:**
1. Run `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && grep -rn "color=\"red\"\|color=\"green\"\|color=\"blue\"\|color=\"orange\"\|#FF0000\|#00AA00\|#ff6600\|#cc0000" callbacks/ layouts/`
   - **Expected:** No matches (or only inside Tooltip strings).
2. Run `grep -n "color:\\s*red\\|color:\\s*green" assets/styles.css`
   - **Expected:** Only CSS-variable references (`var(--acs-pass)` etc.), no raw color names.
3. Verify the ACS metric badge CSS is using the canonical tokens (Task A1 already declared these).
4. Visual diff: open `http://localhost:8052` in two browsers, light theme + dark theme. Cycle through all 12 maneuvers. Confirm:
   - All start markers are the same green
   - All end markers are the same red
   - All reference/center markers are the same blue
   - Pylons / S-turn ref-line / preview lines are amber
   - Active paths are blue-600 with consistent weight 3
   - Envelope rings are lime-500 dashed

**Commit:** if any nits found, fix and commit as `style(maneuvers): color token sweep nits`. Otherwise no commit.

---

### Task E2: Regression test pass

**Files:** None.

**Steps:**
1. Run `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && venv/bin/pytest -x -q`
   - **Expected:** Full test suite green, except for the existing `KNOWN_BAD_VNE_VNO` xfails. New tests for `_acs_metric`, profile_chart helper, performance_dynamics schema, classify_dynamics derivation, dynamics_for loader, turns_point PA, s_turn wind warning, rect_course per-leg, poweroff180 phase markers, and steep_spiral model are all passing.
2. If `app.py` has a smoke test, run it. Otherwise: `cd /Users/nicholaslen/Desktop/tallyaero_archives/tallyaero_overlay_archives && timeout 30 venv/bin/python -c "import app; print('app imports clean')"`
   - **Expected:** `app imports clean` printed, no traceback.

**Commit:** No commit (verification only).

---

### Task E3: Hand-off note for the user — DO NOT push

**Files:** None.

**Steps:**
1. Run `git log --oneline | head -30`
   - **Expected:** A clean linear history with ~20-25 commits from Phases A-D, each on a different file group.
2. Verify nothing is staged or unmerged: `git status`
   - **Expected:** Clean working tree.
3. **Do not push.** Notify the user that the work is ready for review, list the commits, and ask whether they want the branch squash-merged to main or kept as a sequence of small commits.

**Commit:** No commit.

---

## Manual Smoke Checklist (used at every Draw-fronted task)

At `http://localhost:8052`:

| Maneuver | Click | Sliders | Expected visible state |
|---|---|---|---|
| Route Planner | Two airports | Cruise Alt 5500 | Score banner + nav log button + altitude profile + corridor |
| Impossible Turn | Set Takeoff on runway | Failure Alt 700 | Color-coded phases path; success/fail banner; outcome marker |
| Power-Off 180 | Set Touchdown on runway | Abeam 0.5, Residual power 0% | Path with 3-4 amber phase markers; touchdown banner |
| Engine-Out Glide | Set Touchdown + Set Start | Max Bank 30° | Green start, red touchdown, lime envelope, blue glide line |
| Steep Turns | Set Entry | Bank 45°, Power 70% | Closed loop; Turn rate °/s in info; ACS badges green |
| Chandelle | Set Entry | Bank 30°, Power 100% | Climbing arc with altitude profile; exit-heading marker; ACS green |
| Lazy Eight | Set Entry | Max Bank 30°, Power 65% | Figure-8 with 8 amber heading-reversal markers; oscillating altitude chart |
| Steep Spiral | Set Ref | Bank 45°, Turns 3, Power 0% | Descending orbit; altitude profile steps down per turn; exit-heading marker |
| S-Turns | 1. Start + 2. Ref Pt (east-west line) | Bank 35°, Power 60° | Reference line gray; semicircles alternating sides; if wind not perpendicular, amber chip |
| Turns Around a Point | Set Center | Radius 0.25 NM, Power 60% | Orbit colored by GS; PA chip in info; drift correction in scrubber |
| Rectangular Course | 1. DW Start + 2. DW End | Leg spacing 0.75 NM | Rectangle with GS coloring; 4-row per-leg crab table; corner turn radius chip |
| Eights on Pylons | Set Pylon 1 + Set Pylon 2 | Bank 30°, IAS 100 | Figure-8 with PA coloring; pylon-separation chip; 8 heading/track arrow pairs |

---

## Open Decisions / Risks

- **Three potential merge conflicts:** Phase A3 (color sweep) and Phase C9 (ACS badges) both touch many of the same callback files. Order them as listed (A3 first, then C9) to keep merges trivial; do not interleave.
- **POH citation accuracy:** The POH values in Task B3 are calibrated to plausible values but not 100% verified against original POH text. The plan flags them as `provenance="poh"` with citations — but the user should review the table before shipping. If any value is wrong, the fix is a single dict entry in `scripts/apply_poh_dynamics.py` and a re-run.
- **Lazy 8 / Chandelle altitude-from-power coupling:** The current sims are mostly geometric (path + bank from inputs). Wiring power → altitude requires touching `simulation/chandelle.py` and `simulation/lazy_eight.py` math, which has more blast radius than the rest of Phase D. The plan accommodates this in Task D1 with explicit code edits, but if regressions surface during smoke testing, the safest fallback is to keep the badge display in Phase D2 (which is purely cosmetic) and defer the *sim* coupling to a follow-up branch.
- **Eights on Pylons heading/track arrows:** rendering 8 paired Polyline arrows per Draw could clutter the map. If the visual is messy, fall back to showing arrows only at 4 cardinal points per pylon (16 total → 8 total).
- **Schema migration ordering:** Phase B1 extends the Pydantic schema first; Phase B2 writes the field into 110 JSONs. If the order is reversed, `test_aircraft_schema.py` will fail for all aircraft. Hold the ordering as written.

---

## Summary

- **Total tasks:** 27 (A1-A4, B1-B4, C1-C9 including 6 C8 sub-tasks, D1-D3, E1-E3).
- **Phase breakdown:** Phase A (foundations) 4 tasks · Phase B (aircraft data hardening) 4 tasks · Phase C (six ACS gaps + per-maneuver remaining + badge sweep) 14 tasks (C1-C7, six C8a-f, C9) · Phase D (Design Directive enforcement) 3 tasks · Phase E (cleanup + ship) 3 tasks.
- **Estimated effort:** Phase A ~4-6 hours · Phase B ~4-6 hours (heavy on POH calibration) · Phase C ~10-14 hours · Phase D ~4-6 hours (Lazy 8 / Chandelle sim coupling is the risk) · Phase E ~2 hours. Total ~24-34 hours of focused work over 4-5 working days. Commits are scoped tight enough that any single task can be reverted without cascading.
- **Open decisions the executor cannot lock without you:** (1) POH-curated dynamics values in Task B3 — calibrate against your own POH library before shipping. (2) Whether Lazy 8 / Chandelle should get genuine power-coupled sim math now (in D1) or defer to a follow-up branch if regressions surface. (3) Whether the heading/track arrow density on Eights on Pylons is too busy at 16 arrows; fall back to 8 if visual feedback is poor. (4) Whether to keep all commits or squash-merge to main (decided by you in Task E3).
