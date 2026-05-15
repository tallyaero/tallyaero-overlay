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

# Known data-quality issues in shared data v0.2.0 (EM Diagram session's Vne
# canonicalization). Tracked as a Phase 2 follow-up — fix in tallyaero-data
# via PR, then drop these markers.
#   Zlin_Z-242L: Vne=117 (km/h) vs Vno=164 (KIAS) — cross-unit comparison.
#   North_American_P51-D_Mustang: Vne=439 < Vno=440 (both MPH) — Vne wrong.
KNOWN_BAD_VNE_VNO = {
    "Zlin_Z-242L",
    "North_American_P51-D_Mustang",
}


@pytest.mark.parametrize("aircraft_path", AIRCRAFT_FILES, ids=lambda p: p.stem)
def test_aircraft_file_validates(aircraft_path, request):
    """Every aircraft file must parse cleanly against the Aircraft schema."""
    if aircraft_path.stem in KNOWN_BAD_VNE_VNO:
        request.applymarker(pytest.mark.xfail(
            reason="shared-data v0.2.0 Vne/Vno unit inconsistency — fix upstream",
            strict=True,
        ))
    data = json.loads(aircraft_path.read_text())
    try:
        Aircraft(**data)
    except ValidationError as e:
        pytest.fail(
            f"{aircraft_path.name} failed schema validation:\n{e}"
        )


def test_aircraft_count_matches_expected():
    """Sanity: we have >=100 aircraft files (Phase 2 doesn't reduce the fleet)."""
    assert len(AIRCRAFT_FILES) >= 100, (
        f"Found only {len(AIRCRAFT_FILES)} aircraft files; expected at "
        f"least 100. Check whether aircraft_data/ got truncated."
    )
