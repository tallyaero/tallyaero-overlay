"""Tests for the PerformanceDynamics Pydantic block.

Phase B1 of the maneuver production-ready plan. Adds an optional
`performance_dynamics` block to every aircraft. Validates the field
ranges and the cross-field rule that POH-tier values must carry a
citation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.schema import Aircraft, PerformanceDynamics


REPO_ROOT = Path(__file__).resolve().parent.parent
C172_PATH = REPO_ROOT / "aircraft_data" / "Cessna_172S.json"


@pytest.fixture
def c172_dict():
    with open(C172_PATH) as f:
        return json.load(f)


@pytest.fixture
def minimal_dynamics():
    return {
        "roll_rate_dps": 45.0,
        "bank_response_tau_s": 1.0,
        "speed_response_tau_s": 1.5,
        "takeoff_accel_factor": 0.30,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "class_derived",
    }


def test_minimal_dynamics_parses(minimal_dynamics):
    pd = PerformanceDynamics.model_validate(minimal_dynamics)
    assert pd.roll_rate_dps == 45.0
    assert pd.provenance == "class_derived"
    assert pd.poh_citation is None


def test_provenance_must_be_one_of_three(minimal_dynamics):
    bad = {**minimal_dynamics, "provenance": "made_up"}
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate(bad)


def test_roll_rate_positive(minimal_dynamics):
    bad = {**minimal_dynamics, "roll_rate_dps": 0}
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate(bad)


def test_roll_rate_upper_bound(minimal_dynamics):
    bad = {**minimal_dynamics, "roll_rate_dps": 300}
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate(bad)


def test_bank_tau_range(minimal_dynamics):
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "bank_response_tau_s": 0})
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "bank_response_tau_s": 50})


def test_speed_tau_range(minimal_dynamics):
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "speed_response_tau_s": 0})
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "speed_response_tau_s": 50})


def test_takeoff_accel_factor_range(minimal_dynamics):
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "takeoff_accel_factor": 0})
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "takeoff_accel_factor": 1.5})


def test_inter_maneuver_pause_range(minimal_dynamics):
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "inter_maneuver_pause_s": -1})
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate({**minimal_dynamics, "inter_maneuver_pause_s": 60})


def test_poh_provenance_requires_citation(minimal_dynamics):
    bad = {**minimal_dynamics, "provenance": "poh"}  # no poh_citation
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate(bad)
    bad_empty = {**minimal_dynamics, "provenance": "poh", "poh_citation": ""}
    with pytest.raises(ValidationError):
        PerformanceDynamics.model_validate(bad_empty)


def test_poh_provenance_accepts_citation(minimal_dynamics):
    ok = {**minimal_dynamics, "provenance": "poh", "poh_citation": "C172S POH Sec 4"}
    pd = PerformanceDynamics.model_validate(ok)
    assert pd.provenance == "poh"
    assert pd.poh_citation == "C172S POH Sec 4"


def test_estimated_provenance_no_citation_required(minimal_dynamics):
    pd = PerformanceDynamics.model_validate({**minimal_dynamics, "provenance": "estimated"})
    assert pd.provenance == "estimated"


def test_dynamics_optional_on_aircraft(c172_dict):
    # Aircraft schema must accept files with no performance_dynamics block.
    # (Strip the block from the on-disk 172S — after Phase B2 ran, every
    # aircraft has one, but the schema must still parse a stripped dict.)
    c172_dict.pop("performance_dynamics", None)
    ac = Aircraft.model_validate(c172_dict)
    assert ac.performance_dynamics is None


def test_dynamics_nested_into_aircraft(c172_dict, minimal_dynamics):
    c172_dict["performance_dynamics"] = minimal_dynamics
    ac = Aircraft.model_validate(c172_dict)
    assert ac.performance_dynamics is not None
    assert ac.performance_dynamics.roll_rate_dps == 45.0
    assert ac.performance_dynamics.provenance == "class_derived"


def test_extra_field_in_dynamics_forbidden(c172_dict, minimal_dynamics):
    bad = {**minimal_dynamics, "unknown_field": "x"}
    c172_dict["performance_dynamics"] = bad
    with pytest.raises(ValidationError):
        Aircraft.model_validate(c172_dict)
