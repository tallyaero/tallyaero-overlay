"""Tests for core.dynamics.dynamics_for — runtime three-tier fallback.

Phase B4. Loader that the maneuver sim calls to get performance_dynamics
for any aircraft, no matter what tier of data is present:

    tier 1 (poh)           — read from ac["performance_dynamics"]
    tier 2 (class_derived) — read from ac["performance_dynamics"]
    tier 3 (estimated)     — compute on the fly via derive_dynamics(),
                             with provenance overwritten to "estimated"
    last-resort            — hard-coded GA-single fallback dict
"""
from __future__ import annotations

import json
from pathlib import Path

from core.dynamics import dynamics_for


REPO_ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT = REPO_ROOT / "aircraft_data"

REQUIRED_KEYS = {
    "roll_rate_dps",
    "bank_response_tau_s",
    "speed_response_tau_s",
    "takeoff_accel_factor",
    "inter_maneuver_pause_s",
    "provenance",
}

VALID_PROVENANCE = {"poh", "class_derived", "estimated"}


def _load(basename):
    with open(AIRCRAFT / f"{basename}.json") as f:
        return json.load(f)


def test_poh_aircraft_returns_poh_tier():
    """An aircraft with provenance='poh' on disk returns that exact value."""
    pd = dynamics_for(_load("Cessna_172S"))
    assert pd["provenance"] == "poh"
    assert pd["roll_rate_dps"] == 45.0
    assert "poh_citation" in pd


def test_class_derived_aircraft_returns_class_tier():
    """An aircraft with provenance='class_derived' returns that value."""
    pd = dynamics_for(_load("Beechcraft_Baron_58"))
    assert pd["provenance"] == "class_derived"
    assert pd["roll_rate_dps"] == 25.0


def test_aircraft_with_no_block_falls_through_to_estimated():
    """When performance_dynamics is missing, compute on the fly."""
    ac = _load("Cessna_172S")
    ac.pop("performance_dynamics", None)
    pd = dynamics_for(ac)
    assert pd["provenance"] == "estimated"
    assert pd["roll_rate_dps"] > 0


def test_returned_dict_has_all_required_keys():
    for basename in ["Cessna_172S", "Beechcraft_Baron_58", "Pitts_S-2C"]:
        pd = dynamics_for(_load(basename))
        assert REQUIRED_KEYS.issubset(pd.keys()), (
            f"{basename} missing keys: {REQUIRED_KEYS - pd.keys()}"
        )


def test_provenance_always_valid():
    for basename in ["Cessna_172S", "Cessna_152", "Beechcraft_Baron_58",
                     "Pitts_S-2C", "American_Champion_Decathlon"]:
        pd = dynamics_for(_load(basename))
        assert pd["provenance"] in VALID_PROVENANCE


def test_completely_invalid_aircraft_returns_fallback():
    """Even an empty dict (no fields to derive from) should not crash."""
    pd = dynamics_for({})
    assert pd["provenance"] == "estimated"
    assert REQUIRED_KEYS.issubset(pd.keys())
    assert pd["roll_rate_dps"] > 0


def test_dynamics_for_does_not_mutate_input():
    """The caller's aircraft dict must be unchanged after the call."""
    ac = _load("Cessna_172S")
    original = json.loads(json.dumps(ac))
    _ = dynamics_for(ac)
    assert ac == original


def test_returned_dict_is_independent_copy():
    """Mutating the returned dict must not corrupt the aircraft's data."""
    ac = _load("Cessna_172S")
    pd = dynamics_for(ac)
    pd["roll_rate_dps"] = 999.0
    # Re-read from the unchanged input
    pd2 = dynamics_for(ac)
    assert pd2["roll_rate_dps"] != 999.0
