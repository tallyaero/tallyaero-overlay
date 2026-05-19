"""Lazy 8 — Design Directive power consumption tests (Phase D1).

Lazy 8 is a cruise-power maneuver (design = 0.625). Off-design power
drifts the oscillation amplitude per:
    amplitude_factor = 1 + abs(power - 0.625) * 0.5
At design (0.625), amplitude_factor = 1.0 (no drift).
At 100%, factor ≈ 1.19 (wider swing).
At 30%, factor ≈ 1.16 (also wider — symmetric absolute deviation).
"""
import json
from pathlib import Path

from simulation.lazy_eight import simulate_lazy_eight


_REPO = Path(__file__).resolve().parent.parent
_AC = _REPO / "aircraft_data" / "Cessna_172P.json"


def _load_ac():
    with open(_AC) as f:
        return json.load(f)


_BASE = dict(
    entry_point={"lat": 30.5, "lon": -97.5},
    entry_heading_deg=90.0,
    first_turn_direction="left",
    entry_altitude_ft=3000.0,
    entry_ias_knots=100.0,
    max_bank_angle_deg=30.0,
    weight_lb=2300.0,
)


def test_design_power_amplitude_factor_one():
    ac = _load_ac()
    _, hover = simulate_lazy_eight(**_BASE, ac=ac, power_setting=0.625)
    last = hover[-1]
    assert last["amplitude_factor"] == 1.0
    assert last["power_setting"] == 0.625
    assert last["design_power"] == 0.625


def test_full_power_widens_amplitude():
    ac = _load_ac()
    _, hover = simulate_lazy_eight(**_BASE, ac=ac, power_setting=1.0)
    last = hover[-1]
    # |1.0 - 0.625| * 0.5 = 0.1875 → factor 1.1875
    assert abs(last["amplitude_factor"] - 1.188) < 0.01


def test_low_power_widens_amplitude_symmetrically():
    ac = _load_ac()
    _, hover = simulate_lazy_eight(**_BASE, ac=ac, power_setting=0.30)
    last = hover[-1]
    # |0.30 - 0.625| * 0.5 = 0.1625 → factor 1.1625
    assert abs(last["amplitude_factor"] - 1.163) < 0.01


def test_off_design_grows_altitude_swing():
    """Visual proof: amplitude_factor > 1 → larger alt swing in sim."""
    ac = _load_ac()
    _, hover_design = simulate_lazy_eight(**_BASE, ac=ac, power_setting=0.625)
    _, hover_full = simulate_lazy_eight(**_BASE, ac=ac, power_setting=1.0)
    design_swing = hover_design[-1]["altitude_swing_ft"]
    full_swing = hover_full[-1]["altitude_swing_ft"]
    assert full_swing > design_swing


def test_default_power_is_design():
    ac = _load_ac()
    _, hover = simulate_lazy_eight(**_BASE, ac=ac)
    last = hover[-1]
    assert last["power_setting"] == 0.625
    assert last["amplitude_factor"] == 1.0


def test_none_power_falls_back_to_design():
    ac = _load_ac()
    _, hover = simulate_lazy_eight(**_BASE, ac=ac, power_setting=None)
    last = hover[-1]
    assert last["power_setting"] == 0.625


def test_final_metadata_is_present():
    ac = _load_ac()
    _, hover = simulate_lazy_eight(**_BASE, ac=ac, power_setting=0.85)
    last = hover[-1]
    assert "power_setting" in last
    assert "design_power" in last
    assert "amplitude_factor" in last
    assert "altitude_swing_ft" in last
    assert last["design_power"] == 0.625
