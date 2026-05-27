"""
Dynamic Vmca calculation.

Computes Vmca (air minimum control speed, critical engine inoperative) across
a range of bank angles, adjusted from the published Vmca for current power,
weight, CG, prop condition, and density altitude.

Physics basis:
- Vmc is the minimum speed at which directional control can be maintained with
  the critical engine inoperative and max power on the operating engine.
- Published Vmc is typically certified at: max gross weight, most aft CG,
  sea level, 5° bank into the dead engine, critical engine windmilling.

Modifier ranges (recalibrated Phase 5R-3, 2026-05-13):
- Power: 0.70 – 1.00× (max takeoff power → certified condition = 1.0)
- Weight: 0.85 – 1.15× (heavier than reference is rare but supported)
- CG: 0.96 (forward) – 1.00 (aft = certified condition)
- Density altitude: 0.85 – 1.00× (sea level = certified condition)
- Prop condition: 0.88 (feathered) – 1.00 (windmilling = certified condition)
- Bank: 1.00 at +5° (certified), rises both sides

Calibration check: at certified conditions (max weight, aft CG, SL/std day,
max power, windmilling, 5° bank), all modifiers = 1.00 and the function
returns exactly `published_vmca`. Verified by tests in test_vmc.py.

This module is canonical and identical to the copy in tallyaero_overlay_tools —
see Shared Asset Ledger in EM_DIAGRAM_EXECUTION_PLAN.md.
"""

from __future__ import annotations

import numpy as np

from .calculations import KTS_TO_MPH, LAPSE_RATE_K_FT, TEMP_SL_C

DEFAULT_BANK_ANGLES_DEG = np.linspace(-5, 10, 50)


def calculate_vmca(
    published_vmca,
    power_fraction,
    total_weight,
    reference_weight,
    cg,
    cg_range,
    prop_condition,
    pressure_altitude: float = 0,
    oat_c: float = 15,
    unit: str = "KIAS",
    bank_angles_deg: np.ndarray = DEFAULT_BANK_ANGLES_DEG,
):
    """Return (bank_angles, vmca_values) for the given conditions.

    See module docstring for the physics basis and modifier ranges.

    Args:
        published_vmca: Published Vmca speed (KIAS) at certified reference
            conditions. May be a number, or a dict like {"clean_up": 76, ...} —
            the latter is dereferenced to its `clean_up` entry (or first value).
        power_fraction: Power setting on operating engine (0..1).
        total_weight: Current gross weight (lb).
        reference_weight: Weight at which `published_vmca` was published
            (typically max gross).
        cg: Current CG position (in same units as `cg_range`).
        cg_range: [forward_limit, aft_limit] CG range.
        prop_condition: "feathered" | "stationary" | "windmilling".
        pressure_altitude: Pressure altitude (ft).
        oat_c: Outside air temperature (°C).
        unit: Output unit — "KIAS" (default) or "MPH".
        bank_angles_deg: Bank angles (deg) at which to evaluate Vmca.

    Returns:
        (bank_angles_deg, vmca_vals): bank angle array and the corresponding
        Vmca speed array. Returns NaN values when published_vmca is missing.
    """
    # Dereference dict-shaped published_vmca (twins store per-config values).
    if isinstance(published_vmca, dict):
        published_vmca = (
            published_vmca.get("clean_up")
            or next(iter(published_vmca.values()), None)
        )

    if not isinstance(published_vmca, (int, float)):
        return bank_angles_deg, np.full_like(bank_angles_deg, np.nan)

    # Density altitude
    isa_temp_c = TEMP_SL_C - (pressure_altitude * LAPSE_RATE_K_FT)
    temp_dev_c = oat_c - isa_temp_c
    density_altitude = pressure_altitude + (120 * temp_dev_c)

    modifiers = np.ones_like(bank_angles_deg, dtype=float)

    # Power: lower power → less asymmetric thrust → lower Vmc.
    power_mod = 0.70 + 0.30 * power_fraction
    modifiers *= np.clip(power_mod, 0.70, 1.05)

    # Weight: lighter = less yaw inertia = higher Vmc.
    weight_ratio = total_weight / reference_weight
    weight_factor = 1.0 + 0.15 * (1.0 - weight_ratio)
    modifiers *= np.clip(weight_factor, 0.90, 1.15)

    # CG: aft CG = shorter rudder moment arm = higher Vmc (published condition).
    cg_span = cg_range[1] - cg_range[0]
    if cg_span > 0:
        cg_percent = (cg - cg_range[0]) / cg_span
        cg_factor = 0.96 + 0.04 * cg_percent
    else:
        cg_factor = 1.0
    modifiers *= cg_factor

    # Density altitude: higher DA → less asymmetric power → lower Vmc.
    da_factor = 1.0 - (density_altitude / 30000.0) * 0.10
    modifiers *= np.clip(da_factor, 0.85, 1.0)

    # Prop condition: published Vmca is certified WINDMILLING (per 14 CFR
    # 23.149), so windmilling = 1.0. Stationary reduces drag modestly;
    # feathered reduces drag substantially (Kershner/Lowery cite 10-15%
    # Vmc reduction when feathered).
    prop_factors = {
        "windmilling": 1.00,
        "stationary":  0.96,
        "feathered":   0.88,
    }
    modifiers *= prop_factors.get(prop_condition, 1.0)

    # Bank angle: published Vmca is certified at 5° bank INTO the operating
    # engine (14 CFR 23.149), so bank=5° = 1.0. At 0° bank you've lost the
    # rudder/bank assist; at negative bank (toward dead engine) Vmc rises
    # steeply; beyond +5° load factor begins to drive Vmc back up again.
    bank_mod = np.ones_like(bank_angles_deg, dtype=float)
    for i, bank in enumerate(bank_angles_deg):
        if bank < 0:
            # Banking AWAY from operating engine — no rudder aid + sideslip
            bank_mod[i] = 1.04 + 0.03 * abs(bank)        # 1.04 @ 0-, 1.19 @ -5°
        elif 0 <= bank < 5:
            # Less than certified bank — small Vmc penalty linear to 5°
            bank_mod[i] = 1.05 - 0.01 * bank             # 1.05 @ 0°, 1.00 @ 5°
        else:
            # 5° to 90°: Vmc rises with load factor in the turn
            bank_mod[i] = 1.0 + 0.005 * (bank - 5)       # 1.00 @ 5°, 1.425 @ 90°

    modifiers *= bank_mod

    vmca_vals = published_vmca * modifiers

    if unit == "MPH":
        vmca_vals = vmca_vals * KTS_TO_MPH

    return bank_angles_deg, vmca_vals
