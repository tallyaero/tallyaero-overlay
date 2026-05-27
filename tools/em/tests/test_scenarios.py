"""
Deterministic physics-scenario snapshots.

For three canonical scenarios (one trainer, one twin OEI, one aerobatic),
compute the full EM-envelope physics from `core/calculations.py` and snapshot
the result. Any drift in the underlying math — intentional or otherwise —
shows up as a failing snapshot test that must be regenerated explicitly
(`pytest --snapshot-update`).

This is the regression net described in Phase 0 of EM_DIAGRAM_EXECUTION_PLAN.md.
It deliberately tests the *physics* layer rather than the Dash `update_graph`
function: update_graph is a Dash callback that still pulls inputs from the UI
tree, and is extracted into a pure function in Phase 1. Once extracted, a
companion `test_figure_snapshot.py` will snapshot full `figure.to_dict()`
output. Until then, this file pins the physics that those figures will be
built on.

Three scenarios:
  1. Cessna 172P  @ 4000 ft PA, +20 °C, 2300 lb, clean, 100% power
  2. Beech Baron 58 @ 8000 ft PA, +5 °C, 5000 lb, clean, OEI feathered
  3. CAP 232      @ SL,        +15 °C, 1500 lb, clean, 100% power, aerobatic
"""

from __future__ import annotations

import math
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.calculations import (
    KTS_TO_FPS,
    FPS_TO_KTS,
    g,
    compute_dynamic_pressure,
    compute_cl,
    compute_cd,
    compute_drag,
    compute_thrust_available,
    compute_ps_knots_per_sec,
    compute_air_density,
    compute_density_altitude,
    compute_load_factor,
    compute_turn_rate_from_load_factor,
    compute_turn_radius,
    compute_stall_speed_at_load_factor,
    interpolate_stall_speed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "aircraft_data"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Scenario definitions — kept verbose so each frozen input is auditable.
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "id": "172p_4000ft_warm_day",
        "aircraft_file": "Cessna_172P.json",
        "weight_lb": 2300.0,
        "altitude_ft": 4000.0,
        "oat_c": 20.0,           # ~15 °C warmer than ISA at 4000 ft
        "flap_config": "clean",
        "category": "normal",
        "power_fraction": 1.0,
        "oei": False,
        "cg_drag_factor": 1.0,
        "gear_drag_factor": 1.0,
    },
    {
        "id": "baron58_8000ft_oei_feathered",
        "aircraft_file": "Beechcraft_Baron_58.json",
        "weight_lb": 5000.0,
        "altitude_ft": 8000.0,
        "oat_c": 5.0,            # near ISA at 8000 ft
        "flap_config": "clean",
        "category": "normal",
        "power_fraction": 0.5,   # OEI: one engine out, the other at ~50% effective
        "oei": True,
        "cg_drag_factor": 1.0,
        "gear_drag_factor": 1.0,
    },
    {
        "id": "cap232_sl_isa_aerobatic",
        "aircraft_file": "CAP_232.json",
        "weight_lb": 1500.0,
        "altitude_ft": 0.0,
        "oat_c": 15.0,           # ISA at SL
        "flap_config": "clean",
        "category": "aerobatic",
        "power_fraction": 1.0,
        "oei": False,
        "cg_drag_factor": 1.0,
        "gear_drag_factor": 1.0,
    },
]


def _round_floats(obj: Any, ndigits: int = 4) -> Any:
    """Recursively round all floats so snapshots are stable across platforms
    (avoids spurious diffs from the last bit of IEEE 754 noise).
    """
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(x, ndigits) for x in obj]
    return obj


def _compute_envelope(scenario: dict) -> dict:
    """Compute the EM envelope physics for one scenario. Returns a plain dict
    suitable for JSON serialization (no numpy arrays)."""
    with (DATA_DIR / scenario["aircraft_file"]).open() as fh:
        ac = json.load(fh)

    # Environment
    rho = compute_air_density(scenario["altitude_ft"], oat_c=scenario["oat_c"])
    density_alt = compute_density_altitude(scenario["altitude_ft"], scenario["oat_c"])

    # Aerodynamics
    wing_area = ac["wing_area"]
    AR = ac["aspect_ratio"]
    CD0 = ac["CD0"]
    e = ac["e"]
    cl_max = ac["CL_max"][scenario["flap_config"]]

    # 1G stall (interpolated by weight)
    stall = interpolate_stall_speed(
        ac["stall_speeds"][scenario["flap_config"]], scenario["weight_lb"]
    )

    # Structural G limits
    g_pos = ac["G_limits"][scenario["category"]][scenario["flap_config"]]["positive"]
    g_neg = ac["G_limits"][scenario["category"]][scenario["flap_config"]]["negative"]

    # Engine: pick the first option deterministically
    engine_name = sorted(ac["engine_options"].keys())[0]
    eng = ac["engine_options"][engine_name]
    hp_sl = eng["power_curve"]["sea_level_max"]
    derate = eng["power_curve"]["derate_per_1000ft"]
    hp_at_alt = hp_sl * (1.0 - derate * scenario["altitude_ft"] / 1000.0)
    hp = max(0.0, hp_at_alt) * scenario["power_fraction"]
    T_static_factor = ac["prop_thrust_decay"]["T_static_factor"]
    V_max_kts = ac["prop_thrust_decay"]["V_max_kts"]

    # Sweep IAS from below Vs1g to Vne
    Vne = ac["Vne"]
    V_grid_kts = np.linspace(max(20.0, stall * 0.85), Vne, 60)

    envelope = []
    for V_kts in V_grid_kts:
        V_fps = V_kts * KTS_TO_FPS
        q = compute_dynamic_pressure(rho, V_fps)
        # n at structural limit
        n_struct_pos = g_pos
        n_struct_neg = g_neg  # negative number
        # n at aerodynamic stall (V² / Vs²)
        n_stall = (V_kts / stall) ** 2 if stall > 0 else 0.0
        # Operating n is the smaller of structural and stall
        n_op_pos = min(n_struct_pos, n_stall)
        n_op_neg = max(n_struct_neg, -n_stall)

        # Turn rate at operating n (positive side)
        omega_pos = compute_turn_rate_from_load_factor(V_kts, abs(n_op_pos))
        omega_neg = -compute_turn_rate_from_load_factor(V_kts, abs(n_op_neg))

        # Turn radius at structural-limit bank for positive G
        if n_op_pos > 1:
            bank_op = math.degrees(math.acos(1.0 / n_op_pos))
            r_op = compute_turn_radius(V_kts, bank_op)
        else:
            r_op = float("inf")

        # Ps at this operating point (1G, level)
        CL = compute_cl(scenario["weight_lb"], 1.0, q, wing_area, cl_max)
        CD = compute_cd(CD0, CL, AR, e, scenario["cg_drag_factor"], scenario["gear_drag_factor"])
        D = compute_drag(q, wing_area, CD)
        T = compute_thrust_available(hp, V_kts, V_max_kts, T_static_factor)
        Ps = compute_ps_knots_per_sec(T, D, V_fps, scenario["weight_lb"], 0.0)

        envelope.append({
            "V_kts": V_kts,
            "n_op_pos": n_op_pos,
            "n_op_neg": n_op_neg,
            "omega_pos_dps": omega_pos,
            "omega_neg_dps": omega_neg,
            "turn_radius_ft": r_op if math.isfinite(r_op) else None,
            "Ps_kts_per_s": Ps,
            "thrust_lb": T,
            "drag_lb": D,
        })

    # Corner velocity: lowest V where stall n meets structural n
    corner_v = None
    for row in envelope:
        if row["n_op_pos"] >= g_pos - 1e-3:
            corner_v = row["V_kts"]
            break

    return {
        "scenario_id": scenario["id"],
        "aircraft": ac["name"],
        "engine": engine_name,
        "inputs": {
            "weight_lb": scenario["weight_lb"],
            "altitude_ft": scenario["altitude_ft"],
            "oat_c": scenario["oat_c"],
            "flap_config": scenario["flap_config"],
            "category": scenario["category"],
            "power_fraction": scenario["power_fraction"],
            "oei": scenario["oei"],
        },
        "derived": {
            "density_altitude_ft": density_alt,
            "air_density_slugft3": rho,
            "vs1g_kts": stall,
            "g_limit_positive": g_pos,
            "g_limit_negative": g_neg,
            "hp_at_altitude": hp,
            "corner_velocity_kts": corner_v,
            "cl_max": cl_max,
        },
        "envelope": envelope,
    }


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
def test_envelope_snapshot(scenario, snapshot):
    """Compute the envelope physics for one scenario and compare to its
    stored snapshot. Run `pytest --snapshot-update` to regenerate after a
    deliberate physics change.
    """
    result = _compute_envelope(scenario)
    serialized = json.dumps(_round_floats(result), indent=2, sort_keys=True)
    snapshot.assert_match(serialized, f"{scenario['id']}.json")


def test_scenario_definitions_complete():
    """Self-check: every scenario points to a file that exists and to a
    flap_config / category that the JSON actually has.
    """
    for s in SCENARIOS:
        ac_path = DATA_DIR / s["aircraft_file"]
        assert ac_path.exists(), f"Missing aircraft JSON: {ac_path}"
        with ac_path.open() as fh:
            ac = json.load(fh)
        assert s["flap_config"] in ac["CL_max"], (
            f"{s['aircraft_file']} missing CL_max[{s['flap_config']}]"
        )
        assert s["category"] in ac["G_limits"], (
            f"{s['aircraft_file']} missing G_limits[{s['category']}]"
        )
        assert s["flap_config"] in ac["G_limits"][s["category"]], (
            f"{s['aircraft_file']} missing "
            f"G_limits[{s['category']}][{s['flap_config']}]"
        )
