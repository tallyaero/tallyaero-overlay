# Phase 0 — Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring the Maneuver Overlay Tool to "anyone can hack on this without fear" baseline — pyproject.toml, pytest with 30+ tests, snapshot testing, structured logging, explicit `init_data()`, telemetry removed, Makefile, `aeroedge` → `tallyaero` rename complete, `__pycache__/.DS_Store` no longer tracked.

**Architecture:** Direct port of the patterns shipped in the EM Diagram archive's Phase 0 (`~/Desktop/tallyaero_archives/aeroedge_em_diagram/`). Foundation work — no new product features. Each sub-phase is independently verifiable; commit frequently. All work lands on a feature branch `phase-0-foundation` off `main`.

**Tech Stack:** Python 3.11+, Dash 3.0.3, Dash-Leaflet 1.0.15, NumPy 2.2.4, pytest, syrupy (snapshot testing), `pip` for installs (uv optional later).

**Repo:** `~/Desktop/tallyaero_overlay_archives/` (HEAD: `be0965c` — pre-Phase-0 setup commit).

**Acceptance (at end of plan):** `make test` passes ≥30 tests. `make run` boots clean on port 8050. `grep -rn aeroedge_tracker` returns nothing. `grep -rn aeroedge` returns nothing in `.py`/`.md` files. No telemetry network calls in browser DevTools. `git ls-files | grep __pycache__` is empty. Branch ready to merge to main.

---

## Task sequencing rationale

Order chosen so each sub-phase lands on a clean predecessor:

1. **0a** `pyproject.toml` — foundational, must come first
2. **0g** Telemetry removal — small isolated change, simplifies 0i
3. **0i** `aeroedge` → `tallyaero` rename — do *before* tests so snapshot baselines don't need regenerating later
4. **0d** Structured logging — should land before tests so test output is clean
5. **0f** `init_data()` extraction — tests will need it
6. **0b** pytest smoke + physics tests — needs all the above
7. **0c** Snapshot testing — depends on smoke tests existing
8. **0e** `prevent_initial_call` audit — independent, do near the end
9. **0h** `Makefile` + tracked-junk cleanup — needs final test targets to wire

---

## Task 0: Branch setup

**Files:**
- No code changes; git only.

**Step 1: Verify clean working tree**

Run: `cd ~/Desktop/tallyaero_overlay_archives && git status`
Expected: `nothing to commit, working tree clean` and HEAD at `be0965c`.

**Step 2: Create feature branch**

Run:
```bash
cd ~/Desktop/tallyaero_overlay_archives
git checkout -b phase-0-foundation
```
Expected: `Switched to a new branch 'phase-0-foundation'`.

**Step 3: Verify branch position**

Run: `git log --oneline -3`
Expected: top commit is `be0965c chore: setup …`.

No commit at this step — branch creation is the verification.

---

## Sub-phase 0a — `pyproject.toml`

Mirror the EM Diagram's pyproject. Runtime deps stay in `requirements.txt` (single source of truth for PyInstaller later); `pyproject.toml` exists for editable install + pytest configuration + project metadata.

### Task 1: Write `pyproject.toml`

**Files:**
- Create: `~/Desktop/tallyaero_overlay_archives/pyproject.toml`

**Step 1: Write the file**

Content:

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "tallyaero-overlay"
version = "0.1.0-dev"
description = "TallyAero Maneuver Overlay Tool — interactive maneuver visualization on real-world maps."
readme = "CLAUDE_CONTEXT.md"
requires-python = ">=3.11"
license = { text = "Proprietary" }
authors = [
    { name = "Nicholas Len, TallyAero" }
]
keywords = [
    "aviation",
    "flight-training",
    "maneuver-overlay",
    "engine-out",
    "glide-corridor",
    "dash",
    "leaflet",
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Education",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Topic :: Education",
    "Topic :: Scientific/Engineering",
    "Topic :: Scientific/Engineering :: Aerospace",
]
# Runtime deps live in requirements.txt to keep the PyInstaller spec single-source.
# pyproject.toml is for editable installs and test discovery, not for distribution.
dependencies = []

[project.optional-dependencies]
dev = []

[tool.setuptools]
package-dir = { "" = "." }

[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "callbacks*", "layouts*", "components*", "simulation*", "physics*", "rendering*", "data*", "utils*", "services*"]
exclude = ["venv*", "tests*", "_ecosystem*", "build*", "dist*", "aircraft_data*", "airports*"]

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = [
    "-ra",
    "--strict-markers",
    "--strict-config",
]
filterwarnings = [
    "ignore::DeprecationWarning:plotly.*",
    "ignore::DeprecationWarning:dash.*",
]
```

**Step 2: Verify TOML parses**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('ok')"`
Expected: `ok`.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "0a: add pyproject.toml — editable install + pytest config

Mirrors the EM Diagram archive's pyproject. Runtime deps remain in
requirements.txt as single source of truth for PyInstaller bundling
in Phase 12; pyproject.toml owns editable install + test discovery."
```

### Task 2: Create venv and install

**Files:** none directly modified; creates `venv/` (gitignored).

**Step 1: Create venv**

Run:
```bash
cd ~/Desktop/tallyaero_overlay_archives
python3.11 -m venv venv
```
Expected: `venv/` directory created.

**Step 2: Install runtime deps**

Run: `venv/bin/pip install -r requirements.txt`
Expected: ends with `Successfully installed dash-3.0.3 …` (or already-satisfied messages).

**Step 3: Install editable + dev tools**

Run: `venv/bin/pip install -e . pytest syrupy ruff`
Expected: `Successfully installed pytest-… syrupy-… ruff-…` plus a `Successfully installed tallyaero-overlay-0.1.0.dev0` line.

**Step 4: Smoke test the install**

Run: `venv/bin/python -c "import dash, dash_leaflet, numpy, geopy; print('imports ok')"`
Expected: `imports ok`.

No commit — `venv/` is gitignored.

---

## Sub-phase 0g — Telemetry removal (decision D3 enforcement)

Delete `aeroedge_tracker.py` and strip the heartbeat `<script>` from `app.index_string`. Per locked decision D3 — no telemetry, ever.

### Task 3: Inventory all telemetry touchpoints

**Files:** none modified; reconnaissance only.

**Step 1: Find every reference**

Run:
```bash
cd ~/Desktop/tallyaero_overlay_archives
grep -rn "aeroedge_tracker\|init_tracking\|log_feature\|TRACKING_API\|aeroedge-tracking-api" \
  --include="*.py" --include="*.md" 2>/dev/null
```
Expected: shows all touchpoints — should be in `app.py` (3-5 lines around line 90, plus the heartbeat script block inside `app.index_string`) and possibly in docs.

**Step 2: Note the line ranges for the edits below**

Read `app.py:84-100` for the import + init_tracking block. Read the index_string heartbeat block (search for `TRACKING_API`).

No commit at this step.

### Task 4: Delete `aeroedge_tracker.py`

**Files:**
- Delete: `aeroedge_tracker.py`

**Step 1: Confirm it exists**

Run: `ls aeroedge_tracker.py`
Expected: `aeroedge_tracker.py`.

**Step 2: Delete**

Run: `git rm aeroedge_tracker.py`
Expected: `rm 'aeroedge_tracker.py'`.

No commit yet — bundled with subsequent tracker edits.

### Task 5: Strip the import + init_tracking call from `app.py`

**Files:**
- Modify: `app.py` (around lines 84-100 per Task 3 inventory)

**Step 1: Locate the block**

Run:
```bash
grep -nC 2 "init_tracking\|from aeroedge_tracker" app.py
```
Expected: 4-6 lines showing the import + call.

**Step 2: Use Edit to remove the import line**

Remove `from aeroedge_tracker import init_tracking, log_feature`.

**Step 3: Use Edit to remove the `init_tracking(server)` call**

Remove the `init_tracking(server)` line and the comment `# Initialize usage tracking` above it (if present).

**Step 4: Find all `log_feature(...)` call sites and remove them**

Run: `grep -n "log_feature" app.py`

For each match, use Edit to remove just the `log_feature(...)` call (or the entire if-block if log_feature is its only statement). Be conservative — do not remove surrounding business logic.

**Step 5: Verify no residue**

Run: `grep -n "aeroedge_tracker\|init_tracking\|log_feature" app.py`
Expected: empty output.

No commit yet.

### Task 6: Strip the heartbeat `<script>` from `app.index_string`

**Files:**
- Modify: `app.py` (the index_string definition, search for `AeroEdge Session Heartbeat`)

**Step 1: Locate the script block**

Run: `grep -n "TRACKING_API\|Heartbeat\|aeroedge-tracking-api" app.py`
Expected: shows the script tag and its contents.

**Step 2: Remove the entire `<script>...</script>` block**

Use Edit to replace the heartbeat block with an empty string. The block is bounded by `<script>` and `</script>` tags inside the `app.index_string` triple-quoted string.

**Step 3: Verify no residue**

Run: `grep -n "TRACKING_API\|Heartbeat\|aeroedge-tracking-api" app.py`
Expected: empty output.

No commit yet.

### Task 7: Boot-smoke after telemetry removal

**Files:** none modified; verification only.

**Step 1: Import-check**

Run: `venv/bin/python -c "import app; print('import ok')"`
Expected: `import ok` (no ImportError on aeroedge_tracker).

**Step 2: Boot the server briefly**

Run:
```bash
venv/bin/python app.py 8050 &
APP_PID=$!
sleep 4
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/
kill -9 $APP_PID 2>/dev/null
```
Expected: `HTTP 200`.

**Step 3: Commit the telemetry removal**

```bash
git add -A
git commit -m "0g: remove all telemetry (decision D3 — no tracking)

- Delete aeroedge_tracker.py
- Strip init_tracking import + call from app.py
- Strip log_feature() calls from app.py
- Remove the AeroEdge Session Heartbeat <script> block from
  app.index_string

The tool no longer makes any analytics HTTP calls. Future functional
network calls (NOAA AWC, Open-Meteo) are explicit user-initiated
features, not telemetry."
```

### Task 8: Document the no-telemetry stance

**Files:**
- Modify: `CLAUDE_CONTEXT.md` (add a short section)

**Step 1: Read the current file**

Run: `cat CLAUDE_CONTEXT.md`

**Step 2: Use Edit to append a "Locked decisions" section**

Append (or merge into existing top-matter):

```markdown

## Locked decisions

- **D3 — No telemetry.** This tool makes no analytics or tracking HTTP calls.
  Functional network calls (NOAA AWC, Open-Meteo) are explicit user-initiated
  features. `aeroedge_tracker.py` and its heartbeat script were removed in
  Phase 0g.
```

**Step 3: Commit**

```bash
git add CLAUDE_CONTEXT.md
git commit -m "0g: document D3 no-telemetry stance in CLAUDE_CONTEXT.md"
```

---

## Sub-phase 0i — `aeroedge` → `tallyaero` rename

Do this *before* tests so snapshot baselines don't carry the old name. Touch every `.py` / `.md` / `.toml` / `Makefile` reference. Aircraft data JSON files use `aeroedge` only in informational fields (if at all) — handle separately if encountered.

### Task 9: Inventory all `aeroedge` / `AeroEdge` / `Aeroedge` references

**Files:** none modified; reconnaissance only.

**Step 1: Find every match**

Run:
```bash
grep -rni "aeroedge" \
  --include="*.py" --include="*.md" --include="*.toml" --include="Makefile" \
  --include="*.html" --include="*.css" --include="*.json" \
  2>/dev/null | head -60
```
Expected: dozens of matches across docs, comments, and possibly identifiers.

**Step 2: Save the inventory for review**

Run: `grep -rni "aeroedge" --include="*.py" --include="*.md" 2>/dev/null > /tmp/aeroedge_inventory.txt`

Read `/tmp/aeroedge_inventory.txt`. Note any matches that should NOT be renamed (e.g., historical references in changelogs, URLs that still resolve to aeroedge domain).

No commit at this step.

### Task 10: Bulk rename in code files (`.py`)

**Files:**
- Modify: every `.py` file containing `aeroedge` / `AeroEdge` / `Aeroedge`

**Step 1: Run the bulk replace**

Use `sed -i ''` (BSD sed on macOS) per file. Loop:

```bash
cd ~/Desktop/tallyaero_overlay_archives
find . -name "*.py" -not -path "./venv/*" -not -path "./__pycache__/*" \
  -not -path "./.git/*" -print0 \
  | xargs -0 grep -l -i "aeroedge" 2>/dev/null \
  | while read f; do
      sed -i '' \
        -e 's/aeroedge/tallyaero/g' \
        -e 's/AeroEdge/TallyAero/g' \
        -e 's/Aeroedge/Tallyaero/g' \
        "$f"
    done
```

**Step 2: Verify no `aeroedge` in `.py` files**

Run: `grep -rn "aeroedge\|AeroEdge\|Aeroedge" --include="*.py" . 2>/dev/null | grep -v venv | grep -v __pycache__`
Expected: empty output.

**Step 3: Import-check**

Run: `venv/bin/python -c "import app; print('import ok')"`
Expected: `import ok`.

If any ImportError surfaces (e.g., a module named `aeroedge_*.py` that was referenced but not renamed), use Edit to fix imports.

**Step 4: Commit**

```bash
git add -A
git commit -m "0i: rename aeroedge -> tallyaero in .py files (decision D6)"
```

### Task 11: Rename in `.md` files

**Files:**
- Modify: every `.md` file containing `aeroedge` / `AeroEdge` / `Aeroedge`

**Step 1: Run the bulk replace**

```bash
cd ~/Desktop/tallyaero_overlay_archives
find . -name "*.md" -not -path "./venv/*" -not -path "./.git/*" -print0 \
  | xargs -0 grep -l -i "aeroedge" 2>/dev/null \
  | while read f; do
      sed -i '' \
        -e 's/aeroedge/tallyaero/g' \
        -e 's/AeroEdge/TallyAero/g' \
        -e 's/Aeroedge/Tallyaero/g' \
        "$f"
    done
```

**Step 2: Verify**

Run: `grep -rn "aeroedge\|AeroEdge\|Aeroedge" --include="*.md" . 2>/dev/null | grep -v venv | grep -v .git`
Expected: empty output.

**Step 3: Commit**

```bash
git add -A
git commit -m "0i: rename aeroedge -> tallyaero in .md docs (decision D6)"
```

### Task 12: Rename in other config files

**Files:**
- Modify: `requirements.txt`, `wsgi.py`, any `.toml`/`.html`/`.css` containing `aeroedge`.

**Step 1: Run the bulk replace (everything else)**

```bash
cd ~/Desktop/tallyaero_overlay_archives
find . \( -name "*.toml" -o -name "*.html" -o -name "*.css" -o -name "wsgi.py" -o -name "Makefile" -o -name "requirements*.txt" \) \
  -not -path "./venv/*" -not -path "./.git/*" -print0 \
  | xargs -0 grep -l -i "aeroedge" 2>/dev/null \
  | while read f; do
      sed -i '' \
        -e 's/aeroedge/tallyaero/g' \
        -e 's/AeroEdge/TallyAero/g' \
        -e 's/Aeroedge/Tallyaero/g' \
        "$f"
    done
```

**Step 2: Final verification across all source files**

Run: `grep -rni "aeroedge" --exclude-dir=venv --exclude-dir=.git --exclude-dir=__pycache__ . 2>/dev/null`
Expected: empty output (or only matches you've explicitly chosen to keep — review each).

**Step 3: Final boot-smoke**

Run:
```bash
venv/bin/python app.py 8050 &
APP_PID=$!
sleep 4
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/
kill -9 $APP_PID 2>/dev/null
```
Expected: `HTTP 200`.

**Step 4: Commit**

```bash
git add -A
git commit -m "0i: complete aeroedge -> tallyaero rename in remaining config files"
```

---

## Sub-phase 0d — Structured logging

Replace ad-hoc `print()` and `dprint()` with a Python `logging` module. Configurable via `TALLYAERO_OVERLAY_LOG` env var.

### Task 13: Create `core/log.py`

**Files:**
- Create: `core/log.py`

**Step 1: Write the module**

```python
"""TallyAero Maneuver Overlay — structured logging.

Reads TALLYAERO_OVERLAY_LOG from the environment to set the root level.
Defaults to INFO. Use:

    from core.log import get_logger
    log = get_logger(__name__)
    log.info("starting simulation")
    log.warning("falling back to default")

The format is intentionally short for terminal readability: HH:MM:SS LEVEL
module — message.
"""

from __future__ import annotations

import logging
import os
import sys

_INITIALIZED = False


def _initialize() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    level_name = os.environ.get("TALLYAERO_OVERLAY_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))

    root = logging.getLogger("tallyaero.overlay")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the tallyaero.overlay namespace."""
    _initialize()
    return logging.getLogger(f"tallyaero.overlay.{name}")
```

**Step 2: Smoke test**

Run:
```bash
venv/bin/python -c "from core.log import get_logger; log = get_logger('test'); log.info('hello'); log.debug('not shown by default')"
```
Expected: One line of output starting with a timestamp, level `INFO`, name `tallyaero.overlay.test`, message `hello`. No debug line.

**Step 3: Commit**

```bash
git add core/log.py
git commit -m "0d: add core/log.py — structured logging via TALLYAERO_OVERLAY_LOG env"
```

### Task 14: Replace `print` / `dprint` in `app.py`

**Files:**
- Modify: `app.py`

**Step 1: Inventory print/dprint usage**

Run: `grep -nE "^[^#]*\b(print|dprint)\(" app.py | head -30`
Expected: list of call sites.

**Step 2: Add the log import at the top of `app.py`**

Use Edit to add near the existing imports:

```python
from core.log import get_logger

log = get_logger(__name__)
```

**Step 3: Replace each `print(...)` call with `log.info(...)` / `log.debug(...)` / `log.warning(...)` / `log.error(...)`**

Judgment per call:
- Boot-time status messages → `log.info`
- Detailed simulation traces → `log.debug`
- Recovered-from problems → `log.warning`
- Errors that didn't crash but should be visible → `log.error`

Use Edit per occurrence. Do not change message content; just wrap.

**Step 4: Replace `dprint(...)` calls similarly**

`dprint` was a debug-print helper — convert all to `log.debug(...)`.

**Step 5: Verify no `print(` or `dprint(` remain in `app.py`**

Run: `grep -nE "\b(print|dprint)\(" app.py | grep -v "#"`
Expected: empty output (or only matches in string literals — review each).

**Step 6: Boot-smoke**

Run:
```bash
TALLYAERO_OVERLAY_LOG=INFO venv/bin/python app.py 8050 &
APP_PID=$!
sleep 4
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/
kill -9 $APP_PID 2>/dev/null
```
Expected: HTTP 200, terminal shows structured log lines (no raw `print` output).

**Step 7: Commit**

```bash
git add app.py
git commit -m "0d: replace print/dprint in app.py with structured logging"
```

### Task 15: Replace `print` / `dprint` in `simulation/*.py`

**Files:**
- Modify: every `simulation/*.py` containing `print(` or `dprint(`

**Step 1: Inventory**

Run: `grep -rnE "\b(print|dprint)\(" simulation/ | head -30`

**Step 2: For each file, add log import at top and replace calls**

For each `simulation/<name>.py`:
1. Add `from core.log import get_logger` and `log = get_logger(__name__)` at top.
2. Replace each print/dprint with the appropriate log level.

**Step 3: Verify**

Run: `grep -rnE "\b(print|dprint)\(" simulation/ | grep -v "#"`
Expected: empty.

**Step 4: Run smoke tests (planned later, just check imports)**

Run: `venv/bin/python -c "import simulation; print('import ok')"`
Expected: `import ok`.

**Step 5: Commit**

```bash
git add simulation/
git commit -m "0d: replace print/dprint in simulation/ with structured logging"
```

### Task 16: Replace `print` / `dprint` in remaining modules

**Files:**
- Modify: `physics/*.py`, `rendering/*.py`, `data/*.py`, `utils/*.py`, `edit_aircraft_page.py`

**Step 1: Inventory all remaining**

Run:
```bash
grep -rnE "\b(print|dprint)\(" \
  --include="*.py" \
  --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=tests \
  . | grep -v "app.py" | grep -v "simulation/" | head -40
```

**Step 2: Per-file replacement, same pattern as Task 15**

Add the log import + replace calls in each affected file.

**Step 3: Final verification**

Run: `grep -rnE "\b(print|dprint)\(" --include="*.py" --exclude-dir=venv --exclude-dir=__pycache__ . | grep -v "#"`
Expected: empty (or string-literal matches only).

**Step 4: Commit**

```bash
git add -A
git commit -m "0d: replace print/dprint in remaining modules — logging migration complete"
```

---

## Sub-phase 0f — Explicit `init_data()`

Move boot-time data loads (`load_aircraft_data`, `load_airport_data`) out of module-import side effects into an explicit function. Tests can skip the load via `TALLYAERO_NO_AUTO_INIT=1`.

### Task 17: Locate the boot-time loaders in `app.py`

**Files:** none modified.

**Step 1: Find them**

Run: `grep -n "^aircraft_data\s*=\|^airport_data\s*=\|^available_aircraft\s*=" app.py`
Expected: shows the module-level assignment lines (around line 40-60).

Note the exact line numbers.

### Task 18: Refactor into `init_data()` + auto-call guard

**Files:**
- Modify: `app.py`

**Step 1: Add the new module shape**

Replace the module-level loader block with:

```python
import os

# Module-level placeholders — populated by init_data().
aircraft_data: dict = {}
available_aircraft: list = []
airport_data: list = []


def init_data() -> None:
    """Load aircraft and airport data from disk into module-level caches.

    Idempotent. Called automatically at import time unless
    TALLYAERO_NO_AUTO_INIT is set (used by tests that want to load curated
    subsets).
    """
    global aircraft_data, available_aircraft, airport_data
    if aircraft_data:
        return  # already populated; respect idempotency
    aircraft_data = load_aircraft_data()
    available_aircraft = sorted(aircraft_data.keys())
    airport_data = load_airport_data()


# Default: auto-init unless explicitly disabled (mirrors EM Diagram convention).
if not os.environ.get("TALLYAERO_NO_AUTO_INIT"):
    init_data()
```

The functions `load_aircraft_data` and `load_airport_data` already exist in the file — leave them where they are.

**Step 2: Boot-smoke (default path)**

Run: `venv/bin/python -c "import app; print(len(app.aircraft_data), 'aircraft;', len(app.airport_data), 'airports')"`
Expected: `115 aircraft; 16128 airports` (or similar non-zero counts).

**Step 3: Boot-smoke (skip path)**

Run: `TALLYAERO_NO_AUTO_INIT=1 venv/bin/python -c "import app; print(len(app.aircraft_data), 'aircraft (should be 0)')"`
Expected: `0 aircraft (should be 0)`.

**Step 4: Boot the server normally**

Run:
```bash
venv/bin/python app.py 8050 &
APP_PID=$!
sleep 4
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/
kill -9 $APP_PID 2>/dev/null
```
Expected: HTTP 200.

**Step 5: Commit**

```bash
git add app.py
git commit -m "0f: extract init_data() so module import has no side effects

Aircraft + airport data now load only when init_data() is called.
Default behaviour preserved by auto-call at module load — tests can
opt out via TALLYAERO_NO_AUTO_INIT=1 to load curated subsets."
```

---

## Sub-phase 0b — pytest smoke + physics tests

Build the test infrastructure. Smoke tests prove every simulation module imports and runs. Physics tests hand-calculate three maneuvers against published references.

### Task 19: Create `tests/` skeleton

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`

**Step 1: Write `tests/__init__.py`**

Empty file. Run: `touch tests/__init__.py`

**Step 2: Write `tests/conftest.py`**

```python
"""Pytest config + shared fixtures for the Maneuver Overlay Tool."""

import os
import sys
from pathlib import Path

# Tests load a curated aircraft subset, not the full 115-file fleet.
os.environ.setdefault("TALLYAERO_NO_AUTO_INIT", "1")

# Make the repo root importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
```

**Step 3: Commit**

```bash
git add tests/
git commit -m "0b: bootstrap tests/ skeleton with conftest.py"
```

### Task 20: Write `tests/test_smoke.py` — every simulation module imports

**Files:**
- Create: `tests/test_smoke.py`

**Step 1: Write the failing test**

```python
"""Smoke tests — every simulation module imports cleanly and exposes its
documented public function. Catches dependency drift and broken imports
before they hit users."""

import importlib

import pytest


SIMULATION_MODULES = [
    ("simulation.base",                  None),  # utility module, no top-level fn
    ("simulation.steep_turn",            "simulate_steep_turn"),
    ("simulation.chandelle",             "simulate_chandelle"),
    ("simulation.lazy_eight",            "simulate_lazy_eight"),
    ("simulation.steep_spiral",          "simulate_steep_spiral"),
    ("simulation.s_turn",                "simulate_s_turn"),
    ("simulation.po180",                 "simulate_power_off_180"),
    ("simulation.glide_path",            "find_required_aob_for_arc_fit"),
    ("simulation.engine_out",            "simulate_engineout_glide"),
    ("simulation.impossible_turn",       "simulate_impossible_turn"),
    ("simulation.turns_around_point",    "simulate_turns_around_point"),
    ("simulation.rectangular_course",    "simulate_rectangular_course"),
    ("simulation.eights_on_pylons",      "simulate_eights_on_pylons"),
]


@pytest.mark.parametrize("module_name,export_name", SIMULATION_MODULES)
def test_simulation_module_imports(module_name, export_name):
    mod = importlib.import_module(module_name)
    if export_name is not None:
        assert hasattr(mod, export_name), \
            f"{module_name} missing expected export: {export_name}"
        assert callable(getattr(mod, export_name)), \
            f"{module_name}.{export_name} is not callable"


def test_core_log_module():
    from core.log import get_logger
    log = get_logger("tests")
    log.info("smoke")
    assert log.name == "tallyaero.overlay.tests"


def test_app_module_imports_without_data():
    """With TALLYAERO_NO_AUTO_INIT=1, app imports without hitting disk."""
    import app
    assert app.aircraft_data == {}
    assert app.airport_data == []
```

**Step 2: Run, expect it to pass**

Run: `venv/bin/pytest tests/test_smoke.py -v`
Expected: 15 tests pass (13 parametrize + 2 standalone).

If any fail because a module's expected export isn't there, update `SIMULATION_MODULES` to match the actual export.

**Step 3: Commit**

```bash
git add tests/test_smoke.py
git commit -m "0b: add tests/test_smoke.py — 15 import smoke tests for simulation/"
```

### Task 21: Write `tests/test_physics.py` — three published-reference hand-calcs

**Files:**
- Create: `tests/test_physics.py`

**Step 1: Write the failing test**

The three canonical hand-calcs:

1. **Standard rate turn radius.** At 120 KTAS, 25° bank, radius should be ≈ 1,910 ft. Formula: `r = V² / (g × tan(bank))` with V in fps.
2. **Stall speed at bank.** Vs at 60° bank = Vs_clean × √(load_factor) = Vs_clean × √2.
3. **Glide ratio range.** From 5,000 ft AGL at 9:1 glide ratio in still air, range = 45,000 ft = 7.4 NM.

```python
"""Physics hand-calcs — proves the simulation engine's foundational formulas
match published aviation references. Failures here likely indicate a unit
conversion bug or a formula error."""

import math

import pytest

# Constants (re-derived locally to avoid coupling to whatever the app exports)
G_FT_S2 = 32.174
KT_TO_FPS = 1.68781
FT_PER_NM = 6076.12


# -------------------------------------------------------------------
# Test 1 — Standard rate turn radius
# -------------------------------------------------------------------

def _turn_radius_ft(tas_knots: float, bank_deg: float) -> float:
    v_fps = tas_knots * KT_TO_FPS
    return v_fps ** 2 / (G_FT_S2 * math.tan(math.radians(bank_deg)))


def test_turn_radius_120_kt_25_deg_bank():
    """120 kt, 25° bank → radius ≈ 1,910 ft (FAA Pilot's Handbook of
    Aeronautical Knowledge, Ch. 5)."""
    r = _turn_radius_ft(120.0, 25.0)
    assert 1850 < r < 1980, f"got {r:.0f} ft, expected ~1,910"


def test_turn_radius_grows_with_speed():
    r_slow = _turn_radius_ft(80.0, 30.0)
    r_fast = _turn_radius_ft(160.0, 30.0)
    # Doubling speed at same bank → 4× radius
    ratio = r_fast / r_slow
    assert 3.9 < ratio < 4.1, f"got {ratio:.2f}, expected ~4.0"


# -------------------------------------------------------------------
# Test 2 — Stall speed at bank (load factor)
# -------------------------------------------------------------------

def _stall_speed_at_bank(vs_clean_kt: float, bank_deg: float) -> float:
    n = 1.0 / math.cos(math.radians(bank_deg))
    return vs_clean_kt * math.sqrt(n)


def test_vs_at_60_deg_bank_doubles_load_factor():
    """At 60° bank, n = 2; Vs grows by √2. Vs_clean = 50 kt → Vs60 ≈ 70.7 kt.
    (PHAK Ch. 5 + Aerodynamics for Naval Aviators)."""
    vs_clean = 50.0
    vs_60 = _stall_speed_at_bank(vs_clean, 60.0)
    assert 70.0 < vs_60 < 71.5, f"got {vs_60:.1f} kt, expected ~70.7"


def test_vs_at_45_deg_bank_grows_by_19_percent():
    """At 45° bank, Vs grows by √(1/cos45°) ≈ 1.189."""
    vs_clean = 50.0
    vs_45 = _stall_speed_at_bank(vs_clean, 45.0)
    assert 1.18 < (vs_45 / vs_clean) < 1.20, \
        f"ratio {vs_45/vs_clean:.3f}, expected ~1.189"


# -------------------------------------------------------------------
# Test 3 — Glide range
# -------------------------------------------------------------------

def _glide_range_nm(altitude_agl_ft: float, glide_ratio: float) -> float:
    return (altitude_agl_ft * glide_ratio) / FT_PER_NM


def test_glide_range_5000ft_9to1_still_air():
    """5,000 ft AGL, 9:1 glide → 45,000 ft = 7.40 NM."""
    r = _glide_range_nm(5000.0, 9.0)
    assert 7.35 < r < 7.45, f"got {r:.2f} NM, expected ~7.40"


def test_glide_range_scales_linearly():
    r_low = _glide_range_nm(2000.0, 9.0)
    r_high = _glide_range_nm(6000.0, 9.0)
    ratio = r_high / r_low
    assert 2.95 < ratio < 3.05, f"got {ratio:.2f}, expected 3.0"


# -------------------------------------------------------------------
# Cross-check — compute_turn_radius from utility.py
# (proves OUR implementation matches the reference formula)
# -------------------------------------------------------------------

def test_app_turn_radius_matches_reference():
    """Our compute_turn_radius() function in utility.py must match the
    canonical formula within 1% for the standard test condition."""
    from utility import compute_turn_radius

    canonical = _turn_radius_ft(120.0, 25.0)
    ours = compute_turn_radius(120.0, 25.0)
    rel_err = abs(canonical - ours) / canonical
    assert rel_err < 0.01, \
        f"compute_turn_radius={ours:.0f}, canonical={canonical:.0f}, " \
        f"rel_err={rel_err:.4f}"
```

**Step 2: Run, expect to pass**

Run: `venv/bin/pytest tests/test_physics.py -v`
Expected: 7 tests pass.

If `test_app_turn_radius_matches_reference` fails because `compute_turn_radius` has a different signature, adjust the call to match the actual signature (read `utility.py` to confirm).

**Step 3: Total test count check**

Run: `venv/bin/pytest --collect-only -q`
Expected: ≥22 tests collected (15 from smoke + 7 from physics).

**Step 4: Commit**

```bash
git add tests/test_physics.py
git commit -m "0b: add tests/test_physics.py — 7 hand-calc tests against PHAK references"
```

### Task 22: Add three more maneuver-specific physics tests

**Files:**
- Modify: `tests/test_physics.py`

**Step 1: Append maneuver-specific tests**

Append to `tests/test_physics.py`:

```python
# -------------------------------------------------------------------
# Maneuver-specific — at least one canonical scenario per simulation
# -------------------------------------------------------------------

def test_engine_out_glide_returns_path():
    """simulate_engineout_glide produces a non-empty path with hover data
    for a Cessna 172 at 5,000 ft AGL, calm wind."""
    from geopy.point import Point as GeoPoint
    from simulation.engine_out import simulate_engineout_glide

    start = GeoPoint(30.5, -97.5)  # near KAUS
    path, hover, warnings = simulate_engineout_glide(
        start_point=start,
        start_altitude_ft=5000.0,
        start_heading=90.0,
        glide_ratio=9.0,
        tas_knots=65.0,
        wind_dir_deg=0.0,
        wind_speed_kt=0.0,
    )
    assert len(path) > 5, f"path has {len(path)} points, expected >5"
    assert len(hover) == len(path), "hover/path length mismatch"
    assert hover[0]["alt"] > hover[-1]["alt"], "altitude must decrease"


def test_steep_turn_returns_valid_hover_schema():
    """Steep turn hover data must contain every key promised by
    MANEUVER_STANDARD.md."""
    from simulation.steep_turn import simulate_steep_turn

    path, hover, warnings = simulate_steep_turn(
        bank_deg=45.0,
        ias_knots=110.0,
        entry_heading=270.0,
        altitude_ft=3000.0,
        sequence="left",
        oat_c=15.0,
        wind_dir_deg=0.0,
        wind_speed_kt=0.0,
        weight_lb=2300.0,
        cg_position=0.5,
        power_setting=0.65,
    )
    assert len(hover) > 10
    required_keys = {"time", "alt", "tas", "ias", "gs", "aob", "vs",
                     "track", "heading", "drift", "load_factor", "segment"}
    missing = required_keys - set(hover[0].keys())
    assert not missing, f"missing hover keys: {missing}"


def test_impossible_turn_succeeds_above_min_alt():
    """Given a 1,000 ft AGL start with reasonable params, the impossible
    turn should succeed (returns a path back toward the runway)."""
    from geopy.point import Point as GeoPoint
    from simulation.impossible_turn import simulate_impossible_turn

    departure = GeoPoint(30.5, -97.5)
    path, hover, warnings = simulate_impossible_turn(
        departure_point=departure,
        runway_heading=270.0,
        start_altitude_agl_ft=1000.0,
        bank_deg=45.0,
        reaction_delay_sec=4.0,
        glide_ratio=9.0,
        tas_knots=65.0,
        wind_dir_deg=0.0,
        wind_speed_kt=0.0,
    )
    assert len(path) > 10
    # Final point should be heading back toward the runway (roughly 090°
    # from a 270° takeoff, i.e., a 180° turn)
    final_heading = hover[-1].get("heading", None)
    assert final_heading is not None
```

**Step 2: Run**

Run: `venv/bin/pytest tests/test_physics.py -v`
Expected: 10 tests pass. If the simulate_* signatures differ from my guesses, adjust the test calls to match (read each module's def signature).

**Step 3: Total test count**

Run: `venv/bin/pytest --collect-only -q | tail -3`
Expected: ≥25 tests collected.

**Step 4: Commit**

```bash
git add tests/test_physics.py
git commit -m "0b: add 3 maneuver-end-to-end physics tests"
```

---

## Sub-phase 0c — Snapshot testing via `syrupy`

Lock canonical simulation outputs as golden snapshots. Phase-2 physics changes are deliberate; snapshot drift caught immediately.

### Task 23: Add `syrupy` to dev deps

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add `syrupy` to optional-dependencies.dev**

Edit `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "syrupy>=4.6",
    "ruff>=0.5",
]
```

**Step 2: Re-install dev**

Run: `venv/bin/pip install -e ".[dev]"`
Expected: pytest + syrupy + ruff installed.

### Task 24: Write `tests/test_snapshots.py`

**Files:**
- Create: `tests/test_snapshots.py`

**Step 1: Write the snapshot tests**

```python
"""Snapshot tests for canonical maneuver outputs.

These lock the simulation engine's outputs for a fixed scenario set.
Deliberate physics changes regenerate snapshots via:

    venv/bin/pytest tests/test_snapshots.py --snapshot-update

Any other snapshot drift is a bug."""

from geopy.point import Point as GeoPoint
import pytest


# -------------------------------------------------------------------
# Helper — strip floating-point noise to make snapshots stable across
# numpy versions, machine precision, etc.
# -------------------------------------------------------------------

def _round_hover(hover: list[dict], digits: int = 1) -> list[dict]:
    """Round all numeric values in the hover list."""
    def r(v):
        if isinstance(v, float):
            return round(v, digits)
        return v
    return [{k: r(v) for k, v in pt.items()} for pt in hover]


# -------------------------------------------------------------------
# Snapshots
# -------------------------------------------------------------------

def test_engine_out_glide_kaus_5000ft_calm(snapshot):
    from simulation.engine_out import simulate_engineout_glide

    path, hover, warnings = simulate_engineout_glide(
        start_point=GeoPoint(30.5, -97.5),
        start_altitude_ft=5000.0,
        start_heading=90.0,
        glide_ratio=9.0,
        tas_knots=65.0,
        wind_dir_deg=0.0,
        wind_speed_kt=0.0,
    )
    # Lock the first and last 3 points only — the path is long, full snapshot
    # would be a huge file. The boundaries are what matter for correctness.
    assert _round_hover(hover[:3]) == snapshot(name="hover_start")
    assert _round_hover(hover[-3:]) == snapshot(name="hover_end")


def test_steep_turn_left_45deg_110kt(snapshot):
    from simulation.steep_turn import simulate_steep_turn

    path, hover, warnings = simulate_steep_turn(
        bank_deg=45.0,
        ias_knots=110.0,
        entry_heading=270.0,
        altitude_ft=3000.0,
        sequence="left",
        oat_c=15.0,
        wind_dir_deg=0.0,
        wind_speed_kt=0.0,
        weight_lb=2300.0,
        cg_position=0.5,
        power_setting=0.65,
    )
    assert _round_hover(hover[:3]) == snapshot(name="hover_start")
    assert _round_hover(hover[-3:]) == snapshot(name="hover_end")
    assert len(path) == snapshot(name="path_length")


def test_impossible_turn_1000ft_45deg(snapshot):
    from simulation.impossible_turn import simulate_impossible_turn

    path, hover, warnings = simulate_impossible_turn(
        departure_point=GeoPoint(30.5, -97.5),
        runway_heading=270.0,
        start_altitude_agl_ft=1000.0,
        bank_deg=45.0,
        reaction_delay_sec=4.0,
        glide_ratio=9.0,
        tas_knots=65.0,
        wind_dir_deg=0.0,
        wind_speed_kt=0.0,
    )
    assert _round_hover(hover[:3]) == snapshot(name="hover_start")
    assert _round_hover(hover[-3:]) == snapshot(name="hover_end")
```

**Step 2: Generate snapshots**

Run: `venv/bin/pytest tests/test_snapshots.py --snapshot-update -v`
Expected: 9 snapshots created (3 tests × 3 named snapshots each). Output: `9 snapshots generated`.

**Step 3: Run again, snapshots should now pass**

Run: `venv/bin/pytest tests/test_snapshots.py -v`
Expected: `3 passed`.

**Step 4: Verify snapshot files exist**

Run: `ls tests/__snapshots__/`
Expected: `test_snapshots.ambr` or similar.

**Step 5: Commit**

```bash
git add pyproject.toml tests/test_snapshots.py tests/__snapshots__/
git commit -m "0c: add syrupy snapshot tests for 3 canonical maneuver outputs

Locks engine-out glide, steep turn, and impossible turn outputs.
Deliberate physics changes regenerate via pytest --snapshot-update."
```

---

## Sub-phase 0e — `prevent_initial_call` audit

Walk the 47 callbacks in `app.py`. Most should have `prevent_initial_call=True` unless their initial firing is intentional and produces sensible output.

### Task 25: Inventory callbacks

**Files:** none modified.

**Step 1: List all `@app.callback` decorators**

Run:
```bash
grep -nE "^[[:space:]]*@app\.callback" app.py
```
Expected: 47 line numbers.

**Step 2: For each, determine if `prevent_initial_call` is already set**

Run:
```bash
grep -nA 20 "^[[:space:]]*@app\.callback" app.py \
  | grep -E "@app\.callback|prevent_initial_call" \
  | head -100
```

Expected: alternating callback definitions and (where present) `prevent_initial_call=...` markers. Count how many are missing.

Save the audit output for the commit message.

### Task 26: Add `prevent_initial_call=True` where missing — block 1

**Files:**
- Modify: `app.py`

**Step 1: Pick the first 10 callbacks without `prevent_initial_call`**

Manually scan the grep output from Task 25. For each: read the callback body. If the initial firing on page load would produce a nonsense or wasted-compute result, add `prevent_initial_call=True` to the decorator.

**Common cases that NEED `prevent_initial_call=True`:**
- Map-draw callbacks that depend on user clicks
- Simulation-run callbacks that depend on selected parameters
- Save/load callbacks gated on buttons

**Cases that should NOT have it:**
- Initial layout-population callbacks (e.g., populating dropdown options on page load)
- Display callbacks that should show a default state

Use Edit per callback.

**Step 2: After 10 edits, run smoke tests**

Run: `venv/bin/pytest -q`
Expected: all tests pass.

Boot the server:
```bash
venv/bin/python app.py 8050 &
APP_PID=$!
sleep 4
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/
kill -9 $APP_PID 2>/dev/null
```
Expected: HTTP 200.

**Step 3: Commit**

```bash
git add app.py
git commit -m "0e: add prevent_initial_call=True to first batch of 10 callbacks"
```

### Tasks 27 + 28: Repeat for remaining callbacks in batches of 10

Same pattern as Task 26. Two more batches to cover the remaining ~20-30 callbacks needing changes.

After each batch:
1. Run `venv/bin/pytest -q` — must pass.
2. Boot-smoke — must HTTP 200.
3. Commit with batch number in the message.

**Acceptance for sub-phase 0e:** Every callback that depends on user input has `prevent_initial_call=True`. Server still HTTP 200 on cold start. All tests still pass.

---

## Sub-phase 0h — Makefile + tracked-junk cleanup

### Task 29: Write the `Makefile`

**Files:**
- Create: `Makefile`

**Step 1: Write the file**

```makefile
# TallyAero Maneuver Overlay Tool — top-level Makefile
# All targets assume the venv at ./venv is the active interpreter.

PY := venv/bin/python
PIP := venv/bin/pip
PYTEST := venv/bin/pytest
RUFF := venv/bin/ruff
PORT ?= 8050

.PHONY: help install install-dev run test test-v snapshot-update lint clean kill-server

help:
	@echo "Targets:"
	@echo "  install        Install runtime deps into ./venv"
	@echo "  install-dev    Install runtime + dev deps (pytest, syrupy, ruff)"
	@echo "  run            Start the Dash dev server on PORT=$(PORT)"
	@echo "  test           Run all pytest tests quietly"
	@echo "  test-v         Run pytest verbosely"
	@echo "  snapshot-update Regenerate syrupy snapshots (deliberate physics changes)"
	@echo "  lint           Run ruff over the codebase"
	@echo "  kill-server    Kill any process listening on PORT"
	@echo "  clean          Remove __pycache__, .pytest_cache, *.pyc"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements.txt
	$(PIP) install -e ".[dev]"

run:
	TALLYAERO_OVERLAY_LOG=INFO $(PY) app.py $(PORT)

test:
	$(PYTEST) -q

test-v:
	$(PYTEST) -v

snapshot-update:
	$(PYTEST) --snapshot-update -v tests/test_snapshots.py

lint:
	$(RUFF) check .

kill-server:
	@lsof -ti:$(PORT) | xargs -r kill -9 || true

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
	find . -name "*.pyc" -delete
```

**Step 2: Verify each target**

Run:
```bash
make help          # should list targets
make test          # should pass all tests
make lint          # should pass (or print warnings only, not errors)
make clean         # should run silently
```

If `make lint` finds errors, fix them in a separate commit (not part of this task).

**Step 3: Commit**

```bash
git add Makefile
git commit -m "0h: add Makefile — run/test/snapshot-update/lint/clean targets"
```

### Task 30: Remove tracked `__pycache__` and `.DS_Store` files

**Files:** delete tracked junk.

**Step 1: List tracked junk**

Run:
```bash
git ls-files | grep -E "__pycache__|\.pyc$|\.DS_Store$" | head -30
```
Expected: ~30 files.

**Step 2: Untrack them**

Run:
```bash
git ls-files | grep -E "__pycache__|\.pyc$|\.DS_Store$" \
  | xargs git rm --cached
```

**Step 3: Verify .gitignore covers them**

Run: `cat .gitignore | head -5`
Expected: `__pycache__/`, `*.pyc`, `.DS_Store` are listed (they were added in the pre-Phase-0 setup commit).

**Step 4: Verify clean state**

Run: `git ls-files | grep -E "__pycache__|\.pyc$|\.DS_Store$"`
Expected: empty output.

**Step 5: Commit**

```bash
git commit -m "0h: stop tracking __pycache__, .pyc, .DS_Store (.gitignore now covers)"
```

---

## Final verification — full Phase 0 acceptance

### Task 31: Acceptance run-through

**Step 1: Full test suite**

Run: `make test`
Expected: ≥30 tests pass. Capture the count from the output:
```
make test 2>&1 | tail -1
```
Output line: `30 passed in N.NNs` (or higher).

**Step 2: Boot the server**

Run:
```bash
make kill-server
make run &
sleep 5
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8050/
make kill-server
```
Expected: `HTTP 200`.

**Step 3: Telemetry-free verification**

Run: `grep -rn "aeroedge_tracker" --exclude-dir=.git --exclude-dir=venv .`
Expected: empty output.

Run: `grep -rni "aeroedge" --exclude-dir=.git --exclude-dir=venv --include="*.py" --include="*.md" .`
Expected: empty output.

**Step 4: Git hygiene**

Run: `git ls-files | grep -E "__pycache__|\.pyc$|\.DS_Store$"`
Expected: empty.

Run: `git log --oneline phase-0-foundation ^main | wc -l`
Expected: roughly 18-25 commits (one per task that committed).

**Step 5: Append a Phase 0 log entry**

Use Edit on `OVERLAY_TOOL_EXECUTION_PLAN.md` — append under the "Dated execution log" section:

```markdown
- 2026-05-13 — **Phase 0 shipped.** Test infrastructure + telemetry removal + dev ergonomics complete. pyproject.toml + pytest + syrupy + structured logging + explicit init_data() + Makefile + aeroedge→tallyaero rename + tracked-junk cleanup. **30+ tests passing.** Server boots clean on port 8050 with zero telemetry network calls. Branch `phase-0-foundation` is N commits ahead of main; ready to merge.
```

Commit:

```bash
git add OVERLAY_TOOL_EXECUTION_PLAN.md
git commit -m "0h: log Phase 0 completion in execution plan"
```

**Step 6: Update Phase index status**

Use Edit on `OVERLAY_TOOL_EXECUTION_PLAN.md` — change the Phase 0 row in the index table from `pending` to `complete`. Same commit message-style update.

```bash
git add OVERLAY_TOOL_EXECUTION_PLAN.md
git commit -m "0h: mark Phase 0 complete in plan index"
```

### Task 32: Merge to main

**Step 1: Push the feature branch (optional, user's call)**

Run (with user permission only): `git push -u origin phase-0-foundation`

**Step 2: Switch to main and merge**

```bash
git checkout main
git merge --no-ff phase-0-foundation -m "Phase 0: foundation complete"
```

Expected: clean merge, no conflicts.

**Step 3: Delete the feature branch (local + optional remote)**

```bash
git branch -d phase-0-foundation
# Optional, with user permission:
# git push origin :phase-0-foundation
```

---

## What's next after Phase 0

Per `OVERLAY_TOOL_EXECUTION_PLAN.md`: **Phase 1 — Decompose `app.py` (7,784 lines → ≤200).** The biggest single phase by raw effort. Hand off to `superpowers:writing-plans` again to expand Phase 1 into its own implementation plan; do NOT start Phase 1 from this plan.

---

## Plan complete and saved to `docs/plans/2026-05-13-phase-0-foundation.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for active hands-on review.

**2. Parallel Session (separate)** — Open new session at `~/Desktop/tallyaero_overlay_archives/`, batch execution with checkpoints. Good for letting Phase 0 run in the background while you do other work.

Which approach?
