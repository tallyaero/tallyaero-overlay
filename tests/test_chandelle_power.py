"""Chandelle — Design Directive power consumption tests (Phase D1).

Chandelle is a full-power maneuver (design = 1.0). At design power the
airplane climbs through a full 180° heading change. Below 50% power
the airplane cannot complete the 180° — the sim truncates the path
proportionally and surfaces `failure_reason` on the last hover point.
"""
import json
from pathlib import Path

from simulation.chandelle import simulate_chandelle


_REPO = Path(__file__).resolve().parent.parent
_AC = _REPO / "aircraft_data" / "Cessna_172P.json"


def _load_ac():
    with open(_AC) as f:
        return json.load(f)


_BASE = dict(
    entry_point={"lat": 30.5, "lon": -97.5},
    entry_heading_deg=90.0,
    turn_direction="left",
    entry_altitude_ft=3000.0,
    entry_ias_knots=100.0,
    bank_angle_deg=30.0,
    weight_lb=2300.0,
)


def test_design_power_completes_180():
    ac = _load_ac()
    path, hover = simulate_chandelle(**_BASE, ac=ac, power_setting=1.0)
    last = hover[-1]
    assert last["max_progress_deg"] == 180.0
    assert "failure_reason" not in last
    # Exit heading should be ~270° (entry 90° + 180°, left turn)
    assert abs(last["heading"] - 270.0) < 5.0


def test_low_power_truncates_path():
    ac = _load_ac()
    path, hover = simulate_chandelle(**_BASE, ac=ac, power_setting=0.30)
    last = hover[-1]
    # 30% / 50% = 0.6 → 108° max progress
    assert last["max_progress_deg"] == 108.0
    assert "failure_reason" in last
    assert "Insufficient power" in last["failure_reason"]


def test_half_power_just_completes():
    """At exactly 50%, max_progress_deg should hit 180° (boundary)."""
    ac = _load_ac()
    path, hover = simulate_chandelle(**_BASE, ac=ac, power_setting=0.50)
    last = hover[-1]
    assert last["max_progress_deg"] == 180.0
    assert "failure_reason" not in last


def test_below_25_clamps_to_min_30deg():
    ac = _load_ac()
    path, hover = simulate_chandelle(**_BASE, ac=ac, power_setting=0.01)
    last = hover[-1]
    # 1% / 50% = 0.02 → 3.6°, clamped to 30°
    assert last["max_progress_deg"] == 30.0
    assert "failure_reason" in last


def test_default_power_is_full():
    """Omitting power_setting yields design (full power)."""
    ac = _load_ac()
    path, hover = simulate_chandelle(**_BASE, ac=ac)
    last = hover[-1]
    assert last["power_setting"] == 1.0
    assert last["design_power"] == 1.0
    assert "failure_reason" not in last


def test_full_power_climbs_more_than_half():
    """Higher power → more altitude gain (excess HP → climb)."""
    ac = _load_ac()
    _, hover_full = simulate_chandelle(**_BASE, ac=ac, power_setting=1.0)
    _, hover_half = simulate_chandelle(**_BASE, ac=ac, power_setting=0.55)
    full_gain = hover_full[-1]["altitude_gain_ft"]
    half_gain = hover_half[-1]["altitude_gain_ft"]
    assert full_gain > half_gain


def test_final_metadata_is_present():
    ac = _load_ac()
    _, hover = simulate_chandelle(**_BASE, ac=ac, power_setting=0.85)
    last = hover[-1]
    assert "power_setting" in last
    assert "design_power" in last
    assert "max_progress_deg" in last
    assert "altitude_gain_ft" in last
    assert last["design_power"] == 1.0
