"""Steep Turn — Design Directive power consumption tests (Phase D1).

Design power for a level Steep Turn is 0.70. Off-design power produces
altitude drift at +/- 200 fpm per 100% deviation from design.

At design (0.70), altitude is constant: vs = 0 fpm, alt unchanged.
At 100%, altitude climbs at +60 fpm.
At 30%, altitude descends at -80 fpm.
The final hover point carries `power_setting`, `design_power`, and
`altitude_change_ft` so the callback can render a verdict.
"""
from simulation.steep_turn import simulate_steep_turn


_BASE = dict(
    entry_point={"lat": 30.5, "lon": -97.5},
    entry_heading_deg=270.0,
    altitude_ft=3000.0,
    bank_angle_deg=45.0,
    turn_sequence="left",
    ias_knots=110.0,
    oat_c=15.0,
    altimeter_inhg=29.92,
    wind_dir_deg=0.0,
    wind_speed_kt=0.0,
)


def test_design_power_holds_altitude_constant():
    path, hover = simulate_steep_turn(**_BASE, power_setting=0.70)
    assert len(hover) > 10
    assert hover[-1]["altitude_change_ft"] == 0.0
    assert hover[-1]["altitude_drift_fpm"] == 0.0
    alts = [pt["alt"] for pt in hover]
    assert max(alts) == min(alts), "altitude must be constant at design power"


def test_full_power_climbs():
    path, hover = simulate_steep_turn(**_BASE, power_setting=1.00)
    assert hover[-1]["altitude_drift_fpm"] == 60.0  # (1.00 - 0.70) * 200
    assert hover[-1]["altitude_change_ft"] > 0
    assert hover[-1]["alt"] > 3000.0


def test_low_power_descends():
    path, hover = simulate_steep_turn(**_BASE, power_setting=0.30)
    assert hover[-1]["altitude_drift_fpm"] == -80.0  # (0.30 - 0.70) * 200
    assert hover[-1]["altitude_change_ft"] < 0
    assert hover[-1]["alt"] < 3000.0


def test_default_power_is_design():
    """No power_setting passed → default 0.70 → zero drift."""
    path, hover = simulate_steep_turn(**_BASE)
    assert hover[-1]["altitude_drift_fpm"] == 0.0


def test_power_clamps_to_unit_range():
    path_neg, hover_neg = simulate_steep_turn(**_BASE, power_setting=-0.5)
    assert hover_neg[-1]["power_setting"] == 0.0
    path_hi, hover_hi = simulate_steep_turn(**_BASE, power_setting=2.0)
    assert hover_hi[-1]["power_setting"] == 1.0


def test_none_power_falls_back_to_design():
    path, hover = simulate_steep_turn(**_BASE, power_setting=None)
    assert hover[-1]["power_setting"] == 0.7
    assert hover[-1]["altitude_drift_fpm"] == 0.0


def test_final_metadata_is_present():
    path, hover = simulate_steep_turn(**_BASE, power_setting=0.85)
    last = hover[-1]
    assert "power_setting" in last
    assert "design_power" in last
    assert "altitude_change_ft" in last
    assert "altitude_drift_fpm" in last
    assert last["design_power"] == 0.70
