"""Phase 2 dynamics tests for impossible_turn.

Before the wiring: every aircraft used the same hardcoded
`bank_response_tau_sec=1.5`, `tau_sec=4.0` (speed), and HP-bucket
takeoff acceleration. Result: a Decathlon felt exactly like a 172S.

After Phase 2: the sim reads per-airframe `performance_dynamics` via
`core.dynamics.dynamics_for(ac)` and per-aircraft results diverge as
real airframes do.

These tests pin that contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulation.impossible_turn import simulate_takeoff_phase


AIRCRAFT_DIR = Path(__file__).resolve().parent.parent / "aircraft_data"


def _load(name: str) -> dict:
    return json.loads((AIRCRAFT_DIR / f"{name}.json").read_text())


def _takeoff(ac: dict):
    engine = next(iter(ac["engine_options"].keys()))
    weight = float(ac.get("max_weight", 2500))
    _, v_ias, t, _, _, roll = simulate_takeoff_phase(
        threshold_point={"lat": 30.5, "lon": -97.5},
        heading_deg=0.0,
        ac=ac,
        weight_lbs=weight,
        oat_c=15.0,
        altimeter_inhg=29.92,
        field_elev_ft=0.0,
        wind_dir=0.0,
        wind_speed=0.0,
        engine_option=engine,
    )
    return {"liftoff_ias": v_ias, "time_sec": t, "ground_roll_ft": roll}


def test_takeoff_accel_uses_poh_factor():
    """C172S ground roll at SL, gross, calm should be in the POH-cited
    band of ~850-1000 ft. The pre-fix HP-bucket heuristic produced
    ~2100 ft — multiple times the real number."""
    res = _takeoff(_load("Cessna_172S"))
    assert 750 <= res["ground_roll_ft"] <= 1100, (
        f"C172S ground roll {res['ground_roll_ft']:.0f} ft outside POH band "
        f"[750, 1100]. Did POH takeoff_accel_factor wiring regress?"
    )
    assert 10 <= res["time_sec"] <= 20, (
        f"C172S time-to-liftoff {res['time_sec']:.1f} s outside expected [10, 20]"
    )


def test_decathlon_outperforms_172_on_takeoff():
    """Decathlon has higher power-to-weight than a 172S and POH-cites
    a shorter ground roll. The two airframes must show this difference
    after POH-dynamics wiring."""
    res_172 = _takeoff(_load("Cessna_172S"))
    res_dec = _takeoff(_load("American_Champion_Decathlon"))
    assert res_dec["time_sec"] < res_172["time_sec"], (
        f"Decathlon time {res_dec['time_sec']:.1f}s should beat 172S "
        f"{res_172['time_sec']:.1f}s — POH dynamics not differentiating airframes"
    )
    assert res_dec["ground_roll_ft"] < res_172["ground_roll_ft"], (
        f"Decathlon roll {res_dec['ground_roll_ft']:.0f}ft should beat 172S "
        f"{res_172['ground_roll_ft']:.0f}ft"
    )


def test_per_aircraft_differentiation():
    """Trainer-class 172S, sport Decathlon, and twin Baron should
    produce three meaningfully different ground rolls. Pre-fix all
    fell into HP-buckets that lumped similar airframes; after Phase 2
    each one is driven by its own POH-cited factor."""
    rolls = {
        name: _takeoff(_load(name))["ground_roll_ft"]
        for name in ("Cessna_172S", "American_Champion_Decathlon", "Beechcraft_Baron_58")
    }
    # 172S vs Decathlon: meaningfully different (lighter sport plane wins).
    assert rolls["American_Champion_Decathlon"] < rolls["Cessna_172S"] - 50, (
        f"Decathlon ({rolls['American_Champion_Decathlon']:.0f}ft) should beat 172S "
        f"({rolls['Cessna_172S']:.0f}ft) by at least 50 ft"
    )
    # 172S vs Baron: very different weight class — must differ by hundreds of ft.
    assert abs(rolls["Cessna_172S"] - rolls["Beechcraft_Baron_58"]) > 300, (
        f"172S ({rolls['Cessna_172S']:.0f}ft) and Baron 58 "
        f"({rolls['Beechcraft_Baron_58']:.0f}ft) should differ substantially"
    )
