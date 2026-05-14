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
    """Sanity: we have >=100 aircraft files (Phase 2 doesn't reduce the fleet)."""
    assert len(AIRCRAFT_FILES) >= 100, (
        f"Found only {len(AIRCRAFT_FILES)} aircraft files; expected at "
        f"least 100. Check whether aircraft_data/ got truncated."
    )
