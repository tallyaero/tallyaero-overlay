# Phase 2 — Aircraft Data Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give every aircraft file in `aircraft_data/` (112 files) a TCDS provenance footprint, a Pydantic schema lock-in, and a per-class realistic `T_static_factor` (replacing the universal 2.6 placeholder).

**Architecture:** Port the Pydantic schema + the four TCDS/thrust scripts from the EM Diagram archive at `~/Desktop/tallyaero_archives/aeroedge_em_diagram/` (which has the *scripts* but never applied them to data — see below). Run the scripts against the overlay tool's 112 aircraft files. Add a schema-validation pytest fixture. Single behaviour change to the simulation: `T_static_factor` shifts from a flat 2.6 to per-class values (1.85 / 2.50 / 2.50 / 3.00), so `tests/test_snapshots.py` will need a one-time regeneration after sanity-checking the physics delta.

**Tech Stack:** Python 3.11, Pydantic v2, `pdftotext` (poppler) subprocess for TCDS-PDF parsing, NumPy, syrupy snapshot testing.

**Repo:** `~/Desktop/tallyaero_overlay_archives/` on `main` at commit `825eacb` (Phase 1 merged + pushed). All work lands on a new feature branch `phase-2-aircraft-data`.

**Reality check on the EM Diagram source:** the EM Diagram archive task list claimed Phase 2a-2h complete, but on-disk and on GitHub `origin/main` of `github.com/tallyaero/tallyaero-em`:
- `core/schema.py` exists with `Aircraft`, `EngineOption`, `PropThrustDecay`, `ThrustModel` Pydantic models. **Portable.**
- `data/scrapers/{tcds_matcher,apply_tcds_mapping,tcds_pdf_parser,reconcile_tcds,classify_thrust_models}.py` all exist. **Portable.**
- `docs/tcds_mapping.csv/json`, `docs/reconciliation_report.csv` exist as historical artifacts. **Portable (informational).**
- But **the aircraft JSONs themselves still have `T_static_factor: 2.6` and `tcds_number: None`** — the apply-step was never run against the data. So Phase 2 of the overlay tool must actually execute the scripts, not just port their outputs.

**Aircraft delta (overlay vs EM Diagram):** the overlay tool has 112 files; EM Diagram has 110. The two overlay-only files are `Diamond_DA20-C1 2.json` and `Piper_PA-34_Seneca 2.json` — both look like accidental duplicates with a trailing ` 2` (macOS Finder "Copy" suffix) of the base files. Phase 2a investigates whether to delete them or keep as legitimate variants.

**Acceptance (at end of plan):**
- `core/schema.py` exports `Aircraft`, `EngineOption`, `PropThrustDecay`, `ThrustModel` Pydantic models.
- Every `aircraft_data/*.json` validates cleanly against the Aircraft schema (`tests/test_aircraft_schema.py`).
- Every aircraft file has `tcds_number`, `tcds_holder`, `sources[]`, `verified_fields[]`, `confidence` (where TCDS mapping resolved), and `prop_thrust_decay.thrust_model` + `prop_thrust_decay.T_static_factor` set to the per-class realistic value.
- `make test` shows **≥35 passed** (32 existing + ≥3 new schema tests).
- `make run` boots HTTP 200.
- Snapshot tests either pass unchanged or are regenerated once with `--snapshot-update` after a physics sanity-check of the diff.
- Branch `phase-2-aircraft-data` ready to merge to `main`.

---

## Task sequencing rationale

1. **Task 0** — Branch + baseline verify.
2. **Sub-phase 2a (Tasks 1–3)** — Vendor aircraft_data from EM Diagram + resolve the 2-file delta. Touches data only; no code.
3. **Sub-phase 2b (Task 4)** — Port `core/schema.py` Pydantic models. Pure code copy.
4. **Sub-phase 2e-pre (Task 5)** — Add `tests/test_aircraft_schema.py` against the *current* (un-upgraded) data, expecting failures on missing TCDS fields if any. The schema models should treat those as Optional so this passes immediately, but the test gets written FIRST (TDD-ish — it'll catch a regression in any future task that breaks aircraft files).
5. **Sub-phase 2c (Tasks 6–9)** — Port the TCDS scripts one at a time, then run the pipeline against the data.
6. **Sub-phase 2d (Tasks 10–11)** — Port `classify_thrust_models.py`, run it, regenerate snapshots after physics sanity check.
7. **Sub-phase 2e (Task 12)** — Tighten the schema test once data is fully populated; add a few targeted assertions.
8. **Tasks 13–14** — Acceptance + merge.

**Standard verification loop** (referenced from every task): `make test` shows ≥32 passing (or higher if tests have been added), boot a fresh server: `pkill -9 -f "python app.py 8052"; sleep 1; TALLYAERO_OVERLAY_LOG=INFO venv/bin/python app.py 8052 > /tmp/ot_p2.log 2>&1 &; sleep 5; curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8052/`. Expected HTTP 200.

---

## Task 0: Branch setup + baseline

**Step 1:** `cd ~/Desktop/tallyaero_overlay_archives && git status && git log --oneline -2`
Expected: clean working tree, HEAD at `825eacb` ("Phase 1: decomposition complete").

**Step 2:** `git checkout -b phase-2-aircraft-data`
Expected: `Switched to a new branch 'phase-2-aircraft-data'`.

**Step 3:** Run the standard verification loop. Expected 32 passed, HTTP 200.

No commit.

---

## Sub-phase 2a — Reconcile aircraft_data with EM Diagram (informational vendoring)

The decision D11 (vendored copy + sync_check) is locked. Phase 2a establishes the discipline.

### Task 1: Inventory the 2-file delta

**Step 1:** Confirm the delta:
```bash
diff <(ls ~/Desktop/tallyaero_overlay_archives/aircraft_data | sort) \
     <(ls ~/Desktop/tallyaero_archives/aeroedge_em_diagram/aircraft_data | sort) | head -10
```
Expected: 2 lines for `Diamond_DA20-C1 2.json` and `Piper_PA-34_Seneca 2.json` in overlay only.

**Step 2:** Compare each duplicate to its base file to confirm "macOS Finder copy" hypothesis:
```bash
diff ~/Desktop/tallyaero_overlay_archives/aircraft_data/Diamond_DA20-C1.json \
     "~/Desktop/tallyaero_overlay_archives/aircraft_data/Diamond_DA20-C1 2.json"

diff ~/Desktop/tallyaero_overlay_archives/aircraft_data/Piper_PA-34_Seneca.json \
     "~/Desktop/tallyaero_overlay_archives/aircraft_data/Piper_PA-34_Seneca 2.json"
```
If the diff is empty (or trivially different — e.g., name field), the duplicates are confirmed.

No commit yet.

### Task 2: Delete the duplicates

**Step 1:** If both diffs in Task 1 confirmed duplicates, remove them:
```bash
cd ~/Desktop/tallyaero_overlay_archives
git rm "aircraft_data/Diamond_DA20-C1 2.json" "aircraft_data/Piper_PA-34_Seneca 2.json"
ls aircraft_data | wc -l    # expect 110
```

**Step 2:** Run the standard verification loop. Expected 32 passed, HTTP 200.

**Step 3:** Commit:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2a: delete macOS Finder duplicate aircraft files

'Diamond_DA20-C1 2.json' and 'Piper_PA-34_Seneca 2.json' are
content-identical copies of their base files with the trailing ' 2'
that macOS Finder adds when duplicating. Removed. Count drops from
112 to 110 to align with the EM Diagram archive."
```

If the diffs in Task 1 showed REAL content differences, STOP and ask the user how to handle (they may want to merge changes into the base or keep both as variants).

### Task 3: Scaffold `scripts/sync_check.py`

This is a slimmed-down preview of Phase 12a (cross-app sync_check); landing it here gets the sync-check discipline in place from the start of Phase 2.

**Files:**
- Create: `scripts/sync_check.py`

**Step 1:** Write the script:
```python
"""scripts/sync_check.py — diff aircraft_data/ between this repo and the
EM Diagram archive. Reports drift; does NOT mutate.

Run:
    venv/bin/python scripts/sync_check.py
    venv/bin/python scripts/sync_check.py --aircraft Cessna_172P    # one file only
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

OVERLAY_ROOT = Path("/Users/nicholaslen/Desktop/tallyaero_overlay_archives/aircraft_data")
EM_DIAGRAM_ROOT = Path("/Users/nicholaslen/Desktop/tallyaero_archives/aeroedge_em_diagram/aircraft_data")


def _hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--aircraft", help="Inspect a single aircraft basename (e.g. Cessna_172P)")
    args = p.parse_args()

    if not OVERLAY_ROOT.exists() or not EM_DIAGRAM_ROOT.exists():
        raise SystemExit("Either repo root not found; check paths.")

    if args.aircraft:
        names = [args.aircraft]
    else:
        names = sorted({p.stem for p in OVERLAY_ROOT.glob("*.json")}
                       | {p.stem for p in EM_DIAGRAM_ROOT.glob("*.json")})

    same = 0
    differ = []
    overlay_only = []
    em_only = []

    for name in names:
        ov = OVERLAY_ROOT / f"{name}.json"
        em = EM_DIAGRAM_ROOT / f"{name}.json"
        if ov.exists() and em.exists():
            if _hash(ov) == _hash(em):
                same += 1
            else:
                differ.append(name)
        elif ov.exists():
            overlay_only.append(name)
        else:
            em_only.append(name)

    print(f"identical: {same}")
    print(f"differ:    {len(differ)}")
    if differ:
        for n in differ[:20]:
            print(f"  - {n}")
        if len(differ) > 20:
            print(f"  ... and {len(differ) - 20} more")
    print(f"overlay-only: {len(overlay_only)}")
    for n in overlay_only[:10]:
        print(f"  - {n}")
    print(f"em-diagram-only: {len(em_only)}")
    for n in em_only[:10]:
        print(f"  - {n}")


if __name__ == "__main__":
    main()
```

**Step 2:** Run it: `venv/bin/python scripts/sync_check.py`
Expected output: `identical: 110, differ: 0, overlay-only: 0, em-diagram-only: 0` (after Task 2's deletes).

**Step 3:** Commit:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add scripts/sync_check.py
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2a: add scripts/sync_check.py — diff aircraft_data vs EM Diagram archive

D11 enforcement scaffold. Reports content-hash drift between the
overlay tool's aircraft_data/ and the EM Diagram archive's. Will be
used in Phase 12a as part of the broader cross-app reciprocity work."
```

---

## Sub-phase 2b — Port Pydantic schema

### Task 4: Copy `core/schema.py` from EM Diagram

**Files:**
- Create: `core/schema.py` (port verbatim from EM Diagram)

**Step 1:** Copy the file:
```bash
cp ~/Desktop/tallyaero_archives/aeroedge_em_diagram/core/schema.py \
   ~/Desktop/tallyaero_overlay_archives/core/schema.py
```

**Step 2:** Inspect the top of the file to confirm the four core classes are there:
```bash
grep -n "^class " ~/Desktop/tallyaero_overlay_archives/core/schema.py
```
Expected: classes including `EngineOption`, `PropThrustDecay`, `Aircraft`, plus the `ThrustModel` Literal type alias and the source-provenance fields.

**Step 3:** Verify the file imports cleanly:
```bash
cd ~/Desktop/tallyaero_overlay_archives
venv/bin/python -c "from core.schema import Aircraft, EngineOption, PropThrustDecay, ThrustModel; print('schema imports ok')"
```
Expected: `schema imports ok`. If a missing import or syntax error surfaces (e.g., a reference to a helper that doesn't exist in this repo), fix the minimal thing needed to get the file importing.

**Step 4:** Try loading one aircraft file through the schema:
```bash
venv/bin/python -c "
import json
from core.schema import Aircraft
d = json.load(open('aircraft_data/Cessna_172P.json'))
ac = Aircraft(**d)
print('Cessna_172P parsed:', ac.name)
"
```
Expected: `Cessna_172P parsed: Cessna 172P` (or similar). If validation errors surface, the schema may expect fields that the current data lacks — those fields should be `Optional` already (per the EM Diagram's design where the schema accepts pre-Phase-2 data). If a field is required but missing, decide: (a) make it Optional in the schema, or (b) add it as a placeholder to the data. **Recommend (a)** to keep the schema permissive on pre-Phase-2 data; later tasks tighten it.

**Step 5:** Commit:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add core/schema.py
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2b: port core/schema.py Pydantic models from EM Diagram

Aircraft, EngineOption, PropThrustDecay, ThrustModel Literal type +
source-provenance fields (tcds_number, tcds_holder, sources[],
verified_fields[], confidence). All TCDS/thrust-related fields are
Optional so pre-Phase-2 data still validates. Phases 2c/2d populate
them; Phase 2e tightens the schema once data is complete."
```

---

## Sub-phase 2e-pre — Schema validation test (TDD scaffold)

### Task 5: Write `tests/test_aircraft_schema.py`

**Files:**
- Create: `tests/test_aircraft_schema.py`

**Step 1:** Write the test:
```python
"""Aircraft schema validation tests.

Every aircraft_data/*.json must parse cleanly against the Pydantic Aircraft
schema. Catches schema drift in data + drift in the schema definition.

Phase 2e tightens additional assertions about required-after-Phase-2 fields
(tcds_number presence rate, thrust_model required, etc.). For now we only
check basic structural validity.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.schema import Aircraft

AIRCRAFT_DIR = Path(__file__).resolve().parent.parent / "aircraft_data"

# Enumerate every aircraft file at collection time so pytest parametrizes them
AIRCRAFT_FILES = sorted(AIRCRAFT_DIR.glob("*.json"))


@pytest.mark.parametrize("aircraft_path", AIRCRAFT_FILES, ids=lambda p: p.stem)
def test_aircraft_file_validates(aircraft_path):
    """Every aircraft file must parse cleanly against the Aircraft schema."""
    data = json.loads(aircraft_path.read_text())
    try:
        Aircraft(**data)
    except ValidationError as e:
        pytest.fail(
            f"{aircraft_path.name} failed schema validation:\n{e}"
        )


def test_aircraft_count_matches_expected():
    """Sanity: we have ≥100 aircraft files (Phase 2 doesn't reduce the fleet)."""
    assert len(AIRCRAFT_FILES) >= 100, (
        f"Found only {len(AIRCRAFT_FILES)} aircraft files; expected at "
        f"least 100. Check whether aircraft_data/ got truncated."
    )
```

**Step 2:** Run it:
```bash
cd ~/Desktop/tallyaero_overlay_archives
make test 2>&1 | tail -5
```
Expected: ~142 tests pass (32 existing + 110 parametrized + 1 count test). If any aircraft file fails validation, the schema is too strict for current data — relax it in `core/schema.py` (make the failing fields Optional) and re-run.

**Step 3:** Commit:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add tests/test_aircraft_schema.py
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2e-pre: add tests/test_aircraft_schema.py — Pydantic validation per file

110 parametrized + 1 count test. All pre-Phase-2 data must validate
cleanly under the permissive schema landed in 2b. Phase 2e tightens
once TCDS + thrust fields are populated."
```

---

## Sub-phase 2c — Port + run the TCDS pipeline

### Task 6: Copy the 4 TCDS scripts from EM Diagram

**Files:**
- Create: `data/scrapers/tcds_matcher.py`
- Create: `data/scrapers/apply_tcds_mapping.py`
- Create: `data/scrapers/tcds_pdf_parser.py`
- Create: `data/scrapers/reconcile_tcds.py`

**Step 1:** Ensure the directory exists:
```bash
mkdir -p ~/Desktop/tallyaero_overlay_archives/data/scrapers
ls ~/Desktop/tallyaero_overlay_archives/data/scrapers/
```

**Step 2:** Copy each script verbatim:
```bash
for f in tcds_matcher.py apply_tcds_mapping.py tcds_pdf_parser.py reconcile_tcds.py; do
    cp ~/Desktop/tallyaero_archives/aeroedge_em_diagram/data/scrapers/$f \
       ~/Desktop/tallyaero_overlay_archives/data/scrapers/$f
done
ls ~/Desktop/tallyaero_overlay_archives/data/scrapers/
```

**Step 3:** Check each script's REPO_ROOT path:
```bash
grep -n "REPO_ROOT" ~/Desktop/tallyaero_overlay_archives/data/scrapers/*.py
```
These scripts compute `REPO_ROOT = Path(__file__).resolve().parents[2]`, so they're relocatable — they'll auto-target the overlay tool's aircraft_data/ when run from this checkout. No path edits needed.

**Step 4:** Smoke-test each script can at least import:
```bash
cd ~/Desktop/tallyaero_overlay_archives
for s in tcds_matcher apply_tcds_mapping tcds_pdf_parser reconcile_tcds; do
    venv/bin/python -c "import importlib.util, sys; spec = importlib.util.spec_from_file_location('m', 'data/scrapers/$s.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('$s ok')"
done
```
Expected: 4 "ok" lines. If any fails on an import, fix the minimal thing.

**Step 5:** Commit:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add data/scrapers/
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2c: port 4 TCDS scripts from EM Diagram to data/scrapers/

tcds_matcher.py — fuzzy match + 75-entry MANUAL_OVERRIDES
apply_tcds_mapping.py — write tcds_number/tcds_holder/sources back
tcds_pdf_parser.py — pdftotext-based FAA TCDS parser
reconcile_tcds.py — compare parsed TCDS values vs aircraft JSON

REPO_ROOT is computed from __file__ so the scripts auto-target the
overlay tool when run from this checkout. No path edits needed."
```

### Task 7: Run `tcds_matcher.py` → produce `docs/tcds_mapping.{csv,json}`

**Files:**
- Create: `docs/tcds_mapping.csv`
- Create: `docs/tcds_mapping.json`

**Step 1:** Run:
```bash
cd ~/Desktop/tallyaero_overlay_archives
mkdir -p docs
venv/bin/python data/scrapers/tcds_matcher.py
ls docs/
```
Expected: `tcds_mapping.csv` and `tcds_mapping.json` appear in `docs/`. Inspect a few lines.

**Step 2:** Sanity check the coverage:
```bash
python3 -c "
import json
m = json.load(open('docs/tcds_mapping.json'))
matched = sum(1 for v in m.values() if v.get('tcds_number'))
print(f'matched: {matched}/{len(m)}')
"
```
Expected: at least ~75 matched (the manual overrides) + however many fuzzy matches resolved. Reference EM Diagram outcome was 110/110 matched, but for the overlay's 110 files the numbers will be close.

**Step 3:** Commit:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add docs/tcds_mapping.csv docs/tcds_mapping.json
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2c: generate docs/tcds_mapping.{csv,json} from tcds_matcher.py

NN/110 aircraft mapped (MM manual + KK fuzzy). Used by
apply_tcds_mapping.py in the next task."
```

(Replace `NN`, `MM`, `KK` with the actual numbers from the matcher's output.)

### Task 8: Run `apply_tcds_mapping.py` → mutate aircraft files

**Files:**
- Modify: every `aircraft_data/*.json` that resolved a TCDS

**Step 1:** Run the apply step:
```bash
cd ~/Desktop/tallyaero_overlay_archives
venv/bin/python data/scrapers/apply_tcds_mapping.py
```
Expected: prints a summary like "Wrote N aircraft files; M had no mapping."

**Step 2:** Sanity check a few aircraft files now have `tcds_number`, `sources`:
```bash
python3 -c "
import json
for name in ['Cessna_172P', 'Beechcraft_Baron_58', 'CAP_232']:
    d = json.load(open(f'aircraft_data/{name}.json'))
    print(f'{name}: tcds_number={d.get(\"tcds_number\")} sources={len(d.get(\"sources\", []))}')
"
```
Expected: TCDS numbers and `sources` lists populated for the major aircraft.

**Step 3:** Run schema test + full suite:
```bash
make test 2>&1 | tail -5
```
Expected: all tests pass (the schema accepted the new fields because they were already `Optional`).

**Step 4:** Run the standard verification loop. HTTP 200.

**Step 5:** Commit:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add aircraft_data/
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2c: apply TCDS mapping — every matched aircraft now has provenance

NN aircraft files updated with tcds_number, tcds_holder, sources[],
confidence=partial. Aircraft files unchanged in any other field.
Schema validation tests still pass."
```

### Task 9: (Optional) Run TCDS-PDF parser + reconciler

These produce additional `verified_fields[]` for aircraft whose TCDS PDF is locally available. The EM Diagram's outcome was 3 fully verified + 26 partially verified + 84 with 0 verified fields — most of the 84 are aircraft whose PDF wasn't downloaded.

**Step 1:** Check whether TCDS PDFs are available locally:
```bash
ls ~/Desktop/tallyaero_overlay_archives/data/sources/tcds_pdfs/ 2>/dev/null | wc -l
```
If 0, this task can be deferred — the EM Diagram only got 3 fully verified anyway. Skip to Sub-phase 2d.

**Step 2 (only if PDFs exist):** Run the parser:
```bash
venv/bin/python data/scrapers/tcds_pdf_parser.py
ls data/sources/tcds_parsed/ | wc -l
```

**Step 3 (only if PDFs exist):** Run the reconciler:
```bash
venv/bin/python data/scrapers/reconcile_tcds.py
```
Expected: prints summary and writes `docs/reconciliation_report.csv`. Some aircraft files get upgraded to `confidence: verified`.

**Step 4:** Standard verification loop. Commit if anything changed:
```bash
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com add docs/ aircraft_data/
git -c user.name="Nicholas Len" -c user.email=nlen1987@gmail.com commit -m "2c: reconcile parsed TCDS values against aircraft JSONs

Upgrades NN aircraft to confidence=verified where ≥4 fields match
within tolerance (Vne/Vno/Vfe/Va=3kt, max_weight=20lb, fuel=1gal,
seats=exact, engine_hp=1)."
```

---

## Sub-phase 2d — Per-class thrust model

### Task 10: Port `classify_thrust_models.py`

**Files:**
- Create: `data/scrapers/classify_thrust_models.py`

**Step 1:** Copy:
```bash
cp ~/Desktop/tallyaero_archives/aeroedge_em_diagram/data/scrapers/classify_thrust_models.py \
   ~/Desktop/tallyaero_overlay_archives/data/scrapers/classify_thrust_models.py
```

**Step 2:** Smoke-test import:
```bash
cd ~/Desktop/tallyaero_overlay_archives
venv/bin/python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('m', 'data/scrapers/classify_thrust_models.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('classifier ok')
print('manual override count:', len(m.MANUAL_OVERRIDES))
print('class factors:', m.T_STATIC_BY_CLASS)
"
```
Expected: `classifier ok`, `61` overrides, the 4-class T_STATIC_BY_CLASS dict.

**Step 3:** Commit:
```bash
git add data/scrapers/classify_thrust_models.py
git commit -m "2d: port classify_thrust_models.py from EM Diagram

61 manual overrides + heuristic (twin/retractable/>=200 HP -> CS;
else fixed-pitch). Defaults per class:
  piston_fixed_pitch     1.85
  piston_constant_speed  2.50
  turbocharged           2.50
  turboprop              3.00
"
```

### Task 11: Run the classifier + regenerate snapshots

This is the only task in Phase 2 with a *behavioural* change to simulation outputs. `T_static_factor` shifts from a flat 2.6 to per-class values, so simulation paths and altitudes will subtly change.

**Step 1:** Run the classifier:
```bash
cd ~/Desktop/tallyaero_overlay_archives
venv/bin/python data/scrapers/classify_thrust_models.py
```
Expected: prints summary like "Updated 110 aircraft files. 56 piston_constant_speed, 48 piston_fixed_pitch, 4 turbocharged, 2 turboprop." (Numbers will be close to the EM Diagram's mix.)

**Step 2:** Sanity check a few aircraft now have `thrust_model` + per-class `T_static_factor`:
```bash
python3 -c "
import json
for name in ['Cessna_172P', 'Beechcraft_Baron_58', 'CAP_232', 'T-6A_Texan_II']:
    d = json.load(open(f'aircraft_data/{name}.json'))
    ptd = d.get('prop_thrust_decay', {})
    print(f'{name}: thrust_model={ptd.get(\"thrust_model\")!r} T_static_factor={ptd.get(\"T_static_factor\")}')
"
```
Expected: e.g., `Cessna_172P: thrust_model='piston_fixed_pitch' T_static_factor=1.85`, `Baron_58: 'piston_constant_speed' 2.5`, `CAP_232: 'piston_constant_speed' 2.5`, `T-6A: 'turboprop' 3.0`.

**Step 3:** Run tests — expect snapshot failures:
```bash
make test 2>&1 | tail -10
```
Expected: 32 baseline + 110 schema tests pass; 3 snapshot tests in `tests/test_snapshots.py` FAIL because the `T_static_factor` shift changed engine-out simulation outputs.

**Step 4:** Sanity-check the snapshot diffs are physically sensible:
```bash
make test 2>&1 | grep -E "^E|got|expected" | head -30
```
Look at a failing snapshot — the change should be in the right direction. For Cessna 172P (fixed-pitch, 1.85 vs 2.6 = 29% less thrust), engine-out glide should reach the ground *sooner* / shorter range; impossible turn should be harder. For Baron 58 (CS, 2.5 vs 2.6 = 4% less), almost no visible change. For aerobatic (CS, 2.5) similar small change. If the deltas LOOK wrong (e.g., 172P getting *more* range), STOP and investigate — the classifier may have miscategorised that aircraft.

**Step 5:** Regenerate snapshots:
```bash
make snapshot-update
make test 2>&1 | tail -5
```
Expected: all tests pass.

**Step 6:** Standard verification loop. HTTP 200.

**Step 7:** Commit:
```bash
git add aircraft_data/ tests/__snapshots__/
git commit -m "2d: classify_thrust_models.py applied — per-class T_static_factor

Every aircraft now has prop_thrust_decay.thrust_model set to one of:
  piston_fixed_pitch    1.85 lb/HP static (was 2.6 placeholder)
  piston_constant_speed 2.50 lb/HP
  turbocharged          2.50 lb/HP
  turboprop             3.00 lb/HP

3 snapshot tests regenerated (engine-out glide, steep turn,
impossible turn). Sanity-checked: 172P (fixed-pitch) sees ~29 percent
thrust reduction at low IAS, matching FAA AFH Ch 4 references."
```

---

## Sub-phase 2e — Tighten schema validation

### Task 12: Add post-Phase-2 schema assertions

**Files:**
- Modify: `tests/test_aircraft_schema.py`

**Step 1:** Append new assertions to the existing test file:
```python
# Append to tests/test_aircraft_schema.py

def test_every_aircraft_has_thrust_model():
    """After Phase 2d, every aircraft must have a non-None thrust_model."""
    missing = []
    for path in AIRCRAFT_FILES:
        data = json.loads(path.read_text())
        ptd = data.get("prop_thrust_decay") or {}
        if not ptd.get("thrust_model"):
            missing.append(path.stem)
    assert not missing, (
        f"{len(missing)} aircraft missing prop_thrust_decay.thrust_model:\n"
        + "\n".join(f"  - {n}" for n in missing[:20])
    )


def test_thrust_model_in_valid_classes():
    """Every thrust_model is one of the 4 known classes."""
    VALID = {"piston_fixed_pitch", "piston_constant_speed", "turbocharged", "turboprop"}
    bad = []
    for path in AIRCRAFT_FILES:
        data = json.loads(path.read_text())
        tm = (data.get("prop_thrust_decay") or {}).get("thrust_model")
        if tm and tm not in VALID:
            bad.append((path.stem, tm))
    assert not bad, f"Unknown thrust_model values: {bad}"


def test_t_static_factor_matches_class():
    """T_static_factor must match the per-class default (Phase 2d ran
    classify_thrust_models which sets both simultaneously)."""
    EXPECTED = {
        "piston_fixed_pitch": 1.85,
        "piston_constant_speed": 2.50,
        "turbocharged": 2.50,
        "turboprop": 3.00,
    }
    mismatch = []
    for path in AIRCRAFT_FILES:
        data = json.loads(path.read_text())
        ptd = data.get("prop_thrust_decay") or {}
        tm = ptd.get("thrust_model")
        tsf = ptd.get("T_static_factor")
        if tm and EXPECTED.get(tm) is not None and abs(tsf - EXPECTED[tm]) > 0.01:
            mismatch.append((path.stem, tm, tsf))
    assert not mismatch, f"T_static_factor mismatches: {mismatch}"


def test_tcds_coverage_threshold():
    """At least 75% of aircraft should have a non-None tcds_number."""
    with_tcds = sum(
        1 for p in AIRCRAFT_FILES
        if json.loads(p.read_text()).get("tcds_number")
    )
    coverage = with_tcds / len(AIRCRAFT_FILES)
    assert coverage >= 0.75, (
        f"TCDS coverage {coverage:.1%} below 75% threshold "
        f"({with_tcds}/{len(AIRCRAFT_FILES)})"
    )
```

**Step 2:** Run:
```bash
make test 2>&1 | tail -5
```
Expected: 4 new tests pass.

**Step 3:** Commit:
```bash
git add tests/test_aircraft_schema.py
git commit -m "2e: tighten schema validation — thrust_model + T_static + TCDS coverage

4 new assertions:
  - every aircraft has thrust_model
  - thrust_model is one of the 4 valid classes
  - T_static_factor matches per-class default
  - >=75% of aircraft have a tcds_number

Catches regressions in Phase 2d's classifier or future aircraft-file
edits that bypass the pipeline."
```

---

## Final acceptance + merge

### Task 13: Full Phase 2 acceptance

**Step 1:** Total test count:
```bash
cd ~/Desktop/tallyaero_overlay_archives
venv/bin/pytest --collect-only -q | tail -3
```
Expected: ~150 tests (32 baseline + 110 schema parametrized + 4 schema assertion + 4 atmosphere from Phase 0 = ~150).

**Step 2:** Run all tests:
```bash
make test 2>&1 | tail -3
```
Expected: all passing, no skip, no fail.

**Step 3:** Boot smoke:
```bash
make kill-server > /dev/null 2>&1
make run > /tmp/ot_p2_final.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8052/
make kill-server > /dev/null 2>&1
```
Expected: HTTP 200.

**Step 4:** Update `OVERLAY_TOOL_EXECUTION_PLAN.md` — flip the Phase 2 row from `pending` to `**complete**` and append a dated log entry:

```markdown
- 2026-05-14 — **Phase 2 shipped.** Aircraft data hardening complete. Branch
  `phase-2-aircraft-data` is N commits ahead of main.
  - **2a** sync_check scaffold + dropped 2 macOS Finder duplicate aircraft files
    (`Diamond_DA20-C1 2.json`, `Piper_PA-34_Seneca 2.json`). Fleet count: 110.
  - **2b** `core/schema.py` ported from EM Diagram archive (Aircraft, EngineOption,
    PropThrustDecay, ThrustModel + source-provenance fields).
  - **2c** TCDS pipeline ported + run. `docs/tcds_mapping.{csv,json}` produced;
    NN aircraft now carry `tcds_number`, `tcds_holder`, `sources[]`,
    `confidence=partial`. PDF reconciliation deferred until TCDS PDFs are
    sourced (Phase 2c-tail or later).
  - **2d** `classify_thrust_models.py` ported + run. Every aircraft now has
    `prop_thrust_decay.thrust_model` ∈ {piston_fixed_pitch, piston_constant_speed,
    turbocharged, turboprop} with the realistic per-class `T_static_factor`
    (1.85 / 2.50 / 2.50 / 3.00) replacing the universal 2.6 placeholder.
    Snapshot tests regenerated; physics sanity-checked.
  - **2e** `tests/test_aircraft_schema.py` — 110 parametrized validation tests
    + 4 post-Phase-2 assertions. Total test count: ~150.
  - **Open items deferred:** TCDS-PDF reconciliation (need to source PDFs);
    Phase 2g drag polar refinement (optional cd_rise_above_cl per aircraft).
```

Commit the doc:
```bash
git add OVERLAY_TOOL_EXECUTION_PLAN.md
git commit -m "2e: log Phase 2 completion in execution plan"
```

### Task 14: Merge to main + push

**Step 1:** Verify clean working tree:
```bash
git status
git log --oneline phase-2-aircraft-data ^main | wc -l
```
Expected: clean; ~10-12 commits ahead of main.

**Step 2 (WAIT FOR USER OK):** Switch + merge:
```bash
git checkout main
git merge --no-ff phase-2-aircraft-data \
  -m "Phase 2: aircraft data hardening complete

NN aircraft now carry TCDS provenance + per-class thrust models.
Schema is Pydantic-validated on every file. ~150 tests passing.
core/schema.py + 5 scripts ported from EM Diagram archive."
```

**Step 3 (WAIT FOR USER OK):** Push:
```bash
git push origin main
```

**Step 4:** Delete local feature branch:
```bash
git branch -d phase-2-aircraft-data
```

---

## What's next after Phase 2

Per `OVERLAY_TOOL_EXECUTION_PLAN.md`: **Phase 3 — Airport data overhaul** (port the OurAirports+NASR merge from EM Diagram). Smaller phase, mostly a copy job. Estimated ~1 short session.

---

## Plan complete and saved to `docs/plans/2026-05-14-phase-2-aircraft-data.md`. Two execution options:

**1. Subagent-Driven (this session)** — fresh subagent per sub-phase, review between commits, hands-on. ~14 tasks → likely 1 working session given the mechanical nature.

**2. Parallel Session (separate)** — new session at `~/Desktop/tallyaero_overlay_archives/`, batch execution with checkpoints. Plan is self-contained enough for a fresh session via `executing-plans` skill.

Which approach?
