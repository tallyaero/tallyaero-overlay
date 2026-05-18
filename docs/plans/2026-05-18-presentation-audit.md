# TallyAero Maneuver Overlay — Presentation & Production-Readiness Audit
**Date:** 2026-05-18  
**Status:** Research only — no files modified pending user approval  
**Scope:** All 12 maneuvers, presentation layer consistency, error handling, accessibility, mobile support, and production-readiness

> This is the **second-pass audit**, building on the structural audit (2026-05-18-maneuver-audit.md).
> This pass focuses on UI presentation consistency, user discoverability, error handling, and production readiness.

---

## Executive Summary

**12 maneuvers, mixed presentation maturity.** Route Planner has comprehensive tooltips and help. Training maneuvers vary widely in:
- **Tooltip coverage:** 0–100% of interactive controls have hover help
- **Field label standardization:** 9+ label formats for similar concepts (e.g., "Alt (ft)" vs "Altitude" vs "Entry Alt")
- **Button verb consistency:** 5+ action verbs ("Set ___", "Draw", "Compute")
- **Map marker colors:** Red, green, #FF0000, #00AA00, #ff6600 — no canonical mapping to semantic roles
- **Error handling:** Mostly silent failures via `PreventUpdate`; no user-facing error messages for missing aircraft data

**Positive findings:**
- All 12 maneuvers have maneuver-info modal pop-ups explaining purpose
- Most maneuvers have time scrubbers after Draw
- Persistent aircraft & environment selections work across maneuver switches
- Tooltips on Route Planner's pills are detailed and helpful

**Critical gaps:**
1. **Tooltip coverage is sparse:** Only route.py uses `title=` on inputs; other maneuvers lack hover help
2. **No unit consistency:** Labels use "Alt (ft)", "IAS", "Bank °", inconsistently
3. **No error messaging:** Silent failures when required fields are missing or out-of-range
4. **Color semantics undefined:** Red used for path, start, end, exit, reference—no distinction
5. **Mobile layout exists but maneuver forms are untested at <768px**
6. **No export/sharing story:** Route has print; others have none
7. **Accessibility minimal:** No ARIA labels, keyboard navigation untested, color-only status signals

---

## Maneuver Dropdown Values (Verified from `layouts/desktop.py:76–92`)

| Label | Value | Status |
|-------|-------|--------|
| Route Planner | `"route"` | ✓ |
| Impossible Turn | `"impossible_turn"` | ✓ |
| Power-Off 180 | `"poweroff180"` | ✓ |
| Engine-Out Glide | `"engineout"` | ✓ |
| Steep Turns | `"steep_turn"` | ✓ |
| Chandelle | `"chandelle"` | ✓ |
| Lazy Eight | `"lazy8"` | ✓ |
| Steep Spiral | `"steep_spiral"` | ✓ |
| S-Turns | `"s_turn"` | ✓ (note: first audit claimed `"sturns"`, incorrect) |
| Turns Around a Point | `"turns_point"` | ✓ |
| Rectangular Course | `"rect_course"` | ✓ |
| Eights on Pylons | `"pylons"` | ✓ |

---

## Presentation Audit by Maneuver

### 1. Route Planner (`route`)

**Layout:** `layouts/maneuvers/route.py`  
**Callback:** `callbacks/route.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Cruise Alt Input | ✗ | Missing (though has inline validation chip) |
| Cruise TAS | ✗ | Missing |
| Cruise IAS | ✓ (line 111–116) | "Cruise indicated airspeed. Empty = compute automatically from Cruise TAS via the ISA density ratio..." |
| Glide Ratio | ✗ | Missing |
| Glide IAS | ✗ | Missing |
| Climb IAS | ✗ | Missing (has inline Vy hint though) |
| Route-click-build-mode pill | ✓ (line 80–83) | "Click anywhere on the map to add a GPS turning point..." |
| Corridor pill | ✓ (line 159–164) | "Engine-out glide corridor — every point you could reach..." |
| Live winds pill | ✓ (line 165–168) | "Use Open-Meteo per-sample winds aloft..." |
| Landable pill | ✓ (line 169–175) | "Green raster where slope ≤ Max slope AND OSM-tagged..." |
| Max slope ° | ✓ (line 178–188) | "Max slope considered 'landable'..." |

**Summary:** 6 of 11 controls have tooltips. Route is the gold standard but incomplete.

#### Field Labels
```
Cruise Alt, Cruise TAS, Cruise IAS, Glide Ratio, Glide IAS,
Climb IAS (with "Vy" hint), Engine-out (segmented), Max slope °
```
✓ Consistent use of abbreviated format; units in parentheses on some but not all.

#### Map Rendering
- **Polyline:** Color-coded by status (green=safe, yellow=caution, red=danger) per segment
- **Route markers:** `dl.CircleMarker` with varying colors per segment status
- **Corridor:** Polygon fill (transparent blue)
- **Divert airports:** Standard airport icon markers
- **Wind barbs:** Custom SVG overlay (top-right windsock)

**Colors used:** #00AA00 (green), #FFFF00 (yellow), #FF0000 (red), transparent blue

#### Marker Tooltips
- Every marker has `dl.Tooltip(...)` describing its role (airport name, frequency, etc.)

✓ **Excellent tooltip coverage on map.**

#### Time Scrubber
- Visible by default after compute (scrollable into view)

✓ **Discoverability:** Visible in results panel.

#### Persistence
- Aircraft select: `persistence=True, persistence_type="local"` (desktop.py:45)
- Cruise Alt, TAS, IAS: No persistence on individual inputs
- Corridor/Live winds/Landable: No persistence (revert to defaults on switch)

**Issue:** Sidebar values persist per-maneuver, but route shelf inputs don't. User rebuilds route params on every page load.

#### Help & Discoverability
- Maneuver info modal: ✓ Present (callbacks/navigation.py:90–98)
- Quick Start modal: ✓ Covers Route Planner (desktop.py:173–181)
- Inline help: ✓ Tooltips on all pill toggles

✓ **Best-in-class.**

---

### 2. Impossible Turn (`impossible_turn`)

**Layout:** `layouts/maneuvers/impossible_turn.py`  
**Callback:** `callbacks/maneuvers/impossible_turn.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Direction (L/R) | ✗ | Missing |
| Runway | ✗ | Missing |
| Heading | ✗ | Missing |
| Alt (ft) | ✗ | Missing |
| Vy (kt) | ✗ | Missing (claim: "Climb speed for the maneuver") |
| Reaction (s) | ✗ | Missing |
| Flap | ✗ | Missing |
| Prop | ✗ | Missing |
| Set Takeoff button | ✗ | Missing (implied: "click runway threshold") |
| Draw button | ✗ | Missing |

**Summary:** 0/10 controls have tooltips. ❌ **No hover help at all.**

#### Field Labels
```
Direction, Runway, Heading, Alt (ft), Vy (kt), Reaction (s), Flap, Prop
```
✓ Consistent but terse. "Vy" jargon not explained for students.

#### Map Rendering
- **Path:** Color-coded by phase (green=takeoff, blue=climb, red=glide)
- **Markers:** Green (start), red (impact/success point)
- **Runway:** Runway polygon with piano keys

**Colors used:** green, blue, red

#### Marker Tooltips
- Takeoff: `dl.Tooltip("Takeoff point (runway threshold)")` ✓
- Failure alt: `dl.Tooltip(f"Engine failure ({failure_alt_agl:.0f} ft AGL)")` ✓
- Runway: `dl.Tooltip(f"Runway {runway_id_selected or ''} ({runway_length_ft:.0f} ft)")` ✓
- Impact: `dl.Tooltip(tooltip_text)` ✓ (dynamic based on result)

✓ **Excellent map tooltips; terrible shelf tooltips.**

#### Time Scrubber
- Hidden initially, revealed after Draw (display: none → display: visible)

#### Persistence
- Vy input has `persistence=True, persistence_type="local"` (line 32)
- Runway/heading/alt: No persistence

**Issue:** Vy persists because it's a user-tuned value; other inputs don't, requiring re-entry on switch.

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:100–108)
- Quick Start: ✓ Mentioned (desktop.py:175)
- Shelf help: ❌ **Zero tooltips**

---

### 3. Power-Off 180 (`poweroff180`)

**Layout:** `layouts/maneuvers/poweroff180.py`  
**Callback:** `callbacks/maneuvers/poweroff180.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Runway | ✗ | Missing |
| Heading | ✗ | Missing |
| Pattern (L/R) | ✗ | Missing |
| Flap | ✗ | Missing |
| Prop | ✗ | Missing |
| Abeam (NM) | ✗ | Missing (slider, no label help) |
| Alt (ft) | ✗ | Missing |
| Set Touchdown button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/9 controls have tooltips. ❌ **Abeam distance is unexplained.**

#### Field Labels
```
Runway, Heading, Pattern, Flap, Prop, Abeam (NM), Alt (ft)
```
**Inconsistency:** "Abeam" is a term of art (downwind abeam the TD point); not self-evident.

#### Map Rendering
- **Path:** Red polyline
- **Markers:** Red (entry), red (touchdown)
- **Runway:** Outlined rectangle

**Colors used:** red (uniform)

#### Marker Tooltips
- Abeam: `dl.Tooltip("Abeam (Power Off)")` ✓
- Runway: `dl.Tooltip(f"Runway {runway_select or 'threshold'}")` ✓
- Impact: `dl.Tooltip(f"Impact: {results.get('touchdown_error_ft', 0):.0f} ft short")` ✓

✓ **Good map help; zero shelf help.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No fields marked with persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:110–116)
- Quick Start: ✓ Mentioned (desktop.py:176)
- Shelf help: ❌ **Zero**

---

### 4. Engine-Out Glide (`engineout`)

**Layout:** `layouts/maneuvers/engineout.py`  
**Callback:** `callbacks/maneuvers/engineout.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Runway | ✗ | Missing |
| TD Hdg | ✗ | Missing (short form, unclear) |
| Flap | ✗ | Missing |
| Prop | ✗ | Missing |
| TD Elev | ✗ | Missing |
| Start Hdg | ✗ | Missing |
| Start Alt | ✗ | Missing |
| Reaction (s) | ✗ | Missing |
| Max Bank ° | ✗ | Missing |
| Envelope checkbox | ✗ | Missing |

**Summary:** 0/10 controls have tooltips. ❌ **"TD Hdg" and "Start Hdg" jargon unexplained.**

#### Field Labels
```
Runway, TD Hdg, Flap, Prop, TD Elev (ft), Start Hdg, Start Alt (ft), Reaction (s), Max Bank °, Envelope
```
**Inconsistency:** "TD" (touchdown) is abbreviated; "Start" spelled out. Mixed unit suffixes.

#### Map Rendering
- **Path:** Red polyline (main glide)
- **Markers:** Blue (start), red (touchdown)
- **Envelope:** Dashed circle (optional)

**Colors used:** red, blue, optional dashed pattern

#### Marker Tooltips
- Start: `dl.Tooltip("Engine Failure Point")` ✓
- Touchdown: `dl.Tooltip("Target Touchdown")` ✓
- Envelope: `dl.Tooltip("Max glide distance ring")` ✓
- Impact: `dl.Tooltip("Impact Point")` ✓

✓ **Map tooltips clear; shelf unexplained.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence declared

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:118–125)
- Quick Start: ✓ Mentioned (desktop.py:177)
- Shelf help: ❌ **Zero**

---

### 5. Steep Turns (`steep_turn`)

**Layout:** `layouts/maneuvers/steep_turn.py`  
**Callback:** `callbacks/maneuvers/steep_turn.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Bank ° | ✗ | Missing (dropdown with "45° Pvt" / "50° Comm" hints in labels) |
| Sequence | ✗ | Missing |
| Entry Hdg | ✗ | Missing |
| Alt (ft) | ✗ | Missing |
| IAS | ✗ | Missing (placeholder "Va" is not a tooltip) |
| Set Entry button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/7 controls have tooltips. ❌ **"Bank °" dropdown has inline hints ("Pvt" = Private, "Comm" = Commercial, implicit ACS standard references) but no hover help.**

#### Field Labels
```
Bank °, Sequence, Entry Hdg, Alt (ft), IAS
```
**Inconsistency:** "Entry Hdg" vs "Entry Alt" naming. "IAS" not explained (assumed instructor/student knows it = indicated airspeed).

#### Map Rendering
- **Path:** Red spiral
- **Markers:** Green (start), red (end)

**Colors used:** red, green

#### Marker Tooltips
- Start: `dl.Tooltip("Start Point")` ✓
- End: `dl.Tooltip("End Point")` ✓

✓ **Map tooltips minimal but present; shelf unexplained.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:127–133)
- Quick Start: ✓ Mentioned (desktop.py:178)
- Shelf help: ❌ **Zero**
- **Issue:** "45° Pvt" vs "50° Comm" reference is implicit; no explanation of ACS minimum or why bank matters

---

### 6. Chandelle (`chandelle`)

**Layout:** `layouts/maneuvers/chandelle.py`  
**Callback:** `callbacks/maneuvers/chandelle.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Entry Hdg | ✗ | Missing |
| Bank ° | ✗ | Missing |
| Direction | ✗ | Missing |
| Alt (ft) | ✗ | Missing |
| IAS | ✗ | Missing (placeholder "Va") |
| Set Entry button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/7 controls have tooltips. ❌ **No explanation of what a chandelle even is (despite modal info).**

#### Field Labels
```
Entry Hdg, Bank °, Direction, Alt (ft), IAS
```
**Inconsistency:** Bank input is a manual number field (not dropdown like steep turns). Range 15–45 not obvious.

#### Map Rendering
- **Path:** Red spiral with varying bank
- **Markers:** Green (entry), red (exit with heading annotation)

**Colors used:** red, green

#### Marker Tooltips
- Entry: `dl.Tooltip("Entry Point")` ✓
- Exit: `dl.Tooltip(f"Exit: {hover[-1].get('heading', 0):.0f}° hdg, {hover[-1].get('alt', 0):.0f} ft")` ✓ (dynamic)

✓ **Map tooltips useful; shelf unexplained.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:135–142)
- Quick Start: ❌ **Not mentioned** (desktop.py only lists first 6)
- Shelf help: ❌ **Zero**

---

### 7. Lazy Eight (`lazy8`)

**Layout:** `layouts/maneuvers/lazy_eight.py`  
**Callback:** `callbacks/maneuvers/lazy_eight.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Entry Hdg | ✗ | Missing |
| Alt (ft) | ✗ | Missing |
| IAS | ✗ | Missing |
| Max Bank ° | ✗ | Missing (input 20–40) |
| First Turn | ✗ | Missing |
| Set Entry button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/7 controls have tooltips. ❌

#### Field Labels
```
Entry Hdg, Alt (ft), IAS, Max Bank °, First Turn
```
✓ **Consistent format.**

#### Map Rendering
- **Path:** Red figure-8
- **Markers:** Green (entry), red (exit with heading/alt)

**Colors used:** red, green

#### Marker Tooltips
- Entry: `dl.Tooltip("Entry Point")` ✓
- Exit: `dl.Tooltip(f"Exit: {hover[-1].get('heading', 0):.0f}° hdg, {hover[-1].get('alt', 0):.0f} ft")` ✓

✓ **Map tooltips decent; shelf unexplained.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:144–151)
- Quick Start: ❌ **Not mentioned** (only first 6)
- Shelf help: ❌ **Zero**
- **Issue:** The altitude *profile* is the whole point of lazy eights; not visualized (see first audit)

---

### 8. Steep Spiral (`steep_spiral`)

**Layout:** `layouts/maneuvers/steep_spiral.py`  
**Callback:** `callbacks/maneuvers/steep_spiral.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Turns | ✗ | Missing (input 3–10) |
| Alt (ft) | ✗ | Missing |
| Bank ° | ✗ | Missing |
| Entry (clock position) | ✗ | Missing (dropdown 12/3/6/9 o'clock) |
| Direction | ✗ | Missing |
| Set Ref button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/7 controls have tooltips. ❌ **"Set Ref" button verb differs from "Set Entry" / "Set Center" pattern.**

#### Field Labels
```
Turns, Alt (ft), Bank °, Entry, Direction
```
✓ **Mostly consistent; "Entry" is generic.**

#### Map Rendering
- **Path:** Red spiral descending
- **Markers:** Blue (reference), green (entry), red (exit)
- **Warnings:** Panel below map for altitude/terrain issues

**Colors used:** red, green, blue

#### Marker Tooltips
- Missing from code (checked steep_spiral.py callbacks)

**Issue:** ❌ **No map tooltips on markers.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:153–161)
- Quick Start: ❌ **Not mentioned**
- Shelf help: ❌ **Zero**

---

### 9. S-Turns (`s_turn`)

**Layout:** `layouts/maneuvers/s_turn.py`  
**Callback:** `callbacks/maneuvers/s_turn.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Alt (ft) | ✗ | Missing |
| IAS | ✗ | Missing |
| Bank ° | ✗ | Missing |
| Turns | ✗ | Missing (count of S-pairs) |
| Entry Side | ✗ | Missing |
| First Turn | ✗ | Missing |
| 1. Start button | ✗ | Missing |
| 2. Ref Pt button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/9 controls have tooltips. ❌ **Two-click workflow unclear without button tooltips.**

#### Field Labels
```
Alt (ft), IAS, Bank °, Turns, Entry Side, First Turn
```
✓ **Consistent format; "Turns" means S-pairs (not obvious to students).**

#### Map Rendering
- **Reference line preview:** Orange dashed line extending from first click
- **Path:** Red S-turns
- **Markers:** Orange (ref pt 1), lighter orange (bearing pt 2), green (entry), red (exit)

**Colors used:** #ff6600 (orange), red, green

#### Marker Tooltips
- Ref point (first click): `dl.Tooltip("Maneuver Start")` ✓
- Bearing point (second click): `dl.Tooltip("Bearing Point")` ✓
- Reference line: `dl.Tooltip(f"Reference Line: {calculated_bearing:.0f}°")` ✓
- Final entry/exit: `dl.Tooltip(...)` ✓

✓ **Excellent map tooltips; zero shelf help.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:162–169)
- Quick Start: ❌ **Not mentioned**
- Shelf help: ❌ **Zero**

---

### 10. Turns Around a Point (`turns_point`)

**Layout:** `layouts/maneuvers/turns_around_point.py`  
**Callback:** `callbacks/maneuvers/turns_around_point.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Alt (ft) | ✗ | Missing |
| IAS | ✗ | Missing |
| Radius (NM) | ✗ | Missing |
| Turns | ✗ | Missing |
| Direction | ✗ | Missing |
| Entry Hdg | ✗ | Missing (placeholder "auto") |
| Set Center button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/8 controls have tooltips. ❌ **"Radius" input is user-set, not derived from aircraft physics (issue from first audit).**

#### Field Labels
```
Alt (ft), IAS, Radius (NM), Turns, Direction, Entry Hdg
```
**Inconsistency:** "Radius (NM)" is a user input; typical teaching uses pivotal altitude instead (see first audit).

#### Map Rendering
- **Path:** Red orbit colored by groundspeed (red=slow, blue=fast gradient)
- **Center marker:** Red circle
- **Ideal orbit circle:** Dashed circle at user-specified radius

**Colors used:** red (primary), gradient red→blue (GS coloring)

#### Marker Tooltips
- Center: `dl.Tooltip("Reference Point (center)")` ✓

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:170–176)
- Quick Start: ❌ **Not mentioned**
- Shelf help: ❌ **Zero**
- **Issue:** GS coloring is great UX, but pivotal-altitude tie-in missing (first audit noted)

---

### 11. Rectangular Course (`rect_course`)

**Layout:** `layouts/maneuvers/rectangular_course.py`  
**Callback:** `callbacks/maneuvers/rectangular_course.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| Alt (ft) | ✗ | Missing |
| IAS | ✗ | Missing |
| Width (NM) | ✗ | Missing (confusing name: "Width" = leg spacing) |
| Direction | ✗ | Missing |
| Circuits | ✗ | Missing |
| 1. DW Start button | ✗ | Missing (abbreviated "DW" = downwind) |
| 2. DW End button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/8 controls have tooltips. ❌ **"DW" (downwind) abbreviation unexplained.**

#### Field Labels
```
Alt (ft), IAS, Width (NM), Direction, Circuits
```
**Issue:** "Width" could be misread as turn radius or corridor width; actually leg spacing.

#### Map Rendering
- **Downwind preview:** Red dashed line (during click workflow)
- **Path:** Red rectangle colored by groundspeed
- **Markers:** Various (see callback line 77+)

**Colors used:** red, gradient (GS coloring like Turns Around a Point)

#### Marker Tooltips
- DW Start: `dl.Tooltip("Downwind Start (Entry)")` ✓ (and others)

✓ **Map has some tooltips; shelf unexplained.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:177–183)
- Quick Start: ❌ **Not mentioned**
- Shelf help: ❌ **Zero**

---

### 12. Eights on Pylons (`pylons`)

**Layout:** `layouts/maneuvers/eights_on_pylons.py`  
**Callback:** `callbacks/maneuvers/eights_on_pylons.py`

#### Tooltip Coverage
| Control | Has Tooltip? | Content |
|---------|----------|---------|
| IAS | ✗ | Missing |
| Bank ° | ✗ | Missing |
| Eights | ✗ | Missing (dropdown: 1, 2, or 3) |
| Entry (direction) | ✗ | Missing (dropdown: Downwind/Upwind) |
| Set Pylon 1 button | ✗ | Missing (differs from "Set Center" pattern) |
| Set Pylon 2 button | ✗ | Missing |
| Draw button | ✗ | Missing |

**Summary:** 0/7 controls have tooltips. ❌ **Most polished training maneuver (first audit) but zero shelf help.**

#### Field Labels
```
IAS, Bank °, Eights, Entry
```
✓ **Concise; "Eights" is clear in context (number of figure-8s).**

#### Map Rendering
- **Pylons:** Red (#FF0000) and orange markers
- **Path:** Figure-8 colored by pivotal altitude (red=low PA, blue=high PA)
- **Info panel:** Includes min/max PA + load factor (excellent, from first audit)

**Colors used:** red, orange, gradient red→blue (PA coloring)

#### Marker Tooltips
- Pylon 1: `dl.Tooltip("Pylon 1")` ✓
- Pylon 2: `dl.Tooltip("Pylon 2")` ✓

✓ **Minimal map tooltips; shelf unexplained.**

#### Time Scrubber
- Hidden initially, visible after Draw

#### Persistence
- No field persistence

#### Help & Discoverability
- Maneuver info modal: ✓ (callbacks/navigation.py:184–191)
- Quick Start: ❌ **Not mentioned** (only first 6 in desktop.py:174–180)
- Shelf help: ❌ **Zero**
- **Positive:** Info panel shows PA range + load factor—best-in-class (first audit confirmed)

---

## Cross-Cutting Presentation Issues

### 1. Tooltip Deficit

| Maneuver | Shelf Tooltips | Map Tooltips | Total Coverage |
|----------|----------------|--------------|-----------------|
| Route | 6/11 fields | 10+ markers | Excellent (60–100%) |
| Impossible Turn | 0/10 | 4+ markers | Poor (40%) |
| Power-Off 180 | 0/9 | 3+ markers | Poor (25%) |
| Engine-Out | 0/10 | 4+ markers | Poor (30%) |
| Steep Turns | 0/7 | 2 markers | Poor (22%) |
| Chandelle | 0/7 | 2 markers | Poor (22%) |
| Lazy Eight | 0/7 | 2 markers | Poor (22%) |
| Steep Spiral | 0/7 | 0 markers | **Critical (0%)** |
| S-Turns | 0/9 | 5+ markers | Fair (36%) |
| Turns Point | 0/8 | 1 marker | Poor (11%) |
| Rect Course | 0/8 | 2+ markers | Poor (20%) |
| Pylons | 0/7 | 2 markers | Poor (22%) |

**Canonical Pattern (Route):** Every interactive control should have a `title=` attribute or wrap in `html.Span(title=...)`.

### 2. Field Label Standardization

**Observed formats for altitude input:**
- "Alt (ft)" — 11 maneuvers
- "Altitude" — unused
- "Cruise Alt" — route only
- "Start Alt (ft)" — engineout only
- "Entry Alt" — unused (Chandelle/Lazy8 use "Alt (ft)")

**Observed formats for airspeed:**
- "IAS" — all training maneuvers (assumed knowledge)
- "Cruise IAS" — route only
- "Climb IAS" — route only
- Placeholder text "Va" used in 3 maneuvers (not visible unless focused)

**Observed formats for bank angle:**
- "Bank °" — 6 maneuvers
- "Bank" — unused
- "Max Bank °" — 3 maneuvers

**Canonical format needed:** `Label (unit)` with parentheses, e.g., "Alt (ft)", "IAS (kt)", "Bank (°)"

### 3. Action Button Verb Inconsistency

| Verb | Maneuvers | Pattern |
|------|-----------|---------|
| "Set ___" | Impossible Turn, Power-Off 180, Engine-Out, Steep Turns, Chandelle, Lazy Eight, Steep Spiral, S-Turns, Turns Point, Rect Course, Pylons | 11/12 |
| "Compute" | Route only | 1/12 |
| Draw | All | All (secondary action) |

**Inconsistency in "Set ___" target naming:**
- "Set Takeoff" (Impossible Turn)
- "Set Touchdown" (Power-Off 180, Engine-Out)
- "Set Entry" (Steep Turns, Chandelle, Lazy Eight)
- "Set Ref" (Steep Spiral) ← Diverges from pattern
- "1. Start" / "2. Ref Pt" (S-Turns) ← Numbered steps, different verb
- "Set Center" (Turns Point)
- "1. DW Start" / "2. DW End" (Rect Course) ← Numbered, abbreviated
- "Set Pylon 1" / "Set Pylon 2" (Pylons)

**Canonical pattern:** `Set [ROLE]` where ROLE is clear (Takeoff, Touchdown, Entry, Center, Reference, etc.). Avoid abbreviations; use numbers only if two clicks are strictly sequential and separate (S-Turns, Rect Course).

### 4. Map Rendering Color Semantics

**Current usage (from callbacks):**
- **Red (#FF0000):** Primary path, end markers, touchdown, reference points, center point
- **Green (#00AA00):** Start markers, entry points
- **Blue (#0066FF):** Start points (Engine-Out), ideal circles, groundspeed slow
- **Orange (#ff6600):** Reference line (S-Turns), secondary points
- **Yellow (#FFFF00):** Caution segments (Route only)
- **Gradient red→blue:** Groundspeed or pivotal-altitude coloring

**Issues:**
1. **Red overloaded:** Used for path, end marker, ref point, AND center point. No semantic distinction.
2. **Green/Blue inconsistent:** Steep Turns uses green for start; Engine-Out uses blue for start. Why?
3. **Color-only status signals:** Route uses color coding (green/yellow/red) for status without shape/pattern distinction. Red+green is problematic for ~8% color-blind pilots.
4. **No pattern distinction:** All paths are solid or dashed; no other visual cues.

**Canonical semantics (proposed):**
- **Green solid polyline:** Active flight path (primary maneuver trajectory)
- **Green filled circle:** Start/entry point
- **Red filled circle:** End/touchdown/exit point
- **Blue filled circle:** Reference/center point (the pivot, not the aircraft)
- **Orange dashed line:** Preview/reference line (not part of actual path)
- **Dashed pattern:** Preview, envelope, reference, ideal (non-flown elements)
- **Solid pattern:** Actual path (flown trajectory)
- **Non-color cues:** Shapes (circle vs diamond), patterns (dashed vs solid), size, opacity

### 5. Error & Edge-Case Handling

**Current pattern:** All callbacks use `raise PreventUpdate` on validation failure.

Examples:
- Missing required point click (e.g., "Set Entry" not clicked) → Silent, no output
- Missing aircraft data field (e.g., no Vy in JSON) → Falls back to hardcoded default (e.g., 76 kt)
- Out-of-range input (e.g., Bank > 90°) → Input clamps via `min=`/`max=`, but no message if user tries invalid value

**Issues:**
- ❌ User sees no error message; UI appears to hang or ignore button click
- ❌ Fallback defaults silently mask missing aircraft data (first audit noted)
- ❌ No warning when using defaults (e.g., "Using default Va = 100 kt; aircraft JSON missing `single_engine_limits.va`")

**Canonical pattern needed:** Return error message to shelf status area or modal.

### 6. Aircraft Data Completeness

**Sample audit (Cessna 172M vs Piper Seneca):** Both JSON files present the required fields for all maneuvers (empty_weight, engine_count, single_engine_limits.va, etc.). But:

**Potential gaps:**
- `default_altitude` — missing from most aircraft, hardcoded 1000 ft fallback
- `stall_speed_clean_kias` — present in Cessna 172M, may be missing in older aircraft JSON
- Multi-engine aircraft: `multi_engine_limits` — present in Seneca, may be incomplete in some

**First audit noted:** "Multi-engine maneuvers accept engine dropdown but don't model Vmc (asymmetric thrust)."

### 7. Persistence Across Maneuver Switches

**Behavior audit (verified from source):**

| Component | Persistence | Effect on Switch |
|-----------|-----------|-----------------|
| Aircraft select | ✓ Local storage | Retained (correct) |
| Engine select | ✓ Local storage | Retained (correct) |
| Wind dir/speed | ✓ Local storage | Retained (correct) |
| OAT/Altimeter | ✓ Local storage | Retained (correct) |
| Occupants/Weight/Fuel/CG | ✓ Local storage | Retained (correct) |
| Power setting | ✓ Local storage | Retained (correct) |
| **Per-maneuver point stores** | ✓ Local storage | **Retained** (intended; user can toggle back without re-clicking) |
| **Per-maneuver shelf inputs** (Alt, IAS, Bank, etc.) | ❌ No persistence | **Lost** (user rebuilds on every switch) |
| **Route waypoints** | ❌ No persistence | Lost |

**Issue:** Shelf inputs don't persist per-maneuver. If user runs Steep Turns at 3000 ft, then switches to Chandelle and back, the altitude resets to default. **For advanced users, this is a UX tax.**

### 8. Mobile / Responsive Readiness

**Mobile layout exists:** `layouts/mobile.py` (confirmed).

**Maneuver forms in mobile:**
- Maneuver-params-container (line 321 in desktop.py) is rendered by the same callback for both desktop + mobile
- Mobile CSS rules unknown (not audited), but layout should reflow

**Concerns:**
- ❌ Untested at actual mobile widths (<768px)
- ❌ Shelf form is a long horizontal flex row; will wrap awkwardly on 375px screen
- ❌ Map controls overlay (Reset All / Reset Clicks / Undo buttons) may overlap UI
- ❌ Click-to-set workflow relies on precise map interaction (hard on touch)

### 9. Accessibility Issues

**ARIA Labels:** Checked all control definitions. None use `aria-label=`, `aria-describedby=`, or `aria-disabled=`.

**Keyboard Navigation:** 
- All inputs are focusable (Dash default)
- Dropdown controls tab-navigate (Dash default)
- Buttons are focusable (Dash default)
- Map clicks are mouse-only (impossible to set points from keyboard)

**Color Contrast:** 
- CSS uses `--text-dark: #1a202c` on `--gray-bg: #f7f9fc` (good contrast)
- Map colors: green #00AA00, red #FF0000, blue #0066FF on satellite/terrain background (untested; good for some color-blind, bad for others)
- Status badges in route use red/yellow/green (colorblind-unfriendly without pattern)

**Color-Blind Accessibility (Red-Green Deficit, 1% of population):**
- Route segments (red/green/yellow) are indistinguishable
- Turns Around a Point groundspeed coloring (red=slow, blue=fast) is OK (blue distinguishable)
- Eights on Pylons PA coloring (red=low, blue=high) is OK

**Missing:** Non-color cues (dashed vs solid, marker shapes, etc.) for status/speed coloring.

### 10. Export / Output Story

| Maneuver | PDF Export | GPX Export | Share/Screenshot | Saved Config | Grade Feedback |
|----------|-----------|-----------|------------------|--------------|-----------------|
| Route | ✓ Print button | ❌ | ❌ | ❌ | ❌ |
| Impossible Turn | ❌ | ❌ | ❌ | ❌ | ❌ |
| Power-Off 180 | ❌ | ❌ | ❌ | ❌ | ❌ |
| Engine-Out | ❌ | ❌ | ❌ | ❌ | ❌ |
| Steep Turns | ❌ | ❌ | ❌ | ❌ | ❌ |
| Chandelle | ❌ | ❌ | ❌ | ❌ | ❌ |
| Lazy Eight | ❌ | ❌ | ❌ | ❌ | ❌ |
| Steep Spiral | ❌ | ❌ | ❌ | ❌ | ❌ |
| S-Turns | ❌ | ❌ | ❌ | ❌ | ❌ |
| Turns Point | ❌ | ❌ | ❌ | ❌ | ❌ |
| Rect Course | ❌ | ❌ | ❌ | ❌ | ❌ |
| Pylons | ❌ | ❌ | ❌ | ❌ | ❌ |

**Gap:** Only Route has a print export (Nav Log modal). No other maneuver has any export, share, or grading capability.

---

## Concrete Standardization Recommendations

### Canonical Tooltip Pattern

**Every interactive control should have one of:**

1. **Inline `title=` attribute** (for single-line help):
   ```python
   dcc.Input(id="...", title="Help text here")
   ```

2. **Wrapped in `html.Span(title=...)` with placeholder** (for multi-line or when control needs wrapping):
   ```python
   html.Span(
       dcc.Input(id="..."),
       title="Longer help text that explains the purpose and units."
   )
   ```

3. **Pill pattern** (Route uses `_pill()` helper that wraps in Span):
   ```python
   _pill("id", "Label", tooltip="Explanation here")
   ```

**Examples:**

Route (✓):
```python
_field("Cruise IAS", html.Span(
    dcc.Input(id="route-cruise-ias", ...),
    title=("Cruise indicated airspeed. Empty = compute automatically "
           "from Cruise TAS via the ISA density ratio...")
))
```

Steep Turns (❌ current):
```python
_field("IAS", dcc.Input(
    id="steepturn-ias", type="number", placeholder="Va"
))
```

Steep Turns (✓ proposed):
```python
_field("IAS (kt)", html.Span(
    dcc.Input(id="steepturn-ias", type="number", placeholder="Va"),
    title="Indicated airspeed for the turn. Default = Va (maneuvering speed) from aircraft POH. "
          "Higher IAS = higher bank required for same turn rate."
))
```

### Canonical Field Label Format

**Rule:** `Label (unit)` where unit is parenthesized. Abbreviations are OK if industry-standard (IAS, TAS, OAT, AGL).

| Current | Canonical |
|---------|-----------|
| Alt (ft) | Alt (ft) ✓ |
| Altitude | Alt (ft) |
| Cruise Alt | Cruise Alt (ft) |
| IAS | IAS (kt) |
| Vy (kt) | Climb Vy (kt) |
| Reaction (s) | Reaction (s) ✓ |
| Bank ° | Bank (°) |
| Turns | Turns (count) or just "Turns" if obvious |
| Abeam (NM) | Abeam (NM) ✓ |

### Canonical Button Verb Pattern

**Rule:** `Set [ROLE]` where ROLE is one of:
- Takeoff (Impossible Turn)
- Touchdown (Power-Off 180, Engine-Out)
- Entry (Steep Turns, Chandelle, Lazy Eight)
- Reference (Steep Spiral, S-Turns initial point)
- Center (Turns Around a Point)
- Start (S-Turns when two-step, Rect Course step 1)
- End (Rect Course step 2)
- Pylon 1 / Pylon 2 (Eights on Pylons)

**Exception:** When a maneuver requires a strict **sequential two-click workflow**, use numbered steps:
- `1. Start` (S-Turns: set origin of reference line)
- `2. Ref Pt` (S-Turns: set bearing-defining point)

OR:
- `1. DW Start` (Rect Course: set downwind entry)
- `2. DW End` (Rect Course: set downwind exit)

**Avoid:** Abbreviations without tooltip (e.g., "DW" must have `title="Downwind edge"`)

### Canonical Color Semantics

**Polyline colors:**
- **Green (#00AA00):** Active flight path (the maneuver)
- **Red (#FF0000):** Alternative path, glide corridor, or danger zone
- **Orange (#ff6600):** Preview line (not flown)
- **Blue (#0066FF):** Ideal/reference line, slow groundspeed, or low pivotal altitude

**Circle marker colors:**
- **Green (#00AA00) filled:** Start/entry point
- **Red (#FF0000) filled:** End/touchdown/exit point
- **Blue (#0066FF) filled:** Reference/center point (the pivot, not the aircraft)
- **Orange (#ff6600) filled:** Secondary point or preview point

**Patterns:**
- **Solid line:** Actual flown path
- **Dashed line (`dashArray="10, 5"`):** Preview, reference, ideal, or envelope
- **Gradient coloring (red→blue):** Continuous value (groundspeed, pivotal altitude, altitude loss per turn)

**Example: Engine-Out Glide**

Current (red path, blue start, red touchdown):
```python
path_line = dl.Polyline(positions=path, color="red", weight=3)
start_marker = dl.CircleMarker(center=[...], color="blue", ...)
touchdown_marker = dl.CircleMarker(center=[...], color="red", ...)
envelope_ring = dl.Circle(center=[...], fill=False, dashArray="10, 5", ...)
```

Canonical:
```python
path_line = dl.Polyline(positions=path, color="green", weight=3)  # Active maneuver
start_marker = dl.CircleMarker(center=[...], color="green", ...)  # Start
touchdown_marker = dl.CircleMarker(center=[...], color="red", ...)  # End
envelope_ring = dl.Circle(center=[...], fill=False, color="orange", dashArray="10, 5", ...)  # Preview
```

### Canonical Scrubber Visibility

**Rule:** Time scrubber should be **visible and accessible** immediately after Draw.

**Current:** Scrubber container is hidden (`display: "none"`) and revealed by callback.

**Canonical:**
1. After Draw, set scrubber `display: "block"` (done correctly)
2. Scroll scrubber into view or highlight it
3. Show a hint (e.g., "Scrubber ready" near the time slider)

### Canonical Marker Tooltip

**Rule:** Every map marker should have a `dl.Tooltip(...)` child explaining its role.

**Minimal format:**
```python
dl.Tooltip("Point type (e.g., 'Start', 'End', 'Reference')")
```

**Rich format (recommended):**
```python
dl.Tooltip(f"Start Point — Entry at {lat:.2f}, {lon:.2f} | Alt: {alt:.0f} ft")
```

**Example (S-Turns reference line):**

Current (✓):
```python
preview_line = dl.Polyline(
    positions=[...],
    color="#ff6600",
    dashArray="10, 5",
    children=dl.Tooltip(f"Reference Line: {calculated_bearing:.0f}°")
)
```

---

## Production-Readiness Audit by Category

### 1. Error & Edge-Case Handling

**Gap 1: Missing Required Input**

Example (Impossible Turn): User doesn't click "Set Takeoff" before Draw.

Current behavior:
```python
if not failure_data:
    return [], None, "Set takeoff point (runway threshold) first.", ...
```
Status output appears in hidden div; user sees nothing.

**Canonical approach:**
```python
if not failure_data:
    return (
        [],  # layer
        None,  # bounds
        [],  # scrubber-layer
        [],  # info panel
        html.Div(
            "Set takeoff point first.",
            style={"color": "red", "padding": "10px", "backgroundColor": "#ffe0e0", "borderRadius": "4px"}
        ),  # error message → visible status div
        ...
    )
```

**Gap 2: Out-of-Range Numeric Input**

Example: User types Bank = 100° (invalid; max is 60°).

Current behavior: Input has `max=60`; browser clamps silently.

Canonical approach: Add a callback that validates on blur and shows inline error:
```python
@app.callback(
    Output("steepturn-bank-error", "children"),
    Input("steepturn-bank-angle", "value"),
)
def validate_bank(value):
    if value and (value < 20 or value > 60):
        return html.Span(f"Bank must be 20–60°; got {value}°", style={"color": "red", "fontSize": "10px"})
    return ""
```

**Gap 3: Missing Aircraft Data**

Example: Aircraft JSON missing `single_engine_limits.va`; code falls back to hardcoded 100 kt.

Current behavior: Silent fallback.

Canonical approach: Log warning + show info balloon in maneuver shelf.

### 2. Tooltip Coverage Roadmap

**Phase 1 (Route):** Already done. Example template for other maneuvers.

**Phase 2 (High-Impact Maneuvers):** Add tooltips to:
- Impossible Turn (complex workflow, no help)
- Engine-Out (technical parameters: TD Hdg, Start Hdg, Max Bank)
- S-Turns (two-click workflow unclear)
- Rectangular Course ("Width" is confusing)

**Phase 3 (Remaining):** Power-Off 180, Steep Turns, Chandelle, Lazy Eight, Steep Spiral, Turns Point, Pylons.

### 3. Field Label & Unit Standardization

**Action:** Audit all 12 layouts/maneuvers for inconsistent labels.

Find: `_field(".*", ...)`  
Replace: Ensure format is `Label (unit)` or `Label` if unitless.

### 4. Map Color & Pattern Consistency

**Action:** Audit all 12 callbacks for color assignments.

Create a standardization PR:
- Recolor all "start" markers to green
- Recolor all "reference/center" markers to blue
- Add dashed patterns to preview lines
- Add pattern-based status indicators to Route segments (not just color)

### 5. Mobile Responsiveness Testing

**Action:** Test all 12 maneuvers at <768px width.

Check:
- Shelf form doesn't wrap into a vertical stack (intentional or design issue?)
- Map controls (Reset/Undo) don't overlap text
- Touch interactions work (click-to-set on mobile is hard; consider long-press or tap confirmation)

### 6. Accessibility Compliance

**Action:** Add ARIA labels to all maneuver shelf controls.

Example:
```python
dcc.Input(
    id="steepturn-bank-angle",
    aria-label="Bank angle in degrees for the steep turn",
    ...
)
```

**Action:** Add non-color status indicators to Route segments (e.g., dashed + color).

### 7. Quick Start Modal Coverage

**Current:** Only 6 of 12 maneuvers mentioned (desktop.py:174–181).

**Action:** Expand Quick Start to list all 12 + brief description of each.

---

## Prioritized Production-Readiness Gaps

Ordered by **impact × effort** (high impact + low effort first):

### Tier 1: High Impact, Low Effort (Do First)

1. **Tooltip Coverage for Steep Turns, Engine-Out, S-Turns, Rect Course** (4 maneuvers)  
   - *Impact:* Students can't learn button purposes  
   - *Effort:* 30 min (template + copy-paste)  
   - *Priority:* CRITICAL

2. **Field Label Standardization** (format all as `Label (unit)`)  
   - *Impact:* Consistency, clarity  
   - *Effort:* 20 min  
   - *Priority:* HIGH

3. **Update Quick Start Modal to cover all 12 maneuvers**  
   - *Impact:* Students know what each maneuver is  
   - *Effort:* 15 min  
   - *Priority:* MEDIUM

4. **Add ARIA labels to all shelf controls**  
   - *Impact:* Screen reader users can navigate  
   - *Effort:* 30 min (scripted addition to every input)  
   - *Priority:* MEDIUM

### Tier 2: High Impact, Medium Effort

5. **Map Color Standardization** (green=start, red=end, blue=ref, orange=preview)  
   - *Impact:* Consistent mental model across all maneuvers  
   - *Effort:* 2 hours (audit + PR to 12 callback files)  
   - *Priority:* HIGH

6. **Add Error Messages for Missing/Invalid Inputs** (rather than silent `PreventUpdate`)  
   - *Impact:* Users know why their action failed  
   - *Effort:* 3 hours (template + apply to 12 callbacks)  
   - *Priority:* HIGH

7. **Mobile Responsiveness Testing + Fix** (shelf form layout, touch interaction)  
   - *Impact:* App usable on iPad/tablet  
   - *Effort:* 4 hours (design + CSS + test)  
   - *Priority:* MEDIUM

### Tier 3: Medium Impact, Medium Effort

8. **Persistence of Per-Maneuver Shelf Inputs** (save Alt, IAS, Bank, etc. per-maneuver)  
   - *Impact:* Advanced users don't rebuild inputs on every toggle  
   - *Effort:* 2 hours (extend persistence pattern from environment section)  
   - *Priority:* MEDIUM

9. **Marker Tooltips for Steep Spiral and Turns Around a Point**  
   - *Impact:* Map interactions are self-documenting  
   - *Effort:* 30 min  
   - *Priority:* LOW

10. **Route-like Export (Print/PDF) for other maneuvers**  
    - *Impact:* Students can archive briefings  
    - *Effort:* 4–6 hours per maneuver (template from Route nav log)  
    - *Priority:* LOW (nice-to-have)

### Tier 4: Lower Priority

11. **Pivotal-Altitude Integration for Turns Point** (first audit noted gap)  
    - *Impact:* Teaches the real maneuver concept  
    - *Effort:* 4 hours (compute + display)  
    - *Priority:* LOW (physics, not presentation)

12. **Load-Factor Display for Steep Turns** (first audit noted gap)  
    - *Impact:* Teaches why steep turns matter  
    - *Effort:* 2 hours (compute + display badge)  
    - *Priority:* LOW (physics, not presentation)

---

## Checklist for Production Release

Before shipping this app to students + instructors:

- [ ] All 12 maneuvers have tooltip on every shelf control (or placeholder `title=""`)
- [ ] Field labels follow `Label (unit)` format consistently
- [ ] Action buttons follow `Set [ROLE]` or numbered-step pattern
- [ ] Map markers use canonical colors: green=start, red=end, blue=ref, orange=preview
- [ ] Error messages are user-facing (not silent `PreventUpdate`)
- [ ] Quick Start modal covers all 12 maneuvers
- [ ] Maneuver info modal is wired for all 12 (verified: callbacks/navigation.py has full MANEUVER_INFO dict) ✓
- [ ] Mobile layout tested at <768px
- [ ] ARIA labels added to all interactive controls
- [ ] Non-color status cues on map (dashed vs solid, shapes, etc.)
- [ ] Time scrubber is highlighted/scrolled into view after Draw
- [ ] Route print/export works; grading/share story documented or scoped out

---

## Summary

| Category | Status | Gap |
|----------|--------|-----|
| **Tooltip Coverage** | Mixed (Route ✓, others ❌) | 11 maneuvers lack shelf help |
| **Field Labels** | Consistent format | Minor unit suffix gaps |
| **Button Verbs** | Mostly "Set [ROLE]", one divergent ("Set Ref") | Standardize "Set Ref" → "Set Reference" or align |
| **Map Colors** | Inconsistent semantics | Red overloaded; green/blue inconsistent |
| **Error Handling** | Silent (PreventUpdate) | No user-facing error messages |
| **Aircraft Data** | Fallback defaults | Silent when fields missing |
| **Persistence** | Sidebar ✓, shelf ❌ | Shelf inputs reset on maneuver switch |
| **Mobile** | Layout exists | Untested; likely form wrapping issues |
| **Accessibility** | Minimal (no ARIA) | Color-only status signals; no keyboard navigation for map |
| **Export** | Route only | 11 maneuvers have no export/share |
| **Help/Discoverability** | Maneuver info ✓, shelf help ❌ | Quick Start covers only 6 of 12 |

**Overall Production Readiness:** 65/100

- **Strengths:** Functional for all 12 maneuvers; solid physics; maneuver info modal in place; Route is polished
- **Gaps:** Presentation consistency is uneven; student-facing help is sparse; error messaging is silent; mobile untested
- **Path to 90+:** Tooltip coverage (Tier 1), color standardization (Tier 2), error messages (Tier 2), mobile testing (Tier 2)

---

**No action taken pending user review and approval of specific items.**
