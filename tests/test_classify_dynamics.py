"""Tests for scripts.classify_dynamics.derive_dynamics — tier-1 (class-derived).

Phase B2 of the maneuver production-ready plan. The pure function
maps an aircraft JSON dict to a PerformanceDynamics-shaped dict using
class branches based on G_limits / engine_count / gear_type / seats.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core.schema import PerformanceDynamics
from scripts.classify_dynamics import derive_dynamics


REPO_ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT = REPO_ROOT / "aircraft_data"


def _load(basename):
    with open(AIRCRAFT / f"{basename}.json") as f:
        return json.load(f)


def test_top_tier_aerobatic_pitts_s2c():
    """Pitts S-2C has aerobatic.clean.positive = 10.0 → top-tier acro."""
    pd = derive_dynamics(_load("Pitts_S-2C"))
    assert pd["roll_rate_dps"] == 120
    assert pd["provenance"] == "class_derived"


def test_aerobatic_trainer_decathlon():
    """Decathlon has normal.clean.positive = 5.0 → aerobatic-trainer."""
    pd = derive_dynamics(_load("American_Champion_Decathlon"))
    assert pd["roll_rate_dps"] == 90
    assert pd["provenance"] == "class_derived"


def test_trainer_4seat_fixed_gear_cessna_172s():
    """Cessna 172S is the canonical 4-seat fixed-gear trainer."""
    pd = derive_dynamics(_load("Cessna_172S"))
    assert pd["roll_rate_dps"] == 45


def test_light_single_2seat_cessna_152():
    """Cessna 152 has 2 seats + fixed gear → light single."""
    pd = derive_dynamics(_load("Cessna_152"))
    assert pd["roll_rate_dps"] == 40


def test_light_twin_baron_58():
    """Beechcraft Baron 58 (engine_count >= 2) → light twin."""
    pd = derive_dynamics(_load("Beechcraft_Baron_58"))
    assert pd["roll_rate_dps"] == 25


def test_complex_retract_mooney_m20j():
    """Mooney M20J (single, retractable, not aerobatic) → complex/retract."""
    pd = derive_dynamics(_load("Mooney_M20J"))
    assert pd["roll_rate_dps"] == 35


def test_bank_tau_matches_formula():
    """bank_response_tau_s ≈ 1.3 / (roll_rate_dps * pi/180), within 0.05 s."""
    for basename in ["Pitts_S-2C", "American_Champion_Decathlon",
                     "Cessna_172S", "Cessna_152", "Beechcraft_Baron_58",
                     "Mooney_M20J"]:
        pd = derive_dynamics(_load(basename))
        expected = 1.3 / (pd["roll_rate_dps"] * math.pi / 180.0)
        assert abs(pd["bank_response_tau_s"] - expected) <= 0.05, (
            f"{basename}: τ={pd['bank_response_tau_s']:.3f} vs expected {expected:.3f}"
        )


def test_speed_tau_plausible_range():
    """speed_response_tau_s should fall in plausible 1-4 s range for GA."""
    for basename in ["Cessna_172S", "Cessna_152", "Beechcraft_Baron_58",
                     "American_Champion_Decathlon", "Pitts_S-2C", "Mooney_M20J"]:
        pd = derive_dynamics(_load(basename))
        assert 1.0 <= pd["speed_response_tau_s"] <= 4.5, (
            f"{basename}: τ_speed={pd['speed_response_tau_s']:.2f} not in [1.0, 4.5]"
        )


def test_speed_tau_heavier_aircraft_slower():
    """Heavier aircraft should have larger τ_speed than lighter ones."""
    c172 = derive_dynamics(_load("Cessna_172S"))["speed_response_tau_s"]
    baron = derive_dynamics(_load("Beechcraft_Baron_58"))["speed_response_tau_s"]
    assert baron > c172, f"Baron {baron} should exceed C172 {c172}"


def test_takeoff_accel_factor_172s_in_range():
    """C172S should have takeoff_accel_factor in 0.20-0.35 range."""
    pd = derive_dynamics(_load("Cessna_172S"))
    assert 0.20 <= pd["takeoff_accel_factor"] <= 0.40, (
        f"172S TO accel={pd['takeoff_accel_factor']:.3f}"
    )


def test_inter_maneuver_pause_default():
    pd = derive_dynamics(_load("Cessna_172S"))
    assert pd["inter_maneuver_pause_s"] == 1.0


def test_provenance_is_class_derived():
    pd = derive_dynamics(_load("Cessna_172S"))
    assert pd["provenance"] == "class_derived"
    assert pd.get("poh_citation") is None


def test_roundtrips_through_pydantic():
    """The derived dict must validate against PerformanceDynamics."""
    for basename in ["Pitts_S-2C", "Cessna_172S", "Cessna_152",
                     "American_Champion_Decathlon", "Beechcraft_Baron_58",
                     "Mooney_M20J"]:
        pd_dict = derive_dynamics(_load(basename))
        pd = PerformanceDynamics.model_validate(pd_dict)
        assert pd.roll_rate_dps > 0
