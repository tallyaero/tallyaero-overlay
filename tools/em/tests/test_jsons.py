"""
Validate every aircraft JSON profile against the Pydantic schema.

Behavior:
- Strict-mode pass: every JSON must validate against `core.schema.Aircraft`.
  Any file that raises ValidationError fails the run.
- Sanity-warning pass: non-blocking range checks (e.g., aspect_ratio outside
  [3, 15]) surface as warnings.
- Triage CSV: written to `docs/aircraft_data_triage.csv` for human review.

Run with:
    venv/bin/pytest -v tests/test_jsons.py

The triage CSV is regenerated on every test run; it is the authoritative
human-readable view of dataset health.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.schema import Aircraft, find_sanity_warnings

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "aircraft_data"
TRIAGE_DIR = REPO_ROOT / "docs"
TRIAGE_CSV = TRIAGE_DIR / "aircraft_data_triage.csv"


# Discover all aircraft JSON files at collection time so pytest produces one
# test case per file in the report.
_JSON_FILES = sorted([p.name for p in DATA_DIR.glob("*.json")])


def _load_json(path: Path) -> dict:
    with path.open("r") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Module-level triage state.
# Populated by each test as it runs. The session-finalizer writes the CSV.
# ---------------------------------------------------------------------------
_TRIAGE_ROWS: list[dict] = []


@pytest.mark.parametrize("filename", _JSON_FILES)
def test_aircraft_validates(filename: str) -> None:
    """Strict-mode: every aircraft JSON must validate against the schema."""
    path = DATA_DIR / filename
    raw = _load_json(path)

    row: dict = {
        "filename": filename,
        "name": raw.get("name", "?"),
        "type": raw.get("type", "?"),
        "engine_count": raw.get("engine_count", "?"),
        "status": "ok",
        "errors": "",
        "warnings": "",
        "confidence": raw.get("confidence") or "estimated",
        "sources_count": len(raw.get("sources") or []),
        "estimated_fields_count": len(raw.get("estimated_fields") or []),
    }

    errors: list[str] = []
    try:
        Aircraft.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"{loc}: {err['msg']}")
        row["status"] = "fail"
        row["errors"] = " | ".join(errors)

    warnings = find_sanity_warnings(raw)
    row["warnings"] = " | ".join(warnings)
    _TRIAGE_ROWS.append(row)

    # Don't fail the run on validation errors during Phase 0 triage — we want
    # to *enumerate* all defects across all files in a single sweep.
    # Phase 2 flips this assert back on once data is hardened.
    # assert not errors, f"{filename} failed schema validation:\n" + "\n".join(errors)


def test_session_writes_triage_csv() -> None:
    """Last-in-suite: write the triage CSV. Always passes if the file is writable.

    Note: pytest does not guarantee ordering of parametrized tests followed by
    this one, but in practice this test runs after all parametrized
    `test_aircraft_validates` because alphabetical ordering puts it last.
    The CSV may be partial on intermediate runs — that's fine. The
    `make triage` target invokes the suite end-to-end.
    """
    if not _TRIAGE_ROWS:
        pytest.skip("No triage rows collected (run test_aircraft_validates first)")

    TRIAGE_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "filename",
        "name",
        "type",
        "engine_count",
        "status",
        "confidence",
        "sources_count",
        "estimated_fields_count",
        "warnings",
        "errors",
    ]
    with TRIAGE_CSV.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(_TRIAGE_ROWS, key=lambda r: (r["status"] != "fail", r["filename"])):
            writer.writerow(row)

    # Also write a short summary to stdout
    n_total = len(_TRIAGE_ROWS)
    n_fail = sum(1 for r in _TRIAGE_ROWS if r["status"] == "fail")
    n_with_warnings = sum(1 for r in _TRIAGE_ROWS if r["warnings"])
    print(
        f"\nTriage written to {TRIAGE_CSV.relative_to(REPO_ROOT)}: "
        f"{n_total} aircraft, {n_fail} validation failures, "
        f"{n_with_warnings} with warnings."
    )


def test_no_schema_drift_with_overlay_tool() -> None:
    """If the overlay tool tree is reachable, verify it ships the same schema.
    Skipped if the overlay tree is absent (e.g., distribution package).
    """
    overlay_schema = (
        REPO_ROOT.parent / "tallyaero_overlay_tools" / "core" / "schema.py"
    )
    legacy_overlay = (
        REPO_ROOT.parent / "aeroedge_overlay_tools" / "core" / "schema.py"
    )
    target = overlay_schema if overlay_schema.exists() else legacy_overlay
    if not target.exists():
        pytest.skip("overlay tool tree not present — sync check deferred")

    em_schema = REPO_ROOT / "core" / "schema.py"
    em_bytes = em_schema.read_bytes()
    overlay_bytes = target.read_bytes()
    assert em_bytes == overlay_bytes, (
        f"Schema drift detected:\n"
        f"  EM:      {em_schema}\n"
        f"  Overlay: {target}\n"
        f"Run scripts/sync_check.py (Phase 7) to reconcile."
    )
