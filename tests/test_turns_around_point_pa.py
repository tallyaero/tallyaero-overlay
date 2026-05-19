"""Tests for pivotal-altitude surfacing in Turns Around a Point sim.

Phase C1 — ACS Gap 1. The TAP sim must compute PA per step (because
PA varies with ground speed around the orbit just like on Eights on
Pylons) and surface min/max/avg in the warnings dict. The pilot can
then see at what altitude this aircraft would naturally pivot at the
chosen IAS/wind, even though TAP is flown at constant altitude.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulation.turns_around_point import simulate_turns_around_point


REPO_ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT = REPO_ROOT / "aircraft_data"


@pytest.fixture
def c172_dict():
    with open(AIRCRAFT / "Cessna_172S.json") as f:
        return json.load(f)


def _run(c172_dict, wind_dir=180, wind_kt=10):
    return simulate_turns_around_point(
        center_point={"lat": 40.0, "lon": -100.0},
        turn_direction="left",
        entry_heading_deg=None,
        altitude_ft=800,
        ias_knots=100,
        orbit_radius_nm=0.25,
        num_turns=2,
        wind_dir_deg=wind_dir,
        wind_speed_kt=wind_kt,
        oat_c=15,
        altimeter_inhg=29.92,
        field_elev_ft=0,
        ac=c172_dict,
        weight_lb=2300,
    )


def test_each_hover_has_pivotal_alt(c172_dict):
    path, hover, warnings = _run(c172_dict)
    assert hover, "hover must be non-empty"
    for pt in hover:
        assert "pivotal_alt" in pt, f"missing pivotal_alt in hover entry {pt}"
        assert pt["pivotal_alt"] > 0, f"non-positive pivotal_alt {pt['pivotal_alt']}"


def test_pa_varies_with_gs(c172_dict):
    """At fastest-GS point, PA must exceed PA at slowest-GS point."""
    _, hover, _ = _run(c172_dict, wind_dir=180, wind_kt=15)
    max_gs_pt = max(hover, key=lambda p: p["gs"])
    min_gs_pt = min(hover, key=lambda p: p["gs"])
    assert max_gs_pt["pivotal_alt"] > min_gs_pt["pivotal_alt"], (
        f"PA at max-GS ({max_gs_pt['pivotal_alt']}) should exceed "
        f"PA at min-GS ({min_gs_pt['pivotal_alt']})"
    )


def test_warnings_summary_keys_present(c172_dict):
    _, _, warnings = _run(c172_dict)
    for key in ("pivotal_alt_min", "pivotal_alt_max", "pivotal_alt_avg"):
        assert key in warnings, f"warnings missing {key}: keys={list(warnings.keys())}"


def test_warnings_pa_summary_ordering(c172_dict):
    _, _, warnings = _run(c172_dict, wind_kt=15)
    assert warnings["pivotal_alt_min"] <= warnings["pivotal_alt_avg"] <= warnings["pivotal_alt_max"]
    assert warnings["pivotal_alt_max"] > warnings["pivotal_alt_min"], (
        "with 15 kt wind the PA range should be non-zero"
    )


def test_pa_approximates_gs_squared_over_11_3(c172_dict):
    """Sanity: PA per step ≈ GS² / 11.3 (compute_pivotal_altitude formula)."""
    _, hover, _ = _run(c172_dict)
    for pt in hover[:5]:
        expected = (pt["gs"] ** 2) / 11.3
        assert abs(pt["pivotal_alt"] - expected) < 5.0, (
            f"PA {pt['pivotal_alt']} vs expected {expected:.0f} at GS {pt['gs']}"
        )
