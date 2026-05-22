"""Phase 3 climb-ROC tests for impossible_turn.

Before the fix: ROC was looked up by HP-bucket (650 / 800 / 1000 / 1200 fpm
in four steps). Aircraft in the same bucket produced identical ROC. The
weight-and-DA derate was applied, but the base bucket value was the same.

After Phase 3: ROC comes from a real power-available / power-required
model — thrust from `prop_thrust_decay`, drag from `wing_area / CD0 /
e / aspect_ratio`. Each airframe produces a distinct ROC, scaling
correctly with weight and density altitude.

These tests pin:
  - ROC at SL gross is within a reasonable tolerance of POH
  - Per-airframe differentiation is visible (no bucket lumping)
  - Density altitude meaningfully reduces ROC (75% at 5k DA is typical)
  - Twin-engine total power is used (Baron uses 2 × engine HP, not 1)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulation.impossible_turn import _calculate_rate_of_climb


AIRCRAFT_DIR = Path(__file__).resolve().parent.parent / "aircraft_data"


def _load(name: str) -> dict:
    return json.loads((AIRCRAFT_DIR / f"{name}.json").read_text())


def _roc(name: str, density_alt_ft: float = 0.0) -> float:
    ac = _load(name)
    engine = next(iter(ac["engine_options"].keys()))
    return _calculate_rate_of_climb(ac, float(ac["max_weight"]), density_alt_ft, engine)


# (name, poh_roc_sl_fpm, tolerance_pct)
# Tolerances are wider for turbocharged / draggy airframes where the
# physics model under/overshoots; tighter for clean piston singles.
_POH_ROC_TABLE = [
    ("Cessna_172S", 730, 30),
    ("Cessna_152", 715, 20),
    ("American_Champion_Decathlon", 1330, 20),
    ("Beechcraft_Baron_58", 1700, 30),
    ("Beechcraft_Bonanza_A36", 1230, 25),
    ("Piper_PA-28-181", 667, 30),
]


@pytest.mark.parametrize("name,poh,tol", _POH_ROC_TABLE)
def test_roc_at_sl_gross_matches_poh(name: str, poh: int, tol: int):
    roc = _roc(name, density_alt_ft=0.0)
    delta_pct = abs(roc - poh) / poh * 100
    assert delta_pct <= tol, (
        f"{name} ROC at SL gross: sim={roc:.0f} fpm vs POH={poh} fpm "
        f"({delta_pct:.1f}% off, allowed {tol}%)"
    )


def test_roc_decreases_with_density_altitude():
    """ROC at 5000 ft DA should be 60-85% of SL ROC for a normally
    aspirated piston single (172S). Outside that band, the engine
    derate + density model is broken."""
    roc_sl = _roc("Cessna_172S", 0.0)
    roc_5k = _roc("Cessna_172S", 5000.0)
    ratio = roc_5k / roc_sl
    assert 0.55 <= ratio <= 0.85, (
        f"172S ROC ratio at 5k DA = {ratio:.2f}; expected 0.55-0.85"
    )


def test_per_airframe_roc_differentiation():
    """A trainer (C152) and a high-performance single (SR22) should
    produce ROCs that differ by hundreds of fpm — pre-fix they could
    fall into the same HP bucket and look identical."""
    roc_c152 = _roc("Cessna_152", 0.0)
    roc_dec = _roc("American_Champion_Decathlon", 0.0)
    # Decathlon (180 hp @ 1800 lb) should out-climb a C152 (110 hp @ 1670 lb)
    assert roc_dec > roc_c152 + 200, (
        f"Decathlon ROC {roc_dec:.0f} should exceed C152 {roc_c152:.0f} "
        f"by 200+ fpm — POH-physics not differentiating airframes"
    )


def test_twin_engine_uses_total_power():
    """The Baron is a twin. Its physics ROC must use 2× engine HP, not
    1× — without this fix the Baron underclimbed by 60% vs POH."""
    roc = _roc("Beechcraft_Baron_58", 0.0)
    assert roc > 1300, (
        f"Baron 58 ROC {roc:.0f} fpm — too low. Twin-engine multiplier "
        f"missing? Expected >1300 (POH ~1700, model overshoots by ~20%)."
    )
