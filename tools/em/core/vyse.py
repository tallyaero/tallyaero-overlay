"""
Dynamic Vyse calculation.

Computes Vyse (best single-engine rate of climb speed) adjusted from a
published baseline for current weight, density altitude, gear, flap config,
and prop condition.

Physics basis:
- Vyse is the IAS that maximizes excess thrust power with one engine inop.
- Weight affects required lift and thus optimal L/D point.
- Density altitude affects available power from operating engine.
- Gear and flaps shift the drag curve, moving the optimal IAS.

Modifier ranges (recalibrated Phase 5R-4, 2026-05-13):
- Weight: 0.92 – 1.08× (reference weight = 1.00)
- Density altitude: 1.00 – 1.03× (sea level = certified condition)
- Gear: 1.00 (up = certified) – 1.04 (down)
- Flaps: 1.00 (clean = certified) – 1.05 (landing)
- Prop condition: 1.00 (feathered = certified) – 1.07 (windmilling)

Calibration check: at certified conditions (reference weight, sea level /
std day, gear up, clean flaps, prop feathered), all modifiers = 1.00 and
the function returns exactly `published_vyse`. Verified by test_vyse.py.

This module is canonical and identical to the copy in tallyaero_overlay_tools —
see Shared Asset Ledger in EM_DIAGRAM_EXECUTION_PLAN.md.
"""

from __future__ import annotations

import numpy as np

from .calculations import LAPSE_RATE_K_FT, TEMP_SL_C


def calculate_dynamic_vyse(
    published_vyse,
    total_weight,
    reference_weight,
    pressure_altitude: float = 0,
    oat_c: float = 15,
    gear_position: str = "up",
    flap_config: str = "clean",
    prop_condition: str = "feathered",
):
    """Return adjusted Vyse (KIAS).

    See module docstring for the physics basis.

    Args:
        published_vyse: Baseline Vyse (KIAS) at certified reference conditions.
        total_weight: Current gross weight (lb).
        reference_weight: Weight at which `published_vyse` was published.
        pressure_altitude: Pressure altitude (ft).
        oat_c: Outside air temperature (°C).
        gear_position: "up" | "down".
        flap_config: "clean" | "takeoff" | "landing".
        prop_condition: "feathered" | "stationary" | "windmilling".

    Returns:
        Adjusted Vyse in KIAS.
    """
    isa_temp_c = TEMP_SL_C - (pressure_altitude * LAPSE_RATE_K_FT)
    temp_dev_c = oat_c - isa_temp_c
    density_altitude = pressure_altitude + (120 * temp_dev_c)

    # Weight
    weight_ratio = total_weight / reference_weight
    weight_factor = 1.0 + 0.5 * (weight_ratio - 1.0)
    weight_factor = np.clip(weight_factor, 0.92, 1.08)

    # Density altitude
    da_factor = 1.0 + (density_altitude / 50000.0) * 0.05
    da_factor = np.clip(da_factor, 1.0, 1.03)

    # Gear
    gear_factor = 1.04 if gear_position == "down" else 1.0

    # Flap
    flap_factors = {
        "clean": 1.00,
        "takeoff": 1.02,
        "landing": 1.05,
    }
    config_factor = flap_factors.get(flap_config, 1.00)

    # Prop condition — published Vyse is certified with the failed engine's
    # prop FEATHERED (max climb performance), so feathered = 1.0. Windmilling
    # adds drag, shifting optimal climb speed up; stationary is in between.
    prop_factors = {
        "feathered":   1.00,
        "stationary":  1.04,
        "windmilling": 1.07,
    }
    prop_factor = prop_factors.get(prop_condition, 1.0)

    return (
        published_vyse
        * weight_factor
        * da_factor
        * gear_factor
        * config_factor
        * prop_factor
    )
