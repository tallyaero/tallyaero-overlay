"""Airport schema validation tests.

Sanity-checks the shared-data airports.json against the Pydantic Airport
schema. Catches drift in the merged OurAirports + NASR build pipeline.

Full validation across all 49k records is too slow for the default suite,
so the comprehensive pass is gated behind TALLYAERO_FULL_AIRPORT_VALIDATION=1.
The default test suite validates a deterministic random sample plus the
10 reference airports used by Phase 3d's spot-audit.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.schema import Airport

AIRPORTS_PATH = Path(__file__).resolve().parent.parent / "airports" / "airports.json"

# Phase 3d reference set — well-known airports we expect to remain present.
REFERENCE_IDS = [
    "KJFK", "KLAX", "KORD", "KSFO", "KATL",  # US major
    "EGLL", "LFPG", "RJTT", "YSSY", "OMDB",  # international major
]

# Phase 3d runway-data verification — 5 known US-towered fields. Non-US
# fields (EGLL etc.) get empty runway lists today because build_airports.py
# only attaches NASR runways for US records; non-US runway sourcing is a
# future-work item.
RUNWAY_VERIFICATION_IDS = ["KJFK", "KSFO", "KORD", "KATL", "KLAX"]


def _physical_runway(rwys):
    """Pick the first runway with non-zero physical dimensions, skipping
    NASR declared-only stubs (length_ft=0)."""
    for r in rwys:
        if r.length_ft and r.length_ft > 0:
            return r
    return None


@pytest.fixture(scope="session")
def airports():
    return json.loads(AIRPORTS_PATH.read_text())


def test_airports_file_loads(airports):
    """Airport file is a list of objects (not a dict)."""
    assert isinstance(airports, list)
    assert len(airports) > 1000, f"expected >1000 airports, got {len(airports)}"


def test_reference_airports_present(airports):
    """The 10 reference airports must be in the dataset."""
    by_id = {a["id"]: a for a in airports}
    missing = [aid for aid in REFERENCE_IDS if aid not in by_id]
    assert not missing, f"reference airports missing from data: {missing}"


@pytest.mark.parametrize("aid", REFERENCE_IDS)
def test_reference_airport_validates(airports, aid):
    """Each reference airport parses cleanly against the schema."""
    by_id = {a["id"]: a for a in airports}
    ap = by_id[aid]
    try:
        Airport(**ap)
    except ValidationError as e:
        pytest.fail(f"{aid} failed schema validation:\n{e}")


@pytest.mark.parametrize("aid", RUNWAY_VERIFICATION_IDS)
def test_reference_airport_has_runway_data(airports, aid):
    """Known-towered fields must have at least one physical runway with
    non-zero length + at least one end."""
    by_id = {a["id"]: a for a in airports}
    ap = Airport(**by_id[aid])
    rwy = _physical_runway(ap.runways)
    assert rwy is not None, f"{aid} has no physical runways (stubs only)"
    assert len(rwy.ends) >= 1, f"{aid} runway {rwy.id} has no ends"


def test_random_sample_validates(airports):
    """100-record deterministic sample parses cleanly. Guards against
    field-level drift without paying the full-suite cost."""
    rng = random.Random(0xA12C0DE)  # deterministic
    sample = rng.sample(airports, 100)
    errors = []
    for ap in sample:
        try:
            Airport(**ap)
        except ValidationError as e:
            errors.append(f"{ap.get('id')}: {e}")
    assert not errors, "schema validation failed:\n" + "\n".join(errors[:5])


@pytest.mark.skipif(
    not os.environ.get("TALLYAERO_FULL_AIRPORT_VALIDATION"),
    reason="full validation gated behind TALLYAERO_FULL_AIRPORT_VALIDATION=1",
)
def test_all_airports_validate(airports):
    """Validates every airport. Slow — gated."""
    errors = []
    for ap in airports:
        try:
            Airport(**ap)
        except ValidationError as e:
            errors.append(f"{ap.get('id', '?')}: {str(e).splitlines()[0]}")
    if errors:
        pytest.fail(
            f"{len(errors)} of {len(airports)} airports failed validation. "
            f"First 5:\n" + "\n".join(errors[:5])
        )
