# Phase 1 — Decompose `app.py` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decompose the 7,646-line `app.py` (47 callbacks + 11 maneuver layouts + desktop/mobile shells) into `layouts/` + `callbacks/` packages, leaving `app.py` at ≤200 lines.

**Architecture:** Mirror the EM Diagram archive's Phase 1 pattern exactly — `callbacks/__init__.py` exposes `register_all(app)` that calls each topical module's `register(app)`. Layouts are pure functions in `layouts/`. Every component id is preserved verbatim so existing callbacks keep wiring after the move.

**Tech Stack:** Python 3.11, Dash 3.0.3, Dash-Leaflet 1.0.15, pytest 9.0.3, syrupy 5.1.0.

**Repo:** `~/Desktop/tallyaero_overlay_archives/` on `main` at commit `7d1dce4` (Phase 0 merged + pushed). All work lands on a new feature branch `phase-1-decompose`.

**Acceptance (at end of plan):**
- `app.py` ≤ 200 lines
- `make test` shows **32+ passed** after every commit (no regression)
- `make run` boots clean HTTP 200 after every commit
- Every existing component id preserved verbatim (`grep -c 'id="..."' layouts/ callbacks/` totals match pre-decomp `grep -c` on app.py)
- Branch `phase-1-decompose` is N commits ahead of `main`, merged with `--no-ff` and pushed when user gives go

---

## Task sequencing rationale

Order chosen so risk grows monotonically — easy/pure-function extractions first to build confidence and let later sub-phases land on a clean foundation:

1. **Task 0** — Branch setup (no commit)
2. **Sub-phase 1a (Tasks 1–2)** — `callbacks/` + `layouts/` package skeletons. No behavioural change; just infrastructure.
3. **Sub-phase 1b (Tasks 3–13)** — Extract the 11 maneuver layout functions into `layouts/maneuvers/<name>.py`. Pure functions, no callback wiring. One commit per maneuver. ~3k lines moved.
4. **Sub-phase 1h (Tasks 14–15)** — Extract `desktop_layout()` + `mobile_layout()` into `layouts/desktop.py` + `layouts/mobile.py`. Top-level shells that import the per-maneuver modules from 1b.
5. **Sub-phase 1g (Task 16)** — Extract `edit_aircraft_page.py` into `layouts/edit_aircraft.py` + `callbacks/edit_aircraft.py`. Already a separate file; this is a tidy-up rename + registration migration.
6. **Sub-phase 1d (Task 17)** — Extract environment callbacks (OAT / altimeter / wind / airport-select / elevation lookup) into `callbacks/environment.py`. Self-contained domain.
7. **Sub-phase 1e (Task 18)** — Extract aircraft-config callbacks (engine, category, flap, gear, weight, fuel, power, CG) into `callbacks/aircraft.py`.
8. **Sub-phase 1f (Task 19)** — Extract map-interaction callbacks (click handler, point stores, marker rendering, helpers `get_elevation` + `create_airplane_marker`) into `callbacks/map.py`.
9. **Sub-phase 1c (Tasks 20–28)** — Extract the 9 `draw_<maneuver>` callbacks + 2 preview callbacks into `callbacks/maneuvers/<name>.py`. The biggest and riskiest chunk — 200–500 lines per callback, each consumes many State() inputs.
10. **Sub-phase 1i (Task 29)** — Final `app.py` slim-down to ≤200 lines.
11. **Tasks 30–31** — Acceptance run-through + merge to `main`.

**Standard verification loop after every commit** — described once here, referenced as "Run the standard verification loop" in every task below:

```bash
cd ~/Desktop/tallyaero_overlay_archives
make test 2>&1 | tail -3       # expect "32 passed" (or higher if more tests added)
make kill-server > /dev/null 2>&1
make run > /tmp/ot_boot.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/  # expect HTTP 200
make kill-server > /dev/null 2>&1
git status --short              # expect empty
```

---

## Task 0: Branch setup

**Files:** none modified; git only.

**Step 1: Verify clean working tree on main**

Run: `cd ~/Desktop/tallyaero_overlay_archives && git status && git log --oneline -2`
Expected: `nothing to commit`; HEAD at `7d1dce4` (Phase 0 merge).

**Step 2: Create feature branch**

Run:
```bash
cd ~/Desktop/tallyaero_overlay_archives
git checkout -b phase-1-decompose
```
Expected: `Switched to a new branch 'phase-1-decompose'`.

**Step 3: Verify baseline tests + boot still pass**

Run the standard verification loop. Expected: 32 passed, HTTP 200.

No commit yet.

---

## Sub-phase 1a — `callbacks/` + `layouts/` package skeletons

### Task 1: `callbacks/__init__.py` aggregator + topical-module stubs

**Files:**
- Create: `callbacks/maneuvers/__init__.py` (empty)
- Modify: `callbacks/__init__.py` (currently empty file from pre-decomp)

**Step 1: Read the EM Diagram pattern for reference**

Read `~/Desktop/tallyaero_archives/aeroedge_em_diagram/callbacks/__init__.py` — the aggregator structure to mirror.

**Step 2: Write `callbacks/__init__.py`**

```python
"""
TallyAero Maneuver Overlay — callback registration.

Each topical module exports a `register(app)` function. The top-level
`register_all(app)` invokes them in deterministic order. Dash callback
firing order is determined by inputs, not by registration order — the
order here is for readability only.

Module map (filled in as Phase 1 progresses):

    environment     → OAT, altimeter, wind, airport-select, elevation lookup (Phase 1d)
    aircraft        → aircraft cascade, engine/category/flap/gear, weight, fuel, power, CG (Phase 1e)
    map             → click handlers, point stores, marker rendering (Phase 1f)
    edit_aircraft   → /edit-aircraft modal + CRUD (Phase 1g)
    navigation      → URL routing, screen-width, mobile settings toggle (Phase 1d)
    maneuvers       → per-maneuver draw + simulate callbacks (Phase 1c)

Until each module exists, its `register(app)` import here is commented out.
"""

from __future__ import annotations


def register_all(app):
    """Wire every callback module to the given Dash app.

    Sub-phases will uncomment the imports + calls below as each module lands.
    """
    # from . import navigation       # Phase 1d
    # from . import environment      # Phase 1d
    # from . import aircraft         # Phase 1e
    # from . import map as map_      # Phase 1f
    # from . import edit_aircraft    # Phase 1g
    # from .maneuvers import register_maneuvers   # Phase 1c

    # navigation.register(app)
    # environment.register(app)
    # aircraft.register(app)
    # map_.register(app)
    # edit_aircraft.register(app)
    # register_maneuvers(app)

    # Phase 1a: skeleton only. app.py still owns all callbacks until
    # later sub-phases relocate them. This function is a no-op for now.
    pass
```

**Step 3: Create `callbacks/maneuvers/__init__.py`**

```python
"""Per-maneuver draw/simulate callbacks. Each module exports `register(app)`.

The package-level `register_maneuvers(app)` wires every maneuver in
deterministic order. Phase 1c populates this.
"""

from __future__ import annotations


def register_maneuvers(app):
    """Register every maneuver callback. Populated as Phase 1c lands."""
    # from . import impossible_turn
    # impossible_turn.register(app)
    # ... etc
    pass
```

**Step 4: Run the standard verification loop**

Expected: 32 passed, HTTP 200, working tree shows the 2 new files staged.

**Step 5: Commit**

```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com \
  add callbacks/__init__.py callbacks/maneuvers/__init__.py
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "1a: scaffold callbacks/ package with register_all aggregator

Mirrors the EM Diagram archive's pattern. register_all() is currently
a no-op — app.py still owns every callback. Later sub-phases (1c-1g)
relocate callbacks into per-domain modules and uncomment the wiring
inside register_all()."
```

### Task 2: `layouts/__init__.py` aggregator + `layouts/maneuvers/__init__.py`

**Files:**
- Create: `layouts/maneuvers/__init__.py`
- Modify: `layouts/__init__.py`

**Step 1: Write `layouts/__init__.py`**

```python
"""
TallyAero Maneuver Overlay — layouts package.

Builds the desktop + mobile layout trees. The per-maneuver parameter
forms live under `layouts/maneuvers/` and get composed into the maneuver
picker.

Pure functions; no callbacks, no Dash app reference. The `register_all`
inside callbacks/ is what wires interactivity.
"""

from __future__ import annotations

# Phase 1h will populate these imports + re-exports.
# from .desktop import desktop_layout
# from .mobile import mobile_layout

__all__ = [
    # "desktop_layout",
    # "mobile_layout",
]
```

**Step 2: Write `layouts/maneuvers/__init__.py`**

```python
"""Per-maneuver parameter forms. Each module exports a `<name>_layout()`
function returning a list of Dash components used inside the maneuver
picker accordion.

Phase 1b populates this package one maneuver at a time.
"""

from __future__ import annotations

# Filled in as Phase 1b lands. The re-export here lets app.py write a
# single `from layouts.maneuvers import *` once Task 13 ships.
__all__: list[str] = []
```

**Step 3: Run the standard verification loop**

Expected: 32 passed, HTTP 200.

**Step 4: Commit**

```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com \
  add layouts/__init__.py layouts/maneuvers/__init__.py
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "1a: scaffold layouts/ + layouts/maneuvers/ packages

Empty aggregator + maneuvers subpackage. Phase 1b moves each maneuver's
*_layout() function into its own file under layouts/maneuvers/."
```

---

## Sub-phase 1b — Extract maneuver layouts (11 commits, one per maneuver)

**Pattern (applies to Tasks 3–13).** For each maneuver:

1. Identify the layout function's line range in `app.py` (use `grep -n "^def <name>_layout"`).
2. Create `layouts/maneuvers/<name>.py` and paste the function body verbatim.
3. Add any imports the function needs (read the function body to identify them).
4. Remove the function from `app.py` and replace with `from layouts.maneuvers.<name> import <name>_layout`.
5. Update `layouts/maneuvers/__init__.py` to re-export the new symbol.
6. Run the standard verification loop.
7. Commit.

**Critical:** maneuver layouts call helpers like `_reset_buttons_row()` (line 900 of app.py) and `legal_banner_block()` (line 118). These remain in `app.py` for now; the new files import them via `from app import _reset_buttons_row` (acceptable temporary coupling during the decomp). Sub-phase 1h moves those helpers out.

### Task 3: Extract `impossible_turn_layout` → `layouts/maneuvers/impossible_turn.py`

**Files:**
- Create: `layouts/maneuvers/impossible_turn.py`
- Modify: `app.py` (remove `impossible_turn_layout()` at lines 909–1082; add a one-line import)
- Modify: `layouts/maneuvers/__init__.py` (add re-export)

**Step 1: Identify the function range**

Run: `grep -n "^def impossible_turn_layout\|^def poweroff180_layout" app.py`
Expected: shows lines 909 and 1083 — so `impossible_turn_layout` spans lines 909–1082.

**Step 2: Read those lines**

Read `app.py:909-1082` to capture the function body.

**Step 3: Inspect imports needed**

Look for uses of: `dcc`, `html`, `dbc`, `dl` (dash_leaflet), `_reset_buttons_row`, `legal_banner_block`, any other helpers. These determine the imports of the new file.

**Step 4: Write `layouts/maneuvers/impossible_turn.py`**

```python
"""Impossible Turn parameter form.

Engine failure after takeoff scenario. Pilot picks reaction delay, turn
direction, and bank angle; the simulation computes whether the aircraft
can make it back to the runway.

Pure function; no callbacks here. The matching draw callback lives at
callbacks/maneuvers/impossible_turn.py (Phase 1c).
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc
import dash_leaflet as dl

# Temporary coupling — `_reset_buttons_row` still lives in app.py until
# Phase 1h moves shared layout helpers out. Phase 1i will tidy this.
from app import _reset_buttons_row


def impossible_turn_layout():
    # Paste the body from app.py:909-1082 verbatim, indented to match.
    ...
```

**Step 5: Remove from `app.py`**

Use Edit to replace the `def impossible_turn_layout(): ...` block (lines 909-1082) with a single-line import near the top of `app.py`:

```python
from layouts.maneuvers.impossible_turn import impossible_turn_layout
```

Place this import in the existing `# === Load aircraft data ===`-style import section near the top.

**Step 6: Update `layouts/maneuvers/__init__.py`**

```python
from .impossible_turn import impossible_turn_layout

__all__: list[str] = ["impossible_turn_layout"]
```

**Step 7: Run the standard verification loop**

Expected: 32 passed, HTTP 200. The Impossible Turn maneuver picker option still works exactly the same in the browser (we don't manually test this; the boot smoke covers the import chain).

**Step 8: Commit**

```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add -A
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "1b: extract impossible_turn_layout to layouts/maneuvers/impossible_turn.py

~170 lines of layout code moved out of app.py. Function body unchanged;
imports added for dcc/html/dbc/dl + the temporary _reset_buttons_row
coupling to app.py (cleaned up in Phase 1h)."
```

### Tasks 4–13: Repeat for the other 10 maneuvers

Same pattern as Task 3 — one task per maneuver, one commit each. The line ranges:

| Task | Function | Lines | Target file |
|------|----------|-------|-------------|
| 4 | `poweroff180_layout` | 1083–1230 | `layouts/maneuvers/poweroff180.py` |
| 5 | `engineout_layout` | 1231–1413 | `layouts/maneuvers/engineout.py` |
| 6 | `steep_turn_layout` | 1414–1515 | `layouts/maneuvers/steep_turn.py` |
| 7 | `chandelle_layout` | 1516–1608 | `layouts/maneuvers/chandelle.py` |
| 8 | `lazy8_layout` | 1609–1701 | `layouts/maneuvers/lazy_eight.py` |
| 9 | `steep_spiral_layout` | 1702–1803 | `layouts/maneuvers/steep_spiral.py` |
| 10 | `s_turn_layout` | 1804–1931 | `layouts/maneuvers/s_turn.py` |
| 11 | `turns_point_layout` | 1932–2047 | `layouts/maneuvers/turns_around_point.py` |
| 12 | `rect_course_layout` | 2048–2168 | `layouts/maneuvers/rectangular_course.py` |
| 13 | `pylons_layout` | 2169–2274 | `layouts/maneuvers/eights_on_pylons.py` |

For each: same 8 steps as Task 3. Same verification. Same commit-message shape `1b: extract <name>_layout to layouts/maneuvers/<name>.py`.

**Note on filename normalisation:** the codebase uses some inconsistent names (`lazy8_layout` → file `lazy_eight.py`; `turns_point_layout` → file `turns_around_point.py`; `rect_course_layout` → file `rectangular_course.py`; `pylons_layout` → file `eights_on_pylons.py`). The new file names match the `simulation/` module names (which are the authoritative spelling). The exported function names keep their existing spelling so callers don't change.

**Acceptance after Task 13:** `app.py` is ~3,000 lines smaller. `layouts/maneuvers/__init__.py` exports 11 layout functions. Every maneuver still renders the same parameter form in the browser. 32 tests still pass.

---

## Sub-phase 1h — Extract `desktop_layout` + `mobile_layout`

### Task 14: Extract `desktop_layout` → `layouts/desktop.py`

**Files:**
- Create: `layouts/desktop.py`
- Modify: `app.py` (remove `desktop_layout()` at lines 258–605; add import)
- Modify: `app.py` (also move `legal_banner_block()` and `_reset_buttons_row()` since `desktop_layout` is one of their main callers and Phase 1b made the temporary coupling visible)
- Modify: `layouts/__init__.py` (add re-export)

**Step 1: Read the function ranges**

`legal_banner_block` lives at line 118; `_reset_buttons_row` at line 900; `desktop_layout` at line 258. Read all three.

**Step 2: Write `layouts/desktop.py`**

Standard structure:

```python
"""Desktop layout (≥ 768px viewport).

Composes the per-maneuver parameter forms from layouts/maneuvers/ into
the sidebar accordion. Pure function — no callbacks.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from layouts.maneuvers import (
    impossible_turn_layout,
    poweroff180_layout,
    engineout_layout,
    steep_turn_layout,
    chandelle_layout,
    lazy8_layout,
    steep_spiral_layout,
    s_turn_layout,
    turns_point_layout,
    rect_course_layout,
    pylons_layout,
)


def legal_banner_block():
    # Paste body from app.py:118-... verbatim.
    ...


def _reset_buttons_row():
    # Paste body from app.py:900-908 verbatim.
    ...


def desktop_layout():
    # Paste body from app.py:258-605 verbatim. Update internal calls so
    # that any `impossible_turn_layout()` / `poweroff180_layout()` / etc.
    # refer to the imports above (they should already; we moved the
    # functions, not renamed them).
    ...
```

**Step 3: Remove the three functions from `app.py`**

Replace the three function defs in `app.py` with imports from the new file:

```python
from layouts.desktop import desktop_layout, legal_banner_block, _reset_buttons_row
```

**Step 4: Update the temporary couplings in layouts/maneuvers/*.py**

Every Phase-1b file currently has `from app import _reset_buttons_row`. Replace with `from layouts.desktop import _reset_buttons_row`. (Use `grep -rln "from app import _reset_buttons_row" layouts/` to find them all; run a `sed -i ''` replacement.)

**Step 5: Update `layouts/__init__.py`**

```python
from .desktop import desktop_layout

__all__ = ["desktop_layout"]
```

**Step 6: Run the standard verification loop**

Expected: 32 passed, HTTP 200. The desktop UI still renders identically.

**Step 7: Commit**

```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add -A
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "1h: extract desktop_layout + legal_banner_block + _reset_buttons_row

~350 lines moved out of app.py into layouts/desktop.py. Also fixes the
temporary 'from app import _reset_buttons_row' coupling that Phase 1b
introduced in each layouts/maneuvers/<m>.py file — they now import from
layouts/desktop.py."
```

### Task 15: Extract `mobile_layout` → `layouts/mobile.py`

**Files:**
- Create: `layouts/mobile.py`
- Modify: `app.py` (remove `mobile_layout()` at lines 606–865; add import)
- Modify: `layouts/__init__.py` (add re-export)

Same pattern as Task 14. Mobile layout shares the maneuver-layouts imports with desktop. Commit message `1h: extract mobile_layout to layouts/mobile.py`.

After this task: `app.py` has lost ~1,000 lines from sub-phase 1h alone. Layouts package is fully populated.

---

## Sub-phase 1g — Extract `edit_aircraft_page.py` modal/route

### Task 16: Move `edit_aircraft_page.py` → `layouts/edit_aircraft.py` + `callbacks/edit_aircraft.py`

**Files:**
- Create: `layouts/edit_aircraft.py` (the layout-tree part)
- Create: `callbacks/edit_aircraft.py` (the callback registrations)
- Delete: `edit_aircraft_page.py` (root-level)
- Modify: `app.py` (update the import)
- Modify: `callbacks/__init__.py` (uncomment the `edit_aircraft` import + call)

**Step 1: Read the current `edit_aircraft_page.py`**

That file is ~300 lines. Identify which sections are layout (returns Dash components) vs which are `@app.callback` registrations.

**Step 2: Split into the two new files**

`layouts/edit_aircraft.py` exports `edit_aircraft_layout()` and any helper components.
`callbacks/edit_aircraft.py` exports `register(app)` that wraps every `@app.callback` from the original file as registrations under that function (per the EM Diagram pattern).

**Step 3: Update `callbacks/__init__.py`**

Uncomment:

```python
from . import edit_aircraft
edit_aircraft.register(app)
```

**Step 4: Update `app.py`'s display_page routing**

Find the callback that switches between desktop_layout / mobile_layout / edit_aircraft. Update its import to use `layouts.edit_aircraft` instead of `edit_aircraft_page`.

**Step 5: Delete `edit_aircraft_page.py`**

`git rm edit_aircraft_page.py`

**Step 6: Run the standard verification loop**

Expected: 32 passed, HTTP 200. The Edit Aircraft modal/route still opens.

**Step 7: Commit**

```bash
git commit -m "1g: split edit_aircraft_page.py into layouts/ + callbacks/

Layout tree moves to layouts/edit_aircraft.py; the @app.callback
registrations move into callbacks/edit_aircraft.py's register(app).
register_all() now wires it."
```

---

## Sub-phase 1d — Environment callbacks

### Task 17: Extract environment callbacks → `callbacks/environment.py`

**Scope.** The callbacks driven by environment inputs. From the line-number inventory:

- `update_total_weight_display` (line 2275) — total weight from occupants + fuel
- `search_airport_database` (line 2369)
- `handle_airport_result_click` (line 2332)
- `restore_airport_display_on_load` (line 2411)
- `recenter_to_airport` (line 2452)

**Files:**
- Create: `callbacks/environment.py`
- Modify: `app.py` (remove the 5 `@app.callback` blocks; remove the inner def bodies)
- Modify: `callbacks/__init__.py` (uncomment environment import + call)

**Step 1: Write `callbacks/environment.py`**

```python
"""Environment input callbacks — OAT, altimeter, wind, airport selection,
elevation lookup, total weight display.

Every callback here owns inputs the pilot adjusts to set the environmental
context for a maneuver. Map clicks and aircraft-config cascades live in
their own modules (callbacks/map.py, callbacks/aircraft.py).
"""

from __future__ import annotations

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate


def register(app):
    """Install every environment callback against the given Dash app."""

    @app.callback(
        # Paste decorator from app.py:2272-2274 verbatim
        ...
    )
    def update_total_weight_display(...):
        # Paste body from app.py:2275-... verbatim
        ...

    # ... 4 more callbacks, all wrapped inside register() exactly the same way
```

**Step 2: Remove the callbacks from `app.py`**

Use Edit to remove each `@app.callback`+def block. Be precise — only the 5 callbacks listed in the scope, nothing else.

**Step 3: Update `callbacks/__init__.py`**

```python
from . import environment
environment.register(app)
```

(Move the comment lines to active lines.)

**Step 4: Run the standard verification loop**

Expected: 32 passed, HTTP 200.

**Step 5: Commit**

```bash
git commit -m "1d: extract 5 environment callbacks to callbacks/environment.py

Total weight display, airport search/click/restore/recenter. All
behaviour preserved; component ids unchanged. register_all() now
wires environment.register(app)."
```

---

## Sub-phase 1e — Aircraft-config callbacks

### Task 18: Extract aircraft-config callbacks → `callbacks/aircraft.py`

**Scope.**

- `update_aircraft_fields` (line 2534) — main cascade: engine, occupants, fuel, CG slider on aircraft pick
- `update_climb_speed_from_vy` (line 2583)
- `update_runway_options` (line 2605)
- (the second runway callback at line 2657 — read it; if it's airport-runway-list it goes here, if it's draw-related it goes to maneuvers)
- `update_engineout_runway_options` (line 2729)
- `render_maneuver_layout` (line 2470) — actually this is more of a UI routing callback; include here since it depends on aircraft+airport state

**Files:**
- Create: `callbacks/aircraft.py`
- Modify: `app.py` (remove the callbacks)
- Modify: `callbacks/__init__.py` (uncomment aircraft import + call)

Same pattern as Task 17. Commit message: `1e: extract aircraft cascade + runway-options callbacks to callbacks/aircraft.py`.

---

## Sub-phase 1f — Map-interaction callbacks

### Task 19: Extract map-interaction callbacks → `callbacks/map.py` + helpers

**Scope.** These all touch the Leaflet map directly:

- `set_active_click_target` (line 2814)
- `show_click_prompt` (line 2833)
- `write_point_to_scoped_store` (line 2867) — the central map-click handler, ~170 lines, heaviest callback in this sub-phase
- `summarize_points` (line 3028)
- `undo_last_click` (line 3058)
- `autofill_engineout_touchdown_elev` (line 3101)
- `display_click_location` (line 3140)
- Helper functions: `get_elevation` (line 3113), `calculate_runway_geometry` (line 3149), `create_airplane_marker` (line 5962). These should move into `callbacks/map.py` since they're map-coordinate utilities.

**Files:**
- Create: `callbacks/map.py`
- Modify: `app.py` (remove ~600 lines)
- Modify: `callbacks/__init__.py` (uncomment map import + call; alias `map_` to avoid shadowing builtin)
- Modify: any layouts/maneuvers/*.py that calls `create_airplane_marker` to import from the new location

**Step 1–6:** standard pattern.

**Step 7: Commit**

```bash
git commit -m "1f: extract map-interaction callbacks + helpers to callbacks/map.py

7 callbacks + 3 helper functions (get_elevation, calculate_runway_geometry,
create_airplane_marker). ~700 lines moved. register_all() now wires
map.register(app)."
```

---

## Sub-phase 1c — Per-maneuver draw callbacks (9 commits)

**Pattern.** Each maneuver has a `draw_<name>(...)` callback that's 200–500 lines long. Each consumes 10+ State() inputs and writes to the map layer + bounds + info panel. They're independent of each other — extracting one doesn't affect the others.

For each maneuver:

1. Find the `@app.callback`+def block in `app.py`.
2. Create `callbacks/maneuvers/<name>.py` with the standard `register(app)` wrapper.
3. Move the `@app.callback` decorator + def into `register()`.
4. Add the file's name to `callbacks/maneuvers/__init__.py`'s `register_maneuvers()`.
5. Remove the original block from `app.py`.
6. Run the standard verification loop.
7. Commit.

### Tasks 20–28: Per-maneuver draw callback extractions

| Task | Callback | Line | Target file |
|------|----------|------|-------------|
| 20 | `draw_impossible_turn` | 3236 | `callbacks/maneuvers/impossible_turn.py` |
| 21 | `draw_engineout` | 4075 | `callbacks/maneuvers/engineout.py` |
| 22 | `draw_steep_turn` | 4483 | `callbacks/maneuvers/steep_turn.py` |
| 23 | `draw_chandelle` | 4698 | `callbacks/maneuvers/chandelle.py` |
| 24 | `draw_lazy_eight` | 4938 | `callbacks/maneuvers/lazy_eight.py` |
| 25 | `draw_steep_spiral` | 5186 | `callbacks/maneuvers/steep_spiral.py` |
| 26 | `calculate_sturn_bearing_and_preview` + `draw_s_turn` | 5413 + 5705 | `callbacks/maneuvers/s_turn.py` (both belong together) |
| 27 | `calculate_rectcourse_edge_and_preview` + `update_rectcourse_edge_visible_info` + `draw_rect_course` | 5516 + 5654 + (find via grep) | `callbacks/maneuvers/rectangular_course.py` |
| 28 | (anything for pylons + turns_point + po180 — grep for `draw_pylons`, `draw_turns_point`, `draw_poweroff180`) | TBD | three files: `callbacks/maneuvers/eights_on_pylons.py`, `callbacks/maneuvers/turns_around_point.py`, `callbacks/maneuvers/poweroff180.py` |

**Per-task structure (using Task 20 as example):**

**Files:**
- Create: `callbacks/maneuvers/impossible_turn.py`
- Modify: `app.py` (remove `@app.callback`+def at lines 3200–3741)
- Modify: `callbacks/maneuvers/__init__.py` (add the import + call in `register_maneuvers`)

**Step 1: Read the callback block**

Read `app.py:3200-3741` to capture the decorator + def.

**Step 2: Write `callbacks/maneuvers/impossible_turn.py`**

```python
"""draw_impossible_turn callback.

Engine-failure-after-takeoff simulation. Inputs: aircraft + environment +
runway geometry + reaction parameters. Outputs: map layer with path, bounds,
info panel.
"""

from __future__ import annotations

from dash import Input, Output, State
from dash.exceptions import PreventUpdate
import dash_leaflet as dl

from simulation.impossible_turn import simulate_impossible_turn
# ... any other imports the body needs


def register(app):
    @app.callback(
        # Paste decorator verbatim
        ...
    )
    def draw_impossible_turn(
        # Paste signature verbatim
        ...
    ):
        # Paste body verbatim
        ...
```

**Step 3: Remove from `app.py`**

Use Edit to delete lines 3200–3741.

**Step 4: Wire into `callbacks/maneuvers/__init__.py`**

```python
def register_maneuvers(app):
    from . import impossible_turn
    impossible_turn.register(app)
    # ... siblings registered by later tasks
```

**Step 5: Update `callbacks/__init__.py`**

Uncomment the `register_maneuvers` import + call (do this once at Task 20, the first one to land).

**Step 6: Run the standard verification loop**

Expected: 32 passed, HTTP 200.

**Step 7: Commit**

```bash
git commit -m "1c: extract draw_impossible_turn to callbacks/maneuvers/impossible_turn.py

~540 lines moved. The Impossible Turn 'Draw' button still triggers
the simulation and renders the path. component ids preserved."
```

Repeat the same pattern for Tasks 21–28.

**Risk note for Task 27 (rect course)** — has 3 related callbacks; group them in one file but in three separate `@app.callback` blocks inside one `register(app)` function.

**Risk note for Task 28** — three small maneuvers (po180, turns_point, pylons) may not have dedicated `draw_*` callbacks; their drawing might happen inside `write_point_to_scoped_store` (the central map-click handler). If so, the file is created empty-ish or just exports a `register(app)` that's a no-op (consistent with the future expansion pattern).

---

## Sub-phase 1i — Final `app.py` slim-down

### Task 29: Reduce `app.py` to ≤200 lines

**Files:**
- Modify: `app.py`

**Step 1: Inventory what's left**

After Tasks 1–28, `app.py` should contain only:
- Module imports
- `load_aircraft_data` + `load_airport_data` (and the `init_data` function from Phase 0f)
- The Dash app instantiation: `app = dash.Dash(...)`
- `app.index_string` block
- `app.layout = ...` (likely a thin wrapper around `display_page`)
- A `display_page` callback (URL routing)
- `if __name__ == "__main__": app.run(...)`

Run: `wc -l app.py` — expected ~250–400 lines at this point. Goal: ≤200.

**Step 2: Move `load_aircraft_data` + `load_airport_data` + `init_data` to `core/data_loader.py`**

Create `core/data_loader.py`:

```python
"""Aircraft + airport data loaders. Pure I/O, no Dash dependency.

Auto-init at module-import time can be disabled by setting
TALLYAERO_NO_AUTO_INIT in the environment — useful for tests that load
curated subsets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.log import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def load_aircraft_data(folder: str = "aircraft_data") -> dict:
    # Paste from app.py
    ...


def load_airport_data() -> list:
    # Paste from app.py
    ...
```

Update `app.py` to import these from the new location.

**Step 3: Move `display_page` routing callback to `callbacks/navigation.py`**

Create `callbacks/navigation.py`:

```python
"""URL routing + viewport-width tracking + mobile settings toggle."""

from __future__ import annotations

from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate


def register(app):

    @app.callback(
        # Paste decorator from app.py
    )
    def display_page(pathname, screen_width):
        # body
        ...

    @app.callback(...)
    def toggle_mobile_settings(n_clicks, is_open):
        ...
```

Uncomment `navigation` in `callbacks/__init__.py`.

**Step 4: Move `init_data` callsite + the auto-init guard to `app.py` (top level)**

The auto-init `if not os.environ.get("TALLYAERO_NO_AUTO_INIT"): init_data()` line stays at the bottom of `app.py` (or moves into `core/data_loader.py` — pick the cleaner spot).

**Step 5: Final `app.py` should look like:**

```python
"""TallyAero Maneuver Overlay Tool — main entry point.

This module is the thin entry. All physics in `simulation/`, all
callbacks in `callbacks/`, all layouts in `layouts/`. See
`OVERLAY_TOOL_EXECUTION_PLAN.md` for the architectural breakdown.

Run with:
    venv/bin/python app.py [port]    (default port 8050)
"""

import os
import sys

import dash
from dash import dcc, html
import dash_bootstrap_components as dbc

from core.data_loader import init_data
from core.log import get_logger
from callbacks import register_all
from layouts import desktop_layout  # for type-checker only; routing imports it lazily

log = get_logger(__name__)


# ============================================================
# Dash app + Flask server
# ============================================================
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    prevent_initial_callbacks="initial_duplicate",
)
server = app.server
app.title = "Maneuver Overlay Tool | TallyAero"


# ============================================================
# HTML index template
# ============================================================
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


# ============================================================
# Page layout (router shell)
# ============================================================
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    dcc.Store(id="screen-width", data=1400),
    html.Div(id="page-content"),
])


# ============================================================
# Wire callbacks
# ============================================================
register_all(app)


# ============================================================
# Auto-init data (gated by env)
# ============================================================
if not os.environ.get("TALLYAERO_NO_AUTO_INIT"):
    init_data()


# ============================================================
# Run
# ============================================================
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8050
    log.info("Starting Dash dev server on port %s", port)
    app.run(debug=True, host="0.0.0.0", port=port)
```

This target is ~95 lines including blank lines + comments. Well under 200.

**Step 6: Run the standard verification loop**

Expected: 32 passed, HTTP 200. UI behaviour unchanged.

**Step 7: Commit**

```bash
git commit -m "1i: slim app.py to <= 200 lines

Final cut. app.py is now just:
  - imports
  - app = Dash(...)
  - app.index_string
  - app.layout (router shell)
  - register_all(app)
  - auto-init guard
  - if __name__ == '__main__': app.run(...)

All other code lives in callbacks/, layouts/, core/data_loader.py."
```

---

## Final acceptance + merge

### Task 30: Phase 1 acceptance run-through

**Step 1: Hard verification**

```bash
cd ~/Desktop/tallyaero_overlay_archives
wc -l app.py                       # expect ≤200
make test 2>&1 | tail -3           # expect 32+ passed
make kill-server > /dev/null 2>&1
make run > /tmp/ot_post_1.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/
make kill-server > /dev/null 2>&1
```

All three checks must pass. If anything fails, find the cause before merging.

**Step 2: Component-id integrity check**

```bash
# Count component ids in the new tree vs what app.py used to have.
# (We don't have a pre-decomp snapshot, but the test suite + boot-smoke
#  catch most missing-id bugs. Add a manual UI smoke if anything looks off.)
grep -rhE 'id=["\047][a-zA-Z0-9_-]+["\047]' callbacks/ layouts/ app.py \
  | grep -oE 'id=["\047][a-zA-Z0-9_-]+["\047]' \
  | sort -u | wc -l
```

Expected: roughly the same as a baseline `git stash; grep on main; git stash pop` — large drift indicates a missing/renamed id.

**Step 3: Append Phase 1 log entry to `OVERLAY_TOOL_EXECUTION_PLAN.md`**

Insert under the dated log section:

```markdown
- 2026-MM-DD — **Phase 1 shipped.** Decomposition complete. app.py reduced from 7,646 → ≤200 lines. Branch `phase-1-decompose` is N commits ahead of main, all tests + boot HTTP 200 verified after every commit.
  - **1a** Skeleton — `callbacks/` + `layouts/` aggregator packages
  - **1b** 11 maneuver layouts → `layouts/maneuvers/`
  - **1h** `desktop_layout` + `mobile_layout` + `legal_banner_block` + `_reset_buttons_row` → `layouts/desktop.py` + `layouts/mobile.py`
  - **1g** `edit_aircraft_page.py` split into `layouts/edit_aircraft.py` + `callbacks/edit_aircraft.py`
  - **1d** 5 environment callbacks → `callbacks/environment.py`
  - **1e** Aircraft cascade + runway options → `callbacks/aircraft.py`
  - **1f** 7 map-interaction callbacks + 3 helper functions → `callbacks/map.py`
  - **1c** 9 maneuver draw callbacks → `callbacks/maneuvers/`
  - **1i** Final slim-down to thin entry — `core/data_loader.py` (init_data + loaders) + `callbacks/navigation.py` (display_page + toggle_mobile_settings) extracted last
```

Flip the Phase 1 row in the index table from `pending` to `**complete**`.

**Step 4: Commit the log update**

```bash
git commit -m "1i: log Phase 1 completion in execution plan"
```

### Task 31: Merge to main + push

**Step 1: Switch to main**

```bash
git checkout main
git log --oneline -3
```

**Step 2: Merge `phase-1-decompose` with `--no-ff`**

```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com \
  merge --no-ff phase-1-decompose -m "Phase 1: decomposition complete

N commits moved 7,400+ lines out of app.py into:
  layouts/desktop.py + layouts/mobile.py + layouts/maneuvers/<11 files>
  layouts/edit_aircraft.py
  callbacks/environment.py + callbacks/aircraft.py + callbacks/map.py
  callbacks/edit_aircraft.py + callbacks/navigation.py
  callbacks/maneuvers/<9 files>
  core/data_loader.py

app.py is now the thin entry: ~95 lines. Every component id preserved;
all 32+ tests pass; HTTP 200 boot. No behaviour change.

See OVERLAY_TOOL_EXECUTION_PLAN.md dated log for per-sub-phase detail."
```

**Step 3: Push to origin/main**

```bash
git push origin main
```

(Requires user OK if running interactively. The plan assumes pre-approval at the Phase 1 kickoff.)

**Step 4: Delete the local feature branch**

```bash
git branch -d phase-1-decompose
```

**Step 5: Sanity-test on merged main**

```bash
make test 2>&1 | tail -3       # 32+ passed
make run                       # HTTP 200
```

---

## What's next after Phase 1

Per `OVERLAY_TOOL_EXECUTION_PLAN.md`: **Phase 2 — Aircraft data hardening (port from EM Diagram).** Mostly a copy job since the EM Diagram archive already shipped its equivalent — read `~/Desktop/tallyaero_archives/aeroedge_em_diagram/data/scrapers/` and `~/Desktop/tallyaero_archives/aeroedge_em_diagram/core/schema.py` for the source-of-truth implementations. Hand off to `superpowers:writing-plans` again to expand Phase 2 into its own implementation plan.

---

## Plan complete and saved to `docs/plans/2026-05-14-phase-1-decompose.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for hands-on review of each commit. ~31 tasks ⇒ likely 2 working sessions.

**2. Parallel Session (separate)** — Open a new session at `~/Desktop/tallyaero_overlay_archives/`, batch execution with checkpoints. Lets Phase 1 run while you do other work elsewhere.

Which one?
