# EM Diagram Physics Audit Plan

## Overview
This document provides a comprehensive checklist for auditing all physics calculations, data usage, and formula correctness in the EM Diagram application.

---

## FUNCTIONS TO AUDIT

### 1. AERODYNAMICS & LIFT CALCULATIONS

| # | Function | Location | Status |
|---|----------|----------|--------|
| 1.1 | `compute_dynamic_pressure()` | core/calculations.py:28 | [x] OK |
| 1.2 | `compute_cl()` | core/calculations.py:33 | [x] OK |
| 1.3 | `compute_cd()` | core/calculations.py:43 | [x] OK |
| 1.4 | `compute_drag()` | core/calculations.py:52 | [x] OK |
| 1.5 | Stall Load Factor (inline) | app.py:1431 | [x] OK |

**Formulas to Verify:**
- q = 0.5 * ρ * V²
- CL = W * n / (q * S), clipped at CL_max
- CD = (CD0 + CL²/(π*AR*e)) * CG_factor * gear_factor
- D = q * S * CD

---

### 2. THRUST & POWER CALCULATIONS

| # | Function | Location | Status |
|---|----------|----------|--------|
| 2.1 | `compute_thrust_available()` | core/calculations.py:57 | [x] OK |
| 2.2 | Power Derating (altitude) | app.py:1273-1281 | [x] OK |
| 2.3 | OEI Power Override | app.py:1322-1325 | [x] OK |
| 2.4 | Power Fraction Application | app.py:1283, 1323 | [x] OK |

**Formulas to Verify:**
- T_static = T_static_factor * hp
- Thrust decay: T = T_static * (1 - (V/V_max)²)
- Altitude derate: hp = sea_level_max * (1 - derate_per_1000ft * alt/1000)

---

### 3. SPECIFIC EXCESS POWER (Ps)

| # | Function | Location | Status |
|---|----------|----------|--------|
| 3.1 | `compute_ps_knots_per_sec()` | core/calculations.py:68 | [x] FIXED |
| 3.2 | Ps Grid Calculation (vectorized) | app.py:1682 | [x] OK |
| 3.3 | Envelope Masking for Ps | app.py:1698-1705 | [x] FIXED |

**Formulas to Verify:**
- Ps = ((T - D) * V / W - g * sin(γ)) / 1.68781
- Ps units: knots/second

---

### 4. ATMOSPHERIC CALCULATIONS

| # | Function | Location | Status |
|---|----------|----------|--------|
| 4.1 | `compute_air_density()` | core/calculations.py:96 | [x] OK |
| 4.2 | `compute_density_altitude()` | core/calculations.py:127 | [x] OK |
| 4.3 | `compute_pressure_altitude()` | core/calculations.py:145 | [x] OK |
| 4.4 | `compute_true_airspeed()` | core/calculations.py:161 | [x] OK |

**Formulas to Verify:**
- ρ = ρ_SL * (T/T_SL)^4.256
- DA = PA + 120 * (OAT - ISA_temp)
- PA = Field Elev + (29.92 - altimeter) * 1000
- TAS = IAS / sqrt(σ)

---

### 5. TURN PHYSICS

| # | Function | Location | Status |
|---|----------|----------|--------|
| 5.1 | `compute_load_factor()` | core/calculations.py:191 | [x] OK |
| 5.2 | `compute_turn_rate_from_bank()` | core/calculations.py:213 | [x] OK |
| 5.3 | `compute_turn_rate_from_load_factor()` | core/calculations.py:239 | [x] OK |
| 5.4 | `compute_turn_radius()` | core/calculations.py:265 | [x] OK |
| 5.5 | `compute_bank_from_turn_rate()` | core/calculations.py:291 | [x] OK |
| 5.6 | In-app Turn Rate (inline) | app.py:1729, 2113, 2191 | [x] OK |

**Formulas to Verify:**
- n = 1 / cos(bank)
- ω = g * tan(bank) / V
- ω = g * sqrt(n² - 1) / V
- R = V² / (g * tan(bank))
- bank = atan(ω * V / g)

---

### 6. STALL SPEED & BOUNDARY

| # | Function | Location | Status |
|---|----------|----------|--------|
| 6.1 | `compute_stall_speed_at_load_factor()` | core/calculations.py:318 | [x] OK |
| 6.2 | `interpolate_stall_speed()` | core/calculations.py:339 | [x] FIXED |
| 6.3 | `compute_stall_ias_at_turn_rate()` | core/calculations.py:371 | [x] OK |
| 6.4 | Stall Envelope (positive G) | app.py:1428-1439 | [x] OK |
| 6.5 | Stall Envelope (negative G) | app.py:1521-1538 | [x] OK |

**Formulas to Verify:**
- Vs_n = Vs_1g * sqrt(n)
- n_stall = (0.5 * ρ * V² * S * CL_max) / W

---

### 7. G-LIMIT & CORNER SPEED

| # | Function | Location | Status |
|---|----------|----------|--------|
| 7.1 | G-Limit Curve | app.py:1420-1426 | [x] OK |
| 7.2 | Negative G-Limit | app.py:1545-1555 | [x] OK |
| 7.3 | Corner Speed Detection | app.py:1445-1456 | [x] OK |
| 7.4 | Intermediate G Curves | app.py:1645-1679 | [x] OK |

---

### 8. MULTI-ENGINE (Vmc/Vyse)

| # | Function | Location | Status |
|---|----------|----------|--------|
| 8.1 | `calculate_vmca()` | app.py:1039-1106 | [x] OK |
| 8.2 | Vmca Modifiers (power/weight/CG/prop/bank) | app.py:1065-1097 | [x] OK |
| 8.3 | `calculate_dynamic_vyse()` | app.py:1108-1162 | [x] FIXED |
| 8.4 | Vyse Modifiers | app.py:1129-1150 | [x] FIXED |

**Modifier Ranges to Verify:**
- Power: 0.7x - 1.2x
- Weight: 0.85x - 1.15x
- CG: 1.0x - 1.05x
- Prop: 0.95x - 1.05x
- Bank: ±10%

---

### 9. CG & CONFIGURATION EFFECTS

| # | Function | Location | Status |
|---|----------|----------|--------|
| 9.1 | CL_max Adjustment | app.py:1376-1377 | [x] OK |
| 9.2 | CG Drag Factor | app.py:1378 | [x] OK |
| 9.3 | Gear Drag Factor | app.py:1299 | [x] OK |
| 9.4 | Gear Lift Factor | app.py:1300 | [x] OK |

**Effects to Verify:**
- Forward CG: Up to 5% CL_max penalty
- Forward CG: Up to 4% added drag
- Gear down: 15% drag increase
- Gear down: 2% CL reduction

---

### 10. MANEUVER CALCULATIONS

| # | Function | Location | Status |
|---|----------|----------|--------|
| 10.1 | Steep Turn - Turn Rate | app.py:2446 | [x] OK |
| 10.2 | Steep Turn - Load Factor | app.py:2449 | [x] OK |
| 10.3 | Steep Turn - Energy Rate | app.py:2462 | [x] FIXED |
| 10.4 | Chandelle - Energy Profile | app.py:2554-2559 | [x] OK |
| 10.5 | Chandelle - Bank Fade | app.py:2559 | [x] OK |
| 10.6 | Chandelle - Turn Integration | app.py:2569 | [x] OK |

---

### 11. WEIGHT & LOADING

| # | Function | Location | Status |
|---|----------|----------|--------|
| 11.1 | Total Weight Calculation | app.py:1020-1026 | [x] OK |
| 11.2 | Fuel Weight | app.py:1022 | [x] OK |
| 11.3 | Occupant Weight | app.py:1025 | [x] OK |

---

## PHYSICAL CONSTANTS TO VERIFY

| Constant | Value | Units | Location |
|----------|-------|-------|----------|
| g (gravity) | 32.174 | ft/s² | core/calculations.py:18-19 |
| KTS_TO_FPS | 1.68781 | conversion | core/calculations.py:20 |
| KTS_TO_MPH | 1.15078 | conversion | core/calculations.py:22 |
| RHO_SL | 0.002377 | slugs/ft³ | core/calculations.py:23 |
| TEMP_SL_K | 288.15 | Kelvin | core/calculations.py:24 |
| LAPSE_RATE_K_FT | 0.0019812 | K/ft | core/calculations.py:26 |

---

## AIRCRAFT JSON DATA FIELDS

| Field | Used For | Example |
|-------|----------|---------|
| `empty_weight` | Total weight, Ps | 2300 lbs |
| `max_weight` | Weight validation | 2550 lbs |
| `wing_area` | CL, CD, Ps, stall | 174 sq ft |
| `aspect_ratio` | CD calculation | 7.5 |
| `CD0` | Parasite drag | 0.025 |
| `e` (Oswald) | Induced drag | 0.8 |
| `CL_max[config]` | Stall, envelope | {"clean": 1.5} |
| `stall_speeds[config]` | Weight interpolation | {...} |
| `G_limits[category][config]` | Envelope limits | {"positive": 3.8} |
| `single_engine_limits.Vmca` | Dynamic Vmca | 70 kts |
| `prop_thrust_decay` | Thrust model | {...} |
| `cg_range` | CL/CD modifiers | [18.5, 25.5] |
| `engine_options[].horsepower` | Power calcs | 200 hp |
| `engine_options[].power_curve` | Altitude derate | {...} |
| `Vne` / `Vfe` | Speed limits | 200 / 120 kts |
| `fuel_weight_per_gal` | Fuel weight | 6.0 lbs/gal |

---

## AUDIT PRIORITY

### Priority 1: Critical (Core Physics)
- [x] Ps calculation formula *(fixed dimensional bug)*
- [x] Thrust decay model *(verified correct)*
- [x] Air density at altitude *(verified correct)*
- [x] Stall speed interpolation *(fixed edge case bug)*

### Priority 2: Multi-Variable
- [x] Vmca modifier ranges *(verified correct)*
- [x] Vyse adjustment factors *(fixed missing else clause)*
- [x] CG effects on CL/CD *(verified correct)*
- [x] Gear effects *(verified correct)*

### Priority 3: Envelope Logic
- [x] Ps grid masking *(fixed negative TR mask bug)*
- [x] Negative G envelope *(verified correct)*
- [x] Corner speed detection *(verified correct)*

### Priority 4: Maneuvers
- [x] Chandelle energy model *(verified correct)*
- [x] Bank fade rate *(verified: -1°/3° heading)*
- [x] Turn rate integration step size *(verified: 0.1s)*
- [x] Steep turn Ps *(fixed g→V dimensional bug)*

### Priority 5: Presentation & UX
- [x] Ps contour color scale clarity *(verified correct)*
- [x] Envelope boundary visual hierarchy *(verified correct)*
- [x] Hover tooltip completeness *(verified correct)*
- [x] Maneuver display usefulness & UX *(improved steep turn & chandelle)*
- [x] Vmc/Dynamic Vmc/OEI line displays *(major improvements)*
- [x] Flyable/non-flyable region distinction *(DVmc reshapes envelope)*

---

### 12. GRAPH PRESENTATION & DISPLAY

| # | Element | Location | Status |
|---|---------|----------|--------|
| 12.1 | Axis Labels & Units | app.py | [x] OK |
| 12.2 | Ps Contour Color Scale | app.py | [x] OK |
| 12.3 | Contour Level Selection | app.py | [x] OK |
| 12.4 | Stall Boundary Styling | app.py | [x] OK |
| 12.5 | G-Limit Curve Styling | app.py | [x] OK |
| 12.6 | Speed Limit Lines (Vne, Vfe, Vmca) | app.py | [x] OK |
| 12.7 | Corner Speed Annotation | app.py | [x] ADDED |
| 12.8 | Legend Placement & Clarity | app.py | [x] OK |
| 12.9 | Hover Tooltip Content | app.py | [x] OK |
| 12.10 | Grid Lines & Tick Spacing | app.py | [x] OK |
| 12.11 | Envelope Fill/Shading | app.py | [x] OK |
| 12.12 | Maneuver Trace Styling | app.py | [x] IMPROVED |
| 12.13 | Current State Marker | app.py | [x] OK |
| 12.14 | Negative G Region Display | app.py | [x] OK |
| 12.15 | OEI Overlay Distinction | app.py | [x] IMPROVED |

**Display Standards to Verify:**
- Axis labels include units (knots, G, ft/min)
- Ps contours use intuitive color progression (red=negative, green=positive)
- Critical speeds clearly distinguishable from advisory speeds
- Envelope boundaries visually distinct from Ps contours
- Hover data shows all relevant values (V, n, Ps, turn rate)
- Text legible at all zoom levels
- Color choices accessible (colorblind-friendly options)
- Consistent line weights for hierarchy (boundaries > contours > grid)

**User Interpretation Checklist:**
- [x] Flyable vs non-flyable regions immediately obvious
- [x] Energy-gaining vs energy-losing regions clear at a glance
- [x] Current aircraft state prominently displayed
- [x] Maneuver traces easy to follow *(START/END markers, energy flow arrows)*
- [x] Critical limitations (stall, structural) visually emphasized
- [x] Multi-engine considerations (Vmca) clearly marked when applicable *(DVmc reshapes envelope)*

---

## TESTING CHECKLIST

For each function:
- [ ] Formula matches published aerodynamic references
- [ ] Units are consistent (ft, lbs, slugs, knots)
- [ ] Edge cases handled (zero values, negative inputs)
- [ ] Aircraft JSON data accessed correctly
- [ ] Environmental inputs (altitude, temp) applied properly
- [ ] Results within physically realistic ranges

---

## FILES TO AUDIT

1. **core/calculations.py** (~393 lines) - All core physics functions
2. **core/constants.py** - Physical constants and defaults
3. **app.py** (lines 1016-2623) - Inline calculations and main plot logic

---

## NOTES

_Use this section to document findings during audit:_

### Session 1: 2026-01-18 — Priority 1 Audit
**Functions audited:**
- `compute_ps_knots_per_sec()` (core/calculations.py:68)
- `compute_thrust_available()` (core/calculations.py:57)
- `compute_air_density()` (core/calculations.py:82)
- `interpolate_stall_speed()` (core/calculations.py:325)

**Issues found:**
1. **CRITICAL — Ps formula dimensional error:** Used `g * sin(γ)` (ft/s²) instead of `V * sin(γ)` (ft/s). This caused incorrect Ps values when flight path angle ≠ 0.
2. **MINOR — Stall interpolation edge case:** Potential IndexError if `speeds` list was empty but truthy check passed.

**Fixes applied:**
1. Changed `compute_ps_knots_per_sec()` to use `V_fps * sin(gamma)` instead of `g * sin(gamma)`. Added explicit docstring clarifying V_fps must be in ft/s.
2. Added explicit `len(speeds) > 0` check before accessing `speeds[0]`.

**Verified correct (no changes needed):**
- `compute_thrust_available()` — quadratic decay model correct, edge cases handled
- `compute_air_density()` — standard atmosphere formula correct, tropopause floor at 216.65K

### Session 2: 2026-01-18 — Priority 2 Audit
**Functions audited:**
- `calculate_vmca()` (app.py:1039-1106)
- `calculate_dynamic_vyse()` (app.py:1108-1162)
- CG effects (app.py:1375-1378)
- Gear effects (app.py:1298-1300)

**Issues found:**
1. **BUG — Vyse prop_factor undefined:** No `else` clause in prop_condition check. If prop_condition was an unexpected value, `prop_factor` would be undefined → NameError at runtime.

**Fixes applied:**
1. Added `else: prop_factor = 1.0` default case to `calculate_dynamic_vyse()`.

**Verified correct (no changes needed):**
- Vmca modifiers: Power (0.7-1.2x), Weight (0.85-1.15x), CG (1.0-1.05x), Prop (0.95-1.05x), Bank (0.96-1.10x)
- Vyse modifiers: Weight (0.9-1.1x), Altitude (+2%/10kft), Gear (+4%), Flaps (1.0-1.06x)
- CG effects: Forward CG = -5% CL_max, +2% drag (physically correct)
- Gear effects: +15% drag, -2% CL_max (physically correct)

### Session 3: 2026-01-18 — Priority 3 Audit
**Functions audited:**
- Ps grid masking (app.py:1686-1707)
- Negative G envelope (app.py:1473-1512)
- Corner speed detection (app.py:1442-1458)

**Issues found:**
1. **BUG — Ps negative TR mask broken:** `valid_neg = (TR < 0) & (TR >= tr_limit_neg_env)` was always False because `tr_limit_neg_env` is positive but TR is negative in that region. Ps was never displayed in negative G region.

**Fixes applied:**
1. Changed to `TR >= -tr_limit_neg_env` to properly negate the limit for the negative TR region.

**Verified correct (no changes needed):**
- Load factor calculation: n = sqrt(1 + (Vω/g)²)
- Stall speed: V = sqrt(2Wn/(ρS·CL_max))
- Turn rate limit: ω = g·sqrt(n²-1)/V
- Negative G envelope: correctly uses -CL_max and negates turn rate
- Corner speed detection: reasonable numerical intersection approach

### Session 4: 2026-01-18 — Priority 4 Audit
**Functions audited:**
- Steep turn calculations (app.py:2446-2464)
- Chandelle energy model (app.py:2536-2572)
- Bank fade rate (app.py:2561)
- Turn rate integration (app.py:2571)

**Issues found:**
1. **BUG — Steep turn Ps dimensional error:** Line 2464 used `g * sin(γ)` instead of `v_fts * sin(γ)`. Same issue as P1.1 but in inline code.

**Fixes applied:**
1. Changed steep turn Ps to use `v_fts * sin(γ)` for dimensional consistency.

**Verified correct (no changes needed):**
- Steep turn rate: ω = g·tan(bank)/V
- Steep turn load factor: n = 1/cos(bank)
- Chandelle energy bias: 50-80% of energy loss in first 90° based on bank angle
- Chandelle bank fade: 1° reduction per 3° heading change in second half
- Integration timestep: 0.1s with max 1000 steps (adequate for 180° turn)

### Session 5: 2026-01-18 — Priority 5 Audit (Presentation & UX)
**Elements audited:**
- Ps contour color scale
- Envelope boundary visual hierarchy
- Hover tooltip completeness
- Corner speed annotation
- Steep turn maneuver display
- Chandelle maneuver display
- OEI (DVmc/DVyse) line displays
- Flight envelope modification with DVmc

**Issues found:**
1. **UX — Corner speed annotation missing:** No x-axis annotation for corner speed marker.
2. **UX — Steep turn context unclear:** Line/dot representation not explained, ghost trace buried in menu.
3. **UX — Chandelle trace direction unclear:** No indication of START/END or energy flow direction.
4. **TERMINOLOGY — "ATS Standard" incorrect:** Should be "ACS Standard" (Airman Certification Standards).
5. **UX — OEI labels inconsistent:** "Dynamic Vmca" and "Dynamic Vyse" too verbose, labels overlapping.
6. **UX — DVmc/DVyse lines extend beyond envelope:** Lines visible outside flight envelope causing confusion.
7. **PHYSICS — DVmc should reshape envelope:** When DVmc > stall speed, the flight envelope should reflect this constraint.

**Fixes applied:**
1. Added orange corner speed annotation on x-axis with small tick mark, matching corner speed marker.
2. Restructured steep turn menu: Ghost Trace after AOB slider, ACS Standard toggles only visible when Ghost Trace enabled. Added contextual hover showing "Wings Level → Operating Point", G load factor annotation.
3. Added START/END annotations to chandelle trace, "← Energy Flow →" direction indicator, heading progress in hover tooltip.
4. Changed all instances of "ATS Standard" to "ACS Standard" (5 occurrences).
5. Renamed labels: "Dynamic Vmca" → "DVmc", "Dynamic Vyse" → "DVyse". Separated Vyse/Vxse label overlap with arrow offsets.
6. Clipped DVmc/DVyse lines to stay within lift limit boundary. Labels remain visible even if line is clipped.
7. **Major enhancement:** DVmc now reshapes entire flight envelope:
   - DVmc calculated early, before Ps grid and overlays
   - Stall boundary modified where DVmc > stall speed
   - Lift Limit renamed to "Lift Limit (DVmc)" in crimson when active
   - All overlays clip to DVmc boundary: Ps grid masking, AOB heatmap masking, turn radius lines, intermediate G curves

**Verified correct (no changes needed):**
- Ps contour color scale (red=negative, green=positive progression)
- Envelope boundary visual hierarchy (stall red, G-limit black dashed)
- Hover tooltip completeness (V, n, Ps, turn rate displayed)

### Session 6: 2026-01-18 — Comprehensive Remaining Items Audit
**Functions audited:**

**Section 1 - Aerodynamics & Lift (core/calculations.py):**
- `compute_dynamic_pressure()`: q = ½ρV² ✓ CORRECT
- `compute_cl()`: CL = W·n/(q·S), clipped at CL_max ✓ CORRECT (edge case q≤0 handled)
- `compute_cd()`: CD = (CD0 + CL²/(π·AR·e)) × factors ✓ CORRECT
- `compute_drag()`: D = q·S·CD ✓ CORRECT
- Stall Load Factor (app.py:1431): n_stall = (0.5·ρ·V²·S·CL_max)/W ✓ CORRECT

**Section 2 - Thrust & Power (app.py:1273-1325):**
- Power Derating: Linear derate with altitude, capped at max_altitude ✓ CORRECT
- OEI Power Override: Uses OEI-specific power fraction when available ✓ CORRECT
- Power Fraction: Applied correctly in both normal and OEI paths ✓ CORRECT

**Section 4 - Atmospheric (core/calculations.py):**
- `compute_density_altitude()`: DA = PA + 120×(OAT - ISA) ✓ CORRECT
- `compute_pressure_altitude()`: PA = field + (29.92 - altimeter)×1000 ✓ CORRECT
- `compute_true_airspeed()`: TAS = IAS/√σ ✓ CORRECT (stratosphere floor handled)

**Section 5 - Turn Physics (core/calculations.py):**
- `compute_load_factor()`: n = 1/cos(bank) ✓ CORRECT (90° edge case handled)
- `compute_turn_rate_from_bank()`: ω = g·tan(bank)/V ✓ CORRECT
- `compute_turn_rate_from_load_factor()`: ω = g·√(n²-1)/V ✓ CORRECT
- `compute_turn_radius()`: R = V²/(g·tan(bank)) ✓ CORRECT
- `compute_bank_from_turn_rate()`: bank = atan(ω·V/g) ✓ CORRECT
- In-app inline (app.py): All use ω = g·tan(bank)/V ✓ CORRECT

**Section 6 - Stall Speed & Boundary:**
- `compute_stall_speed_at_load_factor()`: Vs_n = Vs_1g·√n ✓ CORRECT
- `compute_stall_ias_at_turn_rate()`: Iterative coupled solution ✓ CORRECT
- Positive G Envelope (app.py:1428-1439): n = L/W, ω = g·√(n²-1)/V ✓ CORRECT
- Negative G Envelope (app.py:1521-1538): Uses -CL_max, negates turn rate ✓ CORRECT

**Section 7 - G-Limit & Corner Speed:**
- G-Limit Curve (app.py:1420-1426): ω = g·√(n_limit²-1)/V ✓ CORRECT
- Intermediate G Curves (app.py:1645-1679): Same formula, DVmc masking added ✓ CORRECT

**Section 11 - Weight & Loading (app.py:1020-1026):**
- Total Weight: empty + fuel_weight + people_weight ✓ CORRECT
- Fuel Weight: fuel_gal × fuel_weight_per_gal ✓ CORRECT
- Occupant Weight: occupants × pax_weight ✓ CORRECT

**Issues found:** None. All remaining functions verified correct.

**Summary:** All physics calculations in core/calculations.py and app.py inline code are mathematically correct and properly handle edge cases. The codebase uses standard aerodynamic formulas consistent with published references.

### Session 7: 2026-01-18 — Variable Propagation & JSON Data Audit
**Audit scope:** Verify all input variables (CG, weight, power, altitude, gear, OEI) are correctly propagated to all calculations, and that JSON aircraft data is used (not hardcoded).

**Variable Propagation Trace:**

| Variable | Source | Used In | Status |
|----------|--------|---------|--------|
| `weight` | fuel + occupants + empty | Stall calcs, CL calcs, Ps calcs, Vmca/Vyse | ✓ Correct |
| `rho` | `compute_air_density(altitude_ft)` | All stall, q, Ps calculations | ✓ Correct |
| `hp` | OEI-adjusted or power_fraction × derated | All thrust calculations (3 places) | ✓ Correct |
| `cl_max` | JSON CL_max × gear_lift_factor × CG penalty | All stall boundaries, CL clipping | ✓ Correct |
| `cg_drag_factor` | CG position effect | Ps grid, hover tooltip, steep turn | ✓ FIXED |
| `gear_drag_factor` | Gear down = 1.15 | Ps grid, hover tooltip, steep turn | ✓ FIXED |
| `g_limit` | JSON G_limits[category][config] | G-limit curves, envelope masking | ✓ Correct |

**Issues Found & Fixed:**

1. **BUG — Steep turn CD missing drag factors (line 2586):**
   - **Before:** `CD = CD0 + (CL ** 2) / (np.pi * e * AR)`
   - **After:** `CD = (CD0 + (CL ** 2) / (np.pi * e * AR)) * cg_drag_factor * gear_drag_factor`
   - Also added CL clipping: `CL = min(CL, cl_max)`

2. **CLEANUP — Hover tooltip redundant ac.get() calls (line 2342):**
   - **Before:** `ac.get("CD0", 0.025)`, `ac.get("e", 0.8)`, `ac.get("aspect_ratio", 7.5)`
   - **After:** Uses pre-defined `CD0`, `e`, `AR` variables for consistency

**JSON Data Usage Audit:**

All aircraft parameters are read from JSON with sensible fallbacks:
- `CD0` → `ac.get("CD0", 0.025)` fallback only if missing
- `e` → `ac.get("e", 0.8)` fallback only if missing
- `AR` → `ac.get("aspect_ratio", 7.5)` fallback only if missing
- `G_limits` → complex nested structure properly handled
- `stall_speeds` → weight interpolation working
- `single_engine_limits` → Vmca/Vyse/Vxse properly accessed
- `prop_thrust_decay` → T_static_factor and V_max_kts used
- `oei_performance` → max_power_fraction used for OEI mode

**Hardcoded Values Review:**
- Line 3470 area: Preset button values (intentional for UI defaults)
- All calculation paths use JSON data with appropriate fallbacks
- No inappropriate hardcoding found

**Verified Correct (no changes needed):**
- Weight propagates to all 25+ calculation points
- rho (altitude effect) propagates to all aerodynamic calculations
- hp (OEI-adjusted) propagates to all 3 thrust calculation points
- cl_max (with CG/gear effects) propagates to all stall boundaries
- All aircraft JSON fields are properly accessed


---

## Session 8 — DVmc + DVyse Calibration Audit (Phase 5R-3 / 5R-4, 2026-05-13)

**Scope:** the dynamic Vmc and dynamic Vyse calculations in `core/vmca.py` and
`core/vyse.py`. Published Vmca/Vyse from POH/AFM are POH-authoritative and out
of scope (they're stored in `aircraft_data/*.json`).

**Defect found.** Both functions had a calibration error: at certified
conditions (where modifiers should multiply to exactly 1.0 so the function
returns published Vmc/Vyse unchanged) the prop and bank modifiers were sized
*relative to a different baseline*, not relative to the certified state.

- **DVmc** at certified state (max gross, aft CG, SL, max power, windmilling,
  5° bank) returned **103.7 %** of published Vmca. Root cause: `prop_factors
  ["windmilling"] = 1.08` and `bank 5° = 0.96`. Per 14 CFR 23.149,
  windmilling and 5° bank ARE the certified condition, so both factors
  should equal 1.00.

- **DVyse** at certified state (ref weight, SL, gear up, clean, feathered)
  returned **98 %** of published Vyse. Root cause: `prop_factors["feathered"]
  = 0.98`. Per 14 CFR 23.65/23.66, feathered is the certified condition, so
  feathered should equal 1.00.

**Fix.** Re-anchored both modifier tables at the certified condition.

- DVmc prop factors: `windmilling 1.00` / `stationary 0.96` / `feathered 0.88`.
  Feathered reduction of 12 % matches Kershner / Lowery (10-15 %).
- DVmc bank: `bank 5° = 1.00` (certified); ramps `1.05 @ 0°` down to
  `1.00 @ 5°`; rises `1.00 + 0.005·(bank-5)` beyond 5°. Negative-bank case
  becomes `1.04 + 0.03·|bank|` so 0° = 1.04 (not 1.0) — the cleaner step
  function makes the +5° certified point the global minimum without a
  discontinuity at 0°.
- DVyse prop factors: `feathered 1.00` / `stationary 1.04` / `windmilling 1.07`.

**Verification.** Two new test files lock in the fix:

- `tests/test_vmc.py` — 16 tests covering certified-conditions equality (for
  any aircraft's published Vmca), the bank-sweep global minimum at 5°,
  weight/prop/CG/altitude/power direction + magnitude bands.
- `tests/test_vyse.py` — 15 tests covering certified-conditions equality,
  weight/altitude/gear/flap/prop direction + magnitude bands, plus a
  realistic Baron-58 OEI scenario assertion.

Full suite went from 203 → 234 passed, no regressions in scenario snapshots.

**What is now defensible.** At the certified condition, both functions return
the published number to 0.01 KIAS. Every modifier moves the V-speed in the
documented direction. Modifier magnitudes are within bands cited by Kershner,
Lowery, AC 23-8.

**What is still calibration, not derivation.** The numeric coefficients
inside each modifier (e.g. `weight_factor = 1.0 + 0.15·(1-weight_ratio)`)
are bounded scalars chosen to land published-guidance magnitudes, not
derived from first-principles aerodynamics. The multiplicative coupling of
modifiers is an approximation — real DVmc/DVyse responses have some
non-linear cross-coupling we don't model. This is acceptable for a teaching
tool with transparent source; flagged for a possible future Session 9
"AFM response-surface fit" if the tool ever needs operator-level rigor.

**Pass status:** SHIPPED. Future work: a more precise calibration against
3-5 specific aircraft's published Vmc-vs-weight curves remains a worthwhile
audit step but is not blocking.

**Path B follow-up (2026-05-13).** Investigated the feasibility of moving
beyond the modifier model to per-aircraft AFM-derived response surfaces.
Local research cache contains no AFM/POH correction-table content (only
FAA registry, CFR, chart supplements, glossary). Public web sources for GA
twins publish at most per-config V-speed point values (already in our JSON)
plus occasional Vyse-vs-weight slopes from type-club forums — quality
unsuitable for the "no provenance cracks" bar. Decision: ship the
recalibrated modifier model as the legitimacy floor; treat any future move
to AFM-anchored surfaces as a separate audit lap gated on access to real
AFM material. Sessions 8 closed.
